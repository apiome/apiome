-- Usage event contract and index tables — RDG-1.1 (#5759).
--
-- Nothing in Apiome could answer "how often is this operation called, by whom, with what outcome?".
-- This migration adds the **usage index** every later runtime-drift reader (usage-weighted diff
-- verdicts, drift reports, adoption charts) reads, built as counters — never as a request log — so
-- it can never become the database full of bearer tokens that the proxy-capture design (PMR-2.4)
-- was built to avoid. (The roadmap reserved V274; that number shipped long ago, so this is V290.)
--
--   usage_source            one traffic source attached to a project (OTLP, HAR, access log, ...)
--   usage_ingest_batch      write-once ledger: what happened to every event of every batch
--   usage_hourly            per-operation counters by UTC hour (the raw grain)
--   usage_daily             the same grain by UTC day, rolled up from usage_hourly
--   usage_field_daily       how often a JSON Pointer was present in a request / response, per day
--   usage_unmatched_daily   traffic on paths no published revision declares, per day
--   usage_sample            opt-in, redacted, size-capped exchanges (never by default)
--   usage_rollup_days       which UTC days have been rolled up, and which are final
--   licenses.seats keys     usage_hourly_retention_days, usage_rollup_retention_days,
--                           usage_events_per_day
--
-- and the functions the REST usage sweep (`app.usage_sweep`, also `python -m app.usage_sweep`)
-- calls on a schedule: `rollup_usage_days` and `purge_usage`. Rows are written by the RDG-1.2
-- ingest pipeline; nothing writes them yet.
--
-- Seven rules shape the schema (they copy V271, AGX-3.3, rather than invent a new scheme):
--
--   1. **Counters, not logs.** Every table carries `tenant_id` and **no column able to hold a header
--      value, a body, a query value or a source IP**: no `inet`/`cidr` column, no free-text column,
--      every text column is a bounded, pattern-checked identifier (an operation pointer, a path
--      template, a method, an environment name, a field pointer, a digest). The one exception is
--      the opt-in `usage_sample.exchange`, which holds an exchange already reduced by the PMR-2.4
--      `app.mock_capture` record reducer. `tests/test_usage_index_db.py` pins every column.
--
--   2. **Operations are classifier pointers.** `operation_key` is `/paths/<escaped template>/<method>`
--      — the pointer `app.consumer_surface.operation_pointer` and `app.change_taxonomy_enum` emit —
--      so usage joins consumer contracts, the blast radius and diff verdicts without translation.
--
--   3. **Latency is an explicit-bound histogram.** `latency_buckets[i]` counts calls whose latency
--      was at most `usage_latency_bounds()[i]` ms (and above the previous bound); the last bucket
--      counts everything above the largest bound. The buckets always sum to `calls`.
--
--   4. **Bodies are opt-in, sampled and bounded.** A source samples bodies only while
--      `body_sample_rate > 0` (at most 5%) *and* `body_sample_until` is in the future; the window may
--      be at most 7 days ahead when it is set (trigger), each sample is capped at 16 KiB (CHECK), and
--      samples are purged after 7 days whatever the tier.
--
--   5. **Rollups match what they were built from.** `rollup_usage_days` recomputes each open UTC day
--      of `usage_daily` from `usage_hourly` (idempotent upsert) and marks a day *final* once it ended
--      more than a grace period ago. A final day is never recomputed, and a trigger refuses new
--      hourly counts on a final day, so the ingest pipeline (RDG-1.2) must ledger such late events as
--      rejected instead of silently drifting from the rollup.
--
--   6. **Pruning never touches rollups.** `purge_usage` deletes hourly rows only once they are past
--      the tenant's tier retention **and** their day is final, so every pruned row was already
--      counted in `usage_daily`. Daily tables and the ledger have their own, longer, retention.
--
--   7. **Retention and caps follow the license tier.** `licenses.seats` gains
--      `usage_hourly_retention_days` (Free 7 / Paid 30 / Sponsor 90),
--      `usage_rollup_retention_days` (Free 90 / Paid 395 / Sponsor 730) — a negative value keeps rows
--      forever, a missing / non-numeric key gets the Free value — and `usage_events_per_day`
--      (Free 100,000 / Paid 10,000,000 / Sponsor 100,000,000; zero or negative = unlimited), the cap
--      RDG-1.2 enforces at ingest.
--
-- History outlives its references: `version_record_id`, `consumer_binding_id` (RDG-1.8 adds the
-- binding table) and the ledger's `api_key_id` carry no foreign key, so deleting a version, a binding
-- or a key never rewrites what was observed. Deleting the tenant, the project or the source removes
-- its rows (a source is normally switched off with `enabled = false` instead).
--
-- Rollback notes:
--   DROP FUNCTION IF EXISTS apiome.purge_usage(TIMESTAMPTZ, INTEGER);
--   DROP FUNCTION IF EXISTS apiome.usage_retention(TIMESTAMPTZ);
--   DROP FUNCTION IF EXISTS apiome.rollup_usage_days(TIMESTAMPTZ, INTERVAL);
--   DROP FUNCTION IF EXISTS apiome.rollup_usage_day(DATE, TIMESTAMPTZ);
--   DROP TABLE IF EXISTS apiome.usage_sample;
--   DROP TABLE IF EXISTS apiome.usage_unmatched_daily;
--   DROP TABLE IF EXISTS apiome.usage_field_daily;
--   DROP TABLE IF EXISTS apiome.usage_daily;
--   DROP TABLE IF EXISTS apiome.usage_hourly;
--   DROP TABLE IF EXISTS apiome.usage_rollup_days;
--   DROP TABLE IF EXISTS apiome.usage_ingest_batch;
--   DROP TABLE IF EXISTS apiome.usage_source;
--   DROP FUNCTION IF EXISTS apiome.usage_hourly_open_day();
--   DROP FUNCTION IF EXISTS apiome.usage_source_body_sample_window();
--   DROP FUNCTION IF EXISTS apiome.usage_buckets_valid(BIGINT[], BIGINT);
--   DROP FUNCTION IF EXISTS apiome.usage_latency_bounds();
--   UPDATE apiome.licenses SET seats = seats - 'usage_hourly_retention_days'
--     - 'usage_rollup_retention_days' - 'usage_events_per_day';

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- Shared helpers.
-- ---------------------------------------------------------------------------------------------------

-- Rule 3: the histogram's upper bounds in milliseconds (`app.usage_events.LATENCY_BOUNDS_MS` mirrors
-- them; a test keeps the two equal). Twelve buckets: one per bound plus the overflow bucket.
CREATE OR REPLACE FUNCTION usage_latency_bounds()
RETURNS INTEGER[] AS $$
    SELECT ARRAY[5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]::INTEGER[];
