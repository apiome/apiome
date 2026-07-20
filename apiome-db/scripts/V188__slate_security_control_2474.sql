-- Slate Edge security control: WAF, DDoS, bot and rate-limit policy, staged rollout, security
-- events and dual-control approval (UXE-3.2, private-suite#2474).
--
-- A firewall toggle cannot carry delivery security. Turning on "protection" tells nobody which
-- rule blocked the customer who phoned in, cannot explain why a release started returning 403 to
-- one region, and leaves no record of who added the exception that reopened the hole. This
-- migration adds the control-plane schema for security policy the way V187 added it for cache:
-- managed rulesets whose modes are documented values rather than adjectives, custom rules with an
-- explicit precedence and a staged rollout, event evidence that is redacted by construction, and
-- rule changes that carry both an approval and a revision to revert to.
--
-- The shape here is not invented. `ROADMAP_AUTHORING_PLATFORM.md` §29.4 names the pieces
-- (always-on DDoS status, managed WAF rulesets, safe bot/rate-limit presets, custom rules,
-- exceptions, challenge modes, staged rollout, and security events joining rule, route, release,
-- region, action and request sample without exposing secrets), and §29.7 assigns them to roles
-- (Publisher gets safe presets; only the Platform operator gets WAF; the Auditor gets read-only
-- policy and exportable audit). These tables are that specification expressed in SQL, so the
-- guarantees the surface asserts are also enforced by the database rather than only by the
-- process that writes to it.
--
--   1. `apiome.slate_security_policies`       — one policy per environment. Owns the managed
--                                               ruleset tier, the bot and rate presets, the
--                                               optimistic-concurrency token, and whether any
--                                               delivery tier is actually attached.
--   2. `apiome.slate_security_managed_groups` — per-environment mode of each managed WAF group.
--                                               The catalog lives in code; only the deviation
--                                               from its default is stored.
--   3. `apiome.slate_security_rules`          — custom rules. `UNIQUE (environment_id, ordinal)`
--                                               is what makes evaluation a total order rather
--                                               than a set with ties.
--   4. `apiome.slate_security_rule_revisions` — the body of every rule as it was before each
--                                               change, so "every rule change can be reverted"
--                                               has something to revert to.
--   5. `apiome.slate_security_exceptions`     — scoped carve-outs from a managed group or rule.
--   6. `apiome.slate_security_approvals`      — dual control. The author cannot be the approver.
--   7. `apiome.slate_security_events`         — security events with allowlisted, expiring
--                                               request evidence.
--   8. `apiome.slate_security_audit`          — append-only; UPDATE and DELETE are refused.
--
-- Staged rollout cannot lock anybody out (acceptance criterion 3). A rule carries both a
-- `rollout_mode` and a `rollout_percent`. A rule in `simulate` records what it would have done
-- and blocks nothing, which is what makes a preview honest rather than a promise. Reaching
-- `enforce` at 100% is therefore a deliberate sequence of writes, each of them audited, rather
-- than a single checkbox. `CHECK (rollout_mode <> 'simulate' OR action <> 'block')` is not
-- needed — a simulated block is exactly the point — but
-- `CHECK (rollout_percent BETWEEN 0 AND 100)` and the enforce-needs-approval rule below are.
--
-- Redacted evidence, enforced rather than promised (acceptance criterion 1). §29.4 requires a
-- request sample "without exposing secrets". A denylist of sensitive headers fails open on the
-- field nobody thought of, so `slate_security_events.evidence` is constrained to an ALLOWLIST:
-- `evidence - <allowed keys> = '{}'` is empty only when every key present is one of the permitted
-- ones. Removing a key from that array is a migration that has to explain itself; adding an
-- `authorization` or `cookie` key is simply impossible. Evidence also carries `retain_until`,
-- because indefinite retention of request data is a liability rather than a feature, and an
-- audit row is the thing that should live forever, not a captured user agent.
--
-- Dual control, and why it is on identity keys rather than user ids (acceptance criterion 4).
-- V186's `slate_release_approvals` records an approval with a content digest but has no
-- distinct-approver constraint, so it is an approval record and not two-person review. This
-- table adds the constraint. It compares `author_actor_key` and `approver_actor_key` — immutable
-- identity strings captured at write time — rather than the nullable `users(id)` foreign keys,
-- because those columns are `ON DELETE SET NULL` and a deleted user would turn a genuine
-- two-person approval into two NULLs that no longer look distinct. A constraint that weakens
-- when a user is offboarded is not a constraint.
--
-- Scope boundary, stated plainly, and it matters more here than it did for cache. `deploy/` in
-- this repository is a single Caddyfile with no WAF, no bot management and no CDN behind it.
-- These tables record security POLICY, its deterministic SIMULATION against a test request, and
-- the EVIDENCE and APPROVAL trail around every change — all of which are real, persisted and
-- auditable. What they do not do is block anything, because there is nothing in the request path
-- to block with. An unenforced cache rule wastes a purge; an unenforced WAF rule means somebody
-- believes they are stopping an attacker and is not. So the boundary is enforced in three
-- places: `slate_security_policies.edge_attached` is FALSE for every row this system can write;
-- `CHECK (source <> 'edge-observed' OR edge_attached)` on `slate_security_events` makes it
-- impossible to record a real attack that nothing observed; and `CHECK (mitigated = FALSE OR
-- edge_attached)` makes it impossible to claim a request was stopped. The delivery tier is
-- UXE-3.2's successor work; this is the control plane it will report into. V186 said the same
-- thing about regions and V187 about eviction, for the same reason: a control plane that
-- overstates its reach is worse than one that admits its edge, and a SECURITY control plane that
-- overstates its reach is dangerous rather than merely disappointing.

SET search_path TO apiome, public;

-- ─── 1. Security policy (one per environment) ────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_security_policies (
    id                     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id              UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    site_id                UUID NOT NULL REFERENCES apiome.slate_sites(id) ON DELETE CASCADE,
    -- Security posture is a property of a lane, not of a site: staging may run everything in
    -- simulate while production enforces. UNIQUE makes "one policy per environment" a database
    -- fact rather than a convention the application is trusted to keep.
    environment_id         UUID NOT NULL UNIQUE
                           REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    -- The managed WAF tier. §29.4 ships managed rulesets in the commercial MVP; the tier names
    -- what breadth of curated coverage is on, and the per-group table below records deviations.
    managed_ruleset        TEXT NOT NULL DEFAULT 'core'
                           CHECK (managed_ruleset IN ('off', 'core', 'strict')),
    -- Safe bot and rate presets (§29.4). Enumerated in SQL so an unknown preset cannot be stored.
    bot_preset             TEXT NOT NULL DEFAULT 'balanced'
                           CHECK (bot_preset IN ('off', 'monitor', 'balanced', 'aggressive')),
    rate_preset            TEXT NOT NULL DEFAULT 'standard'
                           CHECK (rate_preset IN ('off', 'generous', 'standard', 'strict')),
    -- Only the fields an operator moved off the preset's defaults. Stored separately from the
    -- preset names so an edit does not erase which preset this lane believes it is on.
    preset_overrides       JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Documentation must stay available (the problem statement). A lane can declare a ceiling on
    -- how aggressive any rule may be, so a strict preset plus an over-tight custom rule cannot
    -- combine into a site nobody can read.
    challenge_mode         TEXT NOT NULL DEFAULT 'managed'
                           CHECK (challenge_mode IN ('off', 'managed', 'always')),
    -- Optimistic-concurrency token, deliberately mirroring slate_cache_policies.policy_version.
    -- Two operators editing rules during the same incident must not silently overwrite each
    -- other; the second writer matches zero rows and is reported as a conflict.
    policy_version         BIGINT NOT NULL DEFAULT 0,
    -- Whether a managed delivery tier is wired to this lane. FALSE means every rule here is
    -- recorded policy, not enforcement. Stored rather than inferred so that when an edge is
    -- attached later, historical records stay truthful about what was true when written.
    edge_attached          BOOLEAN NOT NULL DEFAULT FALSE,
    -- NULL today. Named now so attaching a provider is a data change, not a schema change.
    edge_provider          TEXT,
    created_at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by_actor_id    UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    updated_by_actor_name  TEXT NOT NULL,
    -- Turning the managed ruleset off is the single most consequential setting on this row, and
    -- §29.4 requires that it be revertible and audited rather than merely possible. Recording
    -- WHY is the part that survives the incident; the approval lives in slate_security_approvals.
    managed_off_reason     TEXT,
    CONSTRAINT slate_security_policies_off_needs_reason
        CHECK (managed_ruleset <> 'off' OR managed_off_reason IS NOT NULL)
);

COMMENT ON TABLE apiome.slate_security_policies IS
    'Security policy for one Slate environment (UXE-3.2, private-suite#2474): managed WAF tier, bot and rate presets, challenge mode, concurrency token and whether a delivery tier is attached.';
COMMENT ON COLUMN apiome.slate_security_policies.tenant_id IS
    'Owning tenant. Denormalized onto every slate_* table so queries and unique constraints stay tenant-scoped without multi-way joins.';
COMMENT ON COLUMN apiome.slate_security_policies.site_id IS
    'Site the environment belongs to, denormalized so policy lookups do not need a two-hop join.';
COMMENT ON COLUMN apiome.slate_security_policies.environment_id IS
    'Environment this policy governs. UNIQUE: a lane has exactly one security policy.';
COMMENT ON COLUMN apiome.slate_security_policies.managed_ruleset IS
    'Managed WAF tier: off, core or strict (roadmap §29.4). CHECK-enumerated so an unknown tier cannot be stored.';
COMMENT ON COLUMN apiome.slate_security_policies.bot_preset IS
    'Safe bot preset: off, monitor, balanced or aggressive. monitor observes without acting, which is the safe default for a documentation site.';
COMMENT ON COLUMN apiome.slate_security_policies.rate_preset IS
    'Safe rate-limit preset: off, generous, standard or strict.';
COMMENT ON COLUMN apiome.slate_security_policies.preset_overrides IS
    'Fields the operator moved off a preset default, as a JSON object. Kept apart from the preset names so an edit does not erase which presets this lane is on.';
COMMENT ON COLUMN apiome.slate_security_policies.challenge_mode IS
    'How interactive challenges are issued: off, managed (only when a rule asks) or always. Documentation availability is the reason this is capped at the lane rather than per rule.';
COMMENT ON COLUMN apiome.slate_security_policies.policy_version IS
    'Optimistic-concurrency token, incremented on every policy, rule or exception write. Mirrors slate_cache_policies.policy_version; a stale expected value is refused, never merged.';
COMMENT ON COLUMN apiome.slate_security_policies.edge_attached IS
    'Whether a managed delivery tier serves this lane. FALSE for every row this system can currently write: there is no request path, so a rule records policy rather than enforcement.';
COMMENT ON COLUMN apiome.slate_security_policies.edge_provider IS
    'Name of the attached delivery tier, or NULL when none.';
COMMENT ON COLUMN apiome.slate_security_policies.created_at IS
    'When the policy row was created.';
COMMENT ON COLUMN apiome.slate_security_policies.updated_at IS
    'When the policy was last changed.';
COMMENT ON COLUMN apiome.slate_security_policies.updated_by_actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_security_policies.updated_by_actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_security_policies.managed_off_reason IS
    'Why the managed ruleset was turned off. Required when it is off: disabling the WAF with no stated reason is the change nobody can explain afterwards.';

CREATE INDEX IF NOT EXISTS idx_slate_security_policies_tenant
    ON apiome.slate_security_policies (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_security_policies_site
    ON apiome.slate_security_policies (site_id);

-- ─── 2. Managed WAF group modes ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_security_managed_groups (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id      UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id UUID NOT NULL
                   REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    -- Identifier of a curated group in the code-side catalog, e.g. 'sql-injection'. Deliberately
    -- TEXT with no foreign key: the catalog is a versioned literal in application code the way
    -- the cache presets are, so that "which groups exist" is reviewable in a diff rather than
    -- being seed data that drifts per environment.
    group_id       TEXT NOT NULL,
    -- The deviation from the group's catalog default. A row exists only when an operator moved
    -- the group off that default, so an empty table means "everything is as shipped".
    mode           TEXT NOT NULL
                   CHECK (mode IN ('off', 'log', 'challenge', 'block')),
    -- Turning a group off or down to log is the direction that removes protection, so it carries
    -- a reason for the same purpose managed_off_reason serves on the policy row.
    reason         TEXT,
    updated_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id       UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    actor_name     TEXT NOT NULL,
    UNIQUE (environment_id, group_id),
    CONSTRAINT slate_security_managed_groups_weakening_needs_reason
        CHECK (mode NOT IN ('off', 'log') OR reason IS NOT NULL)
);

COMMENT ON TABLE apiome.slate_security_managed_groups IS
    'Per-environment mode of a managed WAF group (UXE-3.2). A row exists only where an operator moved a group off its catalog default, so an empty table means everything is as shipped.';
COMMENT ON COLUMN apiome.slate_security_managed_groups.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_security_managed_groups.environment_id IS
    'Environment whose policy this override belongs to.';
COMMENT ON COLUMN apiome.slate_security_managed_groups.group_id IS
    'Identifier of a curated group in the code-side catalog. TEXT with no FK: the catalog is a reviewable literal in application code, not per-tenant seed data.';
COMMENT ON COLUMN apiome.slate_security_managed_groups.mode IS
    'off, log, challenge or block. log observes without acting and is how a group is safely trialled before it enforces.';
COMMENT ON COLUMN apiome.slate_security_managed_groups.reason IS
    'Why the group was weakened. Required for off and log, which are the modes that remove protection.';
COMMENT ON COLUMN apiome.slate_security_managed_groups.updated_at IS
    'When the override was last changed.';
COMMENT ON COLUMN apiome.slate_security_managed_groups.actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_security_managed_groups.actor_name IS
    'Display name of the actor, stored so history survives user deletion.';

CREATE INDEX IF NOT EXISTS idx_slate_security_managed_groups_environment
    ON apiome.slate_security_managed_groups (environment_id);
CREATE INDEX IF NOT EXISTS idx_slate_security_managed_groups_tenant
    ON apiome.slate_security_managed_groups (tenant_id);

-- ─── 3. Custom rules ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_security_rules (
    id                     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id              UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id         UUID NOT NULL
                           REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    -- Explicit precedence, lower wins. The UNIQUE constraint below is half of "deterministic":
    -- without it, two rules could claim the same precedence and which one won would depend on
    -- physical row order, making a simulation unreproducible.
    ordinal                INTEGER NOT NULL CHECK (ordinal >= 0),
    -- Disabling must not lose the rule. A disabled rule still appears in the simulation as
    -- considered-and-skipped, because "why did my rule not fire" is the question it exists to
    -- answer.
    enabled                BOOLEAN NOT NULL DEFAULT TRUE,
    label                  TEXT NOT NULL,
    -- Matchers are the same four kinds the cache rules use, deliberately: an operator who has
    -- learned what 'glob' means on one surface must not have to relearn it on the other.
    matcher_kind           TEXT NOT NULL
                           CHECK (matcher_kind IN ('exact', 'prefix', 'glob', 'regex')),
    matcher_value          TEXT NOT NULL,
    matcher_methods        TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    matcher_hosts          TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    -- Additional non-route conditions: source country, ASN, bot class, header presence. JSONB
    -- rather than columns because the shape is a list of heterogeneous predicates and the
    -- simulation records which one failed.
    conditions             JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- What the rule does when it wins. 'allow' is an early exit that stops later rules, which is
    -- how an exception is expressed as a rule rather than as a special case.
    action                 TEXT NOT NULL
                           CHECK (action IN ('allow', 'log', 'challenge', 'rate-limit', 'block')),
    -- Populated only for action='rate-limit'; the CHECK below ties them together so a rate limit
    -- cannot exist without a budget and a budget cannot exist without a rate limit.
    rate_requests          INTEGER CHECK (rate_requests IS NULL OR rate_requests > 0),
    rate_window_seconds    INTEGER CHECK (rate_window_seconds IS NULL OR rate_window_seconds > 0),
    -- Staged rollout (§29.4, acceptance criterion 3). 'simulate' records what the rule would have
    -- done and acts on nothing; that is what makes a preview honest. Reaching enforce at 100 is a
    -- deliberate sequence of audited writes rather than one checkbox.
    rollout_mode           TEXT NOT NULL DEFAULT 'simulate'
                           CHECK (rollout_mode IN ('simulate', 'enforce')),
    rollout_percent        INTEGER NOT NULL DEFAULT 0
                           CHECK (rollout_percent BETWEEN 0 AND 100),
    -- A temporary rule that cannot expire becomes permanent by accident. Incident rules are the
    -- common case here, so this matters more than it did for cache.
    expires_at             TIMESTAMP WITH TIME ZONE,
    -- Warning reasons the operator explicitly accepted. Warnings only: hard refusals have no
    -- acknowledgement path, because the server is the authority on what is unsafe.
    acknowledged_warnings  TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    -- Content digest of the rule body, so an approval can be checked against what actually
    -- shipped. Same instinct as slate_release_approvals.digest: approving one body and shipping
    -- another must be detectable rather than merely unlikely.
    body_digest            TEXT NOT NULL CHECK (body_digest ~ '^sha256:[0-9a-f]{64}$'),
    revision               INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by_actor_id    UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_by_actor_name  TEXT NOT NULL,
    created_by_actor_kind  TEXT NOT NULL DEFAULT 'user'
                           CHECK (created_by_actor_kind IN ('user', 'automation')),
    UNIQUE (environment_id, ordinal),
    CONSTRAINT slate_security_rules_rate_needs_budget
        CHECK ((action = 'rate-limit')
               = (rate_requests IS NOT NULL AND rate_window_seconds IS NOT NULL))
);

COMMENT ON TABLE apiome.slate_security_rules IS
    'Custom security rules for one environment (UXE-3.2). Precedence is ordinal, lower wins; UNIQUE (environment_id, ordinal) makes evaluation a total order so a simulation is reproducible.';
COMMENT ON COLUMN apiome.slate_security_rules.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_security_rules.environment_id IS
    'Environment whose policy this rule belongs to.';
COMMENT ON COLUMN apiome.slate_security_rules.ordinal IS
    'Precedence, lower wins. Unique per environment: two rules at the same precedence would make the winner depend on physical row order.';
COMMENT ON COLUMN apiome.slate_security_rules.enabled IS
    'Whether the rule participates. A disabled rule is retained and still reported by the simulation as considered-and-skipped.';
COMMENT ON COLUMN apiome.slate_security_rules.label IS
    'Operator-facing name, quoted verbatim by the simulation and by every event this rule produces.';
COMMENT ON COLUMN apiome.slate_security_rules.matcher_kind IS
    'How matcher_value is interpreted: exact, prefix, glob or regex. Deliberately the same four kinds as slate_cache_rules.';
COMMENT ON COLUMN apiome.slate_security_rules.matcher_value IS
    'The route pattern itself.';
COMMENT ON COLUMN apiome.slate_security_rules.matcher_methods IS
    'HTTP methods the rule applies to. Empty means every method, which for a security rule is the safe default rather than the dangerous one.';
COMMENT ON COLUMN apiome.slate_security_rules.matcher_hosts IS
    'Hosts the rule is scoped to. Empty means every host on the lane.';
COMMENT ON COLUMN apiome.slate_security_rules.conditions IS
    'JSON list of non-route predicates: country, ASN, bot class, header presence. The simulation records which predicate failed.';
COMMENT ON COLUMN apiome.slate_security_rules.action IS
    'allow, log, challenge, rate-limit or block. allow is an early exit, which is how an exception is expressed as a rule rather than a special case.';
COMMENT ON COLUMN apiome.slate_security_rules.rate_requests IS
    'Request budget for action=rate-limit, and NULL otherwise.';
COMMENT ON COLUMN apiome.slate_security_rules.rate_window_seconds IS
    'Window the budget applies over for action=rate-limit, and NULL otherwise.';
COMMENT ON COLUMN apiome.slate_security_rules.rollout_mode IS
    'simulate records what the rule would have done and acts on nothing; enforce acts. Staged rollout is what prevents a custom rule from locking everyone out.';
COMMENT ON COLUMN apiome.slate_security_rules.rollout_percent IS
    'Share of traffic the rule applies to while being rolled out, 0 to 100.';
COMMENT ON COLUMN apiome.slate_security_rules.expires_at IS
    'When the rule stops applying, or NULL for a permanent rule. Incident rules are the common case, so an expiry matters more here than on a cache rule.';
COMMENT ON COLUMN apiome.slate_security_rules.acknowledged_warnings IS
    'Warning reasons the operator accepted. Warnings only; hard refusals have no acknowledgement path.';
COMMENT ON COLUMN apiome.slate_security_rules.body_digest IS
    'sha256 over the canonical rule body, so an approval can be checked against what shipped. Approving one body and shipping another is detectable rather than merely unlikely.';
COMMENT ON COLUMN apiome.slate_security_rules.revision IS
    'Monotonic revision counter. The previous body of each revision is kept in slate_security_rule_revisions so any change can be reverted.';
COMMENT ON COLUMN apiome.slate_security_rules.created_at IS
    'When the rule was created.';
COMMENT ON COLUMN apiome.slate_security_rules.updated_at IS
    'When the rule was last changed.';
COMMENT ON COLUMN apiome.slate_security_rules.created_by_actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_security_rules.created_by_actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_security_rules.created_by_actor_kind IS
    'Whether a person or a system created the rule.';

CREATE INDEX IF NOT EXISTS idx_slate_security_rules_environment
    ON apiome.slate_security_rules (environment_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_slate_security_rules_tenant
    ON apiome.slate_security_rules (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_security_rules_expiry
    ON apiome.slate_security_rules (expires_at)
    WHERE expires_at IS NOT NULL;

-- ─── 4. Rule revisions ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_security_rule_revisions (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id      UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id UUID NOT NULL
                   REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    -- Deliberately NOT a foreign key with CASCADE onto slate_security_rules. A deleted rule is
    -- exactly the case where "revert my change" is most needed, so the revision history has to
    -- outlive the row it describes.
    rule_id        UUID NOT NULL,
    revision       INTEGER NOT NULL CHECK (revision >= 1),
    -- The complete rule body as it was, so reverting is applying a stored document rather than
    -- reconstructing intent from an audit sentence.
    body           JSONB NOT NULL,
    body_digest    TEXT NOT NULL CHECK (body_digest ~ '^sha256:[0-9a-f]{64}$'),
    -- What produced this revision, so a revert of a revert reads correctly in history.
    change_kind    TEXT NOT NULL
                   CHECK (change_kind IN ('created', 'updated', 'disabled', 'deleted',
                                          'reverted', 'rollout-changed')),
    at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id       UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    actor_name     TEXT NOT NULL,
    UNIQUE (rule_id, revision)
);

COMMENT ON TABLE apiome.slate_security_rule_revisions IS
    'The body of every security rule as it was before each change (UXE-3.2), so §29.4 "every rule change can be reverted" has a stored document to revert to.';
COMMENT ON COLUMN apiome.slate_security_rule_revisions.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_security_rule_revisions.environment_id IS
    'Environment the rule belonged to.';
COMMENT ON COLUMN apiome.slate_security_rule_revisions.rule_id IS
    'Rule this revision describes. Not a foreign key: a deleted rule is exactly when a revert is most needed, so history must outlive the row.';
COMMENT ON COLUMN apiome.slate_security_rule_revisions.revision IS
    'Which revision of that rule this body was.';
COMMENT ON COLUMN apiome.slate_security_rule_revisions.body IS
    'The complete rule body, so reverting applies a stored document rather than reconstructing intent from a sentence.';
COMMENT ON COLUMN apiome.slate_security_rule_revisions.body_digest IS
    'sha256 over the canonical body, matching slate_security_rules.body_digest at that revision.';
COMMENT ON COLUMN apiome.slate_security_rule_revisions.change_kind IS
    'What produced this revision, so a revert of a revert reads correctly in history.';
COMMENT ON COLUMN apiome.slate_security_rule_revisions.at IS
    'When the change happened.';
COMMENT ON COLUMN apiome.slate_security_rule_revisions.actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_security_rule_revisions.actor_name IS
    'Display name of the actor, stored so history survives user deletion.';

CREATE INDEX IF NOT EXISTS idx_slate_security_rule_revisions_rule
    ON apiome.slate_security_rule_revisions (rule_id, revision DESC);
CREATE INDEX IF NOT EXISTS idx_slate_security_rule_revisions_environment
    ON apiome.slate_security_rule_revisions (environment_id, at DESC);

-- ─── 5. Exceptions ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_security_exceptions (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id      UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id UUID NOT NULL
                   REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    -- What the carve-out applies to: a managed group id, a custom rule id, or the whole lane.
    subject_kind   TEXT NOT NULL
                   CHECK (subject_kind IN ('managed-group', 'rule', 'policy')),
    subject_ref    TEXT NOT NULL,
    matcher_kind   TEXT NOT NULL
                   CHECK (matcher_kind IN ('exact', 'prefix', 'glob', 'regex')),
    matcher_value  TEXT NOT NULL,
    -- An exception is a hole. §29.4 wants them possible; keeping them bounded is what keeps them
    -- from becoming the policy, so an expiry is required rather than optional. This is the one
    -- place this schema is stricter than its cache counterpart, deliberately.
    expires_at     TIMESTAMP WITH TIME ZONE NOT NULL,
    reason         TEXT NOT NULL,
    created_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id       UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    actor_name     TEXT NOT NULL,
    CONSTRAINT slate_security_exceptions_expiry_after_creation
        CHECK (expires_at > created_at)
);

COMMENT ON TABLE apiome.slate_security_exceptions IS
    'Scoped carve-outs from a managed group, a custom rule or the whole lane (UXE-3.2). Every exception expires: an exception that cannot lapse stops being an exception and becomes the policy.';
COMMENT ON COLUMN apiome.slate_security_exceptions.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_security_exceptions.environment_id IS
    'Environment the exception applies to.';
COMMENT ON COLUMN apiome.slate_security_exceptions.subject_kind IS
    'Whether the carve-out targets a managed group, one custom rule, or the whole policy.';
COMMENT ON COLUMN apiome.slate_security_exceptions.subject_ref IS
    'The managed group id or rule id the exception applies to; ignored for policy-wide exceptions.';
COMMENT ON COLUMN apiome.slate_security_exceptions.matcher_kind IS
    'How matcher_value is interpreted: exact, prefix, glob or regex.';
COMMENT ON COLUMN apiome.slate_security_exceptions.matcher_value IS
    'The route pattern the exception covers.';
COMMENT ON COLUMN apiome.slate_security_exceptions.expires_at IS
    'When the carve-out lapses. NOT NULL, and required to be after creation: a permanent exception is not an exception.';
COMMENT ON COLUMN apiome.slate_security_exceptions.reason IS
    'Why the carve-out exists. NOT NULL: an unexplained hole is the one nobody can justify at review.';
COMMENT ON COLUMN apiome.slate_security_exceptions.created_at IS
    'When the exception was created.';
COMMENT ON COLUMN apiome.slate_security_exceptions.actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_security_exceptions.actor_name IS
    'Display name of the actor, stored so history survives user deletion.';

CREATE INDEX IF NOT EXISTS idx_slate_security_exceptions_environment
    ON apiome.slate_security_exceptions (environment_id, expires_at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_security_exceptions_subject
    ON apiome.slate_security_exceptions (subject_kind, subject_ref);

-- ─── 6. Approvals (dual control) ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_security_approvals (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id      UUID NOT NULL
                        REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    subject_kind        TEXT NOT NULL
                        CHECK (subject_kind IN ('rule', 'exception', 'policy', 'managed-group')),
    subject_id          TEXT NOT NULL,
    -- What was approved, content-addressed. An approval that names only a row id would still look
    -- valid after that row changed underneath it; a digest makes a stale approval detectable.
    digest              TEXT NOT NULL CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
    author_actor_id     UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    author_actor_name   TEXT NOT NULL,
    -- Immutable identity captured at write time. The distinctness CHECK compares these rather
    -- than the nullable user ids above, because those are ON DELETE SET NULL and a deleted user
    -- would turn a genuine two-person approval into two NULLs that no longer look distinct. A
    -- constraint that weakens when somebody is offboarded is not a constraint.
    author_actor_key    TEXT NOT NULL,
    approver_actor_id   UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    approver_actor_name TEXT NOT NULL,
    approver_actor_key  TEXT NOT NULL,
    approved_at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note                TEXT,
    -- Two-person review, as a database fact rather than an application convention. This is the
    -- constraint V186's slate_release_approvals does not have.
    CONSTRAINT slate_security_approvals_distinct_actors
        CHECK (approver_actor_key <> author_actor_key),
    -- One approver approves a given body once. Without this, a single approver could satisfy a
    -- two-approval requirement by pressing the button twice.
    UNIQUE (subject_id, digest, approver_actor_key)
);

COMMENT ON TABLE apiome.slate_security_approvals IS
    'Dual-control approvals for security changes (UXE-3.2). Unlike V186 slate_release_approvals, the author cannot be the approver, and that is enforced by CHECK rather than by convention.';
COMMENT ON COLUMN apiome.slate_security_approvals.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_security_approvals.environment_id IS
    'Environment the approved change applies to.';
COMMENT ON COLUMN apiome.slate_security_approvals.subject_kind IS
    'What was approved: a rule, an exception, the policy, or a managed group mode.';
COMMENT ON COLUMN apiome.slate_security_approvals.subject_id IS
    'Id of the subject. TEXT because a managed group is identified by its catalog id rather than a UUID.';
COMMENT ON COLUMN apiome.slate_security_approvals.digest IS
    'sha256 over the canonical body that was approved. An approval naming only a row id would still look valid after that row changed underneath it.';
COMMENT ON COLUMN apiome.slate_security_approvals.author_actor_id IS
    'User who proposed the change, when still present.';
COMMENT ON COLUMN apiome.slate_security_approvals.author_actor_name IS
    'Display name of the author, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_security_approvals.author_actor_key IS
    'Immutable identity of the author captured at write time. The distinctness CHECK uses this, not the nullable user id, so offboarding cannot weaken a recorded approval.';
COMMENT ON COLUMN apiome.slate_security_approvals.approver_actor_id IS
    'User who approved, when still present.';
COMMENT ON COLUMN apiome.slate_security_approvals.approver_actor_name IS
    'Display name of the approver, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_security_approvals.approver_actor_key IS
    'Immutable identity of the approver captured at write time.';
COMMENT ON COLUMN apiome.slate_security_approvals.approved_at IS
    'When the approval was recorded.';
COMMENT ON COLUMN apiome.slate_security_approvals.note IS
    'Optional reviewer note.';

CREATE INDEX IF NOT EXISTS idx_slate_security_approvals_subject
    ON apiome.slate_security_approvals (subject_id, digest);
CREATE INDEX IF NOT EXISTS idx_slate_security_approvals_environment
    ON apiome.slate_security_approvals (environment_id, approved_at DESC);

-- ─── 7. Security events ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_security_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id  UUID NOT NULL
                    REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Where the event came from. 'policy-simulation' is a deterministic evaluation of stored
    -- policy against a test request; 'edge-observed' is a real request something in the path
    -- actually saw. The CHECK below makes the second impossible without a delivery tier, so this
    -- column cannot quietly become a claim nothing supports.
    source          TEXT NOT NULL DEFAULT 'policy-simulation'
                    CHECK (source IN ('policy-simulation', 'edge-observed')),
    -- The §29.4 correlation axes. rule/route/release/region/action, each stored at the grain it
    -- is actually available at rather than the grain that would look tidiest.
    rule_kind       TEXT NOT NULL
                    CHECK (rule_kind IN ('managed-group', 'rule', 'bot-preset', 'rate-preset')),
    -- Catalog id or rule UUID as text. No foreign key: an event must survive the deletion of the
    -- rule that produced it, which is precisely the case an investigation cares about.
    rule_ref        TEXT NOT NULL,
    rule_label      TEXT NOT NULL,
    -- Free text with no FK. slate_release_changed_pages carries only per-release CHANGED routes,
    -- so it is not a route inventory and cannot be the referent for an arbitrary request path.
    route           TEXT NOT NULL,
    method          TEXT NOT NULL DEFAULT 'GET',
    release_id      UUID REFERENCES apiome.slate_releases(id) ON DELETE SET NULL,
    -- TEXT to match slate_release_regions.region_id, which is itself unconstrained: there is no
    -- canonical region registry to point at.
    region          TEXT,
    action          TEXT NOT NULL
                    CHECK (action IN ('allowed', 'logged', 'challenged', 'rate-limited',
                                      'blocked', 'would-block')),
    -- Whether the request was actually stopped. FALSE for everything this system can currently
    -- write; the CHECK ties it to a delivery tier so a simulation can never claim a mitigation.
    mitigated       BOOLEAN NOT NULL DEFAULT FALSE,
    -- Snapshot of the policy's edge_attached at event time, denormalized for the same reason
    -- slate_cache_purges snapshots it: attaching an edge later must not make old rows look real.
    edge_attached   BOOLEAN NOT NULL DEFAULT FALSE,
    -- Redacted request evidence. Constrained to an ALLOWLIST by the CHECK below rather than
    -- filtered by a denylist, because a denylist fails open on the field nobody thought of.
    evidence        JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Request data is a liability, not an asset. An audit row should live forever; a captured
    -- user agent should not.
    retain_until    TIMESTAMP WITH TIME ZONE NOT NULL,
    -- `jsonb - text[]` removes every listed key, so the result is empty only when every key
    -- present was one of the permitted ones. A subquery or a set-returning function cannot appear
    -- in a CHECK, and this expression is both scalar and immutable. Adding a key to this list is
    -- a migration that has to justify itself; storing `authorization` or `cookie` is impossible.
    CONSTRAINT slate_security_events_evidence_allowlisted
        CHECK (evidence - ARRAY['method', 'path', 'query', 'userAgent', 'country', 'asn',
                                'clientIpPrefix', 'matchedFragment', 'statusCode',
                                'botClass'] = '{}'::jsonb),
    CONSTRAINT slate_security_events_retention_after_event
        CHECK (retain_until > at),
    -- Nothing was observed, because there is nothing in the request path to observe it.
    CONSTRAINT slate_security_events_observed_needs_edge
        CHECK (source <> 'edge-observed' OR edge_attached),
    -- Nothing was stopped, for the same reason.
    CONSTRAINT slate_security_events_mitigated_needs_edge
        CHECK (mitigated = FALSE OR edge_attached)
);

COMMENT ON TABLE apiome.slate_security_events IS
    'Security events (UXE-3.2) joining rule, route, release, region and action with allowlisted, expiring request evidence. Simulated policy decisions until a delivery tier is attached.';
COMMENT ON COLUMN apiome.slate_security_events.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_security_events.environment_id IS
    'Environment the event belongs to.';
COMMENT ON COLUMN apiome.slate_security_events.at IS
    'When the event happened.';
COMMENT ON COLUMN apiome.slate_security_events.source IS
    'policy-simulation (a deterministic evaluation of stored policy) or edge-observed (a request something in the path actually saw). The latter requires an attached delivery tier.';
COMMENT ON COLUMN apiome.slate_security_events.rule_kind IS
    'What produced the event: a managed group, a custom rule, or a bot or rate preset.';
COMMENT ON COLUMN apiome.slate_security_events.rule_ref IS
    'Catalog id or rule UUID as text. No foreign key: an event must survive deletion of the rule that produced it, which is exactly the case an investigation cares about.';
COMMENT ON COLUMN apiome.slate_security_events.rule_label IS
    'The rule label as it read when the event happened, so history does not change meaning when a rule is renamed.';
COMMENT ON COLUMN apiome.slate_security_events.route IS
    'Request path. Free text with no FK: slate_release_changed_pages holds only per-release changed routes and is not a route inventory.';
COMMENT ON COLUMN apiome.slate_security_events.method IS
    'Request method.';
COMMENT ON COLUMN apiome.slate_security_events.release_id IS
    'Release active when the event happened, or NULL. SET NULL rather than CASCADE: the event outlives the release.';
COMMENT ON COLUMN apiome.slate_security_events.region IS
    'Region that handled the request. TEXT to match slate_release_regions.region_id; there is no canonical region registry to reference.';
COMMENT ON COLUMN apiome.slate_security_events.action IS
    'What the policy decided: allowed, logged, challenged, rate-limited, blocked or would-block. would-block is what a simulated enforcing rule reports.';
COMMENT ON COLUMN apiome.slate_security_events.mitigated IS
    'Whether the request was actually stopped. FALSE for every row this system can currently write; CHECK-tied to edge_attached so a simulation cannot claim a mitigation.';
COMMENT ON COLUMN apiome.slate_security_events.edge_attached IS
    'Whether a delivery tier was attached when this event was written. Snapshotted so attaching one later cannot make old rows look observed.';
COMMENT ON COLUMN apiome.slate_security_events.evidence IS
    'Redacted request evidence, constrained to an allowlist of keys by CHECK. A denylist would fail open on the field nobody thought of; this cannot store a cookie or an authorization header at all.';
COMMENT ON COLUMN apiome.slate_security_events.retain_until IS
    'When this evidence must be purged. Request data is a liability rather than an asset: the audit row lives forever, the captured user agent does not.';

CREATE INDEX IF NOT EXISTS idx_slate_security_events_environment
    ON apiome.slate_security_events (environment_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_security_events_tenant
    ON apiome.slate_security_events (tenant_id, at DESC);
-- The event explorer filters by rule and by action; both are the first thing an investigation
-- narrows on, so neither should be a sequential scan.
CREATE INDEX IF NOT EXISTS idx_slate_security_events_rule
    ON apiome.slate_security_events (environment_id, rule_ref, at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_security_events_action
    ON apiome.slate_security_events (environment_id, action, at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_security_events_release
    ON apiome.slate_security_events (release_id)
    WHERE release_id IS NOT NULL;
-- Retention sweep. Partial, because the sweep only ever asks for rows already past their date.
CREATE INDEX IF NOT EXISTS idx_slate_security_events_retention
    ON apiome.slate_security_events (retain_until);

-- ─── 8. Audit (append-only) ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_security_audit (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id      UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id UUID NOT NULL
                   REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id       UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    actor_name     TEXT NOT NULL,
    actor_kind     TEXT NOT NULL CHECK (actor_kind IN ('user', 'automation')),
    subject_kind   TEXT NOT NULL
                   CHECK (subject_kind IN ('policy', 'managed-group', 'rule', 'exception',
                                           'approval', 'simulation', 'revert', 'export')),
    subject_id     TEXT,
    summary        TEXT NOT NULL,
    detail         TEXT
);

COMMENT ON TABLE apiome.slate_security_audit IS
    'Append-only audit of every security policy change, approval, revert, refusal and evidence export (UXE-3.2). UPDATE and DELETE are refused by trigger, so history only ever grows.';
COMMENT ON COLUMN apiome.slate_security_audit.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_security_audit.environment_id IS
    'Environment the entry describes.';
COMMENT ON COLUMN apiome.slate_security_audit.at IS
    'When the event happened.';
COMMENT ON COLUMN apiome.slate_security_audit.actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_security_audit.actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_security_audit.actor_kind IS
    'Whether a person or a system acted.';
COMMENT ON COLUMN apiome.slate_security_audit.subject_kind IS
    'What the entry is about. export is included because who read the evidence is itself audit-worthy.';
COMMENT ON COLUMN apiome.slate_security_audit.subject_id IS
    'Id of the subject when there is one. TEXT because a managed group is identified by catalog id rather than UUID.';
COMMENT ON COLUMN apiome.slate_security_audit.summary IS
    'What happened, e.g. "Managed ruleset disabled" or "Rule reverted to revision 3".';
COMMENT ON COLUMN apiome.slate_security_audit.detail IS
    'Extra context, e.g. the refusal reason and its sentence, or the digest that was approved.';

CREATE INDEX IF NOT EXISTS idx_slate_security_audit_environment
    ON apiome.slate_security_audit (environment_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_security_audit_tenant
    ON apiome.slate_security_audit (tenant_id, at DESC);

-- An audit log that can be edited is not an audit log. Both verbs are refused at the database, so
-- no application bug and no ad-hoc session can quietly rewrite what happened. This matters more
-- here than it did for cache: the record of who disabled the WAF, who approved it and who
-- exported the evidence is the entire basis of the security review that follows an incident.
CREATE OR REPLACE FUNCTION apiome.slate_security_audit_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'slate_security_audit is append-only: % is not permitted', TG_OP
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.slate_security_audit_append_only() IS
    'Refuses UPDATE and DELETE on slate_security_audit (UXE-3.2). Audit entries are appended to, never rewritten.';

DROP TRIGGER IF EXISTS trg_slate_security_audit_append_only ON apiome.slate_security_audit;
CREATE TRIGGER trg_slate_security_audit_append_only
    BEFORE UPDATE OR DELETE ON apiome.slate_security_audit
    FOR EACH ROW EXECUTE FUNCTION apiome.slate_security_audit_append_only();
