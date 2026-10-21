'use server';

/**
 * Credit the signed-in reader's active time on a project (#544).
 *
 * The Versions page sends a heartbeat about once a minute while a project is open, the tab is
 * visible and the reader has used it recently (`useProjectTimeTracker`). Each heartbeat that is
 * accepted adds {@link HEARTBEAT_SECONDS} to the reader's row for that project and UTC day in
 * `apiome.project_time` — the rows Home's **Time spent** panel and
 * `GET /v1/projects/{tenant}/time-spent` read.
 *
 * ## Misuse safeguards
 *
 * - **The reader comes from the session, never from the caller.** The only argument is a project
 *   id, so a client cannot credit time to anyone else.
 * - **Only live projects in the reader's workspaces are credited.** The `INSERT … SELECT` matches
 *   no row otherwise.
 * - **Time cannot be inflated.** A heartbeat less than {@link MIN_BEAT_GAP_SECONDS} after the last
 *   accepted one for the same project credits nothing — so two tabs, or a client calling in a
 *   loop, count as one — and a day is capped at 24 hours by the update and by the column's check.
 * - **Malformed ids never reach SQL**, and a failure is `false`, never a rejection.
 */

import type { Pool } from 'pg';

// db.ts is CommonJS (module.exports); keep parity with dashboard-home.ts.
// eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS pool singleton
const connectionPool = require('./db') as Pool;

import { getAuthSession } from '../auth/server-session';
import { isUuid } from '../comment-discussion';

/** Seconds each accepted heartbeat credits — the client's beat interval. */
const HEARTBEAT_SECONDS = 60;

/**
 * The least gap between two credited heartbeats for one (reader, project, day). A little under
 * {@link HEARTBEAT_SECONDS}, so a timer that fires a moment early is not dropped.
 */
const MIN_BEAT_GAP_SECONDS = 55;

/** A day's ceiling, matching the column's check. */
const DAY_SECONDS = 86_400;

/**
 * Credit one heartbeat of active time on a project.
 *
 * @param projectId The project the reader is working on.
 * @returns `true` when time was credited; `false` when the heartbeat came too soon after the last
 *   one, there is no session, the id is malformed, the project is not one the reader can reach,
 *   or the write failed.
 */
export async function recordProjectTimeForSession(projectId: string): Promise<boolean> {
  if (!isUuid(projectId)) return false;

  const session = await getAuthSession().catch(() => null);
  const userId = (session?.user as { user_id?: string } | undefined)?.user_id;
  if (!userId) return false;

  try {
    const result = await connectionPool.query(
      `INSERT INTO apiome.project_time (user_id, project_id, tenant_id, day, active_seconds, last_beat_at)
       SELECT $1::uuid, p.id, p.tenant_id, (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date, $3::int, CURRENT_TIMESTAMP
       FROM apiome.projects p
       WHERE p.id = $2::uuid
         AND p.deleted_at IS NULL
         AND p.tenant_id IN (SELECT tenant_id FROM apiome.tenant_users WHERE user_id = $1::uuid)
       ON CONFLICT (user_id, project_id, day) DO UPDATE
       SET active_seconds = LEAST($5::int, apiome.project_time.active_seconds + $3::int),
           last_beat_at = CURRENT_TIMESTAMP
       WHERE apiome.project_time.last_beat_at <= CURRENT_TIMESTAMP - make_interval(secs => $4::int)`,
      [userId, projectId, HEARTBEAT_SECONDS, MIN_BEAT_GAP_SECONDS, DAY_SECONDS],
    );
    return (result.rowCount ?? 0) > 0;
  } catch (error) {
    console.error('[project-time] crediting active time failed', error);
    return false;
  }
}
