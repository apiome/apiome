-- Push webhook subscriptions for git-like / downstream integrations (#2587 / P2-05)
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS push_webhook_subscriptions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
  url TEXT NOT NULL,
  url_normalized TEXT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT true,
  signing_secret_ref UUID NOT NULL UNIQUE DEFAULT uuid_generate_v4(),
  signing_secret_hash VARCHAR(255) NOT NULL,
  deleted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_push_webhook_subscriptions_tenant_url_norm_active
  ON apiome.push_webhook_subscriptions (tenant_id, url_normalized)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_push_webhook_subscriptions_tenant_id
  ON apiome.push_webhook_subscriptions (tenant_id)
  WHERE deleted_at IS NULL;

COMMENT ON TABLE apiome.push_webhook_subscriptions IS
  'Tenant-configured HTTPS endpoints for push notifications; signing secret stored hashed (#2587)';

COMMENT ON COLUMN apiome.push_webhook_subscriptions.url_normalized IS
  'Normalized URL for duplicate detection within a tenant';

COMMENT ON COLUMN apiome.push_webhook_subscriptions.signing_secret_ref IS
  'Stable reference id for the signing secret (never the secret itself)';

COMMENT ON COLUMN apiome.push_webhook_subscriptions.signing_secret_hash IS
  'Bcrypt hash of SHA-256 digest of the signing secret; never exposed via API';
