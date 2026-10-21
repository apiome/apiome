'use server';

/**
 * Pin and unpin projects for the signed-in reader (#513).
 *
 * Pins live in `apiome.project_pins` — the rows Home's **Pinned projects** panel reads
 * (`./dashboard-home.ts`) and `GET /v1/projects/{tenant}/pinned` serves. Each member may pin up
 * to {@link PROJECT_PIN_LIMIT} projects per workspace; the Projects list's ⋯ menu and Home's
 * panel are the two places that call these actions.
 *
 * ## Misuse safeguards
 *
 * - **The reader comes from the session, never from the caller.** The only argument is a
 *   project id, so a client cannot pin or unpin for anyone else.
 * - **Only live projects in the reader's workspaces can be pinned.** The project is looked up
 *   against `tenant_users`; an unknown, deleted or foreign id is `not_found` and writes nothing.
 * - **The limit cannot be raced.** Pinning runs in one transaction under the same
 *   per-(user, workspace) advisory lock key REST's `pin_project` takes, so two tabs pinning at
 *   once cannot both slip past the count.
 * - **Malformed ids never reach SQL**, and every failure is a status, never a rejection.
 */

import type { Pool } from 'pg';

// db.ts is CommonJS (module.exports); keep parity with dashboard-home.ts.
// eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS pool singleton
const connectionPool = require('./db') as Pool;

import { getAuthSession } from '../auth/server-session';
import { isUuid } from '../comment-discussion';
import { PROJECT_PIN_LIMIT, type PinProjectStatus } from './dashboard-home-model';

/** The session's reader and current workspace, or `null` when signed out. */
async function sessionReader(): Promise<{ userId: string; tenantId: string | null } | null> {
  const session = await getAuthSession().catch(() => null);
  const user = session?.user as { user_id?: string; current_tenant_id?: string } | undefined;
  if (!user?.user_id) return null;
  return { userId: user.user_id, tenantId: user.current_tenant_id ?? null };
}

/**
 * The ids of the projects the reader pinned in the current workspace.
 *
 * The Projects list uses it to word each ⋯ menu's item ("Pin to Home" or "Unpin from Home").
 *
 * @returns Project ids, newest pin first; empty when signed out, with no current workspace, or
 *   when the read fails.
 */
export async function listPinnedProjectIdsForSession(): Promise<string[]> {
  const reader = await sessionReader();
  if (!reader?.tenantId) return [];

  try {
    const result = await connectionPool.query(
      `SELECT pp.project_id
       FROM apiome.project_pins pp
       JOIN apiome.projects p ON p.id = pp.project_id
       WHERE pp.user_id = $1::uuid
         AND pp.tenant_id = $2::uuid
         AND p.deleted_at IS NULL
       ORDER BY pp.pinned_at DESC
       LIMIT $3`,
      [reader.userId, reader.tenantId, PROJECT_PIN_LIMIT],
    );
    return result.rows.map((row) => String(row.project_id));
  } catch (error) {
    console.error('[project-pins] listing pins failed', error);
    return [];
  }
}

/**
 * Pin a project to the reader's Home.
 *
 * Pinning a project that is already pinned changes nothing and reports `already_pinned`, even
 * when the reader is at the limit.
 *
 * @param projectId The project to pin.
 * @returns What happened — see {@link PinProjectStatus}.
 */
export async function pinProjectForSession(projectId: string): Promise<PinProjectStatus> {
  if (!isUuid(projectId)) return 'not_found';
  const reader = await sessionReader();
  if (!reader) return 'error';

  const client = await connectionPool.connect().catch((error: unknown) => {
    console.error('[project-pins] no database connection', error);
    return null;
  });
  if (!client) return 'error';

  try {
    await client.query('BEGIN');

    const project = await client.query(
      `SELECT p.tenant_id
       FROM apiome.projects p
       WHERE p.id = $1::uuid
         AND p.deleted_at IS NULL
         AND p.tenant_id IN (SELECT tenant_id FROM apiome.tenant_users WHERE user_id = $2::uuid)`,
      [projectId, reader.userId],
    );
    if (project.rows.length === 0) {
      await client.query('COMMIT');
      return 'not_found';
    }
    const tenantId = String(project.rows[0].tenant_id);

    // The same lock key REST uses, so the UI and the API serialise against each other.
    await client.query('SELECT pg_advisory_xact_lock(hashtext($1))', [
      `project_pins:${reader.userId}:${tenantId}`,
    ]);

    const existing = await client.query(
      `SELECT 1 FROM apiome.project_pins WHERE user_id = $1::uuid AND project_id = $2::uuid`,
      [reader.userId, projectId],
    );
    if (existing.rows.length > 0) {
      await client.query('COMMIT');
      return 'already_pinned';
    }

    const count = await client.query(
      `SELECT COUNT(*) AS n
       FROM apiome.project_pins pp
       JOIN apiome.projects p ON p.id = pp.project_id
       WHERE pp.tenant_id = $1::uuid AND pp.user_id = $2::uuid AND p.deleted_at IS NULL`,
      [tenantId, reader.userId],
    );
    if (Number(count.rows[0]?.n ?? 0) >= PROJECT_PIN_LIMIT) {
      await client.query('COMMIT');
      return 'limit_reached';
    }

    await client.query(
      `INSERT INTO apiome.project_pins (user_id, project_id, tenant_id)
       VALUES ($1::uuid, $2::uuid, $3::uuid)`,
      [reader.userId, projectId, tenantId],
    );
    await client.query('COMMIT');
    return 'pinned';
  } catch (error) {
    await client.query('ROLLBACK').catch(() => undefined);
    console.error('[project-pins] pinning a project failed', error);
    return 'error';
  } finally {
    client.release();
  }
}

/**
 * Unpin a project from the reader's Home.
 *
 * Unpinning a project that is not pinned is not an error.
 *
 * @param projectId The project to unpin.
 * @returns `true` when the reader's pin is gone (removed now, or never there); `false` when
 *   signed out, the id is malformed, or the write failed.
 */
export async function unpinProjectForSession(projectId: string): Promise<boolean> {
  if (!isUuid(projectId)) return false;
  const reader = await sessionReader();
  if (!reader) return false;

  try {
    await connectionPool.query(
      `DELETE FROM apiome.project_pins WHERE user_id = $1::uuid AND project_id = $2::uuid`,
      [reader.userId, projectId],
    );
    return true;
  } catch (error) {
    console.error('[project-pins] unpinning a project failed', error);
    return false;
  }
}
