"""Guardrails for the git delivery migration — SDK-4.2 (#4496).

V257 adds where each SDK is delivered and the record of every attempt. Each fragment below pins a
structural promise, so a later edit that relaxes it fails here rather than in production.

Two of them carry the ticket's acceptance criteria:

* **No token column anywhere** — "works with the existing repository OAuth integrations (no new
  credential type)" is a schema fact: a target references ``tenant_repositories`` and nothing in
  this migration could hold a credential.
* **``failed`` is a status with an ``error_code`` and a ``log``** — "credential failures and push
  rejections surface as failed jobs with actionable logs".
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V257__sdk_git_delivery_4496.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS sdk_git_delivery_targets (",
    "CREATE TABLE IF NOT EXISTS sdk_git_delivery_runs (",
    # Rule 1: the credential is the registered repository's.
    "repository_id UUID NOT NULL REFERENCES tenant_repositories(id) ON DELETE CASCADE",
    # Rule 2: one destination per project per ecosystem.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sdk_git_delivery_targets_project",
    "ON sdk_git_delivery_targets (tenant_id, project_id, ecosystem)",
    "CHECK (ecosystem IN ('npm', 'pypi'))",
    # Rule 3: a stored path cannot leave the repository or enter .git.
    "target_path TEXT NOT NULL DEFAULT ''",
    "target_path !~ '(^|/)\\.\\.?(/|$)'",
    "target_path !~ '(^|/)\\.git(/|$)'",
    "target_path !~ '^/'",
    # Rule 4: every outcome, failure included, is a status.
    "CHECK (status IN ('in_progress', 'opened', 'updated', 'unchanged', 'up_to_date', 'failed'))",
    "error_code VARCHAR(64)",
    "log JSONB NOT NULL DEFAULT '[]'::jsonb",
    "CHECK (jsonb_typeof(log) = 'array')",
    "changes JSONB NOT NULL DEFAULT '{}'::jsonb",
    "provenance JSONB NOT NULL DEFAULT '{}'::jsonb",
    "branch_name VARCHAR(255)",
    "pull_request_number INTEGER",
    # Rule 5: a run outlives its version, target and repository, but not its project.
    "version_id UUID REFERENCES versions(id) ON DELETE SET NULL",
    "target_id UUID REFERENCES sdk_git_delivery_targets(id) ON DELETE SET NULL",
    "repository_id UUID REFERENCES tenant_repositories(id) ON DELETE SET NULL",
    "project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE",
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "CREATE INDEX IF NOT EXISTS idx_sdk_git_delivery_runs_history",
    "created_by UUID REFERENCES users(id) ON DELETE SET NULL",
)

#: Executable statements that would mean the migration took on a second job, or grew somewhere a
#: credential could be stored.
_FORBIDDEN_FRAGMENTS = (
    "SELECT apiome.seed_builtin_roles",
    "PERFORM apiome.seed_builtin_roles",
    "CREATE OR REPLACE FUNCTION seed_builtin_roles",
    "token TEXT",
    "token VARCHAR",
    "token BYTEA",
    "access_token",
    "encrypted_token",
    "secret TEXT",
    "secret BYTEA",
    "secret VARCHAR",
)


def _sql() -> str:
    """Return the migration's text, read from the repository root."""
    root = Path(__file__).resolve().parents[2]
    return (root / _MIGRATION).read_text(encoding="utf-8")


def _statements() -> str:
    """The migration with ``--`` comments removed, so prose cannot satisfy or trip a check."""
    return "\n".join(line.split("--", 1)[0] for line in _sql().splitlines())


def test_migration_file_exists():
    assert _sql().strip()


def test_migration_keeps_every_structural_promise():
    sql = _sql()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in sql]
    assert not missing, f"V257 no longer keeps: {missing}"


def test_migration_adds_no_rbac_resource_and_no_credential_column():
    statements = _statements()
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in statements]
    assert not present, f"V257 took on a second job: {present}"


def test_the_only_uniqueness_rule_is_one_target_per_project_and_ecosystem():
    """Runs are a log — two deliveries of the same version are two rows, not a conflict."""
    statements = _statements()
    assert statements.count("CREATE UNIQUE INDEX") == 1
    runs_section = statements.split("CREATE TABLE IF NOT EXISTS sdk_git_delivery_runs")[1]
    assert "UNIQUE" not in runs_section


def test_every_migration_version_is_unique():
    scripts = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts"
    versions = [path.name.split("__", 1)[0] for path in scripts.glob("V*__*.sql")]
    duplicates = {version for version in versions if versions.count(version) > 1}
    assert "V257" not in duplicates
