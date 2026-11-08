"""DCW-2.4 (private-suite#2365) — source provenance: element statuses, the source locator, excerpts."""

from __future__ import annotations

from pathlib import Path

from app.source_provenance import (
    EXCERPT_MAX_LINES,
    classify_elements,
    element_pointers,
    excerpt,
    locate_pointer,
)

YAML = """openapi: 3.1.0
info:
  title: Pets
paths:
  /pets:
    get:
      summary: List
      responses:
        '200':
          description: ok
    post:
      summary: Create
components:
  schemas:
    Pet:
      type: object
      description: |
        A pet.
        Two lines.
"""

JSON = (
    '{\n  "paths": {\n    "/pets": {\n      "get": {\n        "summary": "x"\n      },\n'
    '      "post": {}\n    }\n  }\n}\n'
)

IMPORTED = {
    "openapi": "3.1.0",
    "paths": {"/pets": {"get": {"summary": "List"}, "post": {"summary": "Create"}}},
    "components": {"schemas": {"Pet": {"type": "object"}, "Owner": {"type": "object"}}},
}


def _status(rows, pointer):
    return next(r.status for r in rows if r.pointer == pointer)


def test_element_pointers_lists_paths_operations_and_components():
    assert element_pointers(IMPORTED) == [
        ("/paths/~1pets", "path"),
        ("/paths/~1pets/get", "operation"),
        ("/paths/~1pets/post", "operation"),
        ("/components/schemas/Owner", "component"),
        ("/components/schemas/Pet", "component"),
    ]


def test_an_unchanged_element_is_imported():
    rows = classify_elements(IMPORTED, IMPORTED, [])
    assert {r.status for r in rows} == {"imported"}
    assert all(r.in_import for r in rows)


def test_an_element_changed_outside_the_source_workspace_is_local():
    current = {**IMPORTED, "paths": {"/pets": {"get": {"summary": "List all"}, "post": {"summary": "Create"}}}}
    rows = classify_elements(current, IMPORTED, [])
    assert _status(rows, "/paths/~1pets/get") == "local"
    assert _status(rows, "/paths/~1pets/post") == "imported"
    # The path contains the changed operation, so it changed too.
    assert _status(rows, "/paths/~1pets") == "local"


def test_a_source_edit_inside_or_around_an_element_marks_it_source_edited():
    current = {**IMPORTED, "paths": {"/pets": {"get": {"summary": "List all"}, "post": {"summary": "Create"}}}}
    rows = classify_elements(current, IMPORTED, ["/paths/~1pets/get/summary"])
    assert _status(rows, "/paths/~1pets/get") == "source-edited"
    assert _status(rows, "/paths/~1pets") == "source-edited"
    # A source edit that replaced a whole path reaches its operations.
    rows = classify_elements(current, IMPORTED, ["/paths/~1pets"])
    assert _status(rows, "/paths/~1pets/get") == "source-edited"


def test_an_element_created_in_apiome_is_local_and_not_in_the_import():
    current = {**IMPORTED, "paths": {**IMPORTED["paths"], "/owners": {"get": {}}}}
    rows = classify_elements(current, IMPORTED, [])
    created = next(r for r in rows if r.pointer == "/paths/~1owners/get")
    assert (created.status, created.in_import) == ("local", False)


def test_an_element_a_source_apply_created_is_source_edited():
    current = {**IMPORTED, "paths": {**IMPORTED["paths"], "/owners": {"get": {}}}}
    rows = classify_elements(current, IMPORTED, ["/paths/~1owners"])
    assert _status(rows, "/paths/~1owners/get") == "source-edited"


def test_an_unchanged_element_stays_imported_even_beside_source_edits():
    rows = classify_elements(IMPORTED, IMPORTED, ["/paths/~1pets/get"])
    assert _status(rows, "/paths/~1pets/get") == "imported"


def test_without_a_snapshot_everything_is_local():
    rows = classify_elements(IMPORTED, None, [])
    assert {r.status for r in rows} == {"local"}
    assert not any(r.in_import for r in rows)


def test_locate_pointer_spans_yaml_blocks_without_the_next_sibling():
    assert locate_pointer(YAML, "/paths/~1pets/get") == (6, 10)
    assert locate_pointer(YAML, "/paths/~1pets/post") == (11, 12)
    assert locate_pointer(YAML, "/paths/~1pets") == (5, 12)
    assert locate_pointer(YAML, "/info/title") == (3, 3)


def test_locate_pointer_includes_block_scalars():
    assert locate_pointer(YAML, "/components/schemas/Pet") == (15, 19)
    assert locate_pointer(YAML, "/components/schemas/Pet/description") == (17, 19)


def test_locate_pointer_reads_json():
    assert locate_pointer(JSON, "/paths/~1pets/get") == (4, 6)
    assert locate_pointer(JSON, "/paths/~1pets/post") == (7, 7)


def test_locate_pointer_returns_none_for_a_missing_pointer_or_unparseable_text():
    assert locate_pointer(YAML, "/paths/~1owners") is None
    assert locate_pointer("key: [unclosed", "/key") is None
    assert locate_pointer("", "/x") is None


def test_excerpt_quotes_the_lines_and_cuts_long_values():
    quoted = excerpt(YAML, "/paths/~1pets/post")
    assert quoted == {"startLine": 11, "endLine": 12, "text": "    post:\n      summary: Create", "truncated": False}
    long_yaml = "paths:\n  /a:\n    get:\n" + "".join(f"      x{i}: {i}\n" for i in range(EXCERPT_MAX_LINES + 10))
    cut = excerpt(long_yaml, "/paths/~1a/get")
    assert cut["truncated"] is True
    assert cut["endLine"] - cut["startLine"] + 1 == EXCERPT_MAX_LINES


def test_the_migration_creates_both_tables_scoped_to_tenant_and_version():
    sql = (
        Path(__file__).resolve().parents[2] / "apiome-db" / "scripts" / "V362__source_provenance_2365.sql"
    ).read_text()
    for table in ("version_import_snapshots", "version_source_edits"):
        assert f"CREATE TABLE IF NOT EXISTS apiome.{table}" in sql
    assert "REFERENCES apiome.versions(id) ON DELETE CASCADE" in sql
    assert "REFERENCES apiome.source_change_audit(id)" in sql
    assert "UNIQUE (version_id)" in sql
