-- Consumer contract registry — CTG-4.1 (#4479).
--
-- "Breaking" is relative. Removing a field that nobody reads breaks nobody; narrowing a type that
-- one service depends on breaks exactly that service. Without a record of *who uses what*, the
-- CTG-1.1 classifier can only grade a change against the whole published surface, which
-- over-warns the provider ("47 breaking changes") and tells the consumer nothing at all.
--
-- This migration adds the registry that ends that: two tables plus one RBAC resource.
--
--   consumer          — a named client of a project (a service, an app, a partner), with its
--                       owner and free-form metadata. Identity only; it declares nothing.
--   consumer_contract — one *revision* of what that consumer actually uses: the operations and
--                       the response/request fields it reads, resolved against a stored version
--                       of the project's specification.
--
-- Five rules shape the schema, each an acceptance criterion turned into something the database
-- keeps rather than something the application is trusted to remember:
--
--   1. **A contract belongs to one consumer and one project, and never crosses a tenant.**
--      ``consumer`` carries both ``tenant_id`` and ``project_id``; ``consumer_contract`` repeats
--      both and pins itself to its consumer through a composite foreign key, so a contract can
--      never end up attached to a consumer of a different project. Deleting the project takes
--      the consumers and their contracts with it — a contract about a project that no longer
--      exists is not evidence about anything.
--
--   2. **Contracts are versioned, never overwritten.** ``revision`` is a per-consumer counter,
--      UNIQUE with ``consumer_id``. Declaring a new surface writes revision N+1 and leaves the
--      previous revision intact, so "what did billing-service claim it used when we published
--      2.0.0" stays answerable. Exactly one revision per consumer is the *current* one, which is
--      the partial unique index below rather than a habit.
--
--   3. **Unresolvable interactions are recorded, not dropped.** A Pact file routinely names an
--      interaction that no longer resolves to an operation — a retired endpoint, a path the
--      importer could not template-match, a response status the specification does not declare.
--      ``unresolved`` holds one entry per such interaction with a stable reason code, and
--      ``unresolved_count`` is stored beside it so a list read can show "3 unresolved" without
--      opening the document. An import that resolved nothing is still stored, visibly empty,
--      rather than silently succeeding.
--
--   4. **The intersection query CTG-4.2 needs is a column, not a JSON walk.** ``surface_pointers``
--      is the flattened set of every JSON Pointer the contract touches — the operation pointers
--      and the field pointers, in the same vocabulary ``app.change_taxonomy`` emits. Answering
--      "which consumers does this classified change break" is then an array overlap plus a prefix
--      walk over a small candidate set, indexed by GIN, instead of a scan that parses every
--      stored surface document.
--
--   5. **A contract says which specification it was resolved against.** ``version_id`` names the
--      revision whose paths and schemas the pointers were derived from. It is ON DELETE SET NULL
--      rather than CASCADE: losing the version that a contract was resolved against makes the
--      contract stale, not false, and deleting a *version* must never quietly delete a consumer's
--      declared surface.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.consumer_contract;
--   DROP TABLE IF EXISTS apiome.consumer;
--   -- and re-apply the V212 body of apiome.seed_builtin_roles to drop the new resource.

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- consumer — a named client of a project.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS consumer (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Scope. A consumer is a fact about one project inside one tenant, and is never visible
    -- outside it. Both are carried so a tenant-wide read needs no join through projects.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Identity. ``slug`` is the stable handle CI and Pact files name ("billing-service"); ``name``
    -- is what a person reads. The slug shape is constrained here as well as in the API, because a
    -- handle that can contain a slash is a handle that can be mistaken for a path segment.
    slug VARCHAR(128) NOT NULL
        CONSTRAINT consumer_slug_shape_check
            CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
    name VARCHAR(200) NOT NULL,
    description TEXT,

    -- Who to talk to when their contract is about to break. Free text on purpose: teams name this
    -- a squad, a mailing list, a Slack channel, or a person, and forcing one of those is wrong.
    owner VARCHAR(200),
    contact VARCHAR(320),

    -- Non-secret free-form context: repository URL, environment, CI job. Never credentials.
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT consumer_metadata_object_check CHECK (jsonb_typeof(metadata) = 'object'),

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Retiring a consumer keeps its contracts readable: a published version's per-consumer verdict
    -- must stay explicable after the consumer is decommissioned.
    deleted_at TIMESTAMP WITH TIME ZONE,

    -- Referenced by consumer_contract's composite foreign key, which is what pins a contract to
    -- its consumer's project rather than merely to its consumer.
    CONSTRAINT consumer_id_project_key UNIQUE (id, project_id)
);

-- One live consumer per handle per project. Partial, so retiring "billing-service" frees the name.
CREATE UNIQUE INDEX IF NOT EXISTS idx_consumer_project_slug
    ON consumer (project_id, slug)
    WHERE deleted_at IS NULL;

-- The list read: a project's consumers, newest first.
CREATE INDEX IF NOT EXISTS idx_consumer_project
    ON consumer (project_id, created_at DESC);

-- The tenant-wide read ("every consumer in this workspace").
CREATE INDEX IF NOT EXISTS idx_consumer_tenant
    ON consumer (tenant_id, created_at DESC);

COMMENT ON TABLE consumer IS
    'A named client of a project — the "who" half of consumer-driven contracts (CTG-4.1, #4479)';
COMMENT ON COLUMN consumer.tenant_id IS 'Owning tenant; a consumer is never readable outside it';
COMMENT ON COLUMN consumer.project_id IS 'Project this consumer consumes; deleting it removes the consumer';
COMMENT ON COLUMN consumer.slug IS 'Stable handle CI and Pact files name (lowercase, hyphenated)';
COMMENT ON COLUMN consumer.owner IS 'Free text: the team, squad, channel, or person accountable for this consumer';
COMMENT ON COLUMN consumer.contact IS 'Optional email or URL to notify when this consumer''s contract would break';
COMMENT ON COLUMN consumer.metadata IS 'Non-secret free-form context (repository, environment, CI job); never credentials';
COMMENT ON COLUMN consumer.deleted_at IS 'Retirement stamp; retired consumers keep their contracts readable';

-- ---------------------------------------------------------------------------------------------------
-- consumer_contract — one revision of a consumer's declared surface.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS consumer_contract (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL,
    consumer_id UUID NOT NULL,

    -- Per-consumer revision counter, starting at 1. Declaring a new surface never overwrites the
    -- previous one — "what did this consumer claim it used at the time" is a question a
    -- consumer-aware gate has to be able to answer after the fact.
    revision INTEGER NOT NULL
        CONSTRAINT consumer_contract_revision_check CHECK (revision >= 1),

    -- Exactly one revision per consumer is current; see the partial unique index below.
    is_current BOOLEAN NOT NULL DEFAULT TRUE,

    -- How the surface got here. ``pact`` came from an uploaded Pact document, ``manual`` from the
    -- UI picker (or an equivalent API call). Both are first-class; neither is a downgrade of the
    -- other.
    source TEXT NOT NULL DEFAULT 'manual'
        CONSTRAINT consumer_contract_source_check CHECK (source IN ('pact', 'manual')),

    -- The specification revision the pointers were resolved against. SET NULL rather than CASCADE:
    -- deleting a version makes a contract stale, and must not delete the declared surface.
    version_id UUID REFERENCES versions(id) ON DELETE SET NULL,
    version_label VARCHAR(128),

    -- The declared surface: ``{"operations": [{method, path, pointer, fields: [...]}, ...]}`` in
    -- the ``apiome.consumer.contract/v1`` shape. The document is the detail; the two counts and
    -- the pointer array beside it are what list reads and gates actually touch.
    surface JSONB NOT NULL DEFAULT '{"operations": []}'::jsonb
        CONSTRAINT consumer_contract_surface_object_check CHECK (jsonb_typeof(surface) = 'object'),
    operation_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT consumer_contract_operation_count_check CHECK (operation_count >= 0),
    field_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT consumer_contract_field_count_check CHECK (field_count >= 0),

    -- Every JSON Pointer this contract touches, flattened — operation pointers, field pointers,
    -- and the component-schema pointers a ``$ref`` resolved through. Same vocabulary the CTG-1.1
    -- classifier emits, which is precisely what makes the CTG-4.2 intersection an array operation
    -- rather than a document walk.
    surface_pointers TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],

    -- Interactions the importer could not resolve, one entry per interaction with a stable reason
    -- code. Never dropped silently: an import that could not place three of its interactions is a
    -- fact about the contract, not a detail of the import.
    unresolved JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT consumer_contract_unresolved_array_check CHECK (jsonb_typeof(unresolved) = 'array'),
    unresolved_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT consumer_contract_unresolved_count_check CHECK (unresolved_count >= 0),

    -- Provenance of a Pact import: the pact's own consumer/provider names, its specification
    -- version, and the sha256 of the uploaded document. Empty for a manual declaration.
    source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT consumer_contract_source_metadata_object_check
            CHECK (jsonb_typeof(source_metadata) = 'object'),
    source_digest TEXT
        CONSTRAINT consumer_contract_source_digest_shape_check
            CHECK (source_digest IS NULL OR source_digest ~ '^sha256:[0-9a-f]{64}$'),

    note TEXT,

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_label TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- A contract belongs to a consumer *of the same project*. Without the composite key, nothing
    -- would stop a row naming consumer A of project X while claiming project Y.
    CONSTRAINT consumer_contract_consumer_fk
        FOREIGN KEY (consumer_id, project_id)
        REFERENCES consumer (id, project_id) ON DELETE CASCADE,

    -- Revisions are dense and unique per consumer.
    CONSTRAINT consumer_contract_revision_key UNIQUE (consumer_id, revision)
);

