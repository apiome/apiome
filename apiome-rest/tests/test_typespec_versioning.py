"""Tests for TypeSpec versioning — MFI-14.4 (#3797).

The ``versioned`` recording (``tests/fixtures/typespec_compile/recordings/versioned.json``) is the real
``@typespec/compiler`` 0.65.0 (+ ``@typespec/versioning``) compiling
``tests/fixtures/typespec_compile/versioned`` with Apiome's configuration: three versions, each emitted
as ``openapi.<version>.json``. :func:`test_live_versioned_compile_matches_the_recording` runs the real
compiler when it is installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest

from app.fileset import IntakeFileset
from app.typespec_compile import compile_typespec_set
from app.typespec_import_source import TypeSpecImportSource
from app.typespec_versioning import (
    MAX_RECORDED_FINDINGS,
    TypeSpecVersion,
    declared_versions,
    order_versions,
    version_changes,
)
from tests.test_typespec_compile import _live_compiler_ready, _members, _replay, libraries  # noqa: F401

_SET_DIR = Path(__file__).resolve().parent / "fixtures" / "typespec_compile" / "versioned"
_VERSIONS = ["2023-01-01", "2023-06-01", "2024-01-01"]


def _versioned_members() -> Dict[str, str]:
    return {
        str(path.relative_to(_SET_DIR)): path.read_text(encoding="utf-8")
        for path in sorted(_SET_DIR.rglob("*"))
        if path.is_file()
    }


def _doc(version: str, **paths: Dict) -> Dict:
    return {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": version},
        "paths": paths,
        "components": {"schemas": {}},
    }


# ===========================================================================
# Declared versions and their order
# ===========================================================================


def test_declared_versions_read_values_names_comments_and_decorators():
    sources = {
        "main.tsp": "@versioned(Versions)\nnamespace N;\n",
        "versions.tsp": (
            'enum Versions {\n  /** first */ v1: "2023-01-01",\n  // a comment\n  @doc("x") preview,\n'
            '  `v-3`: "3.0",\n}\n'
        ),
    }
    assert declared_versions(sources) == ["2023-01-01", "preview", "3.0"]


def test_a_qualified_versioned_reference_and_an_unversioned_service():
    assert declared_versions({"a.tsp": "@versioned(My.Ns.Releases) namespace N; enum Releases { a, b }"}) == ["a", "b"]
    assert declared_versions({"a.tsp": "namespace N; enum Versions { a, b }"}) == []
    assert declared_versions({"a.tsp": "@versioned(Missing) namespace N;"}) == []


def test_documents_are_ordered_by_the_enum_then_naturally():
    documents = [_doc("v10"), _doc("v2"), _doc("2023-06-01"), _doc("2023-01-01")]
    ordered = order_versions(documents, ["2023-01-01", "2023-06-01"])
    assert [version for version, _ in ordered] == ["2023-01-01", "2023-06-01", "v2", "v10"]


def test_version_changes_grade_each_step():
    pet = {"type": "object", "properties": {"id": {"type": "string"}, "code": {"type": "string"}}}
    v1 = _doc("1", **{"/pets": {"get": {"responses": {"200": {"description": "ok"}}}}})
    v1["components"]["schemas"]["Pet"] = pet
    v2 = _doc("2", **{"/pets": {"get": {"responses": {"200": {"description": "ok"}}}}})
    v2["components"]["schemas"]["Pet"] = {"type": "object", "properties": {"id": {"type": "string"}}}
    versions = [
        TypeSpecVersion(version="1", openapi=v1, openapi_sha256="a"),
        TypeSpecVersion(version="2", openapi=v2, openapi_sha256="b"),
    ]
    (step,) = version_changes(versions)
    assert (step["from"], step["to"], step["overall"]) == ("1", "2", "breaking")
    assert step["counts"] == {"breaking": 1}
    assert step["findings"][0]["rule"] == "property_removed"
    assert step["finding_count"] == 1


def test_version_change_findings_are_capped():
    v1 = _doc("1", **{f"/p{i}": {} for i in range(MAX_RECORDED_FINDINGS + 5)})
    v2 = _doc("2")
    (step,) = version_changes([TypeSpecVersion("1", v1, "a"), TypeSpecVersion("2", v2, "b")])
    assert len(step["findings"]) == MAX_RECORDED_FINDINGS
    assert step["finding_count"] == MAX_RECORDED_FINDINGS + 5


def test_a_single_version_has_no_steps():
    assert version_changes([TypeSpecVersion("1", _doc("1"), "a")]) == []


# ===========================================================================
# Compile → catalog item (recorded)
# ===========================================================================


def test_a_versioned_compile_keeps_every_version_newest_last(monkeypatch, libraries):  # noqa: F811
    calls = _replay(monkeypatch, "versioned")
    compiled = compile_typespec_set(_versioned_members(), "main.tsp")
    assert "openapi.{version}.json" in calls[0]["tspconfig"]
    assert [v.version for v in compiled.versions] == _VERSIONS
    assert compiled.openapi is compiled.versions[-1].openapi
    assert compiled.openapi["info"]["version"] == "2024-01-01"


def test_the_catalog_item_records_the_versions_and_their_steps(monkeypatch, libraries):  # noqa: F811
    _replay(monkeypatch, "versioned")
    adapter = TypeSpecImportSource()
    model = adapter.normalize(adapter.parse_fileset(IntakeFileset.from_members(_versioned_members(), root="main.tsp")))
    assert [v["version"] for v in model.extras["typespec_versions"]] == _VERSIONS
    assert model.extras["typespec_latest_version"] == "2024-01-01"
    steps = model.extras["typespec_version_changes"]
    assert [(s["from"], s["to"], s["overall"]) for s in steps] == [
        ("2023-01-01", "2023-06-01", "safe"),
        ("2023-06-01", "2024-01-01", "breaking"),
    ]
    assert {f["rule"] for f in steps[0]["findings"]} == {"property_added", "path_added"}
    assert [f["path"] for f in steps[1]["findings"]] == ["components.schemas.Pet.properties.legacyCode"]
    assert sorted(model.raw["openapi_versions"]) == _VERSIONS
    # The item itself is the newest version: `GET /pets/{id}` exists and `legacyCode` does not.
    assert any(op.http_path == "/pets/{id}" for service in model.services for op in service.operations)


def test_an_unversioned_project_records_no_versions(monkeypatch, libraries):  # noqa: F811
    _replay(monkeypatch, "petstore")
    adapter = TypeSpecImportSource()
    model = adapter.normalize(adapter.parse_fileset(IntakeFileset.from_members(_members(), root="main.tsp")))
    assert not {"typespec_versions", "typespec_version_changes", "typespec_latest_version"} & set(model.extras)
    assert "openapi_versions" not in (model.raw or {})


# ===========================================================================
# Live compiler
# ===========================================================================


@pytest.mark.skipif(not _live_compiler_ready(), reason="tsp with @typespec/openapi3 is not installed")
def test_live_versioned_compile_matches_the_recording():
    compiled = compile_typespec_set(_versioned_members(), "main.tsp")
    assert [v.version for v in compiled.versions] == _VERSIONS
