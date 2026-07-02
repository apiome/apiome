-- External MCP Catalog (#3653, V2-MCP-15.3 / MCAT-1.3): version snapshots + change records.
--
-- Discovery is periodic (MCAT-7.x): every time the pipeline re-handshakes an endpoint and finds a
-- materially different surface, that result is frozen as one immutable snapshot here. This is the
-- table V126 (`mcp_endpoints.current_version_id`) and V127 (`mcp_capability_items.version_id`) were
-- both written to point at but could not yet reference — Flyway applies migrations in version order,
-- so neither could add a FK to a table that did not exist. V128 creates that table and, now that it
-- exists, retro-fits both deferred foreign keys (see the FK-ordering notes in V126/V127 headers).
--
-- `mcp_endpoint_versions` is the snapshot: the server's identity at discovery time (protocol,
-- name/title/version, instructions), its declared `capabilities` blob, and a `surface_fingerprint`
-- (a stable hash of the discovered surface) used to decide whether a new discovery actually changed
-- anything — and thus whether a new version row is warranted at all. The per-item normalized rows of
-- that surface live in `mcp_capability_items` (V127), children of this snapshot via `version_id`.
--
-- `mcp_version_changes` is the recorded diff: one row per item added / removed / modified relative to
-- the previous version, linked to the version that introduced the change. `detail` carries the
-- before/after payload (a removal has only `before`, an addition only `after`, a modification both).
--
-- Immutability (acceptance criterion). A snapshot — and its change records — are write-once: once a
-- discovery result is recorded it must never be edited. A re-discovery produces a *new* version with
-- a fresh fingerprint, never a mutation of an existing one (this is also why neither table carries an
-- `updated_at`). We enforce this at the database level with a BEFORE UPDATE trigger that raises, so
-- the rule holds regardless of which code path writes. DELETE is intentionally *not* blocked: the FK
-- chain from tenants -> mcp_endpoints is ON DELETE CASCADE, and a tenant/endpoint teardown must be
-- able to reap its versions; immutability concerns a row's *contents*, not the right to drop it
-- wholesale when its owner goes away.
--
-- Monotonic `version_seq` (acceptance criterion). `version_seq` is a per-endpoint counter assigned by
-- the discovery pipeline; `UNIQUE(endpoint_id, version_seq)` guarantees two snapshots of one endpoint
-- can never collide on a sequence number, and the `>= 1` check keeps it a positive ordinal. Strict
-- "next = max + 1" allocation is the application's responsibility (mirroring canvas_layout_revisions,
-- V066); the unique constraint is the backstop that makes a buggy double-assignment fail loudly.
--
-- Rollback notes: this migration adds two tables, their indexes, an immutability trigger function +
-- two triggers, and two foreign-key constraints on pre-existing tables. To roll back:
--   ALTER TABLE apiome.mcp_capability_items DROP CONSTRAINT IF EXISTS mcp_capability_items_version_fk;
--   ALTER TABLE apiome.mcp_endpoints       DROP CONSTRAINT IF EXISTS mcp_endpoints_current_version_fk;
--   DROP TABLE IF EXISTS apiome.mcp_version_changes CASCADE;
--   DROP TABLE IF EXISTS apiome.mcp_endpoint_versions CASCADE;
--   DROP FUNCTION IF EXISTS apiome.mcp_forbid_row_mutation();
-- (Dropping the constraints first leaves V126/V127's columns as the plain UUIDs they were before.)

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- mcp_endpoint_versions — immutable, tagged discovery snapshots (one per material surface change).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mcp_endpoint_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Owning endpoint; snapshots are reaped when the endpoint (or its tenant) is hard-deleted.
    endpoint_id UUID NOT NULL REFERENCES mcp_endpoints(id) ON DELETE CASCADE,

    -- Monotonic per-endpoint snapshot counter assigned by the discovery pipeline (1, 2, 3, …).
    version_seq INTEGER NOT NULL,

    -- Server identity at discovery time, from the MCP `initialize` result (all optional on the wire).
    protocol_version VARCHAR(64),
    server_name VARCHAR(255),
    server_title VARCHAR(255),
    server_version VARCHAR(128),

    -- Free-text usage guidance the server advertises in its `initialize` result.
    instructions TEXT,

    -- The server's declared capabilities object (tools/resources/prompts/logging/… toggles), verbatim.
    capabilities JSONB,

    -- Stable hash of the discovered surface; equal fingerprints mean "nothing changed, no new version".
    surface_fingerprint TEXT,

    -- When the discovery that produced this snapshot ran (distinct from when the row was persisted).
    discovered_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Two snapshots of the same endpoint can never share a sequence number. The btree backing this
    -- constraint also serves lookups/ordering on (endpoint_id) and (endpoint_id, version_seq).
    CONSTRAINT mcp_endpoint_versions_endpoint_seq_unique UNIQUE (endpoint_id, version_seq),

    -- version_seq is a positive ordinal.
    CONSTRAINT mcp_endpoint_versions_seq_check CHECK (version_seq >= 1)
);

