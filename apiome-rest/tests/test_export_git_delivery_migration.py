"""Guardrails for the export git delivery migration — MFX-38.1 (#4328).

V354 adds the record of every export git delivery. Each fragment below pins a structural promise, so a
later edit that relaxes it fails here rather than in production:

* **No token column anywhere** — a delivery authenticates with the registered repository's existing
  linked-account integration, so nothing in this migration could hold a credential.
* **Every outcome is a status** — ``committed`` (direct-commit mode) and ``failed`` with an ``error_code``
  and a redacted ``log`` included.
* **A stored path cannot leave the repository or enter ``.git``.**
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V354__export_git_delivery_4328.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS export_git_delivery_runs (",
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "repository_id UUID REFERENCES tenant_repositories(id) ON DELETE SET NULL",
    "CHECK (mode IN ('pr', 'commit'))",
    "CHECK (status IN ('in_progress', 'opened', 'updated', 'unchanged', 'up_to_date',",
    "'committed', 'failed'))",
    "target_path TEXT NOT NULL DEFAULT ''",
    "target_path !~ '(^|/)\\.\\.?(/|$)'",
    "target_path !~ '(^|/)\\.git(/|$)'",
    "target_path !~ '^/'",
    "fidelity JSONB NOT NULL DEFAULT '{}'::jsonb",
    "log JSONB NOT NULL DEFAULT '[]'::jsonb",
    "error_code VARCHAR(64)",
    "CREATE INDEX IF NOT EXISTS idx_export_git_delivery_runs_job",
    "ON export_git_delivery_runs (tenant_id, job_id, started_at DESC)",
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
               if line.startswith("    ") and not line.strip().startswith(("--", "CONSTRAINT", "CHECK", "AND", "ON"))]
    assert not [name for name in columns if any(word in name for word in ("token", "secret", "password"))]


def test_the_pipeline_s_statuses_match_the_check() -> None:
    from app.export_git_delivery_pipeline import RUN_STATUSES

    text = _migration_text()
    assert all(f"'{status}'" in text for status in RUN_STATUSES)
