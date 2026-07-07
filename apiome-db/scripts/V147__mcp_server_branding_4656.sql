-- External MCP Catalog (#4656, V2-MCP-34.2 / MCAT-20.2): server branding capture.
--
-- A catalog card is text-only today, yet a server often advertises presentation branding in its
-- `initialize` result's `serverInfo` — a website URL and one or more icons (each an object with a
-- `src` URL and optional `mimeType`). Surfacing a logo + site link makes the catalog far more
-- recognizable. `server_name`/`server_title`/`instructions` are already captured on the snapshot;
-- this migration adds a place to persist the *validated* branding alongside them.
--
-- Version-level, on the immutable snapshot (unlike V146's endpoint-level transport metadata). Branding
-- is part of the server's advertised identity, so it belongs with the other `serverInfo` columns on
-- `mcp_endpoint_versions`, captured as of the snapshot that recorded it. The application owns the JSON
-- shape (app.mcp_client.branding.ServerBranding.to_row_value): an object with any of `website_url`,
-- `icon_url`, `icon_mime_type` — each an https-only, SSRF-guarded, length-bounded URL (or MIME string),
-- with absent fields omitted rather than stored as null. NULL for the whole column means the server
-- advertised no usable branding.
--
-- Deliberately *not* folded into the surface fingerprint (the app excludes it from the canonical
-- projection), so a purely cosmetic rebrand never mints a spurious version; the assets are only ever
-- *referenced* (rendered by the browser), never fetched or executed server-side.
--
-- The column is nullable with no default: a snapshot has no branding until one is discovered, and older
-- (2025-03-26) servers that predate `websiteUrl`/`icons` never get any.
--
-- Rollback notes: this migration is purely additive (one nullable column + comment). To roll back:
--   ALTER TABLE apiome.mcp_endpoint_versions DROP COLUMN IF EXISTS server_branding;

SET search_path TO apiome, public;

ALTER TABLE mcp_endpoint_versions
    ADD COLUMN IF NOT EXISTS server_branding JSONB;

COMMENT ON COLUMN mcp_endpoint_versions.server_branding IS 'Validated server branding advertised in the initialize serverInfo (https-only, SSRF-guarded website/icon URLs); shape owned by app.mcp_client.branding; NULL when none advertised (#4656, V2-MCP-34.2)';
