/**
 * The one read of a reader's pinned projects (#513, #542).
 *
 * Home's **Pinned projects** panel (`./dashboard-home.ts`), the Profile page's **Favorite
 * projects** card and the command palette's **Favorites** group (both through
 * `./project-pins.ts`) all list the same pins, so they share this statement and its row mapping
 * rather than three copies that could drift on scope or order.
 *
 * Not a `'use server'` module: it exports a plain function that takes the query runner, so each
 * caller keeps its own session handling and the mapping is testable without a pool.
 */

import { PROJECT_PIN_LIMIT, type PinnedProject } from './dashboard-home-model';

/** The slice of `pg`'s `Pool` this read needs. */
export type PinnedProjectsQueryRunner = (
  sql: string,
  params: unknown[],
) => Promise<{ rows: Record<string, unknown>[] }>;

/**
 * The statement: the reader's live pins in one workspace, newest first, with each project's
 * newest revision label. The workspace is re-checked against `tenant_users`, so a stale
 * `current_tenant_id` lists nothing rather than a workspace the reader has left.
 *
 * Parameters: `$1` the reader's user id, `$2` the workspace id, `$3` the row cap.
 */
export const PINNED_PROJECTS_SQL = `SELECT
       p.id AS project_id,
       p.name AS project_name,
       pp.pinned_at,
       lv.version_id
     FROM apiome.project_pins pp
     JOIN apiome.projects p ON p.id = pp.project_id
     LEFT JOIN LATERAL (
       SELECT v.version_id
       FROM apiome.versions v
       WHERE v.project_id = p.id AND v.deleted_at IS NULL
       ORDER BY v.created_at DESC, v.id DESC
       LIMIT 1
     ) lv ON true
     WHERE pp.user_id = $1
       AND pp.tenant_id = $2
       AND pp.tenant_id IN (SELECT tenant_id FROM apiome.tenant_users WHERE user_id = $1)
       AND p.tenant_id = pp.tenant_id
       AND p.deleted_at IS NULL
     ORDER BY pp.pinned_at DESC, p.name ASC
     LIMIT $3`;

/**
 * Read a `pg` value as a non-empty trimmed string.
 *
 * @param value Whatever the driver returned.
 * @returns The trimmed string, or `null` when it is absent or blank.
 */
function asText(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed || null;
}

/**
 * Read a `pg` timestamp as an ISO string.
 *
 * @param value A `Date`, an ISO string, or neither.
 * @returns The instant as an ISO string, or `null` when there is no usable instant.
 */
function asInstant(value: unknown): string | null {
  if (value instanceof Date) return Number.isFinite(value.getTime()) ? value.toISOString() : null;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? new Date(parsed).toISOString() : null;
  }
  return null;
}

/**
 * Map the statement's rows to {@link PinnedProject}s, dropping any row with no usable instant.
 *
 * @param rows Rows of {@link PINNED_PROJECTS_SQL}.
 * @returns The pins, in the order given.
 */
export function toPinnedProjects(rows: readonly Record<string, unknown>[]): PinnedProject[] {
  return rows.flatMap((row) => {
    const pinnedAt = asInstant(row.pinned_at);
    if (!pinnedAt) return [];
    return [
      {
        projectId: String(row.project_id),
        projectName: asText(row.project_name) ?? 'Untitled project',
        versionLabel: asText(row.version_id),
        pinnedAt,
      } satisfies PinnedProject,
    ];
  });
}

/**
 * List a reader's pinned projects in one workspace.
 *
 * @param query Runs a parameterised statement — `pool.query`, bound.
 * @param userId The reader, from the session.
 * @param tenantId The workspace, from the session.
 * @returns At most {@link PROJECT_PIN_LIMIT} pins, newest first. Rejects when the query does;
 *   each caller decides how to fail soft.
 */
export async function queryPinnedProjects(
  query: PinnedProjectsQueryRunner,
  userId: string,
  tenantId: string,
): Promise<PinnedProject[]> {
  const result = await query(PINNED_PROJECTS_SQL, [userId, tenantId, PROJECT_PIN_LIMIT]);
  return toPinnedProjects(result.rows);
}
