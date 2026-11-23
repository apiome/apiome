"""No list endpoint is unbounded (DBP-1.13, #7196).

Walks ``openapi.json``. Every ``GET`` that answers with a list of rows — a bare JSON array, or an
object carrying an array of objects — must document a maximum page size (a ``limit`` query
parameter with a ``maximum``), or be named in ``openapi_list_bounds_allowlist.json`` with the
reason it cannot grow. A new list endpoint therefore fails here until it pages or is classified;
``python -m tests.openapi_list_ops`` prints what is missing.
"""

from __future__ import annotations

import json

import pytest

from app.keyset_pagination import MAX_OFFSET, MAX_PAGE_LIMIT
from tests.openapi_list_ops import (
    OPENAPI_FILE,
    REASONS,
    ListOperation,
    list_operations,
    load_allowlist,
    unbounded,
)

#: Lists that may return more than :data:`MAX_PAGE_LIMIT` rows a page, and why. Everything else
#: is held to the one hard maximum.
LARGER_PAGES = {
    # One revision's parts: clients read these whole, so most revisions fit in one page.
    "/v1/classes/{tenant_slug}": 1000,
    "/v1/paths/{tenant_slug}/{version_id}": 1000,
}


@pytest.fixture(scope="module")
def spec():
    return json.loads(OPENAPI_FILE.read_text())


@pytest.fixture(scope="module")
def allowlist():
    return load_allowlist()


def test_every_list_operation_has_a_maximum_page_size_or_a_reason(spec, allowlist):
    missing = unbounded(spec, allowlist)
    assert not missing, "list operations with no bounded `limit` and no allowlist entry:\n" + "\n".join(
        f"  {op.shape:8} {op.path}  ({', '.join(op.arrays) or 'array body'})" for op in missing
    )


def test_every_allowlist_entry_gives_a_known_reason(allowlist):
    unknown = {path: reason for path, reason in allowlist.items() if reason not in REASONS}
    assert not unknown, f"allowlist reasons must be one of {sorted(REASONS)}: {unknown}"


def test_the_allowlist_holds_no_stale_or_needless_entry(spec, allowlist):
    operations = {op.path: op for op in list_operations(spec)}
    stale = sorted(path for path in allowlist if path not in operations)
    needless = sorted(
        path for path in allowlist if path in operations and operations[path].limit_maximum is not None
    )
    assert not stale, f"allowlisted paths that are no longer list operations: {stale}"
    assert not needless, f"allowlisted paths that now have a bounded limit: {needless}"


def test_the_converted_lists_share_the_one_hard_maximum(spec):
    """The lists this ticket converted declare the convention's bounds, not their own."""
    by_path = {op.path: op for op in list_operations(spec)}
    for path, expected in {
        "/v1/projects/{tenant_slug}": MAX_PAGE_LIMIT,
        "/v1/versions/{tenant_slug}/{project_id}": MAX_PAGE_LIMIT,
        "/v1/catalog/{tenant_slug}": MAX_PAGE_LIMIT,
        "/v1/mocks/{tenant_slug}": MAX_PAGE_LIMIT,
        "/v1/tenants/{tenant_slug}/notifications": MAX_PAGE_LIMIT,
        "/v1/export/{tenant_slug}/runs": MAX_PAGE_LIMIT,
        "/v1/versions/{tenant_slug}/workflow-audit": MAX_PAGE_LIMIT,
        **LARGER_PAGES,
    }.items():
        assert by_path[path].limit_maximum == expected, path


def test_every_cursor_list_documents_the_cursor_and_caps_a_deprecated_offset(spec):
    for path, item in spec["paths"].items():
        parameters = {p["name"]: p for p in item.get("get", {}).get("parameters", []) if "name" in p}
        if "cursor" not in parameters:
            continue
        assert "limit" in parameters, f"{path}: a cursor list needs a limit"
        offset = parameters.get("offset")
        if offset is not None and offset.get("deprecated"):
            assert offset["schema"].get("maximum") == MAX_OFFSET, path


def test_the_finder_recognises_both_list_shapes():
    spec = {
        "components": {
            "schemas": {
                "Row": {"type": "object", "properties": {"id": {"type": "string"}}},
                "Page": {
                    "type": "object",
                    "properties": {
                        "items": {"type": "array", "items": {"$ref": "#/components/schemas/Row"}},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "Detail": {"type": "object", "properties": {"tags": {"type": "array", "items": {"type": "string"}}}},
            }
        },
        "paths": {
            "/rows": {
                "get": {
                    "parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer", "maximum": 200}}],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"type": "array", "items": {"$ref": "#/components/schemas/Row"}}
                                }
                            }
                        }
                    },
                }
            },
            "/pages": {
                "get": {
                    "responses": {
                        "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Page"}}}}
                    }
                }
            },
            "/detail": {
                "get": {
                    "responses": {
                        "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Detail"}}}}
                    }
                }
            },
            "/write": {"post": {"responses": {"200": {}}}},
        },
    }
    assert list(list_operations(spec)) == [
        ListOperation("/rows", "array", [], 200),
        ListOperation("/pages", "envelope", ["items"], None),
    ]
    assert [op.path for op in unbounded(spec, {})] == ["/pages"]
    assert unbounded(spec, {"/pages": "fixed-catalog"}) == []
