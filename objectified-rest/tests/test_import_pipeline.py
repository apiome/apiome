"""Unit tests for the import pipeline staging core (#3460).

Covers ``detect_candidates`` per source kind and ``build_staged_import``. These
run on parsed documents (no network/DB), so they assert the staged candidates,
pointers, ref counts, and warnings directly.
"""

import pytest

from app.import_pipeline import (
    build_staged_import,
    detect_candidates,
)

# ===========================================================================
# json-schema detection
# ===========================================================================


def test_json_schema_defs_become_candidates():
    doc = {
        "$defs": {
            "Money": {"type": "object", "properties": {"c": {"$ref": "../primitives/string"}}},
            "Date": {"type": "string"},
        }
    }
    candidates, warnings = detect_candidates(doc, "json-schema")
    by_name = {c.name: c for c in candidates}
    assert set(by_name) == {"Money", "Date"}
    assert by_name["Money"].pointer == "#/$defs/Money"
    assert by_name["Money"].ref_count == 1
    assert by_name["Date"].ref_count == 0
    assert warnings == []


def test_json_schema_legacy_definitions_become_candidates():
    doc = {"definitions": {"A": {"type": "string"}}}
    candidates, _ = detect_candidates(doc, "json-schema")
    assert candidates[0].name == "A"
    assert candidates[0].pointer == "#/definitions/A"


def test_json_schema_bare_document_is_single_candidate():
    doc = {"type": "object", "title": "Customer", "properties": {"id": {"$ref": "x"}}}
    candidates, _ = detect_candidates(doc, "json-schema")
    assert len(candidates) == 1
    assert candidates[0].name == "Customer"
    assert candidates[0].pointer == "#"
    assert candidates[0].ref_count == 1


def test_json_schema_bare_name_falls_back_to_label():
    doc = {"type": "object"}
    candidates, _ = detect_candidates(doc, "json-schema", source_label="path/widget.json")
    assert candidates[0].name == "widget"


# ===========================================================================
# type-def-bundle detection
# ===========================================================================


def test_bundle_types_container_becomes_candidates():
    doc = {"types": {"Order": {"type": "object"}, "Line": {"type": "object"}}}
    candidates, warnings = detect_candidates(doc, "type-def-bundle")
    assert {c.name for c in candidates} == {"Order", "Line"}
    assert candidates[0].pointer.startswith("#/types/")
    assert warnings == []


def test_bundle_empty_warns_with_no_candidates():
    candidates, warnings = detect_candidates({"meta": "x"}, "type-def-bundle")
    assert candidates == []
    assert warnings and "types" in warnings[0]


# ===========================================================================
# openapi detection
# ===========================================================================


def test_openapi_components_schemas_become_candidates():
    doc = {"openapi": "3.1.0", "components": {"schemas": {"Pet": {"type": "object"}}}}
    candidates, warnings = detect_candidates(doc, "openapi")
    assert candidates[0].name == "Pet"
    assert candidates[0].pointer == "#/components/schemas/Pet"
    assert warnings == []


def test_openapi_without_components_warns():
    candidates, warnings = detect_candidates({"openapi": "3.1.0"}, "openapi")
    assert candidates == []
    assert warnings and "components.schemas" in warnings[0]


# ===========================================================================
# unknown kind / build_staged_import
# ===========================================================================


def test_detect_unknown_kind_raises():
    with pytest.raises(ValueError, match="Invalid source_kind"):
        detect_candidates({}, "rdf")


def test_build_staged_import_assembles_result_and_report():
    doc = {"$defs": {"A": {"type": "string"}, "B": {"type": "object"}}}
    staged = build_staged_import(
        doc,
        source_kind="json-schema",
        source_method="paste",
        source_label="bundle.json",
        target_namespace="acme/v0/types",
    )
    assert staged.status == "staged"
    assert staged.detected_count == 2
    assert staged.source_method == "paste"
    assert staged.target_namespace == "acme/v0/types"

    report = staged.report()
    assert report["status"] == "staged"
    assert report["detected_count"] == 2
    assert {s["name"] for s in report["staged"]} == {"A", "B"}


# ===========================================================================
# json-schema parser integration (#3461) — internal refs + validation report
# ===========================================================================


def test_json_schema_candidates_carry_internal_refs_and_validation():
    doc = {
        "$defs": {
            "Money": {"properties": {"c": {"$ref": "#/$defs/Currency"}}},
            "Currency": {"type": "string"},
            "Bad": {"type": "stringg"},
        }
    }
    candidates, warnings = detect_candidates(doc, "json-schema")
    by_name = {c.name: c for c in candidates}
    # Intra-doc #/$defs ref captured for the rewrite stage (#3463).
    assert by_name["Money"].internal_refs == [
        {"relative_ref": "#/$defs/Currency", "resolved_target": "Currency", "status": "internal"}
    ]
    # Per-candidate draft 2020-12 validation report.
    assert by_name["Currency"].valid is True
    assert by_name["Bad"].valid is False
    assert by_name["Bad"].validation_errors[0]["path"] == "type"
    assert warnings == []


def test_staged_report_includes_internal_refs_and_validity():
    doc = {"$defs": {"Money": {"properties": {"c": {"$ref": "#/$defs/Money"}}}}}
    staged = build_staged_import(doc, source_kind="json-schema", source_method="paste")
    entry = staged.report()["staged"][0]
    assert entry["internal_refs"][0]["resolved_target"] == "Money"
    assert entry["valid"] is True
    assert entry["validation_errors"] == []
