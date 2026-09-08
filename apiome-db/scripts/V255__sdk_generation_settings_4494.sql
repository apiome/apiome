-- SDK generation settings & branding — SDK-3.4 (#4494).
--
-- An organisation wants the code Apiome hands its consumers to carry the organisation's identity:
-- packages named under its own npm scope / PyPI naming pattern, its licence header on the source,
-- and its own user-agent on the traffic those clients generate. None of that is a property of any
-- single version, project row or generated file — it is tenant policy — so it needs one durable
-- home. That is this migration.
--
--   sdk_generation_settings — one tenant's (or one project's) generation defaults: the package
--                             name pattern per ecosystem, the licence header, and the user-agent.
--
-- Five rules shape the schema:
--
--   1. **Two scopes, one shape.** ``project_id IS NULL`` is the tenant-wide default; a row naming a
--      project overrides it for that project only. Two partial unique indexes keep exactly one row
--      per scope, so "the settings in force" is a pair of lookups rather than a reduction over
--      history. This is deliberately the CTG-4.5 ``deploy_gate_policy`` shape (V254) — a reader who
--      knows one knows the other.
--
--   2. **The override is per field, not per row.** Unlike V254 — where a project override replaces
--      the whole threshold body — a project that wants only its own user-agent must still inherit
--      its tenant's package pattern and licence header. The application therefore reads *both*
--      rows and merges them key by key, which is what makes rule 3 load-bearing.
--
--   3. **"Unset" and "set to nothing" are different answers.** A project whose body omits
--      ``licenseHeader`` inherits the tenant's; a project whose body carries
--      ``"licenseHeader": null`` has deliberately asked for none, and must not have the tenant's
--      re-applied. Only a JSONB body can express both, which is why every setting lives inside one
--      ``settings`` column rather than as nullable columns of its own.
--
--   4. **The row is mutable, and that is deliberate.** ECA-3.1's verification policy and IXH-2.3's
--      quality policy are append-only because a *stored* evaluation has to stay explicable against
--      the policy version it was judged under. These settings produce no stored verdict — they are
--      resolved on demand and every response carries their fingerprint inline — so there is no past
--      judgment for a version history to explain. Attribution of a change lives in
--      ``access_audit``, where every other governance edit is already recorded. Same argument as
--      CTG-4.5.
--
--   5. **Settings cannot outlive their scope.** Both foreign keys cascade: deleting a project drops
--      its override, deleting a tenant drops everything. Branding pointing at nothing would be
--      invisible configuration that silently reappears if an id were ever reused.
--
-- **No new RBAC resource.** Reading the settings in force is reading how a project is configured
-- (``projects:view``); changing them is ``projects:edit``. Adding a resource costs four
-- synchronised edits (the role grid, the REST ``Resource`` enum, the enforcement call sites, and
-- the UI role matrix), and a permission that would always be granted alongside an existing one
-- earns none of them — the identical argument CTG-4.4 and CTG-4.5 made.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.sdk_generation_settings;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- sdk_generation_settings — how generated artifacts are named and branded, for a tenant or one of
-- its projects.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sdk_generation_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Scope (rule 1). ``project_id NULL`` is the tenant-wide default; a row naming a project is
    -- that project's override. Both cascade (rule 5).
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,

    -- The settings themselves (rules 2 and 3), validated by the application against the documented
    -- ``sdk.generation-settings.v1`` shape before they reach this column. Stored as one body so an
    -- absent key (inherit the next scope up) and a null one (deliberately none) stay
    -- distinguishable.
    settings JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT sdk_generation_settings_object_check
            CHECK (jsonb_typeof(settings) = 'object'),

    -- SHA-256 over the canonical settings body. Every response that applies these settings carries
    -- the fingerprint of the *merged* result, so identical settings demonstrably produce identical
    -- artifacts — and a changed artifact can be attributed to changed branding rather than to a
    -- changed API.
    content_fingerprint VARCHAR(71) NOT NULL,

    -- Provenance. ``ON DELETE SET NULL``: a departing user must not take a tenant's branding with
    -- them.
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Rule 1, enforced: one tenant-wide default…
CREATE UNIQUE INDEX IF NOT EXISTS idx_sdk_generation_settings_tenant
    ON sdk_generation_settings (tenant_id)
    WHERE project_id IS NULL;

-- …and at most one override per project.
CREATE UNIQUE INDEX IF NOT EXISTS idx_sdk_generation_settings_project
    ON sdk_generation_settings (tenant_id, project_id)
    WHERE project_id IS NOT NULL;

COMMENT ON TABLE sdk_generation_settings IS
    'SDK-3.4 (#4494): generation defaults and branding for a tenant (project_id NULL) or one of its '
    'projects. At most one row per scope; the two scopes are merged key by key, and an absent row '
    'contributes nothing.';

COMMENT ON COLUMN sdk_generation_settings.settings IS
    'sdk.generation-settings.v1 body: packageNamePatterns (per ecosystem), licenseHeader and '
    'userAgent. An absent key inherits the next scope up; an explicit null means deliberately '
    'none, and blocks that inheritance.';

COMMENT ON COLUMN sdk_generation_settings.content_fingerprint IS
    'sha256: digest of this row''s canonical settings body. Responses carry the digest of the '
    'merged result, so identical settings produce identical, attributable artifacts.';
