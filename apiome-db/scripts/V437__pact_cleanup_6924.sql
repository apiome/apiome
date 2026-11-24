-- Pacticipant labels, version delete and cleanup — PFX-1.11 (#6924).
--
-- A busy CI publishes a pacticipant version per commit, so the registry grows forever unless
-- something removes what nobody can deploy any more. This migration adds what that needs:
--
--   * a **soft delete** for pacticipants and versions: a delete stamps `deleted_at` (who, why, how),
--     and from then on the row is invisible to every read of apiome-rest — pacts, results, the
--     matrix, can-i-deploy, environments, webhooks, badges. It can be restored until it is purged;
--   * **purge**: apiome-rest's retention tick removes a stamped row for good once its grace period
--     (`APIOME_PACT_DELETION_GRACE_DAYS`, default 30) has passed. That hard delete cascades exactly
--     as the V432–V436 foreign keys already say;
--   * `pacticipant_label` — the Pact Broker's labels: free-form names grouped on a pacticipant.
--
-- Rules kept by the database:
--
--   1. **A name or a number is taken only while it is live.** The two natural keys become partial
--      unique indexes (`WHERE deleted_at IS NULL`), so a deleted `billing-service` or version
--      `1.0.0` can be published again, and the deleted row keeps its own history beside it.
--   2. **A delete is described.** `deleted_at` and `delete_cause` come together (a version also
--      says whether it was deleted by itself, with its pacticipant, or by a retention run).
--   3. **Versions still never mutate** — except their deletion stamp. V432's trigger is replaced
--      with one that compares the row without the deletion columns.
--   4. **A label exists once per pacticipant**, and cannot cross a tenant (`(pacticipant_id,
--      tenant_id)` references the pacticipant).
--
-- Branch heads are app-maintained (V432): when a version that heads a branch is deleted,
-- apiome-rest's `app.pacticipant_store` moves the head back to the branch's latest live version,
-- and moves it forward again on a restore.
--
-- Online: nullable columns only; the two unique constraints are replaced by partial indexes of the
-- same columns (both tables are small next to the revision tables); one new table.
--
-- Rollback notes (reverse carefully in shared environments; purge or restore stamped rows first,
-- or the unique constraints cannot be rebuilt):
--   DROP TABLE IF EXISTS apiome.pacticipant_label;
--   DROP INDEX IF EXISTS apiome.pacticipant_tenant_slug_live_key, apiome.pacticipant_version_number_live_key,
--       apiome.idx_pacticipant_deleted, apiome.idx_pacticipant_version_deleted;
--   ALTER TABLE apiome.pacticipant ADD CONSTRAINT pacticipant_tenant_slug_key UNIQUE (tenant_id, slug);
--   ALTER TABLE apiome.pacticipant_version
--       ADD CONSTRAINT pacticipant_version_number_key UNIQUE (pacticipant_id, number);
--   ALTER TABLE apiome.pacticipant DROP COLUMN deleted_at, DROP COLUMN deleted_by,
--       DROP COLUMN deleted_by_label, DROP COLUMN delete_reason;
--   ALTER TABLE apiome.pacticipant_version DROP COLUMN deleted_at, DROP COLUMN deleted_by,
--       DROP COLUMN deleted_by_label, DROP COLUMN delete_reason, DROP COLUMN delete_cause;
--   -- and re-apply the V432 body of apiome.pacticipant_version_immutable().

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- 1. Soft delete of pacticipants
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE pacticipant
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS deleted_by UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS deleted_by_label TEXT,
    ADD COLUMN IF NOT EXISTS delete_reason TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'pacticipant_delete_reason_check' AND conrelid = 'apiome.pacticipant'::regclass
    ) THEN
        ALTER TABLE apiome.pacticipant ADD CONSTRAINT pacticipant_delete_reason_check
            CHECK (delete_reason IS NULL OR (deleted_at IS NOT NULL AND length(delete_reason) <= 500));
    END IF;
END;
$$;

-- Rule 1: the handle is unique among live pacticipants only.
ALTER TABLE pacticipant DROP CONSTRAINT IF EXISTS pacticipant_tenant_slug_key;
CREATE UNIQUE INDEX IF NOT EXISTS pacticipant_tenant_slug_live_key
    ON pacticipant (tenant_id, slug)
    WHERE deleted_at IS NULL;
-- What a restore looks up, and what the purge reads, oldest first.
CREATE INDEX IF NOT EXISTS idx_pacticipant_deleted
    ON pacticipant (deleted_at)
    WHERE deleted_at IS NOT NULL;

COMMENT ON COLUMN pacticipant.deleted_at IS
    'Soft delete (PFX-1.11): when set, no read sees the pacticipant; purged after the grace period';
COMMENT ON COLUMN pacticipant.deleted_by IS 'Who deleted it, while the user exists';
COMMENT ON COLUMN pacticipant.deleted_by_label IS 'Who deleted it, as text, kept after the user row is gone';
COMMENT ON COLUMN pacticipant.delete_reason IS 'Why it was deleted, as the caller said (at most 500 characters)';

