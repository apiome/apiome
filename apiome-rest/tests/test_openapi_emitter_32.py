"""OpenAPI 3.2 output mode — MFX-9.5 (#4342).

``openapi_version="3.2"`` writes an OpenAPI 3.2.0 document that carries natively what the canonical model
holds that only 3.2 can express. Pinned against two imported 3.2 documents in
``fixtures/openapi_32_output/`` (``query-and-additional.yaml``: a ``QUERY`` operation and two
``additionalOperations``; ``tag-tree.yaml``: a tag hierarchy):

* **3.2 mode** — ``openapi: 3.2.0``; ``query`` and ``additionalOperations`` path-item keys and a ``tags``
  list with ``parent`` / ``summary`` / ``kind``; the document passes the bundled 3.2 meta-schema and the
  export gate, and re-imports to the same operations and tag hierarchy (a 3.2 → 3.2 round trip);
* **3.1 / 3.0 / 2.0** — the methods are stashed on ``x-apiome-*`` extensions and the hierarchy is not
  written; each is a recorded loss, and the fidelity report (computed for the chosen version) reports the
  operations ``APPROX`` and the hierarchy ``DROP``, which the 3.2 report does not;
* the default stays 3.1.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

import pytest
import yaml

from app.canonical_model import CanonicalApi
from app.emitter import load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.lossiness import LossinessKind
from app.openapi_emitter import (
    OPENAPI_32_VERSION,
    X_ADDITIONAL_OPERATIONS,
    X_QUERY_OPERATION,
    OpenApiEmitOptions,
    OpenApiEmitter,
)
from app.openapi_normalizer import OpenApiNormalizer
from app.openapi_validator import validate_openapi_document

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "openapi_32_output"


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()


def _imported(name: str) -> CanonicalApi:
    """An imported 3.2 fixture's canonical model."""
    return OpenApiNormalizer().normalize(yaml.safe_load((_FIXTURES / name).read_text(encoding="utf-8")))


def _emit(api: CanonicalApi, version: str) -> Any:
    return OpenApiEmitter().emit(api, opts=OpenApiEmitOptions(openapi_version=version))


def _methods(api: CanonicalApi) -> List[tuple[str, str]]:
    return sorted((op.http_method or "", op.http_path or "") for op in api.operations())


def _report(api: CanonicalApi, version: str):
    return compute_lossiness_for_emitter(api, OpenApiEmitter, options={"openapi_version": version})


# ===========================================================================
# The 3.2 mode
# ===========================================================================


def test_the_default_stays_31() -> None:
    assert OpenApiEmitOptions().openapi_version == "3.1"
    assert _emit(_imported("query-and-additional.yaml"), "3.1").document["openapi"] == "3.1.0"


def test_query_and_additional_operations_are_written_natively() -> None:
    result = _emit(_imported("query-and-additional.yaml"), "3.2")
    document = result.document
    assert document["openapi"] == OPENAPI_32_VERSION == "3.2.0"
    item = document["paths"]["/search"]
    assert item["query"]["operationId"] == "runSearch"
    assert sorted(item["additionalOperations"]) == ["PURGE", "REPORT"]
    assert item["additionalOperations"]["REPORT"]["deprecated"] is True
    assert X_QUERY_OPERATION not in item and X_ADDITIONAL_OPERATIONS not in item
    assert "openapi-3.2-http-method" not in {loss.subject for loss in result.losses}


def test_the_tag_hierarchy_is_written_natively() -> None:
    tags = _emit(_imported("tag-tree.yaml"), "3.2").document["tags"]
    by_name = {tag["name"]: tag for tag in tags}
    assert [tag["name"] for tag in tags] == sorted(by_name)
    assert by_name["invoice-lines"] == {"name": "invoice-lines", "parent": "invoices", "kind": "nav"}
    assert by_name["invoices"] == {"name": "invoices", "summary": "Invoices", "parent": "billing"}
    assert by_name["internal"] == {"name": "internal", "kind": "audience"}


@pytest.mark.parametrize("name", ["query-and-additional.yaml", "tag-tree.yaml"])
def test_a_32_document_passes_the_32_meta_schema(name: str) -> None:
    assert validate_openapi_document(_emit(_imported(name), "3.2").document) == []


@pytest.mark.parametrize("name", ["query-and-additional.yaml", "tag-tree.yaml"])
async def test_a_32_document_passes_the_export_gate(name: str) -> None:
    api = _imported(name)
    verdict = await validate_emitted_artifact("openapi-3.1", _emit(api, "3.2"), api=api,
                                              options={"openapi_version": "3.2"})
    assert verdict.validated and verdict.valid, verdict.errors


