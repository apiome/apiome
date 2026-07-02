-- Dev seed: make the sample user a member and administrator of the sample tenant.

INSERT INTO apiome.tenant_users (tenant_id, user_id)
VALUES (
  '00000000-0000-4000-8000-000000000002',
  '00000000-0000-4000-8000-000000000001'
)
ON CONFLICT (tenant_id, user_id) DO NOTHING;

INSERT INTO apiome.tenant_administrators (tenant_id, user_id)
VALUES (
  '00000000-0000-4000-8000-000000000002',
  '00000000-0000-4000-8000-000000000001'
)
ON CONFLICT (tenant_id, user_id) DO NOTHING;
