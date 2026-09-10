-- Package publishing pipelines — SDK-4.1 (#4495).
--
-- Downloading a zip is not how SDKs are consumed at scale: a team expects `npm install @acme/api`
-- and `pip install acme-api`. Publishing on a tenant's behalf needs two durable things that no
-- existing table holds — the credential that authorises the upload, and the ledger that decides
-- what version number the next upload claims. That is this migration.
--
--   sdk_registry_credentials — one tenant's (or one project's) npm / PyPI token, sealed.
--   sdk_publish_runs         — every publish attempt, and the regen counter it allocated.
--
-- Six rules shape the schema:
--
--   1. **The token is ciphertext, and only ciphertext.** `encrypted_token` is an envelope-encrypted
--      blob (AES-256-GCM data key wrapped by a versioned master key held in the environment — see
--      app.envelope_crypto), and `key_version` records which master key sealed it so the active key
--      can be rotated while older rows stay readable. The database cannot reconstruct a token, and
--      neither can a database backup. This is the V129 `mcp_endpoint_credentials` shape; SDK-4.1
--      seals under its own vault magic, so a blob cannot be moved between the two even under a
--      shared key.
--
--   2. **What can be shown about a token lives beside it, in the clear.** `token_metadata` holds
--      only non-secret facts — the public scheme prefix (`npm_`, `pypi-`), the length, and a
--      truncated SHA-256 — so a screen can say "this is the token you rotated on Tuesday" without
--      the API ever handing one back. There is deliberately no reveal path.
--
--   3. **Credentials override whole, settings merge by key.** SDK-3.4's `sdk_generation_settings`
--      (V255) merges tenant and project bodies field by field. A credential does not: half of one
--      token and half of another is not a credential, so a project row *replaces* the tenant row
--      for that ecosystem. Two partial unique indexes keep one row per (scope, ecosystem).
--
--   4. **The regen counter is a consequence of the ledger, not a column somewhere.** The published
--      package version is `major.minor.<counter>` where major/minor come from the version *line*
--      and the counter is how many releases that line's series has already had. Storing a counter
--      on a project row would drift from what was actually published; deriving it from the runs
--      that claimed a version cannot. `idx_sdk_publish_runs_claim` is what makes the derivation
--      safe under concurrency: two publishes that compute the same number cannot both insert, so
--      the loser retries with the next one instead of racing to the registry.
--
--   5. **A claim is made before the upload, not after.** A run is inserted `in_progress`, then
--      updated to its outcome. A `failed` run leaves the index predicate and frees its number
--      (nothing was published under it); a run that dies mid-upload stays `in_progress` and keeps
--      its number reserved — the safe failure, because the upload may well have landed.
--
--   6. **A run outlives its version, but not its project.** `version_id` is `ON DELETE SET NULL`:
--      the record that `@acme/widgets@1.4.2` was published from revision X must survive that
--      revision being deleted, or the provenance embedded in a package on npm points at nothing.
--      `project_id` and `tenant_id` cascade — a deleted project has no release history to keep.
--
-- **No new RBAC resource.** Storing a registry credential and publishing a package are both things
-- a project maintainer already does under `projects:edit` and `versions:publish`. Adding a resource
-- costs four synchronised edits (the role grid, the REST `Resource` enum, the enforcement call
-- sites, and the UI role matrix), and a permission that would always be granted alongside an
-- existing one earns none of them — the identical argument V254 (CTG-4.5) and V255 (SDK-3.4) made.
--
-- **No retention job.** SDK-1.1's artifact store and its retention policy were closed not-planned;
-- a run row is a few kilobytes of text and is the only record that a version number was consumed,
-- so it is kept. The event log inside `log` is capped by the application rather than by growth.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.sdk_publish_runs;
--   DROP TABLE IF EXISTS apiome.sdk_registry_credentials;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- sdk_registry_credentials — the sealed npm / PyPI token a publish authenticates with.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sdk_registry_credentials (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Scope (rule 3). ``project_id NULL`` is the tenant-wide credential; a row naming a project
    -- replaces it for that project only. Both cascade — a credential pointing at nothing would be
    -- invisible configuration that silently reappears if an id were ever reused.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,

    -- Which registry family this authenticates against. Constrained rather than free text: the
    -- application has exactly one upload transport per value, and an unknown one would be a
    -- credential nothing can ever use. ``gomod`` is absent on purpose — a Go module is released by
    -- pushing a tag (SDK-4.2), not by uploading to a registry.
    ecosystem VARCHAR(16) NOT NULL
        CONSTRAINT sdk_registry_credentials_ecosystem_check
            CHECK (ecosystem IN ('npm', 'pypi')),

    -- Where to publish. Defaulted by the application to the ecosystem's public registry, and
    -- required to be https — a publish token sent over plain HTTP is a token disclosed.
    registry_url TEXT NOT NULL,

    -- Rule 1: ciphertext only, plus the master-key version that sealed it.
    encrypted_token BYTEA NOT NULL,
    key_version INTEGER NOT NULL
        CONSTRAINT sdk_registry_credentials_key_version_check CHECK (key_version >= 1),

    -- Rule 2: what may be shown about the token, and nothing more.
    token_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT sdk_registry_credentials_metadata_object_check
            CHECK (jsonb_typeof(token_metadata) = 'object'),

    -- Provenance. ``ON DELETE SET NULL``: a departing user must not take a tenant's ability to
    -- publish with them.
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Rule 3, enforced: one tenant-wide credential per ecosystem…
CREATE UNIQUE INDEX IF NOT EXISTS idx_sdk_registry_credentials_tenant
    ON sdk_registry_credentials (tenant_id, ecosystem)
    WHERE project_id IS NULL;

-- …and at most one override per project per ecosystem.
CREATE UNIQUE INDEX IF NOT EXISTS idx_sdk_registry_credentials_project
    ON sdk_registry_credentials (tenant_id, project_id, ecosystem)
    WHERE project_id IS NOT NULL;

COMMENT ON TABLE sdk_registry_credentials IS
    'SDK-4.1 (#4495): a tenant''s (project_id NULL) or one project''s npm / PyPI publish token, '
    'stored as ciphertext only. A project row replaces the tenant row for that ecosystem — unlike '
    'sdk_generation_settings, a credential is atomic and does not merge.';

COMMENT ON COLUMN sdk_registry_credentials.encrypted_token IS
    'Envelope-encrypted {"token": "..."} payload (app.envelope_crypto, vault magic OSRV). Never '
    'plaintext; the database cannot reconstruct the token.';

COMMENT ON COLUMN sdk_registry_credentials.key_version IS
    'Which configured master key sealed this row, so the active key can be rotated while older '
    'rows stay readable. Bound into the GCM AAD, so a row cannot be re-tagged to another version.';

COMMENT ON COLUMN sdk_registry_credentials.token_metadata IS
    'Non-secret description of the token: its public scheme prefix, its length, and a truncated '
    'SHA-256. Enough to confirm a rotation; not enough to use.';

-- ---------------------------------------------------------------------------------------------------
-- sdk_publish_runs — one row per publish attempt, and the version number it claimed.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sdk_publish_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Rule 6: the revision this was built from, kept as provenance even if the revision is later
    -- deleted. The immutable coordinates are copied into ``provenance`` as well, because that is
    -- what was embedded in the package that is now on a public registry.
    version_id UUID REFERENCES versions(id) ON DELETE SET NULL,

    ecosystem VARCHAR(16) NOT NULL
        CONSTRAINT sdk_publish_runs_ecosystem_check CHECK (ecosystem IN ('npm', 'pypi')),

    -- ``dry_run`` validates the build, the credential and the version mapping and stops; it never
    -- claims a number (rule 4) and never contacts the registry.
    dry_run BOOLEAN NOT NULL DEFAULT FALSE,

    -- The lifecycle (rule 5). ``in_progress`` holds a claim while the upload is in flight;
    -- ``published`` and ``already_published`` both mean the version exists on the registry and
    -- must never be reused; ``failed`` releases the number; ``dry_run`` never held one.
    status VARCHAR(24) NOT NULL
        CONSTRAINT sdk_publish_runs_status_check
            CHECK (status IN ('in_progress', 'published', 'already_published', 'failed', 'dry_run')),

    -- The version-line → package-version mapping, recorded so it is auditable rather than merely
    -- recomputable. ``release_series`` is the key the counter was allocated under (``1.4``,
    -- ``1.5-beta``); ``regen_counter`` is which release of that series this is.
    version_line TEXT,
    release_series VARCHAR(64) NOT NULL,
    regen_counter INTEGER NOT NULL
        CONSTRAINT sdk_publish_runs_counter_check CHECK (regen_counter >= 0),

    package_name TEXT NOT NULL,
    package_version VARCHAR(128) NOT NULL,

    -- What was (or would have been) uploaded. The digest is what makes a dry-run checkable against
    -- the publish that follows it: the build is byte-deterministic, so the two must agree.
    artifact_sha256 VARCHAR(71),
    artifact_bytes INTEGER
        CONSTRAINT sdk_publish_runs_bytes_check CHECK (artifact_bytes IS NULL OR artifact_bytes >= 0),

    registry_url TEXT,
    credential_scope VARCHAR(16)
        CONSTRAINT sdk_publish_runs_credential_scope_check
            CHECK (credential_scope IS NULL OR credential_scope IN ('tenant', 'project')),

    -- The provenance embedded in the published package's own metadata, kept verbatim so an
    -- incident can compare what is on the registry with what this row says was sent.
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT sdk_publish_runs_provenance_object_check
            CHECK (jsonb_typeof(provenance) = 'object'),

    -- The step-by-step log. An array of objects, capped by the application. Every line is written
    -- through the redactor, so a registry error quoting a token cannot land here.
    log JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT sdk_publish_runs_log_array_check CHECK (jsonb_typeof(log) = 'array'),

    error_code VARCHAR(64),
    error_message TEXT,

    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL
);

