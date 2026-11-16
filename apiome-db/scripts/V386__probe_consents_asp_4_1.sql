-- Probe consent and security probe reports for verification targets — ASP-4.1 (#5939).
--
-- CLX-3.3 (V173) gave MCP endpoints a consent model for active probes: an allowlisted target, a
-- declared owner, an acknowledging user, a dedicated test identity, a stronger approval for hostile
-- payloads, a kill switch, tenant caps and an audit row for every run and refusal. REST security
-- probes (ASP-4.2/4.3) fire at ECA-1.2 verification targets and need the same guarantees, keyed to
-- the target instead of to an MCP endpoint. The policy code is shared (app.probe_consent); this
-- migration adds the two tables it reads and writes:
--
--   * ``verification_target_probe_consents`` — who authorized probing which target, until when,
--                                              for which profiles, and as which test identities.
--   * ``security_probe_reports``             — the write-once record of one probe run, like V252's
--                                              provider verification report.
--
-- Rules the schema keeps (rather than trusting the application to remember):
--
--   1. **A consent is explicit, attributable and bounded.** ``ownership_declared`` must be TRUE,
--      ``approved_by``/``approved_at``/``expires_at`` are NOT NULL and ``expires_at`` must follow
--      ``approved_at`` — a consent that lasts forever is not one.
--   2. **A consent never holds a secret.** ``identity_a`` and ``identity_b`` are ECA-1.2 credential
--      *references* with the same CHECK constraints V211 puts on ``verification_target``: an ``env``
--      ref is an environment-variable NAME, a ``stored`` ref is a credential-vault UUID. A pasted
--      bearer token or JWT cannot satisfy either shape, so it cannot be stored as an identity.
--   3. **One live consent per target.** A partial unique index on the unrevoked rows; granting a new
--      consent revokes the old one in the same transaction.
--   4. **A consent is revoked, never edited.** A BEFORE UPDATE trigger allows only ``revoked_at`` and
--      ``revoked_by`` to change, and only from NULL — so the terms a run was authorized under are the
--      terms on the row.
--   5. **Neither table can cross tenants.** Both carry ``tenant_id`` and reference the target by the
--      composite ``(id, tenant_id)`` key added below; the report's evidence run likewise uses V212's
--      ``verification_run (id, tenant_id)`` key.
--   6. **A report is write-once.** The shared V128 guard rejects every UPDATE, as on V252.
--
-- The kill switch is the ``security_probe_enabled`` setting (default false), not a table: it is an
-- operator flag for the whole deployment, not tenant data.
--
-- No new RBAC resource: granting consent and running a probe both need
-- ``verification_evidence:create`` (V212), reading reports needs ``verification_evidence:view``, and a
-- production target's consent additionally needs a tenant administrator (checked in apiome-rest).
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP FUNCTION IF EXISTS apiome.purge_security_probe_reports(INTEGER);
--   DROP TABLE IF EXISTS apiome.security_probe_reports;
--   DROP TABLE IF EXISTS apiome.verification_target_probe_consents;
--   DROP FUNCTION IF EXISTS apiome.verification_target_probe_consent_guard();
--   ALTER TABLE apiome.verification_target DROP CONSTRAINT IF EXISTS verification_target_id_tenant_key;
-- (The V128 guard function apiome.mcp_forbid_row_mutation() is shared — do not drop it here.)

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- Composite key so tenant-scoped tables can reference a target and its tenant together (rule 5).
-- ``id`` is already the primary key, so this adds no new uniqueness — only a referenceable pair.
-- ---------------------------------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'verification_target_id_tenant_key'
          AND conrelid = 'apiome.verification_target'::regclass
    ) THEN
        ALTER TABLE verification_target
            ADD CONSTRAINT verification_target_id_tenant_key UNIQUE (id, tenant_id);
    END IF;
END
$$;

