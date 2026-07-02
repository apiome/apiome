"""
Tests for primitive import provenance and property→primitive binding (#3448).

Covers:
- Auth gating on the new import-provenance endpoints.
- Route registration order so the literal `imports` path is not captured as a
  primitive id by GET /{tenant_slug}/{primitive_id}.
- Pydantic model contracts for the import request/record and the `source` field.
"""

import pytest
from fastapi.testclient import TestClient

from src.app.main import app
from src.app.models import (
    PrimitiveSchema,
    PrimitiveImportRequest,
    PrimitiveImportRecord,
)
from src.app import primitives_routes

client = TestClient(app)


# ---------------------------------------------------------------------------
# Auth gating on the new provenance endpoints
# ---------------------------------------------------------------------------

def test_list_imports_requires_auth():
    """Listing import provenance requires authentication."""
    response = client.get('/v1/primitives/test-tenant/imports')
    assert response.status_code == 401


def test_get_import_requires_auth():
    """Fetching a single import provenance record requires authentication."""
    response = client.get('/v1/primitives/test-tenant/imports/some-id')
    assert response.status_code == 401


def test_list_imports_invalid_api_key():
    """An invalid API key is rejected on the imports list endpoint."""
    response = client.get(
        '/v1/primitives/test-tenant/imports',
        headers={'X-API-Key': 'invalid-key'},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Route ordering: `/imports` must win over `/{primitive_id}`
# ---------------------------------------------------------------------------

def _get_route_index(path: str, method: str = 'GET') -> int:
    for idx, route in enumerate(app.router.routes):
        if getattr(route, 'path', None) == path and method in getattr(route, 'methods', set()):
            return idx
    raise AssertionError(f"Route not found: {method} {path}")


def test_imports_routes_registered_before_primitive_id():
    """
    The static `/imports` routes must be registered before the parametric
    `/{primitive_id}` route, otherwise FastAPI captures `imports` as a primitive id.
    """
    imports_idx = _get_route_index('/v1/primitives/{tenant_slug}/imports')
    detail_idx = _get_route_index('/v1/primitives/{tenant_slug}/imports/{import_id}')
    primitive_idx = _get_route_index('/v1/primitives/{tenant_slug}/{primitive_id}')

    assert imports_idx < primitive_idx
    assert detail_idx < primitive_idx


# ---------------------------------------------------------------------------
# Model contracts
# ---------------------------------------------------------------------------

def test_import_request_defaults():
    """PrimitiveImportRequest defaults source_kind to json-schema with no label/namespace."""
    req = PrimitiveImportRequest(schema={'$defs': {}})
    assert req.source_kind == 'json-schema'
    assert req.source_label is None
    assert req.target_namespace is None
    assert req.import_all is False


def test_import_request_accepts_provenance_fields():
    """Provenance metadata round-trips through the request model."""
    req = PrimitiveImportRequest(
        schema={'$defs': {}},
        source_kind='openapi',
        source_label='petstore.yaml',
        target_namespace='tenant/acme/types',
    )
    assert req.source_kind == 'openapi'
    assert req.source_label == 'petstore.yaml'
    assert req.target_namespace == 'tenant/acme/types'


def test_valid_source_kinds_match_constraint():
    """The route guard set matches the values allowed by the DB CHECK constraint."""
    assert primitives_routes.VALID_IMPORT_SOURCE_KINDS == {
        'json-schema', 'type-def-bundle', 'openapi',
    }


def test_import_record_model():
    """PrimitiveImportRecord exposes the provenance row including the report JSON."""
    record = PrimitiveImportRecord(
        id='11111111-1111-1111-1111-111111111111',
        tenant_id='22222222-2222-2222-2222-222222222222',
        source_kind='json-schema',
        report={'imported': ['Money'], 'total_imported': 1},
        imported_count=1,
    )
    assert record.report['total_imported'] == 1
    assert record.imported_count == 1
    assert record.skipped_count == 0
    assert record.options == {}


def test_primitive_schema_source_defaults_to_human():
    """A primitive's provenance defaults to 'human' when unspecified."""
    primitive = PrimitiveSchema(
        id='1', tenant_id='t', name='String', category='string',
        schema={'type': 'string'},
    )
    assert primitive.source == 'human'

    imported = PrimitiveSchema(
        id='1', tenant_id='t', name='String', category='string',
        schema={'type': 'string'}, source='imported',
    )
    assert imported.source == 'imported'
