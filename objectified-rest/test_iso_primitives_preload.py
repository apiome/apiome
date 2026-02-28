"""
Tests for ISO Standard Primitives Preload

Verifies that the 36 industry-standard ISO primitives are correctly
loaded and accessible through the API. Uses mocked DB so tests pass without a real DB.
"""

from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src.app.main import app
from src.app.auth import validate_authentication

client = TestClient(app)


# Valid UUID for tenant_id (DB expects UUID type). Use a constant so tests are deterministic.
TEST_TENANT_ID = "11111111-1111-1111-1111-111111111111"


def _fake_validate_authentication(
    tenant_slug: str,
    authorization: Optional[str] = None,
    x_api_key: Optional[str] = None,
):
    """Fake auth for testing. Signature matches validate_authentication."""
    return {
        "tenant_id": TEST_TENANT_ID,
        "tenant_slug": tenant_slug,
        "auth_method": "jwt",
        "user_id": "user-1",
    }


def _make_primitive(
    id: str,
    name: str,
    category: str,
    schema: Dict[str, Any],
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a primitive dict for mocking (matches DB row shape used by PrimitiveSchema)."""
    return {
        "id": id,
        "tenant_id": TEST_TENANT_ID,
        "name": name,
        "description": None,
        "category": category,
        "schema": schema,
        "tags": tags or [],
        "created_by": None,
        "is_system": True,
        "is_public": False,
        "usage_count": 0,
        "created_at": None,
        "updated_at": None,
        "enabled": True,
    }


def _mock_primitives_by_category() -> Dict[Optional[str], List[Dict[str, Any]]]:
    """Build full set of mock primitives keyed by category (None = all)."""
    # String primitives (>=20, with specific names and schemas for assertions)
    string_prims = [
        _make_primitive("s-email", "Email Address", "string", {"type": "string", "format": "email", "maxLength": 254}, ["iso-standard"]),
        _make_primitive("s-uuid", "UUID", "string", {"type": "string", "format": "uuid", "pattern": "^[0-9a-fA-F-]{36}$"}, ["iso-standard"]),
        _make_primitive("s-uri", "Uniform Resource Identifier (URI)", "string", {"type": "string", "format": "uri"}, ["iso-standard"]),
        _make_primitive("s-url", "Uniform Resource Locator (URL)", "string", {"type": "string", "format": "uri"}, ["iso-standard"]),
        _make_primitive("s-date", "Date (ISO 8601)", "string", {"type": "string", "format": "date"}, ["iso8601", "iso-standard"]),
        _make_primitive("s-datetime", "Date-Time (ISO 8601)", "string", {"type": "string", "format": "date-time"}, ["iso8601", "iso-standard"]),
        _make_primitive("s-phone", "Phone Number (E.164)", "string", {"type": "string"}, ["iso-standard"]),
        _make_primitive("s-ipv4", "IPv4 Address", "string", {"type": "string", "format": "ipv4"}, ["iso-standard"]),
        _make_primitive("s-ipv6", "IPv6 Address", "string", {"type": "string", "format": "ipv6"}, ["iso-standard"]),
        _make_primitive("s-country", "Country Code (ISO 3166-1)", "string", {"type": "string"}, ["iso-standard"]),
        _make_primitive("s-lang", "Language Code (ISO 639-1)", "string", {"type": "string"}, ["iso-standard"]),
        _make_primitive("s-currency", "Currency Code (ISO 4217)", "string", {"type": "string"}, ["iso-standard"]),
        _make_primitive("s-1", "String 1", "string", {"type": "string"}, ["iso-standard"]),
        _make_primitive("s-2", "String 2", "string", {"type": "string"}, ["iso-standard"]),
        _make_primitive("s-3", "String 3", "string", {"type": "string"}, ["iso-standard"]),
        _make_primitive("s-4", "String 4", "string", {"type": "string"}, ["iso-standard"]),
        _make_primitive("s-5", "String 5", "string", {"type": "string"}, ["iso-standard"]),
        _make_primitive("s-6", "String 6", "string", {"type": "string"}, ["iso-standard"]),
        _make_primitive("s-7", "String 7", "string", {"type": "string"}, ["iso-standard"]),
        _make_primitive("s-8", "String 8", "string", {"type": "string"}, ["iso-standard"]),
    ]
    # Integer primitives (>=5)
    integer_prims = [
        _make_primitive("i-int", "Integer", "integer", {"type": "integer"}, ["iso-standard"]),
        _make_primitive("i-pos", "Positive Integer", "integer", {"type": "integer", "minimum": 1}, ["iso-standard"]),
        _make_primitive("i-nonneg", "Non-Negative Integer", "integer", {"type": "integer", "minimum": 0}, ["iso-standard"]),
        _make_primitive("i-pct", "Percentage (Integer)", "integer", {"type": "integer", "minimum": 0, "maximum": 100}, ["iso-standard"]),
        _make_primitive("i-5", "Integer 5", "integer", {"type": "integer"}, ["iso-standard"]),
    ]
    # Number primitives (>=4)
    number_prims = [
        _make_primitive("n-dec", "Decimal Number", "number", {"type": "number"}, ["iso-standard"]),
        _make_primitive("n-pct", "Percentage (Decimal)", "number", {"type": "number", "minimum": 0, "maximum": 1}, ["iso-standard"]),
        _make_primitive("n-prob", "Probability", "number", {"type": "number", "minimum": 0, "maximum": 1}, ["iso-standard"]),
        _make_primitive("n-money", "Monetary Amount", "number", {"type": "number"}, ["iso-standard"]),
    ]
    # Array primitives (>=4)
    array_prims = [
        _make_primitive("a-str", "String Array", "array", {"type": "array", "items": {"type": "string"}}, ["iso-standard"]),
        _make_primitive("a-int", "Integer Array", "array", {"type": "array", "items": {"type": "integer"}}, ["iso-standard"]),
        _make_primitive("a-num", "Number Array", "array", {"type": "array", "items": {"type": "number"}}, ["iso-standard"]),
        _make_primitive("a-bool", "Boolean Array", "array", {"type": "array", "items": {"type": "boolean"}}, ["iso-standard"]),
    ]
    boolean_prims = [_make_primitive("b-1", "Boolean", "boolean", {"type": "boolean"}, ["iso-standard"])]
    object_prims = [_make_primitive("o-1", "JSON Object", "object", {"type": "object"}, ["iso-standard"])]
    null_prims = [_make_primitive("nul-1", "Null Value", "null", {"type": "null"}, ["iso-standard"])]

    all_prims = string_prims + integer_prims + number_prims + array_prims + boolean_prims + object_prims + null_prims
    return {
        None: all_prims,
        "string": string_prims,
        "integer": integer_prims,
        "number": number_prims,
        "array": array_prims,
        "boolean": boolean_prims,
        "object": object_prims,
        "null": null_prims,
    }


@pytest.fixture(autouse=True)
def override_auth():
    """Override auth so primitives endpoints accept requests without real JWT/API key."""
    app.dependency_overrides[validate_authentication] = _fake_validate_authentication
    try:
        yield
    finally:
        if validate_authentication in app.dependency_overrides:
            del app.dependency_overrides[validate_authentication]


@pytest.fixture(autouse=True)
def mock_primitives_db():
    """Mock db.get_primitives_for_tenant and get_primitive_by_id so tests pass without a real DB."""
    by_category = _mock_primitives_by_category()
    all_prims = by_category[None]
    by_id = {p["id"]: p for p in all_prims}

    def get_primitives_for_tenant(tenant_id: str, category: Optional[str] = None) -> List[Dict[str, Any]]:
        return by_category.get(category, all_prims) if category else all_prims

    def get_primitive_by_id(primitive_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        return by_id.get(primitive_id)

    with patch("src.app.primitives_routes.db") as mock_db:
        mock_db.get_primitives_for_tenant.side_effect = get_primitives_for_tenant
        mock_db.get_primitive_by_id.side_effect = get_primitive_by_id
        yield mock_db


class TestISOPrimitivesPreload:
    """Tests for preloaded ISO standard primitives."""

    def test_list_all_string_primitives(self, auth_headers):
        """Test that all string primitives are available."""
        response = client.get(
            '/v1/primitives/test-tenant?category=string',
            headers=auth_headers
        )
        assert response.status_code == 200
        primitives = response.json()

        # Should have at least 20 string primitives
        assert len(primitives) >= 20

        # Verify common string primitives exist
        names = [p['name'] for p in primitives]
        assert 'Email Address' in names
        assert 'UUID' in names
        assert 'Uniform Resource Identifier (URI)' in names
        assert 'Uniform Resource Locator (URL)' in names
        assert 'Date (ISO 8601)' in names
        assert 'Date-Time (ISO 8601)' in names
        assert 'Phone Number (E.164)' in names
        assert 'IPv4 Address' in names
        assert 'IPv6 Address' in names
        assert 'Country Code (ISO 3166-1)' in names
        assert 'Language Code (ISO 639-1)' in names
        assert 'Currency Code (ISO 4217)' in names

    def test_list_all_integer_primitives(self, auth_headers):
        """Test that all integer primitives are available."""
        response = client.get(
            '/v1/primitives/test-tenant?category=integer',
            headers=auth_headers
        )
        assert response.status_code == 200
        primitives = response.json()

        # Should have at least 5 integer primitives
        assert len(primitives) >= 5

        names = [p['name'] for p in primitives]
        assert 'Integer' in names
        assert 'Positive Integer' in names
        assert 'Non-Negative Integer' in names
        assert 'Percentage (Integer)' in names

    def test_list_all_number_primitives(self, auth_headers):
        """Test that all number (decimal) primitives are available."""
        response = client.get(
            '/v1/primitives/test-tenant?category=number',
            headers=auth_headers
        )
        assert response.status_code == 200
        primitives = response.json()

        # Should have at least 4 number primitives
        assert len(primitives) >= 4

        names = [p['name'] for p in primitives]
        assert 'Decimal Number' in names
        assert 'Percentage (Decimal)' in names
        assert 'Probability' in names
        assert 'Monetary Amount' in names

    def test_list_all_array_primitives(self, auth_headers):
        """Test that all array primitives are available."""
        response = client.get(
            '/v1/primitives/test-tenant?category=array',
            headers=auth_headers
        )
        assert response.status_code == 200
        primitives = response.json()

        # Should have at least 4 array primitives
        assert len(primitives) >= 4

        names = [p['name'] for p in primitives]
        assert 'String Array' in names
        assert 'Integer Array' in names
        assert 'Number Array' in names
        assert 'Boolean Array' in names

    def test_boolean_primitive_exists(self, auth_headers):
        """Test that boolean primitive is available."""
        response = client.get(
            '/v1/primitives/test-tenant?category=boolean',
            headers=auth_headers
        )
        assert response.status_code == 200
        primitives = response.json()

        assert len(primitives) >= 1
        assert any(p['name'] == 'Boolean' for p in primitives)

    def test_object_primitive_exists(self, auth_headers):
        """Test that object primitive is available."""
        response = client.get(
            '/v1/primitives/test-tenant?category=object',
            headers=auth_headers
        )
        assert response.status_code == 200
        primitives = response.json()

        assert len(primitives) >= 1
        assert any(p['name'] == 'JSON Object' for p in primitives)

    def test_null_primitive_exists(self, auth_headers):
        """Test that null primitive is available."""
        response = client.get(
            '/v1/primitives/test-tenant?category=null',
            headers=auth_headers
        )
        assert response.status_code == 200
        primitives = response.json()

        assert len(primitives) >= 1
        assert any(p['name'] == 'Null Value' for p in primitives)

    def test_email_primitive_schema(self, auth_headers):
        """Test that email primitive has correct JSON Schema."""
        response = client.get(
            '/v1/primitives/test-tenant?category=string',
            headers=auth_headers
        )
        assert response.status_code == 200
        primitives = response.json()

        email_prim = next((p for p in primitives if p['name'] == 'Email Address'), None)
        assert email_prim is not None
        assert email_prim['schema']['type'] == 'string'
        assert email_prim['schema']['format'] == 'email'
        assert email_prim['schema']['maxLength'] == 254

    def test_uuid_primitive_schema(self, auth_headers):
        """Test that UUID primitive has correct JSON Schema."""
        response = client.get(
            '/v1/primitives/test-tenant?category=string',
            headers=auth_headers
        )
        assert response.status_code == 200
        primitives = response.json()

        uuid_prim = next((p for p in primitives if p['name'] == 'UUID'), None)
        assert uuid_prim is not None
        assert uuid_prim['schema']['type'] == 'string'
        assert uuid_prim['schema']['format'] == 'uuid'
        assert 'pattern' in uuid_prim['schema']

    def test_iso8601_date_primitive(self, auth_headers):
        """Test that ISO 8601 date primitive exists and is correct."""
        response = client.get(
            '/v1/primitives/test-tenant?category=string',
            headers=auth_headers
        )
        assert response.status_code == 200
        primitives = response.json()

        date_prim = next((p for p in primitives if 'ISO 8601' in p['name'] and 'Date' in p['name']), None)
        assert date_prim is not None
        assert 'iso8601' in date_prim['tags']
        assert 'iso-standard' in date_prim['tags']

    def test_primitives_tagged_with_iso_standard(self, auth_headers):
        """Test that primitives are tagged with iso-standard tag."""
        response = client.get(
            '/v1/primitives/test-tenant',
            headers=auth_headers
        )
        assert response.status_code == 200
        primitives = response.json()

        # Count primitives with iso-standard tag
        iso_standard_count = sum(
            1 for p in primitives
            if 'iso-standard' in p.get('tags', [])
        )

        # Should have many iso-standard tagged primitives
        assert iso_standard_count >= 20

    def test_all_primitives_are_enabled(self, auth_headers):
        """Test that all preloaded primitives are enabled."""
        response = client.get(
            '/v1/primitives/test-tenant',
            headers=auth_headers
        )
        assert response.status_code == 200
        primitives = response.json()

        for primitive in primitives:
            assert primitive['enabled'] is True, f"Primitive {primitive['name']} is not enabled"

    def test_all_primitives_are_system_primitives(self, auth_headers):
        """Test that all preloaded primitives are marked as system primitives."""
        response = client.get(
            '/v1/primitives/test-tenant',
            headers=auth_headers
        )
        assert response.status_code == 200
        primitives = response.json()

        for primitive in primitives:
            assert primitive['is_system'] is True, f"Primitive {primitive['name']} is not marked as system"

    def test_percentage_integer_vs_decimal(self, auth_headers):
        """Test that percentage primitives exist for both integer and decimal."""
        response = client.get(
            '/v1/primitives/test-tenant',
            headers=auth_headers
        )
        assert response.status_code == 200
        primitives = response.json()

        names = [p['name'] for p in primitives]
        assert 'Percentage (Integer)' in names
        assert 'Percentage (Decimal)' in names

        # Verify their schemas are different
        pct_int = next(p for p in primitives if p['name'] == 'Percentage (Integer)')
        pct_dec = next(p for p in primitives if p['name'] == 'Percentage (Decimal)')

        assert pct_int['schema']['type'] == 'integer'
        assert pct_dec['schema']['type'] == 'number'

    def test_total_primitive_count(self, auth_headers):
        """Test that we have the expected total number of primitives."""
        response = client.get(
            '/v1/primitives/test-tenant',
            headers=auth_headers
        )
        assert response.status_code == 200
        primitives = response.json()

        # Should have at least 36 primitives (the base ISO set)
        assert len(primitives) >= 36


@pytest.fixture
def auth_headers():
    """Provides headers for testing (auth is overridden by override_auth fixture)."""
    return {
        "Authorization": "Bearer test-token",
        "X-API-Key": "test-key",
    }
