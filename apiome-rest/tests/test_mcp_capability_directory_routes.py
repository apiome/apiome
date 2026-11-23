"""API tests for the capability directory (V2-MCP-35.4 / MCAT-21.4, #4663)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.models import mcp_capability_directory_response_from_rows

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}


def _directory_row(**overrides):
    row = {
        "kind": "tool",
        "item_id": "item-1",
        "item_name": "geocode",
        "item_title": "Geocode",
        "description": "Convert an address to coordinates",
        "ordinal": 0,
        "endpoint_id": "ep-1",
        "endpoint_name": "Acme Geo",
        "endpoint_slug": "acme-geo",
        "endpoint_url": "https://mcp.acme.example/sse",
        "category": "geo",
        "visibility": "private",
        "current_version_id": "ver-1",
        "score": 90,
        "grade": "A",
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_mcp_capability_directory_response_from_rows_projects_owner_links():
    wire = mcp_capability_directory_response_from_rows(
        rows=[_directory_row()],
        total=1,
        limit=50,
        offset=0,
    )
    assert wire.total == 1
    assert wire.count == 1
    item = wire.items[0]
    assert item.endpoint_id == "ep-1"
    assert item.endpoint_slug == "acme-geo"
    assert item.host == "mcp.acme.example"
    assert item.item_name == "geocode"


@patch("app.mcp_catalog_routes.db")
def test_list_capability_directory_returns_items(mdb):
    mdb.list_mcp_capability_directory.return_value = ([_directory_row()], 1)
    r = client.get("/v1/mcp/acme/capabilities", params={"include_total": "true"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["endpoint_slug"] == "acme-geo"
    mdb.list_mcp_capability_directory.assert_called_once()
    _, kwargs = mdb.list_mcp_capability_directory.call_args
    assert kwargs["name_pattern"] is None
    # One row past the page: `has_more` without a count (#7196).
    assert kwargs["limit"] == 51
    assert kwargs["include_total"] is True


@patch("app.mcp_catalog_routes.db")
def test_list_capability_directory_passes_filters(mdb):
    mdb.list_mcp_capability_directory.return_value = ([], 0)
    r = client.get(
        "/v1/mcp/acme/capabilities",
        params={
            "name": "geo",
            "type": "tool",
            "endpoint_id": "ep-1",
            "host": "mcp.acme.example",
            "visibility": "private",
            "sort": "name",
            "direction": "desc",
            "limit": 10,
            "offset": 5,
        },
    )
    assert r.status_code == 200
    _, kwargs = mdb.list_mcp_capability_directory.call_args
    assert kwargs["name_pattern"] == "geo"
    assert kwargs["item_type"] == "tool"
    assert kwargs["endpoint_id"] == "ep-1"
    assert kwargs["host"] == "mcp.acme.example"
    assert kwargs["visibility"] == "private"
    assert kwargs["sort"] == "name"
    assert kwargs["direction"] == "desc"
    assert kwargs["limit"] == 11
    assert kwargs["offset"] == 5


@patch("app.mcp_catalog_routes.db")
def test_list_capability_directory_scopes_by_token_tenant(mdb):
    mdb.list_mcp_capability_directory.return_value = ([], 0)
    client.get("/v1/mcp/other/capabilities")
    args, _ = mdb.list_mcp_capability_directory.call_args
    assert args[0] == "t1"


@patch("app.mcp_catalog_routes.db")
def test_list_capability_directory_empty_page(mdb):
    mdb.list_mcp_capability_directory.return_value = ([], 0)
    r = client.get("/v1/mcp/acme/capabilities", params={"name": "zzz", "include_total": "true"})
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_list_capability_directory_invalid_sort():
    r = client.get("/v1/mcp/acme/capabilities", params={"sort": "bogus"})
    assert r.status_code == 422


def test_list_capability_directory_invalid_direction():
    r = client.get("/v1/mcp/acme/capabilities", params={"direction": "sideways"})
    assert r.status_code == 422


@patch("app.mcp_catalog_routes.db")
def test_list_capability_directory_defaults_direction_asc(mdb):
    mdb.list_mcp_capability_directory.return_value = ([], 0)
    client.get("/v1/mcp/acme/capabilities")
    _, kwargs = mdb.list_mcp_capability_directory.call_args
    assert kwargs["direction"] == "asc"


# --- Keyset paging (#7196) ---------------------------------------------------

_URL = "/v1/mcp/acme/capabilities"


def _directory_of(rows):
    """A DAO stand-in ordering ``rows`` like ``sort=name`` and honouring the decoded cursor."""

    def key(row):
        return [row["item_name"], row["kind"], row["endpoint_name"], row["item_id"]]

    ordered = sorted(rows, key=key)

    def dao(_tenant, *, limit=50, offset=0, cursor=None, include_total=True, **_):
        matching = [row for row in ordered if cursor is None or key(row) > list(cursor)]
        offset = 0 if cursor is not None else offset
        return matching[offset : offset + limit], (len(ordered) if include_total else None)

    return dao


def _capabilities(count):
    return [
        _directory_row(
            item_id=f"990e8400-e29b-41d4-a716-{index:012d}", item_name=f"tool-{index // 2}"
        )
        for index in range(count)
    ]


@patch("app.mcp_catalog_routes.db")
def test_list_capability_directory_pages_by_cursor_to_the_end(mdb):
    from tests.keyset_paging_fakes import walk

    mdb.list_mcp_capability_directory.side_effect = _directory_of(_capabilities(5))
    seen = walk(lambda params: client.get(_URL, params={"sort": "name", **params}), "items")
    ids = [item["item_id"] for item in seen]
    assert len(ids) == len(set(ids)) == 5
    assert ids == sorted(ids)


@patch("app.mcp_catalog_routes.db")
def test_list_capability_directory_total_is_not_counted_unless_asked(mdb):
    mdb.list_mcp_capability_directory.side_effect = _directory_of(_capabilities(1))
    body = client.get(_URL).json()
    assert mdb.list_mcp_capability_directory.call_args.kwargs["include_total"] is False
    assert body["total"] is None and body["count"] == 1
    assert body["has_more"] is False and body["next_cursor"] is None


@patch("app.mcp_catalog_routes.db")
def test_list_capability_directory_refuses_a_bad_or_foreign_cursor(mdb):
    from app.keyset_columns import encode_columns_cursor
    from app.mcp_facets import capability_directory_sort_columns

    mdb.list_mcp_capability_directory.side_effect = _directory_of(_capabilities(1))
    assert client.get(_URL, params={"cursor": "not-a-cursor"}).status_code == 400
    # A cursor issued under sort=name cannot continue the default sort=server listing.
    token = encode_columns_cursor(
        "name:asc", capability_directory_sort_columns("name", "asc"), _capabilities(1)[0]
    )
    assert client.get(_URL, params={"cursor": token}).status_code == 400
    assert client.get(_URL, params={"cursor": token, "sort": "name"}).status_code == 200
    flipped = {"cursor": token, "sort": "name", "direction": "desc"}
    assert client.get(_URL, params=flipped).status_code == 400


def test_list_capability_directory_page_size_and_offset_have_hard_maximums():
    assert client.get(_URL, params={"limit": 201}).status_code == 422
    assert client.get(_URL, params={"offset": 10_001}).status_code == 422


def _directory_sql(**kwargs):
    from app.database import Database

    database = Database.__new__(Database)
    calls = []

    def execute_query(sql, params=()):
        calls.append((sql, tuple(params)))
        return [{"total": 3}] if "capped" in sql else []

    with patch.object(Database, "execute_query", side_effect=execute_query):
        result = database.list_mcp_capability_directory("t1", **kwargs)
    return calls, result


def test_directory_sql_orders_totally_and_counts_up_to_the_cap():
    calls, (_rows, total) = _directory_sql(sort="server", direction="desc")
    count_sql, page_sql = calls[0][0], calls[1][0]
    assert "LIMIT 10000" in count_sql and total == 3
    assert "ORDER BY e.name DESC, e.id ASC, ci.ordinal ASC, ci.id ASC" in page_sql


def test_directory_sql_continues_after_a_cursor_without_counting():
    item = "990e8400-e29b-41d4-a716-000000000001"
    calls, (_rows, total) = _directory_sql(
        sort="name", direction="desc", offset=40, include_total=False,
        cursor=["geocode", "tool", "Acme Geo", item],
    )
    assert total is None and len(calls) == 1
    sql, params = calls[0]
    assert "(ci.name < %s)" in sql
    assert "ci.name = %s AND ci.item_type > %s" in sql
    assert "ci.name = %s AND ci.item_type = %s AND e.name = %s AND ci.id > %s::uuid" in sql
    assert "ORDER BY ci.name DESC, ci.item_type ASC, e.name ASC, ci.id ASC" in sql
    assert sql.count("%s") == len(params)
    assert params[-2:] == (50, 0)
