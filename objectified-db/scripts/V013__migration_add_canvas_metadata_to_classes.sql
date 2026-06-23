-- Migration: Add canvas_metadata to classes table
-- Purpose: Store canvas positioning and styling on a per-class basis
-- Note: This field is for UI purposes only and should NOT be included in
--       code generation or schema exports

SET search_path TO odb, public;

-- Add canvas_metadata column to classes table
ALTER TABLE classes
ADD COLUMN IF NOT EXISTS canvas_metadata JSONB DEFAULT NULL;

-- Add comment explaining the column's purpose
COMMENT ON COLUMN classes.canvas_metadata IS
'UI-only metadata for canvas positioning and styling. Contains position (x, y),
dimensions (width, height), and visual styling. This field is excluded from
code generation and schema exports to keep the class schema pure.

Example structure:
{
  "position": { "x": 100, "y": 200 },
  "dimensions": { "width": 250, "height": null },
  "style": {
    "backgroundColor": "#ffffff",
    "borderColor": "#3b82f6",
    "collapsed": false,
    "zIndex": 1
  },
  "group": null
}';

-- Create GIN index for efficient JSONB queries on canvas_metadata
CREATE INDEX IF NOT EXISTS idx_classes_canvas_metadata
ON classes USING GIN (canvas_metadata)
WHERE canvas_metadata IS NOT NULL;

-- Create index for position queries (commonly used for canvas rendering)
CREATE INDEX IF NOT EXISTS idx_classes_canvas_position
ON classes ((canvas_metadata->'position'))
WHERE canvas_metadata IS NOT NULL AND canvas_metadata->'position' IS NOT NULL;

