-- CI tokens & scoped keys — CTG-2.3 (#4473).
--
-- Problem: workspace api_keys are all-or-nothing. A key leaked from a CI log
-- would carry full write access, so teams refuse to put keys in shared pipelines.
--
-- Solution: additive ``scopes TEXT[]`` on apiome.api_keys:
--   * '*'          — full access (default; existing keys keep current behaviour)
--   * 'diff:read'  — POST /v1/diff/{tenant}/classified only
--   * 'lint:read'  — GET …/lint and GET …/lint/gate (catalog + MCP twins)
--
-- CHECK: non-empty; each element in the vocab above; '*' must stand alone.
-- Existing rows pick up ARRAY['*'] via the column default (no row rewrite).
--
-- Rollback notes: purely additive. To roll back:
--   ALTER TABLE apiome.api_keys
--     DROP CONSTRAINT IF EXISTS api_keys_scopes_vocab_ck,
--     DROP CONSTRAINT IF EXISTS api_keys_scopes_star_alone_ck,
--     DROP CONSTRAINT IF EXISTS api_keys_scopes_nonempty_ck;
--   ALTER TABLE apiome.api_keys DROP COLUMN IF EXISTS scopes;

SET search_path TO apiome, public;

ALTER TABLE api_keys
  ADD COLUMN IF NOT EXISTS scopes TEXT[] NOT NULL DEFAULT ARRAY['*']::text[];

ALTER TABLE api_keys
  DROP CONSTRAINT IF EXISTS api_keys_scopes_nonempty_ck;
ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_scopes_nonempty_ck
  CHECK (cardinality(scopes) >= 1);

ALTER TABLE api_keys
  DROP CONSTRAINT IF EXISTS api_keys_scopes_vocab_ck;
ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_scopes_vocab_ck
  CHECK (
    scopes <@ ARRAY['*', 'diff:read', 'lint:read']::text[]
  );

ALTER TABLE api_keys
  DROP CONSTRAINT IF EXISTS api_keys_scopes_star_alone_ck;
ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_scopes_star_alone_ck
  CHECK (
    NOT ('*' = ANY (scopes)) OR cardinality(scopes) = 1
  );

COMMENT ON COLUMN api_keys.scopes IS
  'Machine-key capability scopes (#4473, CTG-2.3). ''*'' = full access (default). '
  'CI tokens use diff:read and/or lint:read only — no write access. '
  'Enforced in apiome-rest auth allowlist.';
