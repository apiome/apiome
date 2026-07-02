-- Granular RBAC: member lifecycle status + platform-admin plane (#3611, RC1-1.1)
--
-- 1. Adds a lifecycle status to tenant_users so members can be invited (pending), suspended, or
--    reinstated without losing their role/history. Suspended members are denied tenant access by the
--    REST auth layer (apiome-rest user_has_tenant_access).
--
-- 2. Adds platform_administrators: a plane separate from tenant administration. A platform admin acts
--    across tenants (support / compliance overrides) and is audited as source='admin'. This is distinct
--    from apiome.tenant_administrators (tenant-scoped Owners/Admins).
SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------
-- Member lifecycle status
-- ---------------------------------------------------------------------------
ALTER TABLE tenant_users
    ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'active';

-- Guard against unexpected values; 'active' | 'pending' | 'suspended'.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'tenant_users_status_check'
    ) THEN
        ALTER TABLE tenant_users
            ADD CONSTRAINT tenant_users_status_check
            CHECK (status IN ('active', 'pending', 'suspended'));
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_tenant_users_status ON tenant_users(tenant_id, status);

COMMENT ON COLUMN tenant_users.status IS 'Member lifecycle: active (default), pending (invited, not yet accepted), suspended (access blocked) (#3611)';

-- ---------------------------------------------------------------------------
-- Platform-admin plane
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS platform_administrators (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    note TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS idx_platform_administrators_user_id ON platform_administrators(user_id);

COMMENT ON TABLE platform_administrators IS 'Platform-admin plane: users who may act across tenants; separate from tenant_administrators (#3611)';
COMMENT ON COLUMN platform_administrators.note IS 'Why this user was granted platform-admin (for audit)';
