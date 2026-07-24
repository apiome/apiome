// `pg` is a CommonJS module; like the other lib/db consumers it is pulled in with `require`.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { Pool } = require('pg');

if (!process.env.DATABASE_URL && process.env.NODE_ENV !== 'production') {
  console.warn(
    '[apiome-ui/db] DATABASE_URL is not set; using libpq/POSTGRES_* defaults. ' +
      'Set DATABASE_URL to the same value as apiome-rest/.env so tenant membership matches the REST API.'
  );
}

const connectionPool = new Pool({
  connectionString: process.env.DATABASE_URL || '',
  user: process.env.POSTGRES_USER,
  host: process.env.POSTGRES_HOST,
  database: process.env.POSTGRES_DB,
  password: process.env.POSTGRES_PASSWORD,
  port: parseInt(process.env.POSTGRES_PORT || '5432', 10),
  // Pin the runtime search_path to `apiome, public` — the same path the Flyway migrations run under
  // (`SET search_path TO apiome, public`). The app's own SQL is `apiome.`-qualified so it never relied
  // on this, but Better Auth (OLO-10.x) queries its `account`/`session`/`verification`/`two_factor`
  // tables UNQUALIFIED via its Kysely adapter; without the schema in the path those resolve to `public`
  // and fail ("relation \"verification\" does not exist"). `public` stays as the fallback so extensions
  // and any public objects still resolve. Applied to every pooled connection via the libpq `options`.
  options: '-c search_path=apiome,public',
});

module.exports = connectionPool;
