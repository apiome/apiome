"""Guardrails for the deploy-gate policy migration — CTG-4.5 (#4502).

V254 adds the one thing the four signals did not already supply: **where the bar is**. Each
fragment below pins a structural promise so a later edit that relaxes it fails here rather than in
production.

There are two **negative** assertions as well. The migration must not seed a new RBAC resource —
reading a gate is ``versions:view`` and moving the bar is ``verification_targets:edit``, the same
argument CTG-4.4 made for schedules — and it must not make the policy row immutable, because unlike
every other policy table in the platform this one is deliberately mutable: the gate stores no
verdict, so there is no past judgment for a version history to explain.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V254__deploy_gate_policy_ctg_4_5.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS deploy_gate_policy (",
    # Rule 4: a policy cannot outlive its scope.
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "project_id UUID REFERENCES projects(id) ON DELETE CASCADE",
    # Rule 3: the thresholds are one JSONB body, so "unset" and "null" stay distinguishable.
    "thresholds JSONB NOT NULL DEFAULT '{}'::jsonb",
    "CONSTRAINT deploy_gate_policy_thresholds_object_check",
    "CHECK (jsonb_typeof(thresholds) = 'object')",
    "content_fingerprint VARCHAR(71) NOT NULL",
    # Rule 1: exactly one row per scope, enforced by two partial unique indexes.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_deploy_gate_policy_tenant",
    "ON deploy_gate_policy (tenant_id)",
    "WHERE project_id IS NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_deploy_gate_policy_project",
    "ON deploy_gate_policy (tenant_id, project_id)",
    "WHERE project_id IS NOT NULL",
    # A departing user must not take a tenant's gate with them.
    "created_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "updated_by UUID REFERENCES users(id) ON DELETE SET NULL",
    # The gate's verification fallback: "the newest report for this project", however the
    # version reference was spelled.
    "CREATE INDEX IF NOT EXISTS idx_provider_verification_report_artifact",
    "ON provider_verification_report (tenant_id, artifact_kind, artifact_id, created_at DESC)",
)

#: Executable statements — not prose — that would mean the migration took on a second job.
_FORBIDDEN_FRAGMENTS = (
    "SELECT apiome.seed_builtin_roles",
    "PERFORM apiome.seed_builtin_roles",
    "CREATE OR REPLACE FUNCTION seed_builtin_roles",
    # The policy row is mutable by design (rule 2); freezing it would break every later edit.
    "BEFORE UPDATE ON deploy_gate_policy",
    "mcp_forbid_row_mutation",
)


def _sql() -> str:
    """Return the migration's text.

    Returns:
        The SQL, read from the repository root.
    """
    root = Path(__file__).resolve().parents[2]
    return (root / _MIGRATION).read_text(encoding="utf-8")


def test_migration_file_exists():
    """The migration is present and numbered after V253."""
    assert _sql().strip()


def test_migration_keeps_every_structural_promise():
    """Each fragment is one acceptance criterion the database keeps rather than the app."""
    sql = _sql()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in sql]
    assert not missing, f"V254 no longer keeps: {missing}"


def test_migration_adds_no_rbac_resource_and_does_not_freeze_the_policy():
    """No new resource, and the one table here stays editable."""
    sql = _sql()
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in sql]
    assert not present, f"V254 took on a second job: {present}"


def test_no_duplicate_migration_versions():
    """A duplicate version number is refused by the migrator, but only at deploy time.

    Checked across the whole directory rather than by pinning V254 as the newest: the rule that
    matters is uniqueness, and "I am the newest" is a tripwire the next ticket has to defuse.
    """
    scripts = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts"
    assert [path.name for path in scripts.glob("V254__*.sql")] == [Path(_MIGRATION).name]

    seen: dict[str, str] = {}
    duplicates: list[tuple[str, str]] = []
    for path in sorted(scripts.glob("V*__*.sql")):
        version = path.name.split("__", 1)[0]
        if version in seen:
            duplicates.append((seen[version], path.name))
        seen[version] = path.name
    assert not duplicates, f"duplicate migration versions: {duplicates}"
