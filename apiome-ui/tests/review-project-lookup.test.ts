/**
 * `resolveReviewProject` (COL-2.2, #4518).
 *
 * The one query that turns `/ade/reviews/{id}` into the project apiome-rest addresses reviews by.
 * Pinned: it is bound to the caller's tenant, ids that are not UUIDs never reach the database, and
 * a review of another tenant (no row) resolves to nothing.
 */

import { REVIEW_PROJECT_SQL, resolveReviewProject, type ReviewProjectQuery } from '../lib/db/review-project';

const REVIEW = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const TENANT = '550e8400-e29b-41d4-a716-446655440000';

/**
 * A query runner that records its calls and answers with the given rows.
 *
 * @param rows - The rows to answer with.
 * @returns The runner and its calls.
 */
function runner(rows: Array<Record<string, unknown>>) {
  const calls: Array<{ sql: string; params: unknown[] }> = [];
  const query: ReviewProjectQuery = async (sql, params) => {
    calls.push({ sql, params });
    return { rows };
  };
  return { query, calls };
}

describe('resolveReviewProject', () => {
  it("reads the review's project bound to the tenant", async () => {
    const { query, calls } = runner([{ id: 'p-1', name: 'Pets', slug: 'pets', metadata: { owner: 'team' } }]);
    await expect(resolveReviewProject(REVIEW, TENANT, query)).resolves.toEqual({
      id: 'p-1',
      name: 'Pets',
      slug: 'pets',
      metadata: { owner: 'team' },
    });
    expect(calls).toEqual([{ sql: REVIEW_PROJECT_SQL, params: [REVIEW, TENANT] }]);
  });

  it('binds both the review and its project to the tenant, and skips deleted projects', () => {
    expect(REVIEW_PROJECT_SQL).toContain('r.id = $1::uuid');
    expect(REVIEW_PROJECT_SQL).toContain('r.tenant_id::text = $2');
    expect(REVIEW_PROJECT_SQL).toContain('p.tenant_id::text = $2');
    expect(REVIEW_PROJECT_SQL).toContain('p.deleted_at IS NULL');
  });

  it('resolves nothing for a review the tenant does not have', async () => {
    const { query } = runner([]);
    await expect(resolveReviewProject(REVIEW, TENANT, query)).resolves.toBeNull();
  });

  it('never queries for an id that is not a UUID, or without a tenant', async () => {
    const { query, calls } = runner([{ id: 'p-1' }]);
    await expect(resolveReviewProject("x' OR 1=1 --", TENANT, query)).resolves.toBeNull();
    await expect(resolveReviewProject(REVIEW, '', query)).resolves.toBeNull();
    expect(calls).toEqual([]);
  });

  it('fills missing name, slug and metadata with empty values', async () => {
    const { query } = runner([{ id: 'p-1', name: null, slug: undefined }]);
    await expect(resolveReviewProject(REVIEW, TENANT, query)).resolves.toEqual({
      id: 'p-1',
      name: '',
      slug: '',
      metadata: null,
    });
  });
});
