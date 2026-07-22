-- Sign-in / sign-up / link audit events (#4191, OLO-1.6)
--
-- Append-only, hash-chained ledger of authentication outcomes: every sign-in, sign-up, provider
-- link and unlink attempt — success or failure — recorded with the provider, the resolved user
-- (when one exists), the stable auth error code on failure, and privacy-preserving hashes of the
-- client IP and User-Agent. Mirrors the access_audit (V120) pattern: writes are best-effort from
-- apiome-rest (a failed audit insert must never fail or block the sign-in it records), and each row
-- carries the entry_hash of the previous row in the chain plus its own entry_hash, so a tampered or
-- deleted row is detectable.
--
-- Unlike access_audit this ledger is deliberately NOT tenant-scoped: authentication happens before
-- any tenant context is chosen, so the hash chain is global (one chain for the whole table). The
-- user_id is nullable — failed sign-ins and pre-account sign-up attempts legitimately have no
-- resolved user — and the canonical email is retained in user_label independent of the users row so
-- the history survives account deletion.
--
-- Consumers: the Profile login-history surface (#1607 login/logout events, #534 / #2418 login
-- history) reads recent rows per user via apiome-rest's list_auth_events_for_user().
--
-- Privacy & retention: raw IP / User-Agent are never stored — only salted SHA-256 hashes — so the
-- ledger carries no directly-identifying network PII. Rows older than the documented retention
-- window are pruned from the tail by apiome-rest's prune_auth_events(); the retained suffix stays
-- contiguous and independently hash-verifiable. See apiome-rest/docs/AUTH_EVENTS.md.
--
-- Event types (event_type): sign_in, sign_up, link, unlink.
-- Outcomes  (outcome):      success, failure.
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS auth_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type VARCHAR(32) NOT NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    user_label VARCHAR(255),
    provider VARCHAR(32),
    outcome VARCHAR(16) NOT NULL,
    error_code VARCHAR(64),
    ip_hash VARCHAR(64),
    user_agent_hash VARCHAR(64),
    detail JSONB,
    prev_hash VARCHAR(64),
    entry_hash VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT auth_events_outcome_check CHECK (outcome IN ('success', 'failure'))
);

-- Login-history-per-user read path (consumers above) and retention pruning by age.
CREATE INDEX IF NOT EXISTS idx_auth_events_user_created_at
    ON auth_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_events_created_at
    ON auth_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_events_event_type
    ON auth_events(event_type);

COMMENT ON TABLE auth_events IS 'Append-only, hash-chained sign-in/sign-up/link authentication audit ledger (#4191, OLO-1.6)';
COMMENT ON COLUMN auth_events.event_type IS 'Authentication event: sign_in, sign_up, link, unlink';
COMMENT ON COLUMN auth_events.user_id IS 'Resolved user; null for failed sign-ins and pre-account sign-up attempts';
COMMENT ON COLUMN auth_events.user_label IS 'Canonical email retained independent of the users row so history survives account deletion';
COMMENT ON COLUMN auth_events.provider IS 'OAuth provider slug (github, gitlab, azure) or credentials; null when unknown';
COMMENT ON COLUMN auth_events.outcome IS 'success or failure';
COMMENT ON COLUMN auth_events.error_code IS 'Stable auth error code on failure (see apiome-rest account_resolution.AUTH_ERROR_CODES)';
COMMENT ON COLUMN auth_events.ip_hash IS 'Salted SHA-256 of the client IP — never the raw address';
COMMENT ON COLUMN auth_events.user_agent_hash IS 'Salted SHA-256 of the client User-Agent — never the raw header';
COMMENT ON COLUMN auth_events.detail IS 'Structured context (e.g. auto_linked flag, link intent, request metadata)';
COMMENT ON COLUMN auth_events.prev_hash IS 'entry_hash of the previous row in the global chain (hash-chaining for tamper-evidence)';
COMMENT ON COLUMN auth_events.entry_hash IS 'SHA-256 over (prev_hash, event_type, outcome, provider, user, error_code, ip/ua hashes, detail)';
