-- Pact verification results — PFX-1.4 (#6917).
--
-- V433 stores the pacts consumers publish. A provider's Pact verifier replays a pact against the
-- provider and publishes what happened; can-i-deploy (PFX-1.6) answers "is it safe?" from those
-- results. This migration stores them:
--
--   verification_result — one verification of one pact version by one provider version: success,
--                         the per-interaction test results, build URL, verifier name and version,
--                         and the provider branch it ran on.
--
-- Rules kept by the database:
--
--   1. **A result never changes.** A trigger refuses every UPDATE except the two the database makes
--      itself: `created_by` set to NULL when the user is deleted, and
--      `provider_verification_report_id` set to NULL when the linked report is deleted.
--   2. **Results are numbered per pact version.** `number` is 1, 2, 3 … for each pact version and is
--      UNIQUE with it, so `…/pact-version/{sha}/verification-results/{number}` names one result. It
--      is therefore also unique per (pact version, provider version, number), and that is the key
--      "the latest result of this pact version by this provider version" is read from.
--   3. **Nothing crosses a tenant.** The pact version is referenced by `(id, consumer_id,
--      provider_id)`, the provider version by `(id, pacticipant_id)` with the provider, and the
--      provider by `(id, tenant_id)`, so a result can only join rows of one tenant and one pair. The
--      optional CTG-4.3 report is referenced by `(id, tenant_id)` too.
--   4. **A result goes with its pact and its provider version.** Both references CASCADE.
--   5. **A CTG-4.3 report is linked, not copied.** `provider_verification_report_id` points at the
--      Apiome conformance report (V252) a result was produced with, when there is one. Deleting the
--      report clears the link (`SET NULL (provider_verification_report_id)`) and keeps the result.
--
-- What can-i-deploy reads — `success`, the two ids and `number` — are columns. The test results
-- stay in `test_results` JSONB and are read only when someone opens a result.
--
-- Online: one new table, and one unique index on `provider_verification_report (id, tenant_id)` built
-- in place (one row per conformance run).
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.verification_result;
--   DROP FUNCTION IF EXISTS apiome.verification_result_immutable();
--   ALTER TABLE apiome.provider_verification_report
--       DROP CONSTRAINT IF EXISTS provider_verification_report_id_tenant_key;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- 0. The composite key a linked CTG-4.3 report is referenced by (rule 3)
-- ---------------------------------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'provider_verification_report_id_tenant_key'
          AND conrelid = 'apiome.provider_verification_report'::regclass
    ) THEN
        ALTER TABLE apiome.provider_verification_report
            ADD CONSTRAINT provider_verification_report_id_tenant_key UNIQUE (id, tenant_id);
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------------------------------
-- 1. verification_result
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS verification_result (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- Constrained through the provider reference below.
    tenant_id UUID NOT NULL,
    consumer_id UUID NOT NULL,
    provider_id UUID NOT NULL,
    pact_version_id UUID NOT NULL,
    provider_version_id UUID NOT NULL,

    -- Rule 2: 1, 2, 3 … per pact version.
    number INTEGER NOT NULL
        CONSTRAINT verification_result_number_check CHECK (number >= 1),
    -- Order of recording across the table; "latest" compares this.
    seq BIGINT GENERATED ALWAYS AS IDENTITY,

    success BOOLEAN NOT NULL,
    build_url TEXT
        CONSTRAINT verification_result_build_url_check
            CHECK (build_url IS NULL
                   OR (build_url ~* '^https?://[^[:space:]]+$' AND length(build_url) <= 2048)),
    -- The provider branch the verification ran on, when known.
    provider_branch VARCHAR(255)
        CONSTRAINT verification_result_provider_branch_check
            CHECK (provider_branch IS NULL
                   OR (provider_branch <> '' AND provider_branch = btrim(provider_branch)
                       AND provider_branch !~ '[[:cntrl:]]')),
    -- The verifier's per-interaction results, as it sent them (an array; may be empty).
    test_results JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT verification_result_test_results_array_check CHECK (jsonb_typeof(test_results) = 'array'),

    -- Who verified: the verifier (`Pact-Rust` 1.2.0) and the client library around it.
    verified_by_implementation VARCHAR(255),
    verified_by_version VARCHAR(255),
    verified_by_client_implementation VARCHAR(255),
    verified_by_client_version VARCHAR(255),
    verified_by_client_test_framework VARCHAR(255),

    -- What the for-verification link said about the pact when it was fetched (PFX-1.3).
    pact_pending BOOLEAN,
    wip BOOLEAN NOT NULL DEFAULT FALSE,

    -- Rule 5.
    provider_verification_report_id UUID,

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_label TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT verification_result_number_key UNIQUE (pact_version_id, number),
    CONSTRAINT verification_result_version_number_key UNIQUE (pact_version_id, provider_version_id, number),
    CONSTRAINT verification_result_pact_version_fk
        FOREIGN KEY (pact_version_id, consumer_id, provider_id)
        REFERENCES pact_version (id, consumer_id, provider_id) ON DELETE CASCADE,
    CONSTRAINT verification_result_provider_version_fk
        FOREIGN KEY (provider_version_id, provider_id)
        REFERENCES pacticipant_version (id, pacticipant_id) ON DELETE CASCADE,
    CONSTRAINT verification_result_provider_fk
        FOREIGN KEY (provider_id, tenant_id)
        REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT verification_result_report_fk
        FOREIGN KEY (provider_verification_report_id, tenant_id)
        REFERENCES provider_verification_report (id, tenant_id)
        ON DELETE SET NULL (provider_verification_report_id)
);

