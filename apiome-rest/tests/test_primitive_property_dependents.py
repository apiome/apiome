"""Reverse index of property→type bindings — "Used by properties" (#3477).

``class_properties.primitive_id`` (#3475) binds a Designer property to a registry type, but
nothing answered the reverse question — which properties use this type. ``GET
/v1/primitives/{tenant}/{id}`` now returns the caller's bound properties as
``property_dependents``.

These tests pin the scope rules (the caller's own properties only; a system type also matches
its per-tenant copies by ``$id``), the entry shape the detail page reads, and the endpoint wiring.
"""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import Database
from app.main import app
from app.primitives_routes import build_property_dependents

client = TestClient(app)

_TENANT_ID = "11111111-1111-1111-1111-111111111111"
_AUTH = {
    "tenant_id": _TENANT_ID,
    "tenant_slug": "acme",
    "user_id": "user-1",
    "auth_method": "jwt",
}

_STRING_ID = "https://api.apiome.dev/types/std/v0/primitives/string"

_SYSTEM_ROW: Dict[str, Any] = {
    "id": "22222222-2222-2222-2222-222222222222",
    "tenant_id": _TENANT_ID,
    "name": "string",
    "description": None,
    "category": "string",
    "schema": {"$id": _STRING_ID, "type": "string"},
    "tags": [],
    "is_system": True,
    "is_public": True,
    "usage_count": 1,
    "enabled": True,
    "namespace": "std/v0/primitives",
    "schema_id": _STRING_ID,
    "base_uri": "https://api.apiome.dev/types/std/v0/primitives/",
    "draft": "2020-12",
    "refs": [],
    "created_at": None,
    "updated_at": None,
}

_TENANT_ROW: Dict[str, Any] = {
    **_SYSTEM_ROW,
    "id": "33333333-3333-3333-3333-333333333333",
    "name": "sku",
    "is_system": False,
    "is_public": False,
    "schema_id": None,
    "namespace": None,
}

_BINDING_ROW: Dict[str, Any] = {
    "class_property_id": "44444444-4444-4444-4444-444444444444",
    "property_name": "email",
    "parent_id": None,
    "primitive_ref": "std/v0/primitives/string",
    "class_id": "55555555-5555-5555-5555-555555555555",
    "class_name": "Customer",
    "version_id": "66666666-6666-6666-6666-666666666666",
    "version_label": "1.0.0",
    "project_id": "77777777-7777-7777-7777-777777777777",
    "project_name": "Billing",
}


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


class TestBuildPropertyDependents:
    def test_maps_each_binding_to_an_entry(self):
        with patch("app.primitives_routes.db") as mdb:
            mdb.get_property_bindings_for_primitive.return_value = [_BINDING_ROW]
            entries = build_property_dependents(_SYSTEM_ROW, tenant_id=_TENANT_ID)

        assert entries == [
            {
                "class_property_id": _BINDING_ROW["class_property_id"],
                "property": "email",
                "parent_id": None,
                "primitive_ref": "std/v0/primitives/string",
                "class_id": _BINDING_ROW["class_id"],
                "class_name": "Customer",
                "version_id": _BINDING_ROW["version_id"],
                "version_label": "1.0.0",
                "project_id": _BINDING_ROW["project_id"],
                "project_name": "Billing",
            }
        ]

    def test_a_system_type_matches_its_copies_by_id(self):
        with patch("app.primitives_routes.db") as mdb:
            mdb.get_property_bindings_for_primitive.return_value = []
            build_property_dependents(_SYSTEM_ROW, tenant_id=_TENANT_ID)

        mdb.get_property_bindings_for_primitive.assert_called_once_with(
            _SYSTEM_ROW["id"], _TENANT_ID, is_system=True, schema_id=_STRING_ID
        )

    def test_a_tenant_type_matches_only_its_own_row(self):
        with patch("app.primitives_routes.db") as mdb:
            mdb.get_property_bindings_for_primitive.return_value = []
            build_property_dependents(_TENANT_ROW, tenant_id=_TENANT_ID)

        mdb.get_property_bindings_for_primitive.assert_called_once_with(
            _TENANT_ROW["id"], _TENANT_ID, is_system=False, schema_id=None
        )

    def test_keeps_a_nested_propertys_parent(self):
        nested = {**_BINDING_ROW, "parent_id": "88888888-8888-8888-8888-888888888888"}
        with patch("app.primitives_routes.db") as mdb:
            mdb.get_property_bindings_for_primitive.return_value = [nested]
            [entry] = build_property_dependents(_SYSTEM_ROW, tenant_id=_TENANT_ID)

        assert entry["parent_id"] == "88888888-8888-8888-8888-888888888888"

    def test_nothing_bound_is_an_empty_list(self):
        with patch("app.primitives_routes.db") as mdb:
            mdb.get_property_bindings_for_primitive.return_value = None
            assert build_property_dependents(_SYSTEM_ROW, tenant_id=_TENANT_ID) == []


class TestGetPropertyBindingsQuery:
    """The SQL itself: tenant-scoped properties, soft-deletes excluded, system copies opt-in."""

    def _run(self, **kwargs):
        database = Database.__new__(Database)
        database.execute_query = MagicMock(return_value=[])
        database.get_property_bindings_for_primitive("prim-1", _TENANT_ID, **kwargs)
        return database.execute_query.call_args.args

    def test_scopes_properties_to_the_callers_tenant(self):
        query, params = self._run()
        assert "p.tenant_id = %s" in query
        assert params[0] == _TENANT_ID

    def test_excludes_soft_deleted_classes_versions_and_projects(self):
        query, _ = self._run()
        for alias in ("c", "v", "p"):
            assert f"{alias}.deleted_at IS NULL" in query

    def test_system_copies_match_only_for_a_system_type(self):
        _, system_params = self._run(is_system=True, schema_id=_STRING_ID)
        assert system_params == (_TENANT_ID, "prim-1", True, _STRING_ID)

        _, tenant_params = self._run(is_system=False, schema_id=_STRING_ID)
        assert tenant_params[2] is False

    def test_a_system_type_without_an_id_matches_by_row_only(self):
        _, params = self._run(is_system=True, schema_id=None)
        assert params[2] is False


class TestGetPrimitiveEndpoint:
    def test_returns_the_bound_properties(self):
        with patch("app.primitives_routes.db") as mdb:
            mdb.get_primitive_by_id.return_value = _SYSTEM_ROW
            mdb.get_dependent_primitives.return_value = []
            mdb.get_property_bindings_for_primitive.return_value = [_BINDING_ROW]
            response = client.get(f"/v1/primitives/acme/{_SYSTEM_ROW['id']}")

        assert response.status_code == 200
        [entry] = response.json()["property_dependents"]
        assert (entry["class_name"], entry["property"]) == ("Customer", "email")

    def test_returns_an_empty_list_when_nothing_is_bound(self):
        with patch("app.primitives_routes.db") as mdb:
            mdb.get_primitive_by_id.return_value = _TENANT_ROW
            mdb.get_property_bindings_for_primitive.return_value = []
            response = client.get(f"/v1/primitives/acme/{_TENANT_ROW['id']}")

        assert response.json()["property_dependents"] == []

    def test_not_found_does_not_query_bindings(self):
        with patch("app.primitives_routes.db") as mdb:
            mdb.get_primitive_by_id.return_value = None
            response = client.get("/v1/primitives/acme/missing")

        assert response.status_code == 404
        mdb.get_property_bindings_for_primitive.assert_not_called()
