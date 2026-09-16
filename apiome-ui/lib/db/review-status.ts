/**
 * Which versions are in review — COL-2.4 (#4520).
 *
 * The status pill has to appear on surfaces that do not otherwise talk to the review API: the
 * revisions table (one project, every row), the projects list (every project, one pill each) and
 * the publish dialog (one revision). apiome-rest addresses reviews **per project**
 * (`/v1/tenants/{tenant}/projects/{project}/reviews`), so the projects list would cost one call
 * per card — fifty projects, fifty round trips, to draw at most fifty pills.
 *
 * This module is the single read behind all three: one statement, scoped to the session's tenant,
 * returning every **open** review with the tally of its current round. It is the same seam
 * `lib/db/dashboard-home.ts` and `/api/database/versions/has-class-schema` use.
 *
 * ## Misuse safeguards
 *
 * - **The tenant comes from the session**, never from the caller — the route reads it off the
 *   session and passes it here, so a project id from another workspace matches nothing.
 * - **Deleted projects and revisions are excluded**, so a soft-deleted project cannot keep
 *   drawing a pill on a dashboard.
 * - **Withdrawn reviews are excluded** (`closed_at IS NULL`): a withdrawn review is the absence of
 *   a status, not a status, and COL-2.1's partial unique index means at most one open review can
 *   exist per revision.
 * - **The row count is capped in SQL** ({@link OPEN_REVIEW_LIMIT}), so a workspace that has left
 *   thousands of reviews open cannot serialise all of them to draw a handful of pills.
 * - This module has **no `'use server'` directive**: it is an internal utility of the BFF route,
 *   not a server action a browser could call.
 */

import type { ReviewStatusRow } from '../review-status';

/** Runs one parameterized query and returns its rows (`pg`'s `Pool.query` shape). */
export type ReviewStatusQuery = (
  sql: string,
  params: unknown[]
) => Promise<{ rows: Array<Record<string, unknown>> }>;

/**
 * How many open reviews one read may return.
 *
 * Well past what any surface draws — the revisions table shows one project's rows and the
 * projects list one pill per card — and low enough that the reply stays small however the
 * workspace is run.
 */
export const OPEN_REVIEW_LIMIT = 500;

/**
 * Every open review of the tenant, newest activity first.
 *
 * `$1` tenant id, `$2` project id or NULL for the whole tenant, `$3` row cap.
 *
 * The reviewer tally is a `LEFT JOIN` over the **current round only** (`rr.round = r.round`), which
 * is the same round COL-2.3's publish gate counts; an earlier round's approvals are history and
 * must never read as progress. The join is left rather than inner so a review whose reviewers were
 * all deleted still reports its state instead of vanishing from the list.
 */
export const OPEN_REVIEWS_SQL = `
  SELECT r.id::text                                                         AS review_id,
         r.project_id::text                                                 AS project_id,
         r.version_id::text                                                 AS version_id,
         v.version_id                                                       AS version_label,
         r.state                                                            AS state,
         r.round                                                            AS round,
         r.updated_at                                                       AS updated_at,
         (COUNT(rr.id))::int                                                AS reviewer_count,
         (COUNT(rr.id) FILTER (WHERE rr.decision = 'approve'))::int         AS approved_count,
         (COUNT(rr.id) FILTER (WHERE rr.decision = 'request_changes'))::int AS changes_requested_count,
         (COUNT(rr.id) FILTER (WHERE rr.decision = 'pending'))::int         AS pending_count
    FROM apiome.reviews r
    JOIN apiome.projects p ON p.id = r.project_id
    JOIN apiome.versions v ON v.id = r.version_id
    LEFT JOIN apiome.review_reviewers rr ON rr.review_id = r.id AND rr.round = r.round
   WHERE r.tenant_id::text = $1
     AND p.tenant_id::text = $1
     AND p.deleted_at IS NULL
     AND v.deleted_at IS NULL
     AND r.closed_at IS NULL
     AND ($2::uuid IS NULL OR r.project_id = $2::uuid)
   GROUP BY r.id, v.version_id
   ORDER BY r.updated_at DESC
   LIMIT $3`;

/**
 * The shared connection pool's query, loaded lazily so tests that inject a runner never open it.
 *
 * @param sql - The statement.
 * @param params - Its parameters.
 * @returns The rows.
 */
const poolQuery: ReviewStatusQuery = (sql, params) => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS pool singleton
  const connectionPool = require('./db');
  return connectionPool.query(sql, params);
};

/**
 * Read a `pg` count as a number.
 *
 * The `::int` casts above already keep the tallies inside a JS number; this only guards against a
 * driver handing a string back, which is what an un-cast `COUNT(*)` would do.
 *
 * @param value - The column.
 * @returns A finite, non-negative integer.
 */
function asCount(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0;
}

/**
 * Read a `pg` timestamp as an ISO string.
 *
 * `timestamptz` arrives as a `Date`; the client compares these as strings to break ties, so one
 * form has to reach it.
 *
 * @param value - The column.
 * @returns The instant as ISO, or an empty string when there is none.
 */
function asInstant(value: unknown): string {
  if (value instanceof Date) return Number.isFinite(value.getTime()) ? value.toISOString() : '';
  if (typeof value === 'string') {
    const parsed = Date.parse(value.trim());
    return Number.isFinite(parsed) ? new Date(parsed).toISOString() : '';
  }
  return '';
}

/**
 * The tenant's open reviews.
 *
 * @param tenantId - The caller's tenant, from the session.
 * @param projectId - One project to narrow to, or null for the whole tenant. A value that is not
 *   a UUID is refused by Postgres' `::uuid` cast, so callers validate it first.
 * @param query - The query runner; defaults to the shared pool.
 * @returns Every open review the tenant can draw a pill for, newest activity first.
 */
export async function listOpenReviews(
  tenantId: string,
  projectId: string | null = null,
  query: ReviewStatusQuery = poolQuery
): Promise<ReviewStatusRow[]> {
  if (!tenantId) return [];
  const { rows } = await query(OPEN_REVIEWS_SQL, [tenantId, projectId, OPEN_REVIEW_LIMIT]);
  return rows.flatMap((row) => {
    const reviewId = typeof row.review_id === 'string' ? row.review_id : '';
    const projectRowId = typeof row.project_id === 'string' ? row.project_id : '';
    const versionId = typeof row.version_id === 'string' ? row.version_id : '';
    const state = row.state;
    if (!reviewId || !projectRowId || !versionId || typeof state !== 'string') return [];
    const label = typeof row.version_label === 'string' ? row.version_label.trim() : '';
    return [
      {
        reviewId,
        projectId: projectRowId,
        versionId,
        versionLabel: label || null,
        state: state as ReviewStatusRow['state'],
        round: Math.max(1, asCount(row.round)),
        reviewerCount: asCount(row.reviewer_count),
        approvedCount: asCount(row.approved_count),
        changesRequestedCount: asCount(row.changes_requested_count),
        pendingCount: asCount(row.pending_count),
        updatedAt: asInstant(row.updated_at),
      } satisfies ReviewStatusRow,
    ];
  });
}
