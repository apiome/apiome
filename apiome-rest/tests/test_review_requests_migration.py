"""Guardrails for the review requests migration — COL-2.1 (#4517).

V261 adds ``reviews`` and ``review_reviewers``. Each fragment below pins a structural promise the
REST layer and the rest of the review roadmap (COL-2.2–2.4) rely on, so a later edit that relaxes
one fails here rather than in production:

* **Stored states** are ``in_review | approved | changes_requested``; ``draft`` is never stored.
* **One open review per version**, by a partial unique index.
* **Rounds** with a content fingerprint, and reviewer rows unique per round.
* **Immutable decisions** — a trigger refuses changing a recorded decision and deciding outside
  the current round of an open review in review; another freezes a withdrawn review.
* **Scope and history** — tenant/project/version cascade; deleting a user keeps their decisions.

The comparison is run against the SQL with ``--`` comments removed, so prose cannot satisfy it.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V261__review_requests_4517.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS reviews (",
    "CREATE TABLE IF NOT EXISTS review_reviewers (",
    # Scope.
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE",
    "version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE",
    "requested_by UUID REFERENCES users(id) ON DELETE SET NULL",
    # States, rounds, closure.
    "state VARCHAR(24) NOT NULL DEFAULT 'in_review'",
    "round INTEGER NOT NULL DEFAULT 1",
    "spec_fingerprint VARCHAR(128) NOT NULL",
    "closed_at TIMESTAMP WITH TIME ZONE,",
    "closed_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "CHECK (closed_at IS NOT NULL OR closed_by IS NULL)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_reviews_open_version",
    "ON reviews (version_id) WHERE closed_at IS NULL",
    # Reviewer rows.
    "review_id UUID NOT NULL REFERENCES reviews(id) ON DELETE CASCADE",
    "user_id UUID REFERENCES users(id) ON DELETE SET NULL",
    "decision VARCHAR(24) NOT NULL DEFAULT 'pending'",
    "CHECK ((decision = 'pending') = (decided_at IS NULL))",
    "CHECK (decision <> 'pending' OR note IS NULL)",
    "UNIQUE (review_id, round, user_id)",
    "ON review_reviewers (user_id) WHERE decision = 'pending'",
    # Immutable decisions.
    "BEFORE UPDATE ON review_reviewers",
    "EXECUTE FUNCTION apiome.review_reviewers_guard_decision();",
    "IF OLD.decision <> 'pending' THEN",
    "parent_closed_at IS NOT NULL OR parent_state <> 'in_review' OR parent_round <> NEW.round",
    "(NEW.user_id IS DISTINCT FROM OLD.user_id AND NEW.user_id IS NOT NULL)",
    # Frozen closed reviews.
    "BEFORE UPDATE ON reviews",
    "EXECUTE FUNCTION apiome.reviews_guard_closed();",
    "IF OLD.closed_at IS NOT NULL",
)

#: Statements that would mean the migration took on a second job, or stored ``draft``.
_FORBIDDEN_FRAGMENTS = (
    "seed_builtin_roles",
    "role_permissions",
    "CREATE TYPE",
    "'draft'",
)


def _statements() -> str:
    """The migration's executable text, ``--`` comments removed, read from the repository root."""
    root = Path(__file__).resolve().parents[2]
    sql = (root / _MIGRATION).read_text(encoding="utf-8")
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def test_migration_keeps_every_structural_promise():
    statements = _statements()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in statements]
    assert not missing, f"V261 no longer keeps: {missing}"


def test_migration_adds_no_rbac_resource_no_enum_type_and_no_stored_draft():
    statements = _statements()
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in statements]
    assert not present, f"V261 took on a second job: {present}"


def test_vocabularies_match_the_rest_models():
    from app.review_lifecycle import DECISIONS, REVIEW_STATES
    from app.reviews import MAX_NOTE_LENGTH

    statements = _statements()
    states = ", ".join(f"'{state}'" for state in REVIEW_STATES)
    decisions = ", ".join(f"'{decision}'" for decision in DECISIONS)
    assert f"CHECK (state IN ({states}))" in statements
    assert f"CHECK (decision IN ({decisions}))" in statements
    assert f"CHECK (note IS NULL OR length(note) <= {MAX_NOTE_LENGTH})" in statements


def test_the_migration_version_is_unique():
    scripts = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts"
    versions = [path.name.split("__", 1)[0] for path in scripts.glob("V*__*.sql")]
    assert versions.count("V261") == 1
