-- Cross-server capability search: per-item semantic embeddings (#4661, V2-MCP-35.2 / MCAT-21.2).
--
-- MCAT-9.2 (V127) already indexes capability items for full-text search; this migration adds the
-- optional pgvector column that backs the semantic half of MCAT-21.2's cross-server capability
-- search. Each row in `mcp_capability_items` may carry a single embedding of its own
-- name/title/description text (distinct from the per-snapshot aggregate on
-- `mcp_endpoint_versions.mcp_capability_embedding` added in V143 for "similar servers").
--
-- The column is nullable and populated lazily (backfill / on-demand reindex) — when embeddings are
-- disabled or simply not yet stored, the search API falls back to keyword (FTS) matches only, never
-- a 500. Dimension 2000 matches the qwen3-embedding:4b convention used elsewhere (V060/V063/V143).
--
-- Rollback notes:
--   DROP INDEX IF EXISTS apiome.idx_mcp_capability_items_embedding_hnsw;
--   ALTER TABLE apiome.mcp_capability_items DROP COLUMN IF EXISTS embedding;

SET search_path TO apiome, public;

ALTER TABLE apiome.mcp_capability_items
  ADD COLUMN IF NOT EXISTS embedding vector(2000) NULL;

COMMENT ON COLUMN apiome.mcp_capability_items.embedding IS
  'Optional semantic embedding of this capability item''s name/title/description for cross-server '
  'capability search (MCAT-21.2); cosine distance via <=>; dimension 2000 matches the '
  'qwen3-embedding:4b vectorization used elsewhere. NULL until backfilled, or whenever embeddings '
  'are disabled — the feature then falls back to FTS-only matches.';

CREATE INDEX IF NOT EXISTS idx_mcp_capability_items_embedding_hnsw
  ON apiome.mcp_capability_items USING hnsw (embedding vector_cosine_ops)
  WHERE embedding IS NOT NULL;
