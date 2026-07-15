-- MCP trust baselines — the approved reference a rediscovery/release is diffed against. CLX-3.4 (#4858).
--
-- A point-in-time score cannot detect a rug pull: tool descriptions, schemas, source releases, and
-- endpoint identity can all change after an operator approved a server, and a stale green badge will
-- keep vouching for the new, worse offering. CLX-3.4 fixes this by pinning a *baseline* — the trust
-- manifest an administrator explicitly approved — so every later snapshot can be diffed against what
-- was actually blessed, not merely against the previous snapshot.
--
--   mcp_trust_baselines — one row per approval. It stores the composed trust-manifest fingerprint and
--                         the full manifest envelope (identity, transport, the reused surface
--                         fingerprint, policy-relevant tool authority annotations, and source/SBOM
--                         digests), the administrator's RATIONALE (AC2 — an approval must say why),
--                         and the gating categories configured for this baseline (which drift deltas
--                         block, AC "notify and gate configured risk deltas"). Approving a new baseline
--                         supersedes the prior one; a partial unique index keeps exactly one live
--                         baseline per endpoint.
--
-- Why a manifest snapshot and not just a fingerprint: AC1 requires every material surface/source change
-- to carry OLD→NEW evidence. The baseline stores the whole approved manifest so the "old" side of a
-- diff is always available, even after the underlying source links or version rows change.
--
-- The manifest reuses existing evidence rather than duplicating it (AC5): the capability/tool/schema
-- portion is the existing mcp_endpoint_versions.surface_fingerprint, the source portion is
-- mcp_endpoint_sources / mcp_source_sboms, so this table adds the approval + composition, not a second
-- discovery pipeline.
--
-- The approval itself is also written to apiome.registry_audit as a policy event by the application
-- (AC2), so "who approved what, when, and why" is queryable from the generic governance audit too.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.mcp_trust_baselines;
--
-- Idempotent: CREATE ... IF NOT EXISTS throughout.

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- mcp_trust_baselines — the operator-approved trust manifest an endpoint is measured against.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mcp_trust_baselines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Denormalized from the endpoint so tenant-scoped listing never needs a join; cascades with tenant.
    tenant_id UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,

    -- The endpoint this baseline approves. A baseline is a fact about the ENDPOINT; superseding one
    -- with a new approval keeps the history but only one row stays live (see the partial unique index).
    endpoint_id UUID NOT NULL REFERENCES mcp_endpoints (id) ON DELETE CASCADE,

    -- The exact snapshot that was approved. Drift is diffed from this snapshot's surface to the current
    -- one; cascades with the endpoint's versions.
    version_id UUID NOT NULL REFERENCES mcp_endpoint_versions (id) ON DELETE CASCADE,

    -- The composed trust-manifest fingerprint that was approved. A later snapshot whose manifest
    -- fingerprint differs has drifted; equal fingerprints mean nothing trust-relevant moved.
    manifest_fingerprint TEXT NOT NULL,

    -- The full approved manifest envelope (algorithm, fingerprint, per-component fingerprints, and the
    -- identity / transport / surfaceFingerprint / permissions / sources projections). Stored whole so
    -- the OLD side of a drift diff is always reconstructable (AC1).
    manifest JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- The administrator's reason for approving this baseline (AC2). Required and non-blank: an approval
    -- that cannot say why is exactly the rubber-stamp this table exists to prevent.
    rationale TEXT NOT NULL,

    -- The drift categories that GATE (block) for this baseline — the "configured risk deltas". Default
    -- is security_regression + coverage_loss; an operator may widen or narrow it per approval.
    gating_categories JSONB NOT NULL DEFAULT '["security_regression","coverage_loss"]'::jsonb,

    -- Who approved it. RESTRICT, not CASCADE: deleting a user must not silently erase the provenance of
    -- an approval other evidence depends on.
    approved_by UUID REFERENCES users (id) ON DELETE RESTRICT,

    -- Soft supersession. When a newer baseline is approved the prior one is stamped here; it stays
    -- readable so historical drift evidence citing it remains interpretable, but it no longer measures
    -- new snapshots.
    superseded_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT mcp_trust_baselines_rationale_not_blank_check
        CHECK (length(trim(rationale)) > 0),

    CONSTRAINT mcp_trust_baselines_fingerprint_not_blank_check
        CHECK (length(trim(manifest_fingerprint)) > 0)
);

-- Exactly one live baseline per endpoint. Superseded rows are excluded, so approving a new baseline
-- after superseding the old one never collides with the endpoint's own approval history.
CREATE UNIQUE INDEX IF NOT EXISTS mcp_trust_baselines_live_unique
    ON mcp_trust_baselines (endpoint_id)
    WHERE superseded_at IS NULL;

CREATE INDEX IF NOT EXISTS mcp_trust_baselines_tenant_idx
    ON mcp_trust_baselines (tenant_id)
    WHERE superseded_at IS NULL;

CREATE INDEX IF NOT EXISTS mcp_trust_baselines_endpoint_idx
    ON mcp_trust_baselines (endpoint_id, created_at DESC);

COMMENT ON TABLE mcp_trust_baselines IS
    'CLX-3.4 (#4858): the operator-approved trust manifest an MCP endpoint is measured against. Each row '
    'pins the approved snapshot, the composed trust-manifest fingerprint and full manifest envelope, the '
    'administrator rationale, and the gating categories (configured risk deltas). Approving a new '
    'baseline supersedes the prior one; a partial unique index keeps one live baseline per endpoint. The '
    'approval is also recorded to registry_audit as a policy event.';

COMMENT ON COLUMN mcp_trust_baselines.manifest IS
    'The full approved trust-manifest envelope, stored whole so the OLD side of a drift diff (AC1 '
    'old→new evidence) is always reconstructable even after underlying source/version rows change.';

COMMENT ON COLUMN mcp_trust_baselines.gating_categories IS
    'The drift categories that block the gate for this baseline (default security_regression + '
    'coverage_loss). The "configured risk deltas" the trust gate and notifications act on.';
