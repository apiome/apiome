/**
 * Line diff model for before/after views (UXE-1.3).
 *
 * "Beautiful diffs" is named as a source of delight in §27.3, and §28.2 and
 * §28.3 both need before/after comparison. The shared piece is the *model*: a
 * list of typed lines plus a summary sentence. Rendering differs by surface;
 * the meaning must not.
 *
 * The summary matters as much as the lines. A visual diff that only exists as
 * red and green rows fails §27.4's no-colour-only rule, so every line also
 * carries a symbolic marker and the whole diff carries a countable sentence.
 */

/** Role of one line in a diff. */
export type AuthoringDiffLineKind = 'added' | 'removed' | 'context';

/** One rendered diff line. */
export type AuthoringDiffLine = {
  kind: AuthoringDiffLineKind;
  text: string;
  /** 1-based line number in the "before" text, absent for added lines. */
  beforeLine?: number;
  /** 1-based line number in the "after" text, absent for removed lines. */
  afterLine?: number;
};

/** Symbolic marker per line kind, so the diff survives greyscale printing. */
export const AUTHORING_DIFF_MARKERS: Record<AuthoringDiffLineKind, string> = {
  added: '+',
  removed: '-',
  context: ' ',
};

/** Spoken name per line kind, used for the accessible line prefix. */
const KIND_NAMES: Record<AuthoringDiffLineKind, string> = {
  added: 'Added',
  removed: 'Removed',
  context: 'Unchanged',
};

/**
 * Spoken name for a diff line kind.
 *
 * @param kind - Line kind.
 * @returns `Added`, `Removed` or `Unchanged`.
 */
export function describeAuthoringDiffKind(kind: AuthoringDiffLineKind): string {
  return KIND_NAMES[kind];
}

/**
 * Build a line diff between two texts.
 *
 * Uses a longest-common-subsequence walk, which is the standard choice for
 * prose and structured text alike: it keeps unchanged lines aligned instead of
 * reporting a wholesale replacement when one paragraph moved.
 *
 * The LCS table is O(n·m); callers pass documents, not catalogs. A guard caps
 * the input so an accidental 100k-line comparison degrades to a plain
 * replacement rather than freezing the interaction thread (§27.5).
 *
 * @param before - Previous text. Empty string means "did not exist".
 * @param after - New text. Empty string means "was deleted".
 * @param maxLines - Cap above which the diff degrades to whole-text replacement.
 * @returns Diff lines in display order.
 */
export function buildAuthoringDiff(
  before: string,
  after: string,
  maxLines = 2000
): AuthoringDiffLine[] {
  const beforeLines = splitLines(before);
  const afterLines = splitLines(after);

  if (beforeLines.length > maxLines || afterLines.length > maxLines) {
    return [
      ...beforeLines.map((text, i) => lineOf('removed', text, i + 1, undefined)),
      ...afterLines.map((text, i) => lineOf('added', text, undefined, i + 1)),
    ];
  }

  // lcs[i][j] = length of the longest common subsequence of the first i
  // "before" lines and the first j "after" lines.
  const lcs: number[][] = Array.from({ length: beforeLines.length + 1 }, () =>
    new Array<number>(afterLines.length + 1).fill(0)
  );

  for (let i = beforeLines.length - 1; i >= 0; i -= 1) {
    for (let j = afterLines.length - 1; j >= 0; j -= 1) {
      lcs[i][j] =
        beforeLines[i] === afterLines[j]
          ? lcs[i + 1][j + 1] + 1
          : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  const lines: AuthoringDiffLine[] = [];
  let i = 0;
  let j = 0;

  while (i < beforeLines.length && j < afterLines.length) {
    if (beforeLines[i] === afterLines[j]) {
      lines.push(lineOf('context', beforeLines[i], i + 1, j + 1));
      i += 1;
      j += 1;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      lines.push(lineOf('removed', beforeLines[i], i + 1, undefined));
      i += 1;
    } else {
      lines.push(lineOf('added', afterLines[j], undefined, j + 1));
      j += 1;
    }
  }

  while (i < beforeLines.length) {
    lines.push(lineOf('removed', beforeLines[i], i + 1, undefined));
    i += 1;
  }
  while (j < afterLines.length) {
    lines.push(lineOf('added', afterLines[j], undefined, j + 1));
    j += 1;
  }

  return lines;
}

/** Aggregate view of a diff. */
export type AuthoringDiffSummary = {
  added: number;
  removed: number;
  unchanged: number;
  /** True when the two texts are identical. */
  identical: boolean;
  /** Sentence to announce, e.g. `4 lines added, 2 removed.` */
  description: string;
};

/**
 * Summarise a diff.
 *
 * @param lines - Diff lines from {@link buildAuthoringDiff}.
 * @returns Counts and the sentence to announce.
 */
export function summarizeAuthoringDiff(lines: readonly AuthoringDiffLine[]): AuthoringDiffSummary {
  const added = lines.filter((line) => line.kind === 'added').length;
  const removed = lines.filter((line) => line.kind === 'removed').length;
  const unchanged = lines.filter((line) => line.kind === 'context').length;
  const identical = added === 0 && removed === 0;

  const parts: string[] = [];
  if (added > 0) parts.push(`${added} ${added === 1 ? 'line' : 'lines'} added`);
  if (removed > 0) parts.push(`${removed} ${removed === 1 ? 'line' : 'lines'} removed`);

  return {
    added,
    removed,
    unchanged,
    identical,
    description: identical ? 'No changes.' : `${parts.join(', ')}.`,
  };
}

/**
 * Split text into lines without inventing a trailing empty one.
 *
 * @param text - Text to split.
 * @returns Lines, or an empty array for empty input.
 */
function splitLines(text: string): string[] {
  if (text === '') return [];
  return text.replace(/\r\n/g, '\n').split('\n');
}

/**
 * Build one diff line.
 *
 * @param kind - Line role.
 * @param text - Line content.
 * @param beforeLine - 1-based line number in the previous text.
 * @param afterLine - 1-based line number in the new text.
 */
function lineOf(
  kind: AuthoringDiffLineKind,
  text: string,
  beforeLine: number | undefined,
  afterLine: number | undefined
): AuthoringDiffLine {
  return { kind, text, beforeLine, afterLine };
}