-- ---------------------------------------------------------------------------------------------------
-- verification_target_probe_consents — authorization to probe one target.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS verification_target_probe_consents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    target_id UUID NOT NULL,

    -- Rule 1. The grantor's assertion that they own the target or are authorized to test it.
    ownership_declared BOOLEAN NOT NULL
        CONSTRAINT verification_target_probe_consents_ownership_check
            CHECK (ownership_declared),

    -- Rule 1. Who granted it, when, and until when. Deleting the approver removes the consent: a
    -- consent nobody can answer for fails closed.
    approved_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    approved_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT verification_target_probe_consents_expiry_check
        CHECK (expires_at > approved_at),

    -- The REST probe profiles this consent authorizes (app.probe_consent.TARGET_PROFILE_IDS).
    profiles_allowed TEXT[] NOT NULL,
    CONSTRAINT verification_target_probe_consents_profiles_check
        CHECK (
            cardinality(profiles_allowed) > 0
            AND profiles_allowed <@ ARRAY['passive', 'safe-active', 'payload']::TEXT[]
        ),

    -- Rule 2. Test identity A — a credential reference, never a credential. NULL kind = no identity.
    identity_a_kind TEXT
        CONSTRAINT verification_target_probe_consents_identity_a_kind_check
            CHECK (identity_a_kind IS NULL OR identity_a_kind IN ('env', 'stored')),
    identity_a_scheme TEXT
        CONSTRAINT verification_target_probe_consents_identity_a_scheme_check
            CHECK (identity_a_scheme IS NULL OR identity_a_scheme IN ('bearer', 'header', 'basic')),
    identity_a_ref TEXT,
    identity_a_header_name TEXT,

    -- Rule 2. Test identity B — the second identity ASP-4.3's BOLA/BFLA probes need.
    identity_b_kind TEXT
        CONSTRAINT verification_target_probe_consents_identity_b_kind_check
            CHECK (identity_b_kind IS NULL OR identity_b_kind IN ('env', 'stored')),
    identity_b_scheme TEXT
        CONSTRAINT verification_target_probe_consents_identity_b_scheme_check
            CHECK (identity_b_scheme IS NULL OR identity_b_scheme IN ('bearer', 'header', 'basic')),
    identity_b_ref TEXT,
    identity_b_header_name TEXT,

    -- Rule 4. Revocation is the only change a consent row may take. ``revoked_by`` is a soft
    -- reference: a revoked row is immutable, so an ON DELETE SET NULL action on it would be rejected
    -- by the guard and make deleting the revoking user fail.
    revoked_at TIMESTAMPTZ,
    revoked_by UUID,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Rule 5. The target must be in the same tenant; retiring the target's row takes the consent.
    CONSTRAINT verification_target_probe_consents_target_fk
        FOREIGN KEY (target_id, tenant_id)
        REFERENCES verification_target (id, tenant_id)
        ON DELETE CASCADE,

    -- Rule 2, identity A: the same shapes V211 enforces on verification_target.
    CONSTRAINT verification_target_probe_consents_identity_a_empty_check
        CHECK (
            identity_a_kind IS NOT NULL
            OR (identity_a_scheme IS NULL AND identity_a_ref IS NULL AND identity_a_header_name IS NULL)
        ),
    CONSTRAINT verification_target_probe_consents_identity_a_complete_check
        CHECK (identity_a_kind IS NULL OR (identity_a_scheme IS NOT NULL AND identity_a_ref IS NOT NULL)),
    CONSTRAINT verification_target_probe_consents_identity_a_env_ref_check
        CHECK (identity_a_kind IS DISTINCT FROM 'env' OR identity_a_ref ~ '^[A-Z_][A-Z0-9_]*$'),
    CONSTRAINT verification_target_probe_consents_identity_a_stored_ref_check
        CHECK (
            identity_a_kind IS DISTINCT FROM 'stored'
            OR identity_a_ref ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
        ),
    CONSTRAINT verification_target_probe_consents_identity_a_header_check
        CHECK (
            (identity_a_scheme = 'header' AND identity_a_header_name ~ '^[!#$%&''*+.^_`|~0-9A-Za-z-]+$')
            OR (identity_a_scheme IS DISTINCT FROM 'header' AND identity_a_header_name IS NULL)
        ),

    -- Rule 2, identity B.
    CONSTRAINT verification_target_probe_consents_identity_b_empty_check
        CHECK (
            identity_b_kind IS NOT NULL
            OR (identity_b_scheme IS NULL AND identity_b_ref IS NULL AND identity_b_header_name IS NULL)
        ),
    CONSTRAINT verification_target_probe_consents_identity_b_complete_check
        CHECK (identity_b_kind IS NULL OR (identity_b_scheme IS NOT NULL AND identity_b_ref IS NOT NULL)),
    CONSTRAINT verification_target_probe_consents_identity_b_env_ref_check
        CHECK (identity_b_kind IS DISTINCT FROM 'env' OR identity_b_ref ~ '^[A-Z_][A-Z0-9_]*$'),
    CONSTRAINT verification_target_probe_consents_identity_b_stored_ref_check
        CHECK (
            identity_b_kind IS DISTINCT FROM 'stored'
            OR identity_b_ref ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
        ),
    CONSTRAINT verification_target_probe_consents_identity_b_header_check
        CHECK (
            (identity_b_scheme = 'header' AND identity_b_header_name ~ '^[!#$%&''*+.^_`|~0-9A-Za-z-]+$')
            OR (identity_b_scheme IS DISTINCT FROM 'header' AND identity_b_header_name IS NULL)
        ),

    -- A revocation is attributable to a moment.
    CONSTRAINT verification_target_probe_consents_revoked_by_check
        CHECK (revoked_by IS NULL OR revoked_at IS NOT NULL)
);

