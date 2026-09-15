"""Guardrails for the comment threads migration — COL-1.1 (#4513).

V259 adds ``comment_threads`` and ``comments``. Each fragment below pins a structural promise the
REST layer and the rest of the collaboration roadmap rely on, so a later edit that relaxes one fails
here rather than in production:

* **Anchored by stable element id** — ``anchor_type`` is the closed element vocabulary and
  ``anchor_id`` a UUID; a version anchor is the thread's own version.
* **Status with a recorded resolution** — ``open | resolved``, and ``resolved_at`` is set exactly
  when resolved.
* **Server-resolved mentions** — ``mentions UUID[]``, capped, and GIN indexed for "mentions me"
  and COL-3.1's fan-out.
* **Scope and ownership** — tenant/project/version cascade; deleting a user keeps their words.

The comparison is run against the SQL with ``--`` comments removed, so prose cannot satisfy it.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V259__comment_threads_4513.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS comment_threads (",
    "CREATE TABLE IF NOT EXISTS comments (",
    # Scope.
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE",
    "version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE",
    # Anchoring by stable element id.
    "CHECK (anchor_type IN ('class', 'property', 'path', 'operation', 'version'))",
    "anchor_id UUID NOT NULL",
    "CHECK (anchor_type <> 'version' OR anchor_id = version_id)",
    # Status and resolution.
    "status VARCHAR(16) NOT NULL DEFAULT 'open'",
    "CHECK (status IN ('open', 'resolved'))",
    "CHECK ((status = 'resolved') = (resolved_at IS NOT NULL))",
    "created_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "resolved_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "last_activity_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP",
    # Comments.
    "thread_id UUID NOT NULL REFERENCES comment_threads(id) ON DELETE CASCADE",
    "author_id UUID REFERENCES users(id) ON DELETE SET NULL",
    "CHECK (length(btrim(body)) > 0 AND length(body) <= 20000)",
    "mentions UUID[] NOT NULL DEFAULT ARRAY[]::UUID[]",
    "CHECK (cardinality(mentions) <= 50)",
    "edited_at TIMESTAMP WITH TIME ZONE,",
    # Read paths.
    "ON comment_threads (project_id, last_activity_at DESC)",
    "ON comment_threads (project_id, status)",
    "ON comment_threads (version_id, anchor_type, anchor_id)",
    "ON comments (thread_id, created_at)",
    "ON comments USING GIN (mentions)",
)

#: Statements that would mean the migration took on a second job: V259 adds no RBAC resource.
_FORBIDDEN_FRAGMENTS = (
    "seed_builtin_roles",
    "role_permissions",
    "CREATE TYPE",
)


def _statements() -> str:
    """The migration's executable text, ``--`` comments removed, read from the repository root."""
    root = Path(__file__).resolve().parents[2]
    sql = (root / _MIGRATION).read_text(encoding="utf-8")
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def test_migration_keeps_every_structural_promise():
    statements = _statements()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in statements]
    assert not missing, f"V259 no longer keeps: {missing}"


def test_migration_adds_no_rbac_resource_and_no_enum_type():
    statements = _statements()
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in statements]
    assert not present, f"V259 took on a second job: {present}"


def test_vocabularies_match_the_rest_models():
    from app.comment_mentions import MAX_MENTIONS
    from app.comments import ANCHOR_TYPES, MAX_BODY_LENGTH, STATUS_ORPHANED, THREAD_STATUSES

    statements = _statements()
    anchors = ", ".join(f"'{kind}'" for kind in ANCHOR_TYPES)
    # V259 shipped the first two statuses; V260 (COL-1.4) widens the CHECK with `orphaned`, and
    # tests/test_comment_anchor_resilience_migration.py pins the full vocabulary there.
    statuses = ", ".join(f"'{status}'" for status in THREAD_STATUSES if status != STATUS_ORPHANED)
    assert f"CHECK (anchor_type IN ({anchors}))" in statements
    assert f"CHECK (status IN ({statuses}))" in statements
    assert f"length(body) <= {MAX_BODY_LENGTH}" in statements
    assert f"cardinality(mentions) <= {MAX_MENTIONS}" in statements


def test_every_migration_version_is_unique():
    scripts = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts"
    versions = [path.name.split("__", 1)[0] for path in scripts.glob("V*__*.sql")]
    duplicates = {version for version in versions if versions.count(version) > 1}
    assert "V259" not in duplicates
