-- Stored overlays as the curation form — GVM-4.3 (#5878).
--
-- (The roadmap reserved V277 for this table; V277 shipped as artifact_tags, so it lands as V385.)
--
-- Curation edits that must not touch the source — AGX-1.3's accepted description overrides, Export
-- Studio tweaks, lint fixes a team keeps out of the repository — live here as one ordered chain of
-- Overlay 1.x documents per revision. The chain is applied at **export and publish render only**:
-- the stored canonical model, the Studio editing surface, lint, diff and SDK paths are untouched.
--
--   version_overlays         — the chain: one write-once row per overlay, ordered by `position`.
--   version_overlay_renders  — what the publish render produced: the source and resolved document
--                              fingerprints side by side, the overlay fingerprints and any findings.
--
-- Rules the schema enforces:
--
--   1. **Rows are write-once.** `version_overlays_write_once` refuses every UPDATE. Replacing an
--      overlay is DELETE + INSERT in one transaction under one audit event (the application writes
--      `version.overlay_replaced` to `apiome.workflow_audit`), so a stored overlay's
--      `content_fingerprint` always describes the bytes the row holds.
--   2. **One overlay per position** — `UNIQUE (version_record_id, position)`, DEFERRABLE so the
--      application can compact positions after a delete inside one transaction.
--   3. **Known sources only** — `manual | lint-fix | export-studio | enrichment-export`.
--   4. **Published revisions are read-only.** The application refuses writes on a published revision
--      (`409 overlay-version-published`); the schema does not, so a version delete still cascades.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.version_overlay_renders;
--   DROP TABLE IF EXISTS apiome.version_overlays;
--   DROP FUNCTION IF EXISTS apiome.version_overlays_refuse_update();

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- version_overlays — the ordered chain.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS version_overlays (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    version_record_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    name VARCHAR(200) NOT NULL CHECK (char_length(btrim(name)) BETWEEN 1 AND 200),
    source VARCHAR(32) NOT NULL
        CHECK (source IN ('manual', 'lint-fix', 'export-studio', 'enrichment-export')),
    document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    content_fingerprint VARCHAR(71) NOT NULL CHECK (content_fingerprint LIKE 'sha256:%'),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT version_overlays_position_uq UNIQUE (version_record_id, position)
        DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX IF NOT EXISTS idx_version_overlays_tenant_version
    ON version_overlays (tenant_id, version_record_id, position);

COMMENT ON TABLE version_overlays IS
    'GVM-4.3 (#5878): ordered, write-once Overlay 1.x chain per revision, applied at export and '
    'publish render only. Replacement is delete + insert under one audit event.';
COMMENT ON COLUMN version_overlays.position IS
    'Order the chain applies in (0 first). Unique per revision.';
COMMENT ON COLUMN version_overlays.content_fingerprint IS
    'sha256: of the canonical JSON of document (sorted keys, compact separators).';

-- Rule 1: write-once.
CREATE OR REPLACE FUNCTION version_overlays_refuse_update() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'version_overlays rows are write-once; replace with DELETE + INSERT'
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS version_overlays_write_once ON version_overlays;
CREATE TRIGGER version_overlays_write_once
    BEFORE UPDATE ON version_overlays
    FOR EACH ROW EXECUTE FUNCTION version_overlays_refuse_update();

-- ---------------------------------------------------------------------------------------------------
-- version_overlay_renders — the publish render record.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS version_overlay_renders (
    version_record_id UUID PRIMARY KEY REFERENCES versions(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_fingerprint VARCHAR(71) NOT NULL,
    resolved_fingerprint VARCHAR(71) NOT NULL,
    overlay_fingerprints JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(overlay_fingerprints) = 'array'),
    findings JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(findings) = 'array'),
    changes INTEGER NOT NULL DEFAULT 0 CHECK (changes >= 0),
    rendered_by UUID REFERENCES users(id) ON DELETE SET NULL,
    rendered_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE version_overlay_renders IS
    'GVM-4.3 (#5878): the publish render of a revision''s overlay chain — the source document '
    'fingerprint beside the resolved (post-overlay) fingerprint, with the overlay.* findings.';

DO $$
BEGIN
    RAISE NOTICE 'apiome.version_overlays and apiome.version_overlay_renders created (GVM-4.3, #5878).';
END $$;