-- "The latest result of this pact version by this provider version" (the matrix, PFX-1.6) is the
-- verification_result_version_number_key index read backwards. The others serve the remaining reads
-- and the referential checks: the latest result between a consumer and a provider (and the provider
-- reference), a pact version's results, a provider version's results, and the linked reports.
CREATE INDEX IF NOT EXISTS idx_verification_result_pair
    ON verification_result (provider_id, tenant_id, consumer_id, seq DESC);
CREATE INDEX IF NOT EXISTS idx_verification_result_pact_version
    ON verification_result (pact_version_id, consumer_id, provider_id);
CREATE INDEX IF NOT EXISTS idx_verification_result_provider_version
    ON verification_result (provider_version_id, provider_id);
CREATE INDEX IF NOT EXISTS idx_verification_result_report
    ON verification_result (provider_verification_report_id, tenant_id)
    WHERE provider_verification_report_id IS NOT NULL;

COMMENT ON TABLE verification_result IS
    'One verification of a pact version by a provider version, as a Pact verifier published it (PFX-1.4, #6917)';
COMMENT ON COLUMN verification_result.number IS 'Sequence number per pact version: 1, 2, 3 …';
COMMENT ON COLUMN verification_result.seq IS 'Order of recording across the table; latest compares this';
COMMENT ON COLUMN verification_result.success IS 'Whether every interaction passed';
COMMENT ON COLUMN verification_result.provider_branch IS 'The provider branch the verification ran on, when known';
COMMENT ON COLUMN verification_result.test_results IS 'The per-interaction test results as the verifier sent them';
COMMENT ON COLUMN verification_result.pact_pending IS 'Whether the pact was pending for this provider build when fetched';
COMMENT ON COLUMN verification_result.wip IS 'Whether the pact was fetched as a work-in-progress pact';
COMMENT ON COLUMN verification_result.provider_verification_report_id IS
    'The CTG-4.3 conformance report this result was produced with, if any; linked, not copied';

-- Rule 1.
CREATE OR REPLACE FUNCTION apiome.verification_result_immutable()
RETURNS trigger AS $$
BEGIN
    -- The changes allowed are the database's own: a deleted user or a deleted report clears its
    -- reference, and nothing else moves.
    IF (to_jsonb(NEW) - 'created_by' - 'provider_verification_report_id')
           = (to_jsonb(OLD) - 'created_by' - 'provider_verification_report_id')
       AND (NEW.created_by IS NULL OR NEW.created_by IS NOT DISTINCT FROM OLD.created_by)
       AND (NEW.provider_verification_report_id IS NULL
            OR NEW.provider_verification_report_id IS NOT DISTINCT FROM OLD.provider_verification_report_id) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'verification_result rows are immutable (result % of pact version %)',
        OLD.number, OLD.pact_version_id
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_verification_result_immutable ON verification_result;
CREATE TRIGGER trg_verification_result_immutable
    BEFORE UPDATE ON verification_result
    FOR EACH ROW
    EXECUTE FUNCTION apiome.verification_result_immutable();
