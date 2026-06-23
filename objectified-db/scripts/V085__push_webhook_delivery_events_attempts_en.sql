-- Push webhook delivery events, attempts, encrypted signing secret (#2588 / P2-06)
SET search_path TO odb, public;

DO $$
BEGIN
  CREATE TYPE odb.push_webhook_delivery_status AS ENUM (
    'pending',
    'retrying',
    'processing',
    'delivered',
    'dead_letter'
  );
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

ALTER TABLE odb.push_webhook_subscriptions
  ADD COLUMN IF NOT EXISTS signing_secret_encrypted BYTEA;

COMMENT ON COLUMN odb.push_webhook_subscriptions.signing_secret_encrypted IS
  'Fernet-encrypted signing secret for outbound HMAC; set when OBJECTIFIED_WEBHOOK_SIGNING_SECRET_ENCRYPTION_KEY is configured (#2588)';

CREATE TABLE IF NOT EXISTS odb.push_webhook_delivery_events (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES odb.tenants(id) ON DELETE CASCADE,
  subscription_id UUID NOT NULL REFERENCES odb.push_webhook_subscriptions(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL,
  status odb.push_webhook_delivery_status NOT NULL DEFAULT 'pending',
  attempt_count INT NOT NULL DEFAULT 0 CHECK (attempt_count >= 0 AND attempt_count <= 4),
  next_retry_at TIMESTAMPTZ,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_push_webhook_delivery_events_tenant_status
  ON odb.push_webhook_delivery_events (tenant_id, status);

CREATE INDEX IF NOT EXISTS idx_push_webhook_delivery_events_due
  ON odb.push_webhook_delivery_events (next_retry_at)
  WHERE status IN ('pending', 'retrying');

COMMENT ON TABLE odb.push_webhook_delivery_events IS
  'Outbound push webhook deliveries with retry and terminal dead-letter state (#2588)';

CREATE TABLE IF NOT EXISTS odb.push_webhook_delivery_attempts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  delivery_event_id UUID NOT NULL REFERENCES odb.push_webhook_delivery_events(id) ON DELETE CASCADE,
  attempt_number INT NOT NULL CHECK (attempt_number >= 1),
  http_status INT,
  response_body_preview TEXT,
  error_message TEXT,
  latency_ms INT,
  attempted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (delivery_event_id, attempt_number)
);

CREATE INDEX IF NOT EXISTS idx_push_webhook_delivery_attempts_event
  ON odb.push_webhook_delivery_attempts (delivery_event_id, attempt_number);

COMMENT ON TABLE odb.push_webhook_delivery_attempts IS
  'HTTP attempt history per push webhook delivery event (#2588)';
