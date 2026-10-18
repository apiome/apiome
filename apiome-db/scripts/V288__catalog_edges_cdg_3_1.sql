-- Graph edge store — CDG-3.1 (#5966).
--
-- The edges between catalog entities already exist in six places and no query joins them: consumer
-- contracts (who consumes which operation and schema pointer), conversions (the project a catalog
-- item was converted into), identity groups (the same API across formats), MCP sources (what an MCP
-- server was built from), connector items (where an API is deployed) and repository bindings and
-- import specs (which repository serves a spec). This table holds them all, with one pointer
-- vocabulary (`app.change_taxonomy` JSON pointers) and one provenance rule.
--
--   provenance — `derived` edges are re-computed from those source rows by `app.catalog_graph`;
--                `declared` (CDG-3.2) and `runtime` (RDG-1.x) edges are written by their producers.
--   source_ref — which source row produced the edge (`consumer_contract:<id>`, `conversion:<id>`, …).
--   stale_since — set when the source row of a derived edge disappears; the edge is kept, visibly
--                 stale, for 30 days (so a vanished consumer is "stale" before it is "gone"), then
--                 purged. Cleared if the source row comes back.
--
-- The pointer index is a `text_pattern_ops` btree rather than GIN: a pointer is one text value and
-- the blast-radius query (CDG-3.3) matches pointer prefixes (`/paths/~1pets/get` covers everything
-- under it), which a pattern-ops btree serves with an index range scan.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.catalog_edges;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS catalog_edges (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    from_kind VARCHAR(32) NOT NULL,
    from_id UUID NOT NULL,
    to_kind VARCHAR(32) NOT NULL,
    to_id UUID NOT NULL,

    edge_kind VARCHAR(32) NOT NULL
        CONSTRAINT catalog_edges_kind_check
            CHECK (edge_kind IN ('depends_on', 'consumes', 'served_by', 'deployed_on', 'built_from',
                                 'converted_from', 'identity_of', 'runtime_calls')),
    -- A JSON pointer (operation or schema) in the app.change_taxonomy vocabulary, or NULL.
    pointer TEXT,
    provenance VARCHAR(16) NOT NULL
        CONSTRAINT catalog_edges_provenance_check CHECK (provenance IN ('declared', 'derived', 'runtime')),
    source_ref TEXT NOT NULL,

    first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    stale_since TIMESTAMP WITH TIME ZONE,

    -- Bounded context about the edge (a revision, an environment, a fidelity grade). Never a payload.
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT catalog_edges_evidence_check
            CHECK (jsonb_typeof(evidence) = 'object' AND pg_column_size(evidence) <= 4096),

    CONSTRAINT catalog_edges_node_kinds_check CHECK (
        from_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector',
                      'repository', 'mcp_source', 'identity_group')
        AND to_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector',
                        'repository', 'mcp_source', 'identity_group')
    ),
    CONSTRAINT catalog_edges_identity_key UNIQUE NULLS NOT DISTINCT
        (tenant_id, from_kind, from_id, to_kind, to_id, edge_kind, pointer, provenance, source_ref)
);

-- Both directions: "what does X depend on" and "who depends on X".
CREATE INDEX IF NOT EXISTS idx_catalog_edges_from ON catalog_edges (tenant_id, from_kind, from_id);
CREATE INDEX IF NOT EXISTS idx_catalog_edges_to ON catalog_edges (tenant_id, to_kind, to_id);
-- Pointer prefix lookups (blast radius, CDG-3.3).
CREATE INDEX IF NOT EXISTS idx_catalog_edges_pointer
    ON catalog_edges (tenant_id, pointer text_pattern_ops)
    WHERE pointer IS NOT NULL;
-- The materializer's stale sweep and purge.
CREATE INDEX IF NOT EXISTS idx_catalog_edges_family
    ON catalog_edges (tenant_id, provenance, edge_kind, last_seen_at);

COMMENT ON TABLE catalog_edges IS
    'Edges between catalog entities: derived from source rows, declared, or observed at runtime (CDG-3.1, #5966)';
COMMENT ON COLUMN catalog_edges.source_ref IS 'The source row that produced the edge, e.g. consumer_contract:<id>';
COMMENT ON COLUMN catalog_edges.stale_since IS 'When a derived edge''s source disappeared; purged 30 days later';
