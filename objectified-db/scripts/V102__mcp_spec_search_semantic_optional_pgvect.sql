-- MCP spec.search_semantic: optional pgvector column on public-catalog revisions (cosine HNSW).
SET search_path TO odb, public;

ALTER TABLE odb.versions
  ADD COLUMN IF NOT EXISTS mcp_public_embedding vector(1536) NULL;

COMMENT ON COLUMN odb.versions.mcp_public_embedding IS
  'Optional embedding for MCP semantic search (spec.search_semantic); cosine distance via <=>; '
  'dimension must match OBJECTIFIED_MCP_OPENAI_EMBEDDING_DIMENSIONS (default 1536). Rows in '
  'odb.mcp_v_public_specs may still omit embeddings until backfilled.';

CREATE INDEX IF NOT EXISTS idx_versions_mcp_public_embedding_hnsw
  ON odb.versions USING hnsw (mcp_public_embedding vector_cosine_ops)
  WHERE mcp_public_embedding IS NOT NULL;
