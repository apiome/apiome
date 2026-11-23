import { Pool } from 'pg';

/**
 * The `statement_timeout` session option for the pool.
 *
 * @returns ` -c statement_timeout=<ms>` from `DB_STATEMENT_TIMEOUT_MS` (default 30000), or `''`
 *   when it is `0`.
 */
export function statementTimeoutOption(): string {
  const parsed = parseInt(process.env.DB_STATEMENT_TIMEOUT_MS || '', 10);
  const ms = Number.isFinite(parsed) && parsed >= 0 ? parsed : 30000;
  return ms > 0 ? ` -c statement_timeout=${ms}` : '';
}

/** Default size of the Browse connection pool. */
export const DEFAULT_DB_POOL_MAX = 10;

/**
 * How many connections this Browse process may hold.
 *
 * @returns `DB_POOL_MAX` when it is a whole number ≥ 1, otherwise {@link DEFAULT_DB_POOL_MAX}.
 */
export function poolMax(): number {
  const raw = (process.env.DB_POOL_MAX ?? '').trim();
  const parsed = /^\d+$/.test(raw) ? Number.parseInt(raw, 10) : 0;
  return parsed >= 1 ? parsed : DEFAULT_DB_POOL_MAX;
}

/** PostgreSQL's SQLSTATE for a statement cancelled by `statement_timeout` (`query_canceled`). */
const QUERY_CANCELED = '57014';

/**
 * Whether an error from the pool is a statement that ran past `statement_timeout`.
 *
 * @param err - Anything a `pool.query` call rejected with.
 * @returns True for PostgreSQL's `query_canceled`.
 */
export function isStatementTimeout(err: unknown): boolean {
  return typeof err === 'object' && err !== null && (err as { code?: unknown }).code === QUERY_CANCELED;
}

const connectionPool = new Pool({
  connectionString: process.env.DATABASE_URL || '',
  user: process.env.POSTGRES_USER,
  host: process.env.POSTGRES_HOST,
  database: process.env.POSTGRES_DB,
  password: process.env.POSTGRES_PASSWORD,
  port: parseInt(process.env.POSTGRES_PORT || '5432', 10),
  // Shown in `pg_stat_activity`, so an operator can tell this app's sessions from the others'.
  application_name: 'apiome-browse',
  // Stated, not left to the `pg` default, so the deployment's connection budget is a number an
  // operator set: `DB_POOL_MAX` × Browse instances count against PostgreSQL's `max_connections`
  // (DBP-1.16, #7199). A page view holds a few of these at once; the directory cache keeps the
  // global reads off them.
  max: poolMax(),
  // With every client checked out, a request waits this long for one and then fails. The `pg`
  // default is to wait forever, which turns a busy or stuck pool into a hung site.
  connectionTimeoutMillis: 10000,
  keepAlive: true,
  // Browse only reads: a statement blocked on a lock fails after 30 s, and one still running after
  // `DB_STATEMENT_TIMEOUT_MS` (default 30 s, `0` turns it off) is cancelled, instead of holding a
  // client (DBP-1.15, #7198).
  //
  // `jit=off` (DBP-1.16, #7199): every Browse statement is a short read. PostgreSQL's JIT compiler
  // switches on by estimated cost, and the planner over-estimates the search palette's bounded
  // sub-selects, so a suggestion that executes in 30 ms spent a further 200 ms compiling.
  options: `-c lock_timeout=30000 -c idle_in_transaction_session_timeout=60000 -c jit=off${statementTimeoutOption()}`,
});

// An idle client whose connection drops emits `error` on the pool; unhandled, that event would
// take the process down. The pool has already discarded the client.
connectionPool.on('error', (error: Error) => {
  console.error('[apiome-browse/db] idle database client error:', error.message);
});

export default connectionPool;
