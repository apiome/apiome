"""The set-based source-apply writer, without a database — DBP-1.7 (#7190).

* :func:`plan_source_apply` keeps exactly the classes, paths, security schemes and servers whose
  rendering does not change;
* :func:`write_canonical_rows` sends the same number of statements for 2 classes and for 300,
  writes nothing for what the plan keeps, and updates a changed class in place.

The rows themselves are checked against PostgreSQL in ``test_set_based_writes_db.py``.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from app.source_apply_writer import SourceApplyPlan, plan_source_apply, write_canonical_rows
from app.source_change_apply import build_canonical_writes
from tests.set_based_fixtures import class_name, class_spec

PROJECT = "11111111-1111-4111-8111-111111111111"
VERSION = "22222222-2222-4222-8222-222222222222"


class FakeCursor:
    """Records every statement; answers the two reads the writer makes."""

    def __init__(self, live_classes: Optional[Dict[str, str]] = None, library: Optional[Dict[str, str]] = None):
        self.live_classes = live_classes or {}
        self.library = library or {}
        self.statements: List[Tuple[str, Any]] = []
        self._rows: List[Dict[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        text = " ".join(str(sql).split())
        self.statements.append((text, params))
        if text.startswith("SELECT id, name FROM apiome.classes"):
            self._rows = [{"id": class_id, "name": name} for name, class_id in self.live_classes.items()]
        elif "FROM apiome.properties p" in text:
            _project, ordinals, data = params
            self._rows = [{"ord": ordinal, "id": self.library.get(value)} for ordinal, value in zip(ordinals, data)]
        else:
            self._rows = []

    def fetchall(self) -> List[Dict[str, Any]]:
        return list(self._rows)

    def writes_to(self, table: str) -> List[Tuple[str, Any]]:
        """The INSERT/UPDATE/DELETE statements naming ``apiome.<table>`` as their target."""
        targets = (f"INSERT INTO apiome.{table} ", f"UPDATE apiome.{table} ", f"DELETE FROM apiome.{table} ")
        return [(sql, params) for sql, params in self.statements if sql.startswith(targets)]


def _canonical(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Stand-in for a rendered document: the plan only compares, it does not care who rendered."""
    return copy.deepcopy(spec)


# ───────────────────────────────── the plan ─────────────────────────────────


def test_identical_documents_keep_everything() -> None:
    spec = class_spec(4)
    plan = plan_source_apply(_canonical(spec), _canonical(spec))
    assert plan.keep_classes == frozenset(class_name(i) for i in range(4))
    assert plan.keep_paths == frozenset(spec["paths"])
    assert plan.write_security_schemes is False
    assert plan.write_servers is False


def test_a_changed_added_or_removed_class_is_not_kept() -> None:
    current = class_spec(4)
    planned = copy.deepcopy(current)
    planned["components"]["schemas"][class_name(1)]["description"] = "Changed"
    planned["components"]["schemas"]["New"] = {"type": "object"}
    del planned["components"]["schemas"][class_name(3)]
    plan = plan_source_apply(current, planned)
    assert plan.keep_classes == frozenset({class_name(0), class_name(2)})
    assert plan.keep_paths == frozenset(current["paths"])


def test_a_changed_path_is_not_kept_and_classes_are() -> None:
    current = class_spec(3)
    planned = copy.deepcopy(current)
    changed = "/things0001/{id}"
    planned["paths"][changed]["get"]["summary"] = "Changed"
    plan = plan_source_apply(current, planned)
    assert plan.keep_paths == frozenset(current["paths"]) - {changed}
    assert len(plan.keep_classes) == 3


def test_security_schemes_and_servers_are_written_only_when_they_differ() -> None:
    current = class_spec(1)
    current["servers"] = [{"url": "https://a.example"}]
    current["components"]["securitySchemes"] = {"key": {"type": "apiKey", "in": "header", "name": "X-Key"}}
    same = plan_source_apply(current, copy.deepcopy(current))
    assert (same.write_security_schemes, same.write_servers) == (False, False)
    planned = copy.deepcopy(current)
    planned["servers"].append({"url": "https://b.example"})
    planned["components"]["securitySchemes"]["key"]["name"] = "X-Api-Key"
    differs = plan_source_apply(current, planned)
    assert (differs.write_security_schemes, differs.write_servers) == (True, True)


