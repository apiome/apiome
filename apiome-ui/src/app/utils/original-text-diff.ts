/**
 * Line diff of two stored originals, for the compare view's **Originals** mode (COA-5.7, #7083).
 *
 * The originals can be large (the acceptance bar is a 20 MB diff that does not freeze the tab), so
 * the diff is built in three steps that keep the main thread responsive:
 *
 * 1. **Trim** the lines both files share at the start and at the end. Two revisions of one spec
 *    usually differ in a small middle, so this is most of the work, done in one linear pass.
 * 2. **Diff the middle** with jsdiff's `diffArrays` in its asynchronous mode, which yields to the
 *    event loop between steps. A middle too different to finish within {@link DiffOptions.timeoutMs}
 *    is shown as one removed block and one added block, with `approximate: true`.
 * 3. **Collapse** unchanged runs longer than twice the context into one `skip` row, so the rows a
 *    virtualized list mounts stay proportional to the change, not to the file.
 */

import { diffArrays } from 'diff';

/** One row of the unified diff. */
export type OriginalDiffRow =
  | { kind: 'context' | 'added' | 'removed'; text: string; leftLine: number | null; rightLine: number | null }
  | { kind: 'skip'; count: number; leftLine: number; rightLine: number };

/** The diff of two originals. */
export interface OriginalDiff {
  /** Rows top to bottom, unchanged runs collapsed to `skip` rows. */
  rows: OriginalDiffRow[];
  /** Lines only in the right (compare-to) file. */
  added: number;
  /** Lines only in the left (base) file. */
  removed: number;
  /** True when the files are byte-for-byte equal. */
  identical: boolean;
  /** True when the middle could not be diffed in time and is shown as replaced wholesale. */
  approximate: boolean;
}

export interface DiffOptions {
  /** Unchanged lines kept around each change (default 3). */
  context?: number;
  /** Longest the middle may take to diff, in ms, before it is shown as replaced (default 15 s). */
  timeoutMs?: number;
  /** Aborts the diff; the promise then rejects with an `AbortError`. */
  signal?: AbortSignal;
}

/** A line as diffed: its text and its 1-based number in its own file. */
interface Line {
  kind: 'context' | 'added' | 'removed';
  text: string;
  leftLine: number | null;
  rightLine: number | null;
}

/**
 * Split text into lines without their terminators (`\r\n`, `\n`). A final terminator adds no line.
 *
 * @param text The file's text.
 * @returns Its lines.
 */
export function splitLines(text: string): string[] {
  if (text === '') return [];
  const lines = text.split(/\r?\n/);
  if (lines[lines.length - 1] === '') lines.pop();
  return lines;
}

function abortError(): Error {
  const error = new Error('The diff was cancelled.');
  error.name = 'AbortError';
  return error;
}

/**
 * Diff two arrays of lines asynchronously, yielding between steps.
 *
 * @returns jsdiff's changes, or `undefined` when the timeout ran out first.
 */
function diffMiddle(
  left: string[],
  right: string[],
  timeoutMs: number,
): Promise<{ value: string[]; added?: boolean; removed?: boolean }[] | undefined> {
  return new Promise((resolve) => {
    diffArrays(left, right, {
      timeout: timeoutMs,
      callback: (changes) => resolve(changes as { value: string[]; added?: boolean; removed?: boolean }[] | undefined),
    });
  });
}

/**
 * Collapse unchanged runs longer than `2 × context` into one `skip` row.
 *
 * @param lines Every line, in order.
 * @param context Unchanged lines kept beside each change.
 * @returns The rows to draw.
 */
export function collapseContext(lines: Line[], context: number): OriginalDiffRow[] {
  const rows: OriginalDiffRow[] = [];
  let index = 0;
  while (index < lines.length) {
    if (lines[index].kind !== 'context') {
      rows.push(lines[index]);
      index += 1;
      continue;
    }
    let end = index;
    while (end < lines.length && lines[end].kind === 'context') end += 1;
    const run = end - index;
    const keepHead = index === 0 ? 0 : context;
    const keepTail = end === lines.length ? 0 : context;
    if (run <= keepHead + keepTail + 1) {
      for (let i = index; i < end; i += 1) rows.push(lines[i]);
    } else {
      for (let i = index; i < index + keepHead; i += 1) rows.push(lines[i]);
      const first = lines[index + keepHead];
      rows.push({
        kind: 'skip',
        count: run - keepHead - keepTail,
        leftLine: first.leftLine ?? 0,
        rightLine: first.rightLine ?? 0,
      });
      for (let i = end - keepTail; i < end; i += 1) rows.push(lines[i]);
    }
    index = end;
  }
  return rows;
}

/**
 * Diff two originals line by line without blocking the page.
 *
 * @param leftText The base file.
 * @param rightText The compare-to file.
 * @param options Context, timeout and an abort signal.
 * @returns The rows and counts.
 */
export async function diffOriginals(leftText: string, rightText: string, options: DiffOptions = {}): Promise<OriginalDiff> {
  const context = Math.max(0, options.context ?? 3);
  const timeoutMs = options.timeoutMs ?? 15_000;
  const { signal } = options;
  if (signal?.aborted) throw abortError();
  if (leftText === rightText) {
    const lines = splitLines(leftText).map(
      (text, i): Line => ({ kind: 'context', text, leftLine: i + 1, rightLine: i + 1 }),
    );
    return { rows: collapseContext(lines, context), added: 0, removed: 0, identical: true, approximate: false };
  }

  const left = splitLines(leftText);
  const right = splitLines(rightText);
  let head = 0;
  const shortest = Math.min(left.length, right.length);
  while (head < shortest && left[head] === right[head]) head += 1;
  let tail = 0;
  while (tail < shortest - head && left[left.length - 1 - tail] === right[right.length - 1 - tail]) tail += 1;

  const leftMiddle = left.slice(head, left.length - tail);
  const rightMiddle = right.slice(head, right.length - tail);
  const changes = await diffMiddle(leftMiddle, rightMiddle, timeoutMs);
  if (signal?.aborted) throw abortError();
  const approximate = changes === undefined;
  const blocks = changes ?? [
    { value: leftMiddle, removed: true },
    { value: rightMiddle, added: true },
  ];

  const lines: Line[] = [];
  for (let i = 0; i < head; i += 1) lines.push({ kind: 'context', text: left[i], leftLine: i + 1, rightLine: i + 1 });
  let leftNo = head + 1;
  let rightNo = head + 1;
  let added = 0;
  let removed = 0;
  for (const block of blocks) {
    for (const text of block.value) {
      if (block.added) {
        lines.push({ kind: 'added', text, leftLine: null, rightLine: rightNo });
        rightNo += 1;
        added += 1;
      } else if (block.removed) {
        lines.push({ kind: 'removed', text, leftLine: leftNo, rightLine: null });
        leftNo += 1;
        removed += 1;
      } else {
        lines.push({ kind: 'context', text, leftLine: leftNo, rightLine: rightNo });
        leftNo += 1;
        rightNo += 1;
      }
    }
  }
  for (let i = left.length - tail; i < left.length; i += 1) {
    lines.push({ kind: 'context', text: left[i], leftLine: leftNo, rightLine: rightNo });
    leftNo += 1;
    rightNo += 1;
  }
  return { rows: collapseContext(lines, context), added, removed, identical: false, approximate };
}
