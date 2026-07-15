-- Catalog-wide lint posture and remediation workspace (#4859, CLX-4.1).
--
-- Problem: lint evidence, axis scores, and waiver decisions (CLX-1.x) are only readable one
-- revision at a time. Teams cannot triage catalog-wide, request waivers for review, or save the
-- filter sets they work from.
--
-- Solution, three additive pieces:
--   1. ``lint_workspace_saved_views`` — per-user named workspace filter sets (mirrors
--      ``mcp_saved_searches``, V150) backing saved/pinned views in the lint workspace UI.
--   2. A ``waiver_requested`` state in the finding-decision lifecycle so a non-privileged
--      editor can request a waiver that a privileged reviewer approves (-> waived) or
--      rejects (-> open). Requested waivers still gate CI as open until approved.
--   3. A ``lint_findings`` RBAC resource in the built-in role grids: Owner/Admin additionally
--      hold ``publish`` (waiver approval, mirroring ``versions:publish``); Editor holds
--      view/edit (assign, acknowledge, request); Viewer holds view.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.lint_workspace_saved_views;
--   Re-add the V169 state CHECKs without 'waiver_requested' (after remapping any rows in that
--   state to 'open') and drop lint_finding_decisions_waiver_request_fields_check;
--   re-run the V118 version of apiome.seed_builtin_roles().

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- lint_workspace_saved_views — per-user named workspace filter sets.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS apiome.lint_workspace_saved_views (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Tenant scope — cascade when the tenant is removed.
    tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,

    -- Owner — cascade when the user is removed; saved views are personal, not shared.
    user_id UUID NOT NULL REFERENCES apiome.users(id) ON DELETE CASCADE,

    -- Human label shown in the workspace UI; unique per owner within a tenant.
    name TEXT NOT NULL,

    -- Workspace filter state (severity, state, axis, grade, coverage, profile, scanner,
    -- subjectType, projectId, ownerUserId, ruleId, category, new) — mirrors the
    -- GET /v1/lint/workspace/findings query vocabulary.
    filters JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Optional free-text search box value saved with the filter set.
    query TEXT NOT NULL DEFAULT '',

    -- Sort key saved with the filter set (severity / newest / rule / subject).
    sort TEXT NOT NULL DEFAULT 'severity',

    -- When TRUE the saved view surfaces as a quick-access chip in the workspace toolbar.
    is_pinned BOOLEAN NOT NULL DEFAULT false,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT lint_workspace_saved_views_name_unique UNIQUE (tenant_id, user_id, name),
    CONSTRAINT lint_workspace_saved_views_name_nonempty CHECK (char_length(trim(name)) > 0)
);

-- List a user's saved views (newest first) and pinned-view lookups.
CREATE INDEX IF NOT EXISTS idx_lint_workspace_saved_views_tenant_user
    ON apiome.lint_workspace_saved_views (tenant_id, user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_lint_workspace_saved_views_pinned
    ON apiome.lint_workspace_saved_views (tenant_id, user_id)
    WHERE is_pinned = true;

COMMENT ON TABLE apiome.lint_workspace_saved_views IS
    'Per-user named lint-workspace filter sets backing saved and pinned workspace views (CLX-4.1, #4859). '
    'One row per (tenant, user, name); filters are JSONB matching the workspace findings query vocabulary.';
COMMENT ON COLUMN apiome.lint_workspace_saved_views.id IS 'Unique identifier for the saved view';
COMMENT ON COLUMN apiome.lint_workspace_saved_views.tenant_id IS 'Tenant that owns the saved view';
COMMENT ON COLUMN apiome.lint_workspace_saved_views.user_id IS 'User that owns the saved view; views are personal';
COMMENT ON COLUMN apiome.lint_workspace_saved_views.name IS 'Human label, unique per (tenant, user)';
COMMENT ON COLUMN apiome.lint_workspace_saved_views.filters IS
    'Workspace filters (severity, state, axis, grade, coverage, profile, scanner, subjectType, '
    'projectId, ownerUserId, ruleId, category, new) as JSONB';
COMMENT ON COLUMN apiome.lint_workspace_saved_views.query IS 'Free-text search value saved with the filter set';
COMMENT ON COLUMN apiome.lint_workspace_saved_views.sort IS 'Sort key saved with the filter set (severity, newest, rule, subject)';
COMMENT ON COLUMN apiome.lint_workspace_saved_views.is_pinned IS
    'When TRUE the saved view surfaces as a pinned quick-access chip in the workspace toolbar';
COMMENT ON COLUMN apiome.lint_workspace_saved_views.created_at IS 'When the saved view was created';
COMMENT ON COLUMN apiome.lint_workspace_saved_views.updated_at IS 'When the saved view was last modified';

-- ---------------------------------------------------------------------------------------------------
-- waiver_requested — request/review split in the finding-decision lifecycle.
-- ---------------------------------------------------------------------------------------------------
-- Widen the V169 state vocabulary. A requested waiver is NOT suppressed at policy-evaluate time;
-- it gates exactly like open until a privileged reviewer approves it into 'waived'.
ALTER TABLE apiome.lint_finding_decisions
    DROP CONSTRAINT IF EXISTS lint_finding_decisions_state_check;
ALTER TABLE apiome.lint_finding_decisions
    ADD CONSTRAINT lint_finding_decisions_state_check
        CHECK (state IN ('open', 'acknowledged', 'waiver_requested', 'waived', 'fixed', 'false_positive'));

ALTER TABLE apiome.lint_finding_decision_events
    DROP CONSTRAINT IF EXISTS lint_finding_decision_events_after_state_check;
ALTER TABLE apiome.lint_finding_decision_events
    ADD CONSTRAINT lint_finding_decision_events_after_state_check
        CHECK (after_state IN ('open', 'acknowledged', 'waiver_requested', 'waived', 'fixed', 'false_positive'));

-- A waiver request must explain itself; expiry stays optional until approval
-- (lint_finding_decisions_waiver_fields_check, V169, still enforces rationale + expiry on 'waived').
ALTER TABLE apiome.lint_finding_decisions
    DROP CONSTRAINT IF EXISTS lint_finding_decisions_waiver_request_fields_check;
ALTER TABLE apiome.lint_finding_decisions
    ADD CONSTRAINT lint_finding_decisions_waiver_request_fields_check
        CHECK (
            state <> 'waiver_requested'
            OR (rationale IS NOT NULL AND length(btrim(rationale)) > 0)
        );

COMMENT ON COLUMN apiome.lint_finding_decisions.state IS
    'Lifecycle state: open, acknowledged, waiver_requested, waived, fixed, or false_positive';

-- ---------------------------------------------------------------------------------------------------
-- RBAC: lint_findings resource in the built-in role grids.
-- ---------------------------------------------------------------------------------------------------
-- Full replacement of the V118 function body with 'lint_findings' added. The function rewrites the
-- built-in grids from scratch on every call and apiome-rest re-invokes it on demand, so replacing
-- it here and reseeding below is idempotent and self-healing for all tenants.
CREATE OR REPLACE FUNCTION apiome.seed_builtin_roles(p_tenant UUID)
RETURNS void AS $$
DECLARE
    v_owner UUID;
    v_admin UUID;
    v_editor UUID;
    v_viewer UUID;
    -- Resources that behave like editable content (full CRUD for Editor).
    content_resources TEXT[] := ARRAY['projects','versions','classes','properties','paths','imports','api_keys'];
    all_resources TEXT[] := ARRAY['projects','versions','classes','properties','paths','types','imports','members','api_keys','billing','lint_findings'];
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
    FOREACH r IN ARRAY content_resources LOOP
        INSERT INTO apiome.role_permissions (role_id, resource, action)
        SELECT v_editor, r, a FROM unnest(ARRAY['view','create','edit','delete']) AS a;
    END LOOP;
    INSERT INTO apiome.role_permissions (role_id, resource, action)
    SELECT v_editor, res, 'view' FROM unnest(ARRAY['types','members','billing']) AS res;
    INSERT INTO apiome.role_permissions (role_id, resource, action)
    SELECT v_editor, 'lint_findings', a FROM unnest(ARRAY['view','edit']) AS a;

    -- Viewer: view-only on every resource.
    FOREACH r IN ARRAY all_resources LOOP
        INSERT INTO apiome.role_permissions (role_id, resource, action) VALUES (v_viewer, r, 'view');
    END LOOP;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.seed_builtin_roles(UUID) IS
    'Idempotently (re)seed the four built-in roles and their canonical permission grids for a tenant (#3611; lint_findings added by #4859)';

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

-- NOTE: idx_lint_finding_decisions_tenant_state (tenant_id, state, updated_at DESC) already
-- exists from V169 and serves the workspace state/queue filters; no new index is required here.
