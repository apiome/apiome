-- Slate Edge cache control: presets, expert rules, trace and scoped purge (UXE-3.1,
-- private-suite#2473).
--
-- A provider credential field cannot carry cache performance, personalization correctness or
-- incident response. Pasting a CDN API token into a form tells nobody which routes are
-- cacheable, cannot explain why a page was served stale, and leaves no record of who purged
-- what during the outage. This migration adds the control-plane schema for cache policy the
-- way V186 added it for routing: presets that are documented values rather than adjectives,
-- expert rules with an explicit precedence, deterministic trace evidence, and purge records
-- that state their own scope and provenance.
--
-- The shape here is not invented. `ROADMAP_AUTHORING_PLATFORM.md` §29.3 names the four presets
-- (Standard, Aggressive, Bypass, Personalized), the expert-rule fields (route matchers,
-- eligibility, browser/edge TTL, stale-while-revalidate, stale-if-error, cache key,
-- query/header/cookie variation, tags, bypass conditions) and the five purge scopes (release,
-- tag, prefix, host, URL). These tables are that specification expressed in SQL, so the
-- guarantees the surface asserts are also enforced by the database rather than only by the
-- process that writes to it.
--
--   1. `apiome.slate_cache_policies`  — one cache policy per environment. Owns the preset, its
--                                       expiry, the optimistic-concurrency token, and whether
--                                       any delivery tier is actually attached.
--   2. `apiome.slate_cache_rules`     — expert route rules. `UNIQUE (environment_id, ordinal)`
--                                       is what makes evaluation a total order rather than a
--                                       set with ties.
--   3. `apiome.slate_cache_rule_tags` — normalized rule tags, because purge-by-tag is a join
--                                       and the commonest purge should not be the slowest one.
--   4. `apiome.slate_cache_traces`    — trace evidence. `rules_digest` is the determinism
--                                       receipt.
--   5. `apiome.slate_cache_purges`    — purge records: scope, estimate, the basis of that
--                                       estimate, outcome and actor.
--   6. `apiome.slate_cache_audit`     — append-only; UPDATE and DELETE are refused.
--
-- Deterministic presets (acceptance criterion 1). A preset is stored as its NAME plus the set
-- of fields an operator moved off its defaults (`preset_overrides`). The preset's own values
-- live in code as literals, not in this schema, so "which preset am I on" stays answerable
-- after an edit and a preset change is a visible diff rather than a silent drift of numbers.
-- `preset` is CHECK-enumerated, so an unknown preset cannot be stored at all.
--
-- Deterministic evaluation (acceptance criterion 2). Rule precedence is `ordinal`, and
-- `UNIQUE (environment_id, ordinal)` forbids two rules claiming the same precedence. Without
-- that constraint, which rule won would depend on row order — that is, on physical storage —
-- and a trace could not be reproduced. `slate_cache_traces.rules_digest` is a sha256 over the
-- canonically-serialized ordered ruleset, the same instinct as `slate_artifacts.content_digest`:
-- identity by content. Re-running a trace against the same digest must produce the same
-- verdict, and if the digest differs the old trace is explained rather than contradicted.
--
-- Bypass cannot outlive its incident. `CHECK (preset <> 'bypass' OR preset_expires_at IS NOT
-- NULL)` makes the §29.3 "explicit expiry" a database fact. A bypass with no end date stops
-- being a decision and becomes the configuration, which is exactly the failure this prevents.
--
-- Scope boundary, stated plainly. `deploy/` in this repository is a single Caddyfile with no
-- cache directives and no CDN behind it. These tables record cache POLICY, the deterministic
-- EVALUATION of that policy against a test request, and the SCOPE and INTENT of a purge — all
-- of which are real, persisted, auditable evidence. What they do not do is evict anything,
-- because there is nothing to evict. `slate_cache_policies.edge_attached` is FALSE for every
-- row this system can currently write, and the `outcome <> 'dispatched' OR edge_attached`
-- constraint on `slate_cache_purges` makes it impossible to record a flush that did not
-- happen. The delivery tier is APX-3.2/UXE-3.2; this is the control plane it will report into.
-- V186 said the same thing about regions, and for the same reason: a control plane that
-- overstates its reach is worse than one that admits its edge.

SET search_path TO apiome, public;

-- ─── 1. Cache policy (one per environment) ───────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_cache_policies (
    id                     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id              UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    site_id                UUID NOT NULL REFERENCES apiome.slate_sites(id) ON DELETE CASCADE,
    -- Cache policy is a property of a lane, not of a site: staging may bypass while production
    -- serves Standard. UNIQUE makes "one policy per environment" a database fact rather than a
    -- convention the application is trusted to keep.
    environment_id         UUID NOT NULL UNIQUE
                           REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    preset                 TEXT NOT NULL DEFAULT 'standard'
                           CHECK (preset IN ('standard', 'aggressive', 'bypass', 'personalized')),
    -- Bypass is an incident mode, so it carries an end date; see the CHECK below.
    preset_expires_at      TIMESTAMP WITH TIME ZONE,
    -- Only the fields an operator moved off the preset's defaults. Stored separately from the
    -- preset name so an edit does not erase which preset this lane believes it is on.
    preset_overrides       JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Optimistic-concurrency token, deliberately mirroring slate_environments.routing_version.
    -- Two operators editing rules during the same incident must not silently overwrite each
    -- other; the second writer matches zero rows and is reported as a conflict.
    policy_version         BIGINT NOT NULL DEFAULT 0,
    -- Whether a managed delivery tier is wired to this lane. FALSE means a purge here is
    -- recorded intent, not a flush. Stored rather than inferred so that when an edge is
    -- attached later, historical records stay truthful about what was true when they were
    -- written.
    edge_attached          BOOLEAN NOT NULL DEFAULT FALSE,
    -- NULL today. Named now so attaching a provider is a data change, not a schema change.
    edge_provider          TEXT,
    created_at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by_actor_id    UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    updated_by_actor_name  TEXT NOT NULL,
    -- The §29.3 "incident/debug mode with explicit expiry", enforced rather than documented.
    CONSTRAINT slate_cache_policies_bypass_needs_expiry
        CHECK (preset <> 'bypass' OR preset_expires_at IS NOT NULL)
);

COMMENT ON TABLE apiome.slate_cache_policies IS
    'Cache policy for one Slate environment (UXE-3.1, private-suite#2473): preset, overrides, concurrency token and whether a delivery tier is attached.';
COMMENT ON COLUMN apiome.slate_cache_policies.tenant_id IS
    'Owning tenant. Denormalized onto every slate_* table so queries and unique constraints stay tenant-scoped without multi-way joins.';
COMMENT ON COLUMN apiome.slate_cache_policies.site_id IS
    'Site the environment belongs to, denormalized so policy lookups do not need a two-hop join.';
COMMENT ON COLUMN apiome.slate_cache_policies.environment_id IS
    'Environment this policy governs. UNIQUE: a lane has exactly one cache policy.';
COMMENT ON COLUMN apiome.slate_cache_policies.preset IS
    'Active preset: standard, aggressive, bypass or personalized (roadmap §29.3). CHECK-enumerated so an unknown preset cannot be stored.';
COMMENT ON COLUMN apiome.slate_cache_policies.preset_expires_at IS
    'When the preset reverts. Required for bypass, which is an incident mode and must not become the configuration by default.';
COMMENT ON COLUMN apiome.slate_cache_policies.preset_overrides IS
    'Fields the operator moved off the preset default, as a JSON object. Kept apart from the preset name so an edit does not erase which preset this lane is on.';
COMMENT ON COLUMN apiome.slate_cache_policies.policy_version IS
    'Optimistic-concurrency token, incremented on every policy or rule write. Mirrors slate_environments.routing_version; a stale expected value is refused, never merged.';
COMMENT ON COLUMN apiome.slate_cache_policies.edge_attached IS
    'Whether a managed delivery tier serves this lane. FALSE for every row this system can currently write: there is no edge, so a purge records intent rather than eviction.';
COMMENT ON COLUMN apiome.slate_cache_policies.edge_provider IS
    'Name of the attached delivery tier, or NULL when none. Reserved for APX-3.2.';
COMMENT ON COLUMN apiome.slate_cache_policies.created_at IS
    'When the policy row was created.';
COMMENT ON COLUMN apiome.slate_cache_policies.updated_at IS
    'When the policy was last changed.';
COMMENT ON COLUMN apiome.slate_cache_policies.updated_by_actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_cache_policies.updated_by_actor_name IS
    'Display name of the actor, stored so history survives user deletion.';

CREATE INDEX IF NOT EXISTS idx_slate_cache_policies_tenant
    ON apiome.slate_cache_policies (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_cache_policies_site
    ON apiome.slate_cache_policies (site_id);

-- ─── 2. Expert rules ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_cache_rules (
    id                             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id                      UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id                 UUID NOT NULL
                                   REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    -- Explicit precedence, lower wins. The UNIQUE constraint below is half of "deterministic":
    -- without it, two rules could claim the same precedence and which one won would depend on
    -- physical row order, making a trace unreproducible.
    ordinal                        INTEGER NOT NULL CHECK (ordinal >= 0),
    -- Disabling must not lose the rule. A disabled rule still appears in the trace as
    -- considered-and-skipped, because "why did my rule not fire" is the question a trace exists
    -- to answer.
    enabled                        BOOLEAN NOT NULL DEFAULT TRUE,
    label                          TEXT NOT NULL,
    matcher_kind                   TEXT NOT NULL
                                   CHECK (matcher_kind IN ('exact', 'prefix', 'glob', 'regex')),
    matcher_value                  TEXT NOT NULL,
    -- A rule that caches POST is almost always a bug. The default states the safe case rather
    -- than leaving it to whoever fills the form.
    matcher_methods                TEXT[] NOT NULL DEFAULT ARRAY['GET', 'HEAD']::TEXT[],
    -- Empty means every host on the lane. Host-scoped rules are what make host purge meaningful.
    matcher_hosts                  TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    eligibility                    TEXT NOT NULL DEFAULT 'cacheable'
                                   CHECK (eligibility IN ('cacheable', 'private', 'no-store')),
    browser_ttl_seconds            INTEGER NOT NULL DEFAULT 0 CHECK (browser_ttl_seconds >= 0),
    edge_ttl_seconds               INTEGER NOT NULL DEFAULT 0 CHECK (edge_ttl_seconds >= 0),
    stale_while_revalidate_seconds INTEGER NOT NULL DEFAULT 0
                                   CHECK (stale_while_revalidate_seconds >= 0),
    stale_if_error_seconds         INTEGER NOT NULL DEFAULT 0
                                   CHECK (stale_if_error_seconds >= 0),
    cache_key_base                 TEXT NOT NULL DEFAULT 'host-url'
                                   CHECK (cache_key_base IN ('url', 'url-no-query', 'host-url')),
    -- 'all' is the classic cache-fragmentation footgun. Naming it as a mode rather than
    -- inferring it from an empty list lets the planner refuse or warn about it by name.
    vary_query_mode                TEXT NOT NULL DEFAULT 'none'
                                   CHECK (vary_query_mode IN ('none', 'all', 'allowlist', 'denylist')),
    vary_query_keys                TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    vary_headers                   TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    -- The single highest-risk column in this migration. Varying a SHARED cache on a session
    -- cookie stores one reader's rendered page under a key another reader can reach. The
    -- identity-in-cache-key refusal keys off this column together with eligibility.
    vary_cookies                   TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    -- List of {kind, name, present|equals} objects. JSONB rather than columns because the shape
    -- is a list of heterogeneous conditions, and the trace records which element fired.
    bypass_conditions              JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- A temporary rule that cannot expire becomes permanent by accident.
    expires_at                     TIMESTAMP WITH TIME ZONE,
    -- Warning reasons the operator explicitly accepted. Warnings only: hard refusals have no
    -- acknowledgement path, because the server is the authority on what is unsafe.
    acknowledged_warnings          TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    created_at                     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by_actor_id            UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_by_actor_name          TEXT NOT NULL,
    created_by_actor_kind          TEXT NOT NULL DEFAULT 'user'
                                   CHECK (created_by_actor_kind IN ('user', 'automation')),
    UNIQUE (environment_id, ordinal)
);

COMMENT ON TABLE apiome.slate_cache_rules IS
    'Expert cache rules for one environment (UXE-3.1). Precedence is ordinal, lower wins; UNIQUE (environment_id, ordinal) makes evaluation a total order so a trace is reproducible.';
COMMENT ON COLUMN apiome.slate_cache_rules.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_cache_rules.environment_id IS
    'Environment whose policy this rule belongs to.';
COMMENT ON COLUMN apiome.slate_cache_rules.ordinal IS
    'Precedence, lower wins. Unique per environment: two rules at the same precedence would make the winner depend on physical row order.';
COMMENT ON COLUMN apiome.slate_cache_rules.enabled IS
    'Whether the rule participates. A disabled rule is retained and still reported by the trace as considered-and-skipped.';
COMMENT ON COLUMN apiome.slate_cache_rules.label IS
    'Operator-facing name, quoted verbatim by the trace when this rule wins.';
COMMENT ON COLUMN apiome.slate_cache_rules.matcher_kind IS
    'How matcher_value is interpreted: exact, prefix, glob or regex (roadmap §29.3 route matchers).';
COMMENT ON COLUMN apiome.slate_cache_rules.matcher_value IS
    'The route pattern itself.';
COMMENT ON COLUMN apiome.slate_cache_rules.matcher_methods IS
    'HTTP methods the rule applies to. Defaults to GET and HEAD because caching a mutating method is almost always a mistake.';
COMMENT ON COLUMN apiome.slate_cache_rules.matcher_hosts IS
    'Hosts the rule is scoped to. Empty means every host on the lane.';
COMMENT ON COLUMN apiome.slate_cache_rules.eligibility IS
    'cacheable (shared), private (one reader) or no-store (never stored). private and no-store are the Personalized safeguards.';
COMMENT ON COLUMN apiome.slate_cache_rules.browser_ttl_seconds IS
    'How long a browser may reuse the response without revalidating.';
COMMENT ON COLUMN apiome.slate_cache_rules.edge_ttl_seconds IS
    'How long a shared tier may reuse the response. Must be zero when eligibility is private or no-store.';
COMMENT ON COLUMN apiome.slate_cache_rules.stale_while_revalidate_seconds IS
    'Window in which a stale response may be served while a fresh one is fetched.';
COMMENT ON COLUMN apiome.slate_cache_rules.stale_if_error_seconds IS
    'Window in which a stale response may be served because the origin failed.';
COMMENT ON COLUMN apiome.slate_cache_rules.cache_key_base IS
    'Base of the cache key: url, url-no-query or host-url.';
COMMENT ON COLUMN apiome.slate_cache_rules.vary_query_mode IS
    'How query parameters enter the key: none, all, allowlist or denylist. all fragments the cache and is warned about by name.';
COMMENT ON COLUMN apiome.slate_cache_rules.vary_query_keys IS
    'Query parameters named by the allowlist or denylist mode.';
COMMENT ON COLUMN apiome.slate_cache_rules.vary_headers IS
    'Request headers that enter the cache key.';
COMMENT ON COLUMN apiome.slate_cache_rules.vary_cookies IS
    'Cookies that enter the cache key. Varying a shared cache on an identity cookie is refused, not warned: it would store one reader page under a key another reader can reach.';
COMMENT ON COLUMN apiome.slate_cache_rules.bypass_conditions IS
    'JSON list of conditions that skip the cache entirely. The trace records which condition fired.';
COMMENT ON COLUMN apiome.slate_cache_rules.expires_at IS
    'When the rule stops applying, or NULL for a permanent rule.';
COMMENT ON COLUMN apiome.slate_cache_rules.acknowledged_warnings IS
    'Warning reasons the operator accepted. Warnings only; hard refusals have no acknowledgement path.';
COMMENT ON COLUMN apiome.slate_cache_rules.created_at IS
    'When the rule was created.';
COMMENT ON COLUMN apiome.slate_cache_rules.updated_at IS
    'When the rule was last changed.';
COMMENT ON COLUMN apiome.slate_cache_rules.created_by_actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_cache_rules.created_by_actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_cache_rules.created_by_actor_kind IS
    'Whether a person or a system created the rule.';

CREATE INDEX IF NOT EXISTS idx_slate_cache_rules_environment
    ON apiome.slate_cache_rules (environment_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_slate_cache_rules_tenant
    ON apiome.slate_cache_rules (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_cache_rules_expiry
    ON apiome.slate_cache_rules (expires_at)
    WHERE expires_at IS NOT NULL;

-- ─── 3. Rule tags ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_cache_rule_tags (
    id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rule_id UUID NOT NULL REFERENCES apiome.slate_cache_rules(id) ON DELETE CASCADE,
    tag     TEXT NOT NULL,
    UNIQUE (rule_id, tag)
);

COMMENT ON TABLE apiome.slate_cache_rule_tags IS
    'Tags attached to cache rules (UXE-3.1). Normalized rather than an array column because purge-by-tag is a join, and the commonest purge should not be the slowest one.';
COMMENT ON COLUMN apiome.slate_cache_rule_tags.rule_id IS
    'Rule the tag belongs to.';
COMMENT ON COLUMN apiome.slate_cache_rule_tags.tag IS
    'The tag. Purge-by-tag resolves tag to rules to matchers to routes.';

CREATE INDEX IF NOT EXISTS idx_slate_cache_rule_tags_tag
    ON apiome.slate_cache_rule_tags (tag);

-- ─── 4. Trace evidence ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_cache_traces (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id  UUID NOT NULL
                    REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id        UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    actor_name      TEXT NOT NULL,
    actor_kind      TEXT NOT NULL DEFAULT 'user'
                    CHECK (actor_kind IN ('user', 'automation')),
    -- The release whose route inventory the trace was evaluated against. NULL when the lane
    -- serves nothing, which is a real answer rather than a missing one.
    release_id      UUID REFERENCES apiome.slate_releases(id) ON DELETE SET NULL,
    request         JSONB NOT NULL,
    policy_version  BIGINT NOT NULL,
    -- The determinism receipt: sha256 over the canonically-serialized ordered ruleset. Two
    -- traces with the same digest and the same request must agree. Same instinct as
    -- slate_artifacts.content_digest — identity by content.
    rules_digest    TEXT NOT NULL CHECK (rules_digest ~ '^sha256:[0-9a-f]{64}$'),
    -- NULL means the preset default decided. That is an answer, not an absence.
    winning_rule_id UUID REFERENCES apiome.slate_cache_rules(id) ON DELETE SET NULL,
    verdict         JSONB NOT NULL
);

COMMENT ON TABLE apiome.slate_cache_traces IS
    'Dry-run cache trace evidence (UXE-3.1): what the policy decides for a test request, and which rule decided it. Policy evaluation, not an observed edge hit.';
COMMENT ON COLUMN apiome.slate_cache_traces.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_cache_traces.environment_id IS
    'Environment whose policy was evaluated.';
COMMENT ON COLUMN apiome.slate_cache_traces.at IS
    'When the trace was run.';
COMMENT ON COLUMN apiome.slate_cache_traces.actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_cache_traces.actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_cache_traces.actor_kind IS
    'Whether a person or a system ran the trace.';
COMMENT ON COLUMN apiome.slate_cache_traces.release_id IS
    'Release whose route inventory the trace was evaluated against, or NULL when the lane serves nothing.';
COMMENT ON COLUMN apiome.slate_cache_traces.request IS
    'The test request as evaluated: method, host, path, query, headers and cookies.';
COMMENT ON COLUMN apiome.slate_cache_traces.policy_version IS
    'Which generation of the lane policy answered, so a later edit does not silently reinterpret this record.';
COMMENT ON COLUMN apiome.slate_cache_traces.rules_digest IS
    'sha256 over the canonical ordered ruleset. Re-running against the same digest must produce the same verdict; a different digest means the ruleset changed.';
COMMENT ON COLUMN apiome.slate_cache_traces.winning_rule_id IS
    'Rule that decided, or NULL when the preset default decided.';
COMMENT ON COLUMN apiome.slate_cache_traces.verdict IS
    'The full verdict: eligibility, resolved cache key and its components, TTLs, bypass decision, and the ordered considered-rule list with a sentence each.';

CREATE INDEX IF NOT EXISTS idx_slate_cache_traces_environment
    ON apiome.slate_cache_traces (environment_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_cache_traces_tenant
    ON apiome.slate_cache_traces (tenant_id, at DESC);

-- ─── 5. Purge records ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_cache_purges (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id         UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id    UUID NOT NULL
                      REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    at                TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id          UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    actor_name        TEXT NOT NULL,
    actor_kind        TEXT NOT NULL DEFAULT 'user'
                      CHECK (actor_kind IN ('user', 'automation')),
    -- Exactly the five scopes roadmap §29.3 names, enumerated in SQL so a sixth cannot appear
    -- without a migration that has to explain itself.
    scope_kind        TEXT NOT NULL
                      CHECK (scope_kind IN ('release', 'tag', 'prefix', 'host', 'url')),
    scope_value       TEXT NOT NULL,
    -- Set for scope_kind='release', and recorded for every other scope too as the release the
    -- estimate was computed against. An estimate without its basis release is unreproducible.
    release_id        UUID REFERENCES apiome.slate_releases(id) ON DELETE SET NULL,
    -- NOT NULL because a purge with no stated reason is the one nobody can explain in the
    -- postmortem.
    reason            TEXT NOT NULL,
    estimated_objects INTEGER NOT NULL CHECK (estimated_objects >= 0),
    -- Which table produced the number. A bare count invites belief; a count plus its source
    -- invites checking.
    estimate_basis    TEXT NOT NULL
                      CHECK (estimate_basis IN ('changed-pages', 'artifact-manifest',
                                                'domain-inventory', 'rule-tags', 'single-url',
                                                'none')),
    -- Bounded sample so an operator can eyeball what would be hit before confirming.
    sample_routes     TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    dry_run           BOOLEAN NOT NULL DEFAULT FALSE,
    outcome           TEXT NOT NULL
                      CHECK (outcome IN ('estimated', 'recorded', 'dispatched', 'refused')),
    refusal_reason    TEXT,
    -- Snapshot of slate_cache_policies.edge_attached at purge time. Denormalized deliberately:
    -- when an edge is attached later, historical records must not retroactively appear to have
    -- flushed something.
    edge_attached     BOOLEAN NOT NULL DEFAULT FALSE,
    -- The honesty rule, enforced at the database. Nothing can be recorded as dispatched on a
    -- lane that had no delivery tier attached to dispatch to.
    CONSTRAINT slate_cache_purges_dispatch_needs_edge
        CHECK (outcome <> 'dispatched' OR edge_attached),
    -- A refusal names its reason; anything else does not carry one.
    CONSTRAINT slate_cache_purges_refusal_has_reason
        CHECK ((outcome = 'refused') = (refusal_reason IS NOT NULL))
);

COMMENT ON TABLE apiome.slate_cache_purges IS
    'Purge records (UXE-3.1): scope, estimated blast radius, the basis of that estimate, outcome and actor. Records intent and scope; with no delivery tier attached it evicts nothing.';
COMMENT ON COLUMN apiome.slate_cache_purges.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_cache_purges.environment_id IS
    'Environment the purge was scoped to.';
COMMENT ON COLUMN apiome.slate_cache_purges.at IS
    'When the purge was requested.';
COMMENT ON COLUMN apiome.slate_cache_purges.actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_cache_purges.actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_cache_purges.actor_kind IS
    'Whether a person or a system requested the purge.';
COMMENT ON COLUMN apiome.slate_cache_purges.scope_kind IS
    'One of release, tag, prefix, host or url (roadmap §29.3).';
COMMENT ON COLUMN apiome.slate_cache_purges.scope_value IS
    'The scope itself: a release id, tag, path prefix, hostname or absolute URL.';
COMMENT ON COLUMN apiome.slate_cache_purges.release_id IS
    'Release the estimate was computed against. Recorded for every scope, not only release scope, because an estimate without its basis is unreproducible.';
COMMENT ON COLUMN apiome.slate_cache_purges.reason IS
    'Why the operator purged. NOT NULL: a purge with no stated reason cannot be explained afterwards.';
COMMENT ON COLUMN apiome.slate_cache_purges.estimated_objects IS
    'Estimated number of objects in scope. An estimate, never a count of things actually evicted.';
COMMENT ON COLUMN apiome.slate_cache_purges.estimate_basis IS
    'Which table produced the estimate, so the number can be checked rather than believed.';
COMMENT ON COLUMN apiome.slate_cache_purges.sample_routes IS
    'Bounded sample of routes in scope, so an operator can see what would be hit before confirming.';
COMMENT ON COLUMN apiome.slate_cache_purges.dry_run IS
    'Whether this was an estimate only. A dry run runs every gate and writes no policy change.';
COMMENT ON COLUMN apiome.slate_cache_purges.outcome IS
    'estimated (dry run), recorded (accepted with no edge attached), dispatched (sent to a delivery tier) or refused.';
COMMENT ON COLUMN apiome.slate_cache_purges.refusal_reason IS
    'Named refusal reason when the outcome is refused, and NULL otherwise.';
COMMENT ON COLUMN apiome.slate_cache_purges.edge_attached IS
    'Whether a delivery tier was attached when this purge ran. Snapshotted so attaching one later cannot make old records look like flushes.';

CREATE INDEX IF NOT EXISTS idx_slate_cache_purges_environment
    ON apiome.slate_cache_purges (environment_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_cache_purges_tenant
    ON apiome.slate_cache_purges (tenant_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_cache_purges_release
    ON apiome.slate_cache_purges (release_id)
    WHERE release_id IS NOT NULL;

-- ─── 6. Audit (append-only) ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_cache_audit (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id      UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id UUID NOT NULL
                   REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id       UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    actor_name     TEXT NOT NULL,
    actor_kind     TEXT NOT NULL CHECK (actor_kind IN ('user', 'automation')),
    subject_kind   TEXT NOT NULL CHECK (subject_kind IN ('preset', 'rule', 'purge', 'trace')),
    subject_id     UUID,
    summary        TEXT NOT NULL,
    detail         TEXT
);

COMMENT ON TABLE apiome.slate_cache_audit IS
    'Append-only audit of every cache policy change, purge and refusal (UXE-3.1). UPDATE and DELETE are refused by trigger, so history only ever grows.';
COMMENT ON COLUMN apiome.slate_cache_audit.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_cache_audit.environment_id IS
    'Environment the entry describes.';
COMMENT ON COLUMN apiome.slate_cache_audit.at IS
    'When the event happened.';
COMMENT ON COLUMN apiome.slate_cache_audit.actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_cache_audit.actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_cache_audit.actor_kind IS
    'Whether a person or a system acted.';
COMMENT ON COLUMN apiome.slate_cache_audit.subject_kind IS
    'What the entry is about: a preset change, a rule write, a purge or a trace.';
COMMENT ON COLUMN apiome.slate_cache_audit.subject_id IS
    'Id of the subject row when there is one.';
COMMENT ON COLUMN apiome.slate_cache_audit.summary IS
    'What happened, e.g. "Purged by prefix" or "Rule refused".';
COMMENT ON COLUMN apiome.slate_cache_audit.detail IS
    'Extra context, e.g. the refusal reason and its sentence, or the scope that was estimated.';

CREATE INDEX IF NOT EXISTS idx_slate_cache_audit_environment
    ON apiome.slate_cache_audit (environment_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_cache_audit_tenant
    ON apiome.slate_cache_audit (tenant_id, at DESC);

-- An audit log that can be edited is not an audit log. Both verbs are refused at the database,
-- so no application bug and no ad-hoc session can quietly rewrite what happened. This matters
-- more here than almost anywhere else: the purge record is the evidence of what an operator did
-- during an incident.
CREATE OR REPLACE FUNCTION apiome.slate_cache_audit_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'slate_cache_audit is append-only: % is not permitted', TG_OP
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.slate_cache_audit_append_only() IS
    'Refuses UPDATE and DELETE on slate_cache_audit (UXE-3.1). Audit entries are appended to, never rewritten.';

DROP TRIGGER IF EXISTS trg_slate_cache_audit_append_only ON apiome.slate_cache_audit;
CREATE TRIGGER trg_slate_cache_audit_append_only
    BEFORE UPDATE OR DELETE ON apiome.slate_cache_audit
    FOR EACH ROW EXECUTE FUNCTION apiome.slate_cache_audit_append_only();
