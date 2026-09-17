"""Guardrails for the provider check migration — GNC-2.2 (#4738).

V265 adds ``provider_check_runs`` and ``provider_check_deliveries``. Each fragment below pins a
structural promise the REST layer relies on, so a later edit that relaxes one fails here rather
than in production:

* **Four states, provider-independent** — ``pending | pass | fail | skipped``, with ``completed_at``
  tied to them so a finished check cannot lack a completion time nor a pending one carry one.
* **A check is identified by what it is about** — ``UNIQUE (binding_id, commit_sha, name)``, which
  is what makes a re-run update one verdict rather than fan out a second.
* **A check inherits its binding's authorization** — it hangs off the binding and is removed with
  it, with no independent path to a repository.
* **Publishing is evidence** — an append-only ledger, one row per distinct verdict published.
* **No credential is stored** — neither table has a token column, encrypted or otherwise.

The comparison runs against the SQL with ``--`` comments removed, so prose cannot satisfy it. The
apiome-db sibling ``test/provider-check-runs.test.ts`` asserts the same shape from the other side
of the wire.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V265__provider_check_runs_gnc_2_2.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS provider_check_runs (",
    "CREATE TABLE IF NOT EXISTS provider_check_deliveries (",
    # Scope and lifetime: a check hangs off its binding and dies with it.
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "binding_id UUID NOT NULL REFERENCES draft_repository_bindings(id) ON DELETE CASCADE",
    "project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE",
    "version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE",
    "created_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "check_run_id UUID NOT NULL REFERENCES provider_check_runs(id) ON DELETE CASCADE",
    # What a verdict is about.
    "provider VARCHAR(32) NOT NULL",
    "repo_full_name VARCHAR(512) NOT NULL",
    "commit_sha VARCHAR(64) NOT NULL",
    "name VARCHAR(128) NOT NULL",
    "state VARCHAR(16) NOT NULL DEFAULT 'pending'",
    "attempt INTEGER NOT NULL DEFAULT 1",
    # Four states, and the completion time tied to them.
    "CHECK (state IN ('pending', 'pass', 'fail', 'skipped'))",
    "CHECK ((state = 'pending') = (completed_at IS NULL))",
    # The re-run identity.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_check_runs_identity",
    "ON provider_check_runs (binding_id, commit_sha, name)",
    # The reads the REST layer makes.
    "CREATE INDEX IF NOT EXISTS idx_provider_check_runs_version_created",
    "CREATE INDEX IF NOT EXISTS idx_provider_check_runs_binding_created",
    "CREATE INDEX IF NOT EXISTS idx_provider_check_runs_repo_commit",
    # The publish ledger and its idempotency key.
    "request_fingerprint VARCHAR(128) NOT NULL",
    "CHECK (outcome IN ('dispatched', 'suppressed', 'failed'))",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_check_deliveries_fingerprint",
    "ON provider_check_deliveries (check_run_id, request_fingerprint)",
    # A row may not overstate its reach (the V187/V197 discipline).
    "CHECK (outcome <> 'suppressed' OR (status_code IS NULL AND external_id IS NULL))",
    "CHECK (outcome <> 'dispatched' OR status_code IS NOT NULL)",
    # Immutability.
    "BEFORE UPDATE ON provider_check_runs",
    "EXECUTE FUNCTION apiome.provider_check_runs_guard_identity();",
    "BEFORE UPDATE ON provider_check_deliveries",
    "EXECUTE FUNCTION apiome.provider_check_deliveries_append_only();",
    "IF NEW.attempt < OLD.attempt THEN",
)

#: Statements that would mean the migration took on a second job.
_FORBIDDEN_FRAGMENTS = (
    "seed_builtin_roles",
    "role_permissions",
    "CREATE TYPE",
    "DELETE FROM apiome.provider_check_runs",
)

#: Words that must never name a column of either table. Rule 5: these rows are read straight into
#: an API response a browser client receives, so there must be nowhere for a credential to sit —
#: not even an encrypted one, which would only move the leak to whoever can decrypt it.
_FORBIDDEN_COLUMN_WORDS = ("token", "secret", "credential", "ciphertext", "password")

#: The two tables whose columns are checked.
_TABLES = ("provider_check_runs", "provider_check_deliveries")


def _statements() -> str:
    """The migration's executable text, ``--`` comments removed, read from the repository root."""
    root = Path(__file__).resolve().parents[2]
    sql = (root / _MIGRATION).read_text(encoding="utf-8")
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def test_migration_keeps_every_structural_promise():
    statements = _statements()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in statements]
    assert not missing, f"V265 no longer keeps: {missing}"


