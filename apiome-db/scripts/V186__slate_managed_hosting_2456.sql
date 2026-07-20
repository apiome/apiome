-- Managed Slate hosting and immutable versioned deployment (APX-3.1, private-suite#2456).
--
-- ZIP download and bring-your-own-CDN export cannot carry a paid publishing product: neither
-- can say what is currently serving production, neither can put it back, and neither leaves
-- evidence that survives the person who ran it. This migration adds the control-plane schema
-- for managed hosting — content-addressed artifacts, environments, immutable releases, atomic
-- activation, retention and audit.
--
-- The shape here is not invented. `private-suite/designer/lib/authoring/release-model.ts`
-- (UXE-2.4, blueprint §28.3) already defines the release record the Release Center renders and
-- announces, and names the fields that may never change after creation. These tables are that
-- contract expressed in SQL, so the guarantee the UI asserts in TypeScript is also enforced by
-- the database rather than only by the process that writes to it.
--
--   1. `apiome.slate_sites`          — one hosted site per project; owns retention policy.
--   2. `apiome.slate_artifacts`      — content-addressed, signed build output. The digest IS
--                                      the identity: same digest means the same bytes, which is
--                                      what makes "promotion never rebuilds" checkable rather
--                                      than merely promised.
--   3. `apiome.slate_environments`   — production / staging / ephemeral preview lanes. Holds
--                                      `active_release_id` (the routing pointer) and
--                                      `routing_version` (its optimistic-concurrency token).
--   4. `apiome.slate_releases`       — the immutable release record. A trigger rejects any
--                                      update touching identity columns.
--   5. Release evidence              — regions, approvals, checks, phases, logs, changed pages.
--   6. `apiome.slate_release_audit`  — append-only; UPDATE and DELETE are refused.
--   7. `apiome.slate_domains`        — hosted domain inventory with TLS and verification state.
--   8. `apiome.slate_activations`    — the activation ledger: every routing change, including
--                                      the ones that failed or only partly landed.
--
-- Atomic activation (acceptance criterion 2). Activation is ONE statement:
--
--     UPDATE apiome.slate_environments
--        SET active_release_id = :to, routing_version = routing_version + 1
--      WHERE id = :env AND routing_version = :expected
--
-- A single row update is atomic in PostgreSQL, so a reader never observes a lane between two
-- releases. The `routing_version` predicate is what makes concurrent promotion safe: the second
-- writer matches zero rows and is reported as a conflict rather than silently overwriting the
-- first (acceptance criterion 4). There is deliberately no last-write-wins path.
--
-- Promotion never rebuilds (acceptance criterion 3). A promotion inserts a release that points
-- at an ALREADY EXISTING `slate_artifacts` row and then moves the pointer. Nothing in this
-- schema lets a promotion produce an artifact — `artifact_id` is a reference, never a build
-- instruction — and rollback simply routes back to a retained artifact that is still present.
--
-- Scope boundary, stated plainly. `deploy/` in this repository is a single Caddyfile and there
-- is no multi-region edge or CDN behind it. `slate_release_regions` and `slate_activations`
-- record per-region rollout because a partial activation is a real failure the Release Center
-- must not report as success, but what this schema drives today is the routing pointer, not a
-- live global edge. The edge integration is APX-3.2/UXE-3.x; this is the control plane it will
-- report into.

SET search_path TO apiome, public;

-- ─── 1. Sites ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_sites (
    id                     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id              UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    project_id             UUID NOT NULL REFERENCES apiome.projects(id) ON DELETE CASCADE,
    name                   TEXT NOT NULL,
    slug                   TEXT NOT NULL,
    -- How many superseded releases per environment keep their artifact. This is the rollback
    -- window expressed as a number: an artifact that has been reaped is no longer a rollback
    -- target, so retention policy and recovery capability are the same setting.
    retained_releases      INTEGER NOT NULL DEFAULT 10 CHECK (retained_releases >= 1),
    -- Budget for a full activation, in seconds. The gap between a release's activated_at and
    -- activation_completed_at is measured against this; see slate_activations.
    activation_slo_seconds INTEGER NOT NULL DEFAULT 300 CHECK (activation_slo_seconds > 0),
    created_at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, slug)
);

COMMENT ON TABLE apiome.slate_sites IS
    'One managed Slate site per project (APX-3.1, private-suite#2456). Owns retention and activation-SLO policy for its environments.';
COMMENT ON COLUMN apiome.slate_sites.tenant_id IS
    'Owning tenant. Denormalized onto every slate_* table so queries and unique constraints stay tenant-scoped without multi-way joins.';
COMMENT ON COLUMN apiome.slate_sites.project_id IS
    'Project whose documentation this site publishes.';
COMMENT ON COLUMN apiome.slate_sites.name IS
    'Human-facing site name shown in the Release Center.';
COMMENT ON COLUMN apiome.slate_sites.slug IS
    'URL-safe site identifier, unique per tenant; forms the default managed hostname.';
COMMENT ON COLUMN apiome.slate_sites.retained_releases IS
    'Superseded releases per environment whose artifact is retained. Defines the rollback window: a reaped artifact is not a rollback target.';