def test_an_unreadable_current_document_keeps_nothing() -> None:
    plan = plan_source_apply(None, class_spec(2))
    assert plan.keep_classes == frozenset() and plan.keep_paths == frozenset()
    assert plan.write_servers is True


# ───────────────────────────────── the writer ─────────────────────────────────


def _full_write(classes: int) -> FakeCursor:
    cursor = FakeCursor()
    write_canonical_rows(cursor, PROJECT, VERSION, build_canonical_writes(class_spec(classes)))
    return cursor


def test_a_full_write_sends_the_same_statements_for_2_and_300_classes() -> None:
    small, large = _full_write(2), _full_write(300)
    assert [sql for sql, _ in small.statements] == [sql for sql, _ in large.statements]
    # One statement carries every class; one carries every class property.
    (_sql, class_params), = large.writes_to("classes")[1:]
    assert len(class_params[0]) == 300
    (_sql, property_params), = large.writes_to("class_properties")
    assert len(property_params[0]) == 900


def test_a_full_write_soft_deletes_first_and_assigns_ids_on_the_client() -> None:
    cursor = _full_write(3)
    assert cursor.statements[0][0].startswith("UPDATE apiome.classes SET deleted_at")
    assert not any("RETURNING" in sql for sql, _ in cursor.statements)
    (_sql, class_params), = cursor.writes_to("classes")[1:]
    class_ids = class_params[0]
    assert len(set(class_ids)) == 3
    (_sql, property_params), = cursor.writes_to("class_properties")
    assert set(property_params[0]) == set(class_ids)
    # Response content refers to the classes by the ids just assigned.
    (_sql, content_params), = cursor.writes_to("shared_path_response_content")
    assert {value for value in content_params[2] if value} <= set(class_ids)


def test_reference_properties_have_no_library_link_and_others_share_one() -> None:
    cursor = _full_write(3)
    (_sql, params), = cursor.writes_to("class_properties")
    _class_ids, property_ids, names, _descriptions, _data = params
    by_name: Dict[str, set] = {}
    for name, property_id in zip(names, property_ids):
        by_name.setdefault(name, set()).add(property_id)
    assert by_name["parent"] == {None}
    assert len(by_name["id"]) == 1 and None not in by_name["id"]
    # ``id`` and ``name`` have the same definition, so they are one library property.
    assert by_name["id"] == by_name["name"]
    (_sql, library_params), = cursor.writes_to("properties")
    assert len(library_params[0]) == 1


def test_a_library_match_inserts_no_property() -> None:
    cursor = FakeCursor(library={'{"type": "string"}': "33333333-3333-4333-8333-333333333333"})
    write_canonical_rows(cursor, PROJECT, VERSION, build_canonical_writes(class_spec(2)))
    assert cursor.writes_to("properties") == []
    (_sql, params), = cursor.writes_to("class_properties")
    assert {pid for pid in params[1] if pid} == {"33333333-3333-4333-8333-333333333333"}


def test_a_plan_that_keeps_everything_writes_nothing_but_the_path_sweep() -> None:
    spec = class_spec(5)
    live = {class_name(i): f"00000000-0000-4000-8000-{i:012d}" for i in range(5)}
    cursor = FakeCursor(live_classes=live)
    plan = plan_source_apply(spec, spec)
    write_canonical_rows(cursor, PROJECT, VERSION, build_canonical_writes(spec), plan)
    statements = [sql for sql, _ in cursor.statements]
    assert len(statements) == 2
    assert statements[0].startswith("SELECT id, name FROM apiome.classes")
    # The sweep deletes paths the candidate no longer has; here it names every path as kept.
    assert statements[1].startswith("DELETE FROM apiome.version_path")
    assert cursor.statements[1][1] == (VERSION, sorted(spec["paths"]))


