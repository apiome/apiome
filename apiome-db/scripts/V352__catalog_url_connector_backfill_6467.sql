-- Catalog URL connector backfill (RAR-6.1b, #6467).
--
-- A catalog item imported with **Document URL** keeps its URL on its version
-- (`versions.format_metadata` → `inputKind: "url"`, `sourceUri`), but nothing ever fetched it
-- again. apiome-rest now registers a `url` connector source (`app.url_connector_source`): a `url`
-- connector with **no base URL** is the workspace's URL connector. On its cadence it re-checks
-- every URL-sourced catalog item with `If-None-Match` / `If-Modified-Since` and imports changed
-- content as a new revision of the item.
--
-- This migration gives every workspace that already has URL-sourced catalog items that connector,
-- so those items show in the Connectors list with a cadence and refresh from now on:
--
--   1. One live `url` connector per tenant, named "Catalog URLs", no base URL, deployment-default
--      cadence. Its creator is the person who imported the tenant's oldest URL item (scheduled
--      runs import on the creator's behalf). A tenant that already has a workspace-mode `url`
--      connector, or a live connector named "Catalog URLs", is left alone.
--
--   2. One inventory row per URL-sourced catalog item (`remote_id` = the item id), linked to it
--      (`project_id`) and `imported`. `deployment.url` is the stored URL. No content anchor is
--      written: the first run anchors each item to what its URL serves then, without a new
--      revision, so introducing the connector never re-imports every item.
--
-- A catalog item imported from a URL later joins the connector on its next run; no migration or
-- trigger is needed for that.
--
-- Idempotent: re-running adds nothing (NOT EXISTS / ON CONFLICT).
--
-- Rollback:
--   DELETE FROM apiome.catalog_connectors
--   WHERE kind = 'url' AND name = 'Catalog URLs' AND COALESCE(btrim(base_url), '') = '';
SET search_path TO apiome, public;

-- The live URL-sourced catalog items: latest version imported from an http(s) URL.
CREATE TEMP TABLE _v352_url_items AS
SELECT p.tenant_id, p.id AS project_id, p.name, p.creator_id, p.created_at,
       v.format_metadata->>'sourceUri' AS url
FROM apiome.projects p
JOIN LATERAL (
    SELECT format_metadata
    FROM apiome.versions
    WHERE project_id = p.id
    ORDER BY created_at DESC
    LIMIT 1
) v ON TRUE
WHERE p.deleted_at IS NULL
  AND p.publishable = FALSE
  AND v.format_metadata->>'inputKind' = 'url'
  AND COALESCE(v.format_metadata->>'sourceUri', '') ~* '^https?://';

-- ─── 1. One workspace URL connector per tenant ────────────────────────────────

INSERT INTO apiome.catalog_connectors (tenant_id, kind, name, base_url, scope, created_by)
SELECT DISTINCT ON (i.tenant_id) i.tenant_id, 'url', 'Catalog URLs', NULL, '{}'::jsonb, i.creator_id
FROM _v352_url_items i
WHERE NOT EXISTS (
    SELECT 1 FROM apiome.catalog_connectors c
    WHERE c.tenant_id = i.tenant_id
      AND c.deleted_at IS NULL
      AND (
          (c.kind = 'url' AND COALESCE(btrim(c.base_url), '') = '')
          OR lower(c.name) = lower('Catalog URLs')
      )
)
ORDER BY i.tenant_id, i.created_at, i.project_id;

-- ─── 2. The items, linked to that connector ───────────────────────────────────

INSERT INTO apiome.catalog_connector_items
    (connector_id, remote_id, remote_name, status, project_id, deployment)
SELECT c.id, i.project_id::text, i.name, 'imported', i.project_id, jsonb_build_object('url', i.url)
FROM _v352_url_items i
JOIN LATERAL (
    -- The tenant's oldest live workspace-mode url connector: the one apiome-rest lets act.
    SELECT id FROM apiome.catalog_connectors c
    WHERE c.tenant_id = i.tenant_id
      AND c.kind = 'url'
      AND c.deleted_at IS NULL
      AND COALESCE(btrim(c.base_url), '') = ''
    ORDER BY c.created_at, c.id
    LIMIT 1
) c ON TRUE
ON CONFLICT (connector_id, remote_id) DO NOTHING;

DROP TABLE _v352_url_items;