def _table_block(table: str) -> str:
    """One table's column block: from its CREATE TABLE to the closing ``);``."""
    statements = _statements()
    start = statements.index(f"CREATE TABLE IF NOT EXISTS {table} (")
    return statements[start : statements.index("\n);", start)]


def test_migration_adds_no_rbac_resource_and_no_enum_type():
    statements = _statements()
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in statements]
    assert not present, f"V265 took on a second job: {present}"


def test_neither_table_has_anywhere_to_put_a_credential():
    for table in _TABLES:
        block = _table_block(table).lower()
        present = [word for word in _FORBIDDEN_COLUMN_WORDS if word in block]
        assert not present, f"{table} grew a credential column: {present}"


def test_every_vocabulary_matches_the_rest_models():
    from app.provider_checks import CHECK_ORIGINS, CHECK_STATES, PUBLISH_OUTCOMES
    from app.provider_status_adapter import supported_providers

    statements = _statements()
    for vocabulary in (CHECK_STATES, CHECK_ORIGINS, PUBLISH_OUTCOMES):
        for name in vocabulary:
            assert f"'{name}'" in statements, name

    # And nothing the API does not know: every quoted value in a CHECK is one of ours.
    for marker, vocabulary in (
        ("CHECK (state IN (", CHECK_STATES),
        ("CHECK (origin IN (", CHECK_ORIGINS),
        ("CHECK (outcome IN (", PUBLISH_OUTCOMES),
    ):
        start = statements.index(marker) + len(marker)
        check = statements[start : statements.index("))", start)]
        assert {fragment for fragment in check.split("'")[1::2]} == set(vocabulary), marker

    # Every provider the schema accepts has an adapter, and vice versa: a check that could be
    # stored but never published would be a green tick nobody can ever see.
    start = statements.index("CHECK (provider IN (")
    check = statements[start : statements.index("))", start)]
    assert set(check.split("'")[1::2]) == set(supported_providers())


def test_the_identity_trigger_freezes_what_a_check_is_about_but_not_its_verdict():
    statements = _statements()
    for column in (
        "tenant_id",
        "binding_id",
        "project_id",
        "version_id",
        "provider",
        "repo_full_name",
        "commit_sha",
        "name",
    ):
        assert f"NEW.{column} IS DISTINCT FROM OLD.{column}" in statements, column
    # The verdict and its presentation move; they are not part of the identity.
    identity = statements[
        statements.index("provider_check_runs_guard_identity") : statements.index(
            "IF NEW.attempt < OLD.attempt THEN"
        )
    ]
    for column in ("state", "title", "summary", "details_url", "external_id", "completed_at"):
        assert f"NEW.{column} IS DISTINCT FROM OLD.{column}" not in identity, column


def test_the_delivery_ledger_refuses_a_rewrite_but_not_the_cascades():
    statements = _statements()
    trigger = statements[statements.index("DROP TRIGGER IF EXISTS trg_provider_check_deliveries") :]
    assert "BEFORE UPDATE ON provider_check_deliveries" in trigger
    # A BEFORE DELETE guard would also fire for the rows a cascade removes, taking the rest of
    # the schema hostage; removal is governed by the cascades instead.
    assert "DELETE ON provider_check_deliveries" not in trigger


def test_the_migration_follows_the_binding_one_it_builds_on():
    root = Path(__file__).resolve().parents[2]
    scripts = sorted(p.name for p in (root / "apiome-db/scripts").glob("V2*.sql"))
    assert scripts.index("V265__provider_check_runs_gnc_2_2.sql") > scripts.index(
        "V264__draft_repository_bindings_gnc_2_1.sql"
    )
