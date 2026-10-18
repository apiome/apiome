-- Declared dependencies — CDG-3.2 (#5967).
--
-- A service can say what it depends on: through `PUT /v1/graph/{tenant}/entities/{kind}/{id}/dependencies`
-- (source_ref `manual`), an `x-apiome-depends-on` list at its spec's root (source_ref `spec`), or a
-- Backstage `catalog-info.yaml` in its repository (source_ref `backstage:<path>`). References that
-- resolve to an entity become `declared` edges in `catalog_edges` (V288). References that resolve to
-- nothing are kept here, on the declaring entity, so they are shown rather than dropped.
--
-- Each declaring source replaces its own rows on every write (per entity and `source_ref`), so a
-- re-import or a repeated PUT never duplicates them, and removing a reference removes its row.
--
--   reference — the reference as written (`payments`, `api:default/payments`, `customers#/…`).
--   pointer   — the JSON pointer after `#`, if any.
--   edge_kind — the edge the reference would have become (`depends_on`, `consumes`).
--   reason    — why it did not resolve: `not-found` (no entity by that name) or `self`.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.catalog_unresolved_dependencies;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS catalog_unresolved_dependencies (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    from_kind    TEXT NOT NULL,
    from_id      UUID NOT NULL,
    source_ref   TEXT NOT NULL,
    reference    TEXT NOT NULL,
    pointer      TEXT,
    edge_kind    TEXT NOT NULL DEFAULT 'depends_on',
    reason       TEXT NOT NULL DEFAULT 'not-found',
    note         TEXT,
    created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT catalog_unresolved_dependencies_from_kind_check CHECK (from_kind IN (
        'project', 'catalog_item', 'consumer', 'connector', 'mcp_endpoint', 'mcp_source', 'repository',
        'identity_group'
    )),
    CONSTRAINT catalog_unresolved_dependencies_edge_kind_check CHECK (edge_kind IN ('depends_on', 'consumes')),
    CONSTRAINT catalog_unresolved_dependencies_reason_check CHECK (reason IN ('not-found', 'self')),
    CONSTRAINT catalog_unresolved_dependencies_reference_check CHECK (length(reference) BETWEEN 1 AND 512),
    CONSTRAINT catalog_unresolved_dependencies_note_check CHECK (note IS NULL OR length(note) <= 500),
    CONSTRAINT catalog_unresolved_dependencies_identity_key UNIQUE NULLS NOT DISTINCT
        (tenant_id, from_kind, from_id, source_ref, reference, pointer, edge_kind)
);

CREATE INDEX IF NOT EXISTS idx_catalog_unresolved_dependencies_from
    ON catalog_unresolved_dependencies (tenant_id, from_id, source_ref);

COMMENT ON TABLE catalog_unresolved_dependencies IS
    'Declared dependency references that resolved to no entity (CDG-3.2); replaced per declaring source.';