-- Rule 3: one live consent per target.
CREATE UNIQUE INDEX IF NOT EXISTS idx_verification_target_probe_consents_live
    ON verification_target_probe_consents (target_id)
    WHERE revoked_at IS NULL;

-- "This target's consent history", newest first.
CREATE INDEX IF NOT EXISTS idx_verification_target_probe_consents_target
    ON verification_target_probe_consents (tenant_id, target_id, created_at DESC);

-- Rule 4: only an unrevoked row may be revoked, and nothing else may change.
CREATE OR REPLACE FUNCTION verification_target_probe_consent_guard()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.revoked_at IS NOT NULL THEN
        RAISE EXCEPTION 'verification_target_probe_consents row % is revoked and immutable', OLD.id
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.revoked_at IS NULL
        OR (to_jsonb(NEW) - 'revoked_at' - 'revoked_by') IS DISTINCT FROM
           (to_jsonb(OLD) - 'revoked_at' - 'revoked_by') THEN
        RAISE EXCEPTION 'verification_target_probe_consents rows may only be revoked, never edited'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_verification_target_probe_consents_guard
    ON verification_target_probe_consents;
CREATE TRIGGER trigger_verification_target_probe_consents_guard
    BEFORE UPDATE ON verification_target_probe_consents
    FOR EACH ROW
    EXECUTE FUNCTION verification_target_probe_consent_guard();

COMMENT ON TABLE verification_target_probe_consents IS
    'ASP-4.1: authorization to run security probes against one verification target — ownership '
    'declaration, approver, expiry, allowed profiles and secret-free test identity references. '
    'Revoked, never edited.';
COMMENT ON COLUMN verification_target_probe_consents.profiles_allowed IS
    'REST probe profiles this consent authorizes: passive | safe-active | payload.';
COMMENT ON COLUMN verification_target_probe_consents.identity_a_ref IS
    'Environment-variable NAME (env) or credential-vault UUID (stored) for test identity A; never a secret.';
COMMENT ON COLUMN verification_target_probe_consents.identity_b_ref IS
    'Environment-variable NAME (env) or credential-vault UUID (stored) for test identity B; never a secret.';

