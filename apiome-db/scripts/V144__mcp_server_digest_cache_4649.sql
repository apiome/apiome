-- Natural-language server digest + usage examples cache (#4649, V2-MCP-32.5 / MCAT-18.5).
--
-- Even a well-visualized surface still asks the reader to synthesize "so what can this actually do for
-- me?". The digest feature answers that with an opt-in, gated AI step: a short "this server lets you …"
-- summary of a cataloged MCP server (written via the Claude API) paired with one deterministic,
-- schema-derived example call per tool. The summary is expensive to produce, so it is computed once per
-- surface and cached — this table is that cache.
--
-- Keyed on `surface_fingerprint` (the stable SHA-256 of a discovery snapshot's semantically-meaningful
-- surface, V128 `mcp_endpoint_versions.surface_fingerprint`): the digest is a pure function of the
-- server's *declared, public* surface (tool names/descriptions/schemas + instructions — no tenant
-- secrets), so one entry can be shared across every tenant and every version snapshot that hashes to the
-- same fingerprint. Because any surface change mints a new version with a new fingerprint, keying the
-- cache on the fingerprint gives the "regenerated on surface change" acceptance criterion for free — a
-- changed surface simply misses the cache. Not a foreign key to `mcp_endpoint_versions`: the fingerprint
-- is a content hash shared across rows/tenants, not a row identity, and the cache should survive the
-- pruning of any individual version snapshot that produced it.
--
-- The feature is OFF by default (apiome-rest `APIOME_MCP_AI_DIGEST_ENABLED`); when disabled the table is
-- simply never written, and the digest read endpoint returns the (deterministic, always-available)
-- example calls with a null digest. `examples` is stored alongside the digest as the snapshot of the
-- per-tool example calls that accompanied it (JSONB); `model` records which Claude model produced the
-- text, for provenance and so a model change is visible.
--
-- Rollback notes: purely additive (one table). To roll back:
--   DROP TABLE IF EXISTS apiome.mcp_server_digests;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.mcp_server_digests (
  surface_fingerprint  TEXT PRIMARY KEY,
  digest               TEXT        NOT NULL,
  examples             JSONB       NOT NULL DEFAULT '[]'::jsonb,
  model                TEXT,
  generated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE apiome.mcp_server_digests IS
  'Per-surface cache of the natural-language server digest + usage examples (MCAT-18.5). Keyed on '
  'mcp_endpoint_versions.surface_fingerprint so the AI summary is computed once per surface and '
  'regenerated only when the surface (and thus the fingerprint) changes. Global, not tenant-scoped: the '
  'digest derives only from a server''s declared public surface, so identical surfaces across tenants '
  'share one entry.';
COMMENT ON COLUMN apiome.mcp_server_digests.digest IS
  'AI-generated plain-language "this server lets you …" summary of the surface.';
COMMENT ON COLUMN apiome.mcp_server_digests.examples IS
  'JSON array of the per-tool example calls (name/title/description/arguments) synthesized deterministically '
  'from each tool''s input_schema — snapshotted alongside the digest.';
COMMENT ON COLUMN apiome.mcp_server_digests.model IS
  'The Claude model that produced the digest, recorded as provenance.';
