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
});

module.exports = connectionPool;
