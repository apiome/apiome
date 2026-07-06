"""Endpoint tests for the export-target enumeration API (MFX-1.2, #3835).

Mirrors :mod:`test_import_sources_routes` (MFI-1.3): the emitter registry is exposed
as ``GET /v1/export/{tenant_slug}/targets?artifact=&version=`` so the UI/CLI can discover
every registered target with its descriptor, capability profile, options metadata,
and a cheap per-source fidelity tier — without emitting an artifact.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.avro_emitter import AvroEmitter
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import (
    CapabilityProfile,
    EmitResult,
    Emitter,
    _REGISTRY,
    register_emitter,
)
from app.export_source import ExportSource, ExportSourceError
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {"tenant_id": "test-tenant-id", "user_id": "test-user-id", "auth_method": "jwt"}


def _override_auth():
    return _MOCK_AUTH


def _source() -> ExportSource:
    """A loaded OpenAPI REST source with one operation + one type."""
    widget = Type(
        key="Widget",
        name="Widget",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string"))],
    )
    op = Operation(key="GET /widgets", name="listWidgets", kind=OperationKind.QUERY)
    service = Service(key="widgets", name="widgets", operations=[op])
    api = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="widgets"),
        services=[service],
        types=[widget],
    )
    return ExportSource(
        api=api,
        artifact_id="artifact-1",
        version_record_id="rev-uuid-1",
        version_label="1.0.0",
    )


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = _override_auth
    yield
    app.dependency_overrides.clear()


def test_list_export_targets_returns_registered_emitters_with_fidelity():
    """Every registered emitter is listed with descriptor, profile, options, and a tier badge."""
    with patch("app.export_routes.load_export_source", return_value=_source()):
        response = client.get(
            "/v1/export/test-tenant/targets",
            params={"artifact": "artifact-1", "version": "1.0.0"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["artifact"] == "artifact-1"
    assert body["version"] == "1.0.0"
    assert body["version_record_id"] == "rev-uuid-1"
    assert body["version_label"] == "1.0.0"

    by_key = {t["descriptor"]["key"]: t for t in body["targets"]}
    assert "openapi" in by_key and "sample" in by_key

    openapi = by_key["openapi"]
    assert openapi["descriptor"]["label"]
    assert openapi["descriptor"]["format"] == "openapi-3.1"
    assert openapi["capability_profile"]["operations"] is True
    assert "options_schema" in openapi
    assert "default_options" in openapi
    assert openapi["fidelity"]["tier"] == "lossless"
    assert openapi["fidelity"]["preserved_percent"] == 100

    sample = by_key["sample"]
    assert sample["fidelity"]["tier"] == "types-only"


def test_list_export_targets_is_sorted_by_key():
    with patch("app.export_routes.load_export_source", return_value=_source()):
        response = client.get(
            "/v1/export/test-tenant/targets",
            params={"artifact": "artifact-1"},
        )
    keys = [t["descriptor"]["key"] for t in response.json()["targets"]]
    assert keys == sorted(keys)


def test_list_export_targets_requires_authentication():
    app.dependency_overrides.clear()
    response = client.get(
        "/v1/export/test-tenant/targets",
        params={"artifact": "artifact-1"},
    )
    assert response.status_code == 401


def test_list_export_targets_requires_artifact_param():
    response = client.get("/v1/export/test-tenant/targets")
    assert response.status_code == 422


def test_openapi_to_openapi_is_lossless():
    """Acceptance: OpenAPI → OpenAPI is lossless for an operation-bearing REST source."""
    with patch("app.export_routes.load_export_source", return_value=_source()):
        response = client.get(
            "/v1/export/test-tenant/targets",
            params={"artifact": "artifact-1"},
        )
    by_key = {t["descriptor"]["key"]: t for t in response.json()["targets"]}
    assert by_key["openapi"]["fidelity"]["tier"] == "lossless"
    assert by_key["openapi"]["fidelity"]["preserved_percent"] == 100


def test_openapi_to_avro_is_types_only():
    """Acceptance: OpenAPI → Avro is types-only (schema-only target drops operations)."""
    with patch("app.export_routes.load_export_source", return_value=_source()):
        response = client.get(
            "/v1/export/test-tenant/targets",
            params={"artifact": "artifact-1"},
        )
    by_key = {t["descriptor"]["key"]: t for t in response.json()["targets"]}
    assert "avro" in by_key
    assert by_key["avro"]["fidelity"]["tier"] == "types-only"
    assert by_key["avro"]["capability_profile"]["operations"] is False
    assert AvroEmitter.capability_profile().operations is False


def test_new_emitter_appears_without_route_changes():
    """Registering an emitter server-side surfaces a new entry — the UI card contract."""

    class _ProbeEmitter(Emitter):
        key = "probe-target"
        format = "probe-target-1"
        label = "Probe Target"
        description = "A throwaway emitter used only by this test."
        icon = "boxes"
        paradigm = ApiParadigm.REST

        @classmethod
        def capability_profile(cls) -> CapabilityProfile:
            return CapabilityProfile(operations=True)

        def emit(self, api, *, opts=None) -> EmitResult:  # pragma: no cover - not exercised
            return EmitResult.from_document({})

    register_emitter(_ProbeEmitter)
    try:
        with patch("app.export_routes.load_export_source", return_value=_source()):
            response = client.get(
                "/v1/export/test-tenant/targets",
                params={"artifact": "artifact-1"},
            )
        by_key = {t["descriptor"]["key"]: t for t in response.json()["targets"]}
        assert "probe-target" in by_key
        probe = by_key["probe-target"]
        assert probe["descriptor"]["label"] == "Probe Target"
        assert probe["descriptor"]["icon"] == "boxes"
        assert probe["fidelity"]["tier"] in {"lossless", "lossy", "types-only"}
    finally:
        _REGISTRY.pop("probe-target-1", None)


def test_list_export_targets_404_when_source_not_found():
    with patch(
        "app.export_routes.load_export_source",
        side_effect=ExportSourceError("Artifact 'nope' was not found.", status_code=404),
    ):
        response = client.get(
            "/v1/export/test-tenant/targets",
            params={"artifact": "nope"},
        )
    assert response.status_code == 404
