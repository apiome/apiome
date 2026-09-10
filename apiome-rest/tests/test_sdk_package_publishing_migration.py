"""Guardrails for the package-publishing migration — SDK-4.1 (#4495).

V256 adds the two things publishing needs and nothing else has: **a sealed home for a registry
token**, and **a ledger that decides what version number the next upload claims**. Each fragment
below pins a structural promise so a later edit that relaxes it fails here rather than in
production.

Three of them are load-bearing beyond their table:

* ``encrypted_token BYTEA`` with a ``key_version`` — the acceptance criterion "credentials are
  stored encrypted" is a *schema* fact, not only an application one: there is no column a plaintext
  token could be written to.
* ``idx_sdk_publish_runs_claim`` — the partial unique index that makes the derived regen counter
  safe under concurrency. Without it, two publishes computing the same counter both upload.
* Its predicate excluding ``failed`` and ``dry_run`` — which is what frees a number nothing was
  published under, and what keeps a dry run from consuming one.

There are two **negative** assertions as well: the migration must not seed a new RBAC resource
(publishing is ``versions:publish`` and credential management is ``projects:edit``, the same
argument V254 and V255 made), and it must not add a column a token could be stored in the clear in.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V256__sdk_package_publishing_4495.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS sdk_registry_credentials (",
    "CREATE TABLE IF NOT EXISTS sdk_publish_runs (",
    # Rule 1: ciphertext only, and the key that sealed it.
    "encrypted_token BYTEA NOT NULL",
    "key_version INTEGER NOT NULL",
    "CHECK (key_version >= 1)",
    # Rule 2: only non-secret facts live beside it.
    "token_metadata JSONB NOT NULL DEFAULT '{}'::jsonb",
    "CHECK (jsonb_typeof(token_metadata) = 'object')",
    # Only the two ecosystems that have an upload transport.
    "CHECK (ecosystem IN ('npm', 'pypi'))",
    # Rule 3: two scopes, whole-row override, one row each.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sdk_registry_credentials_tenant",
    "ON sdk_registry_credentials (tenant_id, ecosystem)",
    "WHERE project_id IS NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sdk_registry_credentials_project",
    "ON sdk_registry_credentials (tenant_id, project_id, ecosystem)",
    "WHERE project_id IS NOT NULL",
    # Rules 4 and 5: the claim, and what it covers.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sdk_publish_runs_claim",
    "ON sdk_publish_runs (tenant_id, project_id, ecosystem, package_version)",
    "WHERE status IN ('in_progress', 'published', 'already_published')",
    "CHECK (status IN ('in_progress', 'published', 'already_published', 'failed', 'dry_run'))",
    "release_series VARCHAR(64) NOT NULL",
    "regen_counter INTEGER NOT NULL",
    "CHECK (regen_counter >= 0)",
    # The counter query and the history listing both have an index.
    "CREATE INDEX IF NOT EXISTS idx_sdk_publish_runs_series",
    "CREATE INDEX IF NOT EXISTS idx_sdk_publish_runs_history",
    # Rule 6: a run outlives its version, but not its project.
    "version_id UUID REFERENCES versions(id) ON DELETE SET NULL",
    "project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE",
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    # The log is an array of events, and it is written redacted.
    "log JSONB NOT NULL DEFAULT '[]'::jsonb",
    "CHECK (jsonb_typeof(log) = 'array')",
    # A departing user must not take a tenant's ability to publish with them.
    "created_by UUID REFERENCES users(id) ON DELETE SET NULL",
)

#: Executable statements — not prose — that would mean the migration took on a second job, or
#: opened a door a token could be written through in the clear.
_FORBIDDEN_FRAGMENTS = (
    "SELECT apiome.seed_builtin_roles",
    "PERFORM apiome.seed_builtin_roles",
    "CREATE OR REPLACE FUNCTION seed_builtin_roles",
    "token TEXT",
    "token VARCHAR",
    "plaintext_token",
)


def _sql() -> str:
    """Return the migration's text.

    Returns:
        The SQL, read from the repository root.
    """
    root = Path(__file__).resolve().parents[2]
    return (root / _MIGRATION).read_text(encoding="utf-8")


def test_migration_file_exists():
    """The migration is present and numbered after V255."""
    assert _sql().strip()


def test_migration_keeps_every_structural_promise():
    """Each fragment is one acceptance criterion the database keeps rather than the app."""
    sql = _sql()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in sql]
    assert not missing, f"V256 no longer keeps: {missing}"


def test_migration_adds_no_rbac_resource_and_no_plaintext_token_column():
    """No new resource, and nowhere a token could be written unsealed."""
    sql = _sql()
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in sql]
    assert not present, f"V256 took on a second job: {present}"


def test_the_claim_index_is_the_only_uniqueness_rule_on_runs():
    """A run's uniqueness is the *claim*, not its id — anything else would let two uploads race."""
    sql = _sql()
    runs_section = sql.split("CREATE TABLE IF NOT EXISTS sdk_publish_runs")[1]
    assert runs_section.count("CREATE UNIQUE INDEX") == 1


def test_a_dry_run_is_outside_every_claim_predicate():
    """A validation must not consume a version number that nothing was published under."""
    sql = _sql()
    for predicate in [
        line for line in sql.splitlines() if "WHERE status IN" in line
    ]:
        assert "dry_run" not in predicate
        assert "failed" not in predicate


def test_the_credential_indexes_are_partial():
    """Postgres treats distinct NULLs as distinct, so a plain unique index would not constrain
    the tenant-wide row at all — a tenant could accumulate any number of them."""
    sql = _sql()
    credentials_section = sql.split("CREATE TABLE IF NOT EXISTS sdk_publish_runs")[0]
    assert credentials_section.count("CREATE UNIQUE INDEX") == 2
    assert credentials_section.count("WHERE project_id IS NULL") == 1
    assert credentials_section.count("WHERE project_id IS NOT NULL") == 1
