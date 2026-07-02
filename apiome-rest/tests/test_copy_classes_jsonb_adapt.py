"""Regression: copying class properties must JSON-wrap the JSONB ``data`` column.

``copy_classes_from_version_for_merge`` (used when cutting/pushing a new version with
``source_version_id``) reads each property's ``data`` JSONB back as a Python ``dict`` and
re-inserts it. Passing the bare ``dict`` as a bind parameter makes psycopg2 raise
``can't adapt type 'dict'`` and the whole version-cut transaction 500s. The copy must wrap
the value with ``psycopg2.extras.Json`` (and preserve SQL NULL for properties with no data).

Surfaced by the end-to-end golden-path smoke test (scripts/golden_path/, #3608).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from psycopg2.extras import Json

from app.database import db


class _FakeCursor:
    """Cursor stub that replays queued results and records every executed statement."""

    def __init__(self, fetchall_queue: List[List[Dict[str, Any]]], fetchone_queue: List[Optional[Dict[str, Any]]]):
        self._fetchall = list(fetchall_queue)
        self._fetchone = list(fetchone_queue)
        self.executed: List[tuple[str, Any]] = []

    def execute(self, query: str, params: Any = None) -> None:
        self.executed.append((query, params))

    def fetchall(self) -> List[Dict[str, Any]]:
        return self._fetchall.pop(0)

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self._fetchone.pop(0)


def test_copy_classes_wraps_jsonb_data_with_json_adapter() -> None:
    # One class ("Pet") with one property whose ``data`` is a JSONB object (a dict).
    fetchall_queue = [
        [{"id": "new-class-1", "name": "Pet"}],  # INSERT ... classes ... RETURNING id, name
        [  # SELECT properties for the source class
            {
                "id": "src-prop-1",
                "property_id": "prop-def-1",
                "name": "id",
                "description": "Unique id.",
                "data": {"type": "string"},  # JSONB read back as a dict
                "parent_id": None,
                "primitive_id": None,
                "primitive_ref": None,
            }
        ],
    ]
    fetchone_queue = [
        {"id": "src-class-1"},  # SELECT id FROM classes WHERE name = 'Pet'
        {"id": "new-prop-1"},   # INSERT ... class_properties ... RETURNING id
    ]
    cursor = _FakeCursor(fetchall_queue, fetchone_queue)

    copied = db.copy_classes_from_version_for_merge(cursor, "src-version", "tgt-version")

    assert copied == 1
    property_inserts = [
        params for query, params in cursor.executed if "INSERT INTO apiome.class_properties" in query
    ]
    assert property_inserts, "expected a class_properties INSERT during the copy"
    data_param = property_inserts[0][4]  # 5th positional bind = the JSONB ``data`` column
    assert isinstance(data_param, Json), "JSONB data must be wrapped with psycopg2 Json(), not a bare dict"
    assert not isinstance(data_param, dict)


def test_copy_classes_preserves_sql_null_for_missing_data() -> None:
    # A property with ``data`` = None must copy across as SQL NULL, not JSON ``null``.
    fetchall_queue = [
        [{"id": "new-class-1", "name": "Error"}],
        [
            {
                "id": "src-prop-1",
                "property_id": "prop-def-1",
                "name": "code",
                "description": None,
                "data": None,
                "parent_id": None,
                "primitive_id": None,
                "primitive_ref": None,
            }
        ],
    ]
    fetchone_queue = [{"id": "src-class-1"}, {"id": "new-prop-1"}]
    cursor = _FakeCursor(fetchall_queue, fetchone_queue)

    db.copy_classes_from_version_for_merge(cursor, "src-version", "tgt-version")

    property_inserts = [
        params for query, params in cursor.executed if "INSERT INTO apiome.class_properties" in query
    ]
    assert property_inserts[0][4] is None
