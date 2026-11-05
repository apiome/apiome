"""Guardrails for the export webhook delivery migration — MFX-38.2 (#4329).

V355 adds the record of every export webhook delivery. Each fragment below pins a structural promise, so a
later edit that relaxes it fails here rather than in production:

* **No secret column anywhere** — the body is signed once at request time; only the signed bytes and their
  ``sha256=<hex>`` signature are kept, which cannot sign anything new.
* **Every outcome is a status**, every attempt is kept, and the sweep has an index for what is due.
* **Only http(s) destinations** can be stored.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V355__export_webhook_delivery_4329.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS export_webhook_delivery_runs (",
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "CHECK (target_url ~* '^https?://')",
    "CHECK (status IN ('pending', 'delivering', 'retrying', 'delivered', 'failed'))",
    "CHECK (artifact_delivery IN ('inline', 'fetch'))",
    "payload BYTEA NOT NULL",
    "CHECK (signature ~ '^sha256=[0-9a-f]{64}$')",
    "attempts JSONB NOT NULL DEFAULT '[]'::jsonb",
    "CHECK (jsonb_typeof(attempts) = 'array')",
    "next_attempt_at TIMESTAMPTZ",
    "error_code VARCHAR(64)",
    "CREATE INDEX IF NOT EXISTS idx_export_webhook_delivery_runs_job",
    "ON export_webhook_delivery_runs (tenant_id, job_id, started_at DESC)",
    "WHERE status IN ('pending', 'retrying')",
    "-- Rollback notes",
)


def _migration_text() -> str:
    return (Path(__file__).resolve().parents[2] / _MIGRATION).read_text(encoding="utf-8")


def test_the_migration_carries_every_structural_promise() -> None:
    text = _migration_text()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in text]
    assert missing == []


def test_no_column_could_hold_a_credential() -> None:
    columns = [line.strip().split()[0].lower() for line in _migration_text().splitlines()
               if line.startswith("    ") and not line.strip().startswith(("--", "CONSTRAINT", "CHECK", "AND", "ON",
                                                                            "WHERE", "'"))]
    assert columns
    assert not [name for name in columns if any(word in name for word in ("token", "secret", "password"))]


def test_the_pipeline_s_statuses_match_the_check() -> None:
    from app.export_webhook_delivery_pipeline import RUN_STATUSES

    text = _migration_text()
    assert all(f"'{status}'" in text for status in RUN_STATUSES)
