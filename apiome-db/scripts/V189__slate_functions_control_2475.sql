-- Slate Edge functions and safe personalization control plane: route-matched functions, immutable
-- versions, secret references, deny-by-default capabilities and egress, personalization variants,
-- revision history, dual-control approval and redacted invocation evidence (UXE-3.3,
-- private-suite#2475).
--
-- Arbitrary code at the edge is the point at which a documentation platform stops being a
-- publisher and starts being a runtime. A function that can read whatever it likes leaks tenant
-- secrets; a function that can call whatever it likes turns the edge into an SSRF relay; a
-- personalization variant that forgets to say what it did to the cache key fragments a shared
-- cache into one entry per reader and quietly serves one person's page to another; and a variant
-- that reads a visitor's country or cohort without saying so moves personal data into a region
-- the tenant promised it would never reach. None of those are runtime bugs — they are missing
-- schema. This migration adds the control-plane schema for edge functions the way V187 added it
-- for cache and V188 for security: capabilities that are grants rather than settings, secrets that
-- are references rather than values, personalization whose cache and privacy effects are recorded
-- columns rather than folklore, and function changes that carry both an approval and a document to
-- revert to.
--
-- The shape here is not invented. `ROADMAP_AUTHORING_PLATFORM.md` §29.5 names the pieces
-- (route matcher, source/version, environment variables and secret references, region and data
-- policy, CPU and runtime limits, test requests, logs/traces and percentage rollout;
-- personalization variants showing audience rule, fallback, cache-key effect, analytics dimension
-- and privacy classification together; and the two flat prohibitions that no arbitrary function
-- may read tenant secrets or cross project boundaries, with egress and runtime capabilities
-- deny-by-default), and §29.7 assigns them to roles (the Platform operator gets functions; the
-- Publisher gets safe presets and never a runtime; the Auditor gets read-only policy and
-- exportable audit). These tables are that specification expressed in SQL, so the guarantees the
-- surface asserts are also enforced by the database rather than only by the process that writes to
-- it.
--
--   1. `apiome.slate_function_policies`          — one policy per environment. Owns the default
--                                                  region, residency class and CPU, memory and
--                                                  wall-clock ceilings, the optimistic-concurrency
--                                                  token, and whether a runtime is attached.
--   2. `apiome.slate_functions`                  — route-matched functions with an explicit
--                                                  precedence and a staged rollout.
--   3. `apiome.slate_function_versions`          — immutable source versions, content-addressed.
--   4. `apiome.slate_function_secret_refs`       — references to secrets, and nothing else. This
--                                                  table has no column able to hold a value.
--   5. `apiome.slate_function_capabilities`      — runtime capability grants. Deny-by-default is
--                                                  modelled as the absence of a row.
--   6. `apiome.slate_function_egress_rules`      — allowlisted egress destinations, same shape.
--   7. `apiome.slate_personalization_variants`   — audience rule, fallback, cache-key effect,
--                                                  analytics dimension, privacy class and consent
--                                                  basis, in one row so they cannot drift apart.
--   8. `apiome.slate_function_revisions`         — the body of every function as it was before
--                                                  each change, so a change can be reverted.
--   9. `apiome.slate_function_approvals`         — dual control. The author cannot be the
--                                                  approver.
--  10. `apiome.slate_function_invocations`       — simulated or observed invocations with
--                                                  allowlisted, expiring evidence.
--  11. `apiome.slate_function_audit`             — append-only; UPDATE and DELETE are refused.
--
-- Secrets are references, not values (acceptance criterion 1). §29.5 says no arbitrary function
-- can read tenant secrets. The obvious implementation is a value column plus a rule that nobody
-- writes plaintext into it, and that rule holds exactly as long as every future caller behaves.
-- `slate_function_secret_refs` instead has NO column capable of holding a secret: a name, an
-- alias the function code binds to, and a scope. That is a stronger claim than any CHECK, because
-- a CHECK constrains what may be written into a place that exists, while an absent column makes
-- the exposure a schema impossibility rather than a validation. Resolution happens at the runtime
-- boundary against whatever vault holds the material, and this table only ever records that a
-- function asked for it — which is also exactly what an auditor needs to read.
--
-- Deny-by-default, modelled as absence (acceptance criterion 2). §29.5 requires egress and runtime
-- capabilities to be deny-by-default. A `granted BOOLEAN NOT NULL DEFAULT FALSE` column would
-- express that, and it would also mean that a bug which wrote the wrong value granted something.
-- `slate_function_capabilities` and `slate_function_egress_rules` carry no such column: a row IS a
-- grant, and no row is a denial. The failure mode of a write bug is therefore a function that
-- cannot do its job — visible, loud and safe — rather than a function that can reach a network it
-- was never meant to. Both tables require `reason TEXT NOT NULL` and record `granted_by_actor_*`,
-- because the question at review is never what was granted but why, and an empty answer is the
-- one nobody can defend.
--
-- Personalization is only safe when its cache and privacy effects are stated (acceptance
-- criterion 3). §29.5 asks for audience rule, fallback, cache-key effect, analytics dimension and
-- privacy classification shown together, and they are stored together for the same reason: split
-- across tables they drift, and the drift is invisible until a shared cache serves one reader's
-- personalized page to another. `fallback_variant` is NOT NULL because a variant with no fallback
-- is an outage for everyone the audience rule does not match, and `privacy_class` is tied to
-- `consent_basis` by CHECK so a variant cannot be classified personal while claiming consent was
-- not required.
--
-- Staged rollout and revert (acceptance criterion 4). A function carries a `rollout_mode` and a
-- `rollout_percent`, exactly as a V188 security rule does. `simulate` records what the function
-- would have done and runs nothing, which is what makes a preview honest rather than a promise.
-- Every change writes its prior body to `slate_function_revisions`, whose `function_id` is
-- deliberately NOT a foreign key: a deleted function is exactly when a revert matters most, so the
-- history has to outlive the row it describes. Approvals compare immutable identity keys rather
-- than the nullable `users(id)` columns, because those are ON DELETE SET NULL and offboarding an
-- author must not turn a genuine two-person approval into two NULLs that no longer look distinct.
--
-- Residency and limits are declared before they are enforced (acceptance criterion 5). §29.5 names
-- region and data policy alongside CPU and runtime limits, and §29.6 goes on to distinguish where
-- function EXECUTION happens from where data is stored. The policy row therefore carries a default
-- region, a residency class ordered most-restrictive-first, and CPU, memory and wall-clock
-- ceilings, all of which a function may tighten and none of which it can silently exceed.
--
-- Scope boundary, stated plainly. `deploy/` in this repository is a single Caddyfile. There is no
-- isolate pool, no WASM runtime, no egress proxy and no CDN behind it, so nothing here executes
-- any code at all. These tables record function POLICY, its deterministic SIMULATION against a
-- test request, and the EVIDENCE and APPROVAL trail around every change — all of which are real,
-- persisted and auditable. What they do not do is run a function, because there is nothing to run
-- it in. An unenforced cache rule wastes a purge and an unenforced WAF rule leaves an attacker
-- unblocked; an imaginary function execution is worse than either, because a green "ran" row would
-- be evidence of an isolation guarantee that was never tested. So the boundary is enforced in
-- three places: `slate_function_policies.edge_attached` is FALSE for every row this system can
-- write; `CHECK (source <> 'edge-observed' OR edge_attached)` on `slate_function_invocations`
-- makes it impossible to record a real request that nothing observed; and
-- `CHECK (executed = FALSE OR edge_attached)` makes it impossible to claim that code ran. The
-- runtime tier is UXE-3.3's successor work; this is the control plane it will report into. V186
-- said the same thing about regions, V187 about eviction and V188 about mitigation, for the same
-- reason: a control plane that overstates its reach is worse than one that admits its edge, and a
-- control plane that claims to have executed untrusted code is not merely disappointing but a
-- false security record.

SET search_path TO apiome, public;

-- ─── 1. Function policy (one per environment) ────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_function_policies (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id               UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    site_id                 UUID NOT NULL REFERENCES apiome.slate_sites(id) ON DELETE CASCADE,
    -- Function posture is a property of a lane, not of a site: staging may let everything run in
    -- simulate while production admits nothing. UNIQUE makes "one policy per environment" a
    -- database fact rather than a convention the application is trusted to keep.
    environment_id          UUID NOT NULL UNIQUE
                            REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    -- Whether functions may exist on this lane at all. A lane that has never wanted a runtime
    -- should not have to express that by having zero rows in six other tables.
    functions_enabled       BOOLEAN NOT NULL DEFAULT FALSE,
    -- Optimistic-concurrency token, deliberately mirroring slate_cache_policies.policy_version and
    -- slate_security_policies.policy_version. Two operators editing functions during the same
    -- incident must not silently overwrite each other; the second writer matches zero rows.
    policy_version          BIGINT NOT NULL DEFAULT 0,
    -- Whether a managed runtime tier is wired to this lane. FALSE means every function here is
    -- recorded policy, not execution. Stored rather than inferred so that when a runtime is
    -- attached later, historical records stay truthful about what was true when written.
    edge_attached           BOOLEAN NOT NULL DEFAULT FALSE,
    -- NULL today. Named now so attaching a runtime is a data change, not a schema change.
    edge_provider           TEXT,
    -- Where functions run by default (§29.5 region and data policy). TEXT to match
    -- slate_release_regions.region_id, which is itself unconstrained: there is no canonical region
    -- registry to point at. 'auto' means the runtime picks, which is the only honest default while
    -- there is no runtime.
    default_region          TEXT NOT NULL DEFAULT 'auto',
    -- What crossing a border is allowed to mean. Ordered most-restrictive-first, and defaulted to
    -- the most restrictive value, because a residency promise that has to be opted into is a
    -- residency promise nobody made.
    default_residency_class TEXT NOT NULL DEFAULT 'in-region-only'
                            CHECK (default_residency_class IN ('in-region-only', 'region-pinned',
                                                               'unrestricted')),
    -- Ceilings a function may tighten and cannot exceed (§29.5 CPU and runtime limits). Stored on
    -- the lane rather than only per function so that adding a function cannot raise the lane's
    -- worst case without an audited policy write.
    default_cpu_ms_limit    INTEGER NOT NULL DEFAULT 50 CHECK (default_cpu_ms_limit > 0),
    default_memory_mb_limit INTEGER NOT NULL DEFAULT 128 CHECK (default_memory_mb_limit > 0),
    default_wall_ms_limit   INTEGER NOT NULL DEFAULT 5000 CHECK (default_wall_ms_limit > 0),
    created_at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by_actor_id     UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    updated_by_actor_name   TEXT NOT NULL,
    updated_by_actor_key    TEXT NOT NULL,
    -- Loosening residency is the single most consequential setting on this row, and §29.5 pairs
    -- region with data policy for exactly that reason. Recording WHY is the part that survives the
    -- review; the approval lives in slate_function_approvals.
    residency_waiver_reason TEXT,
    CONSTRAINT slate_function_policies_unrestricted_needs_reason
        CHECK (default_residency_class <> 'unrestricted' OR residency_waiver_reason IS NOT NULL)
);

COMMENT ON TABLE apiome.slate_function_policies IS
    'Function policy for one Slate environment (UXE-3.3, private-suite#2475): default region, residency class, CPU, memory and wall-clock ceilings, concurrency token and whether a runtime tier is attached.';
COMMENT ON COLUMN apiome.slate_function_policies.tenant_id IS
    'Owning tenant. Denormalized onto every slate_* table so queries and unique constraints stay tenant-scoped without multi-way joins.';
COMMENT ON COLUMN apiome.slate_function_policies.site_id IS
    'Site the environment belongs to, denormalized so policy lookups do not need a two-hop join.';
COMMENT ON COLUMN apiome.slate_function_policies.environment_id IS
    'Environment this policy governs. UNIQUE: a lane has exactly one function policy.';
COMMENT ON COLUMN apiome.slate_function_policies.functions_enabled IS
    'Whether functions may exist on this lane at all. FALSE by default: a runtime is opted into, never inherited.';
COMMENT ON COLUMN apiome.slate_function_policies.policy_version IS
    'Optimistic-concurrency token, incremented on every policy, function, capability or egress write. Mirrors slate_cache_policies and slate_security_policies; a stale expected value is refused, never merged.';
COMMENT ON COLUMN apiome.slate_function_policies.edge_attached IS
    'Whether a managed runtime tier serves this lane. FALSE for every row this system can currently write: there is nothing to execute code in, so a function records policy rather than behaviour.';
COMMENT ON COLUMN apiome.slate_function_policies.edge_provider IS
    'Name of the attached runtime tier, or NULL when none.';
COMMENT ON COLUMN apiome.slate_function_policies.default_region IS
    'Region functions run in by default. TEXT to match slate_release_regions.region_id; there is no canonical region registry to reference. auto means the runtime chooses.';
COMMENT ON COLUMN apiome.slate_function_policies.default_residency_class IS
    'in-region-only, region-pinned or unrestricted, most restrictive first. Defaulted to the most restrictive: a residency promise that must be opted into is one nobody made.';
COMMENT ON COLUMN apiome.slate_function_policies.default_cpu_ms_limit IS
    'Default CPU ceiling in milliseconds (roadmap §29.5). A function may tighten this and cannot exceed it.';
COMMENT ON COLUMN apiome.slate_function_policies.default_memory_mb_limit IS
    'Default memory ceiling in megabytes. A function may tighten this and cannot exceed it.';
COMMENT ON COLUMN apiome.slate_function_policies.default_wall_ms_limit IS
    'Default wall-clock ceiling in milliseconds, separate from CPU because a function that blocks on a slow origin burns no CPU and still holds a request open.';
COMMENT ON COLUMN apiome.slate_function_policies.created_at IS
    'When the policy row was created.';
COMMENT ON COLUMN apiome.slate_function_policies.updated_at IS
    'When the policy was last changed.';
COMMENT ON COLUMN apiome.slate_function_policies.updated_by_actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_function_policies.updated_by_actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_function_policies.updated_by_actor_key IS
    'Immutable identity of the actor captured at write time, so an offboarded operator still reads as a distinct person in history.';
COMMENT ON COLUMN apiome.slate_function_policies.residency_waiver_reason IS
    'Why residency was loosened to unrestricted. Required in that case: moving execution out of region with no stated reason is the change nobody can explain afterwards.';

CREATE INDEX IF NOT EXISTS idx_slate_function_policies_tenant
    ON apiome.slate_function_policies (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_function_policies_site
    ON apiome.slate_function_policies (site_id);

-- ─── 2. Functions ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_functions (
    id                     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id              UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id         UUID NOT NULL
                           REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    -- Explicit precedence, lower wins. The UNIQUE constraint below is half of "deterministic":
    -- without it, two functions could claim the same precedence and which one ran would depend on
    -- physical row order, making a simulation unreproducible.
    ordinal                INTEGER NOT NULL CHECK (ordinal >= 0),
    -- Disabling must not lose the function. A disabled function still appears in the simulation as
    -- considered-and-skipped, because "why did my function not run" is the question it answers.
    enabled                BOOLEAN NOT NULL DEFAULT FALSE,
    label                  TEXT NOT NULL,
    -- Deliberately the same four matcher kinds as slate_cache_rules and slate_security_rules: an
    -- operator who has learned what 'glob' means on one surface must not relearn it on another.
    matcher_kind           TEXT NOT NULL
                           CHECK (matcher_kind IN ('exact', 'prefix', 'glob', 'regex')),
    matcher_value          TEXT NOT NULL,
    matcher_methods        TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    matcher_hosts          TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    -- Execution environment. Enumerated so an unknown runtime cannot be stored, and ordered by how
    -- narrow the sandbox is: an isolate with no filesystem is a smaller blast radius than a WASM
    -- module with a host interface.
    runtime                TEXT NOT NULL DEFAULT 'js-isolate'
                           CHECK (runtime IN ('js-isolate', 'wasm')),
    -- Which immutable version is live. Deliberately a bare UUID with no foreign key:
    -- slate_function_versions references this table, so a reciprocal constraint would be a cycle
    -- that no single CREATE TABLE order can satisfy. Referential integrity here is one direction
    -- only, and the direction that matters is version -> function.
    active_version_id      UUID,
    -- Staged rollout (§29.5 percentage rollout). 'simulate' records what the function would have
    -- done and runs nothing; that is what makes a preview honest. Reaching enforce at 100 is a
    -- deliberate sequence of audited writes rather than one checkbox.
    rollout_mode           TEXT NOT NULL DEFAULT 'simulate'
                           CHECK (rollout_mode IN ('simulate', 'enforce')),
    rollout_percent        INTEGER NOT NULL DEFAULT 0
                           CHECK (rollout_percent BETWEEN 0 AND 100),
    -- Per-function overrides of the lane defaults. NULL means "inherit", which is different from
    -- "the same value as the lane happens to have today": an inheriting function follows a later
    -- policy change, and a pinned one deliberately does not.
    region                 TEXT,
    residency_class        TEXT
                           CHECK (residency_class IS NULL
                                  OR residency_class IN ('in-region-only', 'region-pinned',
                                                         'unrestricted')),
    cpu_ms_limit           INTEGER CHECK (cpu_ms_limit IS NULL OR cpu_ms_limit > 0),
    memory_mb_limit        INTEGER CHECK (memory_mb_limit IS NULL OR memory_mb_limit > 0),
    wall_ms_limit          INTEGER CHECK (wall_ms_limit IS NULL OR wall_ms_limit > 0),
    -- Names only. §29.5 lists environment variables next to secret references, and the difference
    -- between the two is the whole of criterion 1: a non-secret variable's value may live here,
    -- and a secret's may not live anywhere in this schema. See slate_function_secret_refs.
    env_var_names          TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    -- Warning reasons the operator explicitly accepted. Warnings only: hard refusals have no
    -- acknowledgement path, because the server is the authority on what is unsafe.
    acknowledged_warnings  TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    -- Content digest of the function body, so an approval can be checked against what actually
    -- shipped. Approving one body and shipping another must be detectable rather than unlikely.
    body_digest            TEXT NOT NULL CHECK (body_digest ~ '^sha256:[0-9a-f]{64}$'),
    revision               INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by_actor_id    UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_by_actor_name  TEXT NOT NULL,
    created_by_actor_kind  TEXT NOT NULL DEFAULT 'user'
                           CHECK (created_by_actor_kind IN ('user', 'automation')),
    UNIQUE (environment_id, ordinal),
    -- A function cannot be enforcing without a version to enforce. Without this, a rollout could be
    -- driven to 100% against no code at all and the simulation would happily report nothing.
    CONSTRAINT slate_functions_enforce_needs_version
        CHECK (rollout_mode <> 'enforce' OR active_version_id IS NOT NULL)
);

COMMENT ON TABLE apiome.slate_functions IS
    'Route-matched edge functions for one environment (UXE-3.3). Precedence is ordinal, lower wins; UNIQUE (environment_id, ordinal) makes evaluation a total order so a simulation is reproducible.';
COMMENT ON COLUMN apiome.slate_functions.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_functions.environment_id IS
    'Environment this function belongs to.';
COMMENT ON COLUMN apiome.slate_functions.ordinal IS
    'Precedence, lower wins. Unique per environment: two functions at the same precedence would make the winner depend on physical row order.';
COMMENT ON COLUMN apiome.slate_functions.enabled IS
    'Whether the function participates. FALSE by default, and a disabled function is retained and still reported by the simulation as considered-and-skipped.';
COMMENT ON COLUMN apiome.slate_functions.label IS
    'Operator-facing name, quoted verbatim by the simulation and by every invocation record.';
COMMENT ON COLUMN apiome.slate_functions.matcher_kind IS
    'How matcher_value is interpreted: exact, prefix, glob or regex. Deliberately the same four kinds as slate_cache_rules and slate_security_rules.';
COMMENT ON COLUMN apiome.slate_functions.matcher_value IS
    'The route pattern itself.';
COMMENT ON COLUMN apiome.slate_functions.matcher_methods IS
    'HTTP methods the function applies to. Empty means every method.';
COMMENT ON COLUMN apiome.slate_functions.matcher_hosts IS
    'Hosts the function is scoped to. Empty means every host on the lane.';
COMMENT ON COLUMN apiome.slate_functions.runtime IS
    'js-isolate or wasm, ordered by how narrow the sandbox is. CHECK-enumerated so an unknown runtime cannot be stored.';
COMMENT ON COLUMN apiome.slate_functions.active_version_id IS
    'The immutable version currently live, or NULL. Not a foreign key: slate_function_versions references this table, and a reciprocal constraint would be a cycle no CREATE TABLE order can satisfy.';
COMMENT ON COLUMN apiome.slate_functions.rollout_mode IS
    'simulate records what the function would have done and runs nothing; enforce runs it. Staged rollout is what keeps a bad function from reaching every reader at once.';
COMMENT ON COLUMN apiome.slate_functions.rollout_percent IS
    'Share of traffic the function applies to while being rolled out, 0 to 100.';
COMMENT ON COLUMN apiome.slate_functions.region IS
    'Region override, or NULL to inherit the lane default. NULL means inherit, which is different from pinning today''s lane value.';
COMMENT ON COLUMN apiome.slate_functions.residency_class IS
    'Residency override, or NULL to inherit the lane default. A function may only be as permissive as the lane allows; the service enforces that comparison.';
COMMENT ON COLUMN apiome.slate_functions.cpu_ms_limit IS
    'CPU ceiling override in milliseconds, or NULL to inherit. A function may tighten the lane ceiling and cannot exceed it.';
COMMENT ON COLUMN apiome.slate_functions.memory_mb_limit IS
    'Memory ceiling override in megabytes, or NULL to inherit.';
COMMENT ON COLUMN apiome.slate_functions.wall_ms_limit IS
    'Wall-clock ceiling override in milliseconds, or NULL to inherit.';
COMMENT ON COLUMN apiome.slate_functions.env_var_names IS
    'Names of non-secret environment variables the function reads. Names only; secret material has no column anywhere in this schema, and secret references live in slate_function_secret_refs.';
COMMENT ON COLUMN apiome.slate_functions.acknowledged_warnings IS
    'Warning reasons the operator accepted. Warnings only; hard refusals have no acknowledgement path.';
COMMENT ON COLUMN apiome.slate_functions.body_digest IS
    'sha256 over the canonical function body, so an approval can be checked against what shipped.';
COMMENT ON COLUMN apiome.slate_functions.revision IS
    'Monotonic revision counter. The previous body of each revision is kept in slate_function_revisions so any change can be reverted.';
COMMENT ON COLUMN apiome.slate_functions.created_at IS
    'When the function was created.';
COMMENT ON COLUMN apiome.slate_functions.updated_at IS
    'When the function was last changed.';
COMMENT ON COLUMN apiome.slate_functions.created_by_actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_functions.created_by_actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_functions.created_by_actor_kind IS
    'Whether a person or a system created the function.';

CREATE INDEX IF NOT EXISTS idx_slate_functions_environment
    ON apiome.slate_functions (environment_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_slate_functions_tenant
    ON apiome.slate_functions (tenant_id);
-- The rollout board asks for every function on a lane that is currently enforcing, which is a
-- small subset of a table that is mostly simulate. Partial, so the index stays the size of the
-- answer rather than the size of the table.
CREATE INDEX IF NOT EXISTS idx_slate_functions_enforcing
    ON apiome.slate_functions (environment_id, rollout_percent DESC)
    WHERE rollout_mode = 'enforce';
CREATE INDEX IF NOT EXISTS idx_slate_functions_active_version
    ON apiome.slate_functions (active_version_id)
    WHERE active_version_id IS NOT NULL;

-- ─── 3. Function versions (immutable) ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_function_versions (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id             UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id        UUID NOT NULL
                          REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    -- A version belongs to a live function, so unlike slate_function_revisions this one IS a
    -- foreign key: a version of a deleted function is not something anybody can promote.
    function_id           UUID NOT NULL
                          REFERENCES apiome.slate_functions(id) ON DELETE CASCADE,
    revision              INTEGER NOT NULL CHECK (revision >= 1),
    -- Content address of the source, so "which code is live" is answerable without trusting a
    -- mutable pointer. Rows here are written once and never updated; promoting a different version
    -- moves slate_functions.active_version_id rather than editing a version in place.
    source_digest         TEXT NOT NULL CHECK (source_digest ~ '^sha256:[0-9a-f]{64}$'),
    -- The complete version document: entrypoint, module graph, declared capabilities and the
    -- limits it asked for. JSONB rather than columns because it is an artifact manifest, and the
    -- authoritative copy of it must not be reshaped by a later migration.
    body                  JSONB NOT NULL,
    runtime               TEXT NOT NULL
                          CHECK (runtime IN ('js-isolate', 'wasm')),
    source_bytes          INTEGER CHECK (source_bytes IS NULL OR source_bytes >= 0),
    -- Where the source came from, so an artifact can be traced to a commit or an upload.
    source_origin         TEXT NOT NULL DEFAULT 'upload'
                          CHECK (source_origin IN ('upload', 'build', 'import')),
    source_ref            TEXT,
    created_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by_actor_id   UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_by_actor_name TEXT NOT NULL,
    UNIQUE (function_id, revision)
);

COMMENT ON TABLE apiome.slate_function_versions IS
    'Immutable, content-addressed source versions of a function (UXE-3.3). Rows are written once and never updated: promoting different code moves slate_functions.active_version_id rather than editing a version in place.';
COMMENT ON COLUMN apiome.slate_function_versions.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_function_versions.environment_id IS
    'Environment the function belongs to.';
COMMENT ON COLUMN apiome.slate_function_versions.function_id IS
    'Function this version belongs to. A real foreign key, unlike slate_function_revisions.function_id: a version of a deleted function is not something anybody can promote.';
COMMENT ON COLUMN apiome.slate_function_versions.revision IS
    'Which revision of that function this version is. Unique per function.';
COMMENT ON COLUMN apiome.slate_function_versions.source_digest IS
    'sha256 over the canonical source, so "which code is live" is answerable without trusting a mutable pointer.';
COMMENT ON COLUMN apiome.slate_function_versions.body IS
    'The complete version manifest: entrypoint, module graph, declared capabilities and requested limits. The authoritative copy, so it is not reshaped by a later migration.';
COMMENT ON COLUMN apiome.slate_function_versions.runtime IS
    'Runtime this version was built for. Recorded per version because changing runtime is a new version, never an edit.';
COMMENT ON COLUMN apiome.slate_function_versions.source_bytes IS
    'Size of the source in bytes, or NULL when unknown.';
COMMENT ON COLUMN apiome.slate_function_versions.source_origin IS
    'upload, build or import: how this version arrived, so an artifact can be traced back.';
COMMENT ON COLUMN apiome.slate_function_versions.source_ref IS
    'Commit, build id or upload reference the source came from, or NULL.';
COMMENT ON COLUMN apiome.slate_function_versions.created_at IS
    'When the version was recorded.';
COMMENT ON COLUMN apiome.slate_function_versions.created_by_actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_function_versions.created_by_actor_name IS
    'Display name of the actor, stored so history survives user deletion.';

CREATE INDEX IF NOT EXISTS idx_slate_function_versions_function
    ON apiome.slate_function_versions (function_id, revision DESC);
CREATE INDEX IF NOT EXISTS idx_slate_function_versions_tenant
    ON apiome.slate_function_versions (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_function_versions_digest
    ON apiome.slate_function_versions (source_digest);

-- ─── 4. Secret references (references only, never values) ────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_function_secret_refs (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id      UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id UUID NOT NULL
                   REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    function_id    UUID NOT NULL
                   REFERENCES apiome.slate_functions(id) ON DELETE CASCADE,
    -- The NAME of a secret in whatever vault holds the material. Resolution happens at the runtime
    -- boundary, never here, and this row is only ever the record that a function asked for it.
    secret_name    TEXT NOT NULL,
    -- The identifier the function code binds to, so rotating or renaming the underlying secret is
    -- a vault operation rather than a code change.
    alias          TEXT NOT NULL,
    -- How far the reference reaches. Ordered narrowest-first: a function-scoped reference is the
    -- default because §29.5 forbids a function crossing project boundaries, and the narrowest
    -- scope is the one that cannot.
    scope          TEXT NOT NULL DEFAULT 'function'
                   CHECK (scope IN ('function', 'environment')),
    created_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id       UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    actor_name     TEXT NOT NULL,
    UNIQUE (function_id, alias)
);

COMMENT ON TABLE apiome.slate_function_secret_refs IS
    'References to secrets a function may be given at the runtime boundary (UXE-3.3). This table has NO column capable of holding a secret value: only a name, an alias and a scope. That is stronger than a CHECK, because it makes exposure a schema impossibility rather than a validation somebody has to keep passing.';
COMMENT ON COLUMN apiome.slate_function_secret_refs.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_function_secret_refs.environment_id IS
    'Environment the function belongs to.';
COMMENT ON COLUMN apiome.slate_function_secret_refs.function_id IS
    'Function that declared the reference.';
COMMENT ON COLUMN apiome.slate_function_secret_refs.secret_name IS
    'Name of the secret in the vault that holds the material. A name, never the material: nothing in this schema can store a secret value.';
COMMENT ON COLUMN apiome.slate_function_secret_refs.alias IS
    'Identifier the function code binds to, so rotating or renaming the underlying secret is a vault operation rather than a code change.';
COMMENT ON COLUMN apiome.slate_function_secret_refs.scope IS
    'function or environment, narrowest first. function-scoped is the default because §29.5 forbids a function crossing project boundaries and the narrowest scope is the one that cannot.';
COMMENT ON COLUMN apiome.slate_function_secret_refs.created_at IS
    'When the reference was declared.';
COMMENT ON COLUMN apiome.slate_function_secret_refs.actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_function_secret_refs.actor_name IS
    'Display name of the actor, stored so history survives user deletion.';

CREATE INDEX IF NOT EXISTS idx_slate_function_secret_refs_function
    ON apiome.slate_function_secret_refs (function_id);
CREATE INDEX IF NOT EXISTS idx_slate_function_secret_refs_tenant
    ON apiome.slate_function_secret_refs (tenant_id);
-- "Which functions reference this secret" is the question asked at rotation and at offboarding,
-- and it is asked across an environment rather than within one function.
CREATE INDEX IF NOT EXISTS idx_slate_function_secret_refs_secret
    ON apiome.slate_function_secret_refs (environment_id, secret_name);

-- ─── 5. Runtime capabilities (deny-by-default: a row is a grant) ─────────────

CREATE TABLE IF NOT EXISTS apiome.slate_function_capabilities (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id             UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id        UUID NOT NULL
                          REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    function_id           UUID NOT NULL
                          REFERENCES apiome.slate_functions(id) ON DELETE CASCADE,
    -- The capability granted. Enumerated and ordered safest-first: reading geography is a smaller
    -- privilege than reading a secret, and writing a cookie is how a function reaches into a
    -- reader's session. There is deliberately no `granted BOOLEAN` column — see the table comment.
    capability            TEXT NOT NULL
                          CHECK (capability IN ('geo-read', 'env-read', 'kv-read', 'kv-write',
                                                'crypto-subtle', 'fetch-egress', 'cookie-write',
                                                'secret-read')),
    -- Why. NOT NULL because the question at review is never what was granted but why, and an empty
    -- answer is the one nobody can defend.
    reason                TEXT NOT NULL,
    -- A capability that cannot lapse becomes permanent by accident. NULL is a permanent grant and
    -- is deliberately possible, because a function that legitimately reads geography forever should
    -- not be re-granted weekly; the expiry exists for the incident grant that should not outlive
    -- the incident.
    expires_at            TIMESTAMP WITH TIME ZONE,
    granted_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    granted_by_actor_id   UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    granted_by_actor_name TEXT NOT NULL,
    granted_by_actor_key  TEXT NOT NULL,
    UNIQUE (function_id, capability),
    CONSTRAINT slate_function_capabilities_expiry_after_grant
        CHECK (expires_at IS NULL OR expires_at > granted_at)
);

COMMENT ON TABLE apiome.slate_function_capabilities IS
    'Runtime capability grants for a function (UXE-3.3). Deny-by-default is modelled as the ABSENCE of a row: a row is a grant, no row is a denial, and there is no granted flag to get wrong. A bug that fails to write cannot accidentally grant; it can only fail closed.';
COMMENT ON COLUMN apiome.slate_function_capabilities.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_function_capabilities.environment_id IS
    'Environment the function belongs to.';
COMMENT ON COLUMN apiome.slate_function_capabilities.function_id IS
    'Function the capability is granted to.';
COMMENT ON COLUMN apiome.slate_function_capabilities.capability IS
    'What the function may do, enumerated and ordered safest-first. Absence of a row for a capability is the denial; there is no boolean to flip the wrong way.';
COMMENT ON COLUMN apiome.slate_function_capabilities.reason IS
    'Why the capability was granted. NOT NULL: an unexplained privilege is the one nobody can justify at review.';
COMMENT ON COLUMN apiome.slate_function_capabilities.expires_at IS
    'When the grant lapses, or NULL for a permanent grant. The expiry exists for the incident grant that should not outlive the incident.';
COMMENT ON COLUMN apiome.slate_function_capabilities.granted_at IS
    'When the grant was made.';
COMMENT ON COLUMN apiome.slate_function_capabilities.granted_by_actor_id IS
    'Granting user, when still present.';
COMMENT ON COLUMN apiome.slate_function_capabilities.granted_by_actor_name IS
    'Display name of the granter, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_function_capabilities.granted_by_actor_key IS
    'Immutable identity of the granter captured at write time, so offboarding cannot erase who widened a function''s privileges.';

CREATE INDEX IF NOT EXISTS idx_slate_function_capabilities_function
    ON apiome.slate_function_capabilities (function_id);
CREATE INDEX IF NOT EXISTS idx_slate_function_capabilities_tenant
    ON apiome.slate_function_capabilities (tenant_id);
-- "Who on this lane can read secrets" is the standing privilege review, and it is asked by
-- capability across an environment rather than per function.
CREATE INDEX IF NOT EXISTS idx_slate_function_capabilities_capability
    ON apiome.slate_function_capabilities (environment_id, capability);
CREATE INDEX IF NOT EXISTS idx_slate_function_capabilities_expiry
    ON apiome.slate_function_capabilities (expires_at)
    WHERE expires_at IS NOT NULL;

-- ─── 6. Egress rules (deny-by-default: a row is an allowlist entry) ──────────

CREATE TABLE IF NOT EXISTS apiome.slate_function_egress_rules (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id             UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id        UUID NOT NULL
                          REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    function_id           UUID NOT NULL
                          REFERENCES apiome.slate_functions(id) ON DELETE CASCADE,
    -- How destination is matched. Ordered narrowest-first: an exact host is a smaller hole than a
    -- suffix, and there is deliberately no 'any' kind, because an egress allowlist with a wildcard
    -- is a denylist wearing a costume.
    destination_kind      TEXT NOT NULL
                          CHECK (destination_kind IN ('exact-host', 'host-suffix')),
    destination           TEXT NOT NULL,
    scheme                TEXT NOT NULL DEFAULT 'https'
                          CHECK (scheme IN ('https', 'http')),
    -- NULL means the scheme's default port. A named port is narrower, so it is preferred where the
    -- destination is known precisely.
    port                  INTEGER CHECK (port IS NULL OR port BETWEEN 1 AND 65535),
    methods               TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    -- Why, for the same reason capabilities carry one.
    reason                TEXT NOT NULL,
    expires_at            TIMESTAMP WITH TIME ZONE,
    granted_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    granted_by_actor_id   UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    granted_by_actor_name TEXT NOT NULL,
    granted_by_actor_key  TEXT NOT NULL,
    UNIQUE (function_id, destination_kind, destination),
    CONSTRAINT slate_function_egress_rules_expiry_after_grant
        CHECK (expires_at IS NULL OR expires_at > granted_at)
);

COMMENT ON TABLE apiome.slate_function_egress_rules IS
    'Allowlisted egress destinations for a function (UXE-3.3). Deny-by-default in the same shape as capabilities: a row is an allowlist entry, no row is a denial, and there is no wildcard kind, because an egress allowlist with a wildcard is a denylist wearing a costume.';
COMMENT ON COLUMN apiome.slate_function_egress_rules.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_function_egress_rules.environment_id IS
    'Environment the function belongs to.';
COMMENT ON COLUMN apiome.slate_function_egress_rules.function_id IS
    'Function permitted to reach the destination.';
COMMENT ON COLUMN apiome.slate_function_egress_rules.destination_kind IS
    'exact-host or host-suffix, narrowest first. There is no wildcard kind: unrestricted egress is expressed by no row existing and being refused, never by a rule that permits everything.';
COMMENT ON COLUMN apiome.slate_function_egress_rules.destination IS
    'The host or host suffix the function may reach.';
COMMENT ON COLUMN apiome.slate_function_egress_rules.scheme IS
    'https or http. https first because a plaintext egress hop is the one that leaks in transit.';
COMMENT ON COLUMN apiome.slate_function_egress_rules.port IS
    'Port the rule permits, or NULL for the scheme default. A named port is narrower and preferred where the destination is known precisely.';
COMMENT ON COLUMN apiome.slate_function_egress_rules.methods IS
    'HTTP methods permitted. Empty means every method, which is why a narrow destination matters more than a narrow method list.';
COMMENT ON COLUMN apiome.slate_function_egress_rules.reason IS
    'Why this destination is reachable. NOT NULL: an unexplained hole in an allowlist is the one nobody can justify at review.';
COMMENT ON COLUMN apiome.slate_function_egress_rules.expires_at IS
    'When the allowance lapses, or NULL for a permanent one.';
COMMENT ON COLUMN apiome.slate_function_egress_rules.granted_at IS
    'When the allowance was made.';
COMMENT ON COLUMN apiome.slate_function_egress_rules.granted_by_actor_id IS
    'Granting user, when still present.';
COMMENT ON COLUMN apiome.slate_function_egress_rules.granted_by_actor_name IS
    'Display name of the granter, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_function_egress_rules.granted_by_actor_key IS
    'Immutable identity of the granter captured at write time.';

CREATE INDEX IF NOT EXISTS idx_slate_function_egress_rules_function
    ON apiome.slate_function_egress_rules (function_id);
CREATE INDEX IF NOT EXISTS idx_slate_function_egress_rules_tenant
    ON apiome.slate_function_egress_rules (tenant_id);
-- "What can this lane reach" is the SSRF review question, asked by destination across an
-- environment rather than per function.
CREATE INDEX IF NOT EXISTS idx_slate_function_egress_rules_destination
    ON apiome.slate_function_egress_rules (environment_id, destination);
CREATE INDEX IF NOT EXISTS idx_slate_function_egress_rules_expiry
    ON apiome.slate_function_egress_rules (expires_at)
    WHERE expires_at IS NOT NULL;

-- ─── 7. Personalization variants ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_personalization_variants (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id      UUID NOT NULL
                        REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    function_id         UUID NOT NULL
                        REFERENCES apiome.slate_functions(id) ON DELETE CASCADE,
    ordinal             INTEGER NOT NULL CHECK (ordinal >= 0),
    label               TEXT NOT NULL,
    -- What the audience is decided on. Ordered least-identifying-first: a country is coarser than
    -- a cohort, and a cohort is coarser than an experiment assignment tied to a single reader.
    audience_kind       TEXT NOT NULL
                        CHECK (audience_kind IN ('geo', 'language', 'device', 'cohort',
                                                 'experiment')),
    -- The predicate itself. JSONB because it is a list of heterogeneous conditions and the
    -- simulation records which one failed.
    audience_matcher    JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- What every reader the audience rule does not match receives. NOT NULL: a variant with no
    -- fallback is an outage for the majority, and "the audience rule matched nobody" is the
    -- ordinary case on the day an experiment ends.
    fallback_variant    TEXT NOT NULL,
    -- §29.5 requires the cache-key effect to be shown next to the audience rule, and it is stored
    -- next to it for the same reason: split apart, the two drift, and the drift is invisible until
    -- a shared cache serves one reader's personalized page to another. Ordered safest-first.
    cache_key_effect    TEXT NOT NULL DEFAULT 'none'
                        CHECK (cache_key_effect IN ('none', 'vary-on-dimension', 'bypass-cache')),
    -- The dimension this variant reports under, so a release-correlated metric can attribute a
    -- regression to the variant that caused it rather than to the release as a whole.
    analytics_dimension TEXT NOT NULL,
    -- §29.5 privacy classification. Ordered least-personal-first, and tied to consent_basis by the
    -- CHECK below so a variant cannot be marked personal while claiming consent was not required.
    privacy_class       TEXT NOT NULL DEFAULT 'non-personal'
                        CHECK (privacy_class IN ('non-personal', 'pseudonymous', 'personal')),
    -- Ordered by how defensible the basis is: explicit consent is stronger than an assertion of
    -- legitimate interest, and not-required is only honest for non-personal data.
    consent_basis       TEXT NOT NULL DEFAULT 'not-required'
                        CHECK (consent_basis IN ('not-required', 'explicit-consent',
                                                 'legitimate-interest')),
    enabled             BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id            UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    actor_name          TEXT NOT NULL,
    UNIQUE (function_id, ordinal),
    -- Classifying a variant personal and simultaneously claiming no consent was needed is not a
    -- configuration, it is a contradiction. Refused here rather than caught at review.
    CONSTRAINT slate_personalization_variants_personal_needs_basis
        CHECK (privacy_class <> 'personal' OR consent_basis <> 'not-required'),
    -- A variant that personalizes without touching the cache key is a shared cache entry that
    -- differs per reader, which is the exact defect §29.3 refuses for cache. Anything above
    -- non-personal must say what it did to the key.
    CONSTRAINT slate_personalization_variants_personal_needs_cache_effect
        CHECK (privacy_class = 'non-personal' OR cache_key_effect <> 'none')
);

COMMENT ON TABLE apiome.slate_personalization_variants IS
    'Personalization variants for a function (UXE-3.3): audience rule, fallback, cache-key effect, analytics dimension, privacy class and consent basis in one row, because §29.5 requires them shown together and split across tables they drift.';
COMMENT ON COLUMN apiome.slate_personalization_variants.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_personalization_variants.environment_id IS
    'Environment the variant applies to.';
COMMENT ON COLUMN apiome.slate_personalization_variants.function_id IS
    'Function that selects between variants.';
COMMENT ON COLUMN apiome.slate_personalization_variants.ordinal IS
    'Precedence among the variants of one function, lower wins. Unique per function so selection is a total order.';
COMMENT ON COLUMN apiome.slate_personalization_variants.label IS
    'Operator-facing name, quoted verbatim by the simulation and by every invocation record.';
COMMENT ON COLUMN apiome.slate_personalization_variants.audience_kind IS
    'What the audience is decided on: geo, language, device, cohort or experiment, least identifying first.';
COMMENT ON COLUMN apiome.slate_personalization_variants.audience_matcher IS
    'JSON list of audience predicates. The simulation records which predicate failed.';
COMMENT ON COLUMN apiome.slate_personalization_variants.fallback_variant IS
    'What every reader the audience rule does not match receives. NOT NULL: a variant with no fallback is an outage for the majority.';
COMMENT ON COLUMN apiome.slate_personalization_variants.cache_key_effect IS
    'none, vary-on-dimension or bypass-cache. Stored beside the audience rule because split apart the two drift, and the drift is invisible until a shared cache serves one reader''s page to another.';
COMMENT ON COLUMN apiome.slate_personalization_variants.analytics_dimension IS
    'Dimension this variant reports under, so a regression can be attributed to the variant rather than to the release as a whole.';
COMMENT ON COLUMN apiome.slate_personalization_variants.privacy_class IS
    'non-personal, pseudonymous or personal, least personal first. CHECK-tied to consent_basis and to cache_key_effect so a personalizing variant cannot stay silent about either.';
COMMENT ON COLUMN apiome.slate_personalization_variants.consent_basis IS
    'not-required, explicit-consent or legitimate-interest, ordered by how defensible the basis is. not-required is only honest for non-personal data.';
COMMENT ON COLUMN apiome.slate_personalization_variants.enabled IS
    'Whether the variant participates. FALSE by default: personalization is opted into.';
COMMENT ON COLUMN apiome.slate_personalization_variants.created_at IS
    'When the variant was created.';
COMMENT ON COLUMN apiome.slate_personalization_variants.updated_at IS
    'When the variant was last changed.';
COMMENT ON COLUMN apiome.slate_personalization_variants.actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_personalization_variants.actor_name IS
    'Display name of the actor, stored so history survives user deletion.';

CREATE INDEX IF NOT EXISTS idx_slate_personalization_variants_function
    ON apiome.slate_personalization_variants (function_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_slate_personalization_variants_tenant
    ON apiome.slate_personalization_variants (tenant_id);
-- The privacy review asks for every variant on a lane above non-personal, which is a small subset
-- of a table that is mostly non-personal.
CREATE INDEX IF NOT EXISTS idx_slate_personalization_variants_privacy
    ON apiome.slate_personalization_variants (environment_id, privacy_class)
    WHERE privacy_class <> 'non-personal';

-- ─── 8. Function revisions ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_function_revisions (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id      UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id UUID NOT NULL
                   REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    -- Deliberately NOT a foreign key. A deleted function is exactly the case where "revert my
    -- change" is most needed, so the revision history has to outlive the row it describes. A FK
    -- with CASCADE would delete the evidence at the moment it is wanted, and one with RESTRICT
    -- would make the function undeletable. slate_function_versions takes the opposite decision on
    -- purpose: a version is for promoting, and a revision is for remembering.
    function_id    UUID NOT NULL,
    revision       INTEGER NOT NULL CHECK (revision >= 1),
    -- The complete function body as it was, so reverting is applying a stored document rather than
    -- reconstructing intent from an audit sentence.
    body           JSONB NOT NULL,
    body_digest    TEXT NOT NULL CHECK (body_digest ~ '^sha256:[0-9a-f]{64}$'),
    -- What produced this revision, so a revert of a revert reads correctly in history.
    change_kind    TEXT NOT NULL
                   CHECK (change_kind IN ('created', 'updated', 'disabled', 'deleted',
                                          'reverted', 'rollout-changed', 'version-added')),
    at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id       UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    actor_name     TEXT NOT NULL,
    UNIQUE (function_id, revision)
);

COMMENT ON TABLE apiome.slate_function_revisions IS
    'The body of every function as it was before each change (UXE-3.3), so a change can be reverted by applying a stored document rather than reconstructing intent from a sentence.';
COMMENT ON COLUMN apiome.slate_function_revisions.tenant_id IS
    'Owning tenant. Denormalized because this table cannot reach a tenant through its function: that function may already be gone.';
COMMENT ON COLUMN apiome.slate_function_revisions.environment_id IS
    'Environment the function belonged to.';
COMMENT ON COLUMN apiome.slate_function_revisions.function_id IS
    'Function this revision describes. Not a foreign key: a deleted function is exactly when a revert is most needed, so history must outlive the row.';
COMMENT ON COLUMN apiome.slate_function_revisions.revision IS
    'Which revision of that function this body was.';
COMMENT ON COLUMN apiome.slate_function_revisions.body IS
    'The complete function body, so reverting applies a stored document rather than reconstructing intent from a sentence.';
COMMENT ON COLUMN apiome.slate_function_revisions.body_digest IS
    'sha256 over the canonical body, matching slate_functions.body_digest at that revision.';
COMMENT ON COLUMN apiome.slate_function_revisions.change_kind IS
    'What produced this revision, so a revert of a revert reads correctly in history. version-added is included because promoting new code is a change to the function even when nothing else moved.';
COMMENT ON COLUMN apiome.slate_function_revisions.at IS
    'When the change happened.';
COMMENT ON COLUMN apiome.slate_function_revisions.actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_function_revisions.actor_name IS
    'Display name of the actor, stored so history survives user deletion.';

CREATE INDEX IF NOT EXISTS idx_slate_function_revisions_function
    ON apiome.slate_function_revisions (function_id, revision DESC);
CREATE INDEX IF NOT EXISTS idx_slate_function_revisions_environment
    ON apiome.slate_function_revisions (environment_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_function_revisions_tenant
    ON apiome.slate_function_revisions (tenant_id, at DESC);

-- ─── 9. Approvals (dual control) ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_function_approvals (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id      UUID NOT NULL
                        REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    subject_kind        TEXT NOT NULL
                        CHECK (subject_kind IN ('policy', 'function', 'version', 'capability',
                                                'egress-rule', 'variant')),
    subject_id          TEXT NOT NULL,
    -- What was approved, content-addressed. An approval that names only a row id would still look
    -- valid after that row changed underneath it; a digest makes a stale approval detectable.
    digest              TEXT NOT NULL CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
    author_actor_id     UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    author_actor_name   TEXT NOT NULL,
    -- Immutable identity captured at write time. The distinctness CHECK compares these rather than
    -- the nullable user ids above, because those are ON DELETE SET NULL and a deleted user would
    -- turn a genuine two-person approval into two NULLs that no longer look distinct. A constraint
    -- that weakens when somebody is offboarded is not a constraint.
    author_actor_key    TEXT NOT NULL,
    approver_actor_id   UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    approver_actor_name TEXT NOT NULL,
    approver_actor_key  TEXT NOT NULL,
    approved_at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note                TEXT,
    -- Two-person review, as a database fact rather than an application convention, matching V188's
    -- slate_security_approvals and unlike V186's slate_release_approvals.
    CONSTRAINT slate_function_approvals_distinct_actors
        CHECK (approver_actor_key <> author_actor_key),
    -- One approver approves a given body once. Without this, a single approver could satisfy a
    -- two-approval requirement by pressing the button twice.
    UNIQUE (subject_id, digest, approver_actor_key)
);

COMMENT ON TABLE apiome.slate_function_approvals IS
    'Dual-control approvals for function, capability, egress and variant changes (UXE-3.3). The author cannot be the approver, and that is enforced by CHECK on immutable identity keys rather than by convention.';
COMMENT ON COLUMN apiome.slate_function_approvals.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_function_approvals.environment_id IS
    'Environment the approved change applies to.';
COMMENT ON COLUMN apiome.slate_function_approvals.subject_kind IS
    'What was approved: the policy, a function, a version, a capability grant, an egress rule or a personalization variant.';
COMMENT ON COLUMN apiome.slate_function_approvals.subject_id IS
    'Id of the subject. TEXT so a subject identified by something other than a UUID still fits.';
COMMENT ON COLUMN apiome.slate_function_approvals.digest IS
    'sha256 over the canonical body that was approved. An approval naming only a row id would still look valid after that row changed underneath it.';
COMMENT ON COLUMN apiome.slate_function_approvals.author_actor_id IS
    'User who proposed the change, when still present.';
COMMENT ON COLUMN apiome.slate_function_approvals.author_actor_name IS
    'Display name of the author, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_function_approvals.author_actor_key IS
    'Immutable identity of the author captured at write time. The distinctness CHECK uses this, not the nullable user id, so offboarding cannot weaken a recorded approval.';
COMMENT ON COLUMN apiome.slate_function_approvals.approver_actor_id IS
    'User who approved, when still present.';
COMMENT ON COLUMN apiome.slate_function_approvals.approver_actor_name IS
    'Display name of the approver, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_function_approvals.approver_actor_key IS
    'Immutable identity of the approver captured at write time.';
COMMENT ON COLUMN apiome.slate_function_approvals.approved_at IS
    'When the approval was recorded.';
COMMENT ON COLUMN apiome.slate_function_approvals.note IS
    'Optional reviewer note.';

CREATE INDEX IF NOT EXISTS idx_slate_function_approvals_subject
    ON apiome.slate_function_approvals (subject_id, digest);
CREATE INDEX IF NOT EXISTS idx_slate_function_approvals_environment
    ON apiome.slate_function_approvals (environment_id, approved_at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_function_approvals_tenant
    ON apiome.slate_function_approvals (tenant_id, approved_at DESC);

-- ─── 10. Invocations ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_function_invocations (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id      UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id UUID NOT NULL
                   REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Where the record came from. 'policy-simulation' is a deterministic evaluation of stored
    -- policy against a test request; 'edge-observed' is a real request something in the path
    -- actually saw. The CHECK below makes the second impossible without a runtime, so this column
    -- cannot quietly become a claim nothing supports.
    source         TEXT NOT NULL DEFAULT 'policy-simulation'
                   CHECK (source IN ('policy-simulation', 'edge-observed')),
    -- Function UUID as text. No foreign key: an invocation record must survive the deletion of the
    -- function that produced it, which is precisely the case an investigation cares about.
    function_ref   TEXT NOT NULL,
    function_label TEXT NOT NULL,
    -- Free text with no FK. slate_release_changed_pages carries only per-release CHANGED routes,
    -- so it is not a route inventory and cannot be the referent for an arbitrary request path.
    route          TEXT NOT NULL,
    method         TEXT NOT NULL DEFAULT 'GET',
    release_id     UUID REFERENCES apiome.slate_releases(id) ON DELETE SET NULL,
    -- TEXT to match slate_release_regions.region_id, which is itself unconstrained.
    region         TEXT,
    -- Which personalization variant was selected, or NULL when the function does not personalize.
    variant_ref    TEXT,
    -- What the evaluation concluded, ordered from "nothing happened" to "something went wrong".
    -- 'would-run' is what a simulated enforcing function reports, and is the honest counterpart of
    -- 'ran', which nothing in this repository can currently write.
    outcome        TEXT NOT NULL
                   CHECK (outcome IN ('skipped', 'would-run', 'ran', 'refused',
                                      'capability-denied', 'egress-denied', 'limit-exceeded',
                                      'error')),
    -- Whether code actually executed. FALSE for everything this system can currently write; the
    -- CHECK ties it to a runtime so a simulation can never claim an execution.
    executed       BOOLEAN NOT NULL DEFAULT FALSE,
    -- Snapshot of the policy's edge_attached at invocation time, denormalized rather than joined
    -- for the same reason slate_security_events snapshots it: attaching an edge later must not
    -- make old rows look real.
    edge_attached  BOOLEAN NOT NULL DEFAULT FALSE,
    -- Resource usage, NULL for a simulation because a simulation consumed none of it. Storing a
    -- zero would be a measurement; NULL is the absence of one.
    cpu_ms         INTEGER CHECK (cpu_ms IS NULL OR cpu_ms >= 0),
    wall_ms        INTEGER CHECK (wall_ms IS NULL OR wall_ms >= 0),
    memory_peak_mb INTEGER CHECK (memory_peak_mb IS NULL OR memory_peak_mb >= 0),
    -- Why a denial happened, quoted verbatim from the refusing rule so the UI does not restate it.
    denial_reason  TEXT,
    -- Redacted request evidence. Constrained to an ALLOWLIST by the CHECK below rather than
    -- filtered by a denylist, because a denylist fails open on the field nobody thought of. This
    -- matters more for functions than it did for security events: a function's inputs are the
    -- request, so an unconstrained evidence blob would be a verbatim copy of it.
    evidence       JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Request data is a liability, not an asset. An audit row should live forever; a captured user
    -- agent should not.
    retain_until   TIMESTAMP WITH TIME ZONE NOT NULL,
    -- `jsonb - text[]` removes every listed key, so the result is empty only when every key present
    -- was one of the permitted ones. A subquery or a set-returning function cannot appear in a
    -- CHECK, and this expression is both scalar and immutable. Adding a key to this list is a
    -- migration that has to justify itself; storing `authorization` or `cookie` is impossible.
    CONSTRAINT slate_function_invocations_evidence_allowlisted
        CHECK (evidence - ARRAY['method', 'path', 'query', 'userAgent', 'country', 'region',
                                'clientIpPrefix', 'variant', 'outcome', 'statusCode',
                                'denialReason', 'cpuMs', 'wallMs'] = '{}'::jsonb),
    CONSTRAINT slate_function_invocations_retention_after_invocation
        CHECK (retain_until > at),
    -- Nothing was observed, because there is nothing in the request path to observe it.
    CONSTRAINT slate_function_invocations_observed_needs_edge
        CHECK (source <> 'edge-observed' OR edge_attached),
    -- Nothing executed, for the same reason.
    CONSTRAINT slate_function_invocations_executed_needs_edge
        CHECK (executed = FALSE OR edge_attached)
);

COMMENT ON TABLE apiome.slate_function_invocations IS
    'Function invocation records (UXE-3.3) joining function, route, release, region, variant and outcome with allowlisted, expiring request evidence. Simulated evaluations until a runtime tier is attached.';
COMMENT ON COLUMN apiome.slate_function_invocations.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_function_invocations.environment_id IS
    'Environment the invocation belongs to.';
COMMENT ON COLUMN apiome.slate_function_invocations.at IS
    'When the invocation was recorded.';
COMMENT ON COLUMN apiome.slate_function_invocations.source IS
    'policy-simulation (a deterministic evaluation of stored policy) or edge-observed (a request something in the path actually saw). The latter requires an attached runtime tier.';
COMMENT ON COLUMN apiome.slate_function_invocations.function_ref IS
    'Function UUID as text. No foreign key: an invocation must survive deletion of the function that produced it, which is exactly the case an investigation cares about.';
COMMENT ON COLUMN apiome.slate_function_invocations.function_label IS
    'The function label as it read at the time, so history does not change meaning when a function is renamed.';
COMMENT ON COLUMN apiome.slate_function_invocations.route IS
    'Request path. Free text with no FK: slate_release_changed_pages holds only per-release changed routes and is not a route inventory.';
COMMENT ON COLUMN apiome.slate_function_invocations.method IS
    'Request method.';
COMMENT ON COLUMN apiome.slate_function_invocations.release_id IS
    'Release active at the time, or NULL. SET NULL rather than CASCADE: the invocation record outlives the release.';
COMMENT ON COLUMN apiome.slate_function_invocations.region IS
    'Region that would have handled the request. TEXT to match slate_release_regions.region_id.';
COMMENT ON COLUMN apiome.slate_function_invocations.variant_ref IS
    'Personalization variant selected, or NULL when the function does not personalize.';
COMMENT ON COLUMN apiome.slate_function_invocations.outcome IS
    'skipped, would-run, ran, refused, capability-denied, egress-denied, limit-exceeded or error. would-run is what a simulated enforcing function reports; ran is what nothing here can currently write.';
COMMENT ON COLUMN apiome.slate_function_invocations.executed IS
    'Whether code actually ran. FALSE for every row this system can currently write; CHECK-tied to edge_attached so a simulation cannot claim an execution.';
COMMENT ON COLUMN apiome.slate_function_invocations.edge_attached IS
    'Whether a runtime tier was attached when this row was written. Snapshotted so attaching one later cannot make old rows look executed.';
COMMENT ON COLUMN apiome.slate_function_invocations.cpu_ms IS
    'CPU milliseconds consumed, or NULL for a simulation. NULL is the absence of a measurement; a zero would be a measurement.';
COMMENT ON COLUMN apiome.slate_function_invocations.wall_ms IS
    'Wall-clock milliseconds elapsed, or NULL for a simulation.';
COMMENT ON COLUMN apiome.slate_function_invocations.memory_peak_mb IS
    'Peak memory in megabytes, or NULL for a simulation.';
COMMENT ON COLUMN apiome.slate_function_invocations.denial_reason IS
    'Why a denial happened, quoted verbatim from the refusing rule so the UI does not restate it and the two cannot drift.';
COMMENT ON COLUMN apiome.slate_function_invocations.evidence IS
    'Redacted request evidence, constrained to an allowlist of keys by CHECK. A denylist would fail open on the field nobody thought of; this cannot store a cookie, an authorization header or a request body at all.';
COMMENT ON COLUMN apiome.slate_function_invocations.retain_until IS
    'When this evidence must be purged. Request data is a liability rather than an asset: the audit row lives forever, the captured user agent does not.';

CREATE INDEX IF NOT EXISTS idx_slate_function_invocations_environment
    ON apiome.slate_function_invocations (environment_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_function_invocations_tenant
    ON apiome.slate_function_invocations (tenant_id, at DESC);
-- The invocation explorer filters by function and by outcome; both are the first thing an
-- investigation narrows on, so neither should be a sequential scan.
CREATE INDEX IF NOT EXISTS idx_slate_function_invocations_function
    ON apiome.slate_function_invocations (environment_id, function_ref, at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_function_invocations_outcome
    ON apiome.slate_function_invocations (environment_id, outcome, at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_function_invocations_variant
    ON apiome.slate_function_invocations (variant_ref)
    WHERE variant_ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_slate_function_invocations_release
    ON apiome.slate_function_invocations (release_id)
    WHERE release_id IS NOT NULL;
-- Retention sweep. The sweep only ever asks for rows already past their date.
CREATE INDEX IF NOT EXISTS idx_slate_function_invocations_retention
    ON apiome.slate_function_invocations (retain_until);

-- ─── 11. Audit (append-only) ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_function_audit (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id      UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id UUID NOT NULL
                   REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id       UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    actor_name     TEXT NOT NULL,
    actor_kind     TEXT NOT NULL CHECK (actor_kind IN ('user', 'automation')),
    subject_kind   TEXT NOT NULL
                   CHECK (subject_kind IN ('policy', 'function', 'version', 'secret-ref',
                                           'capability', 'egress-rule', 'variant', 'approval',
                                           'simulation', 'revert', 'export')),
    subject_id     TEXT,
    summary        TEXT NOT NULL,
    detail         TEXT
);

COMMENT ON TABLE apiome.slate_function_audit IS
    'Append-only audit of every function policy change, capability and egress grant, variant change, approval, revert, refusal and evidence export (UXE-3.3). UPDATE and DELETE are refused by trigger, so history only ever grows.';
COMMENT ON COLUMN apiome.slate_function_audit.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_function_audit.environment_id IS
    'Environment the entry describes.';
COMMENT ON COLUMN apiome.slate_function_audit.at IS
    'When the event happened.';
COMMENT ON COLUMN apiome.slate_function_audit.actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_function_audit.actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_function_audit.actor_kind IS
    'Whether a person or a system acted.';
COMMENT ON COLUMN apiome.slate_function_audit.subject_kind IS
    'What the entry is about. export is included because who read the evidence is itself audit-worthy; secret-ref is included because declaring a secret reference is a privilege change even though no value ever moves.';
COMMENT ON COLUMN apiome.slate_function_audit.subject_id IS
    'Id of the subject when there is one. TEXT so a subject identified by something other than a UUID still fits.';
COMMENT ON COLUMN apiome.slate_function_audit.summary IS
    'What happened, e.g. "Capability secret-read granted" or "Function reverted to revision 3".';
COMMENT ON COLUMN apiome.slate_function_audit.detail IS
    'Extra context, e.g. the refusal reason and its sentence, or the digest that was approved.';

CREATE INDEX IF NOT EXISTS idx_slate_function_audit_environment
    ON apiome.slate_function_audit (environment_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_function_audit_tenant
    ON apiome.slate_function_audit (tenant_id, at DESC);

-- An audit log that can be edited is not an audit log. Both verbs are refused at the database, so
-- no application bug and no ad-hoc session can quietly rewrite what happened. This matters as much
-- here as it did for security: the record of who granted a function the right to read secrets, who
-- approved it and who exported the evidence is the entire basis of the isolation review.
CREATE OR REPLACE FUNCTION apiome.slate_function_audit_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'slate_function_audit is append-only: % is not permitted', TG_OP
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.slate_function_audit_append_only() IS
    'Refuses UPDATE and DELETE on slate_function_audit (UXE-3.3). Audit entries are appended to, never rewritten.';

DROP TRIGGER IF EXISTS trg_slate_function_audit_append_only ON apiome.slate_function_audit;
CREATE TRIGGER trg_slate_function_audit_append_only
    BEFORE UPDATE OR DELETE ON apiome.slate_function_audit
    FOR EACH ROW EXECUTE FUNCTION apiome.slate_function_audit_append_only();
