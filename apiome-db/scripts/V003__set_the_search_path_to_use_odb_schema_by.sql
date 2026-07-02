-- Set the search path to use apiome schema by default
SET search_path TO apiome, public;

DROP TABLE IF EXISTS versions CASCADE;

-- Versions table: Stores versions of projects
CREATE TABLE versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    creator_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    version_id VARCHAR(255) NOT NULL,
    description TEXT,
    change_log TEXT,
    enabled BOOLEAN NOT NULL DEFAULT true,
    published BOOLEAN NOT NULL DEFAULT false,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    published_at TIMESTAMP WITH TIME ZONE,
    UNIQUE(project_id, version_id)
);

-- Table comment
COMMENT ON TABLE versions IS 'Stores version information for projects, including semantic versioning, publication status, and change tracking';

-- Column comments
COMMENT ON COLUMN versions.id IS 'Unique identifier for the version record';
COMMENT ON COLUMN versions.project_id IS 'Foreign key reference to the parent project (cascades on deletion)';
COMMENT ON COLUMN versions.creator_id IS 'Foreign key reference to the user who created this version (restricts deletion)';
COMMENT ON COLUMN versions.version_id IS 'Semantic version identifier (e.g., "1.0.0", "2.1.3")';
COMMENT ON COLUMN versions.description IS 'Optional text description of what this version represents';
COMMENT ON COLUMN versions.change_log IS 'Optional text documenting the changes made in this version';
COMMENT ON COLUMN versions.enabled IS 'Flag indicating if this version is currently active/enabled';
COMMENT ON COLUMN versions.published IS 'Flag indicating if this version is publicly available';
COMMENT ON COLUMN versions.deleted_at IS 'Soft deletion timestamp (NULL if not deleted)';
COMMENT ON COLUMN versions.created_at IS 'Timestamp when this version record was created';
COMMENT ON COLUMN versions.updated_at IS 'Timestamp when this version record was last modified';
COMMENT ON COLUMN versions.published_at IS 'Timestamp when this version was published (NULL if unpublished)';

-- Indices for performance optimization
CREATE INDEX idx_versions_project_id ON versions(project_id);
CREATE INDEX idx_versions_creator_id ON versions(creator_id);
CREATE INDEX idx_versions_enabled ON versions(enabled) WHERE deleted_at IS NULL;
CREATE INDEX idx_versions_published ON versions(published) WHERE deleted_at IS NULL;
CREATE INDEX idx_versions_deleted_at ON versions(deleted_at);
CREATE INDEX idx_versions_created_at ON versions(created_at);
CREATE INDEX idx_versions_published_at ON versions(published_at) WHERE published_at IS NOT NULL;

