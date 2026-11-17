-- Cumulative level gates — GVM-1.3 (#5856).
--
-- A maturity ladder (GVM-1.1, V390) and its level judgement (GVM-1.2, V391) only describe an
-- API until something refuses on the level. This migration stores the level a guide requires
-- before a revision may publish, and freezes it into the policy pack beside the ladder:
--
--   style_guides.required_publish_level                 the level key a draft must reach before
--                                                        it publishes (e.g. 'silver'); NULL = the
--                                                        level gate is not armed.
--   style_guide_policy_versions.required_publish_level  the same key frozen into a pack, so a
--                                                        historical publish verdict reproduces.
--
-- No CHECK constraint: the key must name a level of the guide's own ladder, and the ladder
-- lives in JSON. apiome-rest (app.maturity_gate) validates it on save, refuses a ladder edit
-- that would drop the required level, and treats a key the frozen ladder does not contain as
-- "unavailable" (audited, never blocking).
--
-- Idempotent. Rollback (additive only):
--   ALTER TABLE apiome.style_guide_policy_versions DROP COLUMN IF EXISTS required_publish_level;
--   ALTER TABLE apiome.style_guides DROP COLUMN IF EXISTS required_publish_level;

SET search_path TO apiome, public;

ALTER TABLE style_guides
    ADD COLUMN IF NOT EXISTS required_publish_level TEXT;

COMMENT ON COLUMN style_guides.required_publish_level IS
    'Maturity level key a revision must reach before it publishes (GVM-1.3, #5856); NULL = no level gate. Validated against the guide''s ladder by apiome-rest';

ALTER TABLE style_guide_policy_versions
    ADD COLUMN IF NOT EXISTS required_publish_level TEXT;

COMMENT ON COLUMN style_guide_policy_versions.required_publish_level IS
    'Required publish level frozen into the policy pack (GVM-1.3, #5856); NULL = no level gate';

DO $$
BEGIN
    RAISE NOTICE 'apiome.style_guides.required_publish_level added and frozen into policy packs (GVM-1.3, #5856).';
END $$;
