-- Document object lifecycle: reference counts, integrity flags and audit rows (COA-5.10, #7086).
--
-- Stored objects are content-addressed, so revisions share them: deleting a revision cannot simply
-- delete its objects. This migration keeps apiome.document_objects.ref_count (added empty by V403)
-- equal to the number of LIVE references, so apiome-rest's lifecycle job (app.document_lifecycle)
-- can delete an object from the store once nothing uses it:
--
--   * A reference is a version_documents row whose revision is not deleted (versions.deleted_at,
--     which version delete and retention pruning set) and whose tenant is not deleted
--     (tenants.deleted_at). A soft-deleted project keeps its references: it can be restored.
--   * apiome.recount_document_objects(ids) recomputes ref_count for the given objects and stamps
--     unreferenced_at when it reaches zero (cleared again when a reference comes back). Triggers
--     call it when version_documents rows are inserted, re-pointed or deleted, when a revision is deleted or
--     restored, and when a tenant is deleted or restored, so the count is right whichever code
--     path (REST or the UI's direct SQL) made the change.
--   * document_objects.integrity_failed_at flags an original or frozen schema whose stored bytes
--     no longer hash to its SHA-256 (or are missing). verified_at is the last successful check.
--   * apiome.document_lifecycle_events is the audit trail: objects purged, tenant prefixes purged,
--     integrity failures and rendered documents dropped for re-render.
--   * apiome.document_tenant_purges records each deleted tenant whose store prefix was emptied, so
--     the job purges a tenant once.
--
-- Online: the two ADD COLUMNs are nullable with no default (catalog-only). The backfill updates
-- every document_objects row once; the table holds index rows only, never bytes.
--
-- Rollback notes (reverse carefully in shared environments — this drops the lifecycle audit):
--   DROP TRIGGER IF EXISTS trg_document_refs_insert ON apiome.version_documents;
--   DROP TRIGGER IF EXISTS trg_document_refs_delete ON apiome.version_documents;
--   DROP TRIGGER IF EXISTS trg_document_refs_update ON apiome.version_documents;
--   DROP TRIGGER IF EXISTS trg_document_refs_version ON apiome.versions;
--   DROP TRIGGER IF EXISTS trg_document_refs_tenant ON apiome.tenants;
--   DROP FUNCTION IF EXISTS apiome.document_refs_from_new_rows();
--   DROP FUNCTION IF EXISTS apiome.document_refs_from_old_rows();
--   DROP FUNCTION IF EXISTS apiome.document_refs_from_changed_rows();
--   DROP FUNCTION IF EXISTS apiome.document_refs_from_version();
--   DROP FUNCTION IF EXISTS apiome.document_refs_from_tenant();
--   DROP FUNCTION IF EXISTS apiome.recount_document_objects(uuid[]);
--   DROP TABLE IF EXISTS apiome.document_tenant_purges;
--   DROP TABLE IF EXISTS apiome.document_lifecycle_events;
--   ALTER TABLE apiome.document_objects DROP COLUMN IF EXISTS unreferenced_at,
--                                       DROP COLUMN IF EXISTS integrity_failed_at;
SET search_path TO apiome, public;

-- ───────────────────────────── columns ─────────────────────────────

ALTER TABLE apiome.document_objects
    ADD COLUMN IF NOT EXISTS unreferenced_at timestamptz,
    ADD COLUMN IF NOT EXISTS integrity_failed_at timestamptz;

COMMENT ON COLUMN apiome.document_objects.ref_count IS
    'Live references: version_documents rows whose revision and tenant are not deleted (COA-5.10). Maintained by apiome.recount_document_objects.';
COMMENT ON COLUMN apiome.document_objects.unreferenced_at IS
    'When ref_count last reached zero; null while referenced. The lifecycle job deletes the object after a grace period.';
COMMENT ON COLUMN apiome.document_objects.integrity_failed_at IS
    'When an integrity run found the stored bytes changed or missing (originals and frozen schemas); null once they verify again.';

CREATE INDEX IF NOT EXISTS idx_document_objects_unreferenced
    ON apiome.document_objects (unreferenced_at)
    WHERE ref_count = 0;

CREATE INDEX IF NOT EXISTS idx_document_objects_tenant
    ON apiome.document_objects (tenant_id);

-- ───────────────────────────── recount ─────────────────────────────

CREATE OR REPLACE FUNCTION apiome.recount_document_objects(object_ids uuid[])
RETURNS void
LANGUAGE sql
AS $$
    UPDATE apiome.document_objects o
    SET ref_count = live.n,
        unreferenced_at = CASE
            WHEN live.n = 0 THEN COALESCE(o.unreferenced_at, now())
            ELSE NULL
        END
    FROM (
        SELECT ids.id,
               (SELECT count(*)
                FROM apiome.version_documents d
                JOIN apiome.versions v ON v.id = d.version_id
                JOIN apiome.projects p ON p.id = v.project_id
                JOIN apiome.tenants t ON t.id = p.tenant_id
                WHERE d.object_id = ids.id
                  AND v.deleted_at IS NULL
                  AND t.deleted_at IS NULL)::integer AS n
        FROM unnest(object_ids) AS ids(id)
    ) AS live
    WHERE o.id = live.id
      AND (o.ref_count IS DISTINCT FROM live.n
           OR (live.n = 0 AND o.unreferenced_at IS NULL)
           OR (live.n > 0 AND o.unreferenced_at IS NOT NULL));
$$;

COMMENT ON FUNCTION apiome.recount_document_objects(uuid[]) IS
    'Recompute document_objects.ref_count (live references) for the given objects and stamp or clear unreferenced_at (COA-5.10).';

-- ───────────────────────────── triggers ─────────────────────────────

CREATE OR REPLACE FUNCTION apiome.document_refs_from_new_rows()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM apiome.recount_document_objects(ARRAY(SELECT DISTINCT object_id FROM new_rows));
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION apiome.document_refs_from_old_rows()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM apiome.recount_document_objects(ARRAY(SELECT DISTINCT object_id FROM old_rows));
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION apiome.document_refs_from_changed_rows()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    -- A link pointed at another object (set_version_document's ON CONFLICT … DO UPDATE): both
    -- the object it left and the one it now uses change count.
    PERFORM apiome.recount_document_objects(ARRAY(
        SELECT object_id FROM old_rows UNION SELECT object_id FROM new_rows
    ));
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION apiome.document_refs_from_version()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.deleted_at IS DISTINCT FROM OLD.deleted_at THEN
        PERFORM apiome.recount_document_objects(ARRAY(
            SELECT DISTINCT d.object_id FROM apiome.version_documents d WHERE d.version_id = NEW.id
        ));
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION apiome.document_refs_from_tenant()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.deleted_at IS DISTINCT FROM OLD.deleted_at THEN
        PERFORM apiome.recount_document_objects(ARRAY(
            SELECT o.id FROM apiome.document_objects o WHERE o.tenant_id = NEW.id::text
        ));
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_document_refs_insert ON apiome.version_documents;
CREATE TRIGGER trg_document_refs_insert
    AFTER INSERT ON apiome.version_documents
    REFERENCING NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION apiome.document_refs_from_new_rows();

DROP TRIGGER IF EXISTS trg_document_refs_delete ON apiome.version_documents;
CREATE TRIGGER trg_document_refs_delete
    AFTER DELETE ON apiome.version_documents
    REFERENCING OLD TABLE AS old_rows
    FOR EACH STATEMENT EXECUTE FUNCTION apiome.document_refs_from_old_rows();

DROP TRIGGER IF EXISTS trg_document_refs_update ON apiome.version_documents;
CREATE TRIGGER trg_document_refs_update
    AFTER UPDATE ON apiome.version_documents
    REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION apiome.document_refs_from_changed_rows();

DROP TRIGGER IF EXISTS trg_document_refs_version ON apiome.versions;
CREATE TRIGGER trg_document_refs_version
    AFTER UPDATE OF deleted_at ON apiome.versions
    FOR EACH ROW EXECUTE FUNCTION apiome.document_refs_from_version();

DROP TRIGGER IF EXISTS trg_document_refs_tenant ON apiome.tenants;
CREATE TRIGGER trg_document_refs_tenant
    AFTER UPDATE OF deleted_at ON apiome.tenants
    FOR EACH ROW EXECUTE FUNCTION apiome.document_refs_from_tenant();

-- ───────────────────────────── audit ─────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.document_lifecycle_events (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at  timestamptz NOT NULL DEFAULT now(),
    event        text NOT NULL
                     CHECK (event IN ('object_purged', 'object_purge_failed', 'tenant_purged',
                                      'integrity_failed', 'rendered_dropped')),
    tenant_id    text,
    object_id    uuid,
    sha256       text CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'),
    backend      text,
    storage_key  text,
    reason       text,
    detail       jsonb NOT NULL DEFAULT '{}'::jsonb
);

COMMENT ON TABLE apiome.document_lifecycle_events IS
    'Audit rows of the document lifecycle job (COA-5.10, #7086): purges, tenant purges, integrity failures, rendered documents dropped for re-render.';
COMMENT ON COLUMN apiome.document_lifecycle_events.object_id IS
    'The document_objects.id the event was about; the row itself may be gone (no foreign key).';
COMMENT ON COLUMN apiome.document_lifecycle_events.reason IS
    'Why: version-deleted, unreferenced, stale-render, tenant-deleted (purges); mismatch or missing (integrity).';

CREATE INDEX IF NOT EXISTS idx_document_lifecycle_events_occurred
    ON apiome.document_lifecycle_events (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_document_lifecycle_events_tenant
    ON apiome.document_lifecycle_events (tenant_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS apiome.document_tenant_purges (
    tenant_id        uuid PRIMARY KEY,
    purged_at        timestamptz NOT NULL DEFAULT now(),
    objects_deleted  integer NOT NULL DEFAULT 0 CHECK (objects_deleted >= 0)
);

COMMENT ON TABLE apiome.document_tenant_purges IS
    'Deleted tenants whose document store prefix the lifecycle job emptied (COA-5.10); a tenant is purged once.';

-- ───────────────────────────── backfill ─────────────────────────────

SELECT apiome.recount_document_objects(ARRAY(SELECT id FROM apiome.document_objects));
