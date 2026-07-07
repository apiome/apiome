-- Scheduled catalog digest reports — per-tenant configuration (#4654, V2-MCP-33.5 / MCAT-19.5).
--
-- Operators want a recurring "here's your catalog this week" without opening the app. A background
-- sweep (apiome-rest `app.mcp_catalog_digest_sweep`, reusing the `repository_refresh_sweep.py`
-- pattern) compiles a periodic digest — new endpoints, grade movements, breaking changes and
-- discovery-health problems over the window since the last digest — and delivers it over the tenant's
-- existing push-webhook subscriptions (the same channel the RAR-5.4 refresh notifications use). This
-- table holds the per-tenant knobs that drive that sweep.
--
-- Design:
--   * One row per tenant (`tenant_id` PRIMARY KEY, FK ON DELETE CASCADE) — the config *is* the tenant's
--     digest preference, so there is nothing to key beyond the tenant.
--   * Opt-in: `enabled` defaults FALSE, so a tenant that never configures a digest is never selected by
--     the sweep and never sends anything (an acceptance criterion). Absence of a row is treated exactly
--     like `enabled = FALSE` by the reader default.
--   * `cadence_seconds` NULL means "use the global default cadence" (apiome-rest
--     `APIOME_MCP_DIGEST_DEFAULT_CADENCE`), mirroring how `mcp_endpoints.discovery_cadence_seconds`
--     falls back to the global discovery default. A positive override sets a per-tenant cadence.
--   * `send_empty` decides the empty-window behaviour the acceptance criteria call out: FALSE (default)
--     sends nothing when the window has no changes; TRUE sends an explicit "no changes" digest.
--   * `last_digest_at` is the sweep's cadence + window anchor: the next digest's window starts here and
--     the "is this tenant due?" check measures from it. NULL (never sent) makes the tenant immediately
--     due; the first digest's window is then bounded to one cadence back so it cannot scan all history.
--
-- Rollback notes: purely additive (one table). To roll back:
--   DROP TABLE IF EXISTS apiome.mcp_catalog_digest_configs;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.mcp_catalog_digest_configs (
  tenant_id        UUID PRIMARY KEY REFERENCES apiome.tenants(id) ON DELETE CASCADE,
  enabled          BOOLEAN NOT NULL DEFAULT false,
  cadence_seconds  INTEGER,
  send_empty       BOOLEAN NOT NULL DEFAULT false,
  last_digest_at   TIMESTAMP WITH TIME ZONE,
  created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT mcp_catalog_digest_cadence_positive
    CHECK (cadence_seconds IS NULL OR cadence_seconds > 0)
);

-- The sweep's due-selection scans enabled configs whose cadence has elapsed, ordered by the anchor;
-- a partial index over just the enabled rows keeps that scan cheap as the number of tenants grows.
CREATE INDEX IF NOT EXISTS idx_mcp_catalog_digest_due
  ON apiome.mcp_catalog_digest_configs (last_digest_at)
  WHERE enabled = true;

COMMENT ON TABLE apiome.mcp_catalog_digest_configs IS
  'Per-tenant scheduled catalog digest configuration (MCAT-19.5). Drives app.mcp_catalog_digest_sweep: '
  'opt-in (enabled), per-tenant cadence (cadence_seconds, NULL = global default), empty-window policy '
  '(send_empty) and the cadence/window anchor (last_digest_at). One row per tenant; a missing row means '
  'the tenant has never opted in (treated as disabled).';
COMMENT ON COLUMN apiome.mcp_catalog_digest_configs.enabled IS
  'Opt-in switch. FALSE (default) = the sweep never selects this tenant and sends nothing.';
COMMENT ON COLUMN apiome.mcp_catalog_digest_configs.cadence_seconds IS
  'Per-tenant digest cadence in seconds; NULL = use the global APIOME_MCP_DIGEST_DEFAULT_CADENCE.';
COMMENT ON COLUMN apiome.mcp_catalog_digest_configs.send_empty IS
  'When TRUE, an empty window still sends an explicit "no changes" digest; FALSE (default) stays silent.';
COMMENT ON COLUMN apiome.mcp_catalog_digest_configs.last_digest_at IS
  'Anchor for the next digest window and the cadence due-check; NULL = never sent (immediately due).';
