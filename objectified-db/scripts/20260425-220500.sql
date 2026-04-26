-- Per-version lint findings (child rows of version_lint_results).
--
-- One row per (rule, target) match. The runner inserts these in the same
-- transaction as the parent result row, so a result is never visible without
-- its findings (and vice-versa). The UI groups findings by `rule_id` for the
-- scorecard and by `target_path` for the schema-scope drilldown.
SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS version_lint_findings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    result_id UUID NOT NULL REFERENCES version_lint_results(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    rule_id VARCHAR(96) NOT NULL,
    severity VARCHAR(16) NOT NULL CHECK (severity IN ('error', 'warning', 'info')),
    target_kind VARCHAR(32) NOT NULL CHECK (target_kind IN ('class', 'property', 'schema')),
    target_id UUID,
    target_path TEXT NOT NULL,
    message TEXT NOT NULL,
    suggestion TEXT,
    detail JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_version_lint_findings_result
    ON version_lint_findings(result_id);

CREATE INDEX IF NOT EXISTS idx_version_lint_findings_version_severity
    ON version_lint_findings(version_id, severity);

CREATE INDEX IF NOT EXISTS idx_version_lint_findings_rule
    ON version_lint_findings(rule_id);

COMMENT ON TABLE version_lint_findings IS 'One row per (rule, target) match for a lint run; cascades when the parent result is deleted';
COMMENT ON COLUMN version_lint_findings.rule_id IS 'Stable rule identifier (e.g. `missing-description`); maps to the rule registry in lint_engine.py';
COMMENT ON COLUMN version_lint_findings.target_kind IS 'class | property | schema (whole-version checks)';
COMMENT ON COLUMN version_lint_findings.target_id IS 'classes.id / class_properties.id / NULL for schema-level findings';
COMMENT ON COLUMN version_lint_findings.target_path IS 'Human-readable location (e.g. `User.email`) shown directly in the UI';
COMMENT ON COLUMN version_lint_findings.suggestion IS 'Optional fix hint surfaced in the scorecard drawer';

-- Rollback: DROP TABLE IF EXISTS odb.version_lint_findings CASCADE;
