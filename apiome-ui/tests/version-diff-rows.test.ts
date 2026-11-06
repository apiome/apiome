/**
 * The Compare dialog's Diff View rows (`buildVersionDiffRows`): with "Show only changes"
 * (the default) each unchanged run keeps three lines of context beside a change and folds
 * the rest, so a 400K-line spec draws only what changed.
 */
import { diffLines } from 'diff';
import {
  buildVersionDiffRows,
  versionDiffFoldLabel,
  type VersionDiffRow,
} from '@/app/components/ade/version-dialogs/versionDialogsModel';

/** `n` numbered lines, `line1`…`lineN`, each ending in a newline. */
function numbered(n: number, from = 1): string {
  return Array.from({ length: n }, (_, i) => `line${from + i}\n`).join('');
}

/** The rows as short strings: `=text@no`, `+text@no`, `-text@no` or `…N`. */
function brief(rows: VersionDiffRow[]): string[] {
  return rows.map((row) => {
    if (row.kind === 'fold') return `…${row.hidden}`;
    const sigil = row.change === 'added' ? '+' : row.change === 'removed' ? '-' : '=';
    return `${sigil}${row.text}@${row.lineNo}`;
  });
}

const base = numbered(20);
const head = base.replace('line10\n', 'line10 changed\n');
const parts = diffLines(base, head);

describe('buildVersionDiffRows', () => {
  it('draws every line when changes-only is off', () => {
    const rows = buildVersionDiffRows(parts, 'unified', false);
    expect(rows).toHaveLength(21);
    expect(rows.every((row) => row.kind === 'line')).toBe(true);
  });

  it('folds the unchanged runs to three lines of context around the change', () => {
    expect(brief(buildVersionDiffRows(parts, 'unified', true))).toEqual([
      '…6',
      '=line7@7',
      '=line8@8',
      '=line9@9',
      '-line10@10',
      '+line10 changed@10',
      '=line11@11',
      '=line12@12',
      '=line13@13',
      '…7',
    ]);
  });

  it('numbers each side of the split view on its own side', () => {
    const left = brief(buildVersionDiffRows(parts, 'left', true));
    const right = brief(buildVersionDiffRows(parts, 'right', true));
    expect(left).toContain('-line10@10');
    expect(left.some((row) => row.startsWith('+'))).toBe(false);
    expect(right).toContain('+line10 changed@10');
    expect(right.some((row) => row.startsWith('-'))).toBe(false);
  });

  it('keeps line numbers right after an insertion shifts the compare side', () => {
    const inserted = diffLines(numbered(10), `${numbered(5)}new\n${numbered(5, 6)}`);
    const right = brief(buildVersionDiffRows(inserted, 'right', true));
    expect(right).toEqual(['…2', '=line3@3', '=line4@4', '=line5@5', '+new@6', '=line6@7', '=line7@8', '=line8@9', '…2']);
  });

  it('does not fold a run no longer than its context', () => {
    const short = diffLines('a\nb\nc\n', 'a\nB\nc\n');
    expect(buildVersionDiffRows(short, 'unified', true).some((row) => row.kind === 'fold')).toBe(false);
  });

  it('folds an identical pair into a single row', () => {
    expect(brief(buildVersionDiffRows(diffLines(base, base), 'unified', true))).toEqual(['…20']);
  });
});

describe('versionDiffFoldLabel', () => {
  it('counts the hidden lines', () => {
    expect(versionDiffFoldLabel(1)).toBe('⋯ 1 unchanged line');
    expect(versionDiffFoldLabel(401204)).toBe('⋯ 401,204 unchanged lines');
  });
});