-- Rule 4/5, enforced: within one project and ecosystem, a package version can be claimed once.
-- ``failed`` and ``dry_run`` rows are outside the predicate, so a failed attempt frees its number.
CREATE UNIQUE INDEX IF NOT EXISTS idx_sdk_publish_runs_claim
    ON sdk_publish_runs (tenant_id, project_id, ecosystem, package_version)
    WHERE status IN ('in_progress', 'published', 'already_published');

-- The counter query: "how far has this series got in this ecosystem?"
CREATE INDEX IF NOT EXISTS idx_sdk_publish_runs_series
    ON sdk_publish_runs (tenant_id, project_id, ecosystem, release_series, regen_counter DESC)
    WHERE status IN ('in_progress', 'published', 'already_published');

-- Listing a project's release history, newest first.
CREATE INDEX IF NOT EXISTS idx_sdk_publish_runs_history
    ON sdk_publish_runs (tenant_id, project_id, started_at DESC);

COMMENT ON TABLE sdk_publish_runs IS
    'SDK-4.1 (#4495): one row per package publish attempt. Also the ledger the regen counter is '
    'derived from — the package version is major.minor.<counter>, and this table is what says '
    'which counters a release series has already used.';

COMMENT ON COLUMN sdk_publish_runs.status IS
    'in_progress holds a version claim while an upload is in flight; published / already_published '
    'mean the version exists on the registry and must never be reused; failed releases the number; '
    'dry_run never held one.';

COMMENT ON COLUMN sdk_publish_runs.release_series IS
    'The key the regen counter was allocated under: major.minor from the version line, plus a '
    'prerelease tag when it has one (1.4, 1.5-beta). Lines 1.4.2 and 1.4.3 share a series, which '
    'is what stops them colliding on 1.4.0.';

COMMENT ON COLUMN sdk_publish_runs.log IS
    'Ordered publish events, each {at, step, level, message}. Written through the secret redactor: '
    'a registry error body quoting the credential is replaced before it is stored.';
