-- The `pact:read` / `pact:publish` / `pact:verify` API key scopes — PFX-4.2 (#6939).
--
-- Pact tooling (the `pact-broker` CLI, the Pact libraries' verifiers, `apiome pact`) reaches the
-- Pact Broker surface at `/v1/tenants/{tenant}/pact-broker` with an ordinary **workspace** API
-- key — sent as a bearer token, as basic auth (`<any-name>:<api-key>`) or as `X-API-Key`. No
-- second key system. Three new scopes keep such a key away from everything else:
--
--   pact:read     every GET of the broker and the hosted verifier, plus the read-only POSTs
--                 (`for-verification`, the provider-state check) — what `can-i-deploy` needs —
--                 and the reads of the pacticipant registry (`/v1/tenants/{tenant}/pacticipants`).
--   pact:publish  the consumer and deploy pipeline's writes: publish pacts and provider contracts,
--                 tag a version or record it on a branch, record a deployment or release.
--   pact:verify   the provider pipeline's writes: publish verification results, run the hosted
--                 verifier, register provider states, tag / branch the provider version. Paired
--                 with pact:read it is a CI verifier's key that cannot publish a pact.
--
-- Deletes, webhooks, environments and cleanup stay full-access (`*`) only.
--
-- The runtime allowlist lives in apiome-rest (`app.auth`); this migration only widens the stored
-- vocabulary. Every earlier scope is kept, `*` must still stand alone (`api_keys_scopes_star_alone_ck`,
-- unchanged) and agent keys stay pinned to `agent:invoke` (V269 rule, restated as V295 did).
--
-- Rollback notes:
--   UPDATE apiome.api_keys
--     SET scopes = array_remove(array_remove(array_remove(scopes, 'pact:read'), 'pact:publish'), 'pact:verify')
--     WHERE scopes && ARRAY['pact:read', 'pact:publish', 'pact:verify']::text[];   -- revoke keys left empty first
--   ALTER TABLE apiome.api_keys DROP CONSTRAINT IF EXISTS api_keys_scopes_vocab_ck;
--   ALTER TABLE apiome.api_keys ADD CONSTRAINT api_keys_scopes_vocab_ck
--     CHECK (scopes <@ ARRAY['*', 'diff:read', 'lint:read', 'agent:invoke', 'usage:ingest',
--                            'registry:read', 'registry:write']::text[]);

SET search_path TO apiome, public;

ALTER TABLE api_keys
  DROP CONSTRAINT IF EXISTS api_keys_scopes_vocab_ck;
ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_scopes_vocab_ck
  CHECK (
    scopes <@ ARRAY[
      '*', 'diff:read', 'lint:read', 'agent:invoke', 'usage:ingest', 'registry:read', 'registry:write',
      'pact:read', 'pact:publish', 'pact:verify'
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
  'Machine-key capability scopes (#4473, CTG-2.3; AGX-3.1 #4537; RDG-1.2 #5760; CDG-4.3 #5975; '
  'PFX-4.2 #6939). ''*'' = full access (default). CI tokens use diff:read and/or lint:read only — '
  'no write access. A usage source uses usage:ingest, which admits POST '
  '/v1/tenants/{tenant}/usage/ingest only. registry:read / registry:write admit the '
  'Confluent-compatible schema registry at /registry/schema/{tenant} only. pact:read / '
  'pact:publish / pact:verify admit the Pact Broker at /v1/tenants/{tenant}/pact-broker and the '
  'hosted verifier at /v1/tenants/{tenant}/pact-verifier (and pact:read the pacticipant registry '
  'reads) only. Agent keys carry exactly '
  'agent:invoke, which no REST route accepts. Enforced in apiome-rest auth allowlist.';