COMMENT ON COLUMN apiome.slate_sites.activation_slo_seconds IS
    'Seconds allowed between activation start and every region completing, before the activation is reported as breaching its SLO.';
COMMENT ON COLUMN apiome.slate_sites.created_at IS
    'When the site was created.';

CREATE INDEX IF NOT EXISTS idx_slate_sites_tenant
    ON apiome.slate_sites (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_sites_project
    ON apiome.slate_sites (project_id);

-- ─── 2. Artifacts ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_artifacts (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id         UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    site_id           UUID NOT NULL REFERENCES apiome.slate_sites(id) ON DELETE CASCADE,
    -- The three digests the acceptance criteria name. content_digest addresses the rendered
    -- bytes; source_digest and config_digest address what produced them, which is what makes a
    -- build reproducible-in-principle and lets an identical rebuild be recognized as identical.
    content_digest    TEXT NOT NULL CHECK (content_digest ~ '^sha256:[0-9a-f]{64}$'),
    source_digest     TEXT NOT NULL CHECK (source_digest  ~ '^sha256:[0-9a-f]{64}$'),
    config_digest     TEXT NOT NULL CHECK (config_digest  ~ '^sha256:[0-9a-f]{64}$'),
    -- Detached signature over the three digests, plus the id of the key that produced it.
    -- Verification is a control-plane gate: an artifact whose signature does not verify is
    -- never routable, so tampering with stored bytes cannot silently reach production.
    signature         TEXT NOT NULL,
    signature_key_id  TEXT NOT NULL,
    -- Build manifest / SBOM: generator versions, inputs, page inventory, dependency list.
    manifest          JSONB NOT NULL DEFAULT '{}'::jsonb,
    page_count        INTEGER NOT NULL DEFAULT 0 CHECK (page_count >= 0),
    size_bytes        BIGINT NOT NULL DEFAULT 0 CHECK (size_bytes >= 0),
    -- Where the bytes live. NULL once the artifact has been reaped by retention, which is how
    -- "retained" and "still rollback-able" stay the same fact.
    storage_uri       TEXT,
    built_at          TIMESTAMP WITH TIME ZONE,
    reaped_at         TIMESTAMP WITH TIME ZONE,
    created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Content addressing: the same bytes are stored once per site. A rebuild that produces an
    -- identical digest reuses this row rather than creating a second identity for one artifact.
    UNIQUE (site_id, content_digest)
);

COMMENT ON TABLE apiome.slate_artifacts IS
    'Content-addressed, signed Slate build output (APX-3.1, private-suite#2456). The content digest is the artifact identity; promotion routes to it and never rebuilds it.';
COMMENT ON COLUMN apiome.slate_artifacts.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_artifacts.site_id IS
    'Site this artifact was built for.';
COMMENT ON COLUMN apiome.slate_artifacts.content_digest IS
    'sha256 over the rendered site bytes. The release identity: two releases carrying this digest serve identical bytes.';
COMMENT ON COLUMN apiome.slate_artifacts.source_digest IS
    'sha256 over the source inputs (catalog revision, guides, changelog) the build consumed.';
COMMENT ON COLUMN apiome.slate_artifacts.config_digest IS
    'sha256 over the build configuration (theme, navigation, generator options) the build applied.';
COMMENT ON COLUMN apiome.slate_artifacts.signature IS
    'Detached signature over the three digests. An artifact whose signature does not verify is refused activation.';
COMMENT ON COLUMN apiome.slate_artifacts.signature_key_id IS
    'Identifier of the signing key, so signatures remain verifiable across key rotation.';
COMMENT ON COLUMN apiome.slate_artifacts.manifest IS
    'Build manifest / SBOM: generator versions, resolved inputs, page inventory and dependencies.';
COMMENT ON COLUMN apiome.slate_artifacts.page_count IS
    'Rendered page count, used for rollback and invalidation scope previews.';
COMMENT ON COLUMN apiome.slate_artifacts.size_bytes IS
    'Total artifact size in bytes.';
COMMENT ON COLUMN apiome.slate_artifacts.storage_uri IS
    'Location of the stored bytes. NULL once retention has reaped the artifact, which also removes it as a rollback target.';
COMMENT ON COLUMN apiome.slate_artifacts.built_at IS
    'When the build finished. NULL while the release is still building.';
COMMENT ON COLUMN apiome.slate_artifacts.reaped_at IS
    'When retention removed the stored bytes. NULL while the artifact is retained.';
COMMENT ON COLUMN apiome.slate_artifacts.created_at IS
    'When the artifact row was created.';

CREATE INDEX IF NOT EXISTS idx_slate_artifacts_site
    ON apiome.slate_artifacts (site_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_artifacts_tenant
    ON apiome.slate_artifacts (tenant_id, created_at DESC);
-- Retention sweeps look only at artifacts that still hold bytes.
CREATE INDEX IF NOT EXISTS idx_slate_artifacts_retained
    ON apiome.slate_artifacts (site_id, created_at DESC)
    WHERE reaped_at IS NULL;

-- ─── 3. Environments ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_environments (
    id                     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id              UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    site_id                UUID NOT NULL REFERENCES apiome.slate_sites(id) ON DELETE CASCADE,
    kind                   TEXT NOT NULL CHECK (kind IN ('production', 'staging', 'preview')),
    name                   TEXT NOT NULL,
    -- The routing pointer. NULL means the lane has never served a release, which is a real and
    -- distinct state from "serving nothing because the last release was rolled back".
    -- The foreign key is added after slate_releases exists (the two tables reference each other).
    active_release_id      UUID,
    -- Optimistic-concurrency token for activation. Every routing change bumps it and every
    -- activation asserts the value it read, so two concurrent promotions cannot both win.
    routing_version        BIGINT NOT NULL DEFAULT 0,
    -- Preview lanes are excluded from indexing by default; production is not. Stored per lane
    -- rather than derived from `kind` so a staging lane can be made public deliberately.
    robots_excluded        BOOLEAN NOT NULL DEFAULT FALSE,
    -- Ephemeral preview expiry. NULL for durable lanes.
    expires_at             TIMESTAMP WITH TIME ZONE,
    -- Preview protection: who may read this lane.
    access_policy          TEXT NOT NULL DEFAULT 'public'
                           CHECK (access_policy IN ('public', 'tenant', 'password', 'sso')),
    created_at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (site_id, name)
);

COMMENT ON TABLE apiome.slate_environments IS
    'Production, staging and ephemeral preview lanes for a Slate site (APX-3.1, private-suite#2456). Holds the routing pointer and its concurrency token.';
COMMENT ON COLUMN apiome.slate_environments.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_environments.site_id IS
    'Site this lane belongs to.';
COMMENT ON COLUMN apiome.slate_environments.kind IS
    'Lane kind: production, staging or ephemeral preview.';
COMMENT ON COLUMN apiome.slate_environments.name IS
    'Lane name, unique per site (e.g. production, staging, preview-pr-412).';
COMMENT ON COLUMN apiome.slate_environments.active_release_id IS
    'Release currently serving this lane. NULL when the lane has never served one. Changed only by the single-statement atomic activation.';
COMMENT ON COLUMN apiome.slate_environments.routing_version IS
    'Optimistic-concurrency token. Activation asserts the value it read and bumps it, so a concurrent promotion is refused rather than silently overwritten.';
COMMENT ON COLUMN apiome.slate_environments.robots_excluded IS
    'True when the lane must not be indexed by crawlers. Defaults false; preview lanes are created with it true.';
COMMENT ON COLUMN apiome.slate_environments.expires_at IS
    'When an ephemeral preview lane expires. NULL for durable lanes.';
COMMENT ON COLUMN apiome.slate_environments.access_policy IS
    'Who may read the lane: public, tenant members, a shared password, or SSO.';
COMMENT ON COLUMN apiome.slate_environments.created_at IS
    'When the lane was created.';

CREATE INDEX IF NOT EXISTS idx_slate_environments_site
    ON apiome.slate_environments (site_id, kind);
CREATE INDEX IF NOT EXISTS idx_slate_environments_tenant
    ON apiome.slate_environments (tenant_id);
-- Expiry sweeps for ephemeral previews.
CREATE INDEX IF NOT EXISTS idx_slate_environments_expiring
    ON apiome.slate_environments (expires_at)
    WHERE expires_at IS NOT NULL;

-- ─── 4. Releases ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_releases (
    id                        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id                 UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    site_id                   UUID NOT NULL REFERENCES apiome.slate_sites(id) ON DELETE CASCADE,
    environment_id            UUID NOT NULL REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    -- Short, human-quotable id (the Release Center's `r-4821`). Unique per site so an operator
    -- can name a release in an incident channel without ambiguity.
    release_ref               TEXT NOT NULL,
    -- NULL only while the release is queued or building, and while failed — a release that
    -- never produced bytes has no artifact, and that is exactly why it cannot be promoted.
    artifact_id               UUID REFERENCES apiome.slate_artifacts(id) ON DELETE RESTRICT,
    status                    TEXT NOT NULL DEFAULT 'queued'
                              CHECK (status IN ('queued', 'building', 'ready', 'review',
                                                'active', 'superseded', 'failed', 'rolled-back')),
    source_commit             TEXT NOT NULL,
    source_ref                TEXT NOT NULL,
    source_message            TEXT NOT NULL,
    actor_id                  UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    actor_name                TEXT NOT NULL,
    actor_kind                TEXT NOT NULL CHECK (actor_kind IN ('user', 'automation')),
    -- Cache and security consequences of routing here (release-model.ts `impact`).
    impact                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Live traffic. Present only while the release serves the lane.
    traffic_percent           INTEGER CHECK (traffic_percent BETWEEN 0 AND 100),
    traffic_requests_per_min  INTEGER CHECK (traffic_requests_per_min >= 0),
    created_at                TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    activated_at              TIMESTAMP WITH TIME ZONE,
    -- Separate from activated_at because the gap between them IS the activation SLO.
    -- Collapsing them would make every rollout look instantaneous and leave nothing to measure.
    activation_completed_at   TIMESTAMP WITH TIME ZONE,
    deactivated_at            TIMESTAMP WITH TIME ZONE,
    UNIQUE (site_id, release_ref)
);

COMMENT ON TABLE apiome.slate_releases IS
    'Immutable release record (APX-3.1, private-suite#2456). Identity columns are enforced by the slate_release_immutability_guard trigger, not by convention.';
COMMENT ON COLUMN apiome.slate_releases.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_releases.site_id IS
    'Site the release belongs to.';
COMMENT ON COLUMN apiome.slate_releases.environment_id IS
    'Lane the release was created for. Immutable: promoting to another lane creates a new release pointing at the same artifact.';
COMMENT ON COLUMN apiome.slate_releases.release_ref IS
    'Short human-quotable release id, unique per site (e.g. r-4821).';
COMMENT ON COLUMN apiome.slate_releases.artifact_id IS
    'Built artifact this release routes to. NULL while queued/building or when the build failed; a release with no artifact cannot be promoted.';
COMMENT ON COLUMN apiome.slate_releases.status IS
    'Lifecycle state, matching the Release Center vocabulary: queued, building, ready, review, active, superseded, failed, rolled-back.';
COMMENT ON COLUMN apiome.slate_releases.source_commit IS
    'Full commit sha the release was built from.';
COMMENT ON COLUMN apiome.slate_releases.source_ref IS
    'Branch or tag the commit was taken from.';
COMMENT ON COLUMN apiome.slate_releases.source_message IS
    'First line of the commit message.';
COMMENT ON COLUMN apiome.slate_releases.actor_id IS
    'User who caused the release, when a person did. NULL for automation or after user deletion.';
COMMENT ON COLUMN apiome.slate_releases.actor_name IS
    'Display name of the actor. Stored rather than joined so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_releases.actor_kind IS
    'Whether a person or a system acted: "who deployed this" answered with a service account is a different answer from a colleague.';
COMMENT ON COLUMN apiome.slate_releases.impact IS
    'Cache/security consequences of activation: invalidated page count, security preset, and whether the preset changes.';
COMMENT ON COLUMN apiome.slate_releases.traffic_percent IS
    'Share of lane traffic served by this release, 0-100. NULL when the release serves none.';
COMMENT ON COLUMN apiome.slate_releases.traffic_requests_per_min IS
    'Requests per minute currently served. NULL when the release serves no traffic.';
COMMENT ON COLUMN apiome.slate_releases.created_at IS
    'When the release was created. Orders the timeline and can never change.';
COMMENT ON COLUMN apiome.slate_releases.activated_at IS
    'When the release began serving traffic. NULL when it never has.';
COMMENT ON COLUMN apiome.slate_releases.activation_completed_at IS
    'When every region finished switching. The gap from activated_at is the measured activation SLO.';
COMMENT ON COLUMN apiome.slate_releases.deactivated_at IS
    'When the release stopped serving traffic. NULL while still active.';

CREATE INDEX IF NOT EXISTS idx_slate_releases_environment
    ON apiome.slate_releases (environment_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_releases_site
    ON apiome.slate_releases (site_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_releases_tenant
    ON apiome.slate_releases (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_releases_artifact
    ON apiome.slate_releases (artifact_id);
-- Rollback target lookup: the most recent superseded release in a lane that still has bytes.
CREATE INDEX IF NOT EXISTS idx_slate_releases_rollback_targets
    ON apiome.slate_releases (environment_id, deactivated_at DESC)
    WHERE status = 'superseded' AND artifact_id IS NOT NULL;

-- The routing pointer references a release; the release references its lane. Declared here,
-- after both tables exist, because the dependency is genuinely circular.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_slate_environments_active_release'
    ) THEN
        ALTER TABLE apiome.slate_environments
            ADD CONSTRAINT fk_slate_environments_active_release
            FOREIGN KEY (active_release_id)
            REFERENCES apiome.slate_releases(id) ON DELETE SET NULL;
    END IF;
END $$;

-- Immutability. `release-model.ts` lists the fields a release may never change; this trigger is
-- the same list, enforced one layer lower. Without it, "immutable" would be a property of the
-- application code that happens to write these rows, which is not the same as a guarantee.
CREATE OR REPLACE FUNCTION apiome.slate_release_immutability_guard()
RETURNS trigger AS $$
DECLARE
    v_changed TEXT[] := ARRAY[]::TEXT[];
BEGIN
    IF NEW.id             IS DISTINCT FROM OLD.id             THEN v_changed := v_changed || 'id';             END IF;
    IF NEW.tenant_id      IS DISTINCT FROM OLD.tenant_id      THEN v_changed := v_changed || 'tenant_id';      END IF;
    IF NEW.site_id        IS DISTINCT FROM OLD.site_id        THEN v_changed := v_changed || 'site_id';        END IF;
    IF NEW.environment_id IS DISTINCT FROM OLD.environment_id THEN v_changed := v_changed || 'environment_id'; END IF;
    IF NEW.release_ref    IS DISTINCT FROM OLD.release_ref    THEN v_changed := v_changed || 'release_ref';    END IF;
    IF NEW.source_commit  IS DISTINCT FROM OLD.source_commit  THEN v_changed := v_changed || 'source_commit';  END IF;
    IF NEW.source_ref     IS DISTINCT FROM OLD.source_ref     THEN v_changed := v_changed || 'source_ref';     END IF;
    IF NEW.source_message IS DISTINCT FROM OLD.source_message THEN v_changed := v_changed || 'source_message'; END IF;
    IF NEW.actor_id       IS DISTINCT FROM OLD.actor_id       THEN v_changed := v_changed || 'actor_id';       END IF;
    IF NEW.actor_name     IS DISTINCT FROM OLD.actor_name     THEN v_changed := v_changed || 'actor_name';     END IF;
    IF NEW.actor_kind     IS DISTINCT FROM OLD.actor_kind     THEN v_changed := v_changed || 'actor_kind';     END IF;
    IF NEW.impact         IS DISTINCT FROM OLD.impact         THEN v_changed := v_changed || 'impact';         END IF;
    IF NEW.created_at     IS DISTINCT FROM OLD.created_at     THEN v_changed := v_changed || 'created_at';     END IF;

    -- The artifact may be attached exactly once, when the build that produced it finishes.
    -- Re-pointing an existing release at different bytes is the supply-chain failure this whole
    -- table exists to prevent: it would let approved-and-audited history serve something else.
    IF OLD.artifact_id IS NOT NULL AND NEW.artifact_id IS DISTINCT FROM OLD.artifact_id THEN
        v_changed := v_changed || 'artifact_id';
    END IF;

    IF array_length(v_changed, 1) > 0 THEN
        RAISE EXCEPTION
            'slate_releases is immutable: % cannot change after the release is created',
            array_to_string(v_changed, ', ')
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.slate_release_immutability_guard() IS
    'Rejects updates to release identity columns (APX-3.1). Mirrors IMMUTABLE_FIELDS in designer/lib/authoring/release-model.ts; artifact_id may be attached once, never repointed.';

DROP TRIGGER IF EXISTS trg_slate_release_immutability ON apiome.slate_releases;
CREATE TRIGGER trg_slate_release_immutability
    BEFORE UPDATE ON apiome.slate_releases
    FOR EACH ROW EXECUTE FUNCTION apiome.slate_release_immutability_guard();

-- ─── 5. Release evidence ─────────────────────────────────────────────────────

-- Regions are tracked individually because a partial activation is a real and common failure:
-- reporting a release as active while a region still serves the previous artifact is exactly
-- the lie the Release Center exists to stop.
CREATE TABLE IF NOT EXISTS apiome.slate_release_regions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    release_id  UUID NOT NULL REFERENCES apiome.slate_releases(id) ON DELETE CASCADE,
    region_id   TEXT NOT NULL,
    label       TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('active', 'activating', 'failed')),
    reported_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (release_id, region_id)
);

COMMENT ON TABLE apiome.slate_release_regions IS
    'Per-region activation state for a release (APX-3.1). A lane with no region reports at all is partial, because absence of evidence is not evidence of a clean activation.';
COMMENT ON COLUMN apiome.slate_release_regions.release_id IS
    'Release being rolled out.';
COMMENT ON COLUMN apiome.slate_release_regions.region_id IS
    'Edge region identifier, unique per release.';
COMMENT ON COLUMN apiome.slate_release_regions.label IS
    'Human-facing region name.';
COMMENT ON COLUMN apiome.slate_release_regions.status IS
    'active (serving), activating (still switching) or failed (still serving the previous release).';
COMMENT ON COLUMN apiome.slate_release_regions.reported_at IS
    'When the region last reported. Staleness is what distinguishes a slow rollout from a silent one.';

CREATE INDEX IF NOT EXISTS idx_slate_release_regions_release
    ON apiome.slate_release_regions (release_id, status);

-- An approval records WHAT was approved, not merely that approval happened. An approval whose
-- digest no longer matches the release artifact is stale, and the promotion gate consults it:
-- approving a build and then promoting different bytes is a supply-chain failure.
CREATE TABLE IF NOT EXISTS apiome.slate_release_approvals (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    release_id  UUID NOT NULL REFERENCES apiome.slate_releases(id) ON DELETE CASCADE,
    actor_id    UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    actor_name  TEXT NOT NULL,
    actor_kind  TEXT NOT NULL CHECK (actor_kind IN ('user', 'automation')),
    approved_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    digest      TEXT NOT NULL CHECK (digest ~ '^sha256:[0-9a-f]{64}$')
);

COMMENT ON TABLE apiome.slate_release_approvals IS
    'Human approvals recorded against a release (APX-3.1). The digest records what was approved, so promoting different bytes is detectable as a stale approval.';
COMMENT ON COLUMN apiome.slate_release_approvals.release_id IS
    'Release that was approved.';
COMMENT ON COLUMN apiome.slate_release_approvals.actor_id IS
    'Approving user, when still present.';
COMMENT ON COLUMN apiome.slate_release_approvals.actor_name IS
    'Display name of the approver, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_release_approvals.actor_kind IS
    'Whether a person or a system approved.';
COMMENT ON COLUMN apiome.slate_release_approvals.approved_at IS
    'When the approval was given.';
COMMENT ON COLUMN apiome.slate_release_approvals.digest IS
    'Artifact content digest that was approved. Compared against the release artifact to detect staleness.';

CREATE INDEX IF NOT EXISTS idx_slate_release_approvals_release
    ON apiome.slate_release_approvals (release_id, approved_at DESC);

CREATE TABLE IF NOT EXISTS apiome.slate_release_checks (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    release_id  UUID NOT NULL REFERENCES apiome.slate_releases(id) ON DELETE CASCADE,
    check_key   TEXT NOT NULL,
    label       TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('pending', 'running', 'passed', 'warning', 'failed', 'skipped')),
    detail      TEXT,
    ordinal     INTEGER NOT NULL DEFAULT 0,
    UNIQUE (release_id, check_key)
);

COMMENT ON TABLE apiome.slate_release_checks IS
    'Build, content, contract, link, accessibility and policy checks for a release (APX-3.1).';
COMMENT ON COLUMN apiome.slate_release_checks.release_id IS
    'Release the check ran against.';
COMMENT ON COLUMN apiome.slate_release_checks.check_key IS
    'Stable check identifier, unique per release.';
COMMENT ON COLUMN apiome.slate_release_checks.label IS
    'Human-facing check name.';
COMMENT ON COLUMN apiome.slate_release_checks.status IS
    'Check outcome: pending, running, passed, warning, failed or skipped.';
COMMENT ON COLUMN apiome.slate_release_checks.detail IS
    'Operator-facing explanation, especially for warning and failed outcomes.';
COMMENT ON COLUMN apiome.slate_release_checks.ordinal IS
    'Display order within the release.';

CREATE INDEX IF NOT EXISTS idx_slate_release_checks_release
    ON apiome.slate_release_checks (release_id, ordinal);

CREATE TABLE IF NOT EXISTS apiome.slate_release_phases (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    release_id   UUID NOT NULL REFERENCES apiome.slate_releases(id) ON DELETE CASCADE,
    phase_key    TEXT NOT NULL,
    label        TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('pending', 'running', 'complete', 'failed', 'skipped')),
    started_at   TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    ordinal      INTEGER NOT NULL DEFAULT 0,
    UNIQUE (release_id, phase_key)
);

COMMENT ON TABLE apiome.slate_release_phases IS
    'Ordered build phases for a release (APX-3.1), matching the Release Center progress vocabulary.';
COMMENT ON COLUMN apiome.slate_release_phases.release_id IS
    'Release the phase belongs to.';
COMMENT ON COLUMN apiome.slate_release_phases.phase_key IS
    'Stable phase identifier, unique per release; log lines reference it.';
COMMENT ON COLUMN apiome.slate_release_phases.label IS
    'Human-facing phase name.';
COMMENT ON COLUMN apiome.slate_release_phases.status IS
    'Phase state: pending, running, complete, failed or skipped.';
COMMENT ON COLUMN apiome.slate_release_phases.started_at IS
    'When the phase began. NULL while pending.';
COMMENT ON COLUMN apiome.slate_release_phases.completed_at IS
    'When the phase finished. NULL while pending or running.';
COMMENT ON COLUMN apiome.slate_release_phases.ordinal IS
    'Display and execution order within the release.';

CREATE INDEX IF NOT EXISTS idx_slate_release_phases_release
    ON apiome.slate_release_phases (release_id, ordinal);

CREATE TABLE IF NOT EXISTS apiome.slate_release_logs (
    id         BIGSERIAL PRIMARY KEY,
    release_id UUID NOT NULL REFERENCES apiome.slate_releases(id) ON DELETE CASCADE,
    at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    phase_key  TEXT NOT NULL,
    level      TEXT NOT NULL CHECK (level IN ('info', 'warn', 'error')),
    message    TEXT NOT NULL
);

COMMENT ON TABLE apiome.slate_release_logs IS
    'Build log lines for a release (APX-3.1). BIGSERIAL rather than UUID because these are appended in volume and read in order.';
COMMENT ON COLUMN apiome.slate_release_logs.release_id IS
    'Release the line belongs to.';
COMMENT ON COLUMN apiome.slate_release_logs.at IS
    'When the line was emitted.';
COMMENT ON COLUMN apiome.slate_release_logs.phase_key IS
    'Phase the line belongs to, matching slate_release_phases.phase_key.';
COMMENT ON COLUMN apiome.slate_release_logs.level IS
    'Line severity: info, warn or error.';
COMMENT ON COLUMN apiome.slate_release_logs.message IS
    'The log message.';

CREATE INDEX IF NOT EXISTS idx_slate_release_logs_release
    ON apiome.slate_release_logs (release_id, id);

CREATE TABLE IF NOT EXISTS apiome.slate_release_changed_pages (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    release_id  UUID NOT NULL REFERENCES apiome.slate_releases(id) ON DELETE CASCADE,
    -- Catalog path record id when the page came from one, enabling deep links back into the
    -- authoring surface. NULL for pages with no catalog origin (guides, changelog, index).
    path_id     UUID,
    route       TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('added', 'changed', 'removed')),
    before_text TEXT NOT NULL DEFAULT '',
    after_text  TEXT NOT NULL DEFAULT '',
    UNIQUE (release_id, route)
);

