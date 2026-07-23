-- First-tenant onboarding wizard resumability + funnel telemetry (OLO-4.5, #4209).
--
-- Two tables backing the onboarding wizard's "abandon mid-wizard, resume where you left off, and
-- measure the funnel" behaviour, both following patterns already in the schema:
--
-- 1. `onboarding_wizard_state` — the resume state, one upsertable row per user (mirrors the
--    `oauth_signup_pending` V071 pattern: a short-lived staging row with an `expires_at` sweep
--    column). A tenant-less user's wizard writes its current step and the organization name/slug
--    they have entered so far; on the next login the wizard reloads the row and reopens on that
--    step with the values pre-filled. The row is cleared when the tenant is provisioned (the
--    wizard no longer shows once a membership exists) and abandoned rows are pruned by
--    `expires_at` — the "abandon cleanup" half of the ticket. Keyed by `user_id` so there is at
--    most one in-flight wizard per user; it cascades away with the user.
--
-- 2. `onboarding_funnel_events` — append-only step-reached / step-completed telemetry for the
--    onboarding funnel (mirrors the `auth_events` V193 append-only-ledger idea, without the hash
--    chain: these are metrics rows, not a tamper-evident audit). Each row records the step and
--    whether the user `reached` it, `completed` the wizard from it, or `abandoned` it, so drop-off
--    per step is a straight GROUP BY. `user_id` is nullable and set-null on user delete so the
--    aggregate funnel survives account deletion. Writes from apiome-rest are best-effort — a failed
--    telemetry insert must never fail the wizard step it records.
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS onboarding_wizard_state (
    user_id UUID PRIMARY KEY REFERENCES apiome.users(id) ON DELETE CASCADE,
    step VARCHAR(32) NOT NULL,
    org_name VARCHAR(255),
    slug VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_onboarding_wizard_state_expires
    ON onboarding_wizard_state (expires_at);

COMMENT ON TABLE onboarding_wizard_state IS 'Resume state for the first-tenant onboarding wizard: one row per user, upserted per step, pruned by expires_at (OLO-4.5, #4209)';
COMMENT ON COLUMN onboarding_wizard_state.step IS 'Wizard step the user was on (welcome, organization, summary, done)';
COMMENT ON COLUMN onboarding_wizard_state.org_name IS 'Organization display name entered so far; null before the organization step';
COMMENT ON COLUMN onboarding_wizard_state.slug IS 'Tenant slug entered so far; null before the organization step';
COMMENT ON COLUMN onboarding_wizard_state.expires_at IS 'Sweep column: abandoned wizards past this instant are pruned (mirrors oauth_signup_pending, V071)';

CREATE TABLE IF NOT EXISTS onboarding_funnel_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    step VARCHAR(32) NOT NULL,
    event VARCHAR(16) NOT NULL,
    detail JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT onboarding_funnel_events_event_check
        CHECK (event IN ('reached', 'completed', 'abandoned'))
);

CREATE INDEX IF NOT EXISTS idx_onboarding_funnel_events_step_event
    ON onboarding_funnel_events (step, event);
CREATE INDEX IF NOT EXISTS idx_onboarding_funnel_events_created_at
    ON onboarding_funnel_events (created_at DESC);

COMMENT ON TABLE onboarding_funnel_events IS 'Append-only onboarding funnel telemetry: step reached/completed/abandoned events for conversion metrics (OLO-4.5, #4209)';
COMMENT ON COLUMN onboarding_funnel_events.step IS 'Wizard step the event is about (welcome, organization, summary, done)';
COMMENT ON COLUMN onboarding_funnel_events.event IS 'reached (landed on the step), completed (finished the wizard), or abandoned';
COMMENT ON COLUMN onboarding_funnel_events.user_id IS 'User the event belongs to; nulled on account deletion so aggregate funnel metrics survive';
COMMENT ON COLUMN onboarding_funnel_events.detail IS 'Optional structured context (e.g. whether the step was resumed)';
