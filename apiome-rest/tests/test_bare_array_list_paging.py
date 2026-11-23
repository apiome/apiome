"""Bare-array lists page by ``limit`` + ``cursor`` and report it in headers (DBP-1.13, #7196).

Projects, versions, catalog items, mocks, classes and paths keep their JSON-array body. Each reads
one row more than the page, cuts it, and says in ``X-Has-More`` / ``X-Next-Cursor`` whether and
where the list continues. The SQL side is checked against a scripted connection: a later page is a
row-value comparison on the list's sort key with a ``LIMIT``, never an ``OFFSET``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.catalog_categories import CatalogFacetFilters
from app.keyset_pagination import (
    HAS_MORE_HEADER,
    NEXT_CURSOR_HEADER,
    decode_key_cursor,
    decode_time_id_cursor,
    encode_key_cursor,
    encode_time_id_cursor,
)
from app.main import app
from app.project_list_paging import project_keyset_sql, project_row_cursor
from tests.scripted_connection import ScriptedConnection, database_with
from tests.test_catalog_routes import _CATALOG_ACTIVE
from tests.test_mock_routes import _instance_row

client = TestClient(app)
TENANT = "11111111-1111-4111-8111-111111111111"
T0 = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)
_AUTH = {"tenant_id": TENANT, "user_id": "u1", "auth_method": "jwt", "permissions": ["*"]}


def _uuid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


@pytest.fixture(autouse=True)
def _signed_in():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _class_rows(count: int) -> List[Dict[str, Any]]:
    return [
        {
            "id": _uuid(n),
            "version_id": "v1",
            "name": f"Class{n:03d}",
            "description": None,
            "schema": {},
            "project_name": "Orders",
            "version_label": "1.0.0",
        }
        for n in range(count)
    ]


def _path_rows(count: int) -> List[Dict[str, Any]]:
    return [{"id": _uuid(n), "version_id": "v1", "pathname": f"/p{n:03d}"} for n in range(count)]


def _catalog_rows(count: int) -> List[Dict[str, Any]]:
    return [
        {
            **_CATALOG_ACTIVE,
            "id": _uuid(n),
            "slug": f"item-{n}",
            "created_at": T0 - timedelta(minutes=n),
            "deleted_at": None,
        }
        for n in range(count)
    ]


def _mock_rows(count: int) -> List[Dict[str, Any]]:
    return [
        _instance_row(id=_uuid(n), created_at=T0 - timedelta(minutes=n), operation_count=4, spec=None)
        for n in range(count)
    ]


# --- routes ----------------------------------------------------------------------------------


def test_a_page_of_classes_says_where_the_list_continues():
    with patch("app.classes_routes.db") as db:
        db.get_version_for_tenant.return_value = {"id": "v1"}
        db.get_classes_for_tenant_version.return_value = _class_rows(3)
        response = client.get("/v1/classes/acme", params={"version_id": "v1", "limit": 2})
    assert [row["name"] for row in response.json()] == ["Class000", "Class001"]
    assert response.headers[HAS_MORE_HEADER] == "true"
    assert decode_key_cursor(response.headers[NEXT_CURSOR_HEADER], 2) == ["Class001", _uuid(1)]
    assert db.get_classes_for_tenant_version.call_args.kwargs["limit"] == 3


def test_the_next_page_of_classes_starts_after_the_cursor():
    cursor = encode_key_cursor(["Class001", _uuid(1)])
    with patch("app.classes_routes.db") as db:
        db.get_version_for_tenant.return_value = {"id": "v1"}
        db.get_classes_for_tenant_version.return_value = _class_rows(3)[2:]
        response = client.get(
            "/v1/classes/acme", params={"version_id": "v1", "limit": 2, "cursor": cursor}
        )
    assert db.get_classes_for_tenant_version.call_args.kwargs["cursor"] == ["Class001", _uuid(1)]
    assert response.headers[HAS_MORE_HEADER] == "false"
    assert NEXT_CURSOR_HEADER not in response.headers


def test_the_tenant_wide_class_list_pages_on_its_five_part_key():
    with patch("app.classes_routes.db") as db:
        db.get_classes_for_tenant.return_value = _class_rows(2)
        response = client.get("/v1/classes/acme", params={"limit": 1})
    assert decode_key_cursor(response.headers[NEXT_CURSOR_HEADER], 5) == [
        "Orders",
        "1.0.0",
        "v1",
        "Class000",
        _uuid(0),
    ]
    assert "project_name" not in response.json()[0]


def test_a_class_cursor_from_the_other_list_is_a_400():
    version_cursor = encode_key_cursor(["Class001", _uuid(1)])
    with patch("app.classes_routes.db"):
        assert client.get("/v1/classes/acme", params={"cursor": version_cursor}).status_code == 400


def test_revision_lists_allow_a_thousand_rows_and_no_more():
    with patch("app.classes_routes.db") as db, patch("app.paths_routes.db") as paths_db:
        db.get_classes_for_tenant.return_value = []
        paths_db.get_version_for_tenant.return_value = {"id": "v1"}
        paths_db.get_paths_for_version_with_tenant.return_value = []
        assert client.get("/v1/classes/acme", params={"limit": 1000}).status_code == 200
        assert client.get("/v1/classes/acme", params={"limit": 1001}).status_code == 422
        assert client.get("/v1/paths/acme/v1", params={"limit": 1001}).status_code == 422
        assert client.get("/v1/paths/acme/v1").status_code == 200
    assert paths_db.get_paths_for_version_with_tenant.call_args.kwargs["limit"] == 1001


def test_a_page_of_paths_says_where_the_list_continues():
    with patch("app.paths_routes.db") as db:
        db.get_version_for_tenant.return_value = {"id": "v1"}
        db.get_paths_for_version_with_tenant.return_value = _path_rows(3)
        response = client.get("/v1/paths/acme/v1", params={"limit": 2})
    assert [row["pathname"] for row in response.json()] == ["/p000", "/p001"]
    assert decode_key_cursor(response.headers[NEXT_CURSOR_HEADER], 2) == ["/p001", _uuid(1)]


def test_a_page_of_mocks_carries_the_sql_counted_operations_and_a_cursor():
    with patch("app.mock_routes.db") as db:
        db.list_mock_instances.return_value = _mock_rows(3)
        response = client.get("/v1/mocks/acme", params={"limit": 2})
    assert response.status_code == 200, response.text
    assert [row["operationCount"] for row in response.json()] == [4, 4]
    assert db.list_mock_instances.call_args.kwargs == {"summary": True, "limit": 3, "cursor": None}
    assert decode_time_id_cursor(response.headers[NEXT_CURSOR_HEADER]) == (
        T0 - timedelta(minutes=1),
        _uuid(1),
    )


def test_tenant_lists_allow_two_hundred_rows_and_no_more():
    with patch("app.mock_routes.db") as db:
        db.list_mock_instances.return_value = []
        assert client.get("/v1/mocks/acme", params={"limit": 200}).status_code == 200
        assert client.get("/v1/mocks/acme", params={"limit": 201}).status_code == 422
        assert client.get("/v1/mocks/acme", params={"cursor": "junk"}).status_code == 400


def test_a_page_of_projects_says_where_the_list_continues():
    from tests.test_owner_envelopes import _project_row

    rows = [
        {**_project_row(), "id": _uuid(n), "created_at": T0 - timedelta(minutes=n), "deleted_at": None}
        for n in range(3)
    ]
    with patch("app.projects_routes.db.get_projects_for_tenant", return_value=rows) as listed:
        response = client.get("/v1/projects/acme", params={"limit": 2})
    assert response.status_code == 200, response.text
    assert len(response.json()) == 2
    assert listed.call_args.kwargs["limit"] == 3 and listed.call_args.kwargs["cursor"] is None
    assert response.headers[HAS_MORE_HEADER] == "true"
    assert decode_key_cursor(response.headers[NEXT_CURSOR_HEADER], 3) == [
        True,
        (T0 - timedelta(minutes=1)).isoformat(),
        _uuid(1),
    ]


def test_the_default_project_page_is_the_hard_maximum():
    with patch("app.projects_routes.db.get_projects_for_tenant", return_value=[]) as listed:
        response = client.get("/v1/projects/acme")
        assert client.get("/v1/projects/acme", params={"limit": 201}).status_code == 422
    assert listed.call_args_list[0].kwargs["limit"] == 201
    assert response.headers[HAS_MORE_HEADER] == "false"


def test_an_unfiltered_catalog_page_is_one_read_of_limit_plus_one():
    with patch("app.catalog_routes.db") as db, patch("app.catalog_routes.drift_badges", return_value={}):
        db.get_catalog_items_for_tenant.return_value = _catalog_rows(3)
        db.get_artifact_tags_for_projects.return_value = {}
        response = client.get("/v1/catalog/acme", params={"limit": 2})
    assert response.status_code == 200, response.text
    assert [row["slug"] for row in response.json()] == ["item-0", "item-1"]
    assert db.get_catalog_items_for_tenant.call_count == 1
    assert db.get_catalog_items_for_tenant.call_args.kwargs["limit"] == 3
    assert response.headers[HAS_MORE_HEADER] == "true"
    assert response.headers[NEXT_CURSOR_HEADER] == project_row_cursor(_catalog_rows(2)[1])


def test_a_filtered_catalog_page_keeps_reading_until_it_is_full():
    from app import catalog_routes

    rows = _catalog_rows(5)
    batches = [rows[:3], rows[3:]]
    calls: List[Any] = []

    def read(_tenant, **kwargs):
        calls.append(kwargs["cursor"])
        return batches[len(calls) - 1]

    keep = {_uuid(1), _uuid(3), _uuid(4)}
    with (
        patch.object(catalog_routes, "_CATALOG_SCAN_BATCH", 3),
        patch("app.catalog_routes.db") as db,
        patch(
            "app.catalog_routes.filter_catalog_items",
            side_effect=lambda items, _tags, _filters: [i for i in items if i["id"] in keep],
        ),
    ):
        db.get_catalog_items_for_tenant.side_effect = read
        db.get_artifact_tags_for_projects.return_value = {}
        page, _tags = catalog_routes._catalog_page(
            TENANT,
            include_deleted=False,
            identity_group_id=None,
            team=None,
            filters=CatalogFacetFilters(protocols=["rest"]),
            limit=2,
            cursor=None,
        )
    # The first batch of three keeps one item, so a second batch is read to fill the page.
    assert [item["id"] for item in page.items] == [_uuid(1), _uuid(3)]
    assert page.has_more is True
    assert page.next_cursor == project_row_cursor(rows[3])
    # The second batch continues after the last row *read*, kept or not.
    assert calls == [None, [True, rows[2]["created_at"], rows[2]["id"]]]


# --- SQL -------------------------------------------------------------------------------------


def _sql(monkeypatch, call) -> tuple[str, tuple]:
    conn = ScriptedConnection([[]])
    call(database_with(monkeypatch, conn))
    assert len(conn.statements) == 1
    return conn.statements[0]


def test_an_unpaged_internal_read_has_no_limit(monkeypatch):
    for call in (
        lambda db: db.get_projects_for_tenant(TENANT),
        lambda db: db.get_catalog_items_for_tenant(TENANT),
        lambda db: db.get_versions_for_project(_uuid(1), TENANT),
        lambda db: db.get_classes_for_tenant_version(TENANT, "v1"),
        lambda db: db.get_classes_for_tenant(TENANT),
        lambda db: db.get_paths_for_version_with_tenant("v1", TENANT),
        lambda db: db.list_mock_instances(TENANT),
    ):
        sql, _ = _sql(monkeypatch, call)
        assert "LIMIT %s" not in sql and "OFFSET" not in sql


def test_a_project_page_seeks_past_the_cursor_on_created_at_and_id(monkeypatch):
    sql, params = _sql(
        monkeypatch,
        lambda db: db.get_projects_for_tenant(TENANT, limit=51, cursor=[True, T0, _uuid(7)]),
    )
    assert "AND (p.created_at, p.id) < (%s, %s::uuid)" in sql
    assert sql.endswith("ORDER BY p.created_at DESC, p.id DESC LIMIT %s")
    assert params[-3:] == (T0, _uuid(7), 51)


def test_a_project_page_with_deleted_rows_keeps_live_rows_first(monkeypatch):
    sql, params = _sql(
        monkeypatch,
        lambda db: db.get_catalog_items_for_tenant(
            TENANT, include_deleted=True, limit=51, cursor=[False, T0, _uuid(7)]
        ),
    )
    assert "((p.deleted_at IS NULL), p.created_at, p.id) < (%s, %s, %s::uuid)" in sql
    assert "ORDER BY (p.deleted_at IS NULL) DESC, p.created_at DESC, p.id DESC LIMIT %s" in sql
    assert params[-4:] == (False, T0, _uuid(7), 51)


def test_the_project_keyset_has_no_predicate_or_limit_when_unpaged():
    order, after, after_params, limit, limit_params = project_keyset_sql(False, None, None)
    assert order == "ORDER BY p.created_at DESC, p.id DESC"
    assert (after, after_params, limit, limit_params) == ("", [], "", [])


def test_a_version_page_uses_the_project_created_index_order(monkeypatch):
    sql, params = _sql(
        monkeypatch,
        lambda db: db.get_versions_for_project(_uuid(1), TENANT, limit=201, cursor=(T0, _uuid(9))),
    )
    assert "AND (v.created_at, v.id) < (%s, %s::uuid)" in sql
    assert sql.endswith("ORDER BY v.created_at DESC NULLS LAST, v.id DESC LIMIT %s")
    assert params[-3:] == (T0, _uuid(9), 201)


def test_class_and_path_pages_seek_forward_by_name(monkeypatch):
    sql, params = _sql(
        monkeypatch,
        lambda db: db.get_classes_for_tenant_version(
            TENANT, "v1", limit=1001, cursor=["Order", _uuid(3)]
        ),
    )
    assert "AND (c.name, c.id) > (%s, %s::uuid)" in sql
    assert sql.endswith("ORDER BY c.name ASC, c.id ASC LIMIT %s")
    assert params == ("v1", TENANT, "Order", _uuid(3), 1001)

    sql, params = _sql(
        monkeypatch,
        lambda db: db.get_classes_for_tenant(
            TENANT, limit=1001, cursor=["Orders", "1.0.0", _uuid(2), "Order", _uuid(3)]
        ),
    )
    assert (
        "(p.name, v.version_id, v.id, c.name, c.id) > (%s, %s, %s::uuid, %s, %s::uuid)" in sql
    )
    assert sql.endswith("ORDER BY p.name, v.version_id, v.id, c.name, c.id LIMIT %s")

    sql, params = _sql(
        monkeypatch,
        lambda db: db.get_paths_for_version_with_tenant(
            "v1", TENANT, limit=1001, cursor=["/orders", _uuid(3)]
        ),
    )
    assert "AND (vp.pathname, vp.id) > (%s, %s::uuid)" in sql
    assert params == ("v1", TENANT, "/orders", _uuid(3), 1001)


def test_the_mock_list_summary_leaves_the_spec_out_and_counts_operations_in_sql(monkeypatch):
    sql, params = _sql(
        monkeypatch,
        lambda db: db.list_mock_instances(TENANT, summary=True, limit=201, cursor=(T0, _uuid(5))),
    )
    assert "CASE WHEN settings IS NULL THEN spec END AS spec" in sql
    assert ") AS operation_count" in sql
    assert "(created_at, id) < (%s, %s::uuid)" in sql
    assert sql.endswith("ORDER BY created_at DESC, id DESC LIMIT %s")
    assert "get" in params[0] and params[1:] == (TENANT, T0, _uuid(5), 201)


def test_the_export_test_drive_reads_only_its_own_mock_rows(monkeypatch):
    sql, params = _sql(
        monkeypatch, lambda db: db.list_mock_instances(TENANT, origin="export-test-drive")
    )
    assert "config->>'origin' = %s" in sql
    assert params == (TENANT, "export-test-drive")


def test_time_cursors_survive_the_round_trip_the_routes_make():
    stamp = T0.replace(microsecond=123456)
    assert decode_time_id_cursor(encode_time_id_cursor(stamp, _uuid(1))) == (stamp, _uuid(1))
