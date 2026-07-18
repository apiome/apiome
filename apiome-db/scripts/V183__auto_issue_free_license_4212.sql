-- Auto-issue the Free license on tenant creation + backfill (OLO-5.2, #4212).
--
-- V182 gave tenants a place to hold a license (`apiome.tenant_licenses`) but nothing writes the
-- row: a tenant is born unlicensed, and enforcement (OLO-5.3, #4213) would 403 every tenant that
-- never picked a plan. The lightweight license must exist without user action, so this migration
-- makes the Free plan attach itself:
--
--   1. `apiome.attach_free_license(p_tenant_id)` — the single service function every create path
--      funnels through. Looks up the Free plan from the V097 catalog and inserts the tenant's
--      `tenant_licenses` row. Idempotent (`ON CONFLICT (tenant_id) DO NOTHING`): a tenant that
--      already holds a license — Free or paid — is never downgraded or duplicated.
--   2. An AFTER INSERT trigger on `apiome.tenants` calls it FOR EACH ROW, so *every* create path
--      (REST provisioning OLO-4.3, UI admin tools, CLI seeds) attaches Free **in the same
--      transaction** as the tenant insert — the row exists or the tenant does not.
--   3. Backfill: every pre-existing tenant without a `tenant_licenses` row gets Free, including
--      disabled/soft-deleted tenants (they can be re-enabled/restored and must not surface as
--      unlicensed then). Ordering rule: this ships BEFORE enforcement (OLO-5.3) so no tenant is
--      stranded when the 403s arrive.
--
-- Failure posture: if the Free plan is missing from the catalog (a broken deployment — V097 seeds
-- it), the function RAISEs a WARNING and returns NULL rather than aborting tenant creation.
-- Enforcement (5.3) will treat such a tenant as unlicensed; creating the tenant anyway is the
-- lesser harm and the warning makes the misconfiguration visible in the Postgres log.
SET search_path TO apiome, public;

-- ─── 1. Single service function ──────────────────────────────────────────────

CREATE OR REPLACE FUNCTION apiome.attach_free_license(p_tenant_id UUID)
RETURNS UUID AS $$
DECLARE
    v_license_id UUID;
    v_row_id     UUID;
BEGIN
    SELECT id
    INTO   v_license_id
    FROM   apiome.licenses
    WHERE  name = 'Free' AND license_type = 'free'
    LIMIT  1;

    IF v_license_id IS NULL THEN
        RAISE WARNING
            'attach_free_license: Free plan missing from apiome.licenses; tenant % left unlicensed',
            p_tenant_id;
        RETURN NULL;
    END IF;

    INSERT INTO apiome.tenant_licenses (tenant_id, license_id, notes)
    VALUES (p_tenant_id, v_license_id, 'auto-issued Free on tenant creation (OLO-5.2)')
    ON CONFLICT (tenant_id) DO NOTHING
    RETURNING id INTO v_row_id;

    RETURN v_row_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.attach_free_license(UUID) IS
  'Attach the Free catalog plan (V097) to a tenant. Idempotent: no-op when the tenant already '
  'holds any license. Returns the new tenant_licenses id, or NULL when skipped (already licensed '
  'or Free plan missing). The single service function for default licensing (OLO-5.2, #4212).';

-- ─── 2. Trigger: every tenant-create path, same transaction ──────────────────

CREATE OR REPLACE FUNCTION apiome.tenants_attach_free_license()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM apiome.attach_free_license(NEW.id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.tenants_attach_free_license() IS
  'AFTER INSERT trigger body on apiome.tenants: auto-issue the Free license to every new tenant '
  'in the same transaction as the insert (OLO-5.2, #4212).';

DROP TRIGGER IF EXISTS trigger_tenants_attach_free_license ON apiome.tenants;
CREATE TRIGGER trigger_tenants_attach_free_license
  AFTER INSERT ON apiome.tenants
  FOR EACH ROW
  EXECUTE FUNCTION apiome.tenants_attach_free_license();

-- ─── 3. Backfill: no pre-existing tenant left unlicensed ─────────────────────

INSERT INTO apiome.tenant_licenses (tenant_id, license_id, notes)
SELECT t.id, l.id, 'backfilled Free for pre-existing tenant (OLO-5.2, #4212)'
FROM   apiome.tenants t
CROSS  JOIN (
    SELECT id FROM apiome.licenses
    WHERE  name = 'Free' AND license_type = 'free'
    LIMIT  1
) l
WHERE  NOT EXISTS (
    SELECT 1 FROM apiome.tenant_licenses tl WHERE tl.tenant_id = t.id
)
ON CONFLICT (tenant_id) DO NOTHING;
