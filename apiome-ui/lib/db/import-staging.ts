/**
 * Staged imports: the committed state an import waits in while a person reviews it (DBP-1.9, #7192).
 *
 * The import wizard used to leave its transaction open, on a pooled connection, until the
 * reviewer chose Accept or Reject — ten reviews exhausted the pool, and PostgreSQL ended a review
 * that took longer than `idle_in_transaction_session_timeout`. Now the import commits and no
 * connection is held:
 *
 * - **Staged.** The version is written with `deleted_at` and `import_pending_at` set (V411), and so
 *   is the project when the import created it. Every reader already filters on
 *   `deleted_at IS NULL`, so nothing shows the staged rows.
 * - **Accept** ({@link acceptStagedImportTx}) clears both columns: the import becomes visible.
 * - **Reject** ({@link discardStagedImportTx}) deletes the staged rows and undoes what the import
 *   changed outside its version, listed in the version's `import_pending` manifest.
 * - **Abandoned** — the dialog was closed, or the server restarted and lost the job — a staged
 *   import is discarded by {@link sweepAbandonedImports} once it is older than
 *   {@link importPendingTtlMs}.
 */

// eslint-disable-next-line @typescript-eslint/no-require-imports
const connectionPool = require('./db');
import type { BulkQueryable } from './import-bulk';
import { getPlanBlockMessageForNewProject, getPlanBlockMessageForNewVersion } from './plan-entitlements';

/** A repository source row as it was before the import moved it. */
export interface TouchedRepositorySource {
  id: string;
  last_version_id: string | null;
  last_blob_sha: string | null;
  updated_at: string | null;
}

/** What discarding a staged import must undo besides deleting its version. */
export interface StagedImportManifest {
  /** The in-memory job that staged the import (for the log; the job does not survive a restart). */
  jobId: string;
  /** Whether the import created the project (staged too) rather than adding a version to one. */
  projectCreated: boolean;
  /** Project properties the import added to the library. */
  propertyIds: string[];
  /** Repository source rows the import added (REPO-5.7). */
  sourcesCreated: string[];
  /** Repository source rows the import moved to its version, with their previous values. */
  sourcesTouched: TouchedRepositorySource[];
}

/** How long a staged import waits for a decision when `IMPORT_PENDING_TTL_MINUTES` is unset. */
export const DEFAULT_IMPORT_PENDING_TTL_MINUTES = 60;

/** Staged imports the sweeper discards per pass. */
const SWEEP_BATCH = 100;

/**
 * How long a staged import may wait for Accept or Reject before the sweeper discards it.
 *
 * @returns Milliseconds, from `IMPORT_PENDING_TTL_MINUTES` (a positive number; default 60).
 */
export function importPendingTtlMs(): number {
  const minutes = Number(process.env.IMPORT_PENDING_TTL_MINUTES);
  return (Number.isFinite(minutes) && minutes > 0 ? minutes : DEFAULT_IMPORT_PENDING_TTL_MINUTES) * 60_000;
}

/**
 * Record what a staged import changed outside its version. Runs in the staging transaction, so a
 * staged version never exists without its manifest.
 *
 * @param client The import's transaction client.
 * @param versionId The staged version.
 * @param manifest What to undo on discard.
 */
export async function writeStagedManifestTx(
  client: BulkQueryable,
  versionId: string,
  manifest: StagedImportManifest,
): Promise<void> {
  await client.query(
    'UPDATE apiome.versions SET import_pending = $2::jsonb WHERE id = $1 AND import_pending_at IS NOT NULL',
    [versionId, JSON.stringify(manifest)],
  );
}

/**
 * A project's repository source rows, read before a repository-file import writes its merge so
 * the manifest can tell the rows it added from the ones it moved.
 *
 * @param client The import's transaction client.
 * @param projectId The project.
 * @returns The rows' ids and the columns an import moves.
 */
export async function listRepositorySourcesTx(
  client: BulkQueryable,
  projectId: string,
): Promise<TouchedRepositorySource[]> {
  const result = await client.query(
    `SELECT id::text AS id, last_version_id::text AS last_version_id, last_blob_sha,
            updated_at::text AS updated_at
       FROM apiome.project_repository_sources
      WHERE project_id = $1`,
    [projectId],
  );
  return result.rows as TouchedRepositorySource[];
}

/**
 * Lock a staged version and read its manifest.
 *
 * @param client A client inside a transaction.
 * @param versionId The version.
 * @param skipLocked Leave a version another session is deciding on (the sweeper passes true).
 * @returns The project and manifest, or `null` when the version is not staged (already accepted,
 *   discarded or swept) or is locked and `skipLocked` is set.
 */
