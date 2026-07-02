"""Guardrails for the refresh-jobs queue migration (RAR-3.2, #3523)."""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V108__repository_auto_refresh_job_queue_rar_3.sql"

# Fragments the migration must contain so the queue + its single-flight guard
# survive accidental edits. Acceptance criteria for #3523:
#   - a queue table for spec-faithful re-import jobs;
#   - each job carries the stored spec snapshot (options_json + descriptor);
#   - file-level single-flight via a partial unique index on the lineage.
_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS apiome.tenant_repository_refresh_jobs",
    "import_spec_id UUID REFERENCES apiome.repository_import_spec(id)",
    "options_json JSONB NOT NULL DEFAULT '{}'::jsonb",
    "refresh_reason VARCHAR(64)",
    "CHECK (status IN ('queued', 'running', 'succeeded', 'failed'))",
    "uq_tenant_repo_refresh_jobs_active_lineage",
    "ON apiome.tenant_repository_refresh_jobs (repository_id, branch, path)",
    "WHERE status IN ('queued', 'running')",
)


def test_migration_creates_refresh_jobs_queue(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_migration_single_flight_is_partial_unique(repo_root: Path) -> None:
    """The lineage single-flight guard must be a partial UNIQUE index."""
    text = (repo_root / _MIGRATION).read_text()
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_repo_refresh_jobs_active_lineage" in text
