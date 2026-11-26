-- Stale-pact remediation and verification scheduling — PFX-6.2 (#6954).
--
-- A pact goes *stale* when it has not been verified for longer than the workspace's stale
-- threshold. This migration stores what the remediation loop and the verification scheduler of
-- apiome-rest (`app.pact_remediation*`) need:
--
--   pact_verification_settings  — the workspace defaults: verification cadence (`on-publish`,
--                                 `hourly`, `nightly`, `manual-only`), stale threshold, how many
--                                 scheduled verifications may run at once, how long a re-publish
--                                 request stays open, and whether stale pacts open one.
--   pact_verification_override  — a different cadence, threshold or verification target for one
--                                 provider (`consumer_id` NULL) or one consumer ↔ provider pair.
--   pact_staleness              — the stale state the sweep last saw for each pair, so a change
--                                 (fresh → stale, stale → fresh) fires exactly one event.
--   pact_republish_request      — a request to a consumer to re-publish a stale pact, and its
--                                 state: requested → acknowledged → republished / cleared /
--                                 expired (escalated).
--   pact_scheduled_verification — the last scheduled verification attempt of each pair, with why
--                                 it did not run when it did not.
--
-- It also widens two closed lists: a verification result may record `trigger = 'scheduled'`, and a
-- contract webhook may listen for the four remediation events.
--
-- Rules kept by the database:
--
--   1. **Closed lists**: cadences, request states and attempt statuses are CHECKed; apiome-rest
--      (`app.pact_remediation`) mirrors them.
--   2. **Bounded numbers**: a threshold of 1 h … 90 days, 1 … 10 concurrent runs, a request window
--      of 1 h … 30 days.
--   3. **One override per provider and one per pair; one open request per pair.**
--   4. **An override says something**: at least one of cadence, threshold, target.
--   5. **Nothing crosses a tenant.** Every reference to a pacticipant or a verification target is
--      composite `(id, tenant_id)`; a deleted target leaves the override without a target.
--   6. **Everything goes with its pacticipants**: deleting a pacticipant removes its overrides,
--      staleness, requests and attempts.
--
-- Online: five new tables and two widened CHECK constraints; nothing existing is rewritten.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.pact_scheduled_verification;
--   DROP TABLE IF EXISTS apiome.pact_republish_request;
--   DROP TABLE IF EXISTS apiome.pact_staleness;
--   DROP TABLE IF EXISTS apiome.pact_verification_override;
--   DROP TABLE IF EXISTS apiome.pact_verification_settings;
--   (and restore the V444 / V436 lists of verification_result_trigger_check and
--   pact_webhook_events_check)

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- 1. pact_verification_settings
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pact_verification_settings (
    tenant_id UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,

    cadence VARCHAR(16) NOT NULL DEFAULT 'manual-only'
        CONSTRAINT pact_verification_settings_cadence_check
            CHECK (cadence IN ('on-publish', 'hourly', 'nightly', 'manual-only')),
    stale_threshold_hours INTEGER NOT NULL DEFAULT 72
        CONSTRAINT pact_verification_settings_threshold_check
            CHECK (stale_threshold_hours BETWEEN 1 AND 2160),
    max_concurrent_runs INTEGER NOT NULL DEFAULT 2
        CONSTRAINT pact_verification_settings_concurrency_check
            CHECK (max_concurrent_runs BETWEEN 1 AND 10),
    request_window_hours INTEGER NOT NULL DEFAULT 72
        CONSTRAINT pact_verification_settings_window_check
            CHECK (request_window_hours BETWEEN 1 AND 720),
    republish_requests_enabled BOOLEAN NOT NULL DEFAULT TRUE,

    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pact_verification_settings_updated_by
    ON pact_verification_settings (updated_by) WHERE updated_by IS NOT NULL;

COMMENT ON TABLE pact_verification_settings IS
    'Workspace defaults for Pact verification scheduling and stale-pact remediation (PFX-6.2, #6954)';
COMMENT ON COLUMN pact_verification_settings.cadence IS
    'on-publish, hourly, nightly or manual-only: when the hosted verifier runs a pair on its own';
COMMENT ON COLUMN pact_verification_settings.stale_threshold_hours IS
    'A pact not verified for longer than this is stale';
COMMENT ON COLUMN pact_verification_settings.request_window_hours IS
    'How long a re-publish request stays open before it expires and escalates';

-- ---------------------------------------------------------------------------------------------------
-- 2. pact_verification_override
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pact_verification_override (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL,
    provider_id UUID NOT NULL,
    -- NULL: the override is for every consumer of the provider.
    consumer_id UUID,

    cadence VARCHAR(16)
        CONSTRAINT pact_verification_override_cadence_check
            CHECK (cadence IS NULL OR cadence IN ('on-publish', 'hourly', 'nightly', 'manual-only')),
    stale_threshold_hours INTEGER
        CONSTRAINT pact_verification_override_threshold_check
            CHECK (stale_threshold_hours IS NULL OR stale_threshold_hours BETWEEN 1 AND 2160),
    -- The verification target scheduled runs replay against.
    target_id UUID,

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pact_verification_override_says_something_check
        CHECK (cadence IS NOT NULL OR stale_threshold_hours IS NOT NULL OR target_id IS NOT NULL),
    CONSTRAINT pact_verification_override_pair_check
        CHECK (consumer_id IS NULL OR consumer_id <> provider_id),
    CONSTRAINT pact_verification_override_provider_fk
        FOREIGN KEY (provider_id, tenant_id) REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT pact_verification_override_consumer_fk
        FOREIGN KEY (consumer_id, tenant_id) REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT pact_verification_override_target_fk
        FOREIGN KEY (target_id, tenant_id) REFERENCES verification_target (id, tenant_id)
        ON DELETE SET NULL (target_id)
);

-- Rule 3: one provider-wide override, one per pair.
CREATE UNIQUE INDEX IF NOT EXISTS uq_pact_verification_override_provider
    ON pact_verification_override (tenant_id, provider_id) WHERE consumer_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_pact_verification_override_pair
    ON pact_verification_override (tenant_id, provider_id, consumer_id) WHERE consumer_id IS NOT NULL;
-- The references' checks.
CREATE INDEX IF NOT EXISTS idx_pact_verification_override_provider
    ON pact_verification_override (provider_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_pact_verification_override_consumer
    ON pact_verification_override (consumer_id, tenant_id) WHERE consumer_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_pact_verification_override_target
    ON pact_verification_override (target_id, tenant_id) WHERE target_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_pact_verification_override_created_by
    ON pact_verification_override (created_by) WHERE created_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_pact_verification_override_updated_by
    ON pact_verification_override (updated_by) WHERE updated_by IS NOT NULL;

COMMENT ON TABLE pact_verification_override IS
    'A cadence, stale threshold or verification target for one provider or one pair (PFX-6.2, #6954)';
COMMENT ON COLUMN pact_verification_override.consumer_id IS 'NULL: every consumer of the provider';
COMMENT ON COLUMN pact_verification_override.target_id IS 'Where scheduled runs replay the pacts';

-- ---------------------------------------------------------------------------------------------------
-- 3. pact_staleness
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pact_staleness (
    tenant_id UUID NOT NULL,
    provider_id UUID NOT NULL,
    consumer_id UUID NOT NULL,

    -- The pair's newest pact version when the sweep last looked.
    sha CHAR(64) NOT NULL
        CONSTRAINT pact_staleness_sha_check CHECK (sha ~ '^[0-9a-f]{64}$'),
    stale BOOLEAN NOT NULL,
    -- When it was last verified, or published when never verified: what the threshold counts from.
    reference_at TIMESTAMP WITH TIME ZONE NOT NULL,
    threshold_hours INTEGER NOT NULL CONSTRAINT pact_staleness_threshold_check CHECK (threshold_hours >= 1),
    changed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    checked_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (tenant_id, provider_id, consumer_id),
    CONSTRAINT pact_staleness_provider_fk
        FOREIGN KEY (provider_id, tenant_id) REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT pact_staleness_consumer_fk
        FOREIGN KEY (consumer_id, tenant_id) REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pact_staleness_provider ON pact_staleness (provider_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_pact_staleness_consumer ON pact_staleness (consumer_id, tenant_id);

COMMENT ON TABLE pact_staleness IS
    'The stale state the remediation sweep last saw per consumer-provider pair (PFX-6.2, #6954)';

-- ---------------------------------------------------------------------------------------------------
-- 4. pact_republish_request
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pact_republish_request (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- Insertion order, for the list's keyset cursor.
    seq BIGSERIAL NOT NULL,
    tenant_id UUID NOT NULL,
    provider_id UUID NOT NULL,
    consumer_id UUID NOT NULL,

    -- The stale pact: its version and the consumer version that published it last.
    sha CHAR(64) NOT NULL
        CONSTRAINT pact_republish_request_sha_check CHECK (sha ~ '^[0-9a-f]{64}$'),
    consumer_version TEXT NOT NULL
        CONSTRAINT pact_republish_request_version_check CHECK (length(consumer_version) BETWEEN 1 AND 255),

    state VARCHAR(16) NOT NULL DEFAULT 'requested'
        CONSTRAINT pact_republish_request_state_check
            CHECK (state IN ('requested', 'acknowledged', 'republished', 'cleared', 'expired')),
    threshold_hours INTEGER NOT NULL
        CONSTRAINT pact_republish_request_threshold_check CHECK (threshold_hours >= 1),
    -- When the pact was last verified (or published, never verified).
    reference_at TIMESTAMP WITH TIME ZONE NOT NULL,
    requested_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,

    acknowledged_at TIMESTAMP WITH TIME ZONE,
    acknowledged_by UUID REFERENCES users(id) ON DELETE SET NULL,
    acknowledged_by_label TEXT CONSTRAINT pact_republish_request_ack_label_check
        CHECK (acknowledged_by_label IS NULL OR length(acknowledged_by_label) <= 320),
    note TEXT CONSTRAINT pact_republish_request_note_check CHECK (note IS NULL OR length(note) <= 1000),

    resolved_at TIMESTAMP WITH TIME ZONE,
    -- The consumer version that re-published, for `republished`.
    resolved_consumer_version TEXT CONSTRAINT pact_republish_request_resolved_version_check
        CHECK (resolved_consumer_version IS NULL OR length(resolved_consumer_version) <= 255),

    -- What notifying the consumer, and escalating, did: routed, throttled, unowned, catch_all,
    -- unlinked (no owner entity), failed.
    notification_status VARCHAR(16),
    escalation_status VARCHAR(16),
    webhook_deliveries INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT pact_republish_request_provider_fk
        FOREIGN KEY (provider_id, tenant_id) REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT pact_republish_request_consumer_fk
        FOREIGN KEY (consumer_id, tenant_id) REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT pact_republish_request_window_check CHECK (expires_at > requested_at),
    CONSTRAINT pact_republish_request_resolved_check
        CHECK ((state IN ('requested', 'acknowledged')) = (resolved_at IS NULL))
);

-- Rule 3: one open request per pair.
CREATE UNIQUE INDEX IF NOT EXISTS uq_pact_republish_request_open
    ON pact_republish_request (tenant_id, provider_id, consumer_id)
    WHERE state IN ('requested', 'acknowledged');
-- The list, newest first; and the references' checks.
CREATE INDEX IF NOT EXISTS idx_pact_republish_request_list
    ON pact_republish_request (tenant_id, seq DESC);
CREATE INDEX IF NOT EXISTS idx_pact_republish_request_provider
    ON pact_republish_request (provider_id, tenant_id, consumer_id, requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_pact_republish_request_consumer
    ON pact_republish_request (consumer_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_pact_republish_request_acknowledged_by
    ON pact_republish_request (acknowledged_by) WHERE acknowledged_by IS NOT NULL;

COMMENT ON TABLE pact_republish_request IS
    'A request to a consumer to re-publish a stale pact, and its state (PFX-6.2, #6954)';
COMMENT ON COLUMN pact_republish_request.state IS
    'requested, acknowledged, republished (a newer publication), cleared (verified meanwhile), expired';

-- ---------------------------------------------------------------------------------------------------
-- 5. pact_scheduled_verification
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pact_scheduled_verification (
    tenant_id UUID NOT NULL,
    provider_id UUID NOT NULL,
    consumer_id UUID NOT NULL,

    sha CHAR(64) NOT NULL
        CONSTRAINT pact_scheduled_verification_sha_check CHECK (sha ~ '^[0-9a-f]{64}$'),
    attempted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(16) NOT NULL
        CONSTRAINT pact_scheduled_verification_status_check
            CHECK (status IN ('verified', 'failed', 'skipped', 'errored')),
    code VARCHAR(64),
    reason TEXT CONSTRAINT pact_scheduled_verification_reason_check
        CHECK (reason IS NULL OR length(reason) <= 1000),

    PRIMARY KEY (tenant_id, provider_id, consumer_id),
    CONSTRAINT pact_scheduled_verification_provider_fk
        FOREIGN KEY (provider_id, tenant_id) REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT pact_scheduled_verification_consumer_fk
        FOREIGN KEY (consumer_id, tenant_id) REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pact_scheduled_verification_provider
    ON pact_scheduled_verification (provider_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_pact_scheduled_verification_consumer
    ON pact_scheduled_verification (consumer_id, tenant_id);

COMMENT ON TABLE pact_scheduled_verification IS
    'The last scheduled verification attempt of each pair, and why it did not run (PFX-6.2, #6954)';

-- ---------------------------------------------------------------------------------------------------
-- 6. Widened closed lists
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE verification_result DROP CONSTRAINT IF EXISTS verification_result_trigger_check;
ALTER TABLE verification_result
    ADD CONSTRAINT verification_result_trigger_check CHECK (
        trigger IS NULL
        OR trigger IN ('published', 'hosted', 'manual', 'stale-recheck', 'bidirectional', 'scheduled')
    );

ALTER TABLE pact_webhook DROP CONSTRAINT IF EXISTS pact_webhook_events_check;
ALTER TABLE pact_webhook
    ADD CONSTRAINT pact_webhook_events_check CHECK (
        cardinality(events) >= 1
        AND events <@ ARRAY[
            'contract_published',
            'contract_content_changed',
            'contract_requiring_verification_published',
            'provider_verification_published',
            'provider_verification_succeeded',
            'provider_verification_failed',
            'consumer_version_branch_created',
            'contract_became_stale',
            'contract_no_longer_stale',
            'contract_republish_requested',
            'contract_republish_request_expired'
        ]::text[]
    );
