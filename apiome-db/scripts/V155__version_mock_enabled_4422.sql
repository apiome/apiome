-- Per-version mock toggle for the hosted mock runtime (#4422, SIM-2.1).
--
-- mock_enabled gates whether apiome-mock serves a published version. mock_settings is reserved
-- for v2 knobs (scenario overrides, latency/chaos) and is unused by MVP logic.

SET search_path TO apiome, public;

ALTER TABLE versions
    ADD COLUMN IF NOT EXISTS mock_enabled BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS mock_settings JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN versions.mock_enabled IS
  'When true on a published version, apiome-mock serves spec-accurate responses at /{tenant}/{project}/{version} (#4422, SIM-2.1)';
COMMENT ON COLUMN versions.mock_settings IS
  'Reserved JSONB for future mock knobs (scenario overrides SIM-4.2, latency/chaos SIM-4.3); unused by MVP';
