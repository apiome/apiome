-- Preserve pre-delete enabled state for safe restore (#2981)
-- Adds pre_delete_enabled to record whether a project was enabled before soft-deletion
-- so that restore can replay the original value instead of always forcing enabled=true.
SET search_path TO apiome, public;

ALTER TABLE apiome.projects
    ADD COLUMN IF NOT EXISTS pre_delete_enabled BOOLEAN;

COMMENT ON COLUMN apiome.projects.pre_delete_enabled IS
    'Stores the enabled state captured at soft-delete time so that restore can replay it instead of always forcing enabled=true';
