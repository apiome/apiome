-- Granular RBAC: per-member role assignments (#3611, RC1-1.1)
--
-- Maps a (tenant, user) to a role. A user has at most one role per tenant (the design models a
-- single effective role per member; group/SSO-driven multi-role mapping is a later ticket). The
-- legacy odb.tenant_administrators table is retained as the authoritative "full access" signal for
-- backward compatibility — objectified-rest's guard treats any tenant_administrators row as Owner.
--
-- Backfill: existing administrators are assigned the built-in Owner role; existing non-admin members
-- are assigned the built-in Editor role (preserving the pre-RBAC behaviour where any member could
-- create and edit content but not publish or administer the tenant).
SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS tenant_user_roles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_tenant_user_roles_tenant_id ON tenant_user_roles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_user_roles_user_id ON tenant_user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_tenant_user_roles_role_id ON tenant_user_roles(role_id);

COMMENT ON TABLE tenant_user_roles IS 'Assigns one RBAC role per (tenant, user); read by the central permission guard (#3611)';

CREATE OR REPLACE FUNCTION update_tenant_user_roles_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_tenant_user_roles_updated_at ON tenant_user_roles;
CREATE TRIGGER trigger_update_tenant_user_roles_updated_at
    BEFORE UPDATE ON tenant_user_roles
    FOR EACH ROW
    EXECUTE FUNCTION update_tenant_user_roles_updated_at();

-- Backfill: administrators -> Owner.
INSERT INTO odb.tenant_user_roles (tenant_id, user_id, role_id)
SELECT ta.tenant_id, ta.user_id, r.id
FROM odb.tenant_administrators ta
JOIN odb.roles r ON r.tenant_id = ta.tenant_id AND r.slug = 'owner'
ON CONFLICT (tenant_id, user_id) DO NOTHING;

-- Backfill: non-admin members -> Editor.
INSERT INTO odb.tenant_user_roles (tenant_id, user_id, role_id)
SELECT tu.tenant_id, tu.user_id, r.id
FROM odb.tenant_users tu
JOIN odb.roles r ON r.tenant_id = tu.tenant_id AND r.slug = 'editor'
WHERE NOT EXISTS (
    SELECT 1 FROM odb.tenant_administrators ta
    WHERE ta.tenant_id = tu.tenant_id AND ta.user_id = tu.user_id
)
ON CONFLICT (tenant_id, user_id) DO NOTHING;
