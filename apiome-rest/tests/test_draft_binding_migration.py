"""Guardrails for the branch-to-draft binding migration — GNC-2.1 (#4737).

V264 adds ``draft_repository_bindings`` and ``draft_binding_sync_candidates``. Each fragment below
pins a structural promise the REST layer relies on, so a later edit that relaxes one fails here
rather than in production:

* **At most one active binding per draft** — a partial unique index on ``version_id``.
* **History is retained** — releasing stamps a row; a released row is frozen, never deleted.
* **The digest is stored and only it moves** — a trigger freezes what a binding names.
* **A ref update becomes a candidate**, idempotent per target commit and per provider delivery.
* **A candidate settles once** — a trigger refuses every later change.
* **Scope and lifetime** — tenant, project, and version cascade; the binder and the registration
  survive.

The comparison is run against the SQL with ``--`` comments removed, so prose cannot satisfy it.
The apiome-db sibling ``test/draft-repository-bindings.test.ts`` asserts the same shape from the
other side of the wire.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V264__draft_repository_bindings_gnc_2_1.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS draft_repository_bindings (",
    "CREATE TABLE IF NOT EXISTS draft_binding_sync_candidates (",
    # Scope and lifetime of a binding.
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE",
    "version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE",
    "repository_id UUID REFERENCES tenant_repositories(id) ON DELETE SET NULL",
    "created_by UUID REFERENCES users(id) ON DELETE SET NULL",
    # What a binding names, and the source it is synchronized with.
    "provider VARCHAR(32) NOT NULL",
    "repo_full_name VARCHAR(512) NOT NULL",
    "ref VARCHAR(255) NOT NULL",
    "path TEXT NOT NULL DEFAULT ''",
    "commit_sha VARCHAR(64) NOT NULL",
    "source_digest VARCHAR(128) NOT NULL",
    "synchronized_at TIMESTAMP WITH TIME ZONE NOT NULL",
    # One active binding per draft; history kept.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_draft_repository_bindings_active_version",
    "ON draft_repository_bindings (version_id) WHERE released_at IS NULL",
    "released_at TIMESTAMP WITH TIME ZONE,",
    "CHECK (released_at IS NOT NULL OR (released_by IS NULL AND release_reason IS NULL))",
    # The webhook lookup.
    "CREATE INDEX IF NOT EXISTS idx_draft_repository_bindings_repo_ref_active",
    "ON draft_repository_bindings (repository_id, ref) WHERE released_at IS NULL",
    # Candidates: what moved, and the two idempotency keys.
    "from_commit_sha VARCHAR(64) NOT NULL",
    "from_digest VARCHAR(128) NOT NULL",
    "to_commit_sha VARCHAR(64) NOT NULL",
    "to_digest VARCHAR(128),",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_draft_binding_sync_candidates_pending",
    "ON draft_binding_sync_candidates (binding_id, to_commit_sha) WHERE status = 'pending'",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_draft_binding_sync_candidates_delivery",
    "ON draft_binding_sync_candidates (binding_id, delivery_id) WHERE delivery_id IS NOT NULL",
    "CHECK ((status = 'pending') = (resolved_at IS NULL))",
    # Immutability.
    "BEFORE UPDATE ON draft_repository_bindings",
    "EXECUTE FUNCTION apiome.draft_repository_bindings_guard_identity();",
    "IF OLD.released_at IS NOT NULL",
    "(NEW.repository_id IS DISTINCT FROM OLD.repository_id AND NEW.repository_id IS NOT NULL)",
    "BEFORE UPDATE ON draft_binding_sync_candidates",
    "EXECUTE FUNCTION apiome.draft_binding_sync_candidates_guard_resolved();",
    "IF OLD.status <> 'pending'",
)

#: Statements that would mean the migration took on a second job.
_FORBIDDEN_FRAGMENTS = (
    "seed_builtin_roles",
    "role_permissions",
    "CREATE TYPE",
    "DELETE FROM apiome.draft_repository_bindings",
)


def _statements() -> str:
    """The migration's executable text, ``--`` comments removed, read from the repository root."""
    root = Path(__file__).resolve().parents[2]
    sql = (root / _MIGRATION).read_text(encoding="utf-8")
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def test_migration_keeps_every_structural_promise():
    statements = _statements()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in statements]
    assert not missing, f"V264 no longer keeps: {missing}"


def test_migration_adds_no_rbac_resource_no_enum_type_and_deletes_no_history():
    statements = _statements()
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in statements]
    assert not present, f"V264 took on a second job: {present}"


def test_every_vocabulary_matches_the_rest_models():
    from app.draft_bindings import (
        CANDIDATE_ORIGINS,
        CANDIDATE_STATUSES,
        PROVIDERS,
        RELEASE_REASONS,
    )

    statements = _statements()
    for vocabulary in (PROVIDERS, RELEASE_REASONS, CANDIDATE_ORIGINS, CANDIDATE_STATUSES):
        for name in vocabulary:
            assert f"'{name}'" in statements, name

    # And nothing the API does not know: every quoted value in a CHECK is one of ours.
    for marker, vocabulary in (
        ("CHECK (provider IN (", PROVIDERS),
        ("CHECK (origin IN (", CANDIDATE_ORIGINS),
        ("CHECK (status IN (", CANDIDATE_STATUSES),
    ):
        start = statements.index(marker) + len(marker)
        check = statements[start : statements.index("))", start)]
        assert {fragment for fragment in check.split("'")[1::2]} == set(vocabulary), marker


def test_the_identity_trigger_freezes_what_a_binding_names_but_not_its_digest():
    statements = _statements()
    for column in ("tenant_id", "project_id", "version_id", "provider", "repo_full_name", "ref", "path"):
        assert f"NEW.{column} IS DISTINCT FROM OLD.{column}" in statements, column
    # The synchronized pair moves while the binding is active: it is guarded only once released.
    identity = statements[
        statements.index("draft_repository_bindings_guard_identity") : statements.index(
            "IF OLD.released_at IS NOT NULL"
        )
    ]
    assert "NEW.commit_sha IS DISTINCT FROM OLD.commit_sha" not in identity
    assert "NEW.source_digest IS DISTINCT FROM OLD.source_digest" not in identity


def test_the_candidate_trigger_freezes_what_was_observed():
    statements = _statements()
    for column in ("binding_id", "from_commit_sha", "from_digest", "to_commit_sha", "origin", "delivery_id"):
        assert f"NEW.{column} IS DISTINCT FROM OLD.{column}" in statements, column
    # to_digest is filled in while pending, so it is not part of what detection fixed.
    observed = statements[
        statements.index("draft_binding_sync_candidates_guard_resolved") : statements.index(
            "IF OLD.status <> 'pending'"
        )
    ]
    assert "NEW.to_digest IS DISTINCT FROM OLD.to_digest" not in observed


def test_the_migration_version_is_unique():
    scripts = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts"
    versions = [path.name.split("__", 1)[0] for path in scripts.glob("V*__*.sql")]
    assert versions.count("V264") == 1
