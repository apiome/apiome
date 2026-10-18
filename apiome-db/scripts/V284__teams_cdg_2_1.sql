-- Teams model and RBAC resource — CDG-2.1 (#5960).
--
-- Routing a finding needs a durable "who". A spec's contact e-mail is not one, and neither is a
-- single user: people move, go on leave and change jobs, while the team that owns a service does
-- not. This migration adds the group that CDG-2.2 (entity ownership), CDG-2.3 (owner routing) and
-- EID-2 (SCIM group mapping) all key on. It is the only group concept in the schema.
--
--   teams        — a named group inside one tenant, with the links a migrating team expects
--                  (contact e-mail, chat channel, on-call schedule, documentation).
--   team_members — who is on a team, as `lead` or `member`; unique per (team, user).
--
-- Four rules are kept by the database rather than by the application:
--
--   1. **A slug is a handle.** It is shaped like a consumer slug (lowercase, hyphenated, no
--      slash) and unique among a tenant's *live* teams, so retiring `payments` frees the name.
--      Kong tags (`owner:payments`) and the `x-apiome-owner` extension name teams by slug.
--
--   2. **Deletes are soft.** `deleted_at` hides a team from reads; its rows stay, so an audit
--      entry or a past notification that names it still resolves.
--
--   3. **Members must be tenant members.** A BEFORE INSERT/UPDATE trigger refuses a
--      `team_members` row whose user has no `tenant_users` row in the team's tenant.
--
--   4. **Leaving the tenant leaves every team, in the same transaction.** An AFTER DELETE trigger
--      on `tenant_users` removes the user's `team_members` rows for that tenant. Four writers
--      delete `tenant_users` rows (apiome-rest, the UI's member actions, the admin portal and the
--      apiome-db CLI); a trigger covers all of them, including ones added later.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TRIGGER IF EXISTS trg_tenant_users_leave_teams ON apiome.tenant_users;
--   DROP FUNCTION IF EXISTS apiome.tenant_users_leave_teams();
--   DROP TABLE IF EXISTS apiome.team_members;
--   DROP FUNCTION IF EXISTS apiome.team_members_require_tenant_member();
--   DROP TABLE IF EXISTS apiome.teams;
--   -- and re-apply the V251 body of apiome.seed_builtin_roles to drop the new resource.

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- teams — a named group inside one tenant.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS teams (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- The handle tags and extensions name; the API refuses to change it after creation.
    slug VARCHAR(128) NOT NULL
        CONSTRAINT teams_slug_shape_check
            CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
    name VARCHAR(200) NOT NULL
        CONSTRAINT teams_name_not_blank_check CHECK (btrim(name) <> ''),
    description TEXT,

    -- Owner links. All optional; the URLs are http(s) so a stored link is always clickable.
    contact_email VARCHAR(320),
    chat_url TEXT
        CONSTRAINT teams_chat_url_shape_check CHECK (chat_url IS NULL OR chat_url ~* '^https?://'),
    oncall_url TEXT
        CONSTRAINT teams_oncall_url_shape_check CHECK (oncall_url IS NULL OR oncall_url ~* '^https?://'),
    docs_url TEXT
        CONSTRAINT teams_docs_url_shape_check CHECK (docs_url IS NULL OR docs_url ~* '^https?://'),

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE
);

-- One live team per slug per tenant. Partial, so a retired slug can be reused.
CREATE UNIQUE INDEX IF NOT EXISTS idx_teams_tenant_slug
    ON teams (tenant_id, slug)
    WHERE deleted_at IS NULL;

-- The list read: a tenant's live teams by name.
CREATE INDEX IF NOT EXISTS idx_teams_tenant_name
    ON teams (tenant_id, name)
    WHERE deleted_at IS NULL;

COMMENT ON TABLE teams IS
    'A named group of tenant members that owns catalog entities and receives their findings (CDG-2.1, #5960)';
COMMENT ON COLUMN teams.slug IS 'Stable handle (lowercase, hyphenated) unique among live teams of the tenant; not editable';
COMMENT ON COLUMN teams.contact_email IS 'Optional shared mailbox for the team';
COMMENT ON COLUMN teams.chat_url IS 'Optional http(s) link to the team chat channel';
COMMENT ON COLUMN teams.oncall_url IS 'Optional http(s) link to the team on-call schedule';
COMMENT ON COLUMN teams.docs_url IS 'Optional http(s) link to the team documentation';
COMMENT ON COLUMN teams.deleted_at IS 'Soft-delete stamp; deleted teams are hidden from reads and free their slug';

-- ---------------------------------------------------------------------------------------------------
-- team_members — who is on a team.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS team_members (
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(16) NOT NULL DEFAULT 'member'
        CONSTRAINT team_members_role_check CHECK (role IN ('lead', 'member')),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT team_members_pkey PRIMARY KEY (team_id, user_id)
);

-- "Which teams is this user on" — the read the tenant-leave trigger and CDG-2.3 routing make.
CREATE INDEX IF NOT EXISTS idx_team_members_user
    ON team_members (user_id);

COMMENT ON TABLE team_members IS 'Membership of a team; the user must be a member of the team''s tenant (CDG-2.1, #5960)';
COMMENT ON COLUMN team_members.role IS 'lead | member';

-- Rule 3: a team member is a tenant member.
CREATE OR REPLACE FUNCTION apiome.team_members_require_tenant_member()
RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM apiome.teams t
        JOIN apiome.tenant_users tu ON tu.tenant_id = t.tenant_id AND tu.user_id = NEW.user_id
        WHERE t.id = NEW.team_id
    ) THEN
        RAISE EXCEPTION 'user % is not a member of the team''s tenant', NEW.user_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_team_members_require_tenant_member ON team_members;
