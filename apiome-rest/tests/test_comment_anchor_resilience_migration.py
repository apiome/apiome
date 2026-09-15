"""Guardrails for the comment anchor resilience migration — COL-1.4 (#4516).

V260 teaches ``comment_threads`` what to do when an anchored element is deleted. Each fragment below
pins a promise the REST layer and the Studio rely on:

* **Orphan state** — ``status`` gains ``orphaned``; ``anchor_label`` and ``orphaned_at`` are set
  exactly while orphaned; a version anchor is never orphaned; an orphaned thread keeps its
  resolution so a relink can restore it.
* **Every writer orphans** — triggers on the soft delete of classes and library properties and on
  the hard delete of class properties, paths, and operations, each reading the deleted row's label.
* **Rename never orphans** — the soft-delete triggers fire on ``UPDATE OF deleted_at`` only, and
  only on the transition to deleted; no trigger watches a name column.

The comparison is run against the SQL with ``--`` comments removed, so prose cannot satisfy it.
"""

import re
from pathlib import Path

_MIGRATION = "apiome-db/scripts/V260__comment_anchor_resilience_4516.sql"

_REQUIRED_FRAGMENTS = (
    # Orphan state.
    "ADD COLUMN IF NOT EXISTS anchor_label VARCHAR(512)",
    "ADD COLUMN IF NOT EXISTS orphaned_at TIMESTAMP WITH TIME ZONE",
    "DROP CONSTRAINT IF EXISTS comment_threads_status_check",
    "CHECK (status = 'orphaned' OR (status = 'resolved') = (resolved_at IS NOT NULL))",
    "(status = 'orphaned') = (orphaned_at IS NOT NULL)",
    "(status = 'orphaned') = (anchor_label IS NOT NULL)",
    "(status <> 'orphaned' OR anchor_type <> 'version')",
    "ON comment_threads (anchor_id) WHERE status <> 'orphaned'",
    # The one orphaning statement.
    "CREATE OR REPLACE FUNCTION apiome.orphan_comment_threads(",
    "SET status = 'orphaned',",
    "AND status <> 'orphaned';",
    # Soft deletes, on the transition to deleted only.
    "AFTER UPDATE OF deleted_at ON apiome.classes",
    "AFTER UPDATE OF deleted_at ON apiome.properties",
    "WHEN (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL)",
    # Hard deletes, before the row (and its label and children) are gone.
    "BEFORE DELETE ON apiome.classes",
    "BEFORE DELETE ON apiome.class_properties",
    "BEFORE DELETE ON apiome.properties",
    "BEFORE DELETE ON apiome.version_path",
    "BEFORE DELETE ON apiome.path_operation",
    # Labels read from the deleted rows.
    "apiome.orphan_comment_threads('class', v_id, v_name)",
    "apiome.orphan_comment_threads('property', v_property.id, v_name || '.' || v_property.name)",
    "apiome.orphan_comment_threads('property', OLD.id, COALESCE(v_class_name || '.', '') || OLD.name)",
    "apiome.orphan_comment_threads('path', OLD.id, OLD.pathname)",
    "upper(v_operation.operation) || ' ' || OLD.pathname",
    "upper(OLD.operation) || COALESCE(' ' || v_pathname, '')",
)

#: Statements that would mean the migration took on a second job.
_FORBIDDEN_FRAGMENTS = (
    "seed_builtin_roles",
    "role_permissions",
    "CREATE TYPE",
    "DROP TABLE",
)


def _statements() -> str:
    """The migration's executable text, ``--`` comments removed, read from the repository root."""
    root = Path(__file__).resolve().parents[2]
    sql = (root / _MIGRATION).read_text(encoding="utf-8")
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def test_migration_keeps_every_structural_promise():
    statements = _statements()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in statements]
    assert not missing, f"V260 no longer keeps: {missing}"


def test_migration_takes_on_no_second_job():
    statements = _statements()
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in statements]
    assert not present, f"V260 took on a second job: {present}"


def test_status_vocabulary_matches_the_rest_models():
    from app.comments import THREAD_STATUSES

    statuses = ", ".join(f"'{status}'" for status in THREAD_STATUSES)
    assert f"CHECK (status IN ({statuses}))" in _statements()


def test_a_rename_can_never_fire_an_orphan_trigger():
    """Every trigger is a delete, or an update of ``deleted_at`` alone — never of a name column."""
    statements = _statements()
    events = re.findall(r"CREATE TRIGGER \w+\s+(BEFORE|AFTER) (.+?) ON apiome\.(\w+)", statements)
    assert len(events) == 7
    for _timing, event, table in events:
        assert event in {"DELETE", "UPDATE OF deleted_at"}, (table, event)
    for column in ("name", "pathname", "operation"):
        assert f"UPDATE OF {column}" not in statements


def test_every_hard_delete_trigger_returns_the_row_it_was_given():
    """A BEFORE DELETE trigger that returned NULL would silently cancel the delete."""
    statements = _statements()
    bodies = re.findall(
        r"FUNCTION apiome\.(comment_threads_orphan_\w+)\(\)\s+RETURNS TRIGGER AS \$\$(.+?)\$\$",
        statements,
        flags=re.DOTALL,
    )
    assert {name for name, _body in bodies} == {
        "comment_threads_orphan_class",
        "comment_threads_orphan_class_property",
        "comment_threads_orphan_property",
        "comment_threads_orphan_path",
        "comment_threads_orphan_operation",
    }
    for name, body in bodies:
        assert "RETURN OLD;" in body, name
        assert "RETURN NULL" not in body, name


def test_the_migration_version_is_unique():
    scripts = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts"
    versions = [path.name.split("__", 1)[0] for path in scripts.glob("V*__*.sql")]
    assert versions.count("V260") == 1
