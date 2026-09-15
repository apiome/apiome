/**
 * Which project a review belongs to — COL-2.2 (#4518).
 *
 * The review page lives at `/ade/reviews/{id}`, but every apiome-rest review route is addressed by
 * project (`/v1/tenants/{tenant}/projects/{project}/reviews/{id}`). This one query closes that gap
 * for the BFF: it reads the review's project, **bound to the caller's tenant**, so a review id from
 * another tenant resolves to nothing. It grants no access by itself — the BFF then calls apiome-rest,
 * which enforces `projects:view` (and the reviewer assignment for decisions).
 *
 * This module deliberately has no `'use server'` directive: it is an internal utility of the BFF
 * routes, not a server action a browser could call.
 */

import { isUuid } from '../comment-discussion';

/** Runs one parameterized query and returns its rows (`pg`'s `Pool.query` shape). */
export type ReviewProjectQuery = (
  sql: string,
  params: unknown[]
) => Promise<{ rows: Array<Record<string, unknown>> }>;

/** The review's project, as the BFF needs it. */
export interface ReviewProjectRow {
  /** The project id, which apiome-rest's review routes accept as the project reference. */
  id: string;
  /** Its display name, for the breadcrumb and the generated document's title. */
  name: string;
  /** Its slug. */
  slug: string;
  /** Its metadata, which the version's OpenAPI document merges into `info`. */
  metadata: unknown;
}

/** The review's project, bound to the tenant (`$1` review id, `$2` tenant id). */
export const REVIEW_PROJECT_SQL = `
  SELECT p.id::text AS id, p.name, p.slug, p.metadata
  FROM apiome.reviews r
  JOIN apiome.projects p ON p.id = r.project_id
  WHERE r.id = $1::uuid
    AND r.tenant_id::text = $2
    AND p.tenant_id::text = $2
    AND p.deleted_at IS NULL`;

/**
 * The shared connection pool's query, loaded lazily so tests that inject a runner never open it.
 *
 * @param sql - The statement.
 * @param params - Its parameters.
 * @returns The rows.
 */
const poolQuery: ReviewProjectQuery = (sql, params) => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const connectionPool = require('./db');
  return connectionPool.query(sql, params);
};

/**
 * Resolve a review's project inside the caller's tenant.
 *
 * @param reviewId - The review id from the URL.
 * @param tenantId - The caller's tenant, from the session.
 * @param query - The query runner; defaults to the shared pool.
 * @returns The project, or null when the id is not a UUID or no review of the tenant has it.
 */
export async function resolveReviewProject(
  reviewId: string,
  tenantId: string,
  query: ReviewProjectQuery = poolQuery
): Promise<ReviewProjectRow | null> {
  if (!isUuid(reviewId) || !tenantId) return null;
  const { rows } = await query(REVIEW_PROJECT_SQL, [reviewId, tenantId]);
  const row = rows[0];
  if (!row || typeof row.id !== 'string') return null;
  return {
    id: row.id,
    name: typeof row.name === 'string' ? row.name : '',
    slug: typeof row.slug === 'string' ? row.slug : '',
    metadata: row.metadata ?? null,
  };
}