CREATE TRIGGER trg_team_members_require_tenant_member
    BEFORE INSERT OR UPDATE OF team_id, user_id ON team_members
    FOR EACH ROW EXECUTE FUNCTION apiome.team_members_require_tenant_member();

-- Rule 4: leaving the tenant leaves every team of that tenant, in the same transaction.
CREATE OR REPLACE FUNCTION apiome.tenant_users_leave_teams()
RETURNS trigger AS $$
BEGIN
    DELETE FROM apiome.team_members tm
    USING apiome.teams t
    WHERE tm.team_id = t.id
      AND t.tenant_id = OLD.tenant_id
      AND tm.user_id = OLD.user_id;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tenant_users_leave_teams ON tenant_users;
CREATE TRIGGER trg_tenant_users_leave_teams
    AFTER DELETE ON tenant_users
    FOR EACH ROW EXECUTE FUNCTION apiome.tenant_users_leave_teams();

-- ---------------------------------------------------------------------------------------------------
-- RBAC: teams resource in the built-in role grids.
-- ---------------------------------------------------------------------------------------------------
-- Full replacement of the V251 function body with 'teams' added. The function rewrites the built-in
-- grids from scratch on every call, so replacing it here and reseeding below is idempotent.
--
-- Grid rationale: Owner and Admin manage teams; Editor and Viewer read them. Membership decides who
-- is notified about (and paged for) an entity's findings, so changing it is not content editing.
CREATE OR REPLACE FUNCTION apiome.seed_builtin_roles(p_tenant UUID)
RETURNS void AS $$
DECLARE
    v_owner UUID;
    v_admin UUID;
    v_editor UUID;
    v_viewer UUID;
    -- Resources that behave like editable content (full CRUD for Editor).
    content_resources TEXT[] := ARRAY['projects','versions','classes','properties','paths','imports','api_keys'];
    all_resources TEXT[] := ARRAY['projects','versions','classes','properties','paths','types','imports','members','api_keys','billing','lint_findings','verification_targets','verification_evidence','consumer_contracts','teams'];
    r TEXT;
