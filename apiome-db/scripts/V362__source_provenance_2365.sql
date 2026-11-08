-- Source navigation and provenance (DCW-2.4, private-suite#2365).
--
-- The studio shows, for every path, operation and component of a revision, whether it is still as
-- imported, was edited in Apiome, or was edited through the source workspace — and the original
-- file, pointer, digest and excerpt behind it. Two facts were not recorded anywhere before this
-- migration, and both are captured here rather than inferred:
--
--   1. `apiome.version_import_snapshots` — what an OpenAPI import looked like. OpenAPI imports are
--      decomposed into classes and paths by the apiome-ui worker and keep no `sourceContent`, so
--      the original text was lost. One row per imported revision holds the source text (secret-
--      scrubbed under the tenant's intake policy, exactly as catalog intake scrubs `sourceContent`;
--      NULL when withheld), the original file name, the digest of the uploaded bytes, and the
--      canonical document generated right after the import committed. Status is derived by
--      comparing a later canonical document against that one, so "unchanged" means unchanged by
--      the same generator rather than by an import normalizer.
--   2. `apiome.version_source_edits` — which pointers a source apply changed. The DCW-2.3 audit
--      (`apiome.source_change_audit`, V185) records counts only; one row here per changed pointer,
--      written in the same transaction as the apply and its audit row, links back to that audit.
--
-- Both tables are tenant-scoped (denormalized `tenant_id`) and go with their revision
-- (ON DELETE CASCADE). Rows are append-only from the application's point of view.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.version_source_edits;
--   DROP TABLE IF EXISTS apiome.version_import_snapshots;
-- Provenance then reads every element as `local` (no snapshot), which is the pre-migration state.

SET search_path TO apiome, public;

-- ─── 1. Import snapshots ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS apiome.version_import_snapshots (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id          UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    version_id         UUID NOT NULL REFERENCES apiome.versions(id) ON DELETE CASCADE,
    -- The file the import named (upload file name, URL basename or repository path).
    source_file        TEXT,
    -- 'yaml' or 'json': how the source text parses for excerpts.
    source_format      TEXT NOT NULL
        CONSTRAINT version_import_snapshots_format_check CHECK (source_format IN ('yaml', 'json')),
    -- Algorithm-prefixed digest of the uploaded bytes (before scrubbing), e.g. 'sha256:<hex>'.
    source_digest      TEXT NOT NULL,
    -- The source as stored for excerpts: scrubbed under the tenant's policy; NULL when withheld.
    source_text        TEXT,
    -- The canonical OpenAPI document generated for the revision right after the import committed.
    canonical_document JSONB NOT NULL,
    -- The scrub report (types and line numbers, never values), as recorded at intake.
    scrub_report       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by         UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT version_import_snapshots_version_unique UNIQUE (version_id)
);

COMMENT ON TABLE apiome.version_import_snapshots IS
  'DCW-2.4 (private-suite#2365): what an OpenAPI import looked like — scrubbed source text, file, '
  'digest and the canonical document at import — so provenance can say imported / local / source-edited.';
COMMENT ON COLUMN apiome.version_import_snapshots.source_text IS
  'Source text scrubbed under the tenant intake policy (as catalog sourceContent); NULL when withheld.';

CREATE INDEX IF NOT EXISTS idx_version_import_snapshots_tenant
    ON apiome.version_import_snapshots (tenant_id, version_id);

-- ─── 2. Per-pointer source edits ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS apiome.version_source_edits (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id    UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    version_id   UUID NOT NULL REFERENCES apiome.versions(id) ON DELETE CASCADE,
    -- RFC 6901 JSON Pointer of the changed value ('' addresses the root).
    pointer      TEXT NOT NULL
        CONSTRAINT version_source_edits_pointer_shape CHECK (pointer = '' OR pointer LIKE '/%'),
    -- The DCW-2.3 change kind: addition | update | deletion | unsupported-preserved.
    change_kind  TEXT NOT NULL,
    audit_id     UUID REFERENCES apiome.source_change_audit(id) ON DELETE SET NULL,
    actor_id     UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE apiome.version_source_edits IS
  'DCW-2.4 (private-suite#2365): one row per pointer a DCW-2.3 source apply changed, written in the '
  'apply''s transaction and linked to its source_change_audit row.';

CREATE INDEX IF NOT EXISTS idx_version_source_edits_version
    ON apiome.version_source_edits (tenant_id, version_id, pointer);