def test_a_32_round_trip_keeps_the_operations_and_the_tag_hierarchy() -> None:
    search = _imported("query-and-additional.yaml")
    back = OpenApiNormalizer().normalize(_emit(search, "3.2").document)
    assert back.format == "openapi-3.2"
    assert _methods(back) == _methods(search) == [
        ("GET", "/search"), ("PURGE", "/search"), ("QUERY", "/search"), ("REPORT", "/search")]
    billing = _imported("tag-tree.yaml")
    again = OpenApiNormalizer().normalize(_emit(billing, "3.2").document)
    assert again.extras["tagHierarchy"] == billing.extras["tagHierarchy"]


def test_a_source_with_nothing_32_only_writes_the_same_document_bar_the_version() -> None:
    api = _imported("query-and-additional.yaml")
    api.services = [s for s in api.services]
    for service in api.services:
        service.operations = [op for op in service.operations if op.http_method == "GET"]
    v31, v32 = _emit(api, "3.1").document, _emit(api, "3.2").document
    assert {**v32, "openapi": "3.1.0"} == v31


# ===========================================================================
# Below 3.2: stashed / dropped, and reported
# ===========================================================================


@pytest.mark.parametrize("version", ["3.1", "3.0", "2.0"])
def test_below_32_the_methods_are_stashed_and_the_hierarchy_dropped_as_losses(version: str) -> None:
    search = _emit(_imported("query-and-additional.yaml"), version)
    assert "openapi-3.2-http-method" in {loss.subject for loss in search.losses}
    billing = _emit(_imported("tag-tree.yaml"), version)
    assert "openapi-3.2-tag-hierarchy" in {loss.subject for loss in billing.losses}
    assert "tags" not in billing.document


def test_31_keeps_the_methods_on_extensions() -> None:
    item = _emit(_imported("query-and-additional.yaml"), "3.1").document["paths"]["/search"]
    assert item[X_QUERY_OPERATION]["operationId"] == "runSearch"
    assert sorted(item[X_ADDITIONAL_OPERATIONS]) == ["PURGE", "REPORT"]
    assert "query" not in item and "additionalOperations" not in item


@pytest.mark.parametrize("version", ["3.1", "3.0", "2.0"])
def test_below_32_the_report_has_the_methods_approx_and_the_hierarchy_dropped(version: str) -> None:
    report = _report(_imported("query-and-additional.yaml"), version)
    methods = [item for item in report.items
               if item.kind is LossinessKind.APPROX and "export OpenAPI 3.2" in item.message]
    assert sorted(item.target_mapping for item in methods) == [
        f"PURGE → {X_ADDITIONAL_OPERATIONS}", f"QUERY → {X_QUERY_OPERATION}", f"REPORT → {X_ADDITIONAL_OPERATIONS}"]
    assert all(f"OpenAPI {version}" in item.message for item in methods)

    tags = _report(_imported("tag-tree.yaml"), version)
    drops = [item for item in tags.items if item.target_mapping == "tag hierarchy → dropped (OpenAPI 3.2 only)"]
    assert len(drops) == 1 and drops[0].kind is LossinessKind.DROP and "5 tag(s)" in drops[0].message


@pytest.mark.parametrize("name", ["query-and-additional.yaml", "tag-tree.yaml"])
def test_the_32_report_has_none_of_them(name: str) -> None:
    report = _report(_imported(name), "3.2")
    assert not [item for item in report.items if "OpenAPI 3.2" in (item.message or "")]


def test_the_preview_tier_follows_the_chosen_version() -> None:
    api = _imported("query-and-additional.yaml")
    preview_32 = build_export_fidelity(api, OpenApiEmitter, options={"openapi_version": "3.2"})
    preview_31 = build_export_fidelity(api, OpenApiEmitter, options={"openapi_version": "3.1"})
    assert preview_32.summary.approximated < preview_31.summary.approximated
    assert preview_32.summary.tier.value == "lossless"


def test_invalid_options_fall_back_to_the_31_report() -> None:
    api = _imported("query-and-additional.yaml")
    bad = compute_lossiness_for_emitter(api, OpenApiEmitter, options={"openapi_version": "9.9"})
    default = compute_lossiness_for_emitter(api, OpenApiEmitter)
    assert [i.model_dump() for i in bad.items] == [i.model_dump() for i in default.items]

