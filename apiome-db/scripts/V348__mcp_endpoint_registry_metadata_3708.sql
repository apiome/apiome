-- What an MCP registry says about an imported endpoint -- V2-MCP-26.2 (#3708).
--
-- The `mcp-registry` connector (CDG-4.4, #5976) imports each registry `server.json` entry as an
-- MCP server (`added_via = 'registry'`). It mapped name, description and the chosen remote's
-- transport and URL onto the endpoint; the rest of what the entry says lived only on the
-- connector's inventory row. This column keeps it on the endpoint: the server name, `version`,
-- `websiteUrl`, the registry's `_meta` status (active / deprecated) and dates, and the chosen
-- remote with the headers it declares. A secret header's value is never stored.
--
-- NULL for endpoints added by hand or from a file. Written by the connector on every import that
-- changed it (app.mcp_server_json.registry_metadata).
SET search_path TO apiome, public;

ALTER TABLE apiome.mcp_endpoints
    ADD COLUMN IF NOT EXISTS registry_metadata JSONB;

COMMENT ON COLUMN apiome.mcp_endpoints.registry_metadata IS
    'MCP registry entry facts for a registry-imported endpoint (V2-MCP-26.2, #3708): serverName, version, websiteUrl, status, isLatest, publishedAt, updatedAt, registryUrl and remote {type, url, headers}; secret header values are never stored. NULL for endpoints not imported from a registry.';
