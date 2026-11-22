-- Per-tenant bring-your-own buckets for the document store (COA-5.15, #7092).
--
-- COA-5.1 gave the install one document store. A tenant can now keep its originals and rendered
-- documents in its own S3-compatible bucket, using a sealed storage credential
-- (export_storage_credentials, V356). The platform store stays the default.
--
--   1. apiome.tenant_document_stores — one row per tenant that has ever configured its own bucket:
--      where documents go now (mode), the bucket settings, how far a move between the platform
--      store and the bucket got, and whether the bucket is currently unreachable.
--   2. document_objects.backend gains 'tenant_s3': an object held in its tenant's own bucket. With
--      storage_key it records where each object lives, so platform and tenant objects coexist
--      while a move is running.
--   3. A notification type, document_store_unavailable, sent to a tenant's administrators when
--      their bucket stops answering.
--   4. The permission document_store:manage in the built-in Owner and Admin role grids.
--
-- Online: one new table; two CHECK constraints are replaced (validated against existing rows,
-- which all satisfy the wider list); seed_builtin_roles rewrites four small grids per tenant.
--
-- Rollback notes (only when no tenant uses its own bucket — objects with backend 'tenant_s3'
-- would otherwise become unreadable):
--   DROP TABLE IF EXISTS apiome.tenant_document_stores;
--   ALTER TABLE apiome.document_objects DROP CONSTRAINT document_objects_backend_check;
--   ALTER TABLE apiome.document_objects ADD CONSTRAINT document_objects_backend_check
--       CHECK (backend IN ('db', 's3', 'filesystem'));
--   Restore notifications_type_check from V394 and seed_builtin_roles from V284, then reseed.

-- ---------------------------------------------------------------------------------------------------
-- 1. Tenant document store settings
-- ---------------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS apiome.tenant_document_stores (
    tenant_id          uuid PRIMARY KEY REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    mode               text NOT NULL DEFAULT 'platform'
                           CONSTRAINT tenant_document_stores_mode_check CHECK (mode IN ('platform', 'tenant')),
    -- A credential in use cannot be deleted out from under the documents it reaches. NO ACTION
    -- (checked at the end of the statement) rather than RESTRICT, so deleting the tenant, which
    -- cascades to both this row and the credential, still goes through.
    credential_id      uuid CONSTRAINT tenant_document_stores_credential_fkey
                           REFERENCES apiome.export_storage_credentials(id) ON DELETE NO ACTION,
    bucket             text CONSTRAINT tenant_document_stores_bucket_check
                           CHECK (bucket IS NULL OR length(bucket) BETWEEN 3 AND 255),
    prefix             text NOT NULL DEFAULT 'apiome'
                           CONSTRAINT tenant_document_stores_prefix_check CHECK (length(prefix) <= 512),
    region             text NOT NULL DEFAULT '',
    endpoint_url       text NOT NULL DEFAULT '',
    addressing_style   text NOT NULL DEFAULT 'auto'
                           CONSTRAINT tenant_document_stores_addressing_check
                           CHECK (addressing_style IN ('auto', 'path', 'virtual')),
    sse                text NOT NULL DEFAULT ''
                           CONSTRAINT tenant_document_stores_sse_check CHECK (sse IN ('', 's3', 'kms')),
    kms_key_id         text NOT NULL DEFAULT '',
    -- The move between the platform store and the bucket.
    move_state         text NOT NULL DEFAULT 'idle'
                           CONSTRAINT tenant_document_stores_move_state_check
                           CHECK (move_state IN ('idle', 'running', 'completed', 'failed')),
    move_target        text CONSTRAINT tenant_document_stores_move_target_check
                           CHECK (move_target IS NULL OR move_target IN ('platform', 'tenant')),
    move_last_key      text,
    move_counts        jsonb NOT NULL DEFAULT '{}'::jsonb,
    move_error         text,
    move_started_at    timestamptz,
    move_finished_at   timestamptz,
    cleanup_pending    boolean NOT NULL DEFAULT false,
    -- The bucket's reachability, as the last read or write saw it.
    unavailable_since  timestamptz,
    last_error         text,
    last_notified_at   timestamptz,
    updated_at         timestamptz NOT NULL DEFAULT now(),
    updated_by         uuid,
    -- Documents can only go to a bucket that is fully described.
    CONSTRAINT tenant_document_stores_tenant_needs_bucket
        CHECK (mode <> 'tenant' OR (credential_id IS NOT NULL AND bucket IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_tenant_document_stores_credential
    ON apiome.tenant_document_stores (credential_id) WHERE credential_id IS NOT NULL;

COMMENT ON TABLE apiome.tenant_document_stores IS
    'Where a tenant''s document store objects go (COA-5.15, #7092): the platform store, or the tenant''s own S3-compatible bucket. No row means the platform store.';
COMMENT ON COLUMN apiome.tenant_document_stores.mode IS
    'platform: new objects go to the platform store. tenant: new objects go to the bucket described by this row.';
COMMENT ON COLUMN apiome.tenant_document_stores.credential_id IS
    'The sealed storage credential (export_storage_credentials) used to reach the bucket. Kept after a move back to the platform store until the old copies are cleaned up.';
COMMENT ON COLUMN apiome.tenant_document_stores.prefix IS
    'Folder inside the bucket; keys are <prefix>/tenants/<tenant_id>/objects/sha256/<aa>/<hex>.';
COMMENT ON COLUMN apiome.tenant_document_stores.move_state IS
    'idle, running, completed or failed: the copy-and-verify move of existing objects to move_target.';
COMMENT ON COLUMN apiome.tenant_document_stores.move_last_key IS
    'document_objects.id of the last object the move finished, so an interrupted move resumes after it.';
COMMENT ON COLUMN apiome.tenant_document_stores.cleanup_pending IS
    'True when a finished move left the old copies in place; they are deleted only after an explicit confirm.';
COMMENT ON COLUMN apiome.tenant_document_stores.unavailable_since IS
    'When the bucket first failed in the current outage; NULL while it answers.';
COMMENT ON COLUMN apiome.tenant_document_stores.last_error IS
    'Why the bucket is unavailable, with credentials redacted.';
COMMENT ON COLUMN apiome.tenant_document_stores.last_notified_at IS
    'When the tenant''s administrators were last told about the current outage (once per outage).';

-- ---------------------------------------------------------------------------------------------------
-- 2. An object held in its tenant's own bucket
-- ---------------------------------------------------------------------------------------------------

ALTER TABLE apiome.document_objects DROP CONSTRAINT IF EXISTS document_objects_backend_check;
ALTER TABLE apiome.document_objects
    ADD CONSTRAINT document_objects_backend_check
        CHECK (backend IN ('db', 's3', 'filesystem', 'tenant_s3'));

COMMENT ON COLUMN apiome.document_objects.backend IS
    'Where the bytes live: db, s3 or filesystem (the platform store), or tenant_s3 (the tenant''s own bucket, described by tenant_document_stores).';

-- ---------------------------------------------------------------------------------------------------
-- 3. The inbox type
-- ---------------------------------------------------------------------------------------------------

ALTER TABLE apiome.notifications DROP CONSTRAINT IF EXISTS notifications_type_check;
ALTER TABLE apiome.notifications
    ADD CONSTRAINT notifications_type_check
        CHECK (type IN (
            'mention', 'review_requested', 'review_decision', 'thread_resolved', 'version_published',
            'export_auto_halted', 'sunset_still_used', 'seat_cap_blocked_sso',
            'owner_finding', 'owner_breaking_change', 'owner_verification_drift', 'owner_gate_blocked',
            'owner_trust_drift', 'owner_shadow_api', 'owner_sync_failed',
            'document_store_unavailable'
        ));

-- ---------------------------------------------------------------------------------------------------
-- 4. RBAC: document_store:manage in the built-in role grids
-- ---------------------------------------------------------------------------------------------------
-- Full replacement of the V284 function body with the one grant added for Owner and Admin. The
-- function rewrites the built-in grids from scratch on every call, so replacing it here and
-- reseeding below is idempotent. document_store is not in all_resources: it has no view / create /
-- edit / delete, only manage.
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
    INSERT INTO apiome.role_permissions (role_id, resource, action) VALUES (v_owner, 'document_store', 'manage');

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
    -- document_store: one action, manage — where the tenant's documents are kept (#7092). Owner and
    -- Admin only: it is a tenant setting backed by a credential, never content editing.
    INSERT INTO apiome.role_permissions (role_id, resource, action) VALUES (v_admin, 'document_store', 'manage');

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
    'Idempotently (re)seed the four built-in roles and their canonical permission grids for a tenant (#3611; lint_findings added by #4859; verification_targets added by #4730; verification_evidence added by #4731; consumer_contracts added by #4479; teams added by #5960; document_store:manage added by #7092)';

COMMENT ON COLUMN apiome.role_permissions.resource IS
    'One of: projects, versions, classes, properties, paths, types, imports, members, api_keys, billing, lint_findings, verification_targets, verification_evidence, consumer_contracts, teams, document_store';
COMMENT ON COLUMN apiome.role_permissions.action IS
    'One of: view, create, edit, delete, publish, manage (manage applies to document_store only)';

-- Reseed every existing tenant so the grant lands in the built-in Owner and Admin grids.
DO $$
DECLARE
    t RECORD;
BEGIN
    FOR t IN SELECT id FROM apiome.tenants LOOP
        PERFORM apiome.seed_builtin_roles(t.id);
    END LOOP;
END;
$$;
