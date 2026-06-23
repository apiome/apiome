-- Dev seed: a sample API key for the sample tenant.
--
-- Raw key (DEV ONLY — never load in production):
--   sk_devseed00000000000000000000000000000000000000000000000000000000
-- Stored as key_prefix (sk_devseed00...) + bcrypt(key) hash, exactly as objectified-rest expects.

INSERT INTO odb.api_keys (id, tenant_id, name, description, key_hash, key_prefix)
VALUES (
  '00000000-0000-4000-8000-000000000004',
  '00000000-0000-4000-8000-000000000002',
  'dev-seed-key',
  'Sample API key for local development.',
  '$2b$10$h6tBQLybes.dgWKLsQVbn.00kbqqq/vJbKYl/wpA.sPXsCbZ2RdTi',
  'sk_devseed00...'
)
ON CONFLICT (id) DO NOTHING;
