-- Similar-servers via capability overlap + embeddings (#4648, V2-MCP-32.4 / MCAT-18.4).
--
-- Discovery is keyword-only today; users want "servers like this one". Similarity is drawn from two
-- signals: (a) capability-name/description **overlap** (a Jaccard set-overlap over an endpoint's
-- tool/resource/prompt names — computed live from the already-normalized `mcp_capability_items`, so
-- it needs no new storage) and (b) **semantic embeddings** — a single vector per discovery snapshot
-- summarizing its capability text, compared by cosine nearest-neighbour to surface related servers.
--
-- This migration adds the storage for (b): an optional `mcp_capability_embedding` column on the
-- immutable per-discovery snapshot `mcp_endpoint_versions` (V128), reusing the existing pgvector
-- setup — the `vector` extension enabled in V001, the 2000-dimension Ollama vectorization convention
-- established for `data_snapshot.embedding` in V060/V063 (qwen3-embedding:4b, which is the embedding
-- service actually wired in apiome-rest), and the cosine-HNSW index pattern of V102's
-- `versions.mcp_public_embedding`. 2000 is pgvector's HNSW dimension ceiling.
--
-- The column is nullable and populated lazily: an endpoint's snapshot carries an embedding only once
-- it has been backfilled (apiome-rest's similar-servers reindex step, gated behind
-- APIOME_MCP_SIMILARITY_EMBEDDINGS_ENABLED). When embeddings are disabled — or simply not yet
-- backfilled — every row is NULL, the nearest-neighbour read finds no vectors, and the similar-servers
-- feature gracefully falls back to overlap-only (the "gracefully no-ops if embeddings are disabled"
-- acceptance criterion holds by construction). The capability-overlap signal never touches this
-- column, so it works whether or not pgvector embeddings are enabled.
--
-- Rollback notes: purely additive (one nullable column + its partial index). To roll back:
--   DROP INDEX IF EXISTS apiome.idx_mcp_endpoint_versions_capability_embedding_hnsw;
--   ALTER TABLE apiome.mcp_endpoint_versions DROP COLUMN IF EXISTS mcp_capability_embedding;
-- The shared `vector` extension (V001) is left in place (data_snapshot and versions still use it).

SET search_path TO apiome, public;

ALTER TABLE apiome.mcp_endpoint_versions
  ADD COLUMN IF NOT EXISTS mcp_capability_embedding vector(2000) NULL;

COMMENT ON COLUMN apiome.mcp_endpoint_versions.mcp_capability_embedding IS
  'Optional semantic embedding of this snapshot''s capability text (tool/resource/prompt names + '
  'descriptions), for "similar servers" nearest-neighbour discovery (MCAT-18.4); cosine distance via '
  '<=>; dimension 2000 matches the qwen3-embedding:4b vectorization used elsewhere (V060/V063). NULL '
  'until backfilled, or whenever embeddings are disabled — the feature then falls back to '
  'capability-overlap similarity, which needs no embedding.';

-- Cosine-HNSW index over the populated embeddings only (partial: NULLs are the common case until
-- backfill, and are never a nearest-neighbour candidate). Mirrors V102's public-embedding index.
CREATE INDEX IF NOT EXISTS idx_mcp_endpoint_versions_capability_embedding_hnsw
  ON apiome.mcp_endpoint_versions USING hnsw (mcp_capability_embedding vector_cosine_ops)
  WHERE mcp_capability_embedding IS NOT NULL;
