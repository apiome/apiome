-- Set the search path to use odb schema by default
SET search_path TO odb, public;

DROP TABLE IF EXISTS projects CASCADE;

-- Projects table: Stores projects owned by tenants and created by users
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    creator_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    slug VARCHAR(255) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, slug)
);

-- Add table and column comments for projects
COMMENT ON TABLE projects IS 'Projects owned by tenants and created by users';
COMMENT ON COLUMN projects.tenant_id IS 'The tenant that owns this project';
COMMENT ON COLUMN projects.creator_id IS 'The user who created this project';
COMMENT ON COLUMN projects.slug IS 'URL-friendly identifier, unique within the tenant';

-- Indices for projects table
CREATE INDEX idx_projects_tenant_id ON projects(tenant_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_projects_creator_id ON projects(creator_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_projects_enabled ON projects(enabled) WHERE deleted_at IS NULL;
CREATE INDEX idx_projects_deleted_at ON projects(deleted_at) WHERE deleted_at IS NOT NULL;
CREATE INDEX idx_projects_created_at ON projects(created_at);
CREATE INDEX idx_projects_name ON projects(name) WHERE deleted_at IS NULL;
CREATE INDEX idx_projects_slug ON projects(tenant_id, slug) WHERE deleted_at IS NULL;
CREATE INDEX idx_projects_tenant_creator ON projects(tenant_id, creator_id) WHERE deleted_at IS NULL;
