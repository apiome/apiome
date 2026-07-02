/**
 * Unit tests for the catalog version timeline helpers (MFI-25.7, #4092).
 *
 * These pin the "tick any two revisions to diff" selection logic and the diff deep-link the Versions
 * tab routes to: newest-first ordering, the two-item selection cap, and that the older revision maps
 * to `compareBase` / the newer to `compareHead` regardless of the order the two were ticked.
 */

import {
  buildVersionDiffHref,
  canDiffRevisions,
  MAX_DIFF_SELECTION,
  orderRevisionPairOldToNew,
  sortRevisionsNewestFirst,
  toggleRevisionSelection,
  type CatalogVersionRevision,
} from '../src/app/utils/catalog-versions-timeline';

const REV = (id: string, version_id: string, created_at: string): CatalogVersionRevision => ({
  id,
  version_id,
  created_at,
});

// Three revisions, deliberately supplied out of order.
const R1 = REV('rev-1', '1.0.0', '2026-01-01T00:00:00.000Z');
const R2 = REV('rev-2', '1.2.0', '2026-02-01T00:00:00.000Z');
const R3 = REV('rev-3', '1.10.0', '2026-03-01T00:00:00.000Z');
const ALL = [R2, R1, R3];

describe('sortRevisionsNewestFirst', () => {
  it('orders revisions newest-first by created_at and does not mutate the input', () => {
    const input = [...ALL];
    const sorted = sortRevisionsNewestFirst(input);
    expect(sorted.map((r) => r.id)).toEqual(['rev-3', 'rev-2', 'rev-1']);
    // Input array untouched (pure).
    expect(input).toEqual([R2, R1, R3]);
  });

  it('breaks created_at ties with a numeric-aware version_id compare (1.10.0 > 1.2.0)', () => {
    const t = '2026-05-01T00:00:00.000Z';
    const sorted = sortRevisionsNewestFirst([REV('a', '1.2.0', t), REV('b', '1.10.0', t)]);
    expect(sorted.map((r) => r.id)).toEqual(['b', 'a']);
  });
});

describe('toggleRevisionSelection', () => {
  it('adds an unselected id', () => {
    expect(toggleRevisionSelection([], 'rev-1')).toEqual(['rev-1']);
    expect(toggleRevisionSelection(['rev-1'], 'rev-2')).toEqual(['rev-1', 'rev-2']);
  });

  it('removes an already-selected id', () => {
    expect(toggleRevisionSelection(['rev-1', 'rev-2'], 'rev-1')).toEqual(['rev-2']);
  });

  it('caps the selection at two — a third tick is ignored', () => {
    expect(toggleRevisionSelection(['rev-1', 'rev-2'], 'rev-3')).toEqual(['rev-1', 'rev-2']);
  });

  it('never mutates the input array', () => {
    const input = ['rev-1'];
    toggleRevisionSelection(input, 'rev-2');
    expect(input).toEqual(['rev-1']);
  });
});

describe('canDiffRevisions', () => {
  it('is true only when exactly two are selected', () => {
    expect(canDiffRevisions([])).toBe(false);
    expect(canDiffRevisions(['rev-1'])).toBe(false);
    expect(canDiffRevisions(['rev-1', 'rev-2'])).toBe(true);
    expect(MAX_DIFF_SELECTION).toBe(2);
  });
});

describe('orderRevisionPairOldToNew', () => {
  it('returns the older revision as base and the newer as head', () => {
    const pair = orderRevisionPairOldToNew(['rev-1', 'rev-3'], ALL);
    expect(pair?.base.id).toBe('rev-1');
    expect(pair?.head.id).toBe('rev-3');
  });

  it('normalizes order regardless of which was ticked first', () => {
    const pair = orderRevisionPairOldToNew(['rev-3', 'rev-1'], ALL);
    expect(pair?.base.id).toBe('rev-1');
    expect(pair?.head.id).toBe('rev-3');
  });

  it('keeps the ticked order when timestamps are equal or unparseable', () => {
    const t = '2026-06-01T00:00:00.000Z';
    const pair = orderRevisionPairOldToNew(['a', 'b'], [REV('a', '1.0.0', t), REV('b', '2.0.0', t)]);
    expect(pair?.base.id).toBe('a');
    expect(pair?.head.id).toBe('b');
  });

  it('returns null unless exactly two distinct, resolvable revisions are selected', () => {
    expect(orderRevisionPairOldToNew(['rev-1'], ALL)).toBeNull();
    expect(orderRevisionPairOldToNew(['rev-1', 'rev-2', 'rev-3'], ALL)).toBeNull();
    expect(orderRevisionPairOldToNew(['rev-1', 'missing'], ALL)).toBeNull();
    expect(orderRevisionPairOldToNew(['rev-1', 'rev-1'], ALL)).toBeNull();
  });
});

describe('buildVersionDiffHref', () => {
  it('routes to the versions diff with the older revision as base and the newer as head', () => {
    const href = buildVersionDiffHref('proj-1', ['rev-1', 'rev-3'], ALL);
    expect(href).toBe(
      '/ade/dashboard/versions?projectId=proj-1&compareOpen=1&compareBase=rev-1&compareHead=rev-3',
    );
  });

  it('normalizes base/head order regardless of which was ticked first', () => {
    // rev-3 (newer) ticked before rev-1 (older) — base should still be the older rev-1.
    const href = buildVersionDiffHref('proj-1', ['rev-3', 'rev-1'], ALL);
    expect(href).toBe(
      '/ade/dashboard/versions?projectId=proj-1&compareOpen=1&compareBase=rev-1&compareHead=rev-3',
    );
  });

  it('encodes the project id', () => {
    const href = buildVersionDiffHref('a b/c', ['rev-1', 'rev-2'], ALL);
    expect(href).toContain('projectId=a+b%2Fc');
  });

  it('returns null unless exactly two distinct, resolvable revisions are selected', () => {
    expect(buildVersionDiffHref('proj-1', ['rev-1'], ALL)).toBeNull();
    expect(buildVersionDiffHref('proj-1', ['rev-1', 'rev-2', 'rev-3'], ALL)).toBeNull();
    expect(buildVersionDiffHref('proj-1', ['rev-1', 'missing'], ALL)).toBeNull();
    expect(buildVersionDiffHref('', ['rev-1', 'rev-2'], ALL)).toBeNull();
  });
});
