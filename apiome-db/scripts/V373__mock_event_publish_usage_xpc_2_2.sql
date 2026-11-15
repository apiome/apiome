-- Mock broker publish usage, by channel and encoding — XPC-2.2 (#5736).
--
-- The hosted mock now publishes AsyncAPI events to a version's bound Kafka broker, periodically and
-- on demand. Every publish already counts as one mock request in `mock_usage` (V154), so quotas and
-- the usage sparkline see it. This table records what `mock_usage` cannot: which channel, which
-- encoding the record was written in (`json`, `avro`, `protobuf`), what triggered it, and how many
-- records were refused because their payload failed its schema (a refused record is never sent).
--
-- One row per tenant / project / version / channel / encoding / trigger / UTC day, incremented in
-- place, like `mock_usage`. No payload, key, header or topic data is stored.
--
-- Idempotent: safe to re-run.
--
-- Rollback notes:
--   DROP FUNCTION IF EXISTS apiome.record_mock_event_publish(UUID, TEXT, TEXT, TEXT, TEXT, TEXT, BOOLEAN);
--   DROP TABLE IF EXISTS apiome.mock_event_publish_usage;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS mock_event_publish_usage (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_slug VARCHAR(255) NOT NULL,
    version_label VARCHAR(255) NOT NULL,
    channel_key VARCHAR(512) NOT NULL,
    encoding VARCHAR(16) NOT NULL
        CONSTRAINT mock_event_publish_usage_encoding_check
            CHECK (encoding IN ('json', 'avro', 'protobuf')),
    trigger VARCHAR(16) NOT NULL
        CONSTRAINT mock_event_publish_usage_trigger_check
            CHECK (trigger IN ('periodic', 'on-demand')),
    usage_date DATE NOT NULL,
    published_count BIGINT NOT NULL DEFAULT 0 CHECK (published_count >= 0),
    rejected_count BIGINT NOT NULL DEFAULT 0 CHECK (rejected_count >= 0),
    PRIMARY KEY (tenant_id, project_slug, version_label, channel_key, encoding, trigger, usage_date)
);

CREATE INDEX IF NOT EXISTS idx_mock_event_publish_usage_tenant_date
    ON mock_event_publish_usage (tenant_id, usage_date DESC);

COMMENT ON TABLE mock_event_publish_usage IS
    'XPC-2.2 (#5736): daily counts of events the hosted mock published to a bound broker, per '
    'channel, encoding and trigger, plus records refused for failing their schema. Metadata only.';
COMMENT ON COLUMN mock_event_publish_usage.encoding IS
    'How the record value was written: json, avro (schemaless binary) or protobuf.';
COMMENT ON COLUMN mock_event_publish_usage.trigger IS
    'periodic (the channel interval) or on-demand (POST …/__channels__/{channel}/publish).';
COMMENT ON COLUMN mock_event_publish_usage.rejected_count IS
    'Records not sent because the payload, key or schema failed validation.';

CREATE OR REPLACE FUNCTION apiome.record_mock_event_publish(
    p_tenant_id UUID,
    p_project_slug TEXT,
    p_version_label TEXT,
    p_channel_key TEXT,
    p_encoding TEXT,
    p_trigger TEXT,
    p_published BOOLEAN
)
RETURNS void
LANGUAGE sql
AS $$
    INSERT INTO apiome.mock_event_publish_usage (
        tenant_id, project_slug, version_label, channel_key, encoding, trigger, usage_date,
        published_count, rejected_count
    )
    VALUES (
        p_tenant_id, p_project_slug, p_version_label, p_channel_key, p_encoding, p_trigger,
        (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date,
        CASE WHEN p_published THEN 1 ELSE 0 END,
        CASE WHEN p_published THEN 0 ELSE 1 END
    )
    ON CONFLICT (tenant_id, project_slug, version_label, channel_key, encoding, trigger, usage_date)
    DO UPDATE SET
        published_count = apiome.mock_event_publish_usage.published_count
            + CASE WHEN p_published THEN 1 ELSE 0 END,
        rejected_count = apiome.mock_event_publish_usage.rejected_count
            + CASE WHEN p_published THEN 0 ELSE 1 END;
$$;

COMMENT ON FUNCTION apiome.record_mock_event_publish(UUID, TEXT, TEXT, TEXT, TEXT, TEXT, BOOLEAN) IS
    'Atomically count one published (or refused) broker event for the daily rollup (#5736).';
