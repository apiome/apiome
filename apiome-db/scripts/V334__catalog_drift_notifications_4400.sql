-- Catalog drift notifications: drift events and the tenant's alert settings (MFI-31.3, #4400).
--
-- When a live refresh (MFI-31.1/31.2) adds a version to a catalog item, the change between the
-- item's previous version and the new one is classified with the breaking-change engine (MFI-3.3):
-- safe, dangerous or breaking. Each such version is one drift event:
--
--   1. `catalog_drift_events` — one row per refresh-created version that has a previous version to
--      compare with. It carries the worst severity, the per-severity counts and the classified
--      changes (capped by the app), feeds the catalog card's drift badge and the item's banner
--      until someone dismisses it, and records how it was announced: `none` (the tenant's
--      settings keep this severity quiet), `sent` (webhook + inbox right away), `pending_digest`
--      (waiting for the daily digest) or `digested` (sent in a digest).
--   2. `catalog_drift_settings` — one row per tenant that changed the defaults: which severities
--      notify, immediate or daily-digest delivery, whether breaking changes skip the digest, and
--      an email opt-in that is stored for a later email channel. No row means the defaults
--      (breaking and dangerous notify, safe badges only, immediate).
--
-- Rollback:
--   DROP TABLE IF EXISTS apiome.catalog_drift_events;
--   DROP TABLE IF EXISTS apiome.catalog_drift_settings;
SET search_path TO apiome, public;

-- ─── 1. Drift events ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.catalog_drift_events (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id            UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    project_id           UUID NOT NULL REFERENCES apiome.projects(id) ON DELETE CASCADE,
    -- The refresh-created version and the version it superseded (the diff baseline).
    version_id           UUID NOT NULL REFERENCES apiome.versions(id) ON DELETE CASCADE,
    parent_version_id    UUID REFERENCES apiome.versions(id) ON DELETE SET NULL,
    version_label        TEXT NOT NULL,
    parent_version_label TEXT,
    -- What ran the check that created the version.
    trigger              VARCHAR(8) NOT NULL CHECK (trigger IN ('sweep', 'manual')),
    severity             VARCHAR(16) NOT NULL CHECK (severity IN ('safe', 'dangerous', 'breaking')),
    -- {"safe": n, "dangerous": n, "breaking": n} over every classified change.
    counts               JSONB NOT NULL DEFAULT '{}'::jsonb,
    change_count         INTEGER NOT NULL DEFAULT 0 CHECK (change_count >= 0),
    -- The classified changes, worst first, capped by the app (change_count is the full count).
    changes              JSONB NOT NULL DEFAULT '[]'::jsonb,
    notification         VARCHAR(16) NOT NULL DEFAULT 'none'
                         CHECK (notification IN ('none', 'sent', 'pending_digest', 'digested')),
    notified_at          TIMESTAMPTZ,
    dismissed_at         TIMESTAMPTZ,
    dismissed_by         UUID,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_catalog_drift_events_version UNIQUE (version_id)
);

-- The badge and the banner read the newest undismissed event per item.
CREATE INDEX IF NOT EXISTS idx_catalog_drift_events_item
    ON apiome.catalog_drift_events (project_id, created_at DESC);

-- The digest reads each tenant's waiting events.
CREATE INDEX IF NOT EXISTS idx_catalog_drift_events_pending_digest
    ON apiome.catalog_drift_events (tenant_id, created_at)
    WHERE notification = 'pending_digest';

COMMENT ON TABLE apiome.catalog_drift_events IS
    'Classified drift of a refresh-created catalog version (MFI-31.3): severity, counts, changes, and how it was announced. Shown as a badge and banner until dismissed.';

-- ─── 2. Tenant alert settings ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.catalog_drift_settings (
    tenant_id            UUID PRIMARY KEY REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    notify_breaking      BOOLEAN NOT NULL DEFAULT TRUE,
    notify_dangerous     BOOLEAN NOT NULL DEFAULT TRUE,
    notify_safe          BOOLEAN NOT NULL DEFAULT FALSE,
    delivery             VARCHAR(16) NOT NULL DEFAULT 'immediate'
                         CHECK (delivery IN ('immediate', 'daily_digest')),
    -- In daily-digest mode, still send breaking changes right away.
    breaking_immediate   BOOLEAN NOT NULL DEFAULT TRUE,
    -- Stored opt-in for an email channel; no email is sent yet.
    email_enabled        BOOLEAN NOT NULL DEFAULT FALSE,
    last_digest_at       TIMESTAMPTZ,
    updated_by           UUID,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE apiome.catalog_drift_settings IS
    'Per-tenant catalog drift alert settings (MFI-31.3). No row means the defaults: breaking and dangerous notify, safe changes badge quietly, immediate delivery.';
