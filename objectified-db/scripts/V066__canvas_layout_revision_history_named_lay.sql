-- Canvas layout revision history (named layout saves)
-- Stores prior snapshots before each named-layout update for restore/version history.

SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS canvas_layout_revisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    canvas_layout_id UUID NOT NULL REFERENCES canvas_layouts(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    viewport JSONB,
    nodes JSONB,
    edges JSONB,
    grid_settings JSONB,
    minimap_settings JSONB,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT canvas_layout_revisions_unique_rev UNIQUE (canvas_layout_id, revision)
);

CREATE INDEX IF NOT EXISTS idx_canvas_layout_revisions_layout_id
    ON canvas_layout_revisions(canvas_layout_id);
CREATE INDEX IF NOT EXISTS idx_canvas_layout_revisions_created_at
    ON canvas_layout_revisions(created_at DESC);

COMMENT ON TABLE canvas_layout_revisions IS 'Point-in-time snapshots of canvas_layouts rows before named-layout updates; capped per layout in application code';
COMMENT ON COLUMN canvas_layout_revisions.revision IS 'Monotonic per canvas_layout_id; higher is newer snapshot of the prior state';
