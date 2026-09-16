/**
 * The tenant-bound read behind the status pills (COL-2.4, #4520).
 *
 * `lib/db/review-status.ts` is the one place the four surfaces get their rows from, and it is a
 * direct database read rather than an apiome-rest call — so the safeguards that would otherwise be
 * REST's are this module's, and they are what this suite pins:
 *
 *   1. **Scope is the session's tenant**, spelled on both the review and its project, so an id
 *      from another workspace matches nothing.
 *   2. **Deleted projects and revisions, and withdrawn reviews, are excluded** — none of the three
 *      is a status a reader should see a pill for.
 *   3. **The tally counts the current round only**, which is the round COL-2.3's publish gate
 *      counts; an earlier round's approvals are history.
 *   4. **The row count is capped in SQL.**
 *   5. **A row the driver returns oddly is coerced, not drawn** — counts to integers, a
 *      `timestamptz` `Date` to ISO — and an unusable row is dropped.
 */

import {
  OPEN_REVIEWS_SQL,
  OPEN_REVIEW_LIMIT,
  listOpenReviews,
  type ReviewStatusQuery,
} from '@lib/db/review-status';

const TENANT = '550e8400-e29b-41d4-a716-446655440000';
const PROJECT = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

/** A driver row as the statement above selects it. */
function row(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    review_id: 'rev-1',
    project_id: PROJECT,
    version_id: 'ver-1',
    version_label: '1.2.0',
    state: 'in_review',
    round: 1,
    updated_at: new Date('2026-09-01T10:00:00.000Z'),
    reviewer_count: 2,
    approved_count: 1,
    changes_requested_count: 0,
    pending_count: 1,
    ...over,
  };
}

/** A runner that records its call and answers with `rows`. */
function runner(rows: Array<Record<string, unknown>>) {
  const calls: Array<{ sql: string; params: unknown[] }> = [];
  const query: ReviewStatusQuery = async (sql, params) => {
    calls.push({ sql, params });
    return { rows };
  };
  return { calls, query };
}

describe('the statement', () => {
  it('binds the tenant on both the review and its project', () => {
    expect(OPEN_REVIEWS_SQL).toContain('r.tenant_id::text = $1');
    expect(OPEN_REVIEWS_SQL).toContain('p.tenant_id::text = $1');
  });

  it('excludes deleted projects, deleted revisions and withdrawn reviews', () => {
    expect(OPEN_REVIEWS_SQL).toContain('p.deleted_at IS NULL');
    expect(OPEN_REVIEWS_SQL).toContain('v.deleted_at IS NULL');
    expect(OPEN_REVIEWS_SQL).toContain('r.closed_at IS NULL');
  });

  it('tallies the current round only', () => {
    expect(OPEN_REVIEWS_SQL).toContain('rr.round = r.round');
    for (const decision of ['approve', 'request_changes', 'pending']) {
      expect(OPEN_REVIEWS_SQL).toContain(`FILTER (WHERE rr.decision = '${decision}')`);
    }
  });

  it('keeps a review whose reviewers were all deleted, by joining left', () => {
    expect(OPEN_REVIEWS_SQL).toContain('LEFT JOIN apiome.review_reviewers rr');
  });

  it('caps the rows it can return', () => {
    expect(OPEN_REVIEWS_SQL).toContain('LIMIT $3');
    expect(OPEN_REVIEW_LIMIT).toBeGreaterThan(0);
  });
});

describe('listOpenReviews', () => {
  it('passes the tenant, the project filter and the cap, in that order', async () => {
    const { calls, query } = runner([]);
    await listOpenReviews(TENANT, PROJECT, query);
    expect(calls).toHaveLength(1);
    expect(calls[0].params).toEqual([TENANT, PROJECT, OPEN_REVIEW_LIMIT]);
  });

  it('passes null for the whole tenant, which the statement reads as "no filter"', async () => {
    const { calls, query } = runner([]);
    await listOpenReviews(TENANT, null, query);
    expect(calls[0].params[1]).toBeNull();
    expect(OPEN_REVIEWS_SQL).toContain('$2::uuid IS NULL OR r.project_id = $2::uuid');
  });

  it('does not query at all without a tenant', async () => {
    const { calls, query } = runner([row()]);
    expect(await listOpenReviews('', null, query)).toEqual([]);
    expect(calls).toHaveLength(0);
  });

  it('shapes a row into what the surfaces draw', async () => {
    const { query } = runner([row()]);
    expect(await listOpenReviews(TENANT, PROJECT, query)).toEqual([
      {
        reviewId: 'rev-1',
        projectId: PROJECT,
        versionId: 'ver-1',
        versionLabel: '1.2.0',
        state: 'in_review',
        round: 1,
        reviewerCount: 2,
        approvedCount: 1,
        changesRequestedCount: 0,
        pendingCount: 1,
        updatedAt: '2026-09-01T10:00:00.000Z',
      },
    ]);
  });

  it('reads a string timestamp as well as a Date', async () => {
    const { query } = runner([row({ updated_at: '2026-09-02T00:00:00Z' })]);
    const [read] = await listOpenReviews(TENANT, null, query);
    expect(read.updatedAt).toBe('2026-09-02T00:00:00.000Z');
  });

  it('coerces counts a driver returned as strings, and refuses a negative round', async () => {
    const { query } = runner([row({ reviewer_count: '5', approved_count: '2', round: 0 })]);
    const [read] = await listOpenReviews(TENANT, null, query);
    expect(read).toMatchObject({ reviewerCount: 5, approvedCount: 2, round: 1 });
  });

  it('reads a blank version label as no label', async () => {
    const { query } = runner([row({ version_label: '  ' })]);
    expect((await listOpenReviews(TENANT, null, query))[0].versionLabel).toBeNull();
  });

  it('drops a row missing an id rather than drawing a pill that links nowhere', async () => {
    const { query } = runner([row({ review_id: null }), row({ version_id: 42 }), row()]);
    expect(await listOpenReviews(TENANT, null, query)).toHaveLength(1);
  });
});
