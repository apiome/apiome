-- Canvas layout PNG snapshot (thumbnail) stored with named layouts for UI reference

SET search_path TO apiome, public;

ALTER TABLE canvas_layouts
    ADD COLUMN IF NOT EXISTS snapshot_image BYTEA;

COMMENT ON COLUMN canvas_layouts.snapshot_image IS 'Optional PNG bytes captured from the canvas when the layout was saved; used for thumbnails and reference';
