"""Tests for property→type `$ref` binding persistence on class properties (#3475).

The binding lives in dedicated `apiome.class_properties` columns — `primitive_id`
(a real FK to the resolved `apiome.primitives` row) and `primitive_ref` (the stored
registry `$ref` string) — *not* inside the property's JSON Schema `data`. These
DB-free route tests assert the create/update/read handlers carry the binding
through to the data layer, that a present-but-null value clears the binding, and
that the `PropertySchema` contract exposes both fields.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.models import PropertySchema

client = TestClient(app)

_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
_CLASS_ID = "880e8400-e29b-41d4-a716-446655440003"
_PROP_ID = "990e8400-e29b-41d4-a716-446655440009"
_PRIMITIVE_ID = "110e8400-e29b-41d4-a716-446655440111"
_PRIMITIVE_REF = "std/v0/types/date"

_API_KEY_AUTH = {
    "tenant_id": _TENANT_ID,
    "tenant_slug": "acme",
    "auth_method": "api_key",
}


@pytest.fixture(autouse=True)
def _auth_api_key():
    app.dependency_overrides[validate_authentication] = lambda: _API_KEY_AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _bound_property_row(**overrides):
    """A class-property row as the DAO returns it once bound to a registry type."""
    row = {
        "id": _PROP_ID,
        "class_id": _CLASS_ID,
        "property_id": None,
        "name": "birthDate",
        "description": "Date of birth",
        "data": {"type": "string", "format": "date"},
        "parent_id": None,
        "primitive_id": _PRIMITIVE_ID,
        "primitive_ref": _PRIMITIVE_REF,
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# Create (POST) — the binding reaches the data layer
# ---------------------------------------------------------------------------

def test_create_property_forwards_binding():
    """POST passes primitive_id/primitive_ref straight through to the DAO."""
    with patch("app.classes_routes.db") as mdb:
        mdb.get_class_by_id.return_value = {"id": _CLASS_ID}
        mdb.add_property_to_class.return_value = _bound_property_row()
        r = client.post(
            f"/v1/classes/acme/{_CLASS_ID}/properties",
            json={
                "name": "birthDate",
                "data": {"type": "string", "format": "date"},
                "primitive_id": _PRIMITIVE_ID,
                "primitive_ref": _PRIMITIVE_REF,
            },
        )
    assert r.status_code == 200
    kwargs = mdb.add_property_to_class.call_args.kwargs
    assert kwargs["primitive_id"] == _PRIMITIVE_ID
    assert kwargs["primitive_ref"] == _PRIMITIVE_REF
    body = r.json()
    assert body["primitive_id"] == _PRIMITIVE_ID
    assert body["primitive_ref"] == _PRIMITIVE_REF


def test_create_property_without_binding_passes_none():
    """An unbound property forwards None for both binding columns."""
    with patch("app.classes_routes.db") as mdb:
        mdb.get_class_by_id.return_value = {"id": _CLASS_ID}
        mdb.add_property_to_class.return_value = _bound_property_row(
            primitive_id=None, primitive_ref=None
        )
        r = client.post(
            f"/v1/classes/acme/{_CLASS_ID}/properties",
            json={"name": "nickname", "data": {"type": "string"}},
        )
    assert r.status_code == 200
    kwargs = mdb.add_property_to_class.call_args.kwargs
    assert kwargs["primitive_id"] is None
    assert kwargs["primitive_ref"] is None


# ---------------------------------------------------------------------------
# Update (PUT) — bind, clear, and read-back
# ---------------------------------------------------------------------------

def test_update_property_persists_binding():
    """PUT routes primitive_id/primitive_ref into the DAO's updates dict."""
    with patch("app.classes_routes.db") as mdb:
        mdb.get_class_by_id.return_value = {"id": _CLASS_ID}
        mdb.update_class_property.return_value = _bound_property_row()
        r = client.put(
            f"/v1/classes/acme/{_CLASS_ID}/properties/{_PROP_ID}",
            json={
                "name": "birthDate",
                "data": {"type": "string", "format": "date"},
                "primitive_id": _PRIMITIVE_ID,
                "primitive_ref": _PRIMITIVE_REF,
            },
        )
    assert r.status_code == 200
    updates = mdb.update_class_property.call_args.kwargs["updates"]
    assert updates["primitive_id"] == _PRIMITIVE_ID
    assert updates["primitive_ref"] == _PRIMITIVE_REF


def test_update_property_clears_binding_with_null():
    """A present-but-null binding clears it (the value still reaches updates)."""
    with patch("app.classes_routes.db") as mdb:
        mdb.get_class_by_id.return_value = {"id": _CLASS_ID}
        mdb.update_class_property.return_value = _bound_property_row(
            primitive_id=None, primitive_ref=None
        )
        r = client.put(
            f"/v1/classes/acme/{_CLASS_ID}/properties/{_PROP_ID}",
            json={
                "name": "birthDate",
                "data": {"type": "string", "format": "date"},
                "primitive_id": None,
                "primitive_ref": None,
            },
        )
    assert r.status_code == 200
    updates = mdb.update_class_property.call_args.kwargs["updates"]
    assert "primitive_id" in updates and updates["primitive_id"] is None
    assert "primitive_ref" in updates and updates["primitive_ref"] is None


def test_update_property_omits_binding_when_not_sent():
    """When the client sends no binding keys, the DAO updates omit them entirely
    (so an unrelated edit never touches the binding columns)."""
    with patch("app.classes_routes.db") as mdb:
        mdb.get_class_by_id.return_value = {"id": _CLASS_ID}
        mdb.update_class_property.return_value = _bound_property_row()
        r = client.put(
            f"/v1/classes/acme/{_CLASS_ID}/properties/{_PROP_ID}",
            json={"description": "tweak only"},
        )
    assert r.status_code == 200
    updates = mdb.update_class_property.call_args.kwargs["updates"]
    assert "primitive_id" not in updates
    assert "primitive_ref" not in updates


def test_get_properties_returns_binding():
    """GET surfaces the persisted binding columns so the Designer can rehydrate."""
    with patch("app.classes_routes.db") as mdb:
        mdb.get_class_by_id.return_value = {"id": _CLASS_ID}
        mdb.get_properties_for_class.return_value = [_bound_property_row()]
        r = client.get(f"/v1/classes/acme/{_CLASS_ID}/properties")
    assert r.status_code == 200
    item = r.json()[0]
    assert item["primitive_id"] == _PRIMITIVE_ID
    assert item["primitive_ref"] == _PRIMITIVE_REF


# ---------------------------------------------------------------------------
# Model contract
# ---------------------------------------------------------------------------

def test_property_schema_exposes_binding_fields():
    """PropertySchema carries the binding fields and defaults them to None."""
    bare = PropertySchema(id=_PROP_ID, class_id=_CLASS_ID, name="x")
    assert bare.primitive_id is None
    assert bare.primitive_ref is None

    bound = PropertySchema(
        id=_PROP_ID,
        class_id=_CLASS_ID,
        name="birthDate",
        primitive_id=_PRIMITIVE_ID,
        primitive_ref=_PRIMITIVE_REF,
    )
    assert bound.primitive_id == _PRIMITIVE_ID
    assert bound.primitive_ref == _PRIMITIVE_REF