COMMENT ON TABLE apiome.slate_release_changed_pages IS
    'Pages whose rendered output differs from the previous release (APX-3.1). Drives changed-page deep links and the diff tab.';
COMMENT ON COLUMN apiome.slate_release_changed_pages.release_id IS
    'Release the change belongs to.';
COMMENT ON COLUMN apiome.slate_release_changed_pages.path_id IS
    'Catalog path record id when the page came from one, for deep links. NULL for guides, changelog and index pages.';
COMMENT ON COLUMN apiome.slate_release_changed_pages.route IS
    'Route of the page, unique per release (e.g. /paths/invoices).';
COMMENT ON COLUMN apiome.slate_release_changed_pages.kind IS
    'Whether the page was added, changed or removed relative to the previous release.';
COMMENT ON COLUMN apiome.slate_release_changed_pages.before_text IS
    'Rendered text in the previous release. Empty when the page was added.';
COMMENT ON COLUMN apiome.slate_release_changed_pages.after_text IS
    'Rendered text in this release. Empty when the page was removed.';

CREATE INDEX IF NOT EXISTS idx_slate_release_changed_pages_release
    ON apiome.slate_release_changed_pages (release_id, route);
CREATE INDEX IF NOT EXISTS idx_slate_release_changed_pages_path
    ON apiome.slate_release_changed_pages (path_id)
    WHERE path_id IS NOT NULL;

