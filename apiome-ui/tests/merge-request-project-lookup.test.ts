/**
 * `resolveMergeRequestProject` and `listReviewerCandidates` (COL-4.3, #4527).
 *
 * Pinned: both queries are bound to the caller's tenant, an id that is not a UUID never reaches the
 * database, a merge request of another tenant (no row) resolves to nothing, and the caller is left
 * out of their own reviewer list.
 */

import {
  MERGE_REQUEST_PROJECT_SQL,
  REVIEWER_CANDIDATES_SQL,
  listReviewerCandidates,
  resolveMergeRequestProject,
  type MergeRequestQuery,
} from '../lib/db/merge-request-project';

const MR = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const TENANT = '550e8400-e29b-41d4-a716-446655440000';

/**
 * A query runner that records its calls and answers with the given rows.
 *
 * @param rows - The rows to answer with.
 * @returns The runner and its calls.
 */
function runner(rows: Array<Record<string, unknown>>) {
  const calls: Array<{ sql: string; params: unknown[] }> = [];
  const query: MergeRequestQuery = async (sql, params) => {
    calls.push({ sql, params });
    return { rows };
  };
  return { query, calls };
}

describe('resolveMergeRequestProject', () => {
  it("reads the merge request's project bound to the tenant", async () => {
    const { query, calls } = runner([{ id: 'p-1', name: 'Pets', slug: 'pets', metadata: null }]);
    await expect(resolveMergeRequestProject(MR, TENANT, query)).resolves.toEqual({
      id: 'p-1',
      name: 'Pets',
      slug: 'pets',
      metadata: null,
    });
    expect(calls).toEqual([{ sql: MERGE_REQUEST_PROJECT_SQL, params: [MR, TENANT] }]);
    expect(MERGE_REQUEST_PROJECT_SQL).toMatch(/mr\.tenant_id::text = \$2/);
    expect(MERGE_REQUEST_PROJECT_SQL).toMatch(/p\.tenant_id::text = \$2/);
  });

  it('never queries for a non-UUID id or a missing tenant, and answers null for no row', async () => {
    const { query, calls } = runner([]);
    await expect(resolveMergeRequestProject('1.0.0', TENANT, query)).resolves.toBeNull();
    await expect(resolveMergeRequestProject(MR, '', query)).resolves.toBeNull();
    expect(calls).toHaveLength(0);
    await expect(resolveMergeRequestProject(MR, TENANT, query)).resolves.toBeNull();
  });
});

describe('listReviewerCandidates', () => {
  it("lists the tenant's active and pending members without the caller", async () => {
    const { query, calls } = runner([
      { user_id: 'me', name: 'Me', email: 'me@example.com' },
      { user_id: 'rex', name: 'Rex', email: null },
    ]);
    await expect(listReviewerCandidates(TENANT, 'me', query)).resolves.toEqual([
      { user_id: 'rex', name: 'Rex', email: null },
    ]);
    expect(calls).toEqual([{ sql: REVIEWER_CANDIDATES_SQL, params: [TENANT] }]);
    expect(REVIEWER_CANDIDATES_SQL).toMatch(/status IN \('active', 'pending'\)/);
  });

  it('answers nothing without a tenant', async () => {
    const { query, calls } = runner([{ user_id: 'rex' }]);
    await expect(listReviewerCandidates('', null, query)).resolves.toEqual([]);
    expect(calls).toHaveLength(0);
  });
});
