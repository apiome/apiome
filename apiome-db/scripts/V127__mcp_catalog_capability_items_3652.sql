-- External MCP Catalog (#3652, V2-MCP-15.2 / MCAT-1.2): the capability-item normalized store.
--
-- A discovered MCP server's surface is more than a blob: it is a set of *capability items* — the
-- `tools`, `resources`, `resource templates`, and `prompts` it advertises. To search, diff, and
-- render them (MCAT-9.x), each item is stored as its own normalized row here, alongside the
-- verbatim wire entry (`raw`) so nothing is lost.
--
-- Each row belongs to exactly one immutable discovery snapshot (`mcp_endpoint_versions`, MCAT-1.3,
-- V128) via `version_id`. As with V126's `mcp_endpoints.current_version_id`, the FK to that table
-- is intentionally NOT added here — `mcp_endpoint_versions` does not exist until V128, and Flyway
-- applies migrations in version order, so a V127 FK to a V128 table is impossible. V128 adds the
-- constraint once its table exists (FK ordering, see roadmap MCAT-1.3). Until then `version_id` is
-- a plain NOT NULL UUID: every capability item still belongs to a version, it is simply not yet
-- referentially enforced.
--
-- Field set follows the MCP server feature specs (2025-06-18):
--   tools     — https://modelcontextprotocol.io/specification/2025-06-18/server/tools
--   resources — https://modelcontextprotocol.io/specification/2025-06-18/server/resources
--   prompts   — https://modelcontextprotocol.io/specification/2025-06-18/server/prompts
-- The schema is deliberately tolerant of older (2025-03-26) servers, which omit `title` and
-- `outputSchema`: every type-specific column is nullable. The shape is a union across all four item
-- types, discriminated by `item_type`:
--   * tool              — `name`, `title?`, `description?`, `input_schema`, `output_schema?`, `annotations?`
--   * resource          — `name`, `title?`, `description?`, `uri`, `annotations?`
--   * resource_template — `name`, `title?`, `description?`, `uri_template`, `annotations?`
--   * prompt            — `name`, `title?`, `description?` (arguments live verbatim in `raw`)
-- Columns not applicable to a given `item_type` are simply left NULL; `raw` always holds the full
-- verbatim entry so no field is ever lost even if it lacks a promoted column.
--
-- Rows are children of an immutable snapshot, so they are write-once: there is no `updated_at`
-- (re-discovery produces a *new* version with a fresh set of items rather than mutating these).
--
-- Rollback notes: purely additive (one new table, its indexes, and comments). To roll back,
-- `DROP TABLE IF EXISTS apiome.mcp_capability_items CASCADE;` — this also drops the dependent indexes.

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS mcp_capability_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Owning discovery snapshot. FK to mcp_endpoint_versions(id) is added in V128 (MCAT-1.3) once
    -- that table exists; kept as a plain NOT NULL UUID here for FK ordering (see header).
    version_id UUID NOT NULL,

    -- Which kind of capability this row describes; discriminates the type-specific columns below.
    item_type VARCHAR(32) NOT NULL,

    -- Common identity fields. `name` is the programmatic identifier (required for every item type);
    -- `title` is the optional human-facing label introduced in 2025-06-18 (NULL on older servers).
    name VARCHAR(255) NOT NULL,
    title VARCHAR(255),
    description TEXT,

    -- Tool I/O schemas. `input_schema` is the tool's JSON Schema for arguments; `output_schema` is
    -- the optional structured-result schema added in 2025-06-18 (NULL on older servers / non-tools).
    input_schema JSONB,
    output_schema JSONB,

    -- Optional behavioural hints (tool/resource annotations: readOnlyHint, audience, priority, …).
    annotations JSONB,

    -- Resource addressing: `uri` for a concrete resource, `uri_template` (RFC 6570) for a template.
    uri TEXT,
    uri_template TEXT,

    -- The verbatim wire entry for this item, retained for full fidelity / lossless re-render.
    raw JSONB NOT NULL,

    -- Position of this item within its type's discovered list, preserving the server's ordering.
    ordinal INTEGER NOT NULL,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- item_type must be one of the four MCP capability kinds.
    CONSTRAINT mcp_capability_items_item_type_check
        CHECK (item_type IN ('tool', 'resource', 'resource_template', 'prompt')),

    -- Ordinals are list positions, so they are zero-or-greater.
    CONSTRAINT mcp_capability_items_ordinal_check
        CHECK (ordinal >= 0)
);

-- Render/diff a snapshot's surface: every item of a given type within a version, in one scan. This
-- btree also backs lookups on (version_id) alone (leftmost-prefix), so no separate version index.
CREATE INDEX IF NOT EXISTS idx_mcp_capability_items_version_type
    ON mcp_capability_items(version_id, item_type);

-- Resolve / autocomplete an item by its programmatic name across snapshots.
CREATE INDEX IF NOT EXISTS idx_mcp_capability_items_name
    ON mcp_capability_items(name);

-- Full-text search over capability items (MCAT-9.2). An expression GIN index on the English
-- tsvector of name + description; `to_tsvector('english', …)` with a constant config is IMMUTABLE,
-- so it is index-safe without a stored column or refresh triggers.
CREATE INDEX IF NOT EXISTS idx_mcp_capability_items_fts
    ON mcp_capability_items
    USING gin (to_tsvector('english', coalesce(name, '') || ' ' || coalesce(description, '')));

COMMENT ON TABLE mcp_capability_items IS 'Normalized tools/resources/resource_templates/prompts discovered per MCP endpoint version, queryable for search/diff/render (#3652, V2-MCP-15.2)';
COMMENT ON COLUMN mcp_capability_items.id IS 'Unique identifier for the capability item';
COMMENT ON COLUMN mcp_capability_items.version_id IS 'Owning mcp_endpoint_versions snapshot; FK added in V128 (MCAT-1.3) once that table exists';
COMMENT ON COLUMN mcp_capability_items.item_type IS 'Capability kind: tool, resource, resource_template, or prompt';
COMMENT ON COLUMN mcp_capability_items.name IS 'Programmatic identifier of the item (required for every item type)';
COMMENT ON COLUMN mcp_capability_items.title IS 'Optional human-facing label (2025-06-18+); NULL on older 2025-03-26 servers';
COMMENT ON COLUMN mcp_capability_items.description IS 'Optional free-text description of the item';
COMMENT ON COLUMN mcp_capability_items.input_schema IS 'Tool argument JSON Schema; NULL for non-tool items';
COMMENT ON COLUMN mcp_capability_items.output_schema IS 'Optional tool structured-result JSON Schema (2025-06-18+); NULL on older servers / non-tools';
COMMENT ON COLUMN mcp_capability_items.annotations IS 'Optional behavioural hints/annotations (e.g. readOnlyHint, audience, priority)';
COMMENT ON COLUMN mcp_capability_items.uri IS 'Resource URI; NULL for non-resource items';
COMMENT ON COLUMN mcp_capability_items.uri_template IS 'Resource-template URI Template (RFC 6570); NULL for non-template items';
COMMENT ON COLUMN mcp_capability_items.raw IS 'Verbatim wire entry for this item, retained for lossless fidelity';
COMMENT ON COLUMN mcp_capability_items.ordinal IS 'Zero-based position within its type''s discovered list, preserving server ordering';
COMMENT ON COLUMN mcp_capability_items.created_at IS 'Timestamp when the item row was recorded (rows are write-once, children of an immutable snapshot)';
