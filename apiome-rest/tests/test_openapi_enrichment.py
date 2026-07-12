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


def _missing_field_descriptions(spec: dict) -> list[str]:
    missing: list[str] = []
    http_methods = {"get", "put", "post", "delete", "patch", "options", "head", "trace"}

    def walk_schema(schema: dict, path: str, schema_name: str) -> None:
        if not isinstance(schema, dict):
            return
        if _is_ref_only(schema):
            return
        props = schema.get("properties")
        if isinstance(props, dict):
            for prop_name, prop_schema in props.items():
                ppath = f"{path}.properties.{prop_name}"
                if isinstance(prop_schema, dict):
                    if not _nonempty_str(prop_schema.get("description")):
                        missing.append(ppath)
                    walk_schema(prop_schema, ppath, schema_name)
        if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
            walk_schema(schema["items"], path + ".items", schema_name)

    for sname, schema in spec.get("components", {}).get("schemas", {}).items():
        if isinstance(schema, dict):
            walk_schema(schema, f"components.schemas.{sname}", sname)

    for ppath, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in http_methods or not isinstance(operation, dict):
                continue
            op_path = f"paths.{ppath}.{method}"
            for param in operation.get("parameters") or []:
                if isinstance(param, dict) and not _nonempty_str(param.get("description")):
                    missing.append(f"{op_path}.parameters.{param.get('name')}")
                schema = param.get("schema") if isinstance(param, dict) else None
                if isinstance(schema, dict):
                    walk_schema(schema, f"{op_path}.parameters.{param.get('name')}.schema", "Parameter")
            rb = operation.get("requestBody")
            if isinstance(rb, dict) and not _nonempty_str(rb.get("description")):
                missing.append(f"{op_path}.requestBody")

    return missing


def _nonempty_str(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_ref_only(schema: dict) -> bool:
    return "$ref" in schema and "type" not in schema and "properties" not in schema


def test_parameters_and_request_bodies_have_descriptions() -> None:
    spec = enrich_openapi_spec(_load_spec())
    missing = _missing_field_descriptions(spec)
    assert missing == [], missing[:20]
