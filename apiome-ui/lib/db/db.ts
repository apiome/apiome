// `pg` is a CommonJS module; like the other lib/db consumers it is pulled in with `require`.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { Pool } = require('pg');
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { instrumentClient } = require('./statement-stats');

if (!process.env.DATABASE_URL && process.env.NODE_ENV !== 'production') {
  console.warn(
    '[apiome-ui/db] DATABASE_URL is not set; using libpq/POSTGRES_* defaults. ' +
      'Set DATABASE_URL to the same value as apiome-rest/.env so tenant membership matches the REST API.'
  );
}

/** A whole number of milliseconds (or a count) from the environment, or the default. */
function envInt(name: string, fallback: number): number {
  const parsed = parseInt(process.env[name] || '', 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

// Session limits, so one stuck statement cannot hold a pooled client forever: a statement waiting
// on a lock fails after `lock_timeout`, and a session left inside an open transaction is ended by
// PostgreSQL (releasing its locks) after `idle_in_transaction_session_timeout`. `0` turns one off.
const lockTimeoutMs = envInt('DB_LOCK_TIMEOUT_MS', 30000);
const idleInTransactionTimeoutMs = envInt('DB_IDLE_IN_TRANSACTION_TIMEOUT_MS', 60000);

const connectionPool = new Pool({
  connectionString: process.env.DATABASE_URL || '',
  user: process.env.POSTGRES_USER,
  host: process.env.POSTGRES_HOST,
  database: process.env.POSTGRES_DB,
  password: process.env.POSTGRES_PASSWORD,
  port: parseInt(process.env.POSTGRES_PORT || '5432', 10),
  // Shown in `pg_stat_activity`, so an operator can tell this app's sessions from the REST API's.
  application_name: 'apiome-ui',
  max: envInt('DB_POOL_MAX', 10) || 10,
  // With every client checked out, a request waits this long for one and then fails. The `pg`
  // default is to wait forever, which turns a busy or stuck pool into a hung application.
  connectionTimeoutMillis: envInt('DB_POOL_CONNECTION_TIMEOUT_MS', 10000),
  keepAlive: true,
  // Pin the runtime search_path to `apiome, public` — the same path the Flyway migrations run under
  // (`SET search_path TO apiome, public`). The app's own SQL is `apiome.`-qualified so it never relied
  // on this, but Better Auth (OLO-10.x) queries its `account`/`session`/`verification`/`two_factor`
  // tables UNQUALIFIED via its Kysely adapter; without the schema in the path those resolve to `public`
  // and fail ("relation \"verification\" does not exist"). `public` stays as the fallback so extensions
  // and any public objects still resolve. Applied to every pooled connection via the libpq `options`.
  options:
    '-c search_path=apiome,public' +
    (lockTimeoutMs > 0 ? ` -c lock_timeout=${lockTimeoutMs}` : '') +
    (idleInTransactionTimeoutMs > 0
      ? ` -c idle_in_transaction_session_timeout=${idleInTransactionTimeoutMs}`
      : ''),
});

// An idle client whose connection drops (a database restart, or PostgreSQL ending an idle
// transaction) emits `error` on the pool. Unhandled, that event would take the process down; the
// pool has already discarded the client, so logging is all there is to do.
connectionPool.on('error', (error: Error) => {
  console.error('[apiome-ui/db] idle database client error:', error.message);
});

// Count every statement each pooled client runs (DBP-1.1, #7184): `pool.query` and checked-out
// clients both go through the client's `query`. See lib/db/statement-stats.ts.
connectionPool.on('connect', (client: { query: (...args: unknown[]) => unknown }) => {
  instrumentClient(client);
});

module.exports = connectionPool;
