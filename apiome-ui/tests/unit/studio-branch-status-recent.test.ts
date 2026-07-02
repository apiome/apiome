import { describe, it, expect } from '@jest/globals';
import {
  collectRecentRevisionsOnLineage,
  type VersionLineageRow,
} from '@/app/ade/studio/lib/studio-branch-status-recent';

describe('collectRecentRevisionsOnLineage', () => {
  const versions: VersionLineageRow[] = [
    { id: 't3', parent_version_id: 't2', shortMessage: 'third' },
    { id: 't2', parent_version_id: 't1', shortMessage: 'second' },
    { id: 't1', parent_version_id: null, shortMessage: 'root' },
  ];

  it('walks parent_version_id from tip', () => {
    expect(collectRecentRevisionsOnLineage(versions, 't3', 5).map((r) => r.id)).toEqual(['t3', 't2', 't1']);
  });

  it('respects limit', () => {
    expect(collectRecentRevisionsOnLineage(versions, 't3', 2).map((r) => r.id)).toEqual(['t3', 't2']);
  });

  it('returns empty when tip missing', () => {
    expect(collectRecentRevisionsOnLineage(versions, 'nope', 3)).toEqual([]);
  });
});