-- ---------------------------------------------------------------------------------------------------
-- 2. Soft delete of versions
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE pacticipant_version
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS deleted_by UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS deleted_by_label TEXT,
    ADD COLUMN IF NOT EXISTS delete_reason TEXT,
    -- Rule 2: `version` (deleted on its own), `pacticipant` (with its pacticipant; restored with it),
    -- `retention` (by a retention run).
    ADD COLUMN IF NOT EXISTS delete_cause VARCHAR(16);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'pacticipant_version_delete_cause_check'
          AND conrelid = 'apiome.pacticipant_version'::regclass
    ) THEN
        ALTER TABLE apiome.pacticipant_version ADD CONSTRAINT pacticipant_version_delete_cause_check
            CHECK ((deleted_at IS NULL AND delete_cause IS NULL)
                   OR (deleted_at IS NOT NULL AND delete_cause IS NOT NULL
                       AND delete_cause IN ('version', 'pacticipant', 'retention')));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'pacticipant_version_delete_reason_check'
          AND conrelid = 'apiome.pacticipant_version'::regclass
    ) THEN
        ALTER TABLE apiome.pacticipant_version ADD CONSTRAINT pacticipant_version_delete_reason_check
            CHECK (delete_reason IS NULL OR (deleted_at IS NOT NULL AND length(delete_reason) <= 500));
    END IF;
END;
$$;

-- Rule 1: the number is unique among a pacticipant's live versions only.
ALTER TABLE pacticipant_version DROP CONSTRAINT IF EXISTS pacticipant_version_number_key;
CREATE UNIQUE INDEX IF NOT EXISTS pacticipant_version_number_live_key
    ON pacticipant_version (pacticipant_id, number)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_pacticipant_version_deleted
    ON pacticipant_version (deleted_at)
    WHERE deleted_at IS NOT NULL;

COMMENT ON COLUMN pacticipant_version.deleted_at IS
    'Soft delete (PFX-1.11): when set, no read sees the version or its pacts, results and deployments; purged after the grace period';
COMMENT ON COLUMN pacticipant_version.deleted_by IS 'Who deleted it, while the user exists';
COMMENT ON COLUMN pacticipant_version.deleted_by_label IS 'Who deleted it, as text, kept after the user row is gone';
COMMENT ON COLUMN pacticipant_version.delete_reason IS 'Why it was deleted (at most 500 characters)';
COMMENT ON COLUMN pacticipant_version.delete_cause IS
    'version (deleted on its own), pacticipant (with its pacticipant) or retention (by a retention run)';

-- Rule 3. Replaces the V432 body: the deletion columns may change, nothing else may.
CREATE OR REPLACE FUNCTION apiome.pacticipant_version_immutable()
RETURNS trigger AS $$
DECLARE
    -- created_by goes to NULL when that user is deleted; the deletion stamp is set and cleared by
    -- apiome-rest's delete, restore and retention.
    mutable TEXT[] := ARRAY['created_by', 'deleted_at', 'deleted_by', 'deleted_by_label',
                            'delete_reason', 'delete_cause'];
BEGIN
    IF (to_jsonb(NEW) - mutable) = (to_jsonb(OLD) - mutable)
       AND (NEW.created_by IS NULL OR NEW.created_by IS NOT DISTINCT FROM OLD.created_by) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'pacticipant_version rows are immutable (version % of pacticipant %)',
        OLD.number, OLD.pacticipant_id
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.pacticipant_version_immutable() IS
    'Refuses every UPDATE of pacticipant_version except created_by being nulled by a user delete and the soft-delete stamp (PFX-1.1 #6914, PFX-1.11 #6924)';

-- ---------------------------------------------------------------------------------------------------
-- 3. pacticipant_label
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pacticipant_label (
    pacticipant_id UUID NOT NULL,
    -- Rule 4. Carried so "every label of the workspace" reads one index.
    tenant_id UUID NOT NULL,
    name VARCHAR(255) NOT NULL
        CONSTRAINT pacticipant_label_name_check
            CHECK (name <> '' AND name = btrim(name) AND name !~ '[[:cntrl:]]'),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pacticipant_label_pkey PRIMARY KEY (pacticipant_id, name),
    CONSTRAINT pacticipant_label_pacticipant_fk
        FOREIGN KEY (pacticipant_id, tenant_id)
        REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE
);

-- "Every label of the workspace" and "the pacticipants labelled `team-billing`".
CREATE INDEX IF NOT EXISTS idx_pacticipant_label_tenant_name
    ON pacticipant_label (tenant_id, name);

COMMENT ON TABLE pacticipant_label IS
    'Labels of a pacticipant — free-form names that group applications, as in the Pact Broker (PFX-1.11, #6924)';
COMMENT ON COLUMN pacticipant_label.tenant_id IS 'The pacticipant''s tenant, by the composite reference';
