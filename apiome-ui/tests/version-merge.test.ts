import {
  classifyMergeDiff,
  filterMergeConflictRows,
  formatMergeConflictKinds,
  mergeConflictKindSignature,
  normalizeMergeConflictRows,
} from '../lib/version-merge';
import type { DiffSummary } from '../lib/schema-diff';

describe('classifyMergeDiff', () => {
  test('treats modified and removed paths as blocking conflicts', () => {
    const summary: DiffSummary = {
      added: [],
      removed: [{ type: 'removed', path: 'schemas.Gone', itemType: 'schema' }],
      modified: [{ type: 'modified', path: 'schemas.Pet', itemType: 'schema', changes: ['type'] }],
      unchanged: [],
    };
    const c = classifyMergeDiff(summary);
    expect(c.canAutoMerge).toBe(false);
    expect(c.conflictPaths).toContain('schemas.Pet');
    expect(c.conflictPaths).toContain('schemas.Gone');
  });

  test('extracts added schema names from added entries', () => {
    const summary: DiffSummary = {
      added: [{ type: 'added', path: 'schemas.NewThing', itemType: 'schema' }],
      removed: [],
      modified: [],
      unchanged: [],
    };
    const c = classifyMergeDiff(summary);
    expect(c.canAutoMerge).toBe(true);
    expect(c.addedSchemaNames).toContain('NewThing');
  });
});

describe('formatMergeConflictKinds', () => {
  test('labels known kinds and joins with separator', () => {
    expect(formatMergeConflictKinds(['twoWay', 'threeWay'])).toBe('Three-way · Two-way (divergent)');
    expect(formatMergeConflictKinds(['blend'])).toBe('Blend / materialize');
  });
});

describe('normalizeMergeConflictRows', () => {
  test('uses API conflicts when present', () => {
    const rows = normalizeMergeConflictRows(
      [{ path: 'schemas.A', kinds: ['threeWay'] }],
      ['schemas.B']
    );
    expect(rows).toEqual([{ path: 'schemas.A', kinds: ['threeWay'] }]);
  });

  test('falls back to conflict paths with twoWay', () => {
    expect(normalizeMergeConflictRows(undefined, ['schemas.X'])).toEqual([
      { path: 'schemas.X', kinds: ['twoWay'] },
    ]);
  });
});

describe('mergeConflictKindSignature', () => {
  test('is order-independent and de-duplicates', () => {
    expect(mergeConflictKindSignature(['twoWay', 'threeWay'])).toBe(mergeConflictKindSignature(['threeWay', 'twoWay', 'twoWay']));
  });
});

describe('filterMergeConflictRows', () => {
  const rows = [
    { path: 'schemas.Alpha', kinds: ['threeWay'] },
    { path: 'schemas.Beta', kinds: ['twoWay'] },
  ];

  test('filters by path substring', () => {
    expect(filterMergeConflictRows(rows, { pathContains: 'beta' })).toEqual([rows[1]]);
  });

  test('filters by kind signature', () => {
    const sig = mergeConflictKindSignature(['threeWay']);
    expect(filterMergeConflictRows(rows, { kindSignature: sig })).toEqual([rows[0]]);
  });
});
