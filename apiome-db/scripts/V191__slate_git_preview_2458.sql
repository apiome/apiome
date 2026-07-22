-- Git-triggered immutable preview builds and provider status (APX-3.3, private-suite#2458).
--
-- A reviewer looking at a branch needs a URL that shows exactly that change, that keeps
-- pointing at that change forever, and that a status check can link to from the pull request.
-- V186 already models the hard half of this: content-addressed immutable artifacts, immutable
-- releases carrying the source commit, ephemeral preview lanes with expiry and access policy,
-- changed-page records and an append-only audit. What V186 does not have is the *git ingress*
-- — nothing receives a signed provider event, turns a commit into a preview exactly once,
-- derives an immutable commit URL plus a moving branch alias, or records a status write-back.
-- This migration adds that ingress as the preview control plane, the way V187 added the cache
-- control plane on top of the same routing tables.
--
-- The shape here is not invented. `ROADMAP_AUTHORING_PLATFORM.md` §29.1 names the model:
-- "immutable commit URL plus moving branch alias; expiry/retention and robots exclusion;
-- preview protection through tenant auth, password or SSO policy; changed-page deep links",
-- and issue #2458's acceptance criteria name the four guarantees these tables enforce:
--
--   1. `apiome.slate_git_connections`  — one git provider connection per site: the repository,
--                                        the webhook secret (Fernet, encrypt-at-rest), and the
--                                        repository token (envelope-encrypted, never returned).
--   2. `apiome.slate_preview_builds`    — the immutable preview record. `UNIQUE (connection_id,
--                                        source_digest)` is acceptance criterion 1: a signed
--                                        event creates exactly ONE preview per source digest,
--                                        so a redelivered webhook is a no-op, not a duplicate.
--   3. `apiome.slate_preview_changed_pages` — the changed pages a preview touches, with a deep
--                                        link into the immutable URL (acceptance criterion 3).
--   4. `apiome.slate_branch_aliases`    — the *moving* branch alias. It advances only through
--                                        the checks path, so "the alias advances only after
--                                        successful checks" (criterion 2) is a code fact.
--   5. `apiome.slate_provider_status_deliveries` — the status write-back records: state,
--                                        changed-page count, and the honesty boundary below.
--   6. `apiome.slate_preview_audit`     — append-only; retry and cleanup are audited
--                                        (criterion 4). UPDATE and DELETE are refused.
--
-- One preview per source digest (criterion 1). `source_digest` is a sha256 over the canonical
-- (repository, commit) pair — the same identity-by-content instinct as
-- `slate_artifacts.content_digest`. `UNIQUE (connection_id, source_digest)` makes a second
-- ingestion of the same commit collide rather than fan out, so a provider that redelivers a
-- webhook (GitHub does, freely) cannot manufacture a second preview. `delivery_id` records the
-- provider's delivery identifier for the audit trail; it does not have to be unique because the
-- digest already carries idempotency.
--
-- The commit URL is immutable (criterion 2). `slate_preview_immutability_guard` refuses any
-- update to `source_commit`, `source_digest`, `immutable_url` or `connection_id`, exactly as
-- `slate_release_immutability_guard` does for releases. A preview URL that could be repointed
-- would let a green check describe bytes that are no longer there — the same supply-chain lie
-- the release immutability trigger exists to stop.
--
-- Repository tokens never reach the browser (criterion 4). `token_ciphertext` is the envelope
-- ciphertext produced by `mcp_credential_crypto.seal_credential_payload`; the plaintext is
-- sealed before it is written and unsealed only in server memory. `webhook_secret_enc` is the
-- Fernet ciphertext produced by `push_webhook_crypto.encrypt_signing_secret`. Neither column is
-- ever selected into an API model — the REST layer projects the connection without them.
--
-- Scope boundary, stated plainly (the V186/V187 discipline). There is still no Slate build
-- worker (7.3, #3419) and no first-party provider check-run write-back (that adapter is owned by
-- `ROADMAP_GIT_NATIVE_COLLABORATION.md`; §23.3 scopes Authoring to "preview builds and
-- documentation-specific status only"). So a preview is created, its immutable and alias URLs
-- are derived, its changed pages are recorded and its expiry/access are set — all real — but the
-- build is NOT executed and the status is NOT POSTed to the provider. `build_dispatched` is
-- FALSE for every row this system can write, enforced by `CHECK (NOT build_dispatched)`, and a
-- status delivery can never claim `outcome = 'dispatched'` unless `dispatch_enabled` is true,
-- which no code path sets — the same `edge_attached` constraint V187 uses for a purge that
-- flushes nothing. A control plane that overstates its reach is worse than one that admits its
-- edge, so the boundary is a database fact, not a comment.

SET search_path TO apiome, public;

-- ─── 1. Git provider connection (one per site) ───────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_git_connections (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    site_id             UUID NOT NULL REFERENCES apiome.slate_sites(id) ON DELETE CASCADE,
    provider            TEXT NOT NULL CHECK (provider IN ('github')),
    repo_owner          TEXT NOT NULL,
    repo_name           TEXT NOT NULL,
    -- Lowercased "owner/name" — the key the webhook receiver resolves the payload's repository
    -- against. Stored rather than derived so the resolution lookup is a single indexed column.
    repo_full_name      TEXT NOT NULL,
    default_branch      TEXT NOT NULL DEFAULT 'main',
    -- Base host the immutable and alias URLs are built from (e.g. previews.apiome.app).
    preview_host        TEXT NOT NULL,
    -- Fernet ciphertext of the webhook signing secret (push_webhook_crypto). NULL when the
    -- server has no encryption key configured — in which case signature verification fails
    -- closed rather than accepting an unverifiable event.
    webhook_secret_enc  BYTEA,
    -- Envelope ciphertext of the repository token (mcp_credential_crypto). NULL when no token
    -- was supplied or encryption is unconfigured. Never selected into an API response.
    token_ciphertext    BYTEA,
    token_key_version   INTEGER,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, provider, repo_full_name)
);

COMMENT ON TABLE apiome.slate_git_connections IS
    'One git provider connection per Slate site (APX-3.3, private-suite#2458). Holds the repository, the Fernet-encrypted webhook secret and the envelope-encrypted repository token. The secret and token columns are never projected into an API response.';
COMMENT ON COLUMN apiome.slate_git_connections.tenant_id IS 'Owning tenant.';
COMMENT ON COLUMN apiome.slate_git_connections.site_id IS 'Site the connection builds previews for.';
COMMENT ON COLUMN apiome.slate_git_connections.provider IS 'Git provider. GitHub only today; the column leaves room for later adapters.';
COMMENT ON COLUMN apiome.slate_git_connections.repo_full_name IS 'Lowercased owner/name, the key the webhook receiver resolves a payload against.';
COMMENT ON COLUMN apiome.slate_git_connections.preview_host IS 'Base host the immutable commit URL and moving branch alias URL are derived from.';
COMMENT ON COLUMN apiome.slate_git_connections.webhook_secret_enc IS 'Fernet ciphertext of the webhook signing secret. NULL disables verification (fails closed).';
COMMENT ON COLUMN apiome.slate_git_connections.token_ciphertext IS 'Envelope ciphertext of the repository token. Sealed before write, unsealed only in server memory, never returned to a client.';
COMMENT ON COLUMN apiome.slate_git_connections.token_key_version IS 'Master-key version that sealed token_ciphertext, for rotation.';

CREATE INDEX IF NOT EXISTS idx_slate_git_connections_tenant
    ON apiome.slate_git_connections (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_git_connections_site
    ON apiome.slate_git_connections (site_id);
-- The webhook receiver has only the payload's repository, not a tenant, so it resolves the
-- connection by provider + repo_full_name and then verifies the signature with its secret.
CREATE INDEX IF NOT EXISTS idx_slate_git_connections_repo
    ON apiome.slate_git_connections (provider, repo_full_name);

-- ─── 2. Preview builds (immutable, one per source digest) ────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_preview_builds (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id         UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    connection_id     UUID NOT NULL REFERENCES apiome.slate_git_connections(id) ON DELETE CASCADE,
    site_id           UUID NOT NULL REFERENCES apiome.slate_sites(id) ON DELETE CASCADE,
    -- The ephemeral preview lane this build serves. Reuses slate_environments for expiry,
    -- access policy and robots exclusion. NULL only if the lane was reaped independently.
    environment_id    UUID REFERENCES apiome.slate_environments(id) ON DELETE SET NULL,
    -- The provider's delivery identifier (X-GitHub-Delivery), kept for the audit trail. Not
    -- unique: source_digest already carries idempotency.
    delivery_id       TEXT,
    source_commit     TEXT NOT NULL,
    source_ref        TEXT NOT NULL,
    source_message    TEXT NOT NULL DEFAULT '',
    source_digest     TEXT NOT NULL CHECK (source_digest ~ '^sha256:[0-9a-f]{64}$'),
    status            TEXT NOT NULL DEFAULT 'queued'
                      CHECK (status IN ('queued', 'building', 'ready', 'failed', 'expired')),
    checks_state      TEXT NOT NULL DEFAULT 'pending'
                      CHECK (checks_state IN ('pending', 'passed', 'failed')),
    -- The immutable commit URL. Set once, never repointed (see the immutability guard).
    immutable_url     TEXT NOT NULL,
    -- Preview protection. Defaults to tenant-only: an unlisted commit URL is not a security
    -- control, so a preview is not public unless deliberately made so.
    access_policy     TEXT NOT NULL DEFAULT 'tenant'
                      CHECK (access_policy IN ('public', 'tenant', 'password', 'sso')),
    robots_excluded   BOOLEAN NOT NULL DEFAULT TRUE,
    -- Failure evidence surfaced in the provider status when a build or check fails.
    failure_evidence  JSONB,
    -- The honesty boundary in SQL: no build worker exists (#3419), so no preview this system
    -- writes has had its build dispatched. FALSE for every row, enforced.
    build_dispatched  BOOLEAN NOT NULL DEFAULT FALSE CHECK (NOT build_dispatched),
    retry_count       INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    expires_at        TIMESTAMP WITH TIME ZONE,
    cleaned_up_at     TIMESTAMP WITH TIME ZONE,
    created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (connection_id, source_digest)
);

COMMENT ON TABLE apiome.slate_preview_builds IS
    'Immutable git-triggered preview record (APX-3.3, private-suite#2458). UNIQUE (connection_id, source_digest) makes one signed event create exactly one preview; the immutability guard forbids repointing the commit URL. build_dispatched is FALSE for every row (no build worker, #3419).';
COMMENT ON COLUMN apiome.slate_preview_builds.source_digest IS 'sha256 over the canonical (repository, commit) pair. The idempotency key: a redelivered event collides here.';
COMMENT ON COLUMN apiome.slate_preview_builds.immutable_url IS 'The immutable commit URL. Set once at creation, never repointed.';
COMMENT ON COLUMN apiome.slate_preview_builds.checks_state IS 'pending until a check outcome is recorded; the branch alias advances only when this is passed.';
COMMENT ON COLUMN apiome.slate_preview_builds.access_policy IS 'Preview protection: public, tenant members, a shared password, or SSO. Defaults to tenant.';
COMMENT ON COLUMN apiome.slate_preview_builds.build_dispatched IS 'Always FALSE: there is no Slate build worker (#3419), so no preview has been built. Enforced by CHECK.';
COMMENT ON COLUMN apiome.slate_preview_builds.retry_count IS 'Number of times a build retry was requested. Audited on every increment.';

CREATE INDEX IF NOT EXISTS idx_slate_preview_builds_connection
    ON apiome.slate_preview_builds (connection_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_preview_builds_tenant
    ON apiome.slate_preview_builds (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_preview_builds_site
    ON apiome.slate_preview_builds (site_id, created_at DESC);
-- Expiry sweeps for the cleanup path.
CREATE INDEX IF NOT EXISTS idx_slate_preview_builds_expiring
    ON apiome.slate_preview_builds (expires_at)
    WHERE expires_at IS NOT NULL AND cleaned_up_at IS NULL;

-- Immutability. A preview that could be repointed to a different commit or URL would let an
-- approved status describe bytes that are no longer there. Mirrors slate_release_immutability.
CREATE OR REPLACE FUNCTION apiome.slate_preview_immutability_guard()
RETURNS trigger AS $$
DECLARE
    v_changed TEXT[] := ARRAY[]::TEXT[];
BEGIN
    IF NEW.id            IS DISTINCT FROM OLD.id            THEN v_changed := array_append(v_changed, 'id');            END IF;
    IF NEW.tenant_id     IS DISTINCT FROM OLD.tenant_id     THEN v_changed := array_append(v_changed, 'tenant_id');     END IF;
    IF NEW.connection_id IS DISTINCT FROM OLD.connection_id THEN v_changed := array_append(v_changed, 'connection_id'); END IF;
    IF NEW.source_commit IS DISTINCT FROM OLD.source_commit THEN v_changed := array_append(v_changed, 'source_commit'); END IF;
    IF NEW.source_digest IS DISTINCT FROM OLD.source_digest THEN v_changed := array_append(v_changed, 'source_digest'); END IF;
    IF NEW.immutable_url IS DISTINCT FROM OLD.immutable_url THEN v_changed := array_append(v_changed, 'immutable_url'); END IF;
    IF NEW.created_at    IS DISTINCT FROM OLD.created_at    THEN v_changed := array_append(v_changed, 'created_at');    END IF;

    IF array_length(v_changed, 1) > 0 THEN
        RAISE EXCEPTION
            'slate_preview_builds is immutable: % cannot change after the preview is created',
            array_to_string(v_changed, ', ')
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.slate_preview_immutability_guard() IS
    'Rejects updates to preview identity columns (APX-3.3): the commit, its digest and the immutable URL cannot change after creation.';

DROP TRIGGER IF EXISTS trg_slate_preview_immutability ON apiome.slate_preview_builds;
CREATE TRIGGER trg_slate_preview_immutability
    BEFORE UPDATE ON apiome.slate_preview_builds
    FOR EACH ROW EXECUTE FUNCTION apiome.slate_preview_immutability_guard();

-- ─── 3. Changed pages (deep links into the immutable preview) ─────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_preview_changed_pages (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    preview_build_id  UUID NOT NULL REFERENCES apiome.slate_preview_builds(id) ON DELETE CASCADE,
    -- Catalog path record id when the route came from one, for deep links back into authoring.
    path_id           UUID,
    route             TEXT NOT NULL,
    kind              TEXT NOT NULL CHECK (kind IN ('added', 'changed', 'removed')),
    -- The absolute deep link: the immutable preview URL plus the route.
    link_url          TEXT NOT NULL,
    -- The repository file path the route was derived from, for traceability.
    source_path       TEXT,
    UNIQUE (preview_build_id, route)
);

COMMENT ON TABLE apiome.slate_preview_changed_pages IS
    'Pages a git-triggered preview touches (APX-3.3). Derived from the pushed file changes; each carries a deep link into the immutable preview URL (acceptance criterion 3).';
COMMENT ON COLUMN apiome.slate_preview_changed_pages.link_url IS 'Absolute deep link: the immutable preview URL joined with the route.';
COMMENT ON COLUMN apiome.slate_preview_changed_pages.source_path IS 'Repository file path the route was derived from.';

CREATE INDEX IF NOT EXISTS idx_slate_preview_changed_pages_build
    ON apiome.slate_preview_changed_pages (preview_build_id, route);

-- ─── 4. Branch aliases (the moving pointer) ──────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_branch_aliases (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id         UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    connection_id     UUID NOT NULL REFERENCES apiome.slate_git_connections(id) ON DELETE CASCADE,
    branch            TEXT NOT NULL,
    -- The preview the alias currently points at. NULL until a build on this branch passes its
    -- checks. Advances only through the checks path, never on ingestion.
    current_build_id  UUID REFERENCES apiome.slate_preview_builds(id) ON DELETE SET NULL,
    alias_url         TEXT NOT NULL,
    -- Optimistic-concurrency token, bumped on every advance, mirroring slate_environments.
    routing_version   BIGINT NOT NULL DEFAULT 0,
    created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (connection_id, branch)
);

COMMENT ON TABLE apiome.slate_branch_aliases IS
    'The moving branch alias for a git-triggered preview (APX-3.3). current_build_id advances only when a build passes its checks (acceptance criterion 2); routing_version guards concurrent advances.';
COMMENT ON COLUMN apiome.slate_branch_aliases.current_build_id IS 'Preview the alias points at. NULL until a build on this branch has passed its checks.';
COMMENT ON COLUMN apiome.slate_branch_aliases.routing_version IS 'Optimistic-concurrency token bumped on every advance.';

CREATE INDEX IF NOT EXISTS idx_slate_branch_aliases_connection
    ON apiome.slate_branch_aliases (connection_id, branch);
CREATE INDEX IF NOT EXISTS idx_slate_branch_aliases_tenant
    ON apiome.slate_branch_aliases (tenant_id);

-- ─── 5. Provider status deliveries (records, does not dispatch) ────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_provider_status_deliveries (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id          UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    preview_build_id   UUID NOT NULL REFERENCES apiome.slate_preview_builds(id) ON DELETE CASCADE,
    state              TEXT NOT NULL CHECK (state IN ('pending', 'success', 'failure')),
    context            TEXT NOT NULL DEFAULT 'apiome/preview',
    description        TEXT NOT NULL DEFAULT '',
    -- The link the status points a reviewer at: the immutable preview URL.
    target_url         TEXT NOT NULL DEFAULT '',
    changed_page_count INTEGER NOT NULL DEFAULT 0 CHECK (changed_page_count >= 0),
    attempts           INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    -- No first-party provider check-run adapter exists (owned by GIT_NATIVE_COLLABORATION), so
    -- no status this system writes was POSTed. dispatch_enabled is FALSE for every row and the
    -- CHECK forbids claiming a dispatch that did not happen — the V187 edge_attached discipline.
    dispatch_enabled   BOOLEAN NOT NULL DEFAULT FALSE,
    outcome            TEXT NOT NULL DEFAULT 'recorded'
                       CHECK (outcome IN ('recorded', 'dispatched', 'failed')),
    created_at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (outcome <> 'dispatched' OR dispatch_enabled)
);

COMMENT ON TABLE apiome.slate_provider_status_deliveries IS
    'Provider status write-back records (APX-3.3). Records state, target link and changed-page count; does NOT POST to the provider — dispatch_enabled is FALSE for every row and the CHECK forbids an undispatched row claiming outcome=dispatched (mirrors V187 slate_cache_purges.edge_attached).';
COMMENT ON COLUMN apiome.slate_provider_status_deliveries.target_url IS 'The immutable preview URL a status would link a reviewer at.';
COMMENT ON COLUMN apiome.slate_provider_status_deliveries.dispatch_enabled IS 'Always FALSE: no provider check-run adapter is attached. The CHECK makes an undispatched status unable to claim it was dispatched.';

CREATE INDEX IF NOT EXISTS idx_slate_provider_status_build
    ON apiome.slate_provider_status_deliveries (preview_build_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_provider_status_tenant
    ON apiome.slate_provider_status_deliveries (tenant_id, created_at DESC);

-- Status deliveries are evidence; they are appended to, never rewritten.
CREATE OR REPLACE FUNCTION apiome.slate_provider_status_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'slate_provider_status_deliveries is append-only: % is not permitted', TG_OP
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.slate_provider_status_append_only() IS
    'Refuses UPDATE and DELETE on slate_provider_status_deliveries (APX-3.3).';

DROP TRIGGER IF EXISTS trg_slate_provider_status_append_only ON apiome.slate_provider_status_deliveries;
CREATE TRIGGER trg_slate_provider_status_append_only
    BEFORE UPDATE OR DELETE ON apiome.slate_provider_status_deliveries
    FOR EACH ROW EXECUTE FUNCTION apiome.slate_provider_status_append_only();

-- ─── 6. Preview audit (append-only) ───────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_preview_audit (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id         UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    preview_build_id  UUID NOT NULL REFERENCES apiome.slate_preview_builds(id) ON DELETE CASCADE,
    at                TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_name        TEXT NOT NULL,
    actor_kind        TEXT NOT NULL CHECK (actor_kind IN ('user', 'automation')),
    summary           TEXT NOT NULL,
    detail            TEXT
);

COMMENT ON TABLE apiome.slate_preview_audit IS
    'Append-only audit of a preview: creation, idempotent redelivery, check outcomes, retries and cleanup (APX-3.3, acceptance criterion 4). UPDATE and DELETE are refused by trigger.';

CREATE INDEX IF NOT EXISTS idx_slate_preview_audit_build
    ON apiome.slate_preview_audit (preview_build_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_preview_audit_tenant
    ON apiome.slate_preview_audit (tenant_id, at DESC);

CREATE OR REPLACE FUNCTION apiome.slate_preview_audit_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'slate_preview_audit is append-only: % is not permitted', TG_OP
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.slate_preview_audit_append_only() IS
    'Refuses UPDATE and DELETE on slate_preview_audit (APX-3.3). Retry and cleanup history only ever grows.';

DROP TRIGGER IF EXISTS trg_slate_preview_audit_append_only ON apiome.slate_preview_audit;
CREATE TRIGGER trg_slate_preview_audit_append_only
    BEFORE UPDATE OR DELETE ON apiome.slate_preview_audit
    FOR EACH ROW EXECUTE FUNCTION apiome.slate_preview_audit_append_only();
