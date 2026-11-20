"""Arazzo version option on the legacy generator — COA-1.1 (#7037).

The legacy generator behind ``GET /v1/arazzo/{tenant}/{project}/{version}`` used to hard-code
``arazzo: 1.0.1``. It now takes an ``arazzo_version`` option and follows the same rules as the
Arazzo emitter:

* an explicit version (1.0.x or 1.1.x) is written as given — never downgraded;
* with no version, ``1.1.0`` when a source description is AsyncAPI, otherwise ``1.0.1``;
* a 1.0.x request for a document with an AsyncAPI source is rejected (1.0 cannot express it).

Each case is checked for 1.0.1 and 1.1.0, and a 1.1 document with an AsyncAPI source is
round-tripped through the Arazzo importer to prove the version and sources survive.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.arazzo_generator import (
    generate_arazzo_spec,
    generate_class_arazzo_spec,
    resolve_generator_arazzo_version,
)
from app.arazzo_import_source import ArazzoImportSource
from app.arazzo_roundtrip import arazzo_schema_violations
from app.arazzo_spec import ArazzoVersionError
from app.main import app

_CLASSES: List[Dict[str, Any]] = [
    {"name": "User", "description": "A user in the system"},
    {"name": "Order", "description": "An order"},
]

_OPENAPI_SOURCE = {"name": "orders", "type": "openapi", "url": "https://api.example.test/openapi.yaml"}
_ASYNCAPI_SOURCE = {"name": "orderEvents", "type": "asyncapi", "url": "https://events.example.test/asyncapi.yaml"}


def _sources_only(document: Dict[str, Any]) -> Dict[str, Any]:
    """The version marker and source descriptions of a generated document, for schema checks.

    The generator's CRUD step shape predates the vendored schemas, so the schema check here
    targets what this ticket changes: the ``arazzo`` marker and ``sourceDescriptions``.
    """
    return {
        "arazzo": document["arazzo"],
        "info": {"title": document["info"]["title"], "version": document["info"]["version"]},
        "sourceDescriptions": document["sourceDescriptions"],
        "workflows": [
            {"workflowId": "probe", "steps": [{"stepId": "probe", "operationId": "probe"}]}
        ],
    }


# ---------------------------------------------------------------------------
# Version resolution
# ---------------------------------------------------------------------------


def test_default_is_1_0_1_for_openapi_only_sources() -> None:
    assert resolve_generator_arazzo_version(None, [_OPENAPI_SOURCE]) == "1.0.1"
    assert resolve_generator_arazzo_version("  ", [_OPENAPI_SOURCE]) == "1.0.1"


def test_default_is_1_1_0_when_a_source_is_asyncapi() -> None:
    assert resolve_generator_arazzo_version(None, [_OPENAPI_SOURCE, _ASYNCAPI_SOURCE]) == "1.1.0"


@pytest.mark.parametrize("version", ["1.0.0", "1.0.1", "1.1.0", "1.1.1"])
def test_explicit_version_is_written_as_given(version: str) -> None:
    assert resolve_generator_arazzo_version(f" {version} ", [_OPENAPI_SOURCE]) == version


def test_explicit_1_1_is_kept_for_asyncapi_sources() -> None:
    assert resolve_generator_arazzo_version("1.1.0", [_ASYNCAPI_SOURCE]) == "1.1.0"


def test_explicit_1_0_with_asyncapi_source_is_rejected() -> None:
    with pytest.raises(ArazzoVersionError, match="AsyncAPI"):
        resolve_generator_arazzo_version("1.0.1", [_OPENAPI_SOURCE, _ASYNCAPI_SOURCE])


@pytest.mark.parametrize("version", ["2.0.0", "1.2.0", "1.1", "latest"])
def test_unsupported_or_partial_version_is_rejected(version: str) -> None:
    with pytest.raises(ArazzoVersionError):
        resolve_generator_arazzo_version(version, [_OPENAPI_SOURCE])


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------


def test_generate_arazzo_spec_keeps_1_0_1_by_default() -> None:
    spec = generate_arazzo_spec("acme", "shop", "1.0.0", _CLASSES)
    assert spec["arazzo"] == "1.0.1"
    assert spec["sourceDescriptions"][0]["url"] == "/v1/schema/acme/shop/1.0.0"
    assert spec["info"]["description"] == "Generated Arazzo 1.0.1 workflow specification from Apiome Studio"


@pytest.mark.parametrize("version", ["1.0.1", "1.1.0"])
def test_generate_arazzo_spec_writes_the_requested_version(version: str) -> None:
    spec = generate_arazzo_spec("acme", "shop", "1.0.0", _CLASSES, arazzo_version=version)
    assert spec["arazzo"] == version
    assert spec["info"]["description"] == f"Generated Arazzo {version} workflow specification from Apiome Studio"


@pytest.mark.parametrize("version", ["1.0.1", "1.1.0"])
def test_requested_version_marker_is_valid_for_its_schema(version: str) -> None:
    """The written marker selects, and satisfies, the vendored schema for its line."""
    spec = generate_arazzo_spec(
        "acme", "shop", "1.0.0", _CLASSES, arazzo_version=version, source_descriptions=[_OPENAPI_SOURCE]
    )
    assert arazzo_schema_violations(_sources_only(spec)) == []


def test_generate_arazzo_spec_with_asyncapi_source_defaults_to_1_1() -> None:
    spec = generate_arazzo_spec(
        "acme", "shop", "1.0.0", _CLASSES, source_descriptions=[_OPENAPI_SOURCE, _ASYNCAPI_SOURCE]
    )
    assert spec["arazzo"] == "1.1.0"
    assert [s["type"] for s in spec["sourceDescriptions"]] == ["openapi", "asyncapi"]
    assert arazzo_schema_violations(_sources_only(spec)) == []


def test_generate_arazzo_spec_rejects_1_0_for_asyncapi_source() -> None:
    with pytest.raises(ArazzoVersionError):
        generate_arazzo_spec(
            "acme", "shop", "1.0.0", _CLASSES,
            arazzo_version="1.0.1",
            source_descriptions=[_ASYNCAPI_SOURCE],
        )


@pytest.mark.parametrize("version", ["1.0.1", "1.1.0"])
def test_generate_class_arazzo_spec_writes_the_requested_version(version: str) -> None:
    spec = generate_class_arazzo_spec("acme", "shop", "1.0.0", _CLASSES[0], arazzo_version=version)
    assert spec["arazzo"] == version
    assert spec["sourceDescriptions"][0]["url"] == "/v1/schema/acme/shop/1.0.0/User"


def test_generate_class_arazzo_spec_with_asyncapi_source_defaults_to_1_1() -> None:
    spec = generate_class_arazzo_spec(
        "acme", "shop", "1.0.0", _CLASSES[0], source_descriptions=[_OPENAPI_SOURCE, _ASYNCAPI_SOURCE]
    )
    assert spec["arazzo"] == "1.1.0"


# ---------------------------------------------------------------------------
# Round trip through the importer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "sources", "expected_types"),
    [
        ("1.0.1", [_OPENAPI_SOURCE], {"orders": "openapi"}),
        ("1.1.0", [_OPENAPI_SOURCE, _ASYNCAPI_SOURCE], {"orders": "openapi", "orderEvents": "asyncapi"}),
    ],
)
def test_generated_document_round_trips_through_the_importer(
    version: str, sources: List[Dict[str, Any]], expected_types: Dict[str, str]
) -> None:
    """Generate → import keeps the declared version and every source type (no downgrade)."""
    spec = generate_arazzo_spec(
        "acme", "shop", "1.0.0", _CLASSES, arazzo_version=version, source_descriptions=sources
    )
    model = ArazzoImportSource().normalize(spec)
    assert model.extras["arazzo"] == version
    assert model.extras["sourceTypes"] == expected_types


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

_VERSION_ROW = {
    "id": "v-1",
    "version_id": "1.0.0",
    "visibility": "public",
    "published": True,
    "project_description": None,
}


@pytest.fixture()
def client():
    """A test client whose database returns one public, published version."""
    with patch("app.main.db") as db:
        db.get_version_by_slugs.return_value = dict(_VERSION_ROW)
        db.get_classes_for_version.return_value = list(_CLASSES)
        db.get_class_by_name.return_value = dict(_CLASSES[0])
        yield TestClient(app)


@pytest.mark.parametrize("path", ["/v1/arazzo/acme/shop/1.0.0", "/v1/arazzo/acme/shop/1.0.0/User"])
def test_route_defaults_to_1_0_1(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()["arazzo"] == "1.0.1"


@pytest.mark.parametrize("path", ["/v1/arazzo/acme/shop/1.0.0", "/v1/arazzo/acme/shop/1.0.0/User"])
@pytest.mark.parametrize("version", ["1.0.1", "1.1.0"])
def test_route_writes_the_requested_version(client: TestClient, path: str, version: str) -> None:
    response = client.get(path, params={"arazzo_version": version})
    assert response.status_code == 200
    assert response.json()["arazzo"] == version


def test_route_yaml_keeps_the_requested_version(client: TestClient) -> None:
    response = client.get(
        "/v1/arazzo/acme/shop/1.0.0",
        params={"arazzo_version": "1.1.0"},
        headers={"Accept": "application/yaml"},
    )
    assert response.status_code == 200
    assert response.text.startswith("arazzo: 1.1.0")


@pytest.mark.parametrize("path", ["/v1/arazzo/acme/shop/1.0.0", "/v1/arazzo/acme/shop/1.0.0/User"])
def test_route_rejects_an_unsupported_version(client: TestClient, path: str) -> None:
    response = client.get(path, params={"arazzo_version": "2.0.0"})
    assert response.status_code == 400
    assert "1.0.x, 1.1.x" in response.json()["detail"]
