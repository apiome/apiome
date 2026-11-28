/**
 * Browser calls for the **Migration wizard** (PFX-8.16, #7313), through the `/api/pact/migrations*`
 * proxies. Each throws REST's message on a failure, so the step can show it (a refused sign-in reads
 * "Could not sign in to acme.pactflow.io (401). Check the token.", a 403 "Permission denied").
 *
 * The source's token or password is sent with the request that needs it and kept nowhere else.
 */

import {
  MIGRATIONS_API,
  type MigrationOptions,
  type MigrationRun,
  type MigrationRunList,
  type SourceTest,
} from '@lib/pact-migration';
import { fetchBrokerAddress } from '../pactSettings/contractSettingsApi';
import { readJson } from '../pactPacticipants/pacticipantsApi';

export { fetchBrokerAddress };

/** How the source is signed in to. */
export type Credentials = { token?: string; username?: string; password?: string };

/** JSON request options for a `POST`. */
function post(body?: unknown): RequestInit {
  return {
    method: 'POST',
    cache: 'no-store',
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  };
}

/** A run's path below the BFF. */
function runPath(runId: string, suffix = ''): string {
  return `${MIGRATIONS_API}/${encodeURIComponent(runId)}${suffix}`;
}

/** The workspace's runs, newest first, and whether the viewer may run one. */
export async function fetchMigrations(): Promise<MigrationRunList> {
  const list = await readJson<MigrationRunList>(
    await fetch(MIGRATIONS_API, { cache: 'no-store' }),
    'Could not load the migrations',
  );
  return { runs: Array.isArray(list.runs) ? list.runs : [], can_migrate: list.can_migrate === true };
}

/**
 * Sign in to the source and count its pacticipants.
 *
 * @param source - The broker's URL.
 * @param credentials - How to sign in.
 * @returns The source's host, product and pacticipant count.
 */
export async function testSource(source: string, credentials: Credentials): Promise<SourceTest> {
  return readJson<SourceTest>(
    await fetch(`${MIGRATIONS_API}/test`, post({ source, ...credentials })),
    'Could not reach the broker',
  );
}

/**
 * Start a run.
 *
 * @param source - The broker's URL.
 * @param credentials - How to sign in.
 * @param mode - `dry-run` (count and check) or `copy`.
 * @param options - The choices; left out of a dry run, which checks everything.
 * @returns The run, running.
 */
export async function startMigration(
  source: string,
  credentials: Credentials,
  mode: MigrationRun['mode'],
  options?: MigrationOptions,
): Promise<MigrationRun> {
  return readJson<MigrationRun>(
    await fetch(MIGRATIONS_API, post({ source, ...credentials, mode, ...(options ? { options } : {}) })),
    mode === 'copy' ? 'Could not start copying' : 'Could not read the broker',
  );
}

/**
 * Read a run.
 *
 * @param runId - The run.
 * @param after - The last log line the reader has.
 * @returns The run with its newer log lines, or the failure and its status (a 404 ends the polling).
 */
export async function readMigration(
  runId: string,
  after = 0,
): Promise<MigrationRun | { failure: string; status: number }> {
  try {
    const response = await fetch(runPath(runId, `?after=${after}`), { cache: 'no-store' });
    const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
    if (response.ok) return body as unknown as MigrationRun;
    return { failure: typeof body.error === 'string' && body.error ? body.error : 'Could not read the migration', status: response.status };
  } catch {
    return { failure: 'Could not read the migration', status: 0 };
  }
}

/**
 * Ask a run to stop.
 *
 * @param runId - The run.
 * @returns The run, winding down.
 */
export async function stopMigration(runId: string): Promise<MigrationRun> {
  return readJson<MigrationRun>(await fetch(runPath(runId, '/stop'), post()), 'Could not stop the migration');
}

/**
 * Set a stopped, failed or partly failed copy running again.
 *
 * @param runId - The run.
 * @param credentials - The source's credentials, again.
 * @returns The run, running.
 */
export async function resumeMigration(runId: string, credentials: Credentials): Promise<MigrationRun> {
  return readJson<MigrationRun>(await fetch(runPath(runId, '/resume'), post(credentials)), 'Could not resume the migration');
}
