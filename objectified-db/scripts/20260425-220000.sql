-- Per-version lint results (run header).
--
-- One row per "Run lint" invocation. The row is the durable summary the UI
-- reads to render the version detail's lint scorecard and the per-version
-- lint badge in the Versions tab. Findings live in the child table
-- `version_lint_findings`; deleting the parent cascades.
SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS version_lint_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    grade CHAR(1) NOT NULL CHECK (grade IN ('A', 'B', 'C', 'D', 'F')),
    error_count INTEGER NOT NULL DEFAULT 0 CHECK (error_count >= 0),
    warning_count INTEGER NOT NULL DEFAULT 0 CHECK (warning_count >= 0),
    info_count INTEGER NOT NULL DEFAULT 0 CHECK (info_count >= 0),
    rules_applied INTEGER NOT NULL DEFAULT 0 CHECK (rules_applied >= 0),
    duration_ms INTEGER,
    computed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    computed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    detail JSONB
);

CREATE INDEX IF NOT EXISTS idx_version_lint_results_version
    ON version_lint_results(version_id, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_version_lint_results_project
    ON version_lint_results(project_id, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_version_lint_results_tenant
    ON version_lint_results(tenant_id);

COMMENT ON TABLE version_lint_results IS 'One row per `Run lint` invocation; surfaces the scorecard on the version detail page';
COMMENT ON COLUMN version_lint_results.grade IS 'Letter grade derived from error/warning counts; A=clean, F=many errors';
COMMENT ON COLUMN version_lint_results.rules_applied IS 'How many rules ran in this invocation (rules can be added without invalidating prior results)';
COMMENT ON COLUMN version_lint_results.duration_ms IS 'Wall time of the run; useful for spotting perf regressions as the rule set grows';
COMMENT ON COLUMN version_lint_results.detail IS 'Optional metadata (rule version set, runner version, env) for forensic comparisons';

-- Rollback: DROP TABLE IF EXISTS odb.version_lint_results CASCADE;