$$ LANGUAGE sql IMMUTABLE PARALLEL SAFE;

COMMENT ON FUNCTION usage_latency_bounds() IS
    'RDG-1.1 (#5759): upper bounds (ms) of the usage latency histogram. latency_buckets has one '
    'more element than this: the last counts calls slower than the largest bound.';

-- A histogram is valid when it has exactly one bucket per bound plus the overflow, no bucket is
-- negative and the buckets sum to the row's calls.
CREATE OR REPLACE FUNCTION usage_buckets_valid(p_buckets BIGINT[], p_calls BIGINT)
RETURNS BOOLEAN AS $$
    SELECT p_buckets IS NOT NULL
       AND array_ndims(p_buckets) = 1
       AND cardinality(p_buckets) = cardinality(apiome.usage_latency_bounds()) + 1
       AND NOT EXISTS (SELECT 1 FROM unnest(p_buckets) b WHERE b IS NULL OR b < 0)
       AND (SELECT sum(b) FROM unnest(p_buckets) b) = p_calls;
$$ LANGUAGE sql IMMUTABLE PARALLEL SAFE;

COMMENT ON FUNCTION usage_buckets_valid(BIGINT[], BIGINT) IS
    'RDG-1.1 (#5759): CHECK helper — a latency histogram has one bucket per usage_latency_bounds() '
    'entry plus the overflow, no negative bucket, and sums to calls.';

