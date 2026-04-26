-- Per-version schema quality snapshots.
--
-- One row per "Compute quality" run; the UI surfaces the latest row plus the
-- recent history (trajectory chart on the project Versions tab and the
-- scorecard on the version detail page). Snapshots are append-only — re-running
-- never mutates a prior row.
SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS version_quality_scores (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    overall SMALLINT NOT NULL CHECK (overall BETWEEN 0 AND 100),
    completeness SMALLINT NOT NULL CHECK (completeness BETWEEN 0 AND 100),
    consistency SMALLINT NOT NULL CHECK (consistency BETWEEN 0 AND 100),
    descriptions SMALLINT NOT NULL CHECK (descriptions BETWEEN 0 AND 100),
    examples SMALLINT NOT NULL CHECK (examples BETWEEN 0 AND 100),
    class_count INTEGER NOT NULL DEFAULT 0,
    property_count INTEGER NOT NULL DEFAULT 0,
    computed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    computed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    detail JSONB
);

CREATE INDEX IF NOT EXISTS idx_version_quality_scores_version
    ON version_quality_scores(version_id, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_version_quality_scores_project
    ON version_quality_scores(project_id, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_version_quality_scores_tenant
    ON version_quality_scores(tenant_id);

COMMENT ON TABLE version_quality_scores IS 'Per-version schema quality snapshots; append-only, written by POST /v1/version-quality/{tenant}/{project}/{versionId}/run';
COMMENT ON COLUMN version_quality_scores.overall IS 'Overall 0-100 score; weighted mean of the four sub-scores';
COMMENT ON COLUMN version_quality_scores.completeness IS 'Share of classes/properties with required fields populated';
COMMENT ON COLUMN version_quality_scores.consistency IS 'Naming consistency and structural homogeneity across the schema';
COMMENT ON COLUMN version_quality_scores.descriptions IS 'Share of classes/properties carrying a non-empty description';
COMMENT ON COLUMN version_quality_scores.examples IS 'Share of properties carrying example values';
COMMENT ON COLUMN version_quality_scores.detail IS 'Optional scorer breakdown (per-class scores, missing-description counts, etc.) for UI drilldown';

-- Rollback: DROP TABLE IF EXISTS odb.version_quality_scores CASCADE;
