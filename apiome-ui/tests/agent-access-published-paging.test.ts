/**
 * The "Enable Agent Access" picker reads every published version (DBP-1.13, #7196).
 *
 * `getPublishedVersionsForTenant` answers a page at a time. The picker needs the whole list, so
 * `fetchPublishedVersions` follows the cursors — the largest page each time, and no further than
 * `MAX_UNPAGED_ROWS` revisions.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

const mockRead =
  jest.fn<(tenantId: string, team: string | null, page: unknown) => Promise<string>>();
jest.mock('@lib/db/helper-actions', () => ({
  getPublishedVersionsForTenant: (tenantId: string, team: string | null, page: unknown) =>
    mockRead(tenantId, team, page),
}));

import { fetchPublishedVersions } from '../src/app/components/ade/agentAccess/agentAccessApi';
import { MAX_LIST_ROWS, MAX_UNPAGED_ROWS } from '../lib/db/list-bounds';

/** One page of the read: `count` versions starting at `from`. */
const page = (from: number, count: number, nextCursor: string | null) =>
  JSON.stringify({
    success: true,
    versions: Array.from({ length: count }, (_, index) => ({
      id: `v-${from + index}`,
      version_id: `1.0.${from + index}`,
      project_id: 'p-1',
      project_name: 'Payments API',
    })),
    hasMore: nextCursor !== null,
    nextCursor,
  });

beforeEach(() => mockRead.mockReset());

describe('fetchPublishedVersions', () => {
  test('one page that is everything is read once', async () => {
    mockRead.mockResolvedValueOnce(page(0, 3, null));

    const options = await fetchPublishedVersions('t-1');

    expect(options.map((option) => option.id)).toEqual(['v-0', 'v-1', 'v-2']);
    expect(mockRead).toHaveBeenCalledTimes(1);
    expect(mockRead).toHaveBeenCalledWith('t-1', null, { limit: MAX_LIST_ROWS, cursor: null });
  });

  test('follows the cursors, keeping the order', async () => {
    mockRead
      .mockResolvedValueOnce(page(0, 2, 'c1'))
      .mockResolvedValueOnce(page(2, 2, 'c2'))
      .mockResolvedValueOnce(page(4, 1, null));

    const options = await fetchPublishedVersions('t-1');

    expect(options.map((option) => option.id)).toEqual(['v-0', 'v-1', 'v-2', 'v-3', 'v-4']);
    expect(mockRead.mock.calls.map((call) => call[2])).toEqual([
      { limit: MAX_LIST_ROWS, cursor: null },
      { limit: MAX_LIST_ROWS, cursor: 'c1' },
      { limit: MAX_LIST_ROWS, cursor: 'c2' },
    ]);
  });

  test('stops at the cap of a list read whole', async () => {
    mockRead.mockImplementation(async () => page(0, 1, 'again'));

    await fetchPublishedVersions('t-1');

    expect(mockRead).toHaveBeenCalledTimes(MAX_UNPAGED_ROWS / MAX_LIST_ROWS);
  });

  test('a page that cannot be read fails the whole read', async () => {
    mockRead
      .mockResolvedValueOnce(page(0, 2, 'c1'))
      .mockResolvedValueOnce(JSON.stringify({ success: false, error: 'connection refused' }));

    await expect(fetchPublishedVersions('t-1')).rejects.toThrow('connection refused');
  });
});
