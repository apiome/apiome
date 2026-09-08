"""Guardrails for the provider verification report migration — CTG-4.3 (#4489).

V252 is where the ticket's structural promises stop being habits and become things the database
keeps. Each fragment below pins one, so a later edit that relaxes it fails here rather than in
production six months later:

* a report is **write-once**, like the evidence it summarises — nothing can turn a red deployment
  green after the fact;
* a report can never summarise another tenant's run (the composite foreign key), and cannot outlive
  the run it cites;
* one report per run — a second verdict on the same evidence is not a thing;
* coverage and the verdict are **columns**, so the CTG-4.4 / CTG-4.5 lookups need no JSON walk;
* the coverage denominator is stored honestly: ``operations_total`` counts what the specification
  declares, ``operations_uncompiled`` counts what could not be compiled, and exercised can never
  exceed total.

There is also a **negative** assertion: this migration must not touch ``seed_builtin_roles``. A
conformance report is verification evidence, governed by V212's existing ``verification_evidence``
resource; adding a resource costs four synchronised edits across the database, the REST enum, the
enforcement call sites, and the UI role matrix, and a permission that would always be granted
alongside an existing one earns none of them.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V252__provider_verification_report_ctg_4_3.sql"

_REQUIRED_FRAGMENTS = (
    # The table, tenant-scoped.
    "CREATE TABLE IF NOT EXISTS provider_verification_report (",
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    # Rule 2: a report belongs to the same tenant as the run it summarises, and dies with it.
    "CONSTRAINT provider_verification_report_run_fk",
    "FOREIGN KEY (run_id, tenant_id)",
    "REFERENCES verification_run (id, tenant_id)",
    "ON DELETE CASCADE",
    # One report per run.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_verification_report_run",
    # Rule 1: write-once, using the shared V128 guard the evidence tables use.
    "CREATE TRIGGER trigger_provider_verification_report_immutable",
    "BEFORE UPDATE ON provider_verification_report",
    "EXECUTE FUNCTION mcp_forbid_row_mutation();",
    # Rule 3: the verdict and coverage are queryable columns.
    "provider_verification_report_outcome_check",
    "CHECK (outcome IN ('passed', 'failed', 'errored'))",
    "operations_total INTEGER NOT NULL DEFAULT 0",
    "operations_exercised INTEGER NOT NULL DEFAULT 0",
    "operations_uncompiled INTEGER NOT NULL DEFAULT 0",
    "coverage_percent NUMERIC(5,2) NOT NULL DEFAULT 0",
    "drift_count INTEGER NOT NULL DEFAULT 0",
    "mutating_allowed BOOLEAN NOT NULL DEFAULT FALSE",
    # Rule 4: coverage can never exceed the specification it is measured against.
    "CONSTRAINT provider_verification_report_coverage_bound_check",
    "CHECK (operations_exercised <= operations_total)",
    # The full report is stored, never optional.
    "report JSONB NOT NULL DEFAULT '{}'::jsonb",
    # Rule 5: the target is an identity snapshot; losing the definition does not falsify a report.
    "target_id UUID REFERENCES verification_target(id) ON DELETE SET NULL",
    "target_base_url TEXT NOT NULL",
    # The reads CTG-4.4 and CTG-4.5 make.
    "CREATE INDEX IF NOT EXISTS idx_provider_verification_report_version",
    "ON provider_verification_report (tenant_id, version_ref, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_provider_verification_report_failures",
    "WHERE outcome <> 'passed'",
    # Retention, mirroring the evidence sweep.
    "CREATE OR REPLACE FUNCTION purge_provider_verification_reports(",
)

#: Executable statements — not prose — that would mean the migration quietly took on a second job.
#: The module docstring names ``seed_builtin_roles``; what must not appear is a *call* to it.
_FORBIDDEN_FRAGMENTS = (
    # No new RBAC resource: a conformance report is verification evidence.
    "CREATE OR REPLACE FUNCTION apiome.seed_builtin_roles",
    "PERFORM apiome.seed_builtin_roles",
    "INSERT INTO apiome.role_permissions",
    "'provider_verifications'",
    # Reports are never updated in place — no code path, and no migration, should imply one.
    "UPDATE apiome.provider_verification_report",
)


def test_migration_declares_the_report_rules(repo_root: Path) -> None:
    """Every structural promise the report layer relies on is in the migration."""
    text = (repo_root / _MIGRATION).read_text()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_migration_adds_no_rbac_resource(repo_root: Path) -> None:
    """Reusing ``verification_evidence`` is deliberate — see the module docstring."""
    text = (repo_root / _MIGRATION).read_text()
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in text]
    assert not present, f"Migration unexpectedly touches: {present}"


def test_migration_version_numbers_are_unique(repo_root: Path) -> None:
    """A duplicate version number is refused by the migrator, but only at deploy time.

    Checked across the whole directory rather than by pinning V252 as the newest: the rule that
    matters is that two migrations never claim one number, and a rule phrased as "nothing newer
    exists" has to be edited by every ticket that adds a migration, which is how it stops being
    checked at all.
    """
    scripts = repo_root / "apiome-db" / "scripts"
    assert [path.name for path in scripts.glob("V252__*.sql")] == [Path(_MIGRATION).name]

    seen: dict[str, str] = {}
    duplicates: list[tuple[str, str]] = []
    for path in sorted(scripts.glob("V*__*.sql")):
        version = path.name.split("__", 1)[0]
        if version in seen:
            duplicates.append((seen[version], path.name))
        seen[version] = path.name
    assert not duplicates, f"duplicate migration versions: {duplicates}"


def test_the_report_layer_reuses_the_existing_evidence_resource() -> None:
    """The REST side must enforce the same resource the migration deliberately did not add."""
    from app.permissions import RESOURCES, Resource

    assert Resource.VERIFICATION_EVIDENCE == "verification_evidence"
    assert "verification_evidence" in RESOURCES
    assert "provider_verifications" not in RESOURCES