async function lockStagedVersionTx(
  client: BulkQueryable,
  versionId: string,
  skipLocked: boolean,
): Promise<{ projectId: string; manifest: StagedImportManifest } | null> {
  const result = await client.query(
    `SELECT project_id::text AS project_id, import_pending
       FROM apiome.versions
      WHERE id = $1 AND import_pending_at IS NOT NULL
        FOR UPDATE${skipLocked ? ' SKIP LOCKED' : ''}`,
    [versionId],
  );
  const row = result.rows[0];
  if (!row) return null;
  const raw = typeof row.import_pending === 'string' ? JSON.parse(row.import_pending) : row.import_pending;
  return {
    projectId: String(row.project_id),
    manifest: {
      jobId: String(raw?.jobId ?? ''),
      projectCreated: raw?.projectCreated === true,
      propertyIds: Array.isArray(raw?.propertyIds) ? raw.propertyIds.map(String) : [],
      sourcesCreated: Array.isArray(raw?.sourcesCreated) ? raw.sourcesCreated.map(String) : [],
      sourcesTouched: Array.isArray(raw?.sourcesTouched) ? raw.sourcesTouched : [],
    },
  };
}

/** What {@link acceptStagedImportTx} reports. */
export type AcceptStagedImportResult =
  | { ok: true; projectId: string; projectCreated: boolean }
  | { ok: false; error: string };

/** Shown when Accept finds nothing staged: the import was discarded, swept, or accepted already. */
export const STAGED_IMPORT_GONE_MESSAGE =
  'This import is no longer awaiting approval: it expired or was discarded, and nothing was added. Run the import again.';

/**
 * Accept a staged import: make its version (and the project it created) visible.
 *
 * A staged version or project does not count toward the plan while it waits, so the plan is
 * checked again here: two imports reviewed side by side cannot both be accepted past the limit.
 *
 * @param client A client inside a transaction; the caller commits (or rolls back when not `ok`).
 * @param versionId The staged version.
 * @param userId The user accepting, whose plan limits apply.
 * @returns The version's project and whether the import created it; or the reason nothing was
 *   accepted — the version is no longer staged ({@link STAGED_IMPORT_GONE_MESSAGE}), or the plan
 *   has no room for it.
 */
export async function acceptStagedImportTx(
  client: BulkQueryable,
  versionId: string,
  userId: string,
): Promise<AcceptStagedImportResult> {
  const staged = await lockStagedVersionTx(client, versionId, false);
  if (!staged) return { ok: false, error: STAGED_IMPORT_GONE_MESSAGE };
  const planError =
    (staged.manifest.projectCreated ? await getPlanBlockMessageForNewProject(userId, client) : null) ??
    (await getPlanBlockMessageForNewVersion(userId, client));
  if (planError) return { ok: false, error: planError };
  await client.query(
    `UPDATE apiome.versions
        SET deleted_at = NULL, import_pending_at = NULL, import_pending = NULL
      WHERE id = $1`,
    [versionId],
  );
  if (staged.manifest.projectCreated) {
    await client.query('UPDATE apiome.projects SET deleted_at = NULL WHERE id = $1 AND deleted_at IS NOT NULL', [
      staged.projectId,
    ]);
  }
  return { ok: true, projectId: staged.projectId, projectCreated: staged.manifest.projectCreated };
}

/**
 * Discard a staged import: delete its version and everything in it, and undo what the import
 * changed outside the version — the properties it added to the project's library (unless
 * something else uses one by now), the repository source rows it added or moved, and the project
 * when the import created it.
 *
 * @param client A client inside a transaction; the caller commits.
 * @param versionId The staged version.
 * @param options `skipLocked` leaves a version another session holds (an Accept or Reject in flight).
 * @returns Whether a staged version was discarded (`false`: it was not staged, or was locked).
 */
