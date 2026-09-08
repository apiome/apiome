"""Guardrails for the generation-settings migration — SDK-3.4 (#4494).

V255 adds the one thing branding needs and nothing else has: **a durable home for a tenant's
package naming, licence header and user-agent**. Each fragment below pins a structural promise so a
later edit that relaxes it fails here rather than in production.

There are two **negative** assertions as well. The migration must not seed a new RBAC resource —
reading these settings is ``projects:view`` and changing them is ``projects:edit``, the same
argument CTG-4.4 and CTG-4.5 made — and it must not freeze the row, because like CTG-4.5's policy
this table is deliberately mutable: the settings produce no stored verdict, so there is no past
judgment for a version history to explain.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V255__sdk_generation_settings_4494.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS sdk_generation_settings (",
    # Rule 5: settings cannot outlive their scope.
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "project_id UUID REFERENCES projects(id) ON DELETE CASCADE",
    # Rules 2 and 3: one JSONB body, so an absent key (inherit) and a null one (deliberately
    # none) stay distinguishable through the per-key merge.
    "settings JSONB NOT NULL DEFAULT '{}'::jsonb",
    "CONSTRAINT sdk_generation_settings_object_check",
    "CHECK (jsonb_typeof(settings) = 'object')",
    # 7 characters of "sha256:" plus 64 hex.
    "content_fingerprint VARCHAR(71) NOT NULL",
    # Rule 1: exactly one row per scope, enforced by two partial unique indexes.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sdk_generation_settings_tenant",
    "ON sdk_generation_settings (tenant_id)",
    "WHERE project_id IS NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sdk_generation_settings_project",
    "ON sdk_generation_settings (tenant_id, project_id)",
    "WHERE project_id IS NOT NULL",
    # A departing user must not take a tenant's branding with them.
    "created_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "updated_by UUID REFERENCES users(id) ON DELETE SET NULL",
)

#: Executable statements — not prose — that would mean the migration took on a second job.
_FORBIDDEN_FRAGMENTS = (
    "SELECT apiome.seed_builtin_roles",
    "PERFORM apiome.seed_builtin_roles",
    "CREATE OR REPLACE FUNCTION seed_builtin_roles",
    # The row is mutable by design (rule 4); freezing it would break every later edit.
    "BEFORE UPDATE ON sdk_generation_settings",
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
    """The migration is present and numbered after V254."""
    assert _sql().strip()


def test_migration_keeps_every_structural_promise():
    """Each fragment is one acceptance criterion the database keeps rather than the app."""
    sql = _sql()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in sql]
    assert not missing, f"V255 no longer keeps: {missing}"


def test_migration_adds_no_rbac_resource_and_does_not_freeze_the_row():
    """No new resource, and the one table here stays editable."""
    sql = _sql()
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in sql]
    assert not present, f"V255 took on a second job: {present}"


def test_the_two_partial_indexes_are_the_only_uniqueness_rule():
    """A plain unique index on ``(tenant_id, project_id)`` would not constrain the tenant row.

    Postgres treats distinct ``NULL``s as distinct, so a non-partial index would let a tenant
    accumulate any number of tenant-wide rows and the "settings in force" read would be a
    reduction over history rather than a lookup.
    """
    sql = _sql()
    assert sql.count("CREATE UNIQUE INDEX") == 2
    assert sql.count("WHERE project_id IS NULL") >= 1
    assert sql.count("WHERE project_id IS NOT NULL") >= 1


def test_only_this_migration_claims_v255():
    """A duplicate version number is refused by the migrator, but only at deploy time."""
    scripts = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts"
    assert [path.name for path in scripts.glob("V255__*.sql")] == [Path(_MIGRATION).name]
