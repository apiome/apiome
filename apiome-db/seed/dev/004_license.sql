-- Dev seed: a sample license-plan catalog row (free tier).
-- `seats` carries the full canonical key set (V097 seats + the V195 quota keys)
-- so a freshly seeded dev database exposes the project/version/AI limits the same
-- way the migrated Free tier does.

INSERT INTO apiome.licenses (id, name, description, license_type, seats, enabled)
VALUES (
  '00000000-0000-4000-8000-000000000003',
  'Dev',
  'Sample free-tier license plan for local development.',
  'free',
  '{"max_tenants":1,"max_users_per_tenant":5,"max_projects":1,"max_versions":3,"max_ai_requests":0}',
  true
)
ON CONFLICT (id) DO NOTHING;