export async function discardStagedImportTx(
  client: BulkQueryable,
  versionId: string,
  options: { skipLocked?: boolean } = {},
): Promise<boolean> {
  const staged = await lockStagedVersionTx(client, versionId, options.skipLocked === true);
  if (!staged) return false;
  const { projectId, manifest } = staged;

  // Paths first: their responses and request bodies point at the version's classes.
  await client.query('DELETE FROM apiome.version_path WHERE version_id = $1', [versionId]);
  await client.query('DELETE FROM apiome.classes WHERE version_id = $1', [versionId]);

  if (manifest.sourcesTouched.length > 0) {
    await client.query(
      `UPDATE apiome.project_repository_sources s
          SET last_version_id = t.last_version_id, last_blob_sha = t.last_blob_sha, updated_at = t.updated_at
         FROM jsonb_to_recordset($1::jsonb)
           AS t(id uuid, last_version_id uuid, last_blob_sha text, updated_at timestamptz)
        WHERE s.id = t.id`,
      [JSON.stringify(manifest.sourcesTouched)],
    );
  }
  if (manifest.sourcesCreated.length > 0) {
    await client.query('DELETE FROM apiome.project_repository_sources WHERE id = ANY($1::uuid[])', [
      manifest.sourcesCreated,
    ]);
  }

  await client.query('DELETE FROM apiome.versions WHERE id = $1', [versionId]);

  if (manifest.projectCreated) {
    // The project exists only for this import: it is still staged and has no other version.
    const stillStaged = `EXISTS (SELECT 1 FROM apiome.projects p WHERE p.id = $1 AND p.deleted_at IS NOT NULL)
       AND NOT EXISTS (SELECT 1 FROM apiome.versions v WHERE v.project_id = $1)`;
    await client.query(`DELETE FROM apiome.properties WHERE project_id = $1 AND ${stillStaged}`, [projectId]);
    await client.query(`DELETE FROM apiome.projects WHERE id = $1 AND ${stillStaged}`, [projectId]);
  } else if (manifest.propertyIds.length > 0) {
    await client.query(
      `DELETE FROM apiome.properties p
        WHERE p.id = ANY($1::uuid[])
          AND NOT EXISTS (SELECT 1 FROM apiome.class_properties cp WHERE cp.property_id = p.id)
          AND NOT EXISTS (SELECT 1 FROM apiome.path_operation_schema s WHERE s.property_id = p.id)
          AND NOT EXISTS (SELECT 1 FROM apiome.path_parameter_schema s WHERE s.property_id = p.id)`,
      [manifest.propertyIds],
    );
  }
  return true;
}

/**
 * Discard one staged import in its own transaction, on its own client.
 *
 * @param versionId The staged version.
 * @param options `skipLocked` leaves a version another session holds.
 * @returns Whether a staged version was discarded.
 */
export async function discardStagedImport(
  versionId: string,
  options: { skipLocked?: boolean } = {},
): Promise<boolean> {
  const client = await connectionPool.connect();
  try {
    await client.query('BEGIN');
    const discarded = await discardStagedImportTx(client, versionId, options);
    await client.query('COMMIT');
    return discarded;
  } catch (error) {
    try {
      await client.query('ROLLBACK');
    } catch {
      /* the connection is gone; the original error is the one to report */
    }
    throw error;
  } finally {
    client.release();
  }
}

/**
 * Discard the staged imports nobody decided on: those older than the time-to-live. Safe to run
 * from several server instances at once — each version is locked before it is deleted, and a
 * version an Accept or Reject holds is skipped.
 *
 * @param options `ttlMs` overrides {@link importPendingTtlMs} (tests, and `0` to discard every
 *   staged import).
 * @returns How many staged imports were discarded.
 */
export async function sweepAbandonedImports(options: { ttlMs?: number } = {}): Promise<number> {
  const ttlMs = options.ttlMs ?? importPendingTtlMs();
  const due = await connectionPool.query(
    `SELECT id::text AS id
       FROM apiome.versions
      WHERE import_pending_at IS NOT NULL
        AND import_pending_at <= CURRENT_TIMESTAMP - make_interval(secs => $1)
      ORDER BY import_pending_at
      LIMIT ${SWEEP_BATCH}`,
    [ttlMs / 1000],
  );
  let discarded = 0;
  for (const row of due.rows as Array<{ id: string }>) {
    try {
      if (await discardStagedImport(row.id, { skipLocked: true })) discarded += 1;
    } catch (error) {
      console.error(
        `[apiome-ui/import] could not discard abandoned import ${row.id}:`,
        error instanceof Error ? error.message : error,
      );
    }
  }
  return discarded;
}

/** Holds the sweeper's timer across module reloads (Next.js dev) so it starts once per process. */
const SWEEPER = Symbol.for('apiome.importStagingSweeper');

/**
 * Start the background sweeper: one pass now — which clears what a previous process left staged
 * once it is old enough — and one every quarter of the time-to-live (between one and fifteen
 * minutes). The timer does not keep the process alive; a failed pass is logged and retried at the
 * next tick.
 *
 * @returns The interval between passes, in milliseconds.
 */
export function startImportStagingSweeper(): number {
  const intervalMs = Math.min(15 * 60_000, Math.max(60_000, Math.floor(importPendingTtlMs() / 4)));
  const holder = globalThis as unknown as Record<symbol, ReturnType<typeof setInterval> | undefined>;
  if (holder[SWEEPER]) return intervalMs;
  const pass = () => {
    sweepAbandonedImports()
      .then((count) => {
        if (count > 0) console.warn(`[apiome-ui/import] discarded ${count} abandoned staged import(s)`);
      })
      .catch((error) => {
        console.error('[apiome-ui/import] staged import sweep failed:', error instanceof Error ? error.message : error);
      });
  };
  const timer = setInterval(pass, intervalMs);
  timer.unref?.();
  holder[SWEEPER] = timer;
  pass();
  return intervalMs;
}
