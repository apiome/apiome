import { describe, it, expect } from '@jest/globals';
import {
  resolveActiveBranchForRevision,
  sortBranchesForPicker,
} from '@lib/studio-branch-resolve';
import type { VersionBranchRow } from '@/app/components/ade/version-dialogs/types';

describe('resolveActiveBranchForRevision', () => {
  it('returns null when no branch tip matches', () => {
    expect(
      resolveActiveBranchForRevision('rev-1', [
        { id: 'b1', name: 'a', tip_version_id: 'other' },
      ])
    ).toBeNull();
  });

  it('returns the matching branch when unique', () => {
    const main: VersionBranchRow = { id: 'b-main', name: 'main', tip_version_id: 'rev-x', is_default: true };
    expect(resolveActiveBranchForRevision('rev-x', [main])).toEqual(main);
  });

  it('prefers is_default when multiple branches share a tip', () => {
    const a: VersionBranchRow = { id: 'b1', name: 'feature', tip_version_id: 'rev-x' };
    const b: VersionBranchRow = { id: 'b2', name: 'main', tip_version_id: 'rev-x', is_default: true };
    expect(resolveActiveBranchForRevision('rev-x', [a, b])).toEqual(b);
  });
});

describe('sortBranchesForPicker', () => {
  it('orders default first, then name', () => {
    const rows: VersionBranchRow[] = [
      { id: 'z', name: 'zebra', tip_version_id: '1' },
      { id: 'm', name: 'main', tip_version_id: '2', is_default: true },
      { id: 'a', name: 'aardvark', tip_version_id: '3' },
    ];
    expect(sortBranchesForPicker(rows).map((b) => b.name)).toEqual(['main', 'aardvark', 'zebra']);
  });
});
