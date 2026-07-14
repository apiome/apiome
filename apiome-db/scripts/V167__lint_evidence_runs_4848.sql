-- Revision-scoped lint evidence runs — CLX-1.1 (#4848).
--
-- Problem: native lint reports are persisted (versions.quality_report / mcp_version_scores),
-- but external and future scanners have no uniform, immutable record of tool input identity,
-- execution constraints, raw output, parser version, normalized findings, or coverage. CLX
-- (ROADMAP_CATALOG_AND_MCP_LINTING_EXCELLENCE) needs one evidence substrate shared by catalog
-- revisions and MCP endpoint versions so an unavailable or not-run scanner is a visible
-- coverage state, never silently a clean result.
--
-- This migration:
--   1. Creates apiome.lint_evidence_runs — append-only, write-once evidence rows linked to
--      exactly ONE subject: a catalog revision (versions.id) or an MCP discovery snapshot
--      (mcp_endpoint_versions.id). Re-scores INSERT a new run; rows are never updated
--      (immutability trigger reuses the V128 write-once guard).
--   2. Backfills evidence rows from the two existing native report stores, PRESERVING the
--      already-captured report fingerprints byte-for-byte:
--        * versions.quality_report / quality_report_fingerprint  -> scanner 'apiome.native-lint'
--        * mcp_version_scores.report / report_fingerprint        -> scanner 'apiome.mcp-lint'
--      Legacy finding dicts ({id, path, category, rule, severity, message}) are projected into
--      the source-neutral finding envelope (rule_id, location, severity, confidence,
--      remediation, source_fingerprint) exactly as app.lint_evidence.normalize_native_finding
--      does in apiome-rest — the two mappings must stay in lock-step.
--
-- Existing tables and API responses are untouched: versions.quality_* and mcp_version_scores
-- remain the fast-path read models; evidence rows are the provenance/audit substrate under
-- them. Never-scored subjects get NO evidence row, so coverage reads as not_run (not clean).
--
-- Coordinates with #1746/#3609 (schema_lint), #3719 (rule-pack SPI), #4423 (style guides) and
-- the closed MCP lint work (#3655/#3686) without duplicating them: those own computation and
-- policy; this table owns the immutable record of each run.
--
-- Idempotent: CREATE ... IF NOT EXISTS everywhere; both backfills skip subjects that already
-- have a run from the same scanner.
--
-- Rollback notes:
--   DROP TRIGGER IF EXISTS trigger_lint_evidence_runs_immutable ON apiome.lint_evidence_runs;
--   DROP TABLE IF EXISTS apiome.lint_evidence_runs;
-- (The V128 guard function apiome.mcp_forbid_row_mutation() is shared — do not drop it here.)

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- lint_evidence_runs — one immutable record per lint/scan execution against one revision/snapshot.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lint_evidence_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Which kind of subject this run scanned. Exactly one of the two FK columns below is set,
    -- and it must agree with this discriminator (see subject checks).
    subject_type VARCHAR(32) NOT NULL,

    -- Subject: a catalog/schema revision. Evidence is reaped with the revision.
    version_record_id UUID REFERENCES versions(id) ON DELETE CASCADE,

    -- Subject: an MCP discovery snapshot. Evidence is reaped with the snapshot/endpoint.
    mcp_version_id UUID REFERENCES mcp_endpoint_versions(id) ON DELETE CASCADE,

    -- Stable identifier of the evidence source (e.g. 'apiome.native-lint', 'apiome.mcp-lint',
    -- later external scanners like 'buf.lint'). Not free-form per run: adapters own their id.
    scanner_id TEXT NOT NULL,

    -- Version of the scanner/tool binary or engine contract that produced the raw output.
    scanner_version TEXT,

    -- Version of the adapter that normalized raw output into the finding envelope
    -- (the issue's "parser version"). Distinct from scanner_version: a re-parse of the same
    -- raw artifact bumps only this.
    adapter_version TEXT,

    -- Named execution profile / configuration preset the run used (e.g. 'import-capture',
    -- 'discovery-capture', 'recompute').
    profile TEXT,

    -- Execution window. Nullable: backfilled/legacy runs may not know their start time.
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE,

    -- What the run concluded. 'not_run' and 'unavailable' are first-class outcomes so absent
    -- scans are recordable and never render as clean.
    outcome TEXT NOT NULL,

    -- Fingerprint of the exact input document/surface the scanner consumed (input identity).
    input_fingerprint TEXT,

    -- Fingerprint of the upstream source the input was derived from (e.g. original upload,
    -- discovery surface), when distinct from input_fingerprint.
    source_fingerprint TEXT,

    -- Fingerprint of the scanner configuration AFTER secret redaction. Raw configuration is
    -- never stored here — only a stable hash of its non-secret projection.
    config_fingerprint TEXT,

    -- Opaque reference to the raw output artifact (object storage key / URI). Access-controlled:
    -- API responses expose availability, not the reference itself.
    raw_artifact_ref TEXT,

    -- Fingerprint of the normalized report. For backfilled native runs this is the pre-existing
    -- versions.quality_report_fingerprint / mcp_version_scores.report_fingerprint, preserved.
    report_fingerprint TEXT,

    -- Normalized findings in the source-neutral envelope (array of objects with rule_id,
    -- message, severity, confidence, category, location, remediation, source_fingerprint).
    findings JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Coverage state of the run over its subject: {"state": "full"|"partial"|"none"|"unknown",
    -- ...} plus optional detail (e.g. which document sections were scanned).
    coverage JSONB NOT NULL DEFAULT '{"state": "unknown"}'::jsonb,

    -- Version of the finding-envelope contract the findings array conforms to.
    envelope_version SMALLINT NOT NULL DEFAULT 1,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- The discriminator names a known subject kind.
    CONSTRAINT lint_evidence_runs_subject_type_check
        CHECK (subject_type IN ('catalog_revision', 'mcp_endpoint_version')),

    -- Exactly one subject FK is set, and it matches the discriminator.
    CONSTRAINT lint_evidence_runs_single_subject_check
        CHECK (
            (subject_type = 'catalog_revision'
                AND version_record_id IS NOT NULL AND mcp_version_id IS NULL)
            OR
            (subject_type = 'mcp_endpoint_version'
                AND mcp_version_id IS NOT NULL AND version_record_id IS NULL)
        ),

    -- Closed outcome vocabulary (CLX-1.1).
    CONSTRAINT lint_evidence_runs_outcome_check
        CHECK (outcome IN ('passed', 'findings', 'not_run', 'unavailable', 'failed',
                           'blocked_by_policy')),

    -- Findings are always a JSON array, coverage always a JSON object.
    CONSTRAINT lint_evidence_runs_findings_array_check
        CHECK (jsonb_typeof(findings) = 'array'),
    CONSTRAINT lint_evidence_runs_coverage_object_check
        CHECK (jsonb_typeof(coverage) = 'object'),

    -- A finished run cannot end before it started (both timestamps optional).
    CONSTRAINT lint_evidence_runs_window_check
        CHECK (started_at IS NULL OR finished_at IS NULL OR finished_at >= started_at),

    -- The envelope contract version is positive.
    CONSTRAINT lint_evidence_runs_envelope_version_check
        CHECK (envelope_version >= 1)
);

COMMENT ON TABLE lint_evidence_runs IS
    'Immutable, append-only record of every lint/scan run against one catalog revision or MCP endpoint version: identity, constraints, outcome, normalized findings, coverage (CLX-1.1, #4848)';
COMMENT ON COLUMN lint_evidence_runs.id IS 'Unique identifier for the evidence run';
COMMENT ON COLUMN lint_evidence_runs.subject_type IS 'Subject kind: catalog_revision or mcp_endpoint_version; agrees with whichever FK is set';
COMMENT ON COLUMN lint_evidence_runs.version_record_id IS 'Scanned catalog revision (versions.id) when subject_type=catalog_revision; cascade-deleted with the revision';
COMMENT ON COLUMN lint_evidence_runs.mcp_version_id IS 'Scanned MCP discovery snapshot (mcp_endpoint_versions.id) when subject_type=mcp_endpoint_version; cascade-deleted with the snapshot';
COMMENT ON COLUMN lint_evidence_runs.scanner_id IS 'Stable id of the evidence source (apiome.native-lint, apiome.mcp-lint, external scanner ids later)';
COMMENT ON COLUMN lint_evidence_runs.scanner_version IS 'Version of the scanner engine/binary that produced the raw output, when known';
COMMENT ON COLUMN lint_evidence_runs.adapter_version IS 'Version of the adapter/parser that normalized raw output into the finding envelope';
COMMENT ON COLUMN lint_evidence_runs.profile IS 'Named execution profile/preset the run used (import-capture, discovery-capture, recompute, ...)';
COMMENT ON COLUMN lint_evidence_runs.started_at IS 'When scanner execution started, when known';
COMMENT ON COLUMN lint_evidence_runs.finished_at IS 'When scanner execution finished, when known; never before started_at';
COMMENT ON COLUMN lint_evidence_runs.outcome IS 'Run conclusion: passed, findings, not_run, unavailable, failed, or blocked_by_policy — absent scans are recordable, never silently clean';
COMMENT ON COLUMN lint_evidence_runs.input_fingerprint IS 'Fingerprint of the exact input document/surface the scanner consumed';
COMMENT ON COLUMN lint_evidence_runs.source_fingerprint IS 'Fingerprint of the upstream source the input derives from, when distinct from the input';
COMMENT ON COLUMN lint_evidence_runs.config_fingerprint IS 'Stable hash of the redacted (non-secret) scanner configuration; raw config is never stored';
COMMENT ON COLUMN lint_evidence_runs.raw_artifact_ref IS 'Opaque object-storage reference to the raw scanner output; access-controlled, never exposed verbatim by the API';
COMMENT ON COLUMN lint_evidence_runs.report_fingerprint IS 'Fingerprint of the normalized report; backfill preserves pre-existing quality/score fingerprints byte-for-byte';
COMMENT ON COLUMN lint_evidence_runs.findings IS 'Normalized findings in the source-neutral envelope: rule_id, message, severity, confidence, category, location, remediation, source_fingerprint';
COMMENT ON COLUMN lint_evidence_runs.coverage IS 'Coverage of the run over its subject: {"state": full|partial|none|unknown} plus optional detail';
COMMENT ON COLUMN lint_evidence_runs.envelope_version IS 'Version of the finding-envelope contract the findings array conforms to (starts at 1)';
COMMENT ON COLUMN lint_evidence_runs.created_at IS 'When the evidence row was recorded (insert-only; rows are write-once)';

-- Latest-runs-first per subject; partial so each index only carries its subject kind.
CREATE INDEX IF NOT EXISTS idx_lint_evidence_runs_version
    ON lint_evidence_runs (version_record_id, created_at DESC)
    WHERE version_record_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lint_evidence_runs_mcp_version
    ON lint_evidence_runs (mcp_version_id, created_at DESC)
    WHERE mcp_version_id IS NOT NULL;

-- Cross-subject scanner queries (e.g. "every run buf.lint ever produced").
CREATE INDEX IF NOT EXISTS idx_lint_evidence_runs_scanner
    ON lint_evidence_runs (scanner_id);

-- Fingerprint lookups (waiver matching / staleness checks in later CLX issues).
CREATE INDEX IF NOT EXISTS idx_lint_evidence_runs_report_fingerprint
    ON lint_evidence_runs (report_fingerprint)
    WHERE report_fingerprint IS NOT NULL;

-- ---------------------------------------------------------------------------------------------------
-- Immutability: evidence rows are write-once. Reuses the generic V128 UPDATE-forbid guard.
-- ---------------------------------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trigger_lint_evidence_runs_immutable ON lint_evidence_runs;
CREATE TRIGGER trigger_lint_evidence_runs_immutable
    BEFORE UPDATE ON lint_evidence_runs
    FOR EACH ROW
    EXECUTE FUNCTION mcp_forbid_row_mutation();

-- ---------------------------------------------------------------------------------------------------
-- Backfill 1/2: catalog revisions — versions.quality_report(+fingerprint) -> evidence runs.
--
-- Only revisions that were actually scored get a row (empty report AND null fingerprint means
-- never scored -> intentionally no evidence, so coverage reads not_run). The pre-existing
-- report fingerprint is preserved verbatim. Legacy findings are projected into the envelope;
-- confidence is 'high' because native lint is deterministic. Outcome falls back to the captured
-- score for V124-era rows whose full report predates V160 (fingerprint without findings JSON).
-- ---------------------------------------------------------------------------------------------------
INSERT INTO lint_evidence_runs (
    subject_type, version_record_id, scanner_id, scanner_version, adapter_version, profile,
    finished_at, outcome, config_fingerprint, report_fingerprint, findings, coverage,
    envelope_version
)
SELECT
    'catalog_revision',
    v.id,
    'apiome.native-lint',
    NULL,
    'backfill:V167',
    'import-capture',
    NULL, -- capture time is not recorded on versions; updated_at moves on unrelated edits

    CASE
        WHEN COALESCE(jsonb_array_length(v.quality_report -> 'findings'), 0) > 0
            THEN 'findings'
        WHEN v.quality_score IS NOT NULL AND v.quality_score < 100
            THEN 'findings'
        ELSE 'passed'
    END,
    NULL,
    COALESCE(v.quality_report ->> 'report_fingerprint', v.quality_report_fingerprint),
    COALESCE(
        (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'rule_id', f ->> 'rule',
                    'message', f ->> 'message',
                    'severity', f ->> 'severity',
                    'confidence', 'high',
                    'category', f ->> 'category',
                    'location', jsonb_build_object('path', f ->> 'path'),
                    'remediation', NULL,
                    'source_fingerprint', f ->> 'id'
                )
            )
            FROM jsonb_array_elements(v.quality_report -> 'findings') AS f
        ),
        '[]'::jsonb
    ),
    '{"state": "full"}'::jsonb,
    1
