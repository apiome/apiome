'use server';

/**
 * Record that the signed-in reader opened a project (#510).
 *
 * Writes the reader's row in `apiome.project_views` — the history Home's **Recently viewed**
 * panel reads (`./dashboard-home.ts`) and `GET /v1/projects/{tenant}/recently-viewed` serves.
 * The statement is the same upsert REST's `record_project_view` runs: the first open inserts a
 * row, every later one moves `last_viewed_at` forward and adds one to `view_count`.
 *
 * ## Misuse safeguards
 *
 * - **The reader comes from the session, never from the caller.** The only argument is the
 *   project id, so a client cannot write into another user's history.
 * - **Only live projects in the reader's workspaces are logged.** The `INSERT … SELECT` matches
 *   no row for a deleted project, an unknown id, or a project in a workspace the reader is not a
 *   member of, so a leaked id records nothing.
 * - **Malformed ids never reach SQL.** A value that is not a UUID would make the `::uuid` cast
 *   throw; it is refused up front instead.
 * - **Recording never breaks the page.** A failed write is logged and reported as `false`; the
 *   Versions page does not wait on it or show an error.
 */

import type { Pool } from 'pg';

// db.ts is CommonJS (module.exports); keep parity with dashboard-home.ts.
// eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS pool singleton
const connectionPool = require('./db') as Pool;

import { getAuthSession } from '../auth/server-session';

/** A canonical UUID, any version. */
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Record one open of a project by the signed-in reader.
 *
 * @param projectId The project the reader opened.
 * @returns `true` when the view was recorded; `false` when there is no session, the id is not a
 *   UUID, the project is not one the reader can reach, or the write failed.
 */
export async function recordProjectViewForSession(projectId: string): Promise<boolean> {
  if (typeof projectId !== 'string' || !UUID_PATTERN.test(projectId)) return false;

  const session = await getAuthSession().catch(() => null);
  const userId = (session?.user as { user_id?: string } | undefined)?.user_id;
  if (!userId) return false;

  try {
    const result = await connectionPool.query(
      `INSERT INTO apiome.project_views (user_id, project_id, tenant_id)
       SELECT $1::uuid, p.id, p.tenant_id
       FROM apiome.projects p
       WHERE p.id = $2::uuid
         AND p.deleted_at IS NULL
         AND p.tenant_id IN (SELECT tenant_id FROM apiome.tenant_users WHERE user_id = $1::uuid)
       ON CONFLICT (user_id, project_id) DO UPDATE
       SET last_viewed_at = CURRENT_TIMESTAMP,
           view_count = apiome.project_views.view_count + 1`,
      [userId, projectId],
    );
    return (result.rowCount ?? 0) > 0;
  } catch (error) {
    console.error('[project-views] recording a project view failed', error);
    return false;
  }
}
