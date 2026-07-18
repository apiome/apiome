-- Tenant→license attachment model (OLO-5.1, #4211).
--
-- The V097 license catalog (`apiome.licenses`: Free/Paid/Sponsor plans with a `seats` JSONB of
-- capacity limits) defines *what a license grants*, but no row records *which tenant holds which
-- license*. The only attachment so far is `user_entitlements.license_id` (V097), which binds a
-- license to a **user** and therefore cannot express per-tenant licensing.
--
-- This migration adds `apiome.tenant_licenses`, the single place a tenant's active license lives:
--
--   - `tenant_id` is UNIQUE → at most one active license per tenant, enforced at the DB level.
--     Changing a tenant's plan is an upsert of this one row, never a second row.
--   - `license_id` references the V097 catalog. Deleting a catalog plan that tenants still hold
--     is refused (ON DELETE RESTRICT) — a tenant must never point at a vanished plan.
--   - `issued_at` / `issued_by` / `notes` record provenance: when the license was attached, by
--     which admin, and why (e.g. "sponsor grant", "support upgrade").
--
-- Division of responsibility (documented here on the tables themselves):
--   - **user entitlement** (`user_entitlements`, V071/V097) = how many tenants a *user* may
--     create (`max_tenants`). Unchanged by this migration.
--   - **tenant license** (`tenant_licenses`, this migration) = what each *tenant* may do —
--     seats via the plan's `max_users_per_tenant`, features via `license_feature_flags`.
--
-- Feature-flag composition is unchanged: effective tenant features remain the license's
-- `license_feature_flags` bundle combined with per-tenant `tenant_feature_flags` overrides (V097).
--
-- No backfill here: OLO-5.2 (#4212) auto-issues the Free plan to existing and newly created
-- tenants; OLO-5.3 (#4213) adds enforcement.
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS tenant_licenses (
    id         UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id  UUID        NOT NULL REFERENCES apiome.tenants(id)  ON DELETE CASCADE,
    license_id UUID        NOT NULL REFERENCES apiome.licenses(id) ON DELETE RESTRICT,
    issued_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    issued_by  UUID        REFERENCES apiome.users(id) ON DELETE SET NULL,
    notes      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tenant_licenses_tenant_id UNIQUE (tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_tenant_licenses_license_id ON apiome.tenant_licenses (license_id);
CREATE INDEX IF NOT EXISTS idx_tenant_licenses_issued_by  ON apiome.tenant_licenses (issued_by);

COMMENT ON TABLE apiome.tenant_licenses IS
  'Active license per tenant (one row per tenant, UNIQUE tenant_id). Tenant license = what each '
  'tenant may do (seats, features); user entitlement (user_entitlements) = how many tenants a '
  'user may create. Plan changes upsert this row.';
COMMENT ON COLUMN apiome.tenant_licenses.tenant_id  IS
  'Tenant holding the license; UNIQUE so a tenant has at most one active license';
COMMENT ON COLUMN apiome.tenant_licenses.license_id IS
  'Plan from the apiome.licenses catalog (V097); RESTRICT blocks deleting a held plan';
COMMENT ON COLUMN apiome.tenant_licenses.issued_at  IS
  'When this license was attached to the tenant';
COMMENT ON COLUMN apiome.tenant_licenses.issued_by  IS
  'Admin user who attached the license; NULL when system-issued or the admin was deleted';
COMMENT ON COLUMN apiome.tenant_licenses.notes      IS
  'Free-form provenance (e.g. "sponsor grant", "auto-issued Free on tenant creation")';
