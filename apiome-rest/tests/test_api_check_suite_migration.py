"""Guardrails for the API change check suite migration — GNC-3.1 (#4740).

V267 adds ``api_check_suite_policy`` and ``api_check_suite_runs``, indexes ECA-1.3 runs by revision,
and re-keys GNC-2.2's publish ledger per outcome. Each fragment below pins a structural promise the
REST layer relies on, so a later edit that relaxes one fails here rather than in production:

* **A run is identified by what it judged** — ``UNIQUE (version_id, input_fingerprint)``, the
  re-run idempotency.
* **A placeholder never passes or fails** — a run that judged nothing may only wait or decline.
* **A run carries the policies it was judged under** — both bodies and both fingerprints.
* **Evaluations are append-only** — except the one change a foreign key makes on its own.
* **A dispatch after a failure lands** — the ledger is unique per verdict *per outcome*.

The comparison runs against the SQL with ``--`` comments removed, so prose cannot satisfy it. The
apiome-db sibling ``test/api-check-suite.test.ts`` asserts the same shape from the other side.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V267__api_check_suite_gnc_3_1.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS api_check_suite_policy (",
    "CREATE TABLE IF NOT EXISTS api_check_suite_runs (",
    # Policy scope, as V254: one tenant row, one override per project, both cascading.
    "project_id UUID REFERENCES projects(id) ON DELETE CASCADE",
    "CHECK (jsonb_typeof(policy) = 'object')",
    "ON api_check_suite_policy (tenant_id)\n    WHERE project_id IS NULL",
    "ON api_check_suite_policy (tenant_id, project_id)\n    WHERE project_id IS NOT NULL",
    # A run: scope, and the binding it was reported through going with that binding.
    "version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE",
    "binding_id UUID REFERENCES draft_repository_bindings(id) ON DELETE CASCADE",
    "created_by UUID REFERENCES users(id) ON DELETE SET NULL",
    # The four states, and the placeholder rule.
    "CHECK (state IN ('pending', 'pass', 'fail', 'skipped'))",
    "evaluated BOOLEAN NOT NULL",
    "CHECK (evaluated OR state IN ('pending', 'skipped'))",
    "CHECK ((binding_id IS NULL) = (commit_sha IS NULL))",
    # What the verdict was judged from.
    "draft_digest VARCHAR(71) NOT NULL",
    "CHECK (policy_source IN ('default', 'tenant', 'project'))",
    "CHECK (thresholds_source IN ('default', 'tenant', 'project'))",
    "policy_fingerprint VARCHAR(71) NOT NULL",
    "thresholds_fingerprint VARCHAR(71) NOT NULL",
    "CHECK (jsonb_typeof(thresholds) = 'object')",
    "CHECK (jsonb_typeof(components) = 'array')",
    # The re-run identity.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_api_check_suite_runs_input",
    "ON api_check_suite_runs (version_id, input_fingerprint)",
    # The reads the REST layer makes.
    "CREATE INDEX IF NOT EXISTS idx_api_check_suite_runs_version_created",
    "CREATE INDEX IF NOT EXISTS idx_api_check_suite_runs_binding_commit",
    # Append-only, but not hostage to a user's deletion.
    "BEFORE UPDATE ON api_check_suite_runs",
    "EXECUTE FUNCTION apiome.api_check_suite_runs_append_only();",
    "(to_jsonb(NEW) - 'created_by') = (to_jsonb(OLD) - 'created_by')",
    # Contract evidence by revision — the accessor repeats this expression and predicate exactly.
    "ON verification_run (tenant_id, (source ->> 'revision_id'), created_at DESC)",
    "WHERE source ? 'revision_id'",
    # GNC-2.2's ledger, re-keyed per outcome — created before the old index is dropped.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_check_deliveries_fingerprint_outcome",
    "ON provider_check_deliveries (check_run_id, request_fingerprint, outcome)",
    "DROP INDEX IF EXISTS uq_provider_check_deliveries_fingerprint;",
)

#: Statements that would mean the migration took on a job it should not have.
_FORBIDDEN_FRAGMENTS = (
    "seed_builtin_roles",
    "role_permissions",
    "CREATE TYPE",
    "UPDATE versions",
    "UPDATE apiome.versions",
    "DELETE ON api_check_suite_runs",
)

#: Words that must never name a column of either table: both are read into API responses.
_FORBIDDEN_COLUMN_WORDS = ("token", "secret", "credential", "ciphertext", "password")

_TABLES = ("api_check_suite_policy", "api_check_suite_runs")


def _statements() -> str:
    """The migration's executable text, ``--`` comments removed, read from the repository root."""
    root = Path(__file__).resolve().parents[2]
    sql = (root / _MIGRATION).read_text(encoding="utf-8")
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _table_block(table: str) -> str:
    """One table's column block: from its CREATE TABLE to the closing ``);``."""
    statements = _statements()
    start = statements.index(f"CREATE TABLE IF NOT EXISTS {table} (")
    return statements[start : statements.index("\n);", start)]


def test_migration_keeps_every_structural_promise():
    statements = _statements()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in statements]
    assert not missing, f"V267 no longer keeps: {missing}"


def test_migration_takes_on_no_second_job():
    statements = _statements()
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in statements]
    assert not present, f"V267 took on a second job: {present}"


def test_neither_table_has_anywhere_to_put_a_credential():
    for table in _TABLES:
        block = _table_block(table).lower()
        present = [word for word in _FORBIDDEN_COLUMN_WORDS if word in block]
        assert not present, f"{table} grew a credential column: {present}"


def test_the_ledger_keeps_a_uniqueness_guarantee_throughout_the_swap():
    statements = _statements()
    created = statements.index("uq_provider_check_deliveries_fingerprint_outcome")
    dropped = statements.index("DROP INDEX IF EXISTS uq_provider_check_deliveries_fingerprint;")
    assert created < dropped


def test_every_vocabulary_matches_the_rest_models():
    from app.api_check_suite import POLICY_SOURCES
    from app.provider_checks import CHECK_STATES

    statements = _statements()
    for marker, vocabulary in (
        ("CHECK (state IN (", CHECK_STATES),
        ("CHECK (policy_source IN (", POLICY_SOURCES),
        ("CHECK (thresholds_source IN (", POLICY_SOURCES),
    ):
        start = statements.index(marker) + len(marker)
        check = statements[start : statements.index("))", start)]
        assert {fragment for fragment in check.split("'")[1::2]} == set(vocabulary), marker


def test_the_accessor_names_the_ledgers_new_conflict_target():
    # An ON CONFLICT target that no unique index matches is an error at runtime, not a no-op.
    root = Path(__file__).resolve().parents[1]
    database = (root / "src/app/database.py").read_text(encoding="utf-8")
    assert "ON CONFLICT (check_run_id, request_fingerprint, outcome) DO NOTHING" in database
    assert "ON CONFLICT (check_run_id, request_fingerprint) DO NOTHING" not in database


def test_the_migration_follows_the_ones_it_builds_on():
    root = Path(__file__).resolve().parents[2]
    scripts = sorted(p.name for p in (root / "apiome-db/scripts").glob("V2*.sql"))
    index = scripts.index("V267__api_check_suite_gnc_3_1.sql")
    for earlier in (
        "V212__verification_evidence_4731.sql",
        "V254__deploy_gate_policy_ctg_4_5.sql",
        "V264__draft_repository_bindings_gnc_2_1.sql",
        "V265__provider_check_runs_gnc_2_2.sql",
        "V266__draft_sync_plans_gnc_2_3.sql",
    ):
        assert index > scripts.index(earlier), earlier
