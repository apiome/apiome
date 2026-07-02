import { describe, test, expect } from '@jest/globals';
import {
  countAuthoredRevisionsTowardHead,
  isRemoteHeadAheadOfSelection,
} from '@/app/utils/studio-sync-indicators';

describe('studio-sync-indicators', () => {
  const u = 'user-1';
  const other = 'user-2';

  test('isRemoteHeadAheadOfSelection is false when selection is head', () => {
    const versions = [{ id: 'h', parent_version_id: null, creator_id: u }];
    expect(isRemoteHeadAheadOfSelection(versions, 'h')).toBe(false);
  });

  test('isRemoteHeadAheadOfSelection is true when a newer revision exists', () => {
    const versions = [
      { id: 'h', parent_version_id: 'o', creator_id: u },
      { id: 'o', parent_version_id: null, creator_id: u },
    ];
    expect(isRemoteHeadAheadOfSelection(versions, 'o')).toBe(true);
  });

  test('countAuthoredRevisionsTowardHead counts only authored nodes above selection', () => {
    const versions = [
      { id: 'v3', parent_version_id: 'v2', creator_id: u },
      { id: 'v2', parent_version_id: 'v1', creator_id: other },
      { id: 'v1', parent_version_id: null, creator_id: u },
    ];
    expect(countAuthoredRevisionsTowardHead(versions, 'v1', u)).toBe(1);
  });

  test('countAuthoredRevisionsTowardHead is zero at head', () => {
    const versions = [{ id: 'v3', parent_version_id: 'v2', creator_id: u }];
    expect(countAuthoredRevisionsTowardHead(versions, 'v3', u)).toBe(0);
  });

  test('countAuthoredRevisionsTowardHead returns zero when lineage does not reach selection', () => {
    const versions = [
      { id: 'a', parent_version_id: 'b', creator_id: u },
      { id: 'c', parent_version_id: null, creator_id: u },
    ];
    expect(countAuthoredRevisionsTowardHead(versions, 'c', u)).toBe(0);
  });
});
