-- The `usage:ingest` API key scope — RDG-1.2 (#5760).
--
-- The usage ingest door (`POST /v1/tenants/{tenant}/usage/ingest`, apiome-rest `app.usage_ingest`)
-- is authenticated with an ordinary **workspace** API key that carries a new scope, `usage:ingest`.
-- There is no new key kind and no new identity: a traffic source (an OpenTelemetry Collector, a log
-- shipper, the CLI) holds a workspace key that can post usage batches and call nothing else.
-- (The roadmap reserved no number for this; V291 is the next free one after V290.)
--
-- Two rules:
--
--   1. **Widen the vocabulary.** `api_keys_scopes_vocab_ck` (V177, widened by V269) gains
--      `usage:ingest`. `*` must still stand alone (`api_keys_scopes_star_alone_ck`, unchanged).
--   2. **Agent keys stay agent keys.** `api_keys_kind_scopes_ck` (V269) already pins an agent key to
--      exactly `ARRAY['agent:invoke']`, so an agent key can never hold `usage:ingest`; it is restated
--      here unchanged so the two constraints read together. apiome-rest also only accepts workspace
--      keys as REST credentials, so the ingest route is unreachable with a `kind = 'agent'` key.
--
-- Rollback notes:
--   UPDATE apiome.api_keys SET scopes = array_remove(scopes, 'usage:ingest')
--     WHERE 'usage:ingest' = ANY (scopes);   -- a key left with no scope must be revoked first
--   ALTER TABLE apiome.api_keys DROP CONSTRAINT IF EXISTS api_keys_scopes_vocab_ck;
--   ALTER TABLE apiome.api_keys ADD CONSTRAINT api_keys_scopes_vocab_ck
--     CHECK (scopes <@ ARRAY['*', 'diff:read', 'lint:read', 'agent:invoke']::text[]);

SET search_path TO apiome, public;

-- Rule 1.
ALTER TABLE api_keys
  DROP CONSTRAINT IF EXISTS api_keys_scopes_vocab_ck;
ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_scopes_vocab_ck
  CHECK (
    scopes <@ ARRAY['*', 'diff:read', 'lint:read', 'agent:invoke', 'usage:ingest']::text[]
  );

-- Rule 2 (unchanged from V269).
ALTER TABLE api_keys
  DROP CONSTRAINT IF EXISTS api_keys_kind_scopes_ck;
ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_kind_scopes_ck
  CHECK (
    (kind = 'agent' AND scopes = ARRAY['agent:invoke']::text[])
    OR (kind = 'workspace' AND NOT ('agent:invoke' = ANY (scopes)))
  );

COMMENT ON COLUMN api_keys.scopes IS
  'Machine-key capability scopes (#4473, CTG-2.3; AGX-3.1 #4537; RDG-1.2 #5760). ''*'' = full '
  'access (default). CI tokens use diff:read and/or lint:read only — no write access. A usage '
  'source uses usage:ingest, which admits POST /v1/tenants/{tenant}/usage/ingest only. Agent keys '
  'carry exactly agent:invoke, which no REST route accepts. Enforced in apiome-rest auth allowlist.';
