-- Unattributed clients for suggested consumers — CDG-3.5 (#5970).
--
-- RDG-1.8 (V292) attributes a call to a consumer through a binding, and counts a call no binding
-- matches under the reserved `anonymous` consumer. That keeps every share honest, but it cannot say
-- *who* the anonymous callers are, so the dependency graph cannot suggest them as consumers. This
-- migration keeps the smallest identity that can: per project and UTC day, how many unattributed
-- calls came from each **client key**.
--
--   usage_unattributed_client_daily   unattributed calls per (project, day, client kind, client key)
--   purge_usage_unattributed()         prunes it past the tier's rollup retention
--
-- A client key is one of two things, never a raw value:
--
--   * `user_agent` — the product token of the call's *scrubbed* user agent, lower-cased
--     (`checkout-web` from `checkout-web/4.2 (linux)`), letters, digits, `.`, `_` and `-` only, at most
--     64 characters (CHECK). The ingest pipeline drops a token that looks like a credential or a
--     random string before it gets here.
--   * `header`, `api_key`, `jwt_claim` — the 64-hex HMAC the edge already put in the event's
--     `consumer_hint` (V292 rule 2) when it matched no binding. The value never reaches Apiome.
--
-- The dependency graph lists these as **Suggested consumers** (`app.consumer_suggestions`).
-- Registering one creates a CTG-4.1 consumer and the matching V292 binding, so its next calls are
-- attributed; its rows here are left to age out. The table follows every rule of the usage index
-- (V290): tenant-scoped, counters only, every text column bounded and pattern-checked, rows pruned
-- with the tier's `usage_rollup_retention_days` by the usage sweep.
--
-- Rollback notes:
--   DROP FUNCTION IF EXISTS apiome.purge_usage_unattributed(TIMESTAMPTZ, INTEGER);
--   DROP TABLE IF EXISTS apiome.usage_unattributed_client_daily;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS usage_unattributed_client_daily (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    day DATE NOT NULL,

    client_kind VARCHAR(16) NOT NULL
        CONSTRAINT usage_unattributed_client_kind_ck CHECK (
            client_kind IN ('user_agent', 'header', 'api_key', 'jwt_claim')
        ),
    client_key VARCHAR(64) NOT NULL
        CONSTRAINT usage_unattributed_client_key_ck CHECK (
            (client_kind = 'user_agent' AND client_key ~ '^[a-z0-9][a-z0-9._-]*$')
            OR (client_kind <> 'user_agent' AND client_key ~ '^[0-9a-f]{64}$')
        ),

    calls BIGINT NOT NULL CONSTRAINT usage_unattributed_client_calls_ck CHECK (calls >= 0),
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT usage_unattributed_client_daily_pk PRIMARY KEY (tenant_id, project_id, day, client_kind, client_key)
);

CREATE INDEX IF NOT EXISTS idx_usage_unattributed_client_project_day
    ON usage_unattributed_client_daily (tenant_id, project_id, day DESC);
CREATE INDEX IF NOT EXISTS idx_usage_unattributed_client_day ON usage_unattributed_client_daily (day);

COMMENT ON TABLE usage_unattributed_client_daily IS
    'CDG-3.5 (#5970): unattributed usage calls per project, UTC day and client key — a scrubbed '
    'user-agent product token or an unmatched consumer_hint HMAC, never a raw value. The source of the '
    'dependency graph''s Suggested consumers.';
COMMENT ON COLUMN usage_unattributed_client_daily.client_key IS
    'user_agent: the lower-cased product token of the scrubbed user agent. header / api_key / '
    'jwt_claim: the consumer_hint HMAC (64 hex). Never a header, key or claim value.';

-- Prune past the tier's rollup retention, at most p_batch rows per call (the rest go next time).
CREATE OR REPLACE FUNCTION purge_usage_unattributed(
    p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    p_batch INTEGER DEFAULT 10000
)
RETURNS INTEGER AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    DELETE FROM apiome.usage_unattributed_client_daily
    WHERE ctid IN (
        SELECT u.ctid
        FROM apiome.usage_retention(p_now) r
        JOIN apiome.usage_unattributed_client_daily u
          ON u.tenant_id = r.tenant_id AND u.day < r.rollup_cutoff
        LIMIT GREATEST(p_batch, 1)
    );
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION purge_usage_unattributed(TIMESTAMPTZ, INTEGER) IS
    'Prune usage_unattributed_client_daily past each tenant''s usage_rollup_retention_days (at most '
    'p_batch rows per call); returns the rows deleted. CDG-3.5 (#5970).';
