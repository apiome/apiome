/**
 * Line diff construction and summary (UXE-1.3).
 *
 * The summary is the part that carries accessibility weight: a diff drawn only
 * in red and green fails roadmap section 27.4, so the countable sentence must
 * stay correct for every case the view can render.
 */

import {
  buildAuthoringDiff,
  summarizeAuthoringDiff,
  describeAuthoringDiffKind,
  AUTHORING_DIFF_MARKERS,
} from '../../lib/authoring/diff';

describe('buildAuthoringDiff', () => {
  it('reports no changes for identical text', () => {
    const lines = buildAuthoringDiff('a\nb', 'a\nb');

    expect(lines.every((line) => line.kind === 'context')).toBe(true);
  });

  it('keeps unchanged lines aligned instead of replacing the whole text', () => {
    const lines = buildAuthoringDiff('one\ntwo\nthree', 'one\nCHANGED\nthree');

    expect(lines.map((line) => line.kind)).toEqual(['context', 'removed', 'added', 'context']);
  });

  it('numbers lines against their own side only', () => {
    const [, removed, added] = buildAuthoringDiff('one\ntwo\nthree', 'one\nCHANGED\nthree');

    expect(removed).toMatchObject({ beforeLine: 2, afterLine: undefined });
    expect(added).toMatchObject({ beforeLine: undefined, afterLine: 2 });
  });

  it('treats empty before as a pure addition', () => {
    const lines = buildAuthoringDiff('', 'new line');

    expect(lines).toEqual([
      { kind: 'added', text: 'new line', beforeLine: undefined, afterLine: 1 },
    ]);
  });

  it('treats empty after as a pure deletion', () => {
    const lines = buildAuthoringDiff('old line', '');

    expect(lines).toEqual([
      { kind: 'removed', text: 'old line', beforeLine: 1, afterLine: undefined },
    ]);
  });

  it('produces nothing for two empty texts rather than one blank line', () => {
    expect(buildAuthoringDiff('', '')).toEqual([]);
  });

  it('normalises CRLF, so a line-ending change alone is not reported as a rewrite', () => {
    expect(summarizeAuthoringDiff(buildAuthoringDiff('a\r\nb', 'a\nb')).identical).toBe(true);
  });

  it('degrades to a whole-text replacement past the guard, rather than blocking the thread', () => {
    const long = Array.from({ length: 12 }, (_, i) => `line ${i}`).join('\n');
    const lines = buildAuthoringDiff(long, `${long}\nextra`, 5);

    // Every before line removed, every after line added — no LCS alignment.
    expect(lines.filter((line) => line.kind === 'context')).toHaveLength(0);
    expect(lines.filter((line) => line.kind === 'removed')).toHaveLength(12);
    expect(lines.filter((line) => line.kind === 'added')).toHaveLength(13);
  });
});

describe('summarizeAuthoringDiff', () => {
  it('counts each kind', () => {
    const summary = summarizeAuthoringDiff(buildAuthoringDiff('one\ntwo\nthree', 'one\nCHANGED\nthree'));

    expect(summary).toMatchObject({ added: 1, removed: 1, unchanged: 2, identical: false });
  });

  it('says so plainly when nothing changed', () => {
    expect(summarizeAuthoringDiff(buildAuthoringDiff('same', 'same'))).toMatchObject({
      identical: true,
      description: 'No changes.',
    });
  });

  it('uses singular wording for a single line', () => {
    expect(summarizeAuthoringDiff(buildAuthoringDiff('', 'one')).description).toBe('1 line added.');
  });

  it('uses plural wording for several lines', () => {
    expect(summarizeAuthoringDiff(buildAuthoringDiff('', 'a\nb')).description).toBe(
      '2 lines added.'
    );
  });

  it('names both directions when a line was replaced', () => {
    expect(summarizeAuthoringDiff(buildAuthoringDiff('a', 'b')).description).toBe(
      '1 line added, 1 line removed.'
    );
  });
});

describe('diff markers', () => {
  it('gives each kind a distinct symbolic marker, so colour is never the only cue', () => {
    expect(AUTHORING_DIFF_MARKERS.added).toBe('+');
    expect(AUTHORING_DIFF_MARKERS.removed).toBe('-');
    expect(new Set(Object.values(AUTHORING_DIFF_MARKERS)).size).toBe(3);
  });

  it('gives each kind a spoken name', () => {
    expect(describeAuthoringDiffKind('added')).toBe('Added');
    expect(describeAuthoringDiffKind('removed')).toBe('Removed');
    expect(describeAuthoringDiffKind('context')).toBe('Unchanged');
  });
});
