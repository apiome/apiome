/**
 * How the Browse loaders run a statement (DBP-1.27, #7210).
 *
 * {@link dbQuery} is `pool.query` with one difference: a failure is logged, reported to
 * `lib/db/availability.ts` when it is a connection failure, and rethrown as
 * {@link DatabaseUnavailableError}. A loader therefore has two honest outcomes — rows, or an
 * error — and "no row" only ever means the thing does not exist. See `lib/db/errors.ts` for what
 * each kind of caller does with the error.
 */

import type { QueryConfig, QueryResult, QueryResultRow } from 'pg';
import connectionPool from './db';
import { isConnectionFailure, noteConnectionFailure } from './availability';
import { DatabaseUnavailableError } from './errors';

/**
 * Run one statement.
 *
 * @param scope - The loader's name, for the log line.
 * @param statement - SQL text, or a `pg` query config (a named statement).
 * @param values - The statement's parameters (with SQL text).
 * @returns The query result.
 * @throws DatabaseUnavailableError When the statement could not be run or failed.
 */
// Rows default to `any`, as `pool.query` does: most callers hand them straight to a component.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function dbQuery<R extends QueryResultRow = any>(
  scope: string,
  statement: string | QueryConfig,
  values?: unknown[]
): Promise<QueryResult<R>> {
  try {
    return typeof statement === 'string'
      ? await connectionPool.query<R>(statement, values)
      : await connectionPool.query<R>(statement);
  } catch (err) {
    const message = (err as { message?: string } | null)?.message ?? String(err);
    console.error(`[db] ${scope}:`, message);
    if (isConnectionFailure(err)) noteConnectionFailure();
    throw new DatabaseUnavailableError(scope, err);
  }
}

/**
 * Run a loader that only decorates a page, returning `fallback` when the database fails.
 *
 * @param fallback - What the page shows instead (an empty list).
 * @param loader - The loader; its {@link DatabaseUnavailableError} is swallowed (it was logged).
 * @returns The loader's value, or `fallback`.
 */
export async function softly<T>(fallback: T, loader: () => Promise<T>): Promise<T> {
  try {
    return await loader();
  } catch (err) {
    if (err instanceof DatabaseUnavailableError) return fallback;
    throw err;
  }
}
