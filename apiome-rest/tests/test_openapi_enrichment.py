"""Tests for OpenAPI spec enrichment (dogfooding schema_lint)."""

from __future__ import annotations

import yaml

from app.openapi_enrichment import enrich_openapi_spec
from app.schema_lint import lint_openapi_spec


def _load_spec() -> dict:
    with open("openapi.yaml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_enriched_spec_scores_a_or_better() -> None:
    result = lint_openapi_spec(enrich_openapi_spec(_load_spec()))
    assert result.score >= 90, result.rule_hits
    assert result.grade == "A"


def test_primitive_class_and_operation_schemas_are_documented() -> None:
    spec = enrich_openapi_spec(_load_spec())
    schemas = spec["components"]["schemas"]
    for name in (
        "PrimitiveSchema",
        "ClassSchema",
        "OperationSchema",
        "PathSchema",
        "ProjectPropertySchema",
    ):
        assert schemas[name]["description"].strip()
        for prop_name, prop_schema in schemas[name]["properties"].items():
            if "$ref" in prop_schema and "type" not in prop_schema:
                continue
            assert prop_schema.get("description"), f"{name}.{prop_name} missing description"


def test_renames_non_pascal_case_component_schemas() -> None:
    spec = enrich_openapi_spec(_load_spec())
    schemas = spec["components"]["schemas"]
    assert "MockScenarioSpec-Input" not in schemas
    assert "MockScenarioSpecInput" in schemas
    assert "SpecImportMultipartUploadBody" in schemas
