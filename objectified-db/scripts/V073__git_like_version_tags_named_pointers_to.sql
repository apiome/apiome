-- Git-like version tags: named pointers to a schema revision (versions.id)
SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS version_tags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    message TEXT,
    channel VARCHAR(64),
    immutable BOOLEAN NOT NULL DEFAULT false,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT version_tags_project_name_unique UNIQUE (project_id, name)
);

CREATE INDEX IF NOT EXISTS idx_version_tags_project_id ON version_tags(project_id);
CREATE INDEX IF NOT EXISTS idx_version_tags_version_id ON version_tags(version_id);

COMMENT ON TABLE version_tags IS 'Named tag pointing at a version row (schema revision); analogous to git tags';
COMMENT ON COLUMN version_tags.version_id IS 'Target schema revision (versions.id)';
COMMENT ON COLUMN version_tags.channel IS 'Optional release channel label (e.g. stable, beta)';
COMMENT ON COLUMN version_tags.immutable IS 'When true, tag cannot be moved or deleted via API';
