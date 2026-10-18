-- Deployment metadata on catalog connector inventory rows (CDG-1.2, #5953).
--
-- A connector's inventory row already says where an API was found (`environment`, `hosts`,
-- `base_path`). Gateway connectors know more than that per API: the Kong connector records the
-- control plane id and name, the service's tags and enabled flag, the protocols, hosts and paths
-- its routes declare, and the *suggested* owners read from `owner:<team-slug>` tags (CDG-2.2
-- turns suggestions into owners; nothing here confirms one). The shape is per kind, so it is a
-- JSONB bag replaced by every sync, never a set of columns per gateway.
--
-- Rollback:
--   ALTER TABLE apiome.catalog_connector_items DROP COLUMN IF EXISTS deployment;
SET search_path TO apiome, public;

ALTER TABLE apiome.catalog_connector_items
    ADD COLUMN IF NOT EXISTS deployment JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN apiome.catalog_connector_items.deployment IS
    'Per-kind deployment metadata the latest sync saw (CDG-1.2): Kong records controlPlaneId, controlPlaneName, tags, enabled, protocols, hosts, paths, updatedAt and suggestedOwners. Never holds credentials.';
