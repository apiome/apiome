import { Pool } from 'pg';

const connectionPool = new Pool({
  connectionString: process.env.DATABASE_URL || '',
  user: process.env.POSTGRES_USER,
  host: process.env.POSTGRES_HOST,
  database: process.env.POSTGRES_DB,
  password: process.env.POSTGRES_PASSWORD,
  port: parseInt(process.env.POSTGRES_PORT || '5432', 10),
  // Shown in `pg_stat_activity`, so an operator can tell this app's sessions from the others'.
  application_name: 'apiome-browse',
  // With every client checked out, a request waits this long for one and then fails. The `pg`
  // default is to wait forever, which turns a busy or stuck pool into a hung site.
  connectionTimeoutMillis: 10000,
  keepAlive: true,
  // Browse only reads: a statement blocked on a lock fails after 30 s instead of holding a client.
  options: '-c lock_timeout=30000 -c idle_in_transaction_session_timeout=60000',
});

// An idle client whose connection drops emits `error` on the pool; unhandled, that event would
// take the process down. The pool has already discarded the client.
connectionPool.on('error', (error: Error) => {
  console.error('[apiome-browse/db] idle database client error:', error.message);
});

export default connectionPool;
