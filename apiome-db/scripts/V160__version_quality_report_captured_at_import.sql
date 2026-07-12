-- Persist the full quality / lint report per schema revision, captured at import time (MFI-4.2).
--
-- V124 stored only score, grade, and fingerprint on apiome.versions. The lint API recomputed
-- OpenAPI findings on read, which diverged from the canonical-model score captured for native
-- catalog imports (Cap'n Proto, gRPC, etc.) and surfaced "No findings" in the UI. This JSONB
-- column stores the complete report (findings, rule_hits, severity_counts, categories) at import
-- so catalog and version lint routes can serve the authoritative import-time report.

ALTER TABLE apiome.versions
  ADD COLUMN IF NOT EXISTS quality_report JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN apiome.versions.quality_report IS
  'Full lint report JSON captured at import (score, grade, fingerprint, findings, tallies). Empty until scored.';
