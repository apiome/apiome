-- Drop unused JSONB GIN indexes to speed up imports (import performance).
--
-- Problem
-- -------
-- Imports insert one row per property into apiome.properties, one per class into apiome.classes,
-- and one per class-property (recursively, the highest-volume insert) into apiome.class_properties.
-- Each of these tables carries a GIN index over a JSONB column:
--
--   apiome.properties.data         -> idx_properties_data_gin        (V004)
--   apiome.classes.schema          -> idx_classes_schema            (V005)
--   apiome.class_properties.data   -> idx_class_properties_data     (V005)
--   apiome.classes.canvas_metadata -> idx_classes_canvas_metadata   (V013)
--
-- GIN index maintenance on INSERT is far more expensive than b-tree: every inserted JSONB value
-- is tokenized into many keys, each inserted into the index's posting tree, and with the default
-- fastupdate=on the pending list is periodically flushed in costly bursts. On lower-power cloud
-- instances with slow I/O this dominates import time, especially for idx_class_properties_data
-- (one maintenance hit per property per class).
--
-- Why it is safe to drop these
-- ----------------------------
-- A GIN index on a JSONB column only helps containment / key-existence / json-path queries
-- (@>, <@, ?, ?|, ?&, @?, @@). A full audit of apiome-rest, apiome-ui, apiome-browse,
-- apiome-mcp, and the SQL migrations/views found NO such query against properties.data,
-- classes.schema, class_properties.data, or classes.canvas_metadata — these columns are only ever
-- written and read back whole (SELECT data / schema ... then JSON.parse in app code). MCP spec
-- search uses a separate maintained tsvector on versions (V101/V102), not these indexes. So the
-- indexes are pure write-amplification with no read benefit.
--
-- Reversibility
-- -------------
-- If a JSONB containment/search feature is added later, recreate the specific index it needs,
-- preferably without blocking writes:
--   CREATE INDEX CONCURRENTLY idx_class_properties_data ON apiome.class_properties USING GIN (data);
-- (CONCURRENTLY must run outside a migration transaction.) Consider WITH (fastupdate = off) or a
-- jsonb_path_ops GIN variant if write latency matters more than query generality.

SET search_path TO apiome, public;

DROP INDEX IF EXISTS apiome.idx_properties_data_gin;
DROP INDEX IF EXISTS apiome.idx_classes_schema;
DROP INDEX IF EXISTS apiome.idx_class_properties_data;
DROP INDEX IF EXISTS apiome.idx_classes_canvas_metadata;