-- Exactly one current revision per consumer. This is the invariant the "latest contract" read
-- depends on, so the database keeps it rather than the store remembering to.
CREATE UNIQUE INDEX IF NOT EXISTS idx_consumer_contract_current
    ON consumer_contract (consumer_id)
    WHERE is_current;

-- A consumer's revision history, newest first.
CREATE INDEX IF NOT EXISTS idx_consumer_contract_consumer
    ON consumer_contract (consumer_id, revision DESC);

-- "Every current contract in this project" — the project page's list read, and the candidate set
-- the CTG-4.2 intersection narrows to before it walks pointers.
CREATE INDEX IF NOT EXISTS idx_consumer_contract_project_current
    ON consumer_contract (project_id)
    WHERE is_current;

-- The intersection index: array overlap against a classified change's pointers.
CREATE INDEX IF NOT EXISTS idx_consumer_contract_pointers
    ON consumer_contract USING GIN (surface_pointers);

COMMENT ON TABLE consumer_contract IS
    'One immutable revision of a consumer''s declared operation/field surface, resolved against a stored version (CTG-4.1, #4479)';
COMMENT ON COLUMN consumer_contract.revision IS 'Per-consumer counter from 1; revisions are never overwritten';
COMMENT ON COLUMN consumer_contract.is_current IS 'Exactly one revision per consumer is current (partial unique index)';
COMMENT ON COLUMN consumer_contract.source IS 'pact (imported Pact document) | manual (UI picker or equivalent API call)';
COMMENT ON COLUMN consumer_contract.version_id IS 'Specification revision the pointers were resolved against; NULL once that version is deleted (stale, not false)';
COMMENT ON COLUMN consumer_contract.surface IS 'apiome.consumer.contract/v1 document: {"operations": [{method, path, pointer, fields}]}';
COMMENT ON COLUMN consumer_contract.surface_pointers IS
  'Flattened JSON Pointers this contract touches, in the CTG-1.1 classifier vocabulary; the CTG-4.2 intersection reads this, not the document';
