-- Multi-axis score and coverage evaluations — CLX-1.2 (#4849).
--
-- Problem: a single A–F quality grade hides whether a defect is definition quality, protocol
-- conformance, security, supply chain, supportability, or compatibility — and conflates
-- "not assessed" with a clean (zero-finding) score.
--
-- This migration:
--   1. Creates apiome.lint_axis_evaluations — append-only, write-once evaluations linked to
--      exactly ONE subject (catalog revision XOR MCP endpoint version), versioned by
--      algorithm_id (clx-axis-v1). Re-scores INSERT a new row; rows are never updated
--      (immutability trigger reuses the V128 write-once guard).
--   2. Backfills one clx-axis-v1 evaluation per existing native report:
--        * versions.quality_*  -> subject catalog_revision
--        * mcp_version_scores  -> subject mcp_endpoint_version
--      Quality axis maps the legacy score/grade; protocol / security / supply_chain /
--      supportability / compatibility are explicit not_assessed (full mapping of security
--      and compatibility findings is applied by apiome-rest's app.axis_score on re-score).
--      Composite = quality alone when quality is assessed (required coverage = quality only).
--
-- Existing versions.quality_* / mcp_version_scores remain the legacy sort/filter keys.
-- Never-scored subjects get NO evaluation row.
--
-- Idempotent: CREATE ... IF NOT EXISTS; backfills skip subjects that already have an
-- evaluation for the same algorithm_id + source_report_fingerprint.
--
-- Rollback notes:
--   DROP TRIGGER IF EXISTS trigger_lint_axis_evaluations_immutable ON apiome.lint_axis_evaluations;
--   DROP TABLE IF EXISTS apiome.lint_axis_evaluations;
-- (The V128 guard function apiome.mcp_forbid_row_mutation() is shared — do not drop it here.)

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- lint_axis_evaluations — one immutable multi-axis evaluation per subject + algorithm + report.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lint_axis_evaluations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Which kind of subject this evaluation covers. Exactly one of the two FK columns below is set.
    subject_type VARCHAR(32) NOT NULL,

    -- Subject: a catalog/schema revision. Evaluation is reaped with the revision.
    version_record_id UUID REFERENCES versions(id) ON DELETE CASCADE,

    -- Subject: an MCP discovery snapshot. Evaluation is reaped with the snapshot/endpoint.
    mcp_version_id UUID REFERENCES mcp_endpoint_versions(id) ON DELETE CASCADE,

    -- Stable id of the scoring algorithm (e.g. 'clx-axis-v1'). Stored with every evaluation
    -- so historical rows remain interpretable after algorithm changes.
    algorithm_id TEXT NOT NULL,

    -- Semver / integer revision of the algorithm implementation (distinct from algorithm_id).
    algorithm_version TEXT NOT NULL DEFAULT '1',

    -- Ordered array of axis objects: key, label, weight, assessed, score, grade,
    -- severity_counts, coverage, not_assessed_reason.
    axes JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Optional composite over assessed axes when required coverage is present; NULL otherwise.
    composite_score INTEGER,
    composite_grade TEXT,

    -- True when required axes (v1: quality) are assessed so a composite may be published.
    required_coverage_met BOOLEAN NOT NULL DEFAULT FALSE,

    -- Fingerprint of the source report the evaluation was derived from (dedupe key with subject
    -- + algorithm_id). For backfilled rows this preserves the existing report fingerprint.
    source_report_fingerprint TEXT,

    evaluated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT lint_axis_evaluations_subject_type_check
        CHECK (subject_type IN ('catalog_revision', 'mcp_endpoint_version')),

    CONSTRAINT lint_axis_evaluations_single_subject_check
        CHECK (
            (subject_type = 'catalog_revision'
                AND version_record_id IS NOT NULL AND mcp_version_id IS NULL)
            OR
            (subject_type = 'mcp_endpoint_version'
                AND mcp_version_id IS NOT NULL AND version_record_id IS NULL)
        ),

    CONSTRAINT lint_axis_evaluations_axes_array_check
        CHECK (jsonb_typeof(axes) = 'array'),

    CONSTRAINT lint_axis_evaluations_composite_score_check
        CHECK (composite_score IS NULL OR (composite_score >= 0 AND composite_score <= 100)),

    CONSTRAINT lint_axis_evaluations_composite_grade_check
        CHECK (composite_grade IS NULL OR composite_grade IN ('A', 'B', 'C', 'D', 'F'))
);

COMMENT ON TABLE lint_axis_evaluations IS
    'Immutable, append-only multi-axis score/coverage evaluation for one catalog revision or MCP endpoint version (CLX-1.2, #4849)';
COMMENT ON COLUMN lint_axis_evaluations.id IS 'Unique identifier for the evaluation row';
COMMENT ON COLUMN lint_axis_evaluations.subject_type IS 'Subject kind: catalog_revision or mcp_endpoint_version; agrees with whichever FK is set';
COMMENT ON COLUMN lint_axis_evaluations.version_record_id IS 'Catalog revision (versions.id) when subject_type=catalog_revision';
COMMENT ON COLUMN lint_axis_evaluations.mcp_version_id IS 'MCP snapshot (mcp_endpoint_versions.id) when subject_type=mcp_endpoint_version';
COMMENT ON COLUMN lint_axis_evaluations.algorithm_id IS 'Stable scoring algorithm id (clx-axis-v1); versioned with every evaluation';
COMMENT ON COLUMN lint_axis_evaluations.algorithm_version IS 'Implementation revision of the algorithm (starts at 1)';
COMMENT ON COLUMN lint_axis_evaluations.axes IS 'Ordered axis payloads: score/grade, severity counts, coverage, weight, not-assessed reason';
COMMENT ON COLUMN lint_axis_evaluations.composite_score IS 'Weighted composite 0-100 when required coverage is met; NULL otherwise';
COMMENT ON COLUMN lint_axis_evaluations.composite_grade IS 'A-F letter grade of the composite; NULL when composite_score is NULL';
COMMENT ON COLUMN lint_axis_evaluations.required_coverage_met IS 'True when required axes (v1: quality) are assessed';
COMMENT ON COLUMN lint_axis_evaluations.source_report_fingerprint IS 'Fingerprint of the source lint report this evaluation was derived from';
COMMENT ON COLUMN lint_axis_evaluations.evaluated_at IS 'When the evaluation was computed';
COMMENT ON COLUMN lint_axis_evaluations.created_at IS 'When the row was recorded (insert-only; rows are write-once)';

CREATE INDEX IF NOT EXISTS idx_lint_axis_evaluations_version
    ON lint_axis_evaluations (version_record_id, evaluated_at DESC)
    WHERE version_record_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lint_axis_evaluations_mcp_version
    ON lint_axis_evaluations (mcp_version_id, evaluated_at DESC)
    WHERE mcp_version_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lint_axis_evaluations_algorithm
    ON lint_axis_evaluations (algorithm_id);
CREATE INDEX IF NOT EXISTS idx_lint_axis_evaluations_source_fingerprint
    ON lint_axis_evaluations (source_report_fingerprint)
    WHERE source_report_fingerprint IS NOT NULL;

DROP TRIGGER IF EXISTS trigger_lint_axis_evaluations_immutable ON lint_axis_evaluations;
CREATE TRIGGER trigger_lint_axis_evaluations_immutable
    BEFORE UPDATE ON lint_axis_evaluations
    FOR EACH ROW
    EXECUTE FUNCTION mcp_forbid_row_mutation();

-- ---------------------------------------------------------------------------------------------------
-- Shared helpers for backfill axis JSON (quality assessed; peers explicitly not_assessed).
-- ---------------------------------------------------------------------------------------------------
-- Grade bands match schema_lint / mcp_score (A≥90 … F<60).
CREATE OR REPLACE FUNCTION lint_axis_grade_for_score(score INTEGER)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE
        WHEN score IS NULL THEN NULL
        WHEN score >= 90 THEN 'A'
        WHEN score >= 80 THEN 'B'
        WHEN score >= 70 THEN 'C'
        WHEN score >= 60 THEN 'D'
        ELSE 'F'
    END;
$$;

CREATE OR REPLACE FUNCTION lint_axis_not_assessed(
    axis_key TEXT,
    axis_label TEXT,
    reason TEXT
)
RETURNS JSONB
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT jsonb_build_object(
        'key', axis_key,
        'label', axis_label,
        'weight', 1.0,
        'assessed', false,
        'score', NULL,
        'grade', NULL,
        'severity_counts', jsonb_build_object('error', 0, 'warning', 0, 'info', 0),
        'coverage', jsonb_build_object('state', 'none'),
        'not_assessed_reason', reason
    );
$$;

CREATE OR REPLACE FUNCTION lint_axis_quality_assessed(
    score INTEGER,
    grade TEXT,
    severity_counts JSONB
)
RETURNS JSONB
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT jsonb_build_object(
        'key', 'quality',
        'label', 'Quality',
        'weight', 1.0,
        'assessed', true,
        'score', score,
        'grade', COALESCE(grade, lint_axis_grade_for_score(score)),
        'severity_counts', COALESCE(
            severity_counts,
            jsonb_build_object('error', 0, 'warning', 0, 'info', 0)
        ),
        'coverage', jsonb_build_object('state', 'full'),
        'not_assessed_reason', NULL
    );
$$;

CREATE OR REPLACE FUNCTION lint_axis_clx_v1_axes(
    quality_score INTEGER,
    quality_grade TEXT,
    severity_counts JSONB,
    subject_kind TEXT
)
RETURNS JSONB
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT jsonb_build_array(
        lint_axis_quality_assessed(quality_score, quality_grade, severity_counts),
        lint_axis_not_assessed(
            'protocol', 'Protocol',
            'No protocol-conformance scanner evidence yet'
        ),
        lint_axis_not_assessed(
            'security', 'Security',
            CASE
                WHEN subject_kind = 'mcp_endpoint_version'
                    THEN 'No security findings mapped yet; re-score to populate from native MCP security rules'
                ELSE 'No security scanner evidence for catalog revisions yet'
            END
        ),
        lint_axis_not_assessed(
            'supply_chain', 'Supply chain',
            'No supply-chain scanner evidence yet'
        ),
        lint_axis_not_assessed(
            'supportability', 'Supportability',
            'No supportability scanner evidence yet'
        ),
        lint_axis_not_assessed(
            'compatibility', 'Compatibility',
            CASE
                WHEN subject_kind = 'catalog_revision'
                    THEN 'No base-revision compatibility evidence'
                ELSE 'Compatibility axis applies to catalog revisions'
            END
        )
    );
$$;

-- ---------------------------------------------------------------------------------------------------
-- Backfill 1/2: catalog revisions with a persisted quality report/score.
-- ---------------------------------------------------------------------------------------------------
INSERT INTO lint_axis_evaluations (
    subject_type, version_record_id, algorithm_id, algorithm_version, axes,
    composite_score, composite_grade, required_coverage_met, source_report_fingerprint,
    evaluated_at
)
SELECT
    'catalog_revision',
    v.id,
    'clx-axis-v1',
    '1',
    lint_axis_clx_v1_axes(
        v.quality_score,
        v.quality_grade,
        COALESCE(v.quality_report -> 'severity_counts', NULL),
        'catalog_revision'
    ),
    v.quality_score,
    COALESCE(v.quality_grade, lint_axis_grade_for_score(v.quality_score)),
    (v.quality_score IS NOT NULL),
    COALESCE(v.quality_report ->> 'report_fingerprint', v.quality_report_fingerprint),
    COALESCE(v.updated_at, CURRENT_TIMESTAMP)
FROM versions v
WHERE v.deleted_at IS NULL
  AND v.quality_score IS NOT NULL
  AND (
        (v.quality_report IS NOT NULL AND v.quality_report <> '{}'::jsonb)
        OR v.quality_report_fingerprint IS NOT NULL
        OR v.quality_score IS NOT NULL
      )
  AND NOT EXISTS (
        SELECT 1 FROM lint_axis_evaluations e
        WHERE e.version_record_id = v.id
          AND e.algorithm_id = 'clx-axis-v1'
          AND e.source_report_fingerprint IS NOT DISTINCT FROM
              COALESCE(v.quality_report ->> 'report_fingerprint', v.quality_report_fingerprint)
      );

-- ---------------------------------------------------------------------------------------------------
-- Backfill 2/2: MCP snapshots with a stored score row.
-- ---------------------------------------------------------------------------------------------------
INSERT INTO lint_axis_evaluations (
    subject_type, mcp_version_id, algorithm_id, algorithm_version, axes,
    composite_score, composite_grade, required_coverage_met, source_report_fingerprint,
    evaluated_at
)
SELECT
    'mcp_endpoint_version',
    s.version_id,
    'clx-axis-v1',
    '1',
    lint_axis_clx_v1_axes(
        s.score,
        s.grade,
        COALESCE(s.report -> 'severity_counts', NULL),
        'mcp_endpoint_version'
    ),
    s.score,
    COALESCE(s.grade, lint_axis_grade_for_score(s.score)),
    (s.score IS NOT NULL),
    COALESCE(s.report ->> 'report_fingerprint', s.report_fingerprint),
    COALESCE(s.scored_at, CURRENT_TIMESTAMP)
FROM mcp_version_scores s
WHERE s.score IS NOT NULL
  AND (
        (s.report IS NOT NULL AND s.report <> '{}'::jsonb)
        OR s.report_fingerprint IS NOT NULL
        OR s.score IS NOT NULL
      )
  AND NOT EXISTS (
        SELECT 1 FROM lint_axis_evaluations e
        WHERE e.mcp_version_id = s.version_id
          AND e.algorithm_id = 'clx-axis-v1'
          AND e.source_report_fingerprint IS NOT DISTINCT FROM
              COALESCE(s.report ->> 'report_fingerprint', s.report_fingerprint)
      );
