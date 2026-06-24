-- Granular RBAC: roles and role_permissions (#3611, RC1-1.1)
--
-- Replaces the binary "tenant member vs. tenant administrator" model with named roles plus a
-- resource x action permission grid. Built-in roles (Owner / Admin / Editor / Viewer) are seeded
-- per tenant and are immutable; tenants may add custom roles (e.g. "Release Manager"). The grid is
-- presence-based: a row in role_permissions means the (resource, action) pair is ALLOWED for that
-- role; the absence of a row means denied. objectified-rest's central permission guard reads this
-- grid on every mutating route (see objectified-rest/src/app/permissions.py).
--
-- Resources: projects, versions, classes, properties, paths, types, imports, members, api_keys, billing
-- Actions:   view, create, edit, delete, publish
SET search_path TO odb, public;

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS roles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    slug VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    description TEXT,
    is_builtin BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, slug)
);

CREATE INDEX IF NOT EXISTS idx_roles_tenant_id ON roles(tenant_id);

CREATE TABLE IF NOT EXISTS role_permissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    resource VARCHAR(48) NOT NULL,
    action VARCHAR(24) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (role_id, resource, action)
);

CREATE INDEX IF NOT EXISTS idx_role_permissions_role_id ON role_permissions(role_id);

COMMENT ON TABLE roles IS 'Tenant-scoped RBAC roles; built-in Owner/Admin/Editor/Viewer plus custom roles (#3611)';
COMMENT ON COLUMN roles.slug IS 'Stable machine identifier, unique per tenant (e.g. owner, admin, editor, viewer, release-manager)';
COMMENT ON COLUMN roles.is_builtin IS 'True for the four immutable seeded roles; custom roles are false';
COMMENT ON TABLE role_permissions IS 'Presence-based grant grid: a row means (resource, action) is allowed for the role (#3611)';
COMMENT ON COLUMN role_permissions.resource IS 'One of: projects, versions, classes, properties, paths, types, imports, members, api_keys, billing';
COMMENT ON COLUMN role_permissions.action IS 'One of: view, create, edit, delete, publish';

-- updated_at maintenance for roles
CREATE OR REPLACE FUNCTION update_roles_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_roles_updated_at ON roles;
CREATE TRIGGER trigger_update_roles_updated_at
    BEFORE UPDATE ON roles
    FOR EACH ROW
    EXECUTE FUNCTION update_roles_updated_at();

-- ---------------------------------------------------------------------------
-- Built-in role seeding
-- ---------------------------------------------------------------------------
-- Idempotent: (re)creates the four built-in roles for a tenant and rewrites their permission grids
-- to the canonical defaults. Custom roles and their permissions are never touched. Called for every
-- existing tenant by this migration and on-demand by objectified-rest when a tenant's roles are
-- first read (so tenants created before/after this migration always have built-ins).

CREATE OR REPLACE FUNCTION odb.seed_builtin_roles(p_tenant UUID)
RETURNS void AS $$
DECLARE
    v_owner UUID;
    v_admin UUID;
    v_editor UUID;
    v_viewer UUID;
    -- Resources that behave like editable content (full CRUD for Editor).
    content_resources TEXT[] := ARRAY['projects','versions','classes','properties','paths','imports','api_keys'];
    all_resources TEXT[] := ARRAY['projects','versions','classes','properties','paths','types','imports','members','api_keys','billing'];
    r TEXT;
BEGIN
    -- Upsert the four built-in roles.
    INSERT INTO odb.roles (tenant_id, slug, name, description, is_builtin) VALUES
        (p_tenant, 'owner',  'Owner',  'Full control of the tenant, including billing and members.', true),
        (p_tenant, 'admin',  'Admin',  'Manage members, roles, and all content; no billing administration.', true),
        (p_tenant, 'editor', 'Editor', 'Create and edit content, but cannot publish, manage members, or change settings.', true),
        (p_tenant, 'viewer', 'Viewer', 'Read-only access to the tenant.', true)
    ON CONFLICT (tenant_id, slug) DO UPDATE
        SET name = EXCLUDED.name,
            description = EXCLUDED.description,
            is_builtin = true;

    SELECT id INTO v_owner  FROM odb.roles WHERE tenant_id = p_tenant AND slug = 'owner';
    SELECT id INTO v_admin  FROM odb.roles WHERE tenant_id = p_tenant AND slug = 'admin';
    SELECT id INTO v_editor FROM odb.roles WHERE tenant_id = p_tenant AND slug = 'editor';
    SELECT id INTO v_viewer FROM odb.roles WHERE tenant_id = p_tenant AND slug = 'viewer';

    -- Rewrite built-in grids from scratch (idempotent / self-healing).
    DELETE FROM odb.role_permissions WHERE role_id IN (v_owner, v_admin, v_editor, v_viewer);

    -- Owner: every action on every resource, plus version publishing.
    FOREACH r IN ARRAY all_resources LOOP
        INSERT INTO odb.role_permissions (role_id, resource, action)
        SELECT v_owner, r, a FROM unnest(ARRAY['view','create','edit','delete']) AS a;
    END LOOP;
    INSERT INTO odb.role_permissions (role_id, resource, action) VALUES (v_owner, 'versions', 'publish');

    -- Admin: same as Owner but billing is view-only (billing administration is Owner-only).
    FOREACH r IN ARRAY all_resources LOOP
        IF r = 'billing' THEN
            INSERT INTO odb.role_permissions (role_id, resource, action) VALUES (v_admin, 'billing', 'view');
        ELSE
            INSERT INTO odb.role_permissions (role_id, resource, action)
            SELECT v_admin, r, a FROM unnest(ARRAY['view','create','edit','delete']) AS a;
        END IF;
    END LOOP;
    INSERT INTO odb.role_permissions (role_id, resource, action) VALUES (v_admin, 'versions', 'publish');

    -- Editor: full CRUD on content resources; view-only on governance resources; no publish.
    FOREACH r IN ARRAY content_resources LOOP
        INSERT INTO odb.role_permissions (role_id, resource, action)
        SELECT v_editor, r, a FROM unnest(ARRAY['view','create','edit','delete']) AS a;
    END LOOP;
    INSERT INTO odb.role_permissions (role_id, resource, action)
    SELECT v_editor, res, 'view' FROM unnest(ARRAY['types','members','billing']) AS res;

    -- Viewer: view-only on every resource.
    FOREACH r IN ARRAY all_resources LOOP
        INSERT INTO odb.role_permissions (role_id, resource, action) VALUES (v_viewer, r, 'view');
    END LOOP;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION odb.seed_builtin_roles(UUID) IS 'Idempotently (re)seed the four built-in roles and their canonical permission grids for a tenant (#3611)';

-- Seed every existing tenant.
DO $$
DECLARE
    t RECORD;
BEGIN
    FOR t IN SELECT id FROM odb.tenants LOOP
        PERFORM odb.seed_builtin_roles(t.id);
    END LOOP;
END;
$$;
