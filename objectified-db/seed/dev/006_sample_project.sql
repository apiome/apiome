-- Dev seed: provision the curated "Pet Store" sample project for the dev tenant (acme-corp),
-- owned by the dev user (ada). Uses the shared odb.provision_sample_project() routine (migration
-- V122), so the dev stack mirrors what every freshly-created tenant gets. Idempotent: the function
-- returns NULL (no-op) when the sample already exists for the tenant.

SELECT odb.provision_sample_project(
  '00000000-0000-4000-8000-000000000002',  -- acme-corp tenant (002_tenant.sql)
  '00000000-0000-4000-8000-000000000001'   -- ada user (001_user.sql)
);
