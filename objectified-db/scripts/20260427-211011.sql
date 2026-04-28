-- REPO-12.5 (#2954): in-app notifications for repository auto/manual import outcomes.
-- One row per (tenant, import job, recipient); used for idempotent emission and read tracking.

SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS odb.repository_import_notification (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL,
  import_job_id text NOT NULL,
  recipient_user_id uuid NOT NULL,
  repository_id uuid NOT NULL,
  title text NOT NULL,
  body text NOT NULL,
  primary_link text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  read_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_repository_import_notification_event UNIQUE (tenant_id, import_job_id, recipient_user_id)
);

CREATE INDEX IF NOT EXISTS idx_repository_import_notification_recipient_unread
  ON odb.repository_import_notification (tenant_id, recipient_user_id, read_at, created_at DESC);

COMMENT ON TABLE odb.repository_import_notification IS
  'REPO-12.5: one deduplicated in-app notification per import job per recipient; dismiss on dashboard marks read.';
