"""Guardrails for the three-way synchronization migration — GNC-2.3 (#4739).

V266 adds ``draft_sync_plans`` and ``draft_sync_conflicts``. Each fragment below pins a structural
promise the REST layer relies on, so a later edit that relaxes one fails here rather than in
production:

* **A plan is a reading, never a write** — no statement in the migration reaches ``versions``, and
  no column claims a draft was changed. That is "an active draft or review decision is never
  overwritten", expressed where it cannot be argued with.
* **A plan is identified by the three documents it merged** — ``UNIQUE (binding_id,
  plan_fingerprint)``, which is what makes a rerun idempotent.
* **All three digests are recorded** — base, Git and draft, the ticket's fourth acceptance
  criterion literally.
* **A conflict names a place** — pointer, scope and group, plus the repository file and line.
* **A settlement is final** — a conflict is resolved once, towards ``git`` or ``draft``.

The comparison runs against the SQL with ``--`` comments removed, so prose cannot satisfy it. The
apiome-db sibling ``test/draft-sync-plans.test.ts`` asserts the same shape from the other side of
the wire.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V266__draft_sync_plans_gnc_2_3.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS draft_sync_plans (",
    "CREATE TABLE IF NOT EXISTS draft_sync_conflicts (",
    # Scope and lifetime: a plan hangs off its binding and dies with it, and outlives the
    # notification that prompted it.
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "binding_id UUID NOT NULL REFERENCES draft_repository_bindings(id) ON DELETE CASCADE",
    "project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE",
    "version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE",
    "candidate_id UUID REFERENCES draft_binding_sync_candidates(id) ON DELETE SET NULL",
    "computed_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "plan_id UUID NOT NULL REFERENCES draft_sync_plans(id) ON DELETE CASCADE",
    # The three documents a merge was computed from.
    "base_commit_sha VARCHAR(64) NOT NULL",
    "base_digest VARCHAR(128) NOT NULL",
    "git_commit_sha VARCHAR(64) NOT NULL",
    "git_digest VARCHAR(128) NOT NULL",
    "draft_digest VARCHAR(128) NOT NULL",
    "plan_fingerprint VARCHAR(128) NOT NULL",
    # The outcome, and the three ways of saying it that may not disagree.
    "CHECK (status IN ('clean', 'mergeable', 'conflicted', 'resolved'))",
    "CHECK (unresolved_count >= 0 AND unresolved_count <= conflict_count)",
    "CHECK (status <> 'clean' OR auto_applied_count = 0)",
    "conflicts_truncated BOOLEAN NOT NULL DEFAULT FALSE",
    "CHECK (jsonb_typeof(changes) = 'array')",
    "CHECK (guard IN ('none', 'review_decided', 'version_published'))",
    # The rerun identity.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_draft_sync_plans_fingerprint",
    "ON draft_sync_plans (binding_id, plan_fingerprint)",
    # The reads the REST layer makes.
    "CREATE INDEX IF NOT EXISTS idx_draft_sync_plans_version_created",
    "CREATE INDEX IF NOT EXISTS idx_draft_sync_plans_binding_created",
    "CREATE INDEX IF NOT EXISTS idx_draft_sync_conflicts_plan_created",
    # A conflict: where it is, what each side did, and all three values.
    "pointer TEXT NOT NULL",
    "CHECK (scope IN ('document', 'path', 'operation', 'component', 'schema'))",
    "CHECK (git_kind IN ('addition', 'update', 'deletion'))",
    "CHECK (draft_kind IN ('addition', 'update', 'deletion'))",
    "base_value JSONB",
    "git_value JSONB",
    "draft_value JSONB",
    "source_file TEXT NOT NULL DEFAULT ''",
    "CHECK (source_line IS NULL OR source_line > 0)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_draft_sync_conflicts_pointer",
    "ON draft_sync_conflicts (plan_id, pointer)",
    # Settlement, and its finality.
    "CHECK (resolution IS NULL OR resolution IN ('git', 'draft'))",
    "CHECK ((resolution IS NULL) = (resolved_at IS NULL))",
    "BEFORE UPDATE ON draft_sync_plans",
    "EXECUTE FUNCTION apiome.draft_sync_plans_guard_identity();",
    "BEFORE UPDATE ON draft_sync_conflicts",
    "EXECUTE FUNCTION apiome.draft_sync_conflicts_guard_settlement();",
    "IF NEW.unresolved_count > OLD.unresolved_count THEN",
    # What the merge found never moves as it is settled — the count, and whether it was a page of
    # a longer list.
    "NEW.conflict_count IS DISTINCT FROM OLD.conflict_count",
    "NEW.conflicts_truncated IS DISTINCT FROM OLD.conflicts_truncated",
)

#: Statements that would mean the migration took on a second job — or, in the case of the three
#: ``versions`` writes, that it took on the one job this whole ticket exists to prevent.
_FORBIDDEN_FRAGMENTS = (
    "seed_builtin_roles",
    "role_permissions",
    "CREATE TYPE",
    "UPDATE versions",
    "UPDATE apiome.versions",
    "INSERT INTO versions",
    "INSERT INTO apiome.versions",
    "DELETE FROM apiome.draft_sync_plans",
)

#: Words that must never name a column of either table. These rows are read straight into an API
#: response a browser client receives, so there must be nowhere for a credential to sit.
_FORBIDDEN_COLUMN_WORDS = ("token", "secret", "credential", "ciphertext", "password")

#: The two tables whose columns are checked.
_TABLES = ("draft_sync_plans", "draft_sync_conflicts")


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
    assert not missing, f"V266 no longer keeps: {missing}"


def test_migration_never_writes_to_the_thing_it_describes():
    statements = _statements()
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in statements]
    assert not present, f"V266 took on a second job: {present}"
    # No column claims a draft was edited, because none ever is.
    assert "applied_at" not in _table_block("draft_sync_plans")


def test_neither_table_has_anywhere_to_put_a_credential():
    for table in _TABLES:
        block = _table_block(table).lower()
        present = [word for word in _FORBIDDEN_COLUMN_WORDS if word in block]
        assert not present, f"{table} grew a credential column: {present}"


def test_every_vocabulary_matches_the_rest_models():
    from app.source_change_review import scope_for_pointer
    from app.spec_sync import GUARDS, KINDS, RESOLUTIONS, STATUSES

    statements = _statements()
    for vocabulary in (STATUSES, GUARDS, KINDS, RESOLUTIONS):
        for name in vocabulary:
            assert f"'{name}'" in statements, name

    # And nothing the API does not know: every quoted value in a CHECK is one of ours.
    for marker, vocabulary in (
        ("CHECK (status IN (", STATUSES),
        ("CHECK (guard IN (", GUARDS),
        ("CHECK (git_kind IN (", KINDS),
        ("CHECK (draft_kind IN (", KINDS),
        ("CHECK (resolution IS NULL OR resolution IN (", RESOLUTIONS),
    ):
        start = statements.index(marker) + len(marker)
        check = statements[start : statements.index("))", start)]
        assert {fragment for fragment in check.split("'")[1::2]} == set(vocabulary), marker

    # Every scope the schema accepts is one the shared change vocabulary can actually produce.
    start = statements.index("CHECK (scope IN (")
    check = statements[start : statements.index("))", start)]
    stored_scopes = set(check.split("'")[1::2])
    produced = {
        scope_for_pointer(pointer)[0]
        for pointer in (
            "",
            "/openapi",
            "/paths/~1pets",
            "/paths/~1pets/get/summary",
            "/components/schemas/Pet",
            "/components/responses/NotFound",
        )
    }
    assert produced <= stored_scopes
    assert stored_scopes == {"document", "path", "operation", "component", "schema"}


def test_the_identity_trigger_freezes_what_a_merge_was_computed_from_but_not_its_outcome():
    statements = _statements()
    identity = statements[
        statements.index("draft_sync_plans_guard_identity") : statements.index(
            "IF NEW.conflict_count IS DISTINCT FROM OLD.conflict_count"
        )
    ]
    for column in (
        "tenant_id",
        "binding_id",
        "project_id",
        "version_id",
        "base_commit_sha",
        "base_digest",
        "git_commit_sha",
        "git_digest",
        "draft_digest",
        "plan_fingerprint",
    ):
        assert f"NEW.{column} IS DISTINCT FROM OLD.{column}" in identity, column
    # Settling conflicts is exactly what an update is for.
    for column in ("status", "unresolved_count", "guard", "updated_at"):
        assert f"NEW.{column} IS DISTINCT FROM OLD.{column}" not in identity, column


def test_a_conflict_is_settled_once_and_never_re_described():
    statements = _statements()
    guard = statements[statements.index("draft_sync_conflicts_guard_settlement") :]
    for column in ("pointer", "scope", "git_kind", "draft_kind", "base_value", "git_value", "draft_value"):
        assert f"NEW.{column} IS DISTINCT FROM OLD.{column}" in guard, column
    assert "IF OLD.resolution IS NOT NULL AND NEW.resolution IS DISTINCT FROM OLD.resolution THEN" in guard
    # A BEFORE DELETE guard would also fire for the rows a cascade removes, taking the rest of
    # the schema hostage; removal is governed by the cascades instead — the V265 lesson.
    assert "DELETE ON draft_sync_conflicts" not in statements
    assert "DELETE ON draft_sync_plans" not in statements


def test_the_migration_follows_the_binding_and_check_ones_it_builds_on():
    root = Path(__file__).resolve().parents[2]
    scripts = sorted(p.name for p in (root / "apiome-db/scripts").glob("V2*.sql"))
    index = scripts.index("V266__draft_sync_plans_gnc_2_3.sql")
    assert index > scripts.index("V264__draft_repository_bindings_gnc_2_1.sql")
    assert index > scripts.index("V265__provider_check_runs_gnc_2_2.sql")
