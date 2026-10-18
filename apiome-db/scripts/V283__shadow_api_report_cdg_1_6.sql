-- Shadow-API report: ignore reasons, manual links and a connector notification throttle
-- (CDG-1.6, #5957).
--
-- The shadow-API report compares what connected gateways serve with what the catalog describes.
-- A tenant acts on each finding by hand — nothing is ever linked automatically:
--
--   * "Ignore with reason" keeps the reason, who gave it and when, and a snapshot of the hosts
--     and base path the item had at that moment. When the gateway later serves the item on a
--     different host or path, the report shows it again (the reason is kept for context).
--   * "Link to item" records who linked the inventory row to a catalog item or Project, and when.
--
-- New shadow APIs found by a sync raise a `catalog.connector.shadow_api_detected` notification on
-- the tenant's channels. The repository notification throttle is keyed by repository, so connectors
-- get their own table with the same one-per-hour conditional-upsert rule.
--
-- Rollback:
--   DROP TABLE IF EXISTS apiome.catalog_connector_notification_throttle;
--   ALTER TABLE apiome.catalog_connector_items
--     DROP COLUMN IF EXISTS ignored_reason, DROP COLUMN IF EXISTS ignored_at,
--     DROP COLUMN IF EXISTS ignored_by, DROP COLUMN IF EXISTS ignored_hosts,
--     DROP COLUMN IF EXISTS ignored_base_path, DROP COLUMN IF EXISTS linked_by,
--     DROP COLUMN IF EXISTS linked_at;
SET search_path TO apiome, public;

-- ─── 1. Ignore reasons and manual links on inventory rows ─────────────────────

ALTER TABLE apiome.catalog_connector_items
    ADD COLUMN IF NOT EXISTS ignored_reason    TEXT CHECK (ignored_reason IS NULL OR length(ignored_reason) <= 1000),
    ADD COLUMN IF NOT EXISTS ignored_at        TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ignored_by        UUID,
    ADD COLUMN IF NOT EXISTS ignored_hosts     TEXT[],
    ADD COLUMN IF NOT EXISTS ignored_base_path TEXT,
    ADD COLUMN IF NOT EXISTS linked_by         UUID,
    ADD COLUMN IF NOT EXISTS linked_at         TIMESTAMPTZ;

COMMENT ON COLUMN apiome.catalog_connector_items.ignored_reason IS
    'Why a tenant ignored this API in the shadow-API report (CDG-1.6). Kept after the API reappears.';
COMMENT ON COLUMN apiome.catalog_connector_items.ignored_hosts IS
    'The hosts the API was served on when it was ignored; the report shows it again when they change.';
COMMENT ON COLUMN apiome.catalog_connector_items.ignored_base_path IS
    'The base path the API was served under when it was ignored; a change makes it reappear.';
COMMENT ON COLUMN apiome.catalog_connector_items.linked_by IS
    'Who linked this inventory row to a catalog item or Project by hand ("Link to item", CDG-1.6); NULL for a sync import.';

-- ─── 2. Connector notification throttle ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.catalog_connector_notification_throttle (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id        UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    connector_id     UUID NOT NULL REFERENCES apiome.catalog_connectors(id) ON DELETE CASCADE,
    event_type       VARCHAR(64) NOT NULL
                     CHECK (event_type IN ('catalog.connector.shadow_api_detected')),
    last_notified_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    suppressed_count BIGINT NOT NULL DEFAULT 0 CHECK (suppressed_count >= 0),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_catalog_connector_notification_throttle UNIQUE (connector_id, event_type)
);

COMMENT ON TABLE apiome.catalog_connector_notification_throttle IS
    'At most one notification per connector per event type per window (CDG-1.6), the REPO-7.2 rule for connectors.';
