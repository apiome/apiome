"""Guardrails for the scheduled-verification migration — CTG-4.4 (#4501).

V253 is where the ticket's structural promises stop being habits and become things the database
keeps. Each fragment below pins one, so a later edit that relaxes it fails here rather than in
production six months later:

* a schedule cannot outlive the deployment it checks (hard FK, ON DELETE CASCADE);
* retiring a schedule keeps its history (soft delete, and the unique indexes are partial on it);
* run history is **write-once**, using the same guard V212 and V252 apply;
* a run row can never cite another tenant's schedule (the composite foreign key);
* the alert state machine lives on the row — which is what makes "exactly one alert" survive a
  restart and hold across replicas; and
* the cadence floor is enforced by the database, not only by the application.

There is also a **negative** assertion: this migration must not touch ``seed_builtin_roles``. A
schedule is governed by V211's ``verification_targets`` resource and its history by V212's
``verification_evidence``; adding a resource costs four synchronised edits across the database, the
REST enum, the enforcement call sites, and the UI role matrix, and a permission that would always
be granted alongside an existing one earns none of them.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V253__verification_schedule_ctg_4_4.sql"

_REQUIRED_FRAGMENTS = (
    # The two tables, tenant-scoped.
    "CREATE TABLE IF NOT EXISTS verification_schedule (",
    "CREATE TABLE IF NOT EXISTS verification_schedule_run (",
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    # Rule 1: a schedule cannot outlive its deployment.
    "target_id UUID NOT NULL REFERENCES verification_target(id) ON DELETE CASCADE",
    # Rule 2: retiring keeps the history, and the uniqueness rules ignore retired rows.
    "deleted_at TIMESTAMPTZ",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_verification_schedule_slug",
    "ON verification_schedule (tenant_id, lower(slug))",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_verification_schedule_pair",
    "ON verification_schedule (tenant_id, version_ref, target_id)",
    "WHERE deleted_at IS NULL",
    # Rule 3: history is write-once, using the shared V128 guard.
    "CREATE TRIGGER trigger_verification_schedule_run_immutable",
    "BEFORE UPDATE ON verification_schedule_run",
    "EXECUTE FUNCTION mcp_forbid_row_mutation();",
    # Rule 4: a run row belongs to the same tenant as the schedule it cites.
    "CONSTRAINT verification_schedule_id_tenant_key UNIQUE (id, tenant_id)",
    "CONSTRAINT verification_schedule_run_schedule_fk",
    "FOREIGN KEY (schedule_id, tenant_id)",
    "REFERENCES verification_schedule (id, tenant_id)",
    # Rule 5: the alert machine is stored, not remembered by a worker.
    "alert_state VARCHAR(16) NOT NULL DEFAULT 'ok'",
    "CHECK (alert_state IN ('ok', 'alerting'))",
    "alert_fingerprint VARCHAR(71)",
    # Rule 6 and the freshness anchor CTG-4.5 reads.
    "last_run_at TIMESTAMPTZ",
    "last_success_at TIMESTAMPTZ",
    "consecutive_failures INTEGER NOT NULL DEFAULT 0",
    # The cadence floor is the database's rule too, not only the application's.
    "CONSTRAINT verification_schedule_cadence_check",
    "CHECK (cadence_seconds >= 300 AND cadence_seconds <= 2592000)",
    # The closed status vocabulary the history stores.
    "CHECK (status IN ('passed', 'failed', 'errored'))",
    "CHECK (alert_reason IS NULL OR alert_reason IN",
    # A purged report must not put a hole in the freshness history.
    "report_id UUID REFERENCES provider_verification_report(id) ON DELETE SET NULL",
    # The reads the sweep and CTG-4.5 make.
    "CREATE INDEX IF NOT EXISTS idx_verification_schedule_due",
    "CREATE INDEX IF NOT EXISTS idx_verification_schedule_version",
    "CREATE INDEX IF NOT EXISTS idx_verification_schedule_run_schedule",
    # Retention, mirroring the evidence and report sweeps.
    "CREATE OR REPLACE FUNCTION purge_verification_schedule_runs(",
)

#: Executable statements — not prose — that would mean the migration quietly took on a second job.
_FORBIDDEN_FRAGMENTS = (
    "SELECT apiome.seed_builtin_roles",
    "PERFORM apiome.seed_builtin_roles",
    "CREATE OR REPLACE FUNCTION seed_builtin_roles",
    # A schedule is mutable by design: the sweep advances its anchor on every tick.
    "BEFORE UPDATE ON verification_schedule\n",
)


def _sql() -> str:
    """Return the migration's text.

    Returns:
        The SQL, read from the repository root.
    """
    root = Path(__file__).resolve().parents[2]
    return (root / _MIGRATION).read_text(encoding="utf-8")


def test_migration_file_exists():
    """The migration is present and numbered after V252, whose table it references."""
    assert _sql().strip()


def test_migration_keeps_every_structural_promise():
    """Each fragment is one acceptance criterion the database keeps rather than the app."""
    sql = _sql()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in sql]
    assert not missing, f"V253 no longer keeps: {missing}"


def test_migration_does_not_seed_roles_or_freeze_the_schedule():
    """No new RBAC resource, and the schedule row stays mutable so its anchor can advance."""
    sql = _sql()
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in sql]
    assert not present, f"V253 took on a second job: {present}"


def test_history_is_immutable_but_the_schedule_is_not():
    """The asymmetry is the point: what happened is fixed, what to do next is not."""
    sql = _sql()
    assert "BEFORE UPDATE ON verification_schedule_run" in sql
    assert sql.count("mcp_forbid_row_mutation()") == 1