BEGIN
    -- Upsert the four built-in roles.
    INSERT INTO apiome.roles (tenant_id, slug, name, description, is_builtin) VALUES
        (p_tenant, 'owner',  'Owner',  'Full control of the tenant, including billing and members.', true),
        (p_tenant, 'admin',  'Admin',  'Manage members, roles, and all content; no billing administration.', true),
        (p_tenant, 'editor', 'Editor', 'Create and edit content, but cannot publish, manage members, or change settings.', true),
        (p_tenant, 'viewer', 'Viewer', 'Read-only access to the tenant.', true)
    ON CONFLICT (tenant_id, slug) DO UPDATE
        SET name = EXCLUDED.name,
            description = EXCLUDED.description,
            is_builtin = true;

    SELECT id INTO v_owner  FROM apiome.roles WHERE tenant_id = p_tenant AND slug = 'owner';
    SELECT id INTO v_admin  FROM apiome.roles WHERE tenant_id = p_tenant AND slug = 'admin';
    SELECT id INTO v_editor FROM apiome.roles WHERE tenant_id = p_tenant AND slug = 'editor';
    SELECT id INTO v_viewer FROM apiome.roles WHERE tenant_id = p_tenant AND slug = 'viewer';

    -- Rewrite built-in grids from scratch (idempotent / self-healing).
    DELETE FROM apiome.role_permissions WHERE role_id IN (v_owner, v_admin, v_editor, v_viewer);

    -- Owner: every action on every resource, plus version publishing and waiver approval.
    FOREACH r IN ARRAY all_resources LOOP
        INSERT INTO apiome.role_permissions (role_id, resource, action)
        SELECT v_owner, r, a FROM unnest(ARRAY['view','create','edit','delete']) AS a;
    END LOOP;
    INSERT INTO apiome.role_permissions (role_id, resource, action) VALUES (v_owner, 'versions', 'publish');
    INSERT INTO apiome.role_permissions (role_id, resource, action) VALUES (v_owner, 'lint_findings', 'publish');

    -- Admin: same as Owner but billing is view-only (billing administration is Owner-only).
    FOREACH r IN ARRAY all_resources LOOP
        IF r = 'billing' THEN
            INSERT INTO apiome.role_permissions (role_id, resource, action) VALUES (v_admin, 'billing', 'view');
        ELSE
            INSERT INTO apiome.role_permissions (role_id, resource, action)
            SELECT v_admin, r, a FROM unnest(ARRAY['view','create','edit','delete']) AS a;
        END IF;
    END LOOP;
    INSERT INTO apiome.role_permissions (role_id, resource, action) VALUES (v_admin, 'versions', 'publish');
    INSERT INTO apiome.role_permissions (role_id, resource, action) VALUES (v_admin, 'lint_findings', 'publish');

    -- Editor: full CRUD on content resources; view-only on governance resources; no publish.
    -- lint_findings: view + edit (assign, acknowledge, request waivers) but no approval.
    -- verification_targets: view only — enough to run verification, not to redefine where it points.
    -- verification_evidence: view + create — recording a run is what verification *is*, and evidence
    -- cannot be edited by anyone (it is immutable) or deleted by an Editor (that is retention).
    -- consumer_contracts: view + create + edit — declaring what your service consumes is developer
    -- work; deleting a consumer removes a signal that guards other people's changes, so it is not.
    -- teams: view only — who owns what, and who is paged for it, is a decision for Owner/Admin.
    FOREACH r IN ARRAY content_resources LOOP
        INSERT INTO apiome.role_permissions (role_id, resource, action)
        SELECT v_editor, r, a FROM unnest(ARRAY['view','create','edit','delete']) AS a;
    END LOOP;
    INSERT INTO apiome.role_permissions (role_id, resource, action)
    SELECT v_editor, res, 'view' FROM unnest(ARRAY['types','members','billing','verification_targets','teams']) AS res;
    INSERT INTO apiome.role_permissions (role_id, resource, action)
    SELECT v_editor, 'lint_findings', a FROM unnest(ARRAY['view','edit']) AS a;
    INSERT INTO apiome.role_permissions (role_id, resource, action)
    SELECT v_editor, 'verification_evidence', a FROM unnest(ARRAY['view','create']) AS a;
    INSERT INTO apiome.role_permissions (role_id, resource, action)
    SELECT v_editor, 'consumer_contracts', a FROM unnest(ARRAY['view','create','edit']) AS a;

    -- Viewer: view-only on every resource.
    FOREACH r IN ARRAY all_resources LOOP
        INSERT INTO apiome.role_permissions (role_id, resource, action) VALUES (v_viewer, r, 'view');
    END LOOP;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.seed_builtin_roles(UUID) IS
    'Idempotently (re)seed the four built-in roles and their canonical permission grids for a tenant (#3611; lint_findings added by #4859; verification_targets added by #4730; verification_evidence added by #4731; consumer_contracts added by #4479; teams added by #5960)';

COMMENT ON COLUMN apiome.role_permissions.resource IS
    'One of: projects, versions, classes, properties, paths, types, imports, members, api_keys, billing, lint_findings, verification_targets, verification_evidence, consumer_contracts, teams';

-- Reseed every existing tenant so the new resource lands in all built-in grids.
DO $$
DECLARE
    t RECORD;
BEGIN
    FOR t IN SELECT id FROM apiome.tenants LOOP
        PERFORM apiome.seed_builtin_roles(t.id);
    END LOOP;
END;
$$;
