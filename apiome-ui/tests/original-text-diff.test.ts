/**
 * The Originals text diff (COA-5.7, #7083): line numbers, counts, collapsed context, the identical
 * short-circuit, cancellation, and that a large pair (20 MB) with a small change is diffed through
 * the shared head/tail trim with rows proportional to the change, not to the file.
 */

import { describe, expect, test } from '@jest/globals';
import { collapseContext, diffOriginals, splitLines } from '@/app/utils/original-text-diff';

describe('splitLines', () => {
  test('drops the final terminator and handles CRLF', () => {
    expect(splitLines('')).toEqual([]);
    expect(splitLines('a\nb\n')).toEqual(['a', 'b']);
    expect(splitLines('a\r\nb')).toEqual(['a', 'b']);
  });
});

describe('diffOriginals', () => {
  test('numbers both sides and counts the change', async () => {
    const diff = await diffOriginals('a\nb\nc\n', 'a\nB\nc\nd\n', { context: 3 });

    expect(diff.identical).toBe(false);
    expect(diff.approximate).toBe(false);
    expect(diff.added).toBe(2);
    expect(diff.removed).toBe(1);
    expect(diff.rows).toEqual([
      { kind: 'context', text: 'a', leftLine: 1, rightLine: 1 },
      { kind: 'removed', text: 'b', leftLine: 2, rightLine: null },
      { kind: 'added', text: 'B', leftLine: null, rightLine: 2 },
      { kind: 'context', text: 'c', leftLine: 3, rightLine: 3 },
      { kind: 'added', text: 'd', leftLine: null, rightLine: 4 },
    ]);
  });

  test('identical files collapse to one skip row', async () => {
    const text = Array.from({ length: 50 }, (_, i) => `line ${i}`).join('\n');

    const diff = await diffOriginals(text, text);

    expect(diff.identical).toBe(true);
    expect(diff.rows).toEqual([{ kind: 'skip', count: 50, leftLine: 1, rightLine: 1 }]);
  });

  test('a cancelled diff rejects with an AbortError', async () => {
    const controller = new AbortController();
    controller.abort();

    await expect(diffOriginals('a', 'b', { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' });
  });

  test('a 20 MB pair with one changed line stays small', async () => {
    const line = 'x'.repeat(99);
    const lines = Array.from({ length: 200_000 }, (_, i) => `${i}:${line}`);
    const left = lines.join('\n');
    const changed = [...lines];
    changed[100_000] = 'changed';
    const right = changed.join('\n');
    expect(left.length).toBeGreaterThan(20_000_000);

    const started = Date.now();
    const diff = await diffOriginals(left, right);

    expect(Date.now() - started).toBeLessThan(5_000);
    expect(diff.added).toBe(1);
    expect(diff.removed).toBe(1);
    expect(diff.rows.length).toBeLessThan(12);
    const removed = diff.rows.find((row) => row.kind === 'removed');
    expect(removed).toMatchObject({ leftLine: 100_001 });
  });
});

describe('collapseContext', () => {
  const ctx = (n: number) => ({ kind: 'context' as const, text: `c${n}`, leftLine: n, rightLine: n });

  test('keeps the context around a change and folds the rest', () => {
    const lines = [...Array.from({ length: 10 }, (_, i) => ctx(i + 1)), { kind: 'added' as const, text: '+', leftLine: null, rightLine: 11 }];

    const rows = collapseContext(lines, 2);

    expect(rows[0]).toEqual({ kind: 'skip', count: 8, leftLine: 1, rightLine: 1 });
    expect(rows.slice(1).map((row) => row.kind)).toEqual(['context', 'context', 'added']);
  });

  test('a short run between changes is kept whole', () => {
    const add = { kind: 'added' as const, text: '+', leftLine: null, rightLine: 1 };
    const rows = collapseContext([add, ctx(1), ctx(2), ctx(3), add], 1);

    expect(rows.map((row) => row.kind)).toEqual(['added', 'context', 'context', 'context', 'added']);
  });
});
