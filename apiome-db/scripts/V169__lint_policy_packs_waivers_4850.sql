-- Versioned policy packs, finding waivers, and remediation states — CLX-1.3 (#4850).
--
-- Problem: severity overrides on style guides lack ownership, approval rationale, expiry,
-- historical reproducibility, and a CI gate for accepted risk.
--
-- This migration extends the existing style-guide store (V159) rather than inventing a parallel
-- ruleset:
--   1. Draft gate settings on style_guides (axis_gates, required_coverage, ci_outcomes).
--   2. style_guide_policy_versions — immutable snapshots (policy packs) of a guide's rules +
--      gates; evaluation always pins a concrete pack id + content fingerprint.
--   3. lint_finding_decisions + lint_finding_decision_events — finding lifecycle
--      (open / acknowledged / waived / fixed / false_positive) with rationale, expiry, actor,
--      and audit trail. Waivers match source_fingerprint; expired or unmatched => open.
--   4. lint_policy_evaluations — append-only, reproducible CI/policy outcomes linked to a
--      subject (catalog revision XOR MCP endpoint version), a policy pack, and optional
--      evidence/axis rows.
--
-- Idempotent: CREATE / ALTER IF NOT EXISTS patterns; write-once triggers reuse the shared
-- V128 mcp_forbid_row_mutation() guard (do not drop or redefine it here).
--
-- Rollback notes (additive only — reverse carefully in shared environments):
--   DROP TRIGGER IF EXISTS trigger_style_guide_policy_versions_immutable ON apiome.style_guide_policy_versions;
--   DROP TRIGGER IF EXISTS trigger_lint_finding_decision_events_immutable ON apiome.lint_finding_decision_events;
--   DROP TRIGGER IF EXISTS trigger_lint_policy_evaluations_immutable ON apiome.lint_policy_evaluations;
--   DROP TABLE IF EXISTS apiome.lint_policy_evaluations;
--   DROP TABLE IF EXISTS apiome.lint_finding_decision_events;
--   DROP TABLE IF EXISTS apiome.lint_finding_decisions;
--   DROP TABLE IF EXISTS apiome.style_guide_policy_versions;
--   ALTER TABLE apiome.style_guides DROP COLUMN IF EXISTS axis_gates;
--   ALTER TABLE apiome.style_guides DROP COLUMN IF EXISTS required_coverage;
--   ALTER TABLE apiome.style_guides DROP COLUMN IF EXISTS ci_outcomes;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- Draft policy gate settings on live style guides (editable; snapshotted into policy versions).
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE style_guides
    ADD COLUMN IF NOT EXISTS axis_gates JSONB;

ALTER TABLE style_guides
    ADD COLUMN IF NOT EXISTS required_coverage JSONB;

ALTER TABLE style_guides
    ADD COLUMN IF NOT EXISTS ci_outcomes JSONB;

COMMENT ON COLUMN style_guides.axis_gates IS
    'Draft per-axis CI gates (e.g. {"quality":{"minGrade":"B"}}); NULL = defaults. Snapshotted into style_guide_policy_versions (CLX-1.3, #4850)';
COMMENT ON COLUMN style_guides.required_coverage IS
    'Draft required axis coverage list (e.g. ["quality"]); NULL = ["quality"]. Snapshotted into style_guide_policy_versions (CLX-1.3, #4850)';
COMMENT ON COLUMN style_guides.ci_outcomes IS
    'Draft CI outcome toggles {failOnUnwaivedErrors,failOnRequiredCoverage,failOnAxisGates}; NULL = all true. Snapshotted into style_guide_policy_versions (CLX-1.3, #4850)';

-- ---------------------------------------------------------------------------------------------------
-- style_guide_policy_versions — immutable policy packs (append-only snapshots of a guide).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS style_guide_policy_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    guide_id UUID NOT NULL REFERENCES style_guides(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Monotonic per guide; application assigns next = max(version_number)+1.
    version_number INTEGER NOT NULL,

    -- SHA-256 hex of the canonicalized snapshot body (rules + gates).
    content_fingerprint TEXT NOT NULL,

    -- Enabled/severity/custom_def rows — same shape the style-guide engine compiles from.
    rules_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Per-axis min grade / min score gates at snapshot time.
    axis_gates JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Axes that must be assessed for required coverage (CLX-1.2 compatible; default quality).
    required_coverage JSONB NOT NULL DEFAULT '["quality"]'::jsonb,

    -- Which CI gates are active when evaluating this pack.
    ci_outcomes JSONB NOT NULL DEFAULT
        '{"failOnUnwaivedErrors":true,"failOnRequiredCoverage":true,"failOnAxisGates":true}'::jsonb,

    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_label TEXT,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT style_guide_policy_versions_version_positive_check
        CHECK (version_number >= 1),

    CONSTRAINT style_guide_policy_versions_rules_array_check
        CHECK (jsonb_typeof(rules_snapshot) = 'array'),

    CONSTRAINT style_guide_policy_versions_axis_gates_object_check
        CHECK (jsonb_typeof(axis_gates) = 'object'),

    CONSTRAINT style_guide_policy_versions_required_coverage_array_check
        CHECK (jsonb_typeof(required_coverage) = 'array'),

    CONSTRAINT style_guide_policy_versions_ci_outcomes_object_check
        CHECK (jsonb_typeof(ci_outcomes) = 'object'),

    CONSTRAINT style_guide_policy_versions_guide_version_uq
        UNIQUE (guide_id, version_number)
);

COMMENT ON TABLE style_guide_policy_versions IS
    'Immutable, append-only versioned policy packs snapshotted from style guides: rules, axis gates, required coverage, CI outcomes (CLX-1.3, #4850)';
COMMENT ON COLUMN style_guide_policy_versions.id IS 'Unique identifier for the policy pack version';
COMMENT ON COLUMN style_guide_policy_versions.guide_id IS 'Live style guide this pack was snapshotted from';
COMMENT ON COLUMN style_guide_policy_versions.tenant_id IS 'Tenant that owns the guide (denormalized for scoped lookups)';
COMMENT ON COLUMN style_guide_policy_versions.version_number IS 'Monotonic version number per guide (starts at 1)';
COMMENT ON COLUMN style_guide_policy_versions.content_fingerprint IS 'SHA-256 of the canonicalized snapshot body for historical reproducibility';
COMMENT ON COLUMN style_guide_policy_versions.rules_snapshot IS 'Frozen style_guide_rules projection (rule_id, enabled, severity, custom_def)';
COMMENT ON COLUMN style_guide_policy_versions.axis_gates IS 'Frozen per-axis min grade/score gates';
COMMENT ON COLUMN style_guide_policy_versions.required_coverage IS 'Frozen list of axes that must be assessed';
COMMENT ON COLUMN style_guide_policy_versions.ci_outcomes IS 'Frozen CI outcome toggles for unwaived errors, coverage, and axis gates';
COMMENT ON COLUMN style_guide_policy_versions.actor_user_id IS 'User who published this pack version; NULL if later deleted';
COMMENT ON COLUMN style_guide_policy_versions.actor_label IS 'Human-readable actor label at publish time';
COMMENT ON COLUMN style_guide_policy_versions.created_at IS 'When the pack version was recorded (insert-only; rows are write-once)';

CREATE INDEX IF NOT EXISTS idx_style_guide_policy_versions_guide
    ON style_guide_policy_versions (guide_id, version_number DESC);
CREATE INDEX IF NOT EXISTS idx_style_guide_policy_versions_tenant
    ON style_guide_policy_versions (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_style_guide_policy_versions_fingerprint
    ON style_guide_policy_versions (content_fingerprint);

DROP TRIGGER IF EXISTS trigger_style_guide_policy_versions_immutable ON style_guide_policy_versions;
CREATE TRIGGER trigger_style_guide_policy_versions_immutable
    BEFORE UPDATE ON style_guide_policy_versions
    FOR EACH ROW
    EXECUTE FUNCTION mcp_forbid_row_mutation();

-- ---------------------------------------------------------------------------------------------------
-- lint_finding_decisions — lifecycle / waiver state keyed by stable source_fingerprint.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lint_finding_decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    -- Optional project scope; NULL = tenant-wide. Project-scoped rows take precedence on match.
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,

    -- Envelope source_fingerprint (native: lint-{sha16(path|rule|message)}).
    source_fingerprint TEXT NOT NULL,
    rule_id TEXT,

    state TEXT NOT NULL DEFAULT 'open'
        CONSTRAINT lint_finding_decisions_state_check
            CHECK (state IN ('open', 'acknowledged', 'waived', 'fixed', 'false_positive')),

    owner_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    rationale TEXT,
    linked_ticket TEXT,

    -- Required by application when state = waived; past expiry => evaluate-on-read as open.
    expires_at TIMESTAMP WITH TIME ZONE,

    -- Policy pack in force when this decision was last recorded.
    policy_version_id UUID REFERENCES style_guide_policy_versions(id) ON DELETE SET NULL,

    -- Fingerprint identity at decision time; material evidence change => new fingerprint => no match.
    evidence_fingerprint_at_decision TEXT,

    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_label TEXT,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Waived rows must carry rationale and an expiry (acceptance criteria).
    CONSTRAINT lint_finding_decisions_waiver_fields_check
        CHECK (
            state <> 'waived'
            OR (
                rationale IS NOT NULL AND length(btrim(rationale)) > 0
                AND expires_at IS NOT NULL
            )
        )
);

COMMENT ON TABLE lint_finding_decisions IS
    'Finding remediation / waiver lifecycle keyed by source_fingerprint; expired waivers reopen at evaluate time (CLX-1.3, #4850)';
COMMENT ON COLUMN lint_finding_decisions.id IS 'Unique identifier for the decision row';
COMMENT ON COLUMN lint_finding_decisions.tenant_id IS 'Tenant that owns the decision';
COMMENT ON COLUMN lint_finding_decisions.project_id IS 'Optional project scope; NULL means tenant-wide';
COMMENT ON COLUMN lint_finding_decisions.source_fingerprint IS 'Stable finding identity from the evidence envelope; match key for waivers';
COMMENT ON COLUMN lint_finding_decisions.rule_id IS 'Denormalized rule id for display and filtering';
COMMENT ON COLUMN lint_finding_decisions.state IS 'Lifecycle state: open, acknowledged, waived, fixed, or false_positive';
COMMENT ON COLUMN lint_finding_decisions.owner_user_id IS 'Optional owner responsible for remediation';
COMMENT ON COLUMN lint_finding_decisions.rationale IS 'Approval rationale; required when state is waived';
COMMENT ON COLUMN lint_finding_decisions.linked_ticket IS 'Optional external ticket URL or id';
COMMENT ON COLUMN lint_finding_decisions.expires_at IS 'Waiver expiry; required when waived; past expiry => effective open';
COMMENT ON COLUMN lint_finding_decisions.policy_version_id IS 'Policy pack version active when the decision was recorded';
COMMENT ON COLUMN lint_finding_decisions.evidence_fingerprint_at_decision IS 'source_fingerprint (or evidence identity) stored at decision time for reopen-on-change semantics';
COMMENT ON COLUMN lint_finding_decisions.actor_user_id IS 'User who last mutated the decision';
COMMENT ON COLUMN lint_finding_decisions.actor_label IS 'Human-readable actor label at last mutation';
COMMENT ON COLUMN lint_finding_decisions.created_at IS 'When the decision was first recorded';
COMMENT ON COLUMN lint_finding_decisions.updated_at IS 'When the decision was last mutated';

-- At most one decision per tenant + optional project + fingerprint.
CREATE UNIQUE INDEX IF NOT EXISTS lint_finding_decisions_tenant_fp_uq
    ON lint_finding_decisions (tenant_id, source_fingerprint)
    WHERE project_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS lint_finding_decisions_project_fp_uq
    ON lint_finding_decisions (project_id, source_fingerprint)
    WHERE project_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_lint_finding_decisions_tenant_state
    ON lint_finding_decisions (tenant_id, state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_lint_finding_decisions_fingerprint
    ON lint_finding_decisions (source_fingerprint);
CREATE INDEX IF NOT EXISTS idx_lint_finding_decisions_expires
    ON lint_finding_decisions (expires_at)
    WHERE state = 'waived' AND expires_at IS NOT NULL;

-- ---------------------------------------------------------------------------------------------------
-- lint_finding_decision_events — append-only audit of each decision transition.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lint_finding_decision_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    decision_id UUID NOT NULL REFERENCES lint_finding_decisions(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    before_state TEXT,
    after_state TEXT NOT NULL
        CONSTRAINT lint_finding_decision_events_after_state_check
            CHECK (after_state IN ('open', 'acknowledged', 'waived', 'fixed', 'false_positive')),

    rationale TEXT,
    expires_at TIMESTAMP WITH TIME ZONE,
    linked_ticket TEXT,
    policy_version_id UUID REFERENCES style_guide_policy_versions(id) ON DELETE SET NULL,

    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_label TEXT,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE lint_finding_decision_events IS
    'Append-only audit history for lint finding decisions: before/after state, actor, policy version, rationale (CLX-1.3, #4850)';
COMMENT ON COLUMN lint_finding_decision_events.id IS 'Unique identifier for the audit event';
COMMENT ON COLUMN lint_finding_decision_events.decision_id IS 'Decision row this event belongs to';
COMMENT ON COLUMN lint_finding_decision_events.tenant_id IS 'Tenant scope (denormalized for queries)';
COMMENT ON COLUMN lint_finding_decision_events.before_state IS 'State before the transition; NULL on create';
COMMENT ON COLUMN lint_finding_decision_events.after_state IS 'State after the transition';
COMMENT ON COLUMN lint_finding_decision_events.rationale IS 'Rationale recorded with this transition';
COMMENT ON COLUMN lint_finding_decision_events.expires_at IS 'Expiry recorded with this transition when waived';
COMMENT ON COLUMN lint_finding_decision_events.linked_ticket IS 'Linked ticket recorded with this transition';
COMMENT ON COLUMN lint_finding_decision_events.policy_version_id IS 'Policy pack version recorded with this transition';
COMMENT ON COLUMN lint_finding_decision_events.actor_user_id IS 'Actor who performed the transition';
COMMENT ON COLUMN lint_finding_decision_events.actor_label IS 'Human-readable actor label at event time';
COMMENT ON COLUMN lint_finding_decision_events.created_at IS 'When the event was recorded (insert-only)';

CREATE INDEX IF NOT EXISTS idx_lint_finding_decision_events_decision
    ON lint_finding_decision_events (decision_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lint_finding_decision_events_tenant
    ON lint_finding_decision_events (tenant_id, created_at DESC);

DROP TRIGGER IF EXISTS trigger_lint_finding_decision_events_immutable ON lint_finding_decision_events;
CREATE TRIGGER trigger_lint_finding_decision_events_immutable
    BEFORE UPDATE ON lint_finding_decision_events
    FOR EACH ROW
    EXECUTE FUNCTION mcp_forbid_row_mutation();

-- ---------------------------------------------------------------------------------------------------
-- lint_policy_evaluations — reproducible CI/policy outcomes for a scanned subject.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lint_policy_evaluations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    subject_type VARCHAR(32) NOT NULL,

    version_record_id UUID REFERENCES versions(id) ON DELETE CASCADE,
    mcp_version_id UUID REFERENCES mcp_endpoint_versions(id) ON DELETE CASCADE,

    policy_version_id UUID NOT NULL REFERENCES style_guide_policy_versions(id) ON DELETE RESTRICT,
    policy_content_fingerprint TEXT NOT NULL,

    evidence_run_id UUID REFERENCES lint_evidence_runs(id) ON DELETE SET NULL,
    axis_evaluation_id UUID REFERENCES lint_axis_evaluations(id) ON DELETE SET NULL,

    -- Fingerprint of the evidence used (report or run) for dedupe with subject + policy fingerprint.
    evidence_fingerprint TEXT,

    passed BOOLEAN NOT NULL,
    gate_results JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Per-finding projection separating raw evidence from policy decision.
    finding_decisions JSONB NOT NULL DEFAULT '[]'::jsonb,

    evaluated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT lint_policy_evaluations_subject_type_check
        CHECK (subject_type IN ('catalog_revision', 'mcp_endpoint_version')),

    CONSTRAINT lint_policy_evaluations_single_subject_check
        CHECK (
            (subject_type = 'catalog_revision'
                AND version_record_id IS NOT NULL AND mcp_version_id IS NULL)
            OR
            (subject_type = 'mcp_endpoint_version'
                AND mcp_version_id IS NOT NULL AND version_record_id IS NULL)
        ),

    CONSTRAINT lint_policy_evaluations_gate_results_object_check
        CHECK (jsonb_typeof(gate_results) = 'object'),

    CONSTRAINT lint_policy_evaluations_finding_decisions_array_check
        CHECK (jsonb_typeof(finding_decisions) = 'array')
);

COMMENT ON TABLE lint_policy_evaluations IS
    'Immutable, append-only policy evaluation for one catalog revision or MCP endpoint version: pack pin, gate results, per-finding decisions (CLX-1.3, #4850)';
COMMENT ON COLUMN lint_policy_evaluations.id IS 'Unique identifier for the evaluation row';
COMMENT ON COLUMN lint_policy_evaluations.subject_type IS 'Subject kind: catalog_revision or mcp_endpoint_version; agrees with whichever FK is set';
COMMENT ON COLUMN lint_policy_evaluations.version_record_id IS 'Catalog revision (versions.id) when subject_type=catalog_revision';
COMMENT ON COLUMN lint_policy_evaluations.mcp_version_id IS 'MCP snapshot (mcp_endpoint_versions.id) when subject_type=mcp_endpoint_version';
COMMENT ON COLUMN lint_policy_evaluations.policy_version_id IS 'Pinned style_guide_policy_versions.id used for this evaluation';
COMMENT ON COLUMN lint_policy_evaluations.policy_content_fingerprint IS 'content_fingerprint of the pinned policy pack at evaluation time';
COMMENT ON COLUMN lint_policy_evaluations.evidence_run_id IS 'Optional lint_evidence_runs.id used as raw finding input';
COMMENT ON COLUMN lint_policy_evaluations.axis_evaluation_id IS 'Optional lint_axis_evaluations.id used for coverage and axis gates';
COMMENT ON COLUMN lint_policy_evaluations.evidence_fingerprint IS 'Fingerprint of the evidence input for dedupe with subject + policy fingerprint';
COMMENT ON COLUMN lint_policy_evaluations.passed IS 'True when every enabled CI gate passed';
COMMENT ON COLUMN lint_policy_evaluations.gate_results IS 'Per-gate pass/detail for unwaived_errors, required_coverage, axis_gates';
COMMENT ON COLUMN lint_policy_evaluations.finding_decisions IS 'Per-finding {source_fingerprint, raw_severity, effective_state, waived} keeping raw evidence separate from policy decision';
COMMENT ON COLUMN lint_policy_evaluations.evaluated_at IS 'When the evaluation was computed';
COMMENT ON COLUMN lint_policy_evaluations.created_at IS 'When the row was recorded (insert-only; rows are write-once)';

CREATE INDEX IF NOT EXISTS idx_lint_policy_evaluations_version
    ON lint_policy_evaluations (version_record_id, evaluated_at DESC)
    WHERE version_record_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lint_policy_evaluations_mcp_version
    ON lint_policy_evaluations (mcp_version_id, evaluated_at DESC)
    WHERE mcp_version_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lint_policy_evaluations_policy
    ON lint_policy_evaluations (policy_version_id);
CREATE INDEX IF NOT EXISTS idx_lint_policy_evaluations_evidence_fingerprint
    ON lint_policy_evaluations (evidence_fingerprint)
    WHERE evidence_fingerprint IS NOT NULL;

DROP TRIGGER IF EXISTS trigger_lint_policy_evaluations_immutable ON lint_policy_evaluations;
CREATE TRIGGER trigger_lint_policy_evaluations_immutable
    BEFORE UPDATE ON lint_policy_evaluations
    FOR EACH ROW
    EXECUTE FUNCTION mcp_forbid_row_mutation();