-- ---------------------------------------------------------------------------------------------------
-- security_probe_reports — the write-once record of one probe run.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS security_probe_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Target identity snapshot, as V252 does: renaming or re-pointing a target cannot rewrite what a
    -- past probe claimed to have tested.
    --
    -- ``target_id`` and ``consent_id`` are deliberately soft references, not foreign keys (the V236
    -- precedent): the row is write-once, so an ON DELETE SET NULL action would be an UPDATE the
    -- immutability trigger rejects, and deleting a target or a consent's approver would fail
    -- outright. The ids keep their values for the life of the report, which is what an audit wants.
    target_id UUID,
    target_slug VARCHAR(200) NOT NULL,
    target_environment VARCHAR(32) NOT NULL,
    target_network_class VARCHAR(16) NOT NULL DEFAULT 'public',
    target_base_url TEXT NOT NULL,

    profile VARCHAR(32) NOT NULL
        CONSTRAINT security_probe_reports_profile_check
            CHECK (profile IN ('passive', 'safe-active', 'payload')),

    -- The consent that authorized the run (soft reference, see above). Revoking the consent later
    -- does not rewrite the report.
    consent_id UUID,
    hosted_mock BOOLEAN NOT NULL DEFAULT FALSE,
    explicit_approval BOOLEAN NOT NULL DEFAULT FALSE,

    -- The strongest tier this run could report: observed on the hosted mock, exploited-in-test
    -- elsewhere. A report can never count a finding above its ceiling.
    proof_ceiling VARCHAR(32) NOT NULL
        CONSTRAINT security_probe_reports_proof_ceiling_check
            CHECK (proof_ceiling IN ('observed', 'exploited-in-test')),
    CONSTRAINT security_probe_reports_mock_ceiling_check
        CHECK (NOT hosted_mock OR proof_ceiling = 'observed'),
    -- Only the hosted mock runs without a consent.
    CONSTRAINT security_probe_reports_consent_required_check
        CHECK (hosted_mock OR consent_id IS NOT NULL),

    -- The ProbeLimits the run carried.
    limits JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT security_probe_reports_limits_object_check
        CHECK (jsonb_typeof(limits) = 'object'),

    -- Counts by proof tier, as columns so the security axis and the gate need no JSON walk.
    count_suspected INTEGER NOT NULL DEFAULT 0 CHECK (count_suspected >= 0),
    count_observed INTEGER NOT NULL DEFAULT 0 CHECK (count_observed >= 0),
    count_exploited_in_test INTEGER NOT NULL DEFAULT 0 CHECK (count_exploited_in_test >= 0),
    CONSTRAINT security_probe_reports_ceiling_respected_check
        CHECK (proof_ceiling = 'exploited-in-test' OR count_exploited_in_test = 0),

    -- The full report body. Never null.
    report JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT security_probe_reports_report_object_check
        CHECK (jsonb_typeof(report) = 'object'),

    -- The ECA-1.3 evidence run, when one was written (ASP-4.4). Same-tenant by construction, and —
    -- as on V252 — the report goes with its run (a DELETE, which the write-once trigger allows).
    evidence_run_id UUID,
    CONSTRAINT security_probe_reports_evidence_run_fk
        FOREIGN KEY (evidence_run_id, tenant_id)
        REFERENCES verification_run (id, tenant_id)
        ON DELETE CASCADE,

    -- ``created_by`` is a soft reference for the same reason as ``target_id``: a departing user must
    -- not take the record of a probe with them, and must not be undeletable because of it.
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by UUID,
    actor_label VARCHAR(320),
    actor_kind VARCHAR(16) NOT NULL DEFAULT 'user'
        CONSTRAINT security_probe_reports_actor_kind_check
            CHECK (actor_kind IN ('user', 'api_key', 'system'))
);

-- "The tenant's newest reports" and "the tenant's runs in the last hour" (the hourly cap).
CREATE INDEX IF NOT EXISTS idx_security_probe_reports_tenant
    ON security_probe_reports (tenant_id, created_at DESC);

-- One report per evidence run.
CREATE UNIQUE INDEX IF NOT EXISTS idx_security_probe_reports_evidence_run
    ON security_probe_reports (evidence_run_id)
    WHERE evidence_run_id IS NOT NULL;

-- "Everything probed against this target."
CREATE INDEX IF NOT EXISTS idx_security_probe_reports_target
    ON security_probe_reports (tenant_id, target_id, created_at DESC);

-- Rule 6: write-once.
DROP TRIGGER IF EXISTS trigger_security_probe_reports_immutable ON security_probe_reports;
CREATE TRIGGER trigger_security_probe_reports_immutable
    BEFORE UPDATE ON security_probe_reports
    FOR EACH ROW
    EXECUTE FUNCTION mcp_forbid_row_mutation();

-- Retention, matching the provider verification report sweep.
CREATE OR REPLACE FUNCTION purge_security_probe_reports(p_retention_days INTEGER DEFAULT 365)
RETURNS INTEGER AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    DELETE FROM apiome.security_probe_reports
    WHERE created_at < CURRENT_TIMESTAMP - (p_retention_days || ' days')::INTERVAL;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

COMMENT ON TABLE security_probe_reports IS
    'ASP-4.1: write-once record of one security probe run against a verification target — target '
    'snapshot, profile, consent, limits, proof ceiling, counts by tier and the report body. '
    'Governed by the verification_evidence RBAC resource.';
COMMENT ON COLUMN security_probe_reports.proof_ceiling IS
    'Strongest tier the run could report: observed on the Apiome-hosted mock, exploited-in-test elsewhere.';
