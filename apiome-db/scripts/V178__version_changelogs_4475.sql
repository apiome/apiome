-- Publish pipeline classification — CTG-3.1 (#4475).
--
-- Problem: classified changelogs must be durable at publish time for UI, webhooks,
-- and guardrails. On-demand POST /v1/diff/.../classified alone is not enough.
--
-- Solution: persist one row per published revision in apiome.version_changelogs:
--   * changelog_json  — ctg.changelog.v1 (or initial-publication marker)
--   * max_severity    — denormalized worst severity for badge queries
--   * status          — ready | initial | failed
--   * baseline_revision_id — prior published ancestor (null when initial)
--
-- Classification needs OpenAPI reconstruction (Python). This migration creates
-- the table only. After migrate, operators run:
--   PYTHONPATH=src python scripts/backfill_version_changelogs.py
-- (apiome-rest) to classify the latest published revision per project lacking a row.
--
-- Rollback:
--   DROP TABLE IF EXISTS apiome.version_changelogs CASCADE;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS version_changelogs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    published_revision_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    baseline_revision_id UUID REFERENCES versions(id) ON DELETE SET NULL,
    changelog_json JSONB,
    max_severity TEXT,
    status TEXT NOT NULL DEFAULT 'ready',
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT version_changelogs_published_revision_unique UNIQUE (published_revision_id),
    CONSTRAINT version_changelogs_status_ck
        CHECK (status IN ('ready', 'initial', 'failed')),
    CONSTRAINT version_changelogs_max_severity_ck
        CHECK (
            max_severity IS NULL
            OR max_severity IN ('breaking', 'non-breaking', 'docs-only')
        )
);

CREATE INDEX IF NOT EXISTS idx_version_changelogs_tenant_project
    ON version_changelogs (tenant_id, project_id);

CREATE INDEX IF NOT EXISTS idx_version_changelogs_project_max_severity
    ON version_changelogs (project_id, max_severity);

COMMENT ON TABLE version_changelogs IS
    'Classified publish changelogs (CTG-3.1 / #4475); one row per published_revision_id';
COMMENT ON COLUMN version_changelogs.published_revision_id IS
    'Natural key: published versions.id; upsert ON CONFLICT';
COMMENT ON COLUMN version_changelogs.baseline_revision_id IS
    'Prior published ancestor used as classifier base; NULL when initial publication';
COMMENT ON COLUMN version_changelogs.changelog_json IS
    'ctg.changelog.v1 JSON (or initialPublication marker); NULL when status=failed';
COMMENT ON COLUMN version_changelogs.max_severity IS
    'Denormalized worst severity for badge queries; NULL when initial/empty/failed';
COMMENT ON COLUMN version_changelogs.status IS
    'ready = classified; initial = first publish marker; failed = classification error (retriable)';
COMMENT ON COLUMN version_changelogs.error IS
    'Failure message when status=failed; NULL otherwise';
