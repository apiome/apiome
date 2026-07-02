-- Dev seed: sample tenant (slug: acme-corp).

INSERT INTO apiome.tenants (id, name, slug, description, enabled)
VALUES (
  '00000000-0000-4000-8000-000000000002',
  'Acme Corp',
  'acme-corp',
  'Sample tenant for local development.',
  true
)
ON CONFLICT (id) DO NOTHING;
