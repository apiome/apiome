"""Unit tests for version-aware Arazzo (1.0.x / 1.1.x) local validation."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from apiome_cli.import_.arazzo import (
    ArazzoStructureError,
    arazzo_version_line,
    load_and_validate_arazzo_file,
    supported_arazzo_versions,
    validate_arazzo_structure,
)

_FIXTURES = Path(__file__).parent / "fixtures"

_VALID_ARAZZO = {
    "arazzo": "1.0.0",
    "info": {"title": "Checkout Flow", "version": "1.0.0"},
    "sourceDescriptions": [
        {
            "name": "openapi",
            "url": "https://example.test/openapi.json",
            "type": "openapi",
        }
    ],
    "workflows": [
        {
            "workflowId": "checkout",
            "steps": [{"stepId": "createCart", "operationId": "createCart"}],
        }
    ],
}


def test_validate_arazzo_structure_accepts_valid_document() -> None:
    """Valid Arazzo 1.0.x documents pass schema validation."""
    validate_arazzo_structure(_VALID_ARAZZO)


def test_validate_arazzo_structure_rejects_missing_info() -> None:
    """Missing required fields raise ArazzoStructureError with a pointer."""
    document = {**_VALID_ARAZZO}
    del document["info"]
    with pytest.raises(ArazzoStructureError) as exc_info:
        validate_arazzo_structure(document)
    assert "info" in exc_info.value.message.lower() or "At /" in exc_info.value.message


def _with_version(version: str) -> dict:
    """Return a copy of the valid baseline document declaring *version*."""
    document = copy.deepcopy(_VALID_ARAZZO)
    document["arazzo"] = version
    return document


def _with_async_source(version: str) -> dict:
    """Return a document declaring *version* that adds an AsyncAPI source description."""
    document = _with_version(version)
    document["sourceDescriptions"].append(
        {"name": "events", "url": "https://example.test/asyncapi.yaml", "type": "asyncapi"}
    )
    return document


@pytest.mark.parametrize("version", ["1.0.0", "1.0.1", "1.1.0", "1.1.1"])
def test_validate_arazzo_structure_accepts_each_supported_version(version: str) -> None:
    """Both supported lines validate, each against its own vendored schema."""
    validate_arazzo_structure(_with_version(version))


def test_supported_arazzo_versions_names_both_lines() -> None:
    """The CLI advertises the same lines the REST importer reads."""
    assert supported_arazzo_versions() == ("1.0.x", "1.1.x")


@pytest.mark.parametrize(
    ("version", "line"),
    [("1.0.1", (1, 0)), ("1.1.0", (1, 1)), ("1.1.0-rc1", (1, 1))],
)
def test_arazzo_version_line_ignores_patch(version: str, line: tuple[int, int]) -> None:
    """The validator picks its schema by major.minor; patch and pre-release are ignored."""
    assert arazzo_version_line({"arazzo": version}) == line


def test_validate_arazzo_structure_accepts_asyncapi_source_in_1_1() -> None:
    """An AsyncAPI source description is valid in a document that declares 1.1."""
    validate_arazzo_structure(_with_async_source("1.1.0"))


def test_validate_arazzo_structure_rejects_asyncapi_source_in_1_0() -> None:
    """The 1.0 schema still governs 1.0 documents: `type: asyncapi` is 1.1-only."""
    with pytest.raises(ArazzoStructureError) as exc_info:
        validate_arazzo_structure(_with_async_source("1.0.1"))
    assert exc_info.value.pointer is not None
    assert exc_info.value.pointer.startswith("/sourceDescriptions/1")


@pytest.mark.parametrize("version", ["2.0.0", "1.2.0", "0.9.0"])
def test_validate_arazzo_structure_rejects_unsupported_version(version: str) -> None:
    """A version line with no vendored schema fails at /arazzo and names the supported lines."""
    with pytest.raises(ArazzoStructureError) as exc_info:
        validate_arazzo_structure(_with_version(version))
    assert exc_info.value.pointer == "/arazzo"
    assert "1.0.x, 1.1.x" in exc_info.value.message


@pytest.mark.parametrize("version", ["latest", "1", ""])
def test_validate_arazzo_structure_rejects_unparseable_version(version: str) -> None:
    """A marker that is not major.minor[.patch] is a structural error, not a crash."""
    with pytest.raises(ArazzoStructureError) as exc_info:
        validate_arazzo_structure(_with_version(version))
    assert exc_info.value.pointer == "/arazzo"


def test_validate_arazzo_structure_rejects_missing_version() -> None:
    """A document with no `arazzo` field is rejected at the document root."""
    document = copy.deepcopy(_VALID_ARAZZO)
    del document["arazzo"]
    with pytest.raises(ArazzoStructureError) as exc_info:
        validate_arazzo_structure(document)
    assert exc_info.value.pointer == "/"


@pytest.mark.parametrize(
    ("fixture", "version"),
    [("checkout.arazzo.yaml", "1.0.0"), ("order-to-cash-1.1.arazzo.yaml", "1.1.0")],
)
def test_arazzo_file_round_trips_without_downgrade(
    tmp_path: Path, fixture: str, version: str
) -> None:
    """Load → validate → write → reload keeps the declared version and every source."""
    document = load_and_validate_arazzo_file(str(_FIXTURES / fixture))
    assert document["arazzo"] == version

    for suffix, dump in ((".json", json.dumps), (".yaml", yaml.safe_dump)):
        written = tmp_path / f"roundtrip{suffix}"
        written.write_text(dump(document), encoding="utf-8")
        reloaded = load_and_validate_arazzo_file(str(written))
        assert reloaded == document
        assert reloaded["arazzo"] == version


def test_arazzo_1_1_fixture_keeps_its_asyncapi_source() -> None:
    """The 1.1 fixture validates with its AsyncAPI source description intact."""
    document = load_and_validate_arazzo_file(str(_FIXTURES / "order-to-cash-1.1.arazzo.yaml"))
    types = [source["type"] for source in document["sourceDescriptions"]]
    assert types == ["openapi", "asyncapi"]
