-- Reconcile one-shot file uploads: the tenant's staleness threshold (RAR-6.2, #3539).
--
-- A catalog item imported from an uploaded file has no remote source to poll, so it can drift
-- from the file its owner keeps editing elsewhere. When an item's newest version came from an
-- upload and is at least this many days old, the catalog shows a "may be stale" hint and offers
-- a re-upload that replays the import spec the upload recorded (format_metadata.importSpec,
-- written by apiome-rest; no schema change needed for it).
--
-- Rollback:
--   ALTER TABLE apiome.tenants DROP COLUMN IF EXISTS catalog_upload_stale_after_days;
SET search_path TO apiome, public;

ALTER TABLE apiome.tenants
    ADD COLUMN IF NOT EXISTS catalog_upload_stale_after_days INTEGER NOT NULL DEFAULT 90
    CHECK (catalog_upload_stale_after_days BETWEEN 1 AND 3650);

COMMENT ON COLUMN apiome.tenants.catalog_upload_stale_after_days IS
    'Days after which an uploaded catalog item''s newest version may be stale (RAR-6.2).';
