-- MCP read model: published + public catalog endpoints as a stable public-browse surface
-- (V2-MCP-23.6 / MCAT-1.6, #3671). Mirrors the V095 `mcp_v_public_specs` pattern: an immutable,
-- credential-free read view that apiome-browse's public MCP pages (and only public surfaces)
-- consume. Like V095 it filters to published + public-visible rows so private endpoints can never
-- leak into anonymous browse, and it joins the current discovery snapshot's quality score/grade.
--
-- Credentials are NEVER exposed: the raw `endpoint_url` (which may carry userinfo such as
-- `https://user:secret@host/…`) is deliberately not selected. Only the host is published, derived
-- with the same expression apiome-rest uses for catalog host extraction
-- (`substring(url from '://(?:[^@/]*@)?([^:/?#]+)')`, which strips any `user:pass@` userinfo).
--
-- The `published`/`visibility` filter is already index-backed by
-- `idx_mcp_endpoints_published_visibility` (V126); capability full-text search over this view is
-- backed by `idx_mcp_capability_items_fts` (V127). No new index is required for the view itself.
SET search_path TO apiome, public;

CREATE OR REPLACE VIEW apiome.mcp_v_public_endpoints AS
SELECT
  e.id,
  e.tenant_id,
  e.name,
  e.slug,
  e.category,
  e.transport,
  e.description,
  e.current_version_id,
  substring(e.endpoint_url from '://(?:[^@/]*@)?([^:/?#]+)') AS host,
  s.score,
  s.grade,
  s.scored_at,
  e.last_discovered_at,
  e.updated_at
FROM apiome.mcp_endpoints e
LEFT JOIN apiome.mcp_version_scores s ON s.version_id = e.current_version_id
WHERE e.deleted_at IS NULL
  AND e.enabled IS TRUE
  AND e.published IS TRUE
  AND e.visibility = 'public'::apiome.visibility_type;

COMMENT ON VIEW apiome.mcp_v_public_endpoints IS
  'MCP catalog discovery: one row per endpoint that is enabled, published, and public-visible (#3671). Credential-free (host only, no endpoint_url); current-version quality score/grade joined. Backs apiome-browse public MCP pages (MCAT-9.6/9.7).';

COMMENT ON COLUMN apiome.mcp_v_public_endpoints.id IS
  'Endpoint id (mcp_endpoints.id); stable identity for public browse.';

COMMENT ON COLUMN apiome.mcp_v_public_endpoints.tenant_id IS
  'Owning tenant (mcp_endpoints.tenant_id).';

COMMENT ON COLUMN apiome.mcp_v_public_endpoints.name IS
  'Human-readable endpoint name (mcp_endpoints.name).';

COMMENT ON COLUMN apiome.mcp_v_public_endpoints.slug IS
  'Tenant-unique URL slug (mcp_endpoints.slug); addresses the endpoint in public browse.';

COMMENT ON COLUMN apiome.mcp_v_public_endpoints.category IS
  'Optional category label (mcp_endpoints.category); nullable.';

COMMENT ON COLUMN apiome.mcp_v_public_endpoints.transport IS
  'MCP transport the server speaks (streamable_http | sse | stdio).';

COMMENT ON COLUMN apiome.mcp_v_public_endpoints.description IS
  'Endpoint description (mcp_endpoints.description); nullable.';

COMMENT ON COLUMN apiome.mcp_v_public_endpoints.current_version_id IS
  'Current discovery snapshot (mcp_endpoints.current_version_id); join key to capability items and score.';

COMMENT ON COLUMN apiome.mcp_v_public_endpoints.host IS
  'Host extracted from endpoint_url with userinfo stripped; the raw URL (and any embedded credentials) is intentionally never exposed.';

COMMENT ON COLUMN apiome.mcp_v_public_endpoints.score IS
  'Quality score (0-100) of the current snapshot (mcp_version_scores.score); NULL if not yet scored.';

COMMENT ON COLUMN apiome.mcp_v_public_endpoints.grade IS
  'A-F letter grade of the current snapshot (mcp_version_scores.grade); NULL if not yet scored. Grade-led browse orders on this.';

COMMENT ON COLUMN apiome.mcp_v_public_endpoints.scored_at IS
  'When the current snapshot was last scored (mcp_version_scores.scored_at); NULL if not yet scored.';

COMMENT ON COLUMN apiome.mcp_v_public_endpoints.last_discovered_at IS
  'When the endpoint was last re-handshaked (mcp_endpoints.last_discovered_at); recency signal for browse.';

COMMENT ON COLUMN apiome.mcp_v_public_endpoints.updated_at IS
  'Endpoint freshness cursor (mcp_endpoints.updated_at).';
