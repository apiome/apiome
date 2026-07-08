-- Cataloger notes & annotations — per-endpoint human commentary (#4666, V2-MCP-36.3 / MCAT-22.3).
--
-- Problem: catalogers learn context, caveats, and recommendations about a server that have nowhere
-- to live and get lost.
--
-- Solution: a lightweight ``mcp_endpoint_notes`` table that stores tenant-scoped human notes on an
-- endpoint, authored by catalog users and kept separate from server-reported discovery data. Each
-- row is one note with author/time audit; notes cascade with their tenant and endpoint.
--
-- Rollback notes: purely additive. To roll back:
--   DROP TABLE IF EXISTS apiome.mcp_endpoint_notes;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS mcp_endpoint_notes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Tenant scope — cascade when the tenant is removed.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- The endpoint this note annotates — cascade when the endpoint is removed.
    endpoint_id UUID NOT NULL REFERENCES mcp_endpoints(id) ON DELETE CASCADE,

    -- Human-authored commentary (never mixed into discovered surface data).
    body TEXT NOT NULL,

    -- Author audit — RESTRICT on user delete so authorship is preserved while notes exist.
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT mcp_endpoint_notes_body_nonempty CHECK (char_length(trim(body)) > 0)
);

-- List notes for an endpoint (newest first).
CREATE INDEX IF NOT EXISTS idx_mcp_endpoint_notes_endpoint
    ON mcp_endpoint_notes (tenant_id, endpoint_id, created_at DESC);

COMMENT ON TABLE mcp_endpoint_notes IS
    'Per-endpoint cataloger commentary, tenant-scoped and separate from server-reported data '
    '(MCAT-22.3). One row per note; author/time audit on create and update.';
COMMENT ON COLUMN mcp_endpoint_notes.body IS
    'Human-authored note text — cataloger commentary, never merged into discovered surface data';
COMMENT ON COLUMN mcp_endpoint_notes.created_by IS
    'User who authored the note (audit trail; RESTRICT while notes exist)';
COMMENT ON COLUMN mcp_endpoint_notes.updated_by IS
    'User who last edited the note (NULL when never edited after creation)';
