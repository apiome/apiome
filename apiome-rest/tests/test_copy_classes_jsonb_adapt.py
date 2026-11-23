"""Copying classes for a merge keeps property ``data`` inside the database.

``copy_classes_from_version_for_merge`` (used when cutting/pushing a new version with
``source_version_id``) once read each property's ``data`` JSONB back as a Python ``dict`` and
re-inserted it; a bare ``dict`` bind parameter made psycopg2 raise ``can't adapt type 'dict'`` and
the whole version-cut transaction answered 500 (golden-path smoke test, #3608).

Since DBP-1.7 (#7190) the copy is ``INSERT … SELECT`` statements: the rows never travel through
Python, so there is nothing to adapt and SQL NULL stays SQL NULL. These tests pin that shape —
only ids are bound — and that the number of statements does not grow with the number of classes.
The copied rows themselves are checked against PostgreSQL in ``test_set_based_writes_db.py``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.database import db


class _FakeCursor:
    """Cursor stub that replays queued ``fetchall`` results and records every statement."""

    def __init__(self, fetchall_queue: List[List[Dict[str, Any]]]):
        self._fetchall = list(fetchall_queue)
        self.executed: List[tuple[str, Any]] = []

    def execute(self, query: str, params: Any = None) -> None:
        self.executed.append((" ".join(query.split()), params))

    def fetchall(self) -> List[Dict[str, Any]]:
        return self._fetchall.pop(0) if self._fetchall else []


def _copy(class_count: int, levels: int) -> _FakeCursor:
    """Copy ``class_count`` classes whose properties nest ``levels`` deep."""
    classes = [{"source_id": f"src-class-{i}", "target_id": f"new-class-{i}"} for i in range(class_count)]
    level_rows = [
        [
            {"old_id": f"old-{depth}-{i}", "new_id": f"new-{depth}-{i}", "target_class_id": f"new-class-{i}"}
            for i in range(class_count)
        ]
        for depth in range(levels)
    ]
    cursor = _FakeCursor([classes, *level_rows, []])
    assert db.copy_classes_from_version_for_merge(cursor, "src-version", "tgt-version") == class_count
    return cursor


def test_the_copy_binds_ids_only_never_property_data() -> None:
    cursor = _copy(class_count=1, levels=1)
    property_inserts = [params for query, params in cursor.executed if "INSERT INTO apiome.class_properties" in query]
    assert property_inserts, "expected a class_properties INSERT during the copy"
    for params in property_inserts:
        for bound in params:
            assert isinstance(bound, list) and all(isinstance(value, str) for value in bound)
    # The top-level copy pairs each source class with its copy.
    assert property_inserts[0] == (["src-class-0"], ["new-class-0"])
    # The next level is addressed by the old id -> new id map of the level above.
    assert property_inserts[1] == (["old-0-0"], ["new-0-0"], ["new-class-0"])


def test_the_statement_count_follows_nesting_depth_not_class_count() -> None:
    assert len(_copy(class_count=2, levels=1).executed) == len(_copy(class_count=300, levels=1).executed) == 3
    assert len(_copy(class_count=2, levels=3).executed) == len(_copy(class_count=300, levels=3).executed) == 5


def test_a_version_with_no_classes_copies_nothing() -> None:
    cursor = _FakeCursor([[]])
    assert db.copy_classes_from_version_for_merge(cursor, "src-version", "tgt-version") == 0
    assert len(cursor.executed) == 1
