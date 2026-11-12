-- CDN / edge provider configuration and purge dispatch — Slate 10.2 (private-suite#120).
--
-- Problem: V187 (UXE-3.1) built the cache control plane against a delivery tier that did not
-- exist. `slate_cache_policies.edge_attached` was FALSE for every row the system could write, and
-- `slate_cache_purges_dispatch_needs_edge` made "dispatched" unreachable, so every purge was a
-- record of intent and nothing was ever evicted. A tenant serving a Slate site through their own
-- CDN had no way to tell the platform about it, so a new release went live at the origin while the
-- CDN kept serving the old pages until their TTLs ran out.
--
-- Solution: one provider per lane, and a log of every call made to it.
--
--   1. `apiome.slate_cdn_providers` — which CDN fronts the lane (Cloudflare, Fastly or a custom
--      purge endpoint), its public coordinates (zone id / service id / purge URL) and the
--      credential that authorizes a purge. The credential is envelope-encrypted by the REST
--      service (`app.slate_cdn_crypto`, magic `OSCV`) before it reaches this table; the column
--      holds ciphertext and the key version that sealed it, and there is no plaintext column to
--      put it in by mistake.
--
--   2. `apiome.slate_cdn_purge_dispatches` — append-only: every purge sent to a provider, whether
--      a deploy triggered it or an operator did, with what the provider answered. A failed call
--      names a short error code ("cdn-auth-rejected") so a tenant can act on it.
--
-- Attaching a provider sets `slate_cache_policies.edge_attached` and `edge_provider` (V187
-- reserved both for this), which is what lets a purge record reach `outcome = 'dispatched'`. V187's
-- CHECK is unchanged: it still refuses a dispatched purge on a lane with no provider attached.
-- Historical purge rows keep the `edge_attached` snapshot they were written with, so attaching a
-- CDN today does not make yesterday's records look like flushes.
--
-- `slate_cache_audit.subject_kind` gains `cdn`, so attaching, changing and detaching a provider
-- are in the same timeline as the purges they enable.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.slate_cdn_purge_dispatches;
--   DROP TABLE IF EXISTS apiome.slate_cdn_providers;
--   UPDATE apiome.slate_cache_policies SET edge_attached = FALSE, edge_provider = NULL;
--   DELETE FROM apiome.slate_cache_audit WHERE subject_kind = 'cdn';
--   ALTER TABLE apiome.slate_cache_audit DROP CONSTRAINT IF EXISTS slate_cache_audit_subject_kind_check;
--   ALTER TABLE apiome.slate_cache_audit ADD CONSTRAINT slate_cache_audit_subject_kind_check
--       CHECK (subject_kind IN ('preset', 'rule', 'purge', 'trace'));

SET search_path TO apiome, public;

-- ─── 1. Provider configuration (one per environment) ─────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_cdn_providers (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id               UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    site_id                 UUID NOT NULL REFERENCES apiome.slate_sites(id) ON DELETE CASCADE,
    -- A CDN fronts a lane, not a site: staging is usually served without one.
    environment_id          UUID NOT NULL UNIQUE
                            REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    provider                TEXT NOT NULL
                            CHECK (provider IN ('cloudflare', 'fastly', 'custom')),
    -- The provider's public coordinate: a Cloudflare zone id, a Fastly service id, or the custom
    -- purge URL. Not a secret, so it is stored and returned in the clear.
    target                  TEXT NOT NULL,
    -- The header a custom endpoint expects its credential in. Cloudflare and Fastly fix their own.
    auth_header_name        TEXT,
    credential_ciphertext   BYTEA NOT NULL,
    credential_key_version  INTEGER NOT NULL,
    purge_on_deploy         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by_actor_id     UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    updated_by_actor_name   TEXT NOT NULL,
    -- Cloudflare zone ids are 32 lowercase hex characters.
    CONSTRAINT slate_cdn_providers_cloudflare_target
        CHECK (provider <> 'cloudflare' OR target ~ '^[0-9a-f]{32}$'),
    -- Fastly service ids are short alphanumeric tokens.
    CONSTRAINT slate_cdn_providers_fastly_target
        CHECK (provider <> 'fastly' OR target ~ '^[A-Za-z0-9]{1,64}$'),
    -- A custom purge endpoint receives a credential, so it must be reached over TLS.
    CONSTRAINT slate_cdn_providers_custom_target
        CHECK (provider <> 'custom' OR (target LIKE 'https://%' AND length(target) <= 2048)),
    -- Exactly the custom provider names a header, and it is a legal header token.
    CONSTRAINT slate_cdn_providers_header_only_custom
        CHECK ((provider = 'custom') = (auth_header_name IS NOT NULL)),
    CONSTRAINT slate_cdn_providers_header_token
        CHECK (auth_header_name IS NULL OR auth_header_name ~ '^[A-Za-z0-9-]{1,64}$')
);

COMMENT ON TABLE apiome.slate_cdn_providers IS
    'CDN in front of one Slate environment (Slate 10.2, private-suite#120): provider, public coordinate, sealed purge credential and whether a deploy purges it.';
COMMENT ON COLUMN apiome.slate_cdn_providers.tenant_id IS
    'Owning tenant. Denormalized like every slate_* table so reads stay tenant-scoped.';
COMMENT ON COLUMN apiome.slate_cdn_providers.site_id IS
    'Site the environment belongs to.';
COMMENT ON COLUMN apiome.slate_cdn_providers.environment_id IS
    'Environment the CDN fronts. UNIQUE: a lane has at most one CDN provider.';
COMMENT ON COLUMN apiome.slate_cdn_providers.provider IS
    'cloudflare, fastly or custom (a purge URL the tenant operates).';
COMMENT ON COLUMN apiome.slate_cdn_providers.target IS
    'Public coordinate: Cloudflare zone id, Fastly service id or the custom https purge URL. Not a secret.';
COMMENT ON COLUMN apiome.slate_cdn_providers.auth_header_name IS
    'Header the custom endpoint reads its credential from. NULL for Cloudflare and Fastly, which fix their own.';
COMMENT ON COLUMN apiome.slate_cdn_providers.credential_ciphertext IS
    'Envelope-encrypted purge credential (app.slate_cdn_crypto, magic OSCV). Never stored or returned in plaintext.';
COMMENT ON COLUMN apiome.slate_cdn_providers.credential_key_version IS
    'Master-key version that sealed credential_ciphertext, so keys can rotate.';
COMMENT ON COLUMN apiome.slate_cdn_providers.purge_on_deploy IS
    'Whether promoting or rolling back a release on this lane purges the CDN.';
COMMENT ON COLUMN apiome.slate_cdn_providers.created_at IS
    'When the provider was first attached.';
COMMENT ON COLUMN apiome.slate_cdn_providers.updated_at IS
    'When the configuration last changed.';
COMMENT ON COLUMN apiome.slate_cdn_providers.updated_by_actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_cdn_providers.updated_by_actor_name IS
    'Display name of the actor, stored so history survives user deletion.';

CREATE INDEX IF NOT EXISTS idx_slate_cdn_providers_tenant
    ON apiome.slate_cdn_providers (tenant_id);

-- ─── 2. Dispatch log ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_cdn_purge_dispatches (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id        UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id   UUID NOT NULL
                     REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    -- The release a deploy purge was sent for. NULL for a manual purge with no basis release.
    release_id       UUID REFERENCES apiome.slate_releases(id) ON DELETE SET NULL,
    -- The cache-plane purge record a manual dispatch belongs to.
    cache_purge_id   UUID REFERENCES apiome.slate_cache_purges(id) ON DELETE SET NULL,
    trigger          TEXT NOT NULL CHECK (trigger IN ('deploy', 'manual')),
    provider         TEXT NOT NULL CHECK (provider IN ('cloudflare', 'fastly', 'custom')),
    -- urls: the listed URLs were purged. purge-all: the scope exceeded what the provider accepts
    -- per purge, or no changed-page record existed, so the whole cache was purged instead.
    mode             TEXT NOT NULL CHECK (mode IN ('urls', 'purge-all')),
    url_count        INTEGER NOT NULL DEFAULT 0 CHECK (url_count >= 0),
    sample_urls      TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    status           TEXT NOT NULL CHECK (status IN ('succeeded', 'failed', 'skipped')),
    http_status      INTEGER,
    error_code       TEXT,
    error_message    TEXT,
    actor_id         UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    actor_name       TEXT NOT NULL,
    dispatched_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- A failure or a skip says why; a success does not carry a stale error.
    CONSTRAINT slate_cdn_purge_dispatches_error_matches_status
        CHECK ((status = 'succeeded') = (error_code IS NULL))
);

COMMENT ON TABLE apiome.slate_cdn_purge_dispatches IS
    'Every purge sent to a lane''s CDN provider (Slate 10.2): trigger, mode, size, and what the provider answered. Append-only.';
COMMENT ON COLUMN apiome.slate_cdn_purge_dispatches.tenant_id IS
    'Owning tenant.';
COMMENT ON COLUMN apiome.slate_cdn_purge_dispatches.environment_id IS
    'Environment whose CDN was purged.';
COMMENT ON COLUMN apiome.slate_cdn_purge_dispatches.release_id IS
    'Release a deploy purge was sent for, or the basis release of a manual purge.';
COMMENT ON COLUMN apiome.slate_cdn_purge_dispatches.cache_purge_id IS
    'The slate_cache_purges record a manual dispatch belongs to. NULL for a deploy purge.';
COMMENT ON COLUMN apiome.slate_cdn_purge_dispatches.trigger IS
    'deploy (a promotion or rollback) or manual (a purge requested on the Cache surface).';
COMMENT ON COLUMN apiome.slate_cdn_purge_dispatches.provider IS
    'Provider the purge was sent to, snapshotted so detaching a provider keeps history readable.';
COMMENT ON COLUMN apiome.slate_cdn_purge_dispatches.mode IS
    'urls (each listed URL was purged) or purge-all (the whole CDN cache for the zone/service).';
COMMENT ON COLUMN apiome.slate_cdn_purge_dispatches.url_count IS
    'How many URLs were in scope. For purge-all, the scope that was too large to list.';
COMMENT ON COLUMN apiome.slate_cdn_purge_dispatches.sample_urls IS
    'Bounded sample of the purged URLs.';
COMMENT ON COLUMN apiome.slate_cdn_purge_dispatches.status IS
    'succeeded, failed (the provider refused or could not be reached) or skipped (nothing to send).';
COMMENT ON COLUMN apiome.slate_cdn_purge_dispatches.http_status IS
    'HTTP status of the provider''s last answer, when one was received.';
COMMENT ON COLUMN apiome.slate_cdn_purge_dispatches.error_code IS
    'Short reason for a failure or skip, e.g. cdn-auth-rejected or cdn-no-hosts. NULL on success.';
COMMENT ON COLUMN apiome.slate_cdn_purge_dispatches.error_message IS
    'What went wrong, in words. Never contains the credential.';
COMMENT ON COLUMN apiome.slate_cdn_purge_dispatches.actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_cdn_purge_dispatches.actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_cdn_purge_dispatches.dispatched_at IS
    'When the purge was sent.';

CREATE INDEX IF NOT EXISTS idx_slate_cdn_purge_dispatches_environment
    ON apiome.slate_cdn_purge_dispatches (environment_id, dispatched_at DESC);
CREATE INDEX IF NOT EXISTS idx_slate_cdn_purge_dispatches_tenant
    ON apiome.slate_cdn_purge_dispatches (tenant_id);

-- ─── 3. Cache audit and policy wording ───────────────────────────────────────

ALTER TABLE apiome.slate_cache_audit
    DROP CONSTRAINT IF EXISTS slate_cache_audit_subject_kind_check;
ALTER TABLE apiome.slate_cache_audit
    ADD CONSTRAINT slate_cache_audit_subject_kind_check
    CHECK (subject_kind IN ('preset', 'rule', 'purge', 'trace', 'cdn'));

COMMENT ON COLUMN apiome.slate_cache_audit.subject_kind IS
    'What the entry is about: preset, rule, purge, trace or cdn (provider attached, changed or detached).';
COMMENT ON COLUMN apiome.slate_cache_policies.edge_attached IS
    'Whether a CDN provider (apiome.slate_cdn_providers) fronts this lane, so a purge is dispatched to it. Set by attaching a provider, cleared by detaching it.';
COMMENT ON COLUMN apiome.slate_cache_policies.edge_provider IS
    'Name of the attached CDN provider (cloudflare, fastly or custom), or NULL when none.';