def test_a_changed_class_is_updated_in_place_and_its_properties_replaced() -> None:
    spec = class_spec(5)
    live = {class_name(i): f"00000000-0000-4000-8000-{i:012d}" for i in range(5)}
    planned = copy.deepcopy(spec)
    planned["components"]["schemas"][class_name(2)]["description"] = "Changed"
    cursor = FakeCursor(live_classes=live)
    write_canonical_rows(cursor, PROJECT, VERSION, build_canonical_writes(planned), plan_source_apply(spec, planned))
    class_writes = cursor.writes_to("classes")
    assert len(class_writes) == 1 and class_writes[0][0].startswith("UPDATE apiome.classes c SET description")
    assert class_writes[0][1][0] == [live[class_name(2)]]
    deletes = [params for sql, params in cursor.writes_to("class_properties") if sql.startswith("DELETE")]
    assert deletes == [([live[class_name(2)]],)]
    (_sql, inserted), = [w for w in cursor.writes_to("class_properties") if w[0].startswith("INSERT")]
    assert set(inserted[0]) == {live[class_name(2)]} and len(inserted[0]) == 3
    assert not any(sql.startswith("INSERT INTO apiome.version_path") for sql, _ in cursor.statements)


def test_a_dropped_class_is_soft_deleted_and_a_new_one_inserted() -> None:
    spec = class_spec(3, paths=1)
    live = {class_name(i): f"00000000-0000-4000-8000-{i:012d}" for i in range(3)}
    planned = copy.deepcopy(spec)
    del planned["components"]["schemas"][class_name(2)]
    planned["components"]["schemas"]["Fresh"] = {"type": "object"}
    cursor = FakeCursor(live_classes=live)
    write_canonical_rows(cursor, PROJECT, VERSION, build_canonical_writes(planned), plan_source_apply(spec, planned))
    soft_delete, insert = cursor.writes_to("classes")
    assert soft_delete[0].startswith("UPDATE apiome.classes SET deleted_at") and soft_delete[1] == ([live[class_name(2)]],)
    assert insert[0].startswith("INSERT INTO apiome.classes") and insert[1][2] == ["Fresh"]


def test_a_rewritten_path_refers_to_kept_classes_by_their_existing_ids() -> None:
    spec = class_spec(2, paths=2)
    live = {class_name(i): f"00000000-0000-4000-8000-{i:012d}" for i in range(2)}
    planned = copy.deepcopy(spec)
    planned["paths"]["/things0001/{id}"]["get"]["summary"] = "Changed"
    cursor = FakeCursor(live_classes=live)
    write_canonical_rows(cursor, PROJECT, VERSION, build_canonical_writes(planned), plan_source_apply(spec, planned))
    (_sql, path_params), = [w for w in cursor.writes_to("version_path") if w[0].startswith("INSERT")]
    assert path_params[2] == ["/things0001/{id}"]
    (_sql, content_params), = cursor.writes_to("shared_path_response_content")
    assert {value for value in content_params[2] if value} == {live[class_name(1)]}
    assert cursor.writes_to("classes") == []


def test_security_schemes_and_servers_are_skipped_when_the_plan_says_so() -> None:
    spec = class_spec(1, paths=0)
    plan = SourceApplyPlan(frozenset({class_name(0)}), frozenset(), write_security_schemes=False, write_servers=False)
    cursor = FakeCursor(live_classes={class_name(0): "00000000-0000-4000-8000-000000000000"})
    write_canonical_rows(cursor, PROJECT, VERSION, build_canonical_writes(spec), plan)
    assert cursor.writes_to("version_security_scheme") == [] and cursor.writes_to("version_server") == []
    full = FakeCursor()
    write_canonical_rows(full, PROJECT, VERSION, build_canonical_writes(spec))
    assert len(full.writes_to("version_security_scheme")) == 1 and len(full.writes_to("version_server")) == 1
