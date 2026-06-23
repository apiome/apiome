-- P-03 / #2642: Paths designer React Flow canvas (presentation layer only; OpenAPI paths remain SoT)
-- ROLLBACK: DROP TABLE IF EXISTS odb.version_path_canvas;

SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS version_path_canvas (
  version_path_id UUID NOT NULL PRIMARY KEY REFERENCES odb.version_path(id) ON DELETE CASCADE,
  canvas JSONB NOT NULL DEFAULT '{"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_version_path_canvas_updated_at
  ON odb.version_path_canvas(updated_at);

COMMENT ON TABLE odb.version_path_canvas IS
  'Paths tab React Flow layout JSON per version_path; semantic paths/ops live in version_path / path_operation (#2642)';

COMMENT ON COLUMN odb.version_path_canvas.canvas IS
  'Canonical shape: { "nodes": [], "edges": [], "viewport": { "x", "y", "zoom" } }';
