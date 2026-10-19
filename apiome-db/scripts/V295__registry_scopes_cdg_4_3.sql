-- The `registry:read` / `registry:write` API key scopes — CDG-4.3 (#5975).
--
-- Kafka serializers (confluent-kafka, kafka-avro-serializer, Spring) reach the Confluent-compatible
-- schema registry at `/registry/schema/{tenant}` with an ordinary **workspace** API key — sent as
-- basic auth (`<any-name>:<api-key>`) or a bearer token. No second key system. Two new scopes keep
-- such a key away from everything else:
--
--   registry:read   GET routes of the registry, plus the two read-only POSTs (subject lookup and
--                   compatibility test) — what a consumer / deserializer needs.
--   registry:write  the writes: register a version, change config or mode, delete a subject — what a
--                   producer with auto-registration needs (alongside registry:read).
--
-- The runtime allowlist lives in apiome-rest (`app.auth`); this migration only widens the stored
-- vocabulary. Every earlier scope is kept, `*` must still stand alone (`api_keys_scopes_star_alone_ck`,
-- unchanged) and agent keys stay pinned to `agent:invoke` (V269 rule, restated as V291 did).
--
-- Rollback notes:
--   UPDATE apiome.api_keys SET scopes = array_remove(array_remove(scopes, 'registry:read'), 'registry:write')
--     WHERE scopes && ARRAY['registry:read', 'registry:write']::text[];   -- revoke keys left empty first
--   ALTER TABLE apiome.api_keys DROP CONSTRAINT IF EXISTS api_keys_scopes_vocab_ck;
--   ALTER TABLE apiome.api_keys ADD CONSTRAINT api_keys_scopes_vocab_ck
--     CHECK (scopes <@ ARRAY['*', 'diff:read', 'lint:read', 'agent:invoke', 'usage:ingest']::text[]);

SET search_path TO apiome, public;

ALTER TABLE api_keys
  DROP CONSTRAINT IF EXISTS api_keys_scopes_vocab_ck;
ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_scopes_vocab_ck
  CHECK (
    scopes <@ ARRAY[
      '*', 'diff:read', 'lint:read', 'agent:invoke', 'usage:ingest', 'registry:read', 'registry:write'
    ]::text[]
  );

ALTER TABLE api_keys
  DROP CONSTRAINT IF EXISTS api_keys_kind_scopes_ck;
ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_kind_scopes_ck
  CHECK (
    (kind = 'agent' AND scopes = ARRAY['agent:invoke']::text[])
    OR (kind = 'workspace' AND NOT ('agent:invoke' = ANY (scopes)))
  );

COMMENT ON COLUMN api_keys.scopes IS
  'Machine-key capability scopes (#4473, CTG-2.3; AGX-3.1 #4537; RDG-1.2 #5760; CDG-4.3 #5975). '
  '''*'' = full access (default). CI tokens use diff:read and/or lint:read only — no write access. '
  'A usage source uses usage:ingest, which admits POST /v1/tenants/{tenant}/usage/ingest only. '
  'registry:read / registry:write admit the Confluent-compatible schema registry at '
  '/registry/schema/{tenant} only. Agent keys carry exactly agent:invoke, which no REST route '
  'accepts. Enforced in apiome-rest auth allowlist.';