-- Newest-first version history for an endpoint (timeline view / "what changed when").
CREATE INDEX IF NOT EXISTS idx_mcp_endpoint_versions_endpoint_discovered
    ON mcp_endpoint_versions(endpoint_id, discovered_at DESC);

COMMENT ON TABLE mcp_endpoint_versions IS 'Immutable, tagged discovery snapshots of an MCP endpoint''s surface; write-once (#3653, V2-MCP-15.3)';
COMMENT ON COLUMN mcp_endpoint_versions.id IS 'Unique identifier for the version snapshot';
COMMENT ON COLUMN mcp_endpoint_versions.endpoint_id IS 'Owning mcp_endpoints row; cascade-deleted with the endpoint/tenant';
COMMENT ON COLUMN mcp_endpoint_versions.version_seq IS 'Monotonic per-endpoint snapshot counter (1-based) assigned by the discovery pipeline';
COMMENT ON COLUMN mcp_endpoint_versions.protocol_version IS 'MCP protocol version reported in the initialize result (e.g. 2025-06-18)';
COMMENT ON COLUMN mcp_endpoint_versions.server_name IS 'Programmatic server name from the initialize result';
COMMENT ON COLUMN mcp_endpoint_versions.server_title IS 'Optional human-facing server title (2025-06-18+); NULL on older servers';
COMMENT ON COLUMN mcp_endpoint_versions.server_version IS 'Server implementation version string from the initialize result';
COMMENT ON COLUMN mcp_endpoint_versions.instructions IS 'Free-text usage guidance advertised by the server';
COMMENT ON COLUMN mcp_endpoint_versions.capabilities IS 'Server-declared capabilities object (verbatim) from the initialize result';
COMMENT ON COLUMN mcp_endpoint_versions.surface_fingerprint IS 'Stable hash of the discovered surface; equal fingerprints mean no new version is needed';
COMMENT ON COLUMN mcp_endpoint_versions.discovered_at IS 'When the discovery that produced this snapshot ran';
COMMENT ON COLUMN mcp_endpoint_versions.created_at IS 'Timestamp when the snapshot row was persisted (rows are write-once / immutable)';

-- ---------------------------------------------------------------------------------------------------
-- mcp_version_changes — the recorded diff: items added/removed/modified by a given version.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mcp_version_changes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- The snapshot that introduced this change; reaped with its version.
    version_id UUID NOT NULL REFERENCES mcp_endpoint_versions(id) ON DELETE CASCADE,

    -- Direction of the change relative to the previous version.
    change_type VARCHAR(32) NOT NULL,

    -- What kind of thing changed (tool/resource/resource_template/prompt, or a server-level field such
    -- as 'instructions'). Left as a plain VARCHAR — unlike capability items, a change can also describe
    -- server metadata, so this is intentionally not constrained to the four capability kinds.
    item_type VARCHAR(64) NOT NULL,

    -- Identifier of the changed item (e.g. the tool/resource name, or the server field name).
    item_name VARCHAR(255) NOT NULL,

    -- Before/after payload: a removal carries `before`, an addition `after`, a modification both.
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- change_type must be one of the three diff directions.
    CONSTRAINT mcp_version_changes_change_type_check
        CHECK (change_type IN ('added', 'removed', 'modified'))
);