-- ─── 6. Audit (append-only) ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_release_audit (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id  UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    release_id UUID NOT NULL REFERENCES apiome.slate_releases(id) ON DELETE CASCADE,
    at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id   UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    actor_name TEXT NOT NULL,
    actor_kind TEXT NOT NULL CHECK (actor_kind IN ('user', 'automation')),
    summary    TEXT NOT NULL,
    detail     TEXT
);

COMMENT ON TABLE apiome.slate_release_audit IS
    'Append-only audit of everything that happened to a release (APX-3.1). UPDATE and DELETE are refused by trigger, so history only ever grows.';
COMMENT ON COLUMN apiome.slate_release_audit.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_release_audit.release_id IS
    'Release the entry describes.';
COMMENT ON COLUMN apiome.slate_release_audit.at IS
    'When the event happened.';
COMMENT ON COLUMN apiome.slate_release_audit.actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_release_audit.actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_release_audit.actor_kind IS
    'Whether a person or a system acted.';
COMMENT ON COLUMN apiome.slate_release_audit.summary IS
    'What happened, e.g. "Promoted to production".';
COMMENT ON COLUMN apiome.slate_release_audit.detail IS
    'Extra context, e.g. the previous release id or the refusal reason.';

CREATE INDEX IF NOT EXISTS idx_slate_release_audit_release
    ON apiome.slate_release_audit (release_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_release_audit_tenant
    ON apiome.slate_release_audit (tenant_id, at DESC);

-- An audit log that can be edited is not an audit log. Both verbs are refused at the database,
-- so no application bug and no ad-hoc session can quietly rewrite what happened.
CREATE OR REPLACE FUNCTION apiome.slate_release_audit_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'slate_release_audit is append-only: % is not permitted', TG_OP
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.slate_release_audit_append_only() IS
    'Refuses UPDATE and DELETE on slate_release_audit (APX-3.1). Audit entries are appended to, never rewritten.';

DROP TRIGGER IF EXISTS trg_slate_release_audit_append_only ON apiome.slate_release_audit;
CREATE TRIGGER trg_slate_release_audit_append_only
    BEFORE UPDATE OR DELETE ON apiome.slate_release_audit
    FOR EACH ROW EXECUTE FUNCTION apiome.slate_release_audit_append_only();

-- ─── 7. Domains ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_domains (
    id                     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id              UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    site_id                UUID NOT NULL REFERENCES apiome.slate_sites(id) ON DELETE CASCADE,
    environment_id         UUID NOT NULL REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    host                   TEXT NOT NULL,
    -- Exactly one canonical host per lane; the rest redirect to it. Enforced by the partial
    -- unique index below rather than by application convention.
    is_primary             BOOLEAN NOT NULL DEFAULT FALSE,
    tls_status             TEXT NOT NULL DEFAULT 'provisioning'
                           CHECK (tls_status IN ('active', 'provisioning', 'error')),
    verification_status    TEXT NOT NULL DEFAULT 'pending'
                           CHECK (verification_status IN ('pending', 'verified', 'failed')),
    verification_token     TEXT,
    dns_target             TEXT,
    certificate_issuer     TEXT,
    certificate_expires_at TIMESTAMP WITH TIME ZONE,
    created_at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- A hostname resolves to one place globally, so this is not tenant-scoped: allowing two
    -- tenants to claim one host would be a routing ambiguity, not a convenience.
    UNIQUE (host)
);

COMMENT ON TABLE apiome.slate_domains IS
    'Hosted domain inventory per environment (APX-3.1): verification, DNS target, TLS issuer and expiry.';
COMMENT ON COLUMN apiome.slate_domains.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_domains.site_id IS
    'Site the domain serves.';
COMMENT ON COLUMN apiome.slate_domains.environment_id IS
    'Lane the domain routes to. Moving a domain between lanes is a routing change, not an edit.';
COMMENT ON COLUMN apiome.slate_domains.host IS
    'Hostname. Globally unique: a host resolves to one place, so two tenants cannot both claim it.';
COMMENT ON COLUMN apiome.slate_domains.is_primary IS
    'True for the canonical host of the lane; aliases redirect to it. At most one per lane.';
COMMENT ON COLUMN apiome.slate_domains.tls_status IS
    'Certificate state: active, provisioning or error.';
COMMENT ON COLUMN apiome.slate_domains.verification_status IS
    'Domain-ownership challenge state: pending, verified or failed.';
COMMENT ON COLUMN apiome.slate_domains.verification_token IS
    'Ownership challenge token the tenant must publish. NULL once verified.';
COMMENT ON COLUMN apiome.slate_domains.dns_target IS
    'Record the tenant must point at, shown in the domain inventory.';
COMMENT ON COLUMN apiome.slate_domains.certificate_issuer IS
    'Issuing certificate authority.';
COMMENT ON COLUMN apiome.slate_domains.certificate_expires_at IS
    'Certificate expiry, so renewal can be reported before it lapses.';
COMMENT ON COLUMN apiome.slate_domains.created_at IS
    'When the domain was attached.';

CREATE INDEX IF NOT EXISTS idx_slate_domains_environment
    ON apiome.slate_domains (environment_id);
CREATE INDEX IF NOT EXISTS idx_slate_domains_site
    ON apiome.slate_domains (site_id);
CREATE INDEX IF NOT EXISTS idx_slate_domains_tenant
    ON apiome.slate_domains (tenant_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_slate_domains_primary_per_environment
    ON apiome.slate_domains (environment_id)
    WHERE is_primary;

-- ─── 8. Activation ledger ────────────────────────────────────────────────────

-- Every attempt to change routing is recorded, including the ones that failed and the ones that
-- only partly landed. A ledger that records only successes cannot answer the question an
-- operator actually has during an incident, which is what was tried and what happened.
CREATE TABLE IF NOT EXISTS apiome.slate_activations (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id               UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id          UUID NOT NULL REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    from_release_id         UUID REFERENCES apiome.slate_releases(id) ON DELETE SET NULL,
    to_release_id           UUID NOT NULL REFERENCES apiome.slate_releases(id) ON DELETE CASCADE,
    kind                    TEXT NOT NULL CHECK (kind IN ('initial', 'promotion', 'rollback')),
    actor_id                UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    actor_name              TEXT NOT NULL,
    actor_kind              TEXT NOT NULL CHECK (actor_kind IN ('user', 'automation')),
    outcome                 TEXT NOT NULL DEFAULT 'pending'
                            CHECK (outcome IN ('pending', 'succeeded', 'partial', 'failed', 'conflict')),
    -- The concurrency token as read and as written. Recording both is what makes a lost
    -- promotion reconstructable after the fact rather than merely detectable at the time.
    routing_version_before  BIGINT NOT NULL,
    routing_version_after   BIGINT,
    -- The digest routed to. Recorded on the activation as well as the release so the ledger
    -- alone proves no rebuild occurred: a promotion whose digest matches its source release
    -- routed existing bytes.
    artifact_digest         TEXT NOT NULL CHECK (artifact_digest ~ '^sha256:[0-9a-f]{64}$'),
    failure_reason          TEXT,
    started_at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at            TIMESTAMP WITH TIME ZONE
);

COMMENT ON TABLE apiome.slate_activations IS
    'Ledger of every routing change attempt (APX-3.1), including conflicts, failures and partial rollouts. Records the concurrency token before and after.';
COMMENT ON COLUMN apiome.slate_activations.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_activations.environment_id IS
    'Lane whose routing was being changed.';
COMMENT ON COLUMN apiome.slate_activations.from_release_id IS
    'Release that was serving before the attempt. NULL for the first activation of a lane.';
COMMENT ON COLUMN apiome.slate_activations.to_release_id IS
    'Release the attempt routed to.';
COMMENT ON COLUMN apiome.slate_activations.kind IS
    'initial (lane had nothing), promotion (forward) or rollback (back to a retained artifact).';
COMMENT ON COLUMN apiome.slate_activations.actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_activations.actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_activations.actor_kind IS
    'Whether a person or a system acted.';
COMMENT ON COLUMN apiome.slate_activations.outcome IS
    'pending, succeeded, partial (a region did not switch), failed, or conflict (another activation won the routing_version race).';
COMMENT ON COLUMN apiome.slate_activations.routing_version_before IS
    'Lane routing_version the attempt read and asserted.';
COMMENT ON COLUMN apiome.slate_activations.routing_version_after IS
    'Lane routing_version after a successful switch. NULL when the attempt did not change routing.';
COMMENT ON COLUMN apiome.slate_activations.artifact_digest IS
    'Content digest routed to. Proves promotion routed existing bytes rather than producing new ones.';
COMMENT ON COLUMN apiome.slate_activations.failure_reason IS
    'Operator-facing reason for a conflict, failure or partial rollout.';
COMMENT ON COLUMN apiome.slate_activations.started_at IS
    'When the attempt began. With completed_at, measures the activation against the site SLO.';
COMMENT ON COLUMN apiome.slate_activations.completed_at IS
    'When the attempt reached a terminal outcome. NULL while pending.';

CREATE INDEX IF NOT EXISTS idx_slate_activations_environment
    ON apiome.slate_activations (environment_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_activations_tenant
    ON apiome.slate_activations (tenant_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_activations_release
    ON apiome.slate_activations (to_release_id);
