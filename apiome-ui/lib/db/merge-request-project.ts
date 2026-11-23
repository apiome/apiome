/**
 * Which project a merge request belongs to, and who can review it — COL-4.3 (#4527).
 *
 * The merge request page lives at `/ade/merge-requests/{id}`, but every apiome-rest merge-request
 * route is addressed by project (`/v1/tenants/{tenant}/projects/{project}/merge-requests/{id}`).
 * {@link resolveMergeRequestProject} closes that gap with one query **bound to the caller's
 * tenant**, so an id from another tenant resolves to nothing. It grants no access by itself — the
 * BFF then calls apiome-rest, which enforces `versions:view`.
 *
 * {@link listReviewerCandidates} lists the members COL-2.1 accepts as reviewers: active or pending
 * members of the tenant (apiome-rest re-checks the list when the review is requested).
 *
 * This module deliberately has no `'use server'` directive: it is an internal utility of the BFF
 * routes, not a server action a browser could call.
 */

import { isUuid } from '../comment-discussion';
import type { ReviewerCandidate } from '../merge-requests';

/** Runs one parameterized query and returns its rows (`pg`'s `Pool.query` shape). */
export type MergeRequestQuery = (
  sql: string,
  params: unknown[]
) => Promise<{ rows: Array<Record<string, unknown>> }>;

/** The merge request's project, as the BFF needs it. */
export interface MergeRequestProjectRow {
  /** The project id, which apiome-rest's routes accept as the project reference. */
  id: string;
  /** Its display name, for the breadcrumb and the generated document's title. */
  name: string;
  /** Its slug. */
  slug: string;
  /** Its metadata, which a revision's OpenAPI document merges into `info`. */
  metadata: unknown;
}

/** The merge request's project, bound to the tenant (`$1` merge request id, `$2` tenant id). */
export const MERGE_REQUEST_PROJECT_SQL = `
  SELECT p.id::text AS id, p.name, p.slug, p.metadata
  FROM apiome.merge_requests mr
  JOIN apiome.projects p ON p.id = mr.project_id
  WHERE mr.id = $1::uuid
    AND mr.tenant_id = $2::uuid
    AND p.tenant_id = $2::uuid
    AND p.deleted_at IS NULL`;

/** The tenant's reviewable members (`$1` tenant id), by name. */
export const REVIEWER_CANDIDATES_SQL = `
  SELECT u.id::text AS user_id, u.name, u.email
  FROM apiome.tenant_users tu
  JOIN apiome.users u ON u.id = tu.user_id
  WHERE tu.tenant_id = $1::uuid
    AND tu.status IN ('active', 'pending')
  ORDER BY lower(coalesce(u.name, u.email, '')), u.id`;

/**
 * The shared connection pool's query, loaded lazily so tests that inject a runner never open it.
 *
 * @param sql - The statement.
 * @param params - Its parameters.
 * @returns The rows.
 */
const poolQuery: MergeRequestQuery = (sql, params) => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const connectionPool = require('./db');
  return connectionPool.query(sql, params);
};

/**
 * Resolve a merge request's project inside the caller's tenant.
 *
 * @param mergeRequestId - The merge request id from the URL.
 * @param tenantId - The caller's tenant, from the session.
 * @param query - The query runner; defaults to the shared pool.
 * @returns The project, or null when the id is not a UUID or no merge request of the tenant has it.
 */
export async function resolveMergeRequestProject(
  mergeRequestId: string,
  tenantId: string,
  query: MergeRequestQuery = poolQuery
): Promise<MergeRequestProjectRow | null> {
  if (!isUuid(mergeRequestId) || !tenantId) return null;
  const { rows } = await query(MERGE_REQUEST_PROJECT_SQL, [mergeRequestId, tenantId]);
  const row = rows[0];
  if (!row || typeof row.id !== 'string') return null;
  return {
    id: row.id,
    name: typeof row.name === 'string' ? row.name : '',
    slug: typeof row.slug === 'string' ? row.slug : '',
    metadata: row.metadata ?? null,
  };
}

/**
 * The tenant members who can be asked to review, without the caller (who cannot review their own).
 *
 * @param tenantId - The caller's tenant, from the session.
 * @param viewerId - The caller, left out of the list.
 * @param query - The query runner; defaults to the shared pool.
 * @returns The candidates, by name.
 */
export async function listReviewerCandidates(
  tenantId: string,
  viewerId: string | null,
  query: MergeRequestQuery = poolQuery
): Promise<ReviewerCandidate[]> {
  if (!tenantId) return [];
  const { rows } = await query(REVIEWER_CANDIDATES_SQL, [tenantId]);
  return rows
    .filter((row) => typeof row.user_id === 'string' && row.user_id !== viewerId)
    .map((row) => ({
      user_id: row.user_id as string,
      name: typeof row.name === 'string' ? row.name : null,
      email: typeof row.email === 'string' ? row.email : null,
    }));
}
