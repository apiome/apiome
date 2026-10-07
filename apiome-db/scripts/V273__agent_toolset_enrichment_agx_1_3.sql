-- Description enrichment pass — AGX-1.3 (#4531).
--
-- Many specs leave operations and parameters undescribed. The AGX-1.1 compiler turns them into
-- valid tools an agent cannot choose or fill in. The enrichment pass proposes better descriptions
-- with the copilot (Ollama), synthesized from the spec's own documentation, and a person reviews
-- every proposal. This migration stores those proposals and the per-toolset opt-out:
--
--   agent_toolsets.description_enrichment — whether accepted proposals are served (opt-out).
--   agent_toolset_enrichments            — one proposal per thin tool or parameter description.
--
-- Four rules shape the schema:
--
--   1. **Nothing AI-generated is served without acceptance.** Only `accepted_description` is ever
--      compiled into a toolset, and `agent_toolset_enrichments_review_ck` makes it impossible to
--      store one without the review that accepted it (`reviewed_at`). A `proposed` row has no
--      reviewer and no accepted text; a `rejected` row has a reviewer and no accepted text.
--
--   2. **One proposal per description, so the pass is idempotent.** `target_key` addresses the
--      description: the operation key (`GET /pets/{id}`) for a tool, the canonical parameter key
--      (`GET /pets#query.limit`) for a parameter. It is unique per toolset and the application
--      inserts with ON CONFLICT DO NOTHING, so re-running the pass never duplicates a proposal and
--      never overwrites a reviewed one. The toolset's version is published (immutable, V083), so
--      the descriptions a proposal was written for cannot drift under it.
--
--   3. **Opting out serves raw descriptions.** `description_enrichment` defaults to true: a
--      proposal only reaches agents after a person accepts it, so serving accepted text is the
--      expected behaviour. Switching it off serves the spec-derived descriptions unchanged and keeps
--      the proposals and reviews for later.
--
--   4. **Reviews are audited by the application** in `apiome.access_audit`
--      (`agent.toolset.enrichment.run`, `agent.toolset.enrichment.review`), not here.
--
-- Agent-hostile flags (missing descriptions, examples, error docs) are computed from the spec on
-- read and are not stored.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.agent_toolset_enrichments;
--   ALTER TABLE apiome.agent_toolsets DROP COLUMN IF EXISTS description_enrichment;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- Rule 3: the per-toolset opt-out.
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE agent_toolsets
    ADD COLUMN IF NOT EXISTS description_enrichment BOOLEAN NOT NULL DEFAULT true;

COMMENT ON COLUMN agent_toolsets.description_enrichment IS
    'AGX-1.3 (#4531): whether accepted description-enrichment proposals are served in the compiled '
    'toolset. False serves the spec-derived descriptions unchanged.';

-- ---------------------------------------------------------------------------------------------------
-- agent_toolset_enrichments — reviewable description proposals.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_toolset_enrichments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    toolset_id UUID NOT NULL REFERENCES agent_toolsets(id) ON DELETE CASCADE,

    -- What the proposal describes: a tool, or one parameter of it.
    operation_key TEXT NOT NULL
        CONSTRAINT agent_toolset_enrichments_operation_key_ck
            CHECK (char_length(operation_key) BETWEEN 1 AND 2048),
    target_kind VARCHAR(16) NOT NULL
        CONSTRAINT agent_toolset_enrichments_target_kind_ck
            CHECK (target_kind IN ('tool', 'parameter')),
    -- Rule 2: the description's stable address.
    target_key TEXT NOT NULL
        CONSTRAINT agent_toolset_enrichments_target_key_ck
            CHECK (char_length(target_key) BETWEEN 1 AND 2048),
    -- The parameter as `location.name` (`query.limit`); only for a parameter target.
    parameter_name TEXT,
    CONSTRAINT agent_toolset_enrichments_parameter_ck CHECK (
        (target_kind = 'tool') = (parameter_name IS NULL)
    ),

    -- The spec's description when the proposal was made (NULL when there was none).
    original_description TEXT,
    -- What the copilot proposed. Never served as is.
    proposed_description TEXT NOT NULL
        CONSTRAINT agent_toolset_enrichments_proposed_ck
            CHECK (char_length(btrim(proposed_description)) BETWEEN 1 AND 2000),
    -- The Ollama model that wrote the proposal.
    model VARCHAR(128) NOT NULL,

    -- Rule 1: the review.
    status VARCHAR(16) NOT NULL DEFAULT 'proposed'
        CONSTRAINT agent_toolset_enrichments_status_ck
            CHECK (status IN ('proposed', 'accepted', 'rejected')),
    -- The text served once accepted: the proposal, or the reviewer's edit of it.
    accepted_description TEXT
        CONSTRAINT agent_toolset_enrichments_accepted_ck
            CHECK (char_length(btrim(accepted_description)) BETWEEN 1 AND 2000),
    reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMPTZ,
    CONSTRAINT agent_toolset_enrichments_review_ck CHECK (
        (status = 'proposed' AND accepted_description IS NULL AND reviewed_at IS NULL)
        OR (status = 'accepted' AND accepted_description IS NOT NULL AND reviewed_at IS NOT NULL)
        OR (status = 'rejected' AND accepted_description IS NULL AND reviewed_at IS NOT NULL)
    ),

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT agent_toolset_enrichments_target_uq UNIQUE (toolset_id, target_key)
);

-- Compiling a toolset reads its accepted proposals.
CREATE INDEX IF NOT EXISTS idx_agent_toolset_enrichments_accepted
    ON agent_toolset_enrichments (toolset_id)
    WHERE status = 'accepted';

COMMENT ON TABLE agent_toolset_enrichments IS
    'AGX-1.3 (#4531): copilot-proposed descriptions for thin tool/parameter descriptions of an '
    'agent toolset. Only accepted_description is served, and only after a person accepts it.';

COMMENT ON COLUMN agent_toolset_enrichments.target_key IS
    'The operation key for a tool target, the canonical parameter key for a parameter target. '
    'Unique per toolset, which makes the enrichment pass idempotent.';

COMMENT ON COLUMN agent_toolset_enrichments.accepted_description IS
    'The text served to agents: the proposal or a reviewer''s edit of it. Set only on acceptance.';
