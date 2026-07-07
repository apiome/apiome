-- External MCP Catalog (#4655, V2-MCP-34.1 / MCAT-20.1): host & transport metadata capture.
--
-- The catalog records a server's *capabilities* (mcp_endpoint_versions / mcp_capability_items) but
-- almost nothing about the *service* hosting them. This migration adds a place to persist the
-- non-invasive transport facts the discovery handshake already observes — hostname/host, a TLS
-- certificate summary (issuer, validity window, SAN) for HTTPS endpoints, notable HTTP response
-- headers (server, rate-limit hints), and connect/handshake timing — so the identity card (MCAT-15.1)
-- and report (MCAT-19.1) can surface "who hosts this, is its TLS valid, how responsive is it".
--
-- Endpoint-level, not version-level. These facts are *volatile* (connect timing differs on every
-- run; a header or cert can rotate without the capability surface changing at all) and the version
-- snapshots in mcp_endpoint_versions are deliberately immutable and gated by a surface fingerprint —
-- folding transport facts into them would either pollute the fingerprint (spurious versions on every
-- run) or freeze a stale observation on the "unchanged" path. So this is a *latest observation* on the
-- endpoint, refreshed by every successful discovery (changed or unchanged). `transport_metadata` holds
-- the captured JSON document (its shape is owned by the application, app.mcp_client.transport_meta),
-- and `transport_metadata_at` records when that observation was taken.
--
-- Both columns are nullable with no default: an endpoint has no transport metadata until its first
-- successful discovery, and a stdio endpoint (no network handshake) may never get any.
--
-- Rollback notes: this migration is purely additive (two nullable columns + comments). To roll back:
--   ALTER TABLE apiome.mcp_endpoints DROP COLUMN IF EXISTS transport_metadata_at;
--   ALTER TABLE apiome.mcp_endpoints DROP COLUMN IF EXISTS transport_metadata;

SET search_path TO apiome, public;

ALTER TABLE mcp_endpoints
    ADD COLUMN IF NOT EXISTS transport_metadata JSONB,
    ADD COLUMN IF NOT EXISTS transport_metadata_at TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN mcp_endpoints.transport_metadata IS 'Latest host/transport facts observed at discovery (host, TLS cert summary, notable response headers, connect timing); NULL until first successful discovery (#4655, V2-MCP-34.1)';
COMMENT ON COLUMN mcp_endpoints.transport_metadata_at IS 'When transport_metadata was last captured; NULL until first successful discovery';