FROM versions v
WHERE v.deleted_at IS NULL
  AND (
        (v.quality_report IS NOT NULL AND v.quality_report <> '{}'::jsonb)
        OR v.quality_report_fingerprint IS NOT NULL
      )
  AND NOT EXISTS (
        SELECT 1 FROM lint_evidence_runs r
        WHERE r.version_record_id = v.id AND r.scanner_id = 'apiome.native-lint'
      );

-- ---------------------------------------------------------------------------------------------------
-- Backfill 2/2: MCP snapshots — mcp_version_scores.report(+fingerprint) -> evidence runs.
--
-- Same envelope projection as backfill 1. input_fingerprint carries the snapshot's
-- surface_fingerprint (the exact surface the scorer consumed); finished_at carries scored_at.
-- ---------------------------------------------------------------------------------------------------
INSERT INTO lint_evidence_runs (
    subject_type, mcp_version_id, scanner_id, scanner_version, adapter_version, profile,
    finished_at, outcome, input_fingerprint, report_fingerprint, findings, coverage,
    envelope_version
)
SELECT
    'mcp_endpoint_version',
    s.version_id,
    'apiome.mcp-lint',
    NULL,
    'backfill:V167',
    'discovery-capture',
    s.scored_at,
    CASE
        WHEN COALESCE(jsonb_array_length(s.report -> 'findings'), 0) > 0
            THEN 'findings'
        WHEN s.score IS NOT NULL AND s.score < 100
            THEN 'findings'
        ELSE 'passed'
    END,
    mv.surface_fingerprint,
    COALESCE(s.report ->> 'report_fingerprint', s.report_fingerprint),
    COALESCE(
        (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'rule_id', f ->> 'rule',
                    'message', f ->> 'message',
                    'severity', f ->> 'severity',
                    'confidence', 'high',
                    'category', f ->> 'category',
                    'location', jsonb_build_object('path', f ->> 'path'),
                    'remediation', NULL,
                    'source_fingerprint', f ->> 'id'
                )
            )
            FROM jsonb_array_elements(s.report -> 'findings') AS f
        ),
        '[]'::jsonb
    ),
    '{"state": "full"}'::jsonb,
    1
FROM mcp_version_scores s
JOIN mcp_endpoint_versions mv ON mv.id = s.version_id
WHERE (
        (s.report IS NOT NULL AND s.report <> '{}'::jsonb)
        OR s.report_fingerprint IS NOT NULL
      )
  AND NOT EXISTS (
        SELECT 1 FROM lint_evidence_runs r
        WHERE r.mcp_version_id = s.version_id AND r.scanner_id = 'apiome.mcp-lint'
      );
