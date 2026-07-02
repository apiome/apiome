-- Dev seed: a sample license-plan catalog row (free tier).

INSERT INTO apiome.licenses (id, name, description, license_type, enabled)
VALUES (
  '00000000-0000-4000-8000-000000000003',
  'Dev',
  'Sample free-tier license plan for local development.',
  'free',
  true
)
ON CONFLICT (id) DO NOTHING;