-- Render a version's full diff in one scan; the leftmost prefix also serves lookups on (version_id).
CREATE INDEX IF NOT EXISTS idx_mcp_version_changes_version_change_type
    ON mcp_version_changes(version_id, change_type);

-- Trace a single item's history across versions (e.g. "when did tool X change?").
CREATE INDEX IF NOT EXISTS idx_mcp_version_changes_item
    ON mcp_version_changes(item_type, item_name);

COMMENT ON TABLE mcp_version_changes IS 'Per-item diff (added/removed/modified) introduced by an mcp_endpoint_versions snapshot; write-once (#3653, V2-MCP-15.3)';
COMMENT ON COLUMN mcp_version_changes.id IS 'Unique identifier for the change record';
COMMENT ON COLUMN mcp_version_changes.version_id IS 'The mcp_endpoint_versions snapshot that introduced this change';
COMMENT ON COLUMN mcp_version_changes.change_type IS 'Diff direction: added, removed, or modified';
COMMENT ON COLUMN mcp_version_changes.item_type IS 'Kind of changed item (tool/resource/resource_template/prompt, or a server-level field)';
COMMENT ON COLUMN mcp_version_changes.item_name IS 'Identifier of the changed item (item name, or server field name)';
COMMENT ON COLUMN mcp_version_changes.detail IS 'Before/after payload: removal has before, addition has after, modification has both';
COMMENT ON COLUMN mcp_version_changes.created_at IS 'Timestamp when the change record was persisted (rows are write-once / immutable)';

-- ---------------------------------------------------------------------------------------------------
-- Immutability enforcement: snapshots and their change records are write-once. A BEFORE UPDATE
-- trigger rejects any in-place edit; DELETE is left to the FK cascades so owner teardown still works.
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION mcp_forbid_row_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Table %.% is immutable; rows are write-once and cannot be updated',
        TG_TABLE_SCHEMA, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_mcp_endpoint_versions_immutable ON mcp_endpoint_versions;
CREATE TRIGGER trigger_mcp_endpoint_versions_immutable
    BEFORE UPDATE ON mcp_endpoint_versions
    FOR EACH ROW
    EXECUTE FUNCTION mcp_forbid_row_mutation();

DROP TRIGGER IF EXISTS trigger_mcp_version_changes_immutable ON mcp_version_changes;
CREATE TRIGGER trigger_mcp_version_changes_immutable
    BEFORE UPDATE ON mcp_version_changes
    FOR EACH ROW
    EXECUTE FUNCTION mcp_forbid_row_mutation();

COMMENT ON FUNCTION mcp_forbid_row_mutation() IS 'Trigger guard that rejects UPDATEs, enforcing write-once immutability on MCP version/change rows (#3653)';

-- ---------------------------------------------------------------------------------------------------
-- Retro-fit the foreign keys V126 and V127 deferred until this table existed (FK ordering).
-- ---------------------------------------------------------------------------------------------------

-- V126: mcp_endpoints.current_version_id -> the latest snapshot. SET NULL so dropping the pointed-at
-- version (rare; normally only via endpoint teardown) does not also delete the endpoint row.
ALTER TABLE mcp_endpoints
    DROP CONSTRAINT IF EXISTS mcp_endpoints_current_version_fk;
ALTER TABLE mcp_endpoints
    ADD CONSTRAINT mcp_endpoints_current_version_fk
    FOREIGN KEY (current_version_id) REFERENCES mcp_endpoint_versions(id) ON DELETE SET NULL;

-- V127: mcp_capability_items.version_id -> its owning snapshot. CASCADE so a version's normalized
-- items are reaped with it (they have no meaning apart from their snapshot).
ALTER TABLE mcp_capability_items
    DROP CONSTRAINT IF EXISTS mcp_capability_items_version_fk;
ALTER TABLE mcp_capability_items
    ADD CONSTRAINT mcp_capability_items_version_fk
    FOREIGN KEY (version_id) REFERENCES mcp_endpoint_versions(id) ON DELETE CASCADE;
