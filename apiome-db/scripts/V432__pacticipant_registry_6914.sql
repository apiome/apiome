-- Pacticipant, version, branch and tag model — PFX-1.1 (#6914).
--
-- Apiome stores *what a consumer uses* (CTG-4.1, V251) but not *who published which pact from which
-- build*. Pact tooling addresses everything by pacticipant name, application version, branch and
-- tag; without those there is no matrix, no can-i-deploy and no environments. This migration adds
-- that registry: five tables, one RBAC resource.
--
--   pacticipant                — an application that takes part in a pact, as a consumer, a provider
--                                or both: handle, display name, repository URL, main branch, and two
--                                optional bindings — the Apiome project it *is* (a provider) and the
--                                `consumer` row it *is* (CTG-4.1).
--   pacticipant_version        — one application version (a commit, a build): version number, build
--                                URL, who recorded it. Immutable.
--   pacticipant_branch         — a branch of the application's repository, with its head version.
--   pacticipant_branch_version — which versions were recorded on which branch.
--   pacticipant_version_tag    — the tags of a version (Pact's older way to name a branch or stage).
--
-- Rules kept by the database:
--
--   1. **Names are unique per tenant.** `slug` is the handle tooling names, shaped like a consumer
--      slug (V251) and UNIQUE with `tenant_id`.
--   2. **Nothing crosses a tenant.** Only `pacticipant` carries `tenant_id`; every other row hangs
--      off one pacticipant, so its tenant cannot disagree with its owner's. The two bindings use the
--      composite keys `(project_id, tenant_id)` and `(consumer_id, tenant_id)`, so a pacticipant can
--      only be bound to a project or a consumer of its own tenant. Branch membership and tags carry
--      `pacticipant_id` and reference `(id, pacticipant_id)`, so a branch can only hold, and a tag
--      can only name, a version of the same pacticipant.
--   3. **Deleting a project does not delete its pacticipant; it clears the binding.** A hard delete
--      is `ON DELETE SET NULL (project_id)`. The app deletes a project by stamping `deleted_at`
--      (apiome-rest and apiome-ui both do), so a trigger on `projects` clears the binding on that
--      stamp too. The consumer binding follows the same two rules: `SET NULL (consumer_id)` when
--      the consumer row goes, and a trigger on `consumer` for the stamp that retires one.
--   4. **Versions never mutate.** A trigger refuses any UPDATE of `pacticipant_version` except the
--      one the database itself makes: `created_by` set to NULL when that user is deleted.
--   5. **A tag and a branch membership exist once.** Their primary keys are the natural keys, so
--      recording the same one again is `ON CONFLICT DO NOTHING`.
--
-- The branch head only moves forward (to a version recorded later than the current head, compared
-- by `pacticipant_version.seq`). apiome-rest's `app.pacticipant_store.record_version` is the only
-- writer of `head_version_id` and keeps that rule in one statement; it is not a trigger, because
-- deleting a version (PFX-1.11) will have to move a head back.
--
-- Online: five new tables; `projects` and `consumer` each gain a unique index on `(id, tenant_id)`
-- (built in place — both are small next to the revision tables) and one row trigger each that only
-- fires when `deleted_at` goes from NULL to a value. `seed_builtin_roles` rewrites four small
-- grids per tenant.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TRIGGER IF EXISTS trg_pacticipant_unbind_deleted_project ON apiome.projects;
--   DROP TRIGGER IF EXISTS trg_pacticipant_unbind_deleted_consumer ON apiome.consumer;
--   DROP FUNCTION IF EXISTS apiome.pacticipant_unbind_deleted_project();
--   DROP FUNCTION IF EXISTS apiome.pacticipant_unbind_deleted_consumer();
--   DROP TABLE IF EXISTS apiome.pacticipant_version_tag, apiome.pacticipant_branch_version,
--       apiome.pacticipant_branch, apiome.pacticipant_version, apiome.pacticipant;
--   DROP FUNCTION IF EXISTS apiome.pacticipant_version_immutable();
--   ALTER TABLE apiome.consumer DROP CONSTRAINT IF EXISTS consumer_id_tenant_key;
--   ALTER TABLE apiome.projects DROP CONSTRAINT IF EXISTS projects_id_tenant_key;
--   -- and re-apply the V408 body of apiome.seed_builtin_roles to drop the new resource, then reseed.

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- 0. Composite keys the two bindings reference (rule 2)
-- ---------------------------------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'projects_id_tenant_key' AND conrelid = 'apiome.projects'::regclass
    ) THEN
        ALTER TABLE apiome.projects ADD CONSTRAINT projects_id_tenant_key UNIQUE (id, tenant_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'consumer_id_tenant_key' AND conrelid = 'apiome.consumer'::regclass
    ) THEN
        ALTER TABLE apiome.consumer ADD CONSTRAINT consumer_id_tenant_key UNIQUE (id, tenant_id);
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------------------------------
-- 1. pacticipant — an application that takes part in a pact
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pacticipant (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Rule 1. The handle Pact tooling and URLs name. Same shape as consumer.slug (V251), and not
    -- editable: renaming it would orphan every pact and CI job that names it.
    slug VARCHAR(128) NOT NULL
        CONSTRAINT pacticipant_slug_shape_check
            CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
    -- The display name: the pacticipant name as a Pact file or a person writes it.
    name VARCHAR(255) NOT NULL
        CONSTRAINT pacticipant_name_not_blank_check CHECK (btrim(name) <> ''),

    repository_url TEXT
        CONSTRAINT pacticipant_repository_url_check
            CHECK (repository_url IS NULL
                   OR (repository_url ~* '^https?://[^[:space:]]+$' AND length(repository_url) <= 2048)),
    -- The branch can-i-deploy and "latest from main" read by default (`main`, `master`, `trunk`).
    main_branch VARCHAR(255)
        CONSTRAINT pacticipant_main_branch_not_blank_check
            CHECK (main_branch IS NULL OR btrim(main_branch) <> ''),

    -- Rule 2 and 3. A provider pacticipant may be bound to the Apiome project that describes it; a
    -- consumer pacticipant to its row in the consumer registry (CTG-4.1). Both optional.
    project_id UUID,
    consumer_id UUID,

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pacticipant_tenant_slug_key UNIQUE (tenant_id, slug),

    -- `SET NULL (column)` clears the binding only; without the column list the delete would try to
    -- null `tenant_id` as well.
    CONSTRAINT pacticipant_project_fk
        FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects (id, tenant_id) ON DELETE SET NULL (project_id),
    CONSTRAINT pacticipant_consumer_fk
        FOREIGN KEY (consumer_id, tenant_id)
        REFERENCES consumer (id, tenant_id) ON DELETE SET NULL (consumer_id)
);

-- The referential checks of the two bindings, and "which pacticipant is this project / consumer".
CREATE INDEX IF NOT EXISTS idx_pacticipant_project
    ON pacticipant (project_id, tenant_id)
    WHERE project_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_pacticipant_consumer
    ON pacticipant (consumer_id, tenant_id)
    WHERE consumer_id IS NOT NULL;

COMMENT ON TABLE pacticipant IS
    'An application that takes part in a pact, as consumer, provider or both (PFX-1.1, #6914)';
COMMENT ON COLUMN pacticipant.tenant_id IS 'Owning tenant; a pacticipant is never readable outside it';
COMMENT ON COLUMN pacticipant.slug IS 'Stable handle tooling and URLs name (lowercase, hyphenated); unique per tenant, never renamed';
COMMENT ON COLUMN pacticipant.name IS 'Display name: the pacticipant name as a Pact file or a person writes it';
COMMENT ON COLUMN pacticipant.repository_url IS 'http(s) URL of the application''s source repository';
COMMENT ON COLUMN pacticipant.main_branch IS 'The branch read by default when a query names no branch';
COMMENT ON COLUMN pacticipant.project_id IS 'Optional: the Apiome project that describes this provider; cleared when the project is deleted';
COMMENT ON COLUMN pacticipant.consumer_id IS 'Optional: this application''s row in the consumer registry (CTG-4.1); cleared when that consumer is retired or deleted';

-- Rule 3, for the delete the app actually performs: a `deleted_at` stamp.
CREATE OR REPLACE FUNCTION apiome.pacticipant_unbind_deleted_project()
RETURNS trigger AS $$
BEGIN
    UPDATE apiome.pacticipant
    SET project_id = NULL, updated_at = CURRENT_TIMESTAMP
    WHERE project_id = NEW.id AND tenant_id = NEW.tenant_id;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.pacticipant_unbind_deleted_project() IS
    'Clears pacticipant.project_id when a project is soft-deleted, so the pacticipant survives its project (PFX-1.1, #6914)';

DROP TRIGGER IF EXISTS trg_pacticipant_unbind_deleted_project ON apiome.projects;
CREATE TRIGGER trg_pacticipant_unbind_deleted_project
    AFTER UPDATE OF deleted_at ON apiome.projects
    FOR EACH ROW
    WHEN (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL)
    EXECUTE FUNCTION apiome.pacticipant_unbind_deleted_project();

-- The same for the consumer binding: retiring a consumer is a `deleted_at` stamp (V251).
CREATE OR REPLACE FUNCTION apiome.pacticipant_unbind_deleted_consumer()
RETURNS trigger AS $$
BEGIN
    UPDATE apiome.pacticipant
    SET consumer_id = NULL, updated_at = CURRENT_TIMESTAMP
    WHERE consumer_id = NEW.id AND tenant_id = NEW.tenant_id;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.pacticipant_unbind_deleted_consumer() IS
    'Clears pacticipant.consumer_id when a consumer is retired, so the pacticipant survives it (PFX-1.1, #6914)';

DROP TRIGGER IF EXISTS trg_pacticipant_unbind_deleted_consumer ON apiome.consumer;
CREATE TRIGGER trg_pacticipant_unbind_deleted_consumer
    AFTER UPDATE OF deleted_at ON apiome.consumer
    FOR EACH ROW
    WHEN (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL)
    EXECUTE FUNCTION apiome.pacticipant_unbind_deleted_consumer();

-- ---------------------------------------------------------------------------------------------------
-- 2. pacticipant_version — one application version; immutable
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pacticipant_version (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pacticipant_id UUID NOT NULL REFERENCES pacticipant(id) ON DELETE CASCADE,

    -- The version string exactly as the build reported it — a commit SHA, a semantic version. Never
    -- parsed or re-cased; order comes from `seq`, not from the string.
    number VARCHAR(255) NOT NULL
        CONSTRAINT pacticipant_version_number_check
            CHECK (number <> '' AND number = btrim(number) AND number !~ '[[:cntrl:]]'),

    -- Order of recording across the whole table. "Latest" and the branch head compare this, not
    -- `created_at`, which is equal for every row written in one transaction.
    seq BIGINT GENERATED ALWAYS AS IDENTITY,

    build_url TEXT
        CONSTRAINT pacticipant_version_build_url_check
            CHECK (build_url IS NULL
                   OR (build_url ~* '^https?://[^[:space:]]+$' AND length(build_url) <= 2048)),

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    -- Email or key name at the time of recording, kept after the user is gone.
    actor_label TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pacticipant_version_number_key UNIQUE (pacticipant_id, number),
    -- Referenced by branch heads, branch membership and tags (rule 2).
    CONSTRAINT pacticipant_version_id_pacticipant_key UNIQUE (id, pacticipant_id)
);

-- A pacticipant's versions, latest first.
CREATE INDEX IF NOT EXISTS idx_pacticipant_version_latest
    ON pacticipant_version (pacticipant_id, seq DESC);

COMMENT ON TABLE pacticipant_version IS
    'One immutable application version of a pacticipant — a commit or a build (PFX-1.1, #6914)';
COMMENT ON COLUMN pacticipant_version.number IS 'The version string as the build reported it; unique per pacticipant';
COMMENT ON COLUMN pacticipant_version.seq IS 'Order of recording; what "latest" and the branch head compare';
COMMENT ON COLUMN pacticipant_version.build_url IS 'http(s) URL of the CI build that produced this version';
COMMENT ON COLUMN pacticipant_version.actor_label IS 'Who recorded it, as text, kept after the user row is gone';

-- Rule 4.
CREATE OR REPLACE FUNCTION apiome.pacticipant_version_immutable()
RETURNS trigger AS $$
BEGIN
    -- The one change allowed is the database's own: created_by → NULL when the user is deleted.
    IF NEW.created_by IS NULL
       AND (to_jsonb(NEW) - 'created_by') = (to_jsonb(OLD) - 'created_by') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'pacticipant_version rows are immutable (version % of pacticipant %)',
        OLD.number, OLD.pacticipant_id
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.pacticipant_version_immutable() IS
    'Refuses every UPDATE of pacticipant_version except created_by being nulled by a user delete (PFX-1.1, #6914)';

DROP TRIGGER IF EXISTS trg_pacticipant_version_immutable ON apiome.pacticipant_version;
CREATE TRIGGER trg_pacticipant_version_immutable
    BEFORE UPDATE ON apiome.pacticipant_version
    FOR EACH ROW
    EXECUTE FUNCTION apiome.pacticipant_version_immutable();

-- ---------------------------------------------------------------------------------------------------
-- 3. pacticipant_branch — a repository branch and its head version
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pacticipant_branch (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pacticipant_id UUID NOT NULL REFERENCES pacticipant(id) ON DELETE CASCADE,

    -- As git names it (`main`, `feat/new-invoice`); case-sensitive.
    name VARCHAR(255) NOT NULL
        CONSTRAINT pacticipant_branch_name_check
            CHECK (name <> '' AND name = btrim(name) AND name !~ '[[:cntrl:]]'),

    -- The latest version recorded on this branch. A branch exists only because a version was
    -- recorded on it, so it always has one. NO ACTION: deleting the pacticipant removes the branch
    -- and the version together, and the check runs after both cascades.
    head_version_id UUID NOT NULL,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- When the head last moved.
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pacticipant_branch_name_key UNIQUE (pacticipant_id, name),
    CONSTRAINT pacticipant_branch_id_pacticipant_key UNIQUE (id, pacticipant_id),
    CONSTRAINT pacticipant_branch_head_fk
        FOREIGN KEY (head_version_id, pacticipant_id)
        REFERENCES pacticipant_version (id, pacticipant_id)
);

-- The referential check of the head, and "which branches is this version the head of".
CREATE INDEX IF NOT EXISTS idx_pacticipant_branch_head
    ON pacticipant_branch (head_version_id, pacticipant_id);

COMMENT ON TABLE pacticipant_branch IS
    'A branch of a pacticipant''s repository, with the latest version recorded on it (PFX-1.1, #6914)';
COMMENT ON COLUMN pacticipant_branch.head_version_id IS
    'Latest version recorded on the branch; moves only to a version with a higher seq (apiome-rest app.pacticipant_store.record_version)';
COMMENT ON COLUMN pacticipant_branch.updated_at IS 'When the head last moved';

-- ---------------------------------------------------------------------------------------------------
-- 4. pacticipant_branch_version — the versions recorded on a branch
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pacticipant_branch_version (
    branch_id UUID NOT NULL,
    pacticipant_id UUID NOT NULL,
    version_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Rule 5: one membership per branch and version.
    CONSTRAINT pacticipant_branch_version_pkey PRIMARY KEY (branch_id, pacticipant_id, version_id),
    -- Rule 2: the branch and the version belong to the same pacticipant.
    CONSTRAINT pacticipant_branch_version_branch_fk
        FOREIGN KEY (branch_id, pacticipant_id)
        REFERENCES pacticipant_branch (id, pacticipant_id) ON DELETE CASCADE,
    CONSTRAINT pacticipant_branch_version_version_fk
        FOREIGN KEY (version_id, pacticipant_id)
        REFERENCES pacticipant_version (id, pacticipant_id) ON DELETE CASCADE
);

-- "Which branches was this version recorded on", and the version side's referential check.
CREATE INDEX IF NOT EXISTS idx_pacticipant_branch_version_version
    ON pacticipant_branch_version (version_id, pacticipant_id);

COMMENT ON TABLE pacticipant_branch_version IS
    'Which versions of a pacticipant were recorded on which of its branches (PFX-1.1, #6914)';

-- ---------------------------------------------------------------------------------------------------
-- 5. pacticipant_version_tag — the tags of a version
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pacticipant_version_tag (
    version_id UUID NOT NULL,
    pacticipant_id UUID NOT NULL,
    name VARCHAR(255) NOT NULL
        CONSTRAINT pacticipant_version_tag_name_check
            CHECK (name <> '' AND name = btrim(name) AND name !~ '[[:cntrl:]]'),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Rule 5: a version carries a tag once.
    CONSTRAINT pacticipant_version_tag_pkey PRIMARY KEY (version_id, pacticipant_id, name),
    CONSTRAINT pacticipant_version_tag_version_fk
        FOREIGN KEY (version_id, pacticipant_id)
        REFERENCES pacticipant_version (id, pacticipant_id) ON DELETE CASCADE
);

-- "The versions of this pacticipant tagged `prod`" (latest-by-tag, PFX-1.3).
CREATE INDEX IF NOT EXISTS idx_pacticipant_version_tag_name
    ON pacticipant_version_tag (pacticipant_id, name);

COMMENT ON TABLE pacticipant_version_tag IS
    'Tags of a pacticipant version — Pact''s older way to name a branch or a stage (PFX-1.1, #6914)';

-- ---------------------------------------------------------------------------------------------------
-- 6. RBAC: the pacts resource in the built-in role grids
-- ---------------------------------------------------------------------------------------------------
-- Full replacement of the V408 function body with 'pacts' added. The function rewrites the built-in
-- grids from scratch on every call, so replacing it here and reseeding below is idempotent.
--
-- Grid rationale: registering your application and recording its versions, branches and tags is
-- what a CI job does — an Editor (which is also what a CI runner authenticating with an API key
-- resolves to) gets view, create and edit. Deleting a pacticipant removes its whole version history,
-- so it is an Owner/Admin decision.
CREATE OR REPLACE FUNCTION apiome.seed_builtin_roles(p_tenant UUID)
RETURNS void AS $$
DECLARE
    v_owner UUID;
    v_admin UUID;
    v_editor UUID;
    v_viewer UUID;
    -- Resources that behave like editable content (full CRUD for Editor).
    content_resources TEXT[] := ARRAY['projects','versions','classes','properties','paths','imports','api_keys'];
    all_resources TEXT[] := ARRAY['projects','versions','classes','properties','paths','types','imports','members','api_keys','billing','lint_findings','verification_targets','verification_evidence','consumer_contracts','teams','pacts'];
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
    -- pacts: view + create + edit — registering a pacticipant and recording its versions, branches
    -- and tags is what CI does; deleting one removes its whole version history, so it is not.
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
    INSERT INTO apiome.role_permissions (role_id, resource, action)
    SELECT v_editor, 'pacts', a FROM unnest(ARRAY['view','create','edit']) AS a;

    -- Viewer: view-only on every resource.
    FOREACH r IN ARRAY all_resources LOOP
        INSERT INTO apiome.role_permissions (role_id, resource, action) VALUES (v_viewer, r, 'view');
    END LOOP;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.seed_builtin_roles(UUID) IS
    'Idempotently (re)seed the four built-in roles and their canonical permission grids for a tenant (#3611; lint_findings added by #4859; verification_targets added by #4730; verification_evidence added by #4731; consumer_contracts added by #4479; teams added by #5960; document_store:manage added by #7092; pacts added by #6914)';

COMMENT ON COLUMN apiome.role_permissions.resource IS
    'One of: projects, versions, classes, properties, paths, types, imports, members, api_keys, billing, lint_findings, verification_targets, verification_evidence, consumer_contracts, teams, document_store, pacts';
COMMENT ON COLUMN apiome.role_permissions.action IS
    'One of: view, create, edit, delete, publish, manage (manage applies to document_store only)';

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
