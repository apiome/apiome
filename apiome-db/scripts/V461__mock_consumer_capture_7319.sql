-- Consumer-tagged mock capture — PFX-9.1 (#7319).
--
-- A call to the hosted mock that carries `X-Mock-Capture: <consumer>@<version>`, or arrives through
-- a private capture URL (`/{tenant}/{project}/{version}/~capture/{token}/…`), is recorded for that
-- consumer and version so a pact can later be generated from it (PFX-9.2). Untagged calls are never
-- recorded. The mock runtime never writes on the request path: tagged calls are queued in memory
-- and written in batches, one transaction per flush.
--
--   * `mock_consumer_capture_settings` — per tenant: how many days captures are kept (default 7),
--     and calls the runtime refused for the whole tenant (too many live sessions), so nothing is
--     dropped without a count and a reason;
--   * `mock_consumer_capture_link`     — private capture URLs. Only the token's SHA-256 digest and
--     its visible prefix are stored; the token itself is shown once, when the link is created;
--   * `mock_consumer_capture_session`  — one row per (version, consumer, consumer version): the
--     calls recorded for it, and how many were refused and why;
--   * `mock_consumer_capture_call`     — one recorded call: method, path, the spec's path template,
--     status, where the answer came from (spec, scenario, session, chaos, …), and the request and
--     response as stored after the mock's redaction rules ran.
--
-- Rules kept by the database:
--
--   1. **Nothing crosses a tenant.** Every row carries `tenant_id` and goes with the tenant; calls
--      and sessions go with their version.
--   2. **Captures expire.** Every session and call has `expires_at`, set from the tenant's retention
--      when it is written; the mock runtime deletes expired rows in batches and every read filters
--      them out, so an expired capture is never shown even before it is swept.
--   3. **Known origins only.** `origin` is one of the values the runtime classifies a response as.
--
-- Online: four new tables and their indexes.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.mock_consumer_capture_call;
--   DROP TABLE IF EXISTS apiome.mock_consumer_capture_session;
--   DROP TABLE IF EXISTS apiome.mock_consumer_capture_link;
--   DROP TABLE IF EXISTS apiome.mock_consumer_capture_settings;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS mock_consumer_capture_settings (
    tenant_id UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,

    retention_days INTEGER NOT NULL DEFAULT 7
        CONSTRAINT mock_consumer_capture_settings_retention_check
            CHECK (retention_days BETWEEN 1 AND 30),

    refused_calls BIGINT NOT NULL DEFAULT 0
        CONSTRAINT mock_consumer_capture_settings_refused_check CHECK (refused_calls >= 0),
    last_refused_reason TEXT,
    last_refused_at TIMESTAMP WITH TIME ZONE,

    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by_label TEXT,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mock_consumer_capture_settings_updated_by
    ON mock_consumer_capture_settings (updated_by) WHERE updated_by IS NOT NULL;

COMMENT ON TABLE mock_consumer_capture_settings IS
    'Per tenant: how long consumer-tagged mock captures are kept (PFX-9.1, #7319); no row = 7 days';
COMMENT ON COLUMN mock_consumer_capture_settings.retention_days IS 'Days a capture is kept after it is recorded (1-30)';
COMMENT ON COLUMN mock_consumer_capture_settings.refused_calls IS
    'Tagged calls refused for the whole tenant (no session could be opened), counted rather than dropped';

CREATE TABLE IF NOT EXISTS mock_consumer_capture_link (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,

    consumer TEXT NOT NULL
        CONSTRAINT mock_consumer_capture_link_consumer_check CHECK (length(consumer) BETWEEN 1 AND 200),
    consumer_version TEXT NOT NULL
        CONSTRAINT mock_consumer_capture_link_version_check CHECK (length(consumer_version) BETWEEN 1 AND 200),

    -- SHA-256 of the token, hex. The token is never stored.
    token_hash TEXT NOT NULL
        CONSTRAINT mock_consumer_capture_link_token_hash_check CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    token_prefix TEXT NOT NULL,

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_by_label TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,

    CONSTRAINT mock_consumer_capture_link_token_hash_key UNIQUE (token_hash)
);

CREATE INDEX IF NOT EXISTS idx_mock_consumer_capture_link_tenant
    ON mock_consumer_capture_link (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mock_consumer_capture_link_version
    ON mock_consumer_capture_link (version_id);
CREATE INDEX IF NOT EXISTS idx_mock_consumer_capture_link_created_by
    ON mock_consumer_capture_link (created_by) WHERE created_by IS NOT NULL;

COMMENT ON TABLE mock_consumer_capture_link IS
    'Private capture URLs: calls through one are recorded for its consumer and version (PFX-9.1, #7319)';
COMMENT ON COLUMN mock_consumer_capture_link.token_hash IS 'SHA-256 (hex) of the URL token; the token is shown once and never stored';

CREATE TABLE IF NOT EXISTS mock_consumer_capture_session (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    -- Denormalised for reading: the slugs the calls were made under.
    project_slug TEXT NOT NULL,
    version_label TEXT NOT NULL,

    consumer TEXT NOT NULL
        CONSTRAINT mock_consumer_capture_session_consumer_check CHECK (length(consumer) BETWEEN 1 AND 200),
    consumer_version TEXT NOT NULL
        CONSTRAINT mock_consumer_capture_session_version_check CHECK (length(consumer_version) BETWEEN 1 AND 200),

    first_call_at TIMESTAMP WITH TIME ZONE NOT NULL,
    last_call_at TIMESTAMP WITH TIME ZONE NOT NULL,
    call_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT mock_consumer_capture_session_call_count_check CHECK (call_count >= 0),
    -- Calls that reached the writer but were not stored, by reason: {"session-full": 3, ...}.
    refused_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT mock_consumer_capture_session_refused_count_check CHECK (refused_count >= 0),
    refused JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT mock_consumer_capture_session_refused_object_check CHECK (jsonb_typeof(refused) = 'object'),

    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,

    CONSTRAINT mock_consumer_capture_session_key UNIQUE (version_id, consumer, consumer_version)
);

CREATE INDEX IF NOT EXISTS idx_mock_consumer_capture_session_tenant
    ON mock_consumer_capture_session (tenant_id, last_call_at DESC);
CREATE INDEX IF NOT EXISTS idx_mock_consumer_capture_session_expires
    ON mock_consumer_capture_session (expires_at);

COMMENT ON TABLE mock_consumer_capture_session IS
    'Calls to a hosted mock recorded for one consumer and version (PFX-9.1, #7319)';
COMMENT ON COLUMN mock_consumer_capture_session.refused IS 'Calls not stored, counted by reason';

CREATE TABLE IF NOT EXISTS mock_consumer_capture_call (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES mock_consumer_capture_session(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    captured_at TIMESTAMP WITH TIME ZONE NOT NULL,
    via VARCHAR(8) NOT NULL
        CONSTRAINT mock_consumer_capture_call_via_check CHECK (via IN ('header', 'url')),
    link_id UUID REFERENCES mock_consumer_capture_link(id) ON DELETE SET NULL,
    api_key_id UUID REFERENCES api_keys(id) ON DELETE SET NULL,

    method VARCHAR(16) NOT NULL,
    path TEXT NOT NULL,
    path_template TEXT,
    operation_key TEXT,
    status INTEGER NOT NULL
        CONSTRAINT mock_consumer_capture_call_status_check CHECK (status >= 100 AND status < 600),

    origin VARCHAR(16) NOT NULL
        CONSTRAINT mock_consumer_capture_call_origin_check
            CHECK (origin IN ('spec', 'scenario', 'session', 'chaos', 'forced', 'off-spec', 'rejected')),
    origin_detail TEXT,
    scenario TEXT,
    -- A digest of the X-Mock-Session token: groups a stateful conversation without storing the token.
    mock_session TEXT,

    request JSONB NOT NULL,
    response JSONB NOT NULL,
    redactions JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT mock_consumer_capture_call_redactions_array_check CHECK (jsonb_typeof(redactions) = 'array'),
    redaction_count INTEGER NOT NULL DEFAULT 0,

    expires_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mock_consumer_capture_call_session
    ON mock_consumer_capture_call (session_id, id);
CREATE INDEX IF NOT EXISTS idx_mock_consumer_capture_call_tenant
    ON mock_consumer_capture_call (tenant_id);
CREATE INDEX IF NOT EXISTS idx_mock_consumer_capture_call_expires
    ON mock_consumer_capture_call (expires_at);
CREATE INDEX IF NOT EXISTS idx_mock_consumer_capture_call_link
    ON mock_consumer_capture_call (link_id) WHERE link_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_mock_consumer_capture_call_api_key
    ON mock_consumer_capture_call (api_key_id) WHERE api_key_id IS NOT NULL;

COMMENT ON TABLE mock_consumer_capture_call IS
    'One mock call recorded for a consumer, stored after redaction (PFX-9.1, #7319)';
COMMENT ON COLUMN mock_consumer_capture_call.origin IS
    'Where the answer came from: spec, scenario, session, chaos, forced (Prefer: code=), off-spec, rejected';
COMMENT ON COLUMN mock_consumer_capture_call.mock_session IS 'SHA-256 prefix of the X-Mock-Session token, never the token';
