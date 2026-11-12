-- =============================================================================
-- V367: Advanced component governance and lifecycle (DCW-3.4, private-suite#2364)
-- =============================================================================
-- Builds on the DCW-3.1 component library (V366) without changing its MVP
-- guarantees: published revisions stay immutable and every row stays
-- tenant-scoped.
--
--   * apiome.style_guides gains the component-library policy, so administrators
--     configure it through the existing governance primitive (the GOV-1.4
--     guide chain, next to the COL-2.3 version approval policy):
--       - component_approval_stages        ordered multi-stage approval policy
--       - component_deprecation_notice_days minimum notice before a sunset
--   * apiome.component_revision_approvals  — reviewer decisions on a draft
--     revision, per policy stage, bound to the payload digest they judged
--     (the COL-2.1 approve / request_changes vocabulary; decisions are
--     immutable history)
--   * apiome.component_revision_deprecations — scheduled deprecation of a
--     published revision: sunset date, optional replacement revision, and
--     migration guidance. Metadata only; the revision itself never changes.
--
-- Bulk consumer upgrades and audit exports need no new tables: upgrades
-- replace version_component_pins rows (soft delete + insert) and every
-- governance mutation appends to apiome.component_library_audit.

SET search_path TO apiome, public;

-- -----------------------------------------------------------------------------
-- Policy on the governing style guide
-- -----------------------------------------------------------------------------

ALTER TABLE apiome.style_guides
    ADD COLUMN IF NOT EXISTS component_approval_stages JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE apiome.style_guides
    ADD COLUMN IF NOT EXISTS component_deprecation_notice_days INTEGER NOT NULL DEFAULT 0;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'style_guides_component_approval_stages_ck'
          AND conrelid = 'apiome.style_guides'::regclass
    ) THEN
        ALTER TABLE apiome.style_guides
            ADD CONSTRAINT style_guides_component_approval_stages_ck
            CHECK (
                jsonb_typeof(component_approval_stages) = 'array'
                AND jsonb_array_length(component_approval_stages) <= 5
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'style_guides_component_deprecation_notice_days_ck'
          AND conrelid = 'apiome.style_guides'::regclass
    ) THEN
        ALTER TABLE apiome.style_guides
            ADD CONSTRAINT style_guides_component_deprecation_notice_days_ck
            CHECK (component_deprecation_notice_days BETWEEN 0 AND 365);
    END IF;
END $$;

COMMENT ON COLUMN apiome.style_guides.component_approval_stages IS
    'DCW-3.4: ordered component-library approval stages, each '
    '{"name", "requiredApprovals" (1-20), "requiredReviewerRole" (role slug or null)}. '
    'An empty array (default) means component publishes need no approval.';
COMMENT ON COLUMN apiome.style_guides.component_deprecation_notice_days IS
    'DCW-3.4: minimum days between scheduling a component revision deprecation and its '
    'sunset (0-365, default 0).';

-- -----------------------------------------------------------------------------
-- Approval decisions on draft revisions
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS apiome.component_revision_approvals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    component_id UUID NOT NULL REFERENCES apiome.operational_components(id) ON DELETE CASCADE,
    revision_id UUID NOT NULL
        REFERENCES apiome.operational_component_revisions(id) ON DELETE CASCADE,
    stage_index INTEGER NOT NULL,
    stage_name TEXT NOT NULL,
    user_id UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    decision TEXT NOT NULL,
    note TEXT,
    payload_digest TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT component_revision_approval_stage_index CHECK (stage_index BETWEEN 0 AND 4),
    CONSTRAINT component_revision_approval_decision CHECK (
        decision IN ('approve', 'request_changes')
    ),
    CONSTRAINT component_revision_approval_note CHECK (note IS NULL OR length(note) <= 5000),
    -- A reviewer decides once per stage for one payload; editing the draft
    -- changes the digest, which is what makes earlier decisions stale.
    CONSTRAINT uq_component_revision_approval UNIQUE (revision_id, stage_index, user_id, payload_digest)
);

COMMENT ON TABLE apiome.component_revision_approvals IS
    'Reviewer decisions on a draft component revision per approval stage (DCW-3.4). '
    'Decisions are immutable; only rows whose payload_digest matches the revision''s current '
    'digest count toward the policy.';
COMMENT ON COLUMN apiome.component_revision_approvals.stage_name IS
    'The stage name at decision time, so audit history reads correctly after a policy edit.';
COMMENT ON COLUMN apiome.component_revision_approvals.payload_digest IS
    'The revision payload digest (sha256:<hex>) the reviewer judged.';

CREATE INDEX IF NOT EXISTS idx_component_revision_approvals_revision
    ON apiome.component_revision_approvals (revision_id, stage_index);

-- -----------------------------------------------------------------------------
-- Scheduled deprecations of published revisions
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS apiome.component_revision_deprecations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    component_id UUID NOT NULL REFERENCES apiome.operational_components(id) ON DELETE CASCADE,
    revision_id UUID NOT NULL
        REFERENCES apiome.operational_component_revisions(id) ON DELETE RESTRICT,
    replacement_revision_id UUID
        REFERENCES apiome.operational_component_revisions(id) ON DELETE RESTRICT,
    sunset_at TIMESTAMPTZ NOT NULL,
    migration_guide TEXT,
    policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    scheduled_by UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cancelled_at TIMESTAMPTZ,
    cancelled_by UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    CONSTRAINT component_revision_deprecation_guide CHECK (
        migration_guide IS NULL OR length(migration_guide) <= 10000
    ),
    CONSTRAINT component_revision_deprecation_replacement CHECK (
        replacement_revision_id IS NULL OR replacement_revision_id <> revision_id
    ),
    CONSTRAINT component_revision_deprecation_cancelled_by CHECK (
        cancelled_at IS NOT NULL OR cancelled_by IS NULL
    )
);

COMMENT ON TABLE apiome.component_revision_deprecations IS
    'Scheduled deprecation of a published component revision (DCW-3.4). The revision row is '
    'never modified; after sunset_at new pins to it are refused, existing pins keep working.';
COMMENT ON COLUMN apiome.component_revision_deprecations.policy IS
    'Snapshot of the deprecation policy the schedule was accepted under (notice days).';
COMMENT ON COLUMN apiome.component_revision_deprecations.cancelled_at IS
    'Set when the deprecation is withdrawn; NULL while it is live.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_component_revision_deprecation_live
    ON apiome.component_revision_deprecations (revision_id)
    WHERE cancelled_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_component_revision_deprecations_tenant
    ON apiome.component_revision_deprecations (tenant_id, sunset_at)
    WHERE cancelled_at IS NULL;

COMMENT ON TABLE apiome.component_library_audit IS
    'Append-only ledger for component-library lifecycle and pin mutations (DCW-3.1, DCW-3.4): '
    'component.create, component.delete, revision.draft, revision.update, revision.publish, '
    'revision.delete, pin.create, pin.remove, revision.approval, deprecation.schedule, '
    'deprecation.cancel, pin.upgrade, upgrade.bulk. Written in the same transaction as the '
    'mutation it records. Subject ids are plain UUIDs (no FK) so history survives deletes.';
