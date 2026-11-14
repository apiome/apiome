"""``GET /v1/data/{tenant_slug}/classes`` — class schema lookup for data records (#3255).

Resolves ``project`` + ``version`` (+ optional ``class``) to the frozen class schemas a data record
is created against: the tenant comes from the token, an unknown project or version is 404, a version
never published answers an empty list, and the caller needs ``versions:view``.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_URL = "/v1/data/acme/classes"

_VERSION = {
    "version_record_id": "22222222-2222-2222-2222-222222222222",
    "version": "1.0.0",
    "published": True,
    "project_slug": "billing",
}
_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"amount": {"type": "number"}},
    "required": ["amount"],
}
_ROW = {
    "class_schema_id": "33333333-3333-3333-3333-333333333333",
    "class_id": "44444444-4444-4444-4444-444444444444",
    "class_name": "Charge",
    "schema": _SCHEMA,
}


@pytest.fixture(autouse=True)
def _auth_override():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.clear()


def test_lists_class_schemas_for_a_published_version():
    with patch("app.data_routes.db") as mdb:
        mdb.user_has_permission.return_value = True
        mdb.find_data_version.return_value = _VERSION
        mdb.list_version_class_schemas.return_value = [_ROW]
        res = client.get(_URL, params={"project": "billing", "version": "v1.0.0"})
    assert res.status_code == 200
    body = res.json()
    assert body == {
        "success": True,
        "project": "billing",
        "version": "1.0.0",
        "published": True,
        "classes": [
            {
                "class_schema_id": _ROW["class_schema_id"],
                "class_id": _ROW["class_id"],
                "class_name": "Charge",
                "schema": _SCHEMA,
            }
        ],
    }
    mdb.find_data_version.assert_called_once_with("t1", "billing", "v1.0.0")
    mdb.list_version_class_schemas.assert_called_once_with(_VERSION["version_record_id"], None)


def test_class_filter_is_passed_through():
    with patch("app.data_routes.db") as mdb:
        mdb.user_has_permission.return_value = True
        mdb.find_data_version.return_value = _VERSION
        mdb.list_version_class_schemas.return_value = [_ROW]
        res = client.get(_URL, params={"project": "billing", "version": "1.0.0", "class": "Charge"})
    assert res.status_code == 200
    mdb.list_version_class_schemas.assert_called_once_with(_VERSION["version_record_id"], "Charge")


def test_unpublished_version_answers_an_empty_list():
    with patch("app.data_routes.db") as mdb:
        mdb.user_has_permission.return_value = True
        mdb.find_data_version.return_value = {**_VERSION, "published": False}
        mdb.list_version_class_schemas.return_value = []
        res = client.get(_URL, params={"project": "billing", "version": "1.0.0"})
    assert res.status_code == 200
    assert res.json()["published"] is False
    assert res.json()["classes"] == []


def test_non_dict_schema_is_answered_as_an_empty_object():
    with patch("app.data_routes.db") as mdb:
        mdb.user_has_permission.return_value = True
        mdb.find_data_version.return_value = _VERSION
        mdb.list_version_class_schemas.return_value = [{**_ROW, "schema": None}]
        res = client.get(_URL, params={"project": "billing", "version": "1.0.0"})
    assert res.json()["classes"][0]["schema"] == {}


def test_unknown_version_is_404():
    with patch("app.data_routes.db") as mdb:
        mdb.user_has_permission.return_value = True
        mdb.find_data_version.return_value = None
        res = client.get(_URL, params={"project": "billing", "version": "9.9.9"})
    assert res.status_code == 404
    assert "billing/9.9.9" in res.json()["detail"]
    mdb.list_version_class_schemas.assert_not_called()


def test_project_and_version_are_required():
    with patch("app.data_routes.db") as mdb:
        mdb.user_has_permission.return_value = True
        res = client.get(_URL, params={"project": "billing"})
    assert res.status_code == 422


def test_requires_versions_view():
    with patch("app.data_routes.db") as mdb:
        mdb.user_has_permission.return_value = False
        res = client.get(_URL, params={"project": "billing", "version": "1.0.0"})
    assert res.status_code == 403
    mdb.find_data_version.assert_not_called()


# ---------------------------------------------------------------------------
# Database accessors
# ---------------------------------------------------------------------------


def test_find_data_version_also_matches_the_label_without_a_leading_v():
    from app.database import db as real_db

    with patch.object(real_db, "execute_query", return_value=[_VERSION]) as query:
        assert real_db.find_data_version("t1", "billing", "v1.0.0") == _VERSION
    params = query.call_args.args[1]
    assert params == ("t1", "billing", ["v1.0.0", "1.0.0"], "v1.0.0")


def test_find_data_version_keeps_a_plain_label_as_is():
    from app.database import db as real_db

    with patch.object(real_db, "execute_query", return_value=[]) as query:
        assert real_db.find_data_version("t1", "billing", "1.0.0") is None
    assert query.call_args.args[1][2] == ["1.0.0"]


def test_list_version_class_schemas_filters_by_class_name_only_when_given():
    from app.database import db as real_db

    with patch.object(real_db, "execute_query", return_value=[_ROW]) as query:
        assert real_db.list_version_class_schemas("v-1") == [_ROW]
        assert query.call_args.args[1] == ("v-1",)
        real_db.list_version_class_schemas("v-1", "Charge")
    sql, params = query.call_args.args
    assert "c.name = %s" in sql
    assert params == ("v-1", "Charge")