-- ---------------------------------------------------------------------------------------------------
-- Sources.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usage_source (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    kind VARCHAR(16) NOT NULL
        CONSTRAINT usage_source_kind_ck CHECK (
            kind IN ('otlp', 'har', 'access_log', 'mock', 'agent', 'sdk_beacon')
        ),
    -- The environment events default to. `mock` is reserved for the mock runtime's own source.
    environment VARCHAR(32) NOT NULL DEFAULT 'prod'
        CONSTRAINT usage_source_environment_ck CHECK (environment ~ '^[a-z][a-z0-9_-]{0,31}$'),
    CONSTRAINT usage_source_mock_environment_ck CHECK (environment <> 'mock' OR kind = 'mock'),

    -- Head-sampling rate in (0, 1]; counts are scaled by its inverse at ingest.
    sampling_rate NUMERIC(7, 6) NOT NULL DEFAULT 1
        CONSTRAINT usage_source_sampling_rate_ck CHECK (sampling_rate > 0 AND sampling_rate <= 1),
    -- Whether the source reports field presence (usage_field_daily).
    field_capture BOOLEAN NOT NULL DEFAULT false,

    -- Rule 4: the opt-in body sample.
    body_sample_rate NUMERIC(5, 4) NOT NULL DEFAULT 0,
    body_sample_until TIMESTAMPTZ,
    CONSTRAINT usage_source_body_sample_ck CHECK (
        body_sample_rate >= 0 AND body_sample_rate <= 0.05
        AND (body_sample_rate = 0 OR body_sample_until IS NOT NULL)
    ),

    enabled BOOLEAN NOT NULL DEFAULT true,
    last_received_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_usage_source_project ON usage_source (tenant_id, project_id);

COMMENT ON TABLE usage_source IS
    'RDG-1.1 (#5759): one traffic source feeding a project''s usage index — an OTLP receiver, a HAR '
    'upload, a gateway access log, the mock or agent runtime, or the SDK beacon.';
COMMENT ON COLUMN usage_source.environment IS
    'Default environment of the source''s events (prod by default). mock is reserved for kind=mock.';
COMMENT ON COLUMN usage_source.sampling_rate IS
    'Fraction (0..1] of events kept by head sampling; ingest scales counts by its inverse.';
COMMENT ON COLUMN usage_source.body_sample_rate IS
    'Opt-in fraction (0..0.05) of exchanges kept as redacted usage_sample rows. 0 (the default) keeps '
    'none.';
COMMENT ON COLUMN usage_source.body_sample_until IS
    'Body sampling stops at this time. Required while body_sample_rate > 0; at most 7 days ahead when '
    'written.';

-- A CHECK cannot read the clock, so the 7-day bound on the window is a trigger. It applies when the
-- window is written, so an existing window is never invalidated by time passing (as V271).
CREATE OR REPLACE FUNCTION usage_source_body_sample_window()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.body_sample_rate > 0
       AND NEW.body_sample_until IS DISTINCT FROM
           (CASE WHEN TG_OP = 'UPDATE' THEN OLD.body_sample_until END)
       AND NEW.body_sample_until > CURRENT_TIMESTAMP + INTERVAL '7 days' THEN
        RAISE EXCEPTION 'usage_source.body_sample_until may be at most 7 days ahead'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_usage_source_body_sample_window ON usage_source;
CREATE TRIGGER trigger_usage_source_body_sample_window
    BEFORE INSERT OR UPDATE OF body_sample_rate, body_sample_until ON usage_source
    FOR EACH ROW
    EXECUTE FUNCTION usage_source_body_sample_window();

-- ---------------------------------------------------------------------------------------------------
-- The ingest ledger: one write-once row per batch.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usage_ingest_batch (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES usage_source(id) ON DELETE CASCADE,
    -- The workspace API key that sent the batch. No FK: the ledger outlives the key.
    api_key_id UUID,

    received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    received_day DATE GENERATED ALWAYS AS ((received_at AT TIME ZONE 'UTC')::date) STORED,

    -- What happened to every event: each one is accepted, sampled out, unmatched or rejected.
    received INTEGER NOT NULL CONSTRAINT usage_ingest_batch_received_ck CHECK (received >= 0),
    accepted INTEGER NOT NULL CONSTRAINT usage_ingest_batch_accepted_ck CHECK (accepted >= 0),
    sampled_out INTEGER NOT NULL CONSTRAINT usage_ingest_batch_sampled_out_ck CHECK (sampled_out >= 0),
    unmatched INTEGER NOT NULL CONSTRAINT usage_ingest_batch_unmatched_ck CHECK (unmatched >= 0),
    rejected INTEGER NOT NULL CONSTRAINT usage_ingest_batch_rejected_ck CHECK (rejected >= 0),
    CONSTRAINT usage_ingest_batch_total_ck CHECK (
        received = accepted + sampled_out + unmatched + rejected
    ),
    -- How many strings the edge scrub rewrote (a count, never what was found).
    scrub_findings INTEGER NOT NULL DEFAULT 0
        CONSTRAINT usage_ingest_batch_scrub_findings_ck CHECK (scrub_findings >= 0),
    -- SHA-256 (hex) of the batch as received, for replay detection.
    batch_digest CHAR(64) NOT NULL
        CONSTRAINT usage_ingest_batch_digest_ck CHECK (batch_digest ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_usage_ingest_batch_source_time
    ON usage_ingest_batch (source_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_ingest_batch_tenant_day
    ON usage_ingest_batch (tenant_id, received_day);

COMMENT ON TABLE usage_ingest_batch IS
    'RDG-1.1 (#5759): write-once ledger of usage ingest batches — per batch, how many events were '
    'received, accepted, sampled out, unmatched or rejected, the scrub-finding count and the batch '
    'digest. Never an event.';

DROP TRIGGER IF EXISTS trigger_usage_ingest_batch_immutable ON usage_ingest_batch;
CREATE TRIGGER trigger_usage_ingest_batch_immutable
    BEFORE UPDATE ON usage_ingest_batch
    FOR EACH ROW
    EXECUTE FUNCTION mcp_forbid_row_mutation();

-- ---------------------------------------------------------------------------------------------------
-- Rule 5: which days are rolled up, and which are final.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usage_rollup_days (
    day DATE PRIMARY KEY,
    rolled_up_at TIMESTAMPTZ NOT NULL,
    finalized_at TIMESTAMPTZ
);

COMMENT ON TABLE usage_rollup_days IS
    'RDG-1.1 (#5759): UTC days rolled up from usage_hourly into usage_daily. A finalized day is never '
    'recomputed, takes no new hourly counts, and only its hourly rows may be pruned.';

-- ---------------------------------------------------------------------------------------------------
-- Counters by UTC hour.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usage_hourly (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES usage_source(id) ON DELETE CASCADE,
    environment VARCHAR(32) NOT NULL
        CONSTRAINT usage_hourly_environment_ck CHECK (environment ~ '^[a-z][a-z0-9_-]{0,31}$'),
    -- The start of the UTC hour.
    hour TIMESTAMPTZ NOT NULL
        CONSTRAINT usage_hourly_hour_ck CHECK (extract(epoch FROM hour)::bigint % 3600 = 0),
    day DATE GENERATED ALWAYS AS ((hour AT TIME ZONE 'UTC')::date) STORED,

    -- The published revision the call matched, when known. No FK (history outlives the version).
    version_record_id UUID,
    -- Rule 2: /paths/<escaped template>/<method>.
    operation_key VARCHAR(1024) NOT NULL
        CONSTRAINT usage_hourly_operation_key_ck CHECK (operation_key ~ '^/paths/[^?#[:space:]]+/[a-z]+$'),
    status_code SMALLINT NOT NULL
        CONSTRAINT usage_hourly_status_code_ck CHECK (status_code BETWEEN 100 AND 599),
    -- The RDG-1.8 consumer binding the call was attributed to. No FK (history outlives the binding).
    consumer_binding_id UUID,

    calls BIGINT NOT NULL CONSTRAINT usage_hourly_calls_ck CHECK (calls >= 0),
    -- Calls that failed (status 4xx or 5xx).
    errors BIGINT GENERATED ALWAYS AS (CASE WHEN status_code >= 400 THEN calls ELSE 0 END) STORED,

    -- Rule 3.
    latency_buckets BIGINT[] NOT NULL,
    latency_sum_ms BIGINT NOT NULL CONSTRAINT usage_hourly_latency_sum_ck CHECK (latency_sum_ms >= 0),
    latency_max_ms INTEGER NOT NULL CONSTRAINT usage_hourly_latency_max_ck CHECK (latency_max_ms >= 0),
    CONSTRAINT usage_hourly_latency_buckets_ck CHECK (apiome.usage_buckets_valid(latency_buckets, calls)),

    -- Posture bits: how many calls carried a credential (and for how many it was unknown), a version
    -- marker (and unknown), and were made over HTTPS.
    auth_present_calls BIGINT NOT NULL DEFAULT 0,
    auth_unknown_calls BIGINT NOT NULL DEFAULT 0,
    versioned_calls BIGINT NOT NULL DEFAULT 0,
    version_unknown_calls BIGINT NOT NULL DEFAULT 0,
    https_calls BIGINT NOT NULL DEFAULT 0,
    CONSTRAINT usage_hourly_posture_ck CHECK (
        auth_present_calls >= 0 AND auth_unknown_calls >= 0
        AND auth_present_calls + auth_unknown_calls <= calls
        AND versioned_calls >= 0 AND version_unknown_calls >= 0
        AND versioned_calls + version_unknown_calls <= calls
        AND https_calls >= 0 AND https_calls <= calls
    ),

    request_bytes BIGINT NOT NULL DEFAULT 0
        CONSTRAINT usage_hourly_request_bytes_ck CHECK (request_bytes >= 0),
    response_bytes BIGINT NOT NULL DEFAULT 0
        CONSTRAINT usage_hourly_response_bytes_ck CHECK (response_bytes >= 0),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT usage_hourly_grain_uq UNIQUE NULLS NOT DISTINCT (
        tenant_id, project_id, source_id, environment, hour, version_record_id, operation_key,
        status_code, consumer_binding_id
    )
);

CREATE INDEX IF NOT EXISTS idx_usage_hourly_day ON usage_hourly (day);
CREATE INDEX IF NOT EXISTS idx_usage_hourly_project_hour
    ON usage_hourly (tenant_id, project_id, hour DESC);

COMMENT ON TABLE usage_hourly IS
    'RDG-1.1 (#5759): per-operation usage counters by UTC hour — calls, errors, a latency histogram, '
    'posture bits and bytes per (source, environment, version, operation, status, consumer). The raw '
    'grain; rolled up into usage_daily and pruned per tier once its day is final.';
COMMENT ON COLUMN usage_hourly.operation_key IS
    'The operation as the classifier''s pointer: /paths/<escaped template>/<method>.';
COMMENT ON COLUMN usage_hourly.latency_buckets IS
    'Calls per latency bucket: element i counts latencies <= usage_latency_bounds()[i] ms (and above '
    'the previous bound); the last element counts latencies above the largest bound.';
COMMENT ON COLUMN usage_hourly.auth_present_calls IS
    'Calls that carried a credential header (presence only, never the value).';
COMMENT ON COLUMN usage_hourly.auth_unknown_calls IS
    'Calls whose source could not say whether a credential was present.';
COMMENT ON COLUMN usage_hourly.versioned_calls IS
    'Calls that carried a version marker (path segment, header or user-agent marker).';

-- Rule 5: a final day takes no new counts, so its rollup always matches its hourly rows.
CREATE OR REPLACE FUNCTION usage_hourly_open_day()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM apiome.usage_rollup_days
        WHERE day = (NEW.hour AT TIME ZONE 'UTC')::date AND finalized_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'usage day % is finalized and takes no new counts',
            (NEW.hour AT TIME ZONE 'UTC')::date
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_usage_hourly_open_day ON usage_hourly;
CREATE TRIGGER trigger_usage_hourly_open_day
    BEFORE INSERT OR UPDATE ON usage_hourly
    FOR EACH ROW
    EXECUTE FUNCTION usage_hourly_open_day();

-- ---------------------------------------------------------------------------------------------------
-- Counters by UTC day (rolled up from usage_hourly).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usage_daily (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES usage_source(id) ON DELETE CASCADE,
    environment VARCHAR(32) NOT NULL
        CONSTRAINT usage_daily_environment_ck CHECK (environment ~ '^[a-z][a-z0-9_-]{0,31}$'),
    day DATE NOT NULL,

    version_record_id UUID,
    operation_key VARCHAR(1024) NOT NULL
        CONSTRAINT usage_daily_operation_key_ck CHECK (operation_key ~ '^/paths/[^?#[:space:]]+/[a-z]+$'),
    status_code SMALLINT NOT NULL
        CONSTRAINT usage_daily_status_code_ck CHECK (status_code BETWEEN 100 AND 599),
    consumer_binding_id UUID,

    calls BIGINT NOT NULL CONSTRAINT usage_daily_calls_ck CHECK (calls >= 0),
    errors BIGINT GENERATED ALWAYS AS (CASE WHEN status_code >= 400 THEN calls ELSE 0 END) STORED,

    latency_buckets BIGINT[] NOT NULL,
    latency_sum_ms BIGINT NOT NULL CONSTRAINT usage_daily_latency_sum_ck CHECK (latency_sum_ms >= 0),
    latency_max_ms INTEGER NOT NULL CONSTRAINT usage_daily_latency_max_ck CHECK (latency_max_ms >= 0),
    CONSTRAINT usage_daily_latency_buckets_ck CHECK (apiome.usage_buckets_valid(latency_buckets, calls)),

    auth_present_calls BIGINT NOT NULL,
    auth_unknown_calls BIGINT NOT NULL,
    versioned_calls BIGINT NOT NULL,
    version_unknown_calls BIGINT NOT NULL,
    https_calls BIGINT NOT NULL,
    CONSTRAINT usage_daily_posture_ck CHECK (
        auth_present_calls >= 0 AND auth_unknown_calls >= 0
        AND auth_present_calls + auth_unknown_calls <= calls
        AND versioned_calls >= 0 AND version_unknown_calls >= 0
        AND versioned_calls + version_unknown_calls <= calls
        AND https_calls >= 0 AND https_calls <= calls
    ),

    request_bytes BIGINT NOT NULL CONSTRAINT usage_daily_request_bytes_ck CHECK (request_bytes >= 0),
    response_bytes BIGINT NOT NULL CONSTRAINT usage_daily_response_bytes_ck CHECK (response_bytes >= 0),

    computed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT usage_daily_grain_uq UNIQUE NULLS NOT DISTINCT (
        tenant_id, project_id, source_id, environment, day, version_record_id, operation_key,
        status_code, consumer_binding_id
    )
);

CREATE INDEX IF NOT EXISTS idx_usage_daily_project_day ON usage_daily (tenant_id, project_id, day DESC);
CREATE INDEX IF NOT EXISTS idx_usage_daily_day ON usage_daily (day);

COMMENT ON TABLE usage_daily IS
    'RDG-1.1 (#5759): usage_hourly rolled up by UTC day (same grain, same counters). What the diff, '
    'gate, drift and adoption readers query; retained longer than the hourly rows.';

-- ---------------------------------------------------------------------------------------------------
-- Field presence by UTC day.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usage_field_daily (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES usage_source(id) ON DELETE CASCADE,
    environment VARCHAR(32) NOT NULL
        CONSTRAINT usage_field_daily_environment_ck CHECK (environment ~ '^[a-z][a-z0-9_-]{0,31}$'),
    day DATE NOT NULL,

    operation_key VARCHAR(1024) NOT NULL
        CONSTRAINT usage_field_daily_operation_key_ck
        CHECK (operation_key ~ '^/paths/[^?#[:space:]]+/[a-z]+$'),
    direction VARCHAR(8) NOT NULL
        CONSTRAINT usage_field_daily_direction_ck CHECK (direction IN ('request', 'response')),
    status_code SMALLINT NOT NULL
        CONSTRAINT usage_field_daily_status_code_ck CHECK (status_code BETWEEN 100 AND 599),
    -- A JSON Pointer to a field (names only — the value was discarded at the edge).
    pointer VARCHAR(512) NOT NULL
        CONSTRAINT usage_field_daily_pointer_ck CHECK (pointer ~ '^(/([^~[:space:]]|~[01])*)+$'),

    -- Of the calls whose bodies were inspected, how many carried the field.
    calls_with_field BIGINT NOT NULL,
    calls_sampled BIGINT NOT NULL,
    CONSTRAINT usage_field_daily_calls_ck CHECK (
        calls_with_field >= 0 AND calls_sampled >= calls_with_field
    ),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (tenant_id, project_id, source_id, environment, day, operation_key, direction,
                 status_code, pointer)
);

CREATE INDEX IF NOT EXISTS idx_usage_field_daily_day ON usage_field_daily (day);

COMMENT ON TABLE usage_field_daily IS
    'RDG-1.1 (#5759): how often a field (JSON Pointer) was present in an operation''s request or '
    'response, per UTC day — computed at the edge from a body the edge then discards. Never a value.';

-- ---------------------------------------------------------------------------------------------------
-- Unmatched traffic by UTC day.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usage_unmatched_daily (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES usage_source(id) ON DELETE CASCADE,
    environment VARCHAR(32) NOT NULL
        CONSTRAINT usage_unmatched_daily_environment_ck
        CHECK (environment ~ '^[a-z][a-z0-9_-]{0,31}$'),
    day DATE NOT NULL,

    method VARCHAR(16) NOT NULL
        CONSTRAINT usage_unmatched_daily_method_ck CHECK (method ~ '^[A-Z]{1,16}$'),
    -- The inferred template (`/users/{param}/orders`); a raw path never persists.
    path_template VARCHAR(1024) NOT NULL
        CONSTRAINT usage_unmatched_daily_path_template_ck CHECK (path_template ~ '^/[^?#[:space:]]*$'),

    calls BIGINT NOT NULL CONSTRAINT usage_unmatched_daily_calls_ck CHECK (calls >= 0),
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT usage_unmatched_daily_seen_ck CHECK (first_seen_at <= last_seen_at),

    -- Calls by status class.
    calls_1xx BIGINT NOT NULL DEFAULT 0,
    calls_2xx BIGINT NOT NULL DEFAULT 0,
    calls_3xx BIGINT NOT NULL DEFAULT 0,
    calls_4xx BIGINT NOT NULL DEFAULT 0,
    calls_5xx BIGINT NOT NULL DEFAULT 0,
    CONSTRAINT usage_unmatched_daily_classes_ck CHECK (
        calls_1xx >= 0 AND calls_2xx >= 0 AND calls_3xx >= 0 AND calls_4xx >= 0 AND calls_5xx >= 0
        AND calls = calls_1xx + calls_2xx + calls_3xx + calls_4xx + calls_5xx
    ),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (tenant_id, project_id, source_id, environment, day, method, path_template)
);

CREATE INDEX IF NOT EXISTS idx_usage_unmatched_daily_day ON usage_unmatched_daily (day);

COMMENT ON TABLE usage_unmatched_daily IS
    'RDG-1.1 (#5759): traffic on paths no published revision declares, by inferred template and UTC '
    'day, with first/last seen and calls per status class. The drift report''s undocumented-endpoint '
    'input.';

-- ---------------------------------------------------------------------------------------------------
-- Rule 4: opt-in redacted samples.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usage_sample (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES usage_source(id) ON DELETE CASCADE,
    environment VARCHAR(32) NOT NULL
        CONSTRAINT usage_sample_environment_ck CHECK (environment ~ '^[a-z][a-z0-9_-]{0,31}$'),
    captured_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- The matched operation, when there was one.
    operation_key VARCHAR(1024)
        CONSTRAINT usage_sample_operation_key_ck CHECK (operation_key ~ '^/paths/[^?#[:space:]]+/[a-z]+$'),
    status_code SMALLINT NOT NULL
        CONSTRAINT usage_sample_status_code_ck CHECK (status_code BETWEEN 100 AND 599),

    -- The exchange as the PMR-2.4 `app.mock_capture` record reducer leaves it (credentials removed,
    -- then re-scanned; anything still flagged is never stored). At most 16 KiB.
    exchange JSONB NOT NULL
        CONSTRAINT usage_sample_exchange_ck CHECK (
            jsonb_typeof(exchange) = 'object' AND octet_length(exchange::text) <= 16384
        )
);

CREATE INDEX IF NOT EXISTS idx_usage_sample_captured ON usage_sample (captured_at);
CREATE INDEX IF NOT EXISTS idx_usage_sample_source ON usage_sample (source_id, captured_at DESC);

COMMENT ON TABLE usage_sample IS
    'RDG-1.1 (#5759): opt-in redacted exchanges (<= 16 KiB) of a source whose body_sample window is '
    'open, reduced by the PMR-2.4 capture reducer. Purged after 7 days whatever the tier. The only '
    'usage_* column that holds exchange content.';

DROP TRIGGER IF EXISTS trigger_usage_sample_immutable ON usage_sample;
CREATE TRIGGER trigger_usage_sample_immutable
    BEFORE UPDATE ON usage_sample
    FOR EACH ROW
    EXECUTE FUNCTION mcp_forbid_row_mutation();

-- ---------------------------------------------------------------------------------------------------
-- Rule 5: rollups.
-- ---------------------------------------------------------------------------------------------------

-- One UTC day: recompute every usage_daily group from usage_hourly. A no-op on a finalized day.
CREATE OR REPLACE FUNCTION rollup_usage_day(
    p_day DATE,
    p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
)
RETURNS INTEGER AS $$
DECLARE
    v_groups INTEGER;
BEGIN
    IF EXISTS (
        SELECT 1 FROM apiome.usage_rollup_days
        WHERE day = p_day AND finalized_at IS NOT NULL
    ) THEN
        RETURN 0;
    END IF;

    INSERT INTO apiome.usage_daily AS d (
        tenant_id, project_id, source_id, environment, day, version_record_id, operation_key,
        status_code, consumer_binding_id, calls, latency_buckets, latency_sum_ms, latency_max_ms,
        auth_present_calls, auth_unknown_calls, versioned_calls, version_unknown_calls, https_calls,
        request_bytes, response_bytes, computed_at
    )
    SELECT h.tenant_id, h.project_id, h.source_id, h.environment, p_day, h.version_record_id,
           h.operation_key, h.status_code, h.consumer_binding_id,
           sum(h.calls),
           -- The element-wise sum of the hourly histograms (twelve buckets, rule 3; the CHECK on
           -- usage_daily refuses the row if usage_latency_bounds() ever grows without this list).
           ARRAY[sum(h.latency_buckets[1]), sum(h.latency_buckets[2]), sum(h.latency_buckets[3]),
                 sum(h.latency_buckets[4]), sum(h.latency_buckets[5]), sum(h.latency_buckets[6]),
                 sum(h.latency_buckets[7]), sum(h.latency_buckets[8]), sum(h.latency_buckets[9]),
                 sum(h.latency_buckets[10]), sum(h.latency_buckets[11]),
                 sum(h.latency_buckets[12])]::BIGINT[],
           sum(h.latency_sum_ms),
           max(h.latency_max_ms),
           sum(h.auth_present_calls),
           sum(h.auth_unknown_calls),
           sum(h.versioned_calls),
           sum(h.version_unknown_calls),
           sum(h.https_calls),
           sum(h.request_bytes),
           sum(h.response_bytes),
           p_now
    FROM apiome.usage_hourly h
    WHERE h.day = p_day
    GROUP BY h.tenant_id, h.project_id, h.source_id, h.environment, h.version_record_id,
             h.operation_key, h.status_code, h.consumer_binding_id
    ON CONFLICT ON CONSTRAINT usage_daily_grain_uq DO UPDATE SET
        calls = EXCLUDED.calls,
        latency_buckets = EXCLUDED.latency_buckets,
        latency_sum_ms = EXCLUDED.latency_sum_ms,
        latency_max_ms = EXCLUDED.latency_max_ms,
        auth_present_calls = EXCLUDED.auth_present_calls,
        auth_unknown_calls = EXCLUDED.auth_unknown_calls,
        versioned_calls = EXCLUDED.versioned_calls,
        version_unknown_calls = EXCLUDED.version_unknown_calls,
        https_calls = EXCLUDED.https_calls,
        request_bytes = EXCLUDED.request_bytes,
        response_bytes = EXCLUDED.response_bytes,
        computed_at = EXCLUDED.computed_at;
    GET DIAGNOSTICS v_groups = ROW_COUNT;

    INSERT INTO apiome.usage_rollup_days (day, rolled_up_at)
    VALUES (p_day, p_now)
    ON CONFLICT (day) DO UPDATE SET rolled_up_at = EXCLUDED.rolled_up_at;

    RETURN v_groups;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION rollup_usage_day(DATE, TIMESTAMPTZ) IS
    'Recompute usage_daily for one UTC day from usage_hourly (idempotent upsert). No-op on a '
    'finalized day. Returns the number of groups written (RDG-1.1, #5759).';

-- Every open day, oldest first: from the day after the newest finalized one (or the oldest hourly
-- row on a day not yet final) through today. A day is finalized once it ended more than p_grace ago.
CREATE OR REPLACE FUNCTION rollup_usage_days(
    p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    p_grace INTERVAL DEFAULT INTERVAL '6 hours'
)
RETURNS INTEGER AS $$
DECLARE
    v_today DATE := (p_now AT TIME ZONE 'UTC')::date;
    v_from DATE;
    v_day DATE;
    v_days INTEGER := 0;
BEGIN
    SELECT max(day) + 1 INTO v_from
    FROM apiome.usage_rollup_days
    WHERE finalized_at IS NOT NULL;

    -- Also reach back to any hourly day not yet finalized (e.g. the very first sweep).
    SELECT LEAST(v_from, min(h.day)) INTO v_from
    FROM apiome.usage_hourly h
    WHERE NOT EXISTS (
        SELECT 1 FROM apiome.usage_rollup_days r
        WHERE r.day = h.day AND r.finalized_at IS NOT NULL
    );

    IF v_from IS NULL THEN
        RETURN 0;
    END IF;

    v_day := v_from;
    WHILE v_day <= v_today LOOP
        PERFORM apiome.rollup_usage_day(v_day, p_now);
        -- The day ended at (v_day + 1) 00:00 UTC.
        IF ((v_day + 1)::timestamp AT TIME ZONE 'UTC') + p_grace <= p_now THEN
            UPDATE apiome.usage_rollup_days
            SET finalized_at = p_now
            WHERE day = v_day AND finalized_at IS NULL;
        END IF;
        v_days := v_days + 1;
        v_day := v_day + 1;
    END LOOP;
    RETURN v_days;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION rollup_usage_days(TIMESTAMPTZ, INTERVAL) IS
    'Roll up every open UTC day through today into usage_daily and finalize days that ended more '
    'than p_grace ago. Returns the number of days processed (RDG-1.1, #5759).';

-- ---------------------------------------------------------------------------------------------------
-- Rules 6–7: per-tier retention.
-- ---------------------------------------------------------------------------------------------------

-- Each tenant's retention cutoffs from its license tier (Free values when unlicensed or unset).
-- NULL cutoff = keep forever (a negative seats value).
CREATE OR REPLACE FUNCTION usage_retention(p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)
RETURNS TABLE (tenant_id UUID, hourly_cutoff TIMESTAMPTZ, rollup_cutoff DATE) AS $$
    WITH tiers AS (
        SELECT t.id AS tenant_id,
               CASE WHEN jsonb_typeof(l.seats -> 'usage_hourly_retention_days') = 'number'
                    THEN (l.seats ->> 'usage_hourly_retention_days')::numeric::integer
                    ELSE 7 END AS hourly_days,
               CASE WHEN jsonb_typeof(l.seats -> 'usage_rollup_retention_days') = 'number'
                    THEN (l.seats ->> 'usage_rollup_retention_days')::numeric::integer
                    ELSE 90 END AS rollup_days
        FROM apiome.tenants t
        LEFT JOIN apiome.tenant_licenses tl ON tl.tenant_id = t.id
        LEFT JOIN apiome.licenses l ON l.id = tl.license_id
    )
    SELECT tenant_id,
           CASE WHEN hourly_days < 0 THEN NULL
                ELSE p_now - GREATEST(hourly_days, 1) * INTERVAL '1 day' END,
           CASE WHEN rollup_days < 0 THEN NULL
                ELSE (p_now AT TIME ZONE 'UTC')::date - GREATEST(rollup_days, 1) END
    FROM tiers;
$$ LANGUAGE sql STABLE;

COMMENT ON FUNCTION usage_retention(TIMESTAMPTZ) IS
    'Per-tenant usage retention from licenses.seats: hourly_cutoff (usage_hourly rows starting before '
    'it may go) and rollup_cutoff (daily rows and ledger days before it may go). NULL = keep forever. '
    'RDG-1.1 (#5759).';

-- One pass of every prune, each bounded by p_batch rows (the rest go on the next pass):
--   hourly    usage_hourly past the tier's hourly retention, only on finalized days (rule 6);
--   samples   usage_sample older than 7 days, whatever the tier;
--   daily / fields / unmatched / batches   past the tier's rollup retention.
CREATE OR REPLACE FUNCTION purge_usage(
    p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    p_batch INTEGER DEFAULT 10000
)
RETURNS JSONB AS $$
DECLARE
    v_batch INTEGER := GREATEST(p_batch, 1);
    v_hourly INTEGER;
    v_samples INTEGER;
    v_daily INTEGER;
    v_fields INTEGER;
    v_unmatched INTEGER;
    v_batches INTEGER;
BEGIN
    DELETE FROM apiome.usage_hourly
    WHERE ctid IN (
        SELECT h.ctid
        FROM apiome.usage_retention(p_now) r
        JOIN apiome.usage_hourly h
          ON h.tenant_id = r.tenant_id AND h.hour < r.hourly_cutoff
        JOIN apiome.usage_rollup_days d
          ON d.day = h.day AND d.finalized_at IS NOT NULL
        LIMIT v_batch
    );
    GET DIAGNOSTICS v_hourly = ROW_COUNT;

    DELETE FROM apiome.usage_sample
    WHERE id IN (
        SELECT id FROM apiome.usage_sample
        WHERE captured_at < p_now - INTERVAL '7 days'
        LIMIT v_batch
    );
    GET DIAGNOSTICS v_samples = ROW_COUNT;

    DELETE FROM apiome.usage_daily
    WHERE ctid IN (
        SELECT u.ctid
        FROM apiome.usage_retention(p_now) r
        JOIN apiome.usage_daily u ON u.tenant_id = r.tenant_id AND u.day < r.rollup_cutoff
        LIMIT v_batch
    );
    GET DIAGNOSTICS v_daily = ROW_COUNT;

    DELETE FROM apiome.usage_field_daily
    WHERE ctid IN (
        SELECT u.ctid
        FROM apiome.usage_retention(p_now) r
        JOIN apiome.usage_field_daily u ON u.tenant_id = r.tenant_id AND u.day < r.rollup_cutoff
        LIMIT v_batch
    );
    GET DIAGNOSTICS v_fields = ROW_COUNT;

    DELETE FROM apiome.usage_unmatched_daily
    WHERE ctid IN (
        SELECT u.ctid
        FROM apiome.usage_retention(p_now) r
        JOIN apiome.usage_unmatched_daily u ON u.tenant_id = r.tenant_id AND u.day < r.rollup_cutoff
        LIMIT v_batch
    );
    GET DIAGNOSTICS v_unmatched = ROW_COUNT;

    DELETE FROM apiome.usage_ingest_batch
    WHERE id IN (
        SELECT b.id
        FROM apiome.usage_retention(p_now) r
        JOIN apiome.usage_ingest_batch b
          ON b.tenant_id = r.tenant_id AND b.received_day < r.rollup_cutoff
        LIMIT v_batch
    );
    GET DIAGNOSTICS v_batches = ROW_COUNT;

    RETURN jsonb_build_object(
        'hourly', v_hourly,
        'samples', v_samples,
        'daily', v_daily,
        'fields', v_fields,
        'unmatched', v_unmatched,
        'batches', v_batches
    );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION purge_usage(TIMESTAMPTZ, INTEGER) IS
    'Prune the usage index per tier (at most p_batch rows per table per call): hourly rows past '
    'usage_hourly_retention_days on finalized days only, samples after 7 days, daily / field / '
    'unmatched rows and ledger batches past usage_rollup_retention_days. Returns the rows deleted per '
    'table as JSON (RDG-1.1, #5759).';

-- ---------------------------------------------------------------------------------------------------
-- Rule 7: seed the tier keys (fill-if-absent, as V271: an operator's value is never clobbered).
-- ---------------------------------------------------------------------------------------------------
UPDATE licenses
SET    seats = jsonb_build_object(
                 'usage_hourly_retention_days', 7,
                 'usage_rollup_retention_days', 90,
                 'usage_events_per_day',        100000
               ) || seats,
       updated_at = CURRENT_TIMESTAMP
WHERE  license_type = 'free';

UPDATE licenses
SET    seats = jsonb_build_object(
                 'usage_hourly_retention_days', 30,
                 'usage_rollup_retention_days', 395,
                 'usage_events_per_day',        10000000
               ) || seats,
       updated_at = CURRENT_TIMESTAMP
WHERE  license_type = 'paid';

UPDATE licenses
SET    seats = jsonb_build_object(
                 'usage_hourly_retention_days', 90,
                 'usage_rollup_retention_days', 730,
                 'usage_events_per_day',        100000000
               ) || seats,
       updated_at = CURRENT_TIMESTAMP
WHERE  license_type = 'sponsor';

COMMENT ON COLUMN licenses.seats IS
  'Capacity limits JSON. Canonical keys: max_tenants (int), max_users_per_tenant (int), '
  'max_projects (int), max_versions (int), max_ai_requests (int), mock_rps (int), '
  'mock_requests_per_month (int), agent_invocation_retention_days (int), '
  'agent_usage_rollup_retention_days (int), agent_key_rps (number), agent_key_daily_calls (int), '
  'usage_hourly_retention_days (int), usage_rollup_retention_days (int), usage_events_per_day (int). '
  'For the quota keys (projects/versions/ai) a negative value means unlimited and a missing key '
  'falls back to the Free-tier default (1 project / 3 versions / 0 AI requests). For the agent '
  'usage retention keys (AGX-3.3) a negative value keeps rows forever and a missing key falls back '
  'to Free (7 days raw / 90 days rollups). For the agent key limits (AGX-3.2) zero or a negative '
  'value means unlimited and a missing key falls back to Free (2 rps / 1000 calls per UTC day). '
  'For the usage index retention keys (RDG-1.1) a negative value keeps rows forever and a missing '
  'key falls back to Free (7 days hourly / 90 days rollups); usage_events_per_day is the daily '
  'ingest cap (zero or negative = unlimited; missing = Free, 100000).';
