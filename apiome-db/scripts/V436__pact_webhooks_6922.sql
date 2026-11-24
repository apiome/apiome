-- Contract webhooks — PFX-1.9 (#6922).
--
-- CI needs to be told "a pact needs verifying" and "a verification finished". This migration stores
-- the webhooks a workspace defines for those events and what each firing did:
--
--   pact_webhook           — one webhook in the Pact Broker's shape: the events it fires on, the
--                            consumer and/or provider it is limited to, and the HTTP request to send
--                            (method, URL, headers, body template, basic-auth user).
--   pact_triggered_webhook — one firing of a webhook for one event: which pact or verification
--                            result caused it. Its delivery is a row of the existing
--                            push_webhook_delivery_events queue, so retries, dead-lettering and the
--                            attempt history are the ones every other outbound webhook has (#2588).
--
-- Rules kept by the database:
--
--   1. **No secret in the clear.** A webhook's password, its secret header values (Authorization,
--      tokens) and its HMAC signing secret are stored only in `secret_ciphertext`, sealed by
--      apiome-rest's envelope cipher (`app.pact_webhook_secrets`). `secret_fields` names what is
--      sealed so a read can say "set" without opening it. Ciphertext and key version come together.
--   2. **Events are a closed list**, at least one per webhook.
--   3. **Only POST, PUT and PATCH to http(s) URLs.** The address rules (no private or loopback
--      hosts) are apiome-rest's SSRF guard, applied when a webhook is saved and again on every send.
--   4. **Nothing crosses a tenant.** A webhook names its consumer and provider by
--      `(id, tenant_id)`; a firing names its webhook the same way.
--   5. **A firing goes with its webhook.** Deleting a webhook removes its queued deliveries, its
--      firings and their logs; deleting a pacticipant removes the webhooks limited to it.
--
-- The delivery queue gains `pact_webhook_id` (which webhook a queued delivery belongs to; the
-- worker then sends the webhook's own request instead of the subscription envelope) and the attempt
-- history gains `execution_log` (the request and response of one attempt, with secrets redacted).
--
-- Online: two new tables and two nullable columns; nothing existing is rewritten.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.pact_triggered_webhook;
--   DELETE FROM apiome.push_webhook_delivery_events WHERE pact_webhook_id IS NOT NULL;
--   ALTER TABLE apiome.push_webhook_delivery_events DROP COLUMN IF EXISTS pact_webhook_id;
--   ALTER TABLE apiome.push_webhook_delivery_attempts DROP COLUMN IF EXISTS execution_log;
--   DROP TABLE IF EXISTS apiome.pact_webhook;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- 1. pact_webhook
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pact_webhook (
    -- The webhook's `uuid` in the broker API. A client may choose it (`PUT …/webhooks/{uuid}`).
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    description TEXT
        CONSTRAINT pact_webhook_description_check
            CHECK (description IS NULL OR length(description) <= 1000),

    -- NULL means "any": a webhook with neither fires for every pact of the workspace.
    consumer_id UUID,
    provider_id UUID,

    enabled BOOLEAN NOT NULL DEFAULT TRUE,

    events TEXT[] NOT NULL
        CONSTRAINT pact_webhook_events_check
            CHECK (cardinality(events) >= 1
                   AND events <@ ARRAY[
                       'contract_published',
                       'contract_content_changed',
                       'contract_requiring_verification_published',
                       'provider_verification_published',
                       'provider_verification_succeeded',
                       'provider_verification_failed',
                       'consumer_version_branch_created'
                   ]::text[]),

    -- `http`: the request as given. `github_repository_dispatch`: the request was built from
    -- `target_config` (repository, event type, client payload); the token is sealed.
    target_kind VARCHAR(40) NOT NULL DEFAULT 'http'
        CONSTRAINT pact_webhook_target_kind_check
            CHECK (target_kind IN ('http', 'github_repository_dispatch')),
    target_config JSONB
        CONSTRAINT pact_webhook_target_config_check
            CHECK (target_config IS NULL OR jsonb_typeof(target_config) = 'object'),

    request_method VARCHAR(8) NOT NULL
        CONSTRAINT pact_webhook_method_check CHECK (request_method IN ('POST', 'PUT', 'PATCH')),
    request_url TEXT NOT NULL
        CONSTRAINT pact_webhook_url_check
            CHECK (request_url ~* '^https?://[^[:space:]]+$' AND length(request_url) <= 2048),
    -- Header values that are not secret. Secret ones are sealed and named in `secret_fields`.
    request_headers JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT pact_webhook_headers_object_check CHECK (jsonb_typeof(request_headers) = 'object'),
    -- The body template: a JSON value (sent as JSON) or a JSON string (sent as text). NULL: no body.
    request_body JSONB,
    request_username TEXT
        CONSTRAINT pact_webhook_username_check
            CHECK (request_username IS NULL OR length(request_username) <= 256),

    secret_ciphertext BYTEA,
    key_version INTEGER,
    -- What is sealed: `password`, `signingSecret`, `header:<Name>`.
    secret_fields TEXT[] NOT NULL DEFAULT ARRAY[]::text[],

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pact_webhook_sealed_together_check
        CHECK ((secret_ciphertext IS NULL) = (key_version IS NULL)),
    CONSTRAINT pact_webhook_secret_fields_check
        CHECK ((cardinality(secret_fields) = 0) = (secret_ciphertext IS NULL)),
    -- The target of pact_triggered_webhook's composite reference.
    CONSTRAINT pact_webhook_id_tenant_key UNIQUE (id, tenant_id),
    CONSTRAINT pact_webhook_consumer_fk
        FOREIGN KEY (consumer_id, tenant_id)
        REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT pact_webhook_provider_fk
        FOREIGN KEY (provider_id, tenant_id)
        REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE
);

-- "The workspace's webhooks", and the ones to fire for an event.
CREATE INDEX IF NOT EXISTS idx_pact_webhook_tenant
    ON pact_webhook (tenant_id, created_at);
-- The referential checks of the two pacticipant references.
CREATE INDEX IF NOT EXISTS idx_pact_webhook_consumer
    ON pact_webhook (consumer_id, tenant_id) WHERE consumer_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_pact_webhook_provider
    ON pact_webhook (provider_id, tenant_id) WHERE provider_id IS NOT NULL;

COMMENT ON TABLE pact_webhook IS
    'A webhook fired on pact and verification events, in the Pact Broker''s shape (PFX-1.9, #6922)';
COMMENT ON COLUMN pact_webhook.consumer_id IS 'Only pacts of this consumer; NULL for any consumer';
COMMENT ON COLUMN pact_webhook.provider_id IS 'Only pacts of this provider; NULL for any provider';
COMMENT ON COLUMN pact_webhook.events IS 'The events the webhook fires on';
COMMENT ON COLUMN pact_webhook.target_kind IS 'http (the request as given) or github_repository_dispatch';
COMMENT ON COLUMN pact_webhook.target_config IS 'The GitHub target as given, without its token';
COMMENT ON COLUMN pact_webhook.request_headers IS 'Header templates that are not secret';
COMMENT ON COLUMN pact_webhook.request_body IS 'Body template: a JSON value, or a JSON string for a text body';
COMMENT ON COLUMN pact_webhook.secret_ciphertext IS
    'Envelope-sealed {password, signingSecret, headers}; never stored in the clear (app.pact_webhook_secrets)';
COMMENT ON COLUMN pact_webhook.key_version IS 'The master key version that sealed secret_ciphertext';
COMMENT ON COLUMN pact_webhook.secret_fields IS 'Names of the sealed values: password, signingSecret, header:<Name>';

-- ---------------------------------------------------------------------------------------------------
-- 2. The delivery queue: which webhook a delivery belongs to, and the log of each attempt
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE push_webhook_delivery_events
    ADD COLUMN IF NOT EXISTS pact_webhook_id UUID REFERENCES pact_webhook(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_push_webhook_delivery_events_pact_webhook
    ON push_webhook_delivery_events (pact_webhook_id) WHERE pact_webhook_id IS NOT NULL;

COMMENT ON COLUMN push_webhook_delivery_events.pact_webhook_id IS
    'The contract webhook this delivery is a firing of (PFX-1.9); the worker sends that webhook''s request';

ALTER TABLE push_webhook_delivery_attempts
    ADD COLUMN IF NOT EXISTS execution_log TEXT;

COMMENT ON COLUMN push_webhook_delivery_attempts.execution_log IS
    'Request and response of the attempt as text, secrets redacted; written for contract webhooks (PFX-1.9)';

-- ---------------------------------------------------------------------------------------------------
-- 3. pact_triggered_webhook — one firing
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pact_triggered_webhook (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL,
    webhook_id UUID NOT NULL,
    -- The queued delivery: status, attempts, next retry.
    delivery_event_id UUID NOT NULL
        REFERENCES push_webhook_delivery_events(id) ON DELETE CASCADE,
    consumer_id UUID NOT NULL,
    provider_id UUID NOT NULL,
    event_name TEXT NOT NULL,
    trigger_type VARCHAR(32) NOT NULL DEFAULT 'resource_creation'
        CONSTRAINT pact_triggered_webhook_trigger_type_check
            CHECK (trigger_type IN ('resource_creation', 'user')),
    -- What caused it: the pact a consumer version published, and the verification result if any.
    consumer_version_number TEXT,
    pact_version_sha CHAR(64),
    verification_number INTEGER,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pact_triggered_webhook_delivery_key UNIQUE (delivery_event_id),
    CONSTRAINT pact_triggered_webhook_webhook_fk
        FOREIGN KEY (webhook_id, tenant_id)
        REFERENCES pact_webhook (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT pact_triggered_webhook_consumer_fk
        FOREIGN KEY (consumer_id, tenant_id)
        REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT pact_triggered_webhook_provider_fk
        FOREIGN KEY (provider_id, tenant_id)
        REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE
);

-- "What fired for this pact", newest first; also the provider reference's check.
CREATE INDEX IF NOT EXISTS idx_pact_triggered_webhook_pair
    ON pact_triggered_webhook (provider_id, tenant_id, consumer_id, created_at DESC);
-- The referential checks of the webhook and consumer references.
CREATE INDEX IF NOT EXISTS idx_pact_triggered_webhook_webhook
    ON pact_triggered_webhook (webhook_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_pact_triggered_webhook_consumer
    ON pact_triggered_webhook (consumer_id, tenant_id);

COMMENT ON TABLE pact_triggered_webhook IS
    'One firing of a contract webhook for one event; its delivery is a push_webhook_delivery_events row (PFX-1.9, #6922)';
COMMENT ON COLUMN pact_triggered_webhook.delivery_event_id IS 'The queued delivery that carries status and attempts';
COMMENT ON COLUMN pact_triggered_webhook.trigger_type IS 'resource_creation (an event) or user (run by hand)';
COMMENT ON COLUMN pact_triggered_webhook.verification_number IS 'The verification result that caused it, for a verification event';
