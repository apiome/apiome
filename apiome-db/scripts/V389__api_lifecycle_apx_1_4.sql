-- Product and plan lifecycle — APX-1.4 (#6101).
--
-- Plans change: a tier is withdrawn or replaced. V387 (api_products) and V388 (api_plans) already carry
-- a `state` of draft | published | deprecated | retired; this migration records *when* and *why*:
--
--   api_plans    + deprecated_at        when the plan was deprecated (new subscriptions are blocked from then)
--                + retire_at            the date the plan retires (its place on the sunset timeline)
--                + retired_at           when it was retired (provisioning revoked)
--                + deprecation_message  what consumers are told (`Move to Premium before 31 March.`)
--                + successor_plan_id    the plan consumers migrate to, in the same product
--                + owners_notified_at   when subscribed application owners were told — once per deprecation
--   api_products + deprecated_at, retire_at, retired_at, deprecation_message
--
-- Rules kept by the database:
--
--   1. **A retirement date belongs to a deprecated (or retired) record.** A draft or published plan
--      or product has no `retire_at`, and only a retired one has `retired_at`.
--   2. **A plan is not its own successor.** That the successor is a published plan of the same
--      product with the same auth strategy (so a consumer keeps its key) is apiome-rest's rule
--      (app.api_lifecycle), checked on every write; deleting the successor clears the link.
--   3. **A message is bounded** (1000 characters).
--
-- Subscriptions, application owners and gateway provisioning arrive with APX-2.x and APX-4.x; until
-- then deprecation notifies nobody, migration moves nothing and retirement revokes nothing, but every
-- transition is audited and `owners_notified_at` is already the once-only marker those hooks use.
--
-- Rollback notes (reverse carefully in shared environments):
--   ALTER TABLE apiome.api_plans DROP CONSTRAINT IF EXISTS api_plans_retire_at_state_check,
--       DROP CONSTRAINT IF EXISTS api_plans_retired_at_state_check,
--       DROP CONSTRAINT IF EXISTS api_plans_successor_not_self_check,
--       DROP CONSTRAINT IF EXISTS api_plans_deprecation_message_length_check,
--       DROP COLUMN IF EXISTS deprecated_at, DROP COLUMN IF EXISTS retire_at, DROP COLUMN IF EXISTS retired_at,
--       DROP COLUMN IF EXISTS deprecation_message, DROP COLUMN IF EXISTS successor_plan_id,
--       DROP COLUMN IF EXISTS owners_notified_at;
--   ALTER TABLE apiome.api_products DROP CONSTRAINT IF EXISTS api_products_retire_at_state_check,
--       DROP CONSTRAINT IF EXISTS api_products_retired_at_state_check,
--       DROP CONSTRAINT IF EXISTS api_products_deprecation_message_length_check,
--       DROP COLUMN IF EXISTS deprecated_at, DROP COLUMN IF EXISTS retire_at, DROP COLUMN IF EXISTS retired_at,
--       DROP COLUMN IF EXISTS deprecation_message;
--   DROP INDEX IF EXISTS apiome.idx_api_plans_retire_at; DROP INDEX IF EXISTS apiome.idx_api_products_retire_at;

SET search_path TO apiome, public;

ALTER TABLE api_plans
    ADD COLUMN IF NOT EXISTS deprecated_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS retire_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS retired_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS deprecation_message TEXT,
    ADD COLUMN IF NOT EXISTS successor_plan_id UUID REFERENCES api_plans(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS owners_notified_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE api_plans
    DROP CONSTRAINT IF EXISTS api_plans_retire_at_state_check,
    DROP CONSTRAINT IF EXISTS api_plans_retired_at_state_check,
    DROP CONSTRAINT IF EXISTS api_plans_successor_not_self_check,
    DROP CONSTRAINT IF EXISTS api_plans_deprecation_message_length_check,
    -- Rule 1.
    ADD CONSTRAINT api_plans_retire_at_state_check
        CHECK (retire_at IS NULL OR state IN ('deprecated', 'retired')),
    ADD CONSTRAINT api_plans_retired_at_state_check
        CHECK (retired_at IS NULL OR state = 'retired'),
    -- Rule 2.
    ADD CONSTRAINT api_plans_successor_not_self_check
        CHECK (successor_plan_id IS NULL OR successor_plan_id <> id),
    -- Rule 3.
    ADD CONSTRAINT api_plans_deprecation_message_length_check
        CHECK (deprecation_message IS NULL OR length(deprecation_message) <= 1000);

ALTER TABLE api_products
    ADD COLUMN IF NOT EXISTS deprecated_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS retire_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS retired_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS deprecation_message TEXT;

ALTER TABLE api_products
    DROP CONSTRAINT IF EXISTS api_products_retire_at_state_check,
    DROP CONSTRAINT IF EXISTS api_products_retired_at_state_check,
    DROP CONSTRAINT IF EXISTS api_products_deprecation_message_length_check,
    -- Rule 1.
    ADD CONSTRAINT api_products_retire_at_state_check
        CHECK (retire_at IS NULL OR state IN ('deprecated', 'retired')),
    ADD CONSTRAINT api_products_retired_at_state_check
        CHECK (retired_at IS NULL OR state = 'retired'),
    -- Rule 3.
    ADD CONSTRAINT api_products_deprecation_message_length_check
        CHECK (deprecation_message IS NULL OR length(deprecation_message) <= 1000);

-- The sunset timeline reads deprecated and retired records of a tenant.
CREATE INDEX IF NOT EXISTS idx_api_plans_retire_at
    ON api_plans (tenant_id, retire_at)
    WHERE deleted_at IS NULL AND state IN ('deprecated', 'retired');

CREATE INDEX IF NOT EXISTS idx_api_products_retire_at
    ON api_products (tenant_id, retire_at)
    WHERE deleted_at IS NULL AND state IN ('deprecated', 'retired');

COMMENT ON COLUMN api_plans.deprecated_at IS 'When the plan was deprecated; new subscriptions are blocked from then';
COMMENT ON COLUMN api_plans.retire_at IS 'The date the plan retires (sunset timeline); deprecated or retired plans only';
COMMENT ON COLUMN api_plans.retired_at IS 'When the plan was retired and its provisioning revoked';
COMMENT ON COLUMN api_plans.deprecation_message IS 'What subscribed application owners are told';
COMMENT ON COLUMN api_plans.successor_plan_id IS 'The plan consumers migrate to (same product, same auth strategy)';
COMMENT ON COLUMN api_plans.owners_notified_at IS 'When subscribed application owners were notified; once per deprecation';
COMMENT ON COLUMN api_products.deprecated_at IS 'When the product was deprecated';
COMMENT ON COLUMN api_products.retire_at IS 'The date the product retires (sunset timeline)';
COMMENT ON COLUMN api_products.retired_at IS 'When the product was retired';
COMMENT ON COLUMN api_products.deprecation_message IS 'What consumers are told about the deprecation';
