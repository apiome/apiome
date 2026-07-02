-- Canvas Layout Table
-- Stores canvas layout information (node positions, zoom, pan, etc.) on a per-version basis
-- Allows users to persist and restore their visual layout when working with schema diagrams

SET search_path TO apiome, public;

DROP TABLE IF EXISTS apiome.canvas_layouts CASCADE;
DROP INDEX IF EXISTS idx_canvas_layouts_version_id;
DROP INDEX IF EXISTS idx_canvas_layouts_user_id;
DROP INDEX IF EXISTS idx_canvas_layouts_created_at;
DROP INDEX IF EXISTS idx_canvas_layouts_updated_at;

-- Canvas Layouts table: Stores canvas layout state for each version
CREATE TABLE canvas_layouts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,  -- NULL for shared/default layouts
    name VARCHAR(255),  -- Optional name for saved layouts (e.g., "Default", "Presentation View")
    is_default BOOLEAN NOT NULL DEFAULT false,  -- Whether this is the default layout for the version
    viewport JSONB,  -- Viewport state: { x, y, zoom }
    nodes JSONB,  -- Node positions and dimensions: [{ id, position: { x, y }, dimensions: { width, height }, collapsed, ... }]
    edges JSONB,  -- Edge routing information: [{ id, sourceHandle, targetHandle, waypoints, ... }]
    groups JSONB,  -- Group definitions: [{ id, name, nodeIds, position, dimensions, color, ... }]
    grid_settings JSONB,  -- Grid configuration: { enabled, size, snapToGrid, showGrid }
    minimap_settings JSONB,  -- Minimap configuration: { enabled, position, size }
    metadata JSONB,  -- Additional layout metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Partial unique index to ensure only one default layout per version per user
CREATE UNIQUE INDEX idx_canvas_layouts_unique_default
    ON canvas_layouts(version_id, user_id)
    WHERE is_default = true;

-- Indices for canvas_layouts table
CREATE INDEX idx_canvas_layouts_version_id ON canvas_layouts(version_id);
CREATE INDEX idx_canvas_layouts_user_id ON canvas_layouts(user_id);
CREATE INDEX idx_canvas_layouts_is_default ON canvas_layouts(is_default) WHERE is_default = true;
CREATE INDEX idx_canvas_layouts_created_at ON canvas_layouts(created_at);
CREATE INDEX idx_canvas_layouts_updated_at ON canvas_layouts(updated_at);

-- Add table and column comments
COMMENT ON TABLE canvas_layouts IS 'Stores canvas layout state (positions, viewport, groups) for schema visualization on a per-version basis';
COMMENT ON COLUMN canvas_layouts.id IS 'Unique identifier for the canvas layout record';
COMMENT ON COLUMN canvas_layouts.version_id IS 'Reference to the version this layout belongs to';
COMMENT ON COLUMN canvas_layouts.user_id IS 'Reference to the user who owns this layout (NULL for shared/default layouts)';
COMMENT ON COLUMN canvas_layouts.name IS 'Optional name for the saved layout (e.g., "Default", "Presentation View", "Compact")';
COMMENT ON COLUMN canvas_layouts.is_default IS 'Whether this is the default layout loaded when opening the version';
COMMENT ON COLUMN canvas_layouts.viewport IS 'Viewport state including pan position and zoom level: { x, y, zoom }';
COMMENT ON COLUMN canvas_layouts.nodes IS 'Array of node positions and visual states: [{ id, position: { x, y }, dimensions, collapsed, ... }]';
COMMENT ON COLUMN canvas_layouts.edges IS 'Array of edge routing information: [{ id, sourceHandle, targetHandle, waypoints, ... }]';
COMMENT ON COLUMN canvas_layouts.groups IS 'Array of visual group containers: [{ id, name, description, color, nodeIds: [...], position: { x, y }, dimensions: { width, height } }]';
COMMENT ON COLUMN canvas_layouts.grid_settings IS 'Grid configuration: { enabled, size, snapToGrid, showGrid }';
COMMENT ON COLUMN canvas_layouts.minimap_settings IS 'Minimap configuration: { enabled, position, size }';
COMMENT ON COLUMN canvas_layouts.metadata IS 'Additional layout metadata and custom settings';
COMMENT ON COLUMN canvas_layouts.created_at IS 'Timestamp when this layout was created';
COMMENT ON COLUMN canvas_layouts.updated_at IS 'Timestamp when this layout was last modified';

-- Function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_canvas_layouts_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to automatically update updated_at
CREATE TRIGGER trigger_update_canvas_layouts_updated_at
    BEFORE UPDATE ON canvas_layouts
    FOR EACH ROW
    EXECUTE FUNCTION update_canvas_layouts_updated_at();

