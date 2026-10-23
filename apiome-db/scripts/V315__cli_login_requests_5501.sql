-- `apiome login` — browser-approved CLI sign-in (#5501).
--
-- `apiome login` signs the CLI in without anyone copying an API key out of the app:
--
--   1. The CLI asks apiome-rest to start a login. It gets a secret **device code** (kept by the CLI)
--      and a short **user code** (shown in the terminal and in the browser).
--   2. The person opens /cli/login in apiome-ui, signs in the usual way (any provider, password,
--      two-factor), checks the user code matches, picks a workspace and approves.
--   3. The CLI, polling with its device code, then receives a new API key — minted at that moment,
--      returned once, never stored in clear — and saves it in its config file.
--
-- The key is an ordinary workspace key (so every command that takes an API key accepts it), marked
-- `cli_login`, created by the approving user, and expiring after 14 days. Approval requires the
-- same `api_keys:create` permission as creating a key in the app. `apiome logout` revokes it.
--
-- This migration:
--
--   * adds `apiome.cli_login_requests`, one row per login attempt:
--       - only the SHA-256 of the device code is stored, so a database read cannot be replayed;
--       - `user_code` is unique among live (pending / approved) requests;
--       - `status` moves pending → approved | denied, then approved → consumed when the CLI
--         collects its key. Every row expires (`expires_at`, ten minutes after it starts); apiome-rest
--         deletes rows a day past expiry whenever a new login starts;
--   * adds `api_keys.cli_login`, true for keys minted this way. A CLI login key is always a
--     workspace key with an expiry.
--
-- Rollback notes (revoke CLI login keys first in shared environments):
--   ALTER TABLE apiome.api_keys DROP CONSTRAINT IF EXISTS api_keys_cli_login_ck;
--   ALTER TABLE apiome.api_keys DROP COLUMN IF EXISTS cli_login;
--   DROP TABLE IF EXISTS apiome.cli_login_requests;

SET search_path TO apiome, public;

ALTER TABLE apiome.api_keys
  ADD COLUMN IF NOT EXISTS cli_login BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE apiome.api_keys DROP CONSTRAINT IF EXISTS api_keys_cli_login_ck;
ALTER TABLE apiome.api_keys
  ADD CONSTRAINT api_keys_cli_login_ck
  CHECK (NOT cli_login OR (kind = 'workspace' AND expires_at IS NOT NULL));

COMMENT ON COLUMN apiome.api_keys.cli_login IS
  'True for a short-lived key minted by `apiome login` (#5501). Always a workspace key with an expiry.';

CREATE TABLE IF NOT EXISTS apiome.cli_login_requests (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  -- Lowercase hex SHA-256 of the device code the CLI polls with; the code itself is never stored.
  device_code_hash CHAR(64) NOT NULL,
  -- What the person compares in the terminal and the browser, e.g. `KTXR-9MWD`.
  user_code VARCHAR(9) NOT NULL,
  -- Free text the CLI sends to name itself (e.g. `apiome-cli on laptop`); shown on the approve page.
  client_name VARCHAR(255),
  status VARCHAR(16) NOT NULL DEFAULT 'pending',
  -- Who approved or denied it, and (approved only) for which workspace.
  user_id UUID REFERENCES apiome.users(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES apiome.tenants(id) ON DELETE CASCADE,
  -- The key handed to the CLI (consumed only).
  api_key_id UUID REFERENCES apiome.api_keys(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMPTZ NOT NULL,
  decided_at TIMESTAMPTZ,
  consumed_at TIMESTAMPTZ,
  last_polled_at TIMESTAMPTZ,
  CONSTRAINT cli_login_requests_hash_format_ck CHECK (device_code_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT cli_login_requests_user_code_ck CHECK (user_code ~ '^[A-Z0-9]{4}-[A-Z0-9]{4}$'),
  CONSTRAINT cli_login_requests_status_ck
    CHECK (status IN ('pending', 'approved', 'denied', 'consumed')),
  CONSTRAINT cli_login_requests_expiry_ck CHECK (expires_at > created_at),
  CONSTRAINT cli_login_requests_decision_ck CHECK (
    (status = 'pending' AND user_id IS NULL AND tenant_id IS NULL AND decided_at IS NULL)
    OR (status = 'denied' AND user_id IS NOT NULL AND tenant_id IS NULL AND decided_at IS NOT NULL)
    OR (status IN ('approved', 'consumed') AND user_id IS NOT NULL AND tenant_id IS NOT NULL
        AND decided_at IS NOT NULL)
  ),
  CONSTRAINT cli_login_requests_consumed_ck CHECK ((status = 'consumed') = (consumed_at IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS cli_login_requests_device_code_uq
  ON apiome.cli_login_requests (device_code_hash);

CREATE UNIQUE INDEX IF NOT EXISTS cli_login_requests_live_user_code_uq
  ON apiome.cli_login_requests (user_code)
  WHERE status IN ('pending', 'approved');

CREATE INDEX IF NOT EXISTS cli_login_requests_expires_idx
  ON apiome.cli_login_requests (expires_at);

COMMENT ON TABLE apiome.cli_login_requests IS
  'Browser-approved `apiome login` attempts (#5501). Device code stored as SHA-256 only; ten-minute expiry.';
COMMENT ON COLUMN apiome.cli_login_requests.status IS
  'pending → approved | denied; approved → consumed when the CLI collects its key.';
