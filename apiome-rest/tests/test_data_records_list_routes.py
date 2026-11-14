"""``GET /v1/data/{tenant_slug}/records`` — list a class schema's records (#3253).

The route against a mocked database: filters, sort, ``include_deleted``, the opaque cursor (issued
only while more records remain, refused when malformed or reused for another query), limits,
404s and ``versions:view``; then the SQL :meth:`Database.list_data_records` builds.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.data_routes import _encode_records_cursor, _records_query_signature
from app.main import app

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_URL = "/v1/data/acme/records"
_CS = "33333333-3333-3333-3333-333333333333"
_T0 = datetime(2026, 5, 4, 12, 42, tzinfo=timezone.utc)


def _row(n: int, **extra):
    return {
        "record_id": f"00000000-0000-4000-8000-00000000000{n}",
        "created_at": _T0,
        "updated_at": _T0,
        "deleted_at": None,
        "data": {"amount": n, "status": "succeeded"},
        **extra,
    }


@pytest.fixture(autouse=True)
def _auth_override():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def mdb():
    with patch("app.data_routes.db", new=MagicMock(unsafe=True)) as mock:
        mock.user_has_permission.return_value = True
        mock.assert_class_schema_tenant_access.return_value = True
        yield mock


def test_lists_the_first_page_with_a_next_cursor(mdb):
    mdb.list_data_records.return_value = ([_row(1), _row(2)], 5)
    res = client.get(_URL, params={"class_schema_id": _CS, "limit": 2})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 5 and body["limit"] == 2 and body["sort"] == "created_at"
    assert body["items"][0] == {
        "record_id": "00000000-0000-4000-8000-000000000001",
        "created_at": "2026-05-04T12:42:00+00:00",
        "updated_at": "2026-05-04T12:42:00+00:00",
        "deleted_at": None,
        "data": {"amount": 1, "status": "succeeded"},
    }
    assert body["next_cursor"] == _encode_records_cursor(2, _records_query_signature(_CS, [], "created_at", False))
    mdb.list_data_records.assert_called_once_with(
        _CS, "t1", filters=[], sort_field="created_at", descending=False, include_deleted=False, limit=2, offset=0
    )


def test_the_cursor_fetches_the_next_page_and_the_last_page_has_none(mdb):
    mdb.list_data_records.return_value = ([_row(1), _row(2)], 3)
    first = client.get(_URL, params={"class_schema_id": _CS, "limit": 2}).json()
    mdb.list_data_records.return_value = ([_row(3)], 3)
    last = client.get(_URL, params={"class_schema_id": _CS, "limit": 2, "cursor": first["next_cursor"]})
    assert last.status_code == 200
    assert mdb.list_data_records.call_args.kwargs["offset"] == 2
    assert last.json()["next_cursor"] is None


def test_filters_sort_and_include_deleted_are_passed_through(mdb):
    mdb.list_data_records.return_value = ([_row(1, deleted_at=_T0)], 1)
    res = client.get(
        _URL,
        params=[
            ("class_schema_id", _CS),
            ("filter", "status=succeeded"),
            ("filter", "note=a=b"),
            ("sort", "-amount"),
            ("include_deleted", "true"),
        ],
    )
    assert res.status_code == 200
    assert res.json()["items"][0]["deleted_at"] == "2026-05-04T12:42:00+00:00"
    assert res.json()["next_cursor"] is None
    kwargs = mdb.list_data_records.call_args.kwargs
    assert kwargs["filters"] == [("status", "succeeded"), ("note", "a=b")]
    assert kwargs["sort_field"] == "amount" and kwargs["descending"] is True
    assert kwargs["include_deleted"] is True


def test_a_cursor_from_another_query_is_refused(mdb):
    cursor = _encode_records_cursor(2, _records_query_signature(_CS, [], "created_at", False))
    res = client.get(_URL, params={"class_schema_id": _CS, "cursor": cursor, "sort": "-created_at"})
    assert res.status_code == 400
    assert "does not belong to this query" in res.json()["detail"]
    mdb.list_data_records.assert_not_called()


@pytest.mark.parametrize("cursor", ["not-base64!!", "e30", "eyJvIjotMSwicSI6IngifQ"])
def test_a_malformed_cursor_is_refused(mdb, cursor):
    res = client.get(_URL, params={"class_schema_id": _CS, "cursor": cursor})
    assert res.status_code == 400


@pytest.mark.parametrize(
    "params, detail",
    [
        ([("filter", "status")], "must be key=value"),
        ([("filter", "=x")], "must be key=value"),
        ([("sort", "-")], "must name a field"),
        ([("filter", f"k{i}=v") for i in range(21)], "At most 20 filters"),
    ],
)
def test_bad_filters_and_sorts_are_400(mdb, params, detail):
    res = client.get(_URL, params=[("class_schema_id", _CS), *params])
    assert res.status_code == 400
    assert detail in res.json()["detail"]


@pytest.mark.parametrize("limit", [0, 501])
def test_limit_bounds(mdb, limit):
    assert client.get(_URL, params={"class_schema_id": _CS, "limit": limit}).status_code == 422


def test_unknown_class_schema_is_404(mdb):
    mdb.assert_class_schema_tenant_access.return_value = False
    assert client.get(_URL, params={"class_schema_id": _CS}).status_code == 404
    mdb.list_data_records.assert_not_called()


def test_a_class_schema_id_that_is_not_a_uuid_is_404(mdb):
    assert client.get(_URL, params={"class_schema_id": "Charge"}).status_code == 404
    mdb.assert_class_schema_tenant_access.assert_not_called()


def test_requires_versions_view(mdb):
    mdb.user_has_permission.return_value = False
    assert client.get(_URL, params={"class_schema_id": _CS}).status_code == 403


# ---------------------------------------------------------------------------
# Database.list_data_records
# ---------------------------------------------------------------------------


def _calls(rows=None, total=0):
    from app.database import db as real_db

    answers = [[{"total": total}], rows or []]
    return patch.object(real_db, "execute_query", side_effect=answers), real_db


def test_list_data_records_counts_then_pages():
    patcher, real_db = _calls([_row(1)], total=7)
    with patcher as query:
        rows, total = real_db.list_data_records(_CS, "t1", limit=10, offset=20)
    assert total == 7 and rows == [_row(1)]
    count_sql, count_params = query.call_args_list[0].args
    page_sql, page_params = query.call_args_list[1].args
    assert "COUNT(*) AS total" in count_sql
    assert "'{}'::jsonb" in page_sql
    assert "ORDER BY r.created_at ASC NULLS LAST, r.record_id ASC" in page_sql
    assert count_params == (_CS, "t1", _CS, "t1", "t1", False)
    assert page_params == (_CS, "t1", _CS, "t1", "t1", False, 10, 20)


def test_list_data_records_filters_and_sorts_on_a_data_field():
    patcher, real_db = _calls()
    with patcher as query:
        real_db.list_data_records(
            _CS, "t1", filters=[("status", "ok")], sort_field="amount", descending=True, include_deleted=True
        )
    count_sql, count_params = query.call_args_list[0].args
    page_sql, page_params = query.call_args_list[1].args
    assert "WHERE r.data ->> %s = %s" in count_sql
    assert count_params[-3:] == (True, "status", "ok")
    assert "ORDER BY (r.data -> %s) DESC NULLS LAST" in page_sql
    assert page_params[-5:] == ("status", "ok", "amount", 50, 0)


def test_list_data_records_never_interpolates_a_data_sort_field():
    patcher, real_db = _calls()
    with patcher as query:
        real_db.list_data_records(_CS, "t1", sort_field="amount; DROP TABLE x")
    page_sql, page_params = query.call_args_list[1].args
    assert "DROP TABLE" not in page_sql
    assert "amount; DROP TABLE x" in page_params
