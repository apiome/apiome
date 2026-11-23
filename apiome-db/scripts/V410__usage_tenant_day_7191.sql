-- Per-tenant daily event counter for the usage ingest cap (DBP-1.8, #7191).
--
-- Every ingest batch checks the tenant's usage_events_per_day cap. Until DBP-1.8 it did that by
-- summing the day's usage_ingest_batch ledger (received - rejected) on every batch, while it held
-- the tenant's advisory lock: the busier the tenant, the longer the sum and the longer the lock.
--
--   * usage_tenant_day: one row per tenant and UTC day holding the events the ledger admitted that
--     day. The ingest writes its ledger row and adds to this counter in the same statement, so the
--     two cannot disagree. Reading the cap is then one primary-key probe.
--   * The ingest keeps only today and yesterday for each tenant: the statement that adds to today's
--     row deletes the tenant's older rows, so the table stays at about two rows per tenant and
--     needs no sweep.
--   * Backfill: today's and yesterday's counts are summed from the ledger once, so a deploy in the
--     middle of a UTC day keeps the cap where it was.
--
-- Unlike the old sum, the counter does not go down when a usage source is deleted (the ledger
-- rows cascade away with the source, the counter does not): deleting a source no longer gives a
-- day's quota back.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.usage_tenant_day;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS usage_tenant_day (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    day DATE NOT NULL,
    events_used BIGINT NOT NULL DEFAULT 0
        CONSTRAINT usage_tenant_day_events_used_ck CHECK (events_used >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT usage_tenant_day_pkey PRIMARY KEY (tenant_id, day)
);

COMMENT ON TABLE usage_tenant_day IS
    'DBP-1.8 (#7191): events each tenant''s usage ledger admitted per UTC day (received - rejected), '
    'kept by the ingest in the statement that writes the ledger row. The cap check reads it instead '
    'of summing usage_ingest_batch. Only today and yesterday are kept.';

INSERT INTO usage_tenant_day (tenant_id, day, events_used)
SELECT b.tenant_id, b.received_day, sum(b.received - b.rejected)
FROM usage_ingest_batch b
WHERE b.received_day >= (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date - 1
GROUP BY b.tenant_id, b.received_day
ON CONFLICT (tenant_id, day) DO NOTHING;

DO $$
BEGIN
    RAISE NOTICE 'usage_tenant_day added and backfilled (#7191, DBP-1.8).';
END $$;
