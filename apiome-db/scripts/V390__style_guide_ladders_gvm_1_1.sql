-- Maturity ladders frozen into policy packs — GVM-1.1 (#5854).
--
-- Problem: a style guide yields one A–F grade, per-axis axis_gates and error-level blocking.
-- Governance buyers ask "what level is this API at?" — ordered levels a team climbs (Bronze →
-- Silver → Gold) — and Apiome had nowhere to store the answer.
--
-- This migration:
--   1. Creates apiome.style_guide_ladders — at most one ordered ladder per style guide.
--      `levels` is an ordered JSON array, lowest level first:
--        [{"key": "bronze", "label": "Bronze",
--          "rules":    [{"ruleId": "...", "maxSeverity": "error|warning|info|none"}],
--          "axes":     [{"axis": "quality", "minGrade": "B", "minScore": 80}],
--          "evidence": ["review_approved", "verification_passing"],
--          "waiversSatisfy": false}, ...]
--      A ladder is cumulative: level n implicitly includes every requirement of level n-1.
--      Rule ids, axis keys and the cumulative rule are validated by apiome-rest
--      (app.style_guide_ladder) against the rule registry and the axis vocabulary, which live
--      in code; the CHECK below only pins the JSON shape.
--   2. Adds a nullable `ladder` column to style_guide_revisions (V236) and
--      style_guide_policy_versions (V169) so both snapshots freeze the ladder beside the rules
--      and gates, and a historical level evaluation can be reproduced. NULL means "this guide
--      had no ladder" — never an empty ladder.
--   3. Extends the revision change_kind vocabulary with 'ladder_changed'.
--
-- No ladder is seeded: the default Bronze/Silver/Gold ladder of the built-in Apiome Recommended
-- guide is a read-only template served by apiome-rest, not applied to any tenant.
--
-- Idempotent: CREATE / ALTER IF NOT EXISTS; the change_kind constraint is dropped and re-added.
--
-- Rollback notes (additive only):
--   ALTER TABLE apiome.style_guide_policy_versions DROP COLUMN IF EXISTS ladder;
--   ALTER TABLE apiome.style_guide_revisions DROP COLUMN IF EXISTS ladder;
--   (restore the V236 change_kind CHECK without 'ladder_changed')
--   DROP TABLE IF EXISTS apiome.style_guide_ladders;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- style_guide_ladders — one editable ladder per guide.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS style_guide_ladders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    guide_id UUID NOT NULL UNIQUE REFERENCES style_guides(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    name TEXT NOT NULL,

    -- Ordered levels, lowest first (shape in the header comment).
    levels JSONB NOT NULL,

    -- SHA-256 hex over the canonical JSON of {name, levels}.
    content_fingerprint TEXT NOT NULL,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT style_guide_ladders_levels_array_check
        CHECK (jsonb_typeof(levels) = 'array')
);

COMMENT ON TABLE style_guide_ladders IS
    'Ordered, cumulative maturity ladder of a style guide (at most one per guide; GVM-1.1, #5854)';
COMMENT ON COLUMN style_guide_ladders.guide_id IS 'The style guide this ladder belongs to (unique: one ladder per guide)';
COMMENT ON COLUMN style_guide_ladders.tenant_id IS 'Tenant that owns the guide (denormalized for scoped lookups)';
COMMENT ON COLUMN style_guide_ladders.name IS 'Display name of the ladder';
COMMENT ON COLUMN style_guide_ladders.levels IS 'Ordered levels, lowest first: [{key, label, rules[{ruleId, maxSeverity}], axes[{axis, minGrade?, minScore?}], evidence[], waiversSatisfy}]';
COMMENT ON COLUMN style_guide_ladders.content_fingerprint IS 'SHA-256 of the canonical {name, levels} JSON';

CREATE INDEX IF NOT EXISTS idx_style_guide_ladders_tenant
    ON style_guide_ladders (tenant_id);

-- ---------------------------------------------------------------------------------------------------
-- Snapshots freeze the ladder beside rules and gates.
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE style_guide_revisions
    ADD COLUMN IF NOT EXISTS ladder JSONB;

COMMENT ON COLUMN style_guide_revisions.ladder IS
    'Frozen maturity ladder {name, levels} at snapshot time; NULL = the guide had no ladder (GVM-1.1, #5854)';

ALTER TABLE style_guide_policy_versions
    ADD COLUMN IF NOT EXISTS ladder JSONB;

COMMENT ON COLUMN style_guide_policy_versions.ladder IS
    'Frozen maturity ladder {name, levels} of the policy pack; NULL = no ladder (GVM-1.1, #5854)';

-- ---------------------------------------------------------------------------------------------------
-- Revision change vocabulary gains 'ladder_changed'.
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE style_guide_revisions
    DROP CONSTRAINT IF EXISTS style_guide_revisions_change_kind_check;

ALTER TABLE style_guide_revisions
    ADD CONSTRAINT style_guide_revisions_change_kind_check
        CHECK (change_kind IN ('created', 'edited', 'rules_changed',
                               'custom_rules_changed', 'policy_changed', 'imported',
                               'ladder_changed'));

COMMENT ON COLUMN style_guide_revisions.change_kind IS 'What produced the revision: created | edited | rules_changed | custom_rules_changed | policy_changed | imported | ladder_changed';

DO $$
BEGIN
    RAISE NOTICE 'apiome.style_guide_ladders created; ladder frozen into revisions and policy packs (GVM-1.1, #5854).';
END $$;