COMMENT ON COLUMN consumer_contract.unresolved IS
  'Interactions that could not be resolved to an operation/field, one entry per interaction with a stable reason code. Never silently dropped.';
COMMENT ON COLUMN consumer_contract.source_metadata IS 'Pact provenance (consumer/provider names, pact specification version); empty for a manual declaration';
COMMENT ON COLUMN consumer_contract.source_digest IS 'sha256:<hex> of the uploaded Pact document, so a re-import of the same file is recognisable';

-- ---------------------------------------------------------------------------------------------------
-- RBAC: consumer_contracts resource in the built-in role grids.
-- ---------------------------------------------------------------------------------------------------
-- Full replacement of the V212 function body with 'consumer_contracts' added. The function rewrites
-- the built-in grids from scratch on every call and apiome-rest re-invokes it on demand, so
-- replacing it here and reseeding below is idempotent and self-healing for all tenants.
--
-- Grid rationale: registering your own service and declaring which operations it uses is developer
-- work — an Editor (which is also what a CI runner authenticating with an API key resolves to) gets
-- view, create, and edit. Deleting is not: a consumer record is what makes somebody else's change
-- visibly breaking, so removing one is an Owner/Admin decision.
CREATE OR REPLACE FUNCTION apiome.seed_builtin_roles(p_tenant UUID)
RETURNS void AS $$
DECLARE
    v_owner UUID;
    v_admin UUID;
    v_editor UUID;
    v_viewer UUID;
    -- Resources that behave like editable content (full CRUD for Editor).
    content_resources TEXT[] := ARRAY['projects','versions','classes','properties','paths','imports','api_keys'];
    all_resources TEXT[] := ARRAY['projects','versions','classes','properties','paths','types','imports','members','api_keys','billing','lint_findings','verification_targets','verification_evidence','consumer_contracts'];
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
    FOREACH r IN ARRAY content_resources LOOP
        INSERT INTO apiome.role_permissions (role_id, resource, action)
        SELECT v_editor, r, a FROM unnest(ARRAY['view','create','edit','delete']) AS a;
    END LOOP;
    INSERT INTO apiome.role_permissions (role_id, resource, action)
    SELECT v_editor, res, 'view' FROM unnest(ARRAY['types','members','billing','verification_targets']) AS res;
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
    'Idempotently (re)seed the four built-in roles and their canonical permission grids for a tenant (#3611; lint_findings added by #4859; verification_targets added by #4730; verification_evidence added by #4731; consumer_contracts added by #4479)';

COMMENT ON COLUMN apiome.role_permissions.resource IS
    'One of: projects, versions, classes, properties, paths, types, imports, members, api_keys, billing, lint_findings, verification_targets, verification_evidence, consumer_contracts';

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
