"""Unit tests for schema backward-compatibility analysis (deterministic, no DB)."""

import json

from src.app.schema_compatibility import (
    CompatibilityRules,
    analyze_schema_compatibility,
)


def _min_openapi(components: dict, paths: dict | None = None) -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": "t", "version": "1"},
        "paths": paths or {},
        "components": {"schemas": components},
    }


def test_identical_specs_are_safe():
    spec = _min_openapi({"A": {"type": "object", "properties": {"x": {"type": "string"}}}})
    overall, findings = analyze_schema_compatibility(spec, json.loads(json.dumps(spec)))
    assert overall == "safe"
    assert findings == []


def test_removed_schema_is_breaking():
    base = _min_openapi({"A": {"type": "object"}})
    head = _min_openapi({})
    overall, findings = analyze_schema_compatibility(base, head)
    assert overall == "breaking"
    assert any(f.rule == "schema_removed" for f in findings)


def test_new_required_property_is_breaking():
    base = _min_openapi(
        {
            "A": {
                "type": "object",
                "properties": {"x": {"type": "string"}},
            }
        }
    )
    head = _min_openapi(
        {
            "A": {
                "type": "object",
                "required": ["y"],
                "properties": {
                    "x": {"type": "string"},
                    "y": {"type": "string"},
                },
            }
        }
    )
    overall, findings = analyze_schema_compatibility(base, head)
    assert overall == "breaking"
    assert any(f.rule == "required_field_added" for f in findings)


def test_enum_narrowing_is_breaking():
    base = _min_openapi(
        {"E": {"type": "string", "enum": ["a", "b", "c"]}}
    )
    head = _min_openapi({"E": {"type": "string", "enum": ["a", "b"]}})
    overall, findings = analyze_schema_compatibility(base, head)
    assert overall == "breaking"
    assert any(f.rule == "enum_narrowed" for f in findings)


def test_removed_path_is_breaking():
    base = _min_openapi({}, paths={"/foo": {"get": {"responses": {"200": {"description": "ok"}}}}})
    head = _min_openapi({}, paths={})
    overall, findings = analyze_schema_compatibility(base, head)
    assert overall == "breaking"
    assert any(f.rule == "path_removed" for f in findings)


def test_deterministic_findings_order():
    base = _min_openapi(
        {"Z": {"type": "object"}, "A": {"type": "object"}},
        paths={"/z": {"get": {"responses": {"200": {"description": "ok"}}}}},
    )
    head = _min_openapi({"A": {"type": "object"}}, paths={})
    o1, f1 = analyze_schema_compatibility(base, head)
    o2, f2 = analyze_schema_compatibility(base, head)
    assert o1 == o2
    assert [x.path for x in f1] == [x.path for x in f2]
    assert [x.id for x in f1] == [x.id for x in f2]


def test_rules_disable_paths():
    base = _min_openapi({}, paths={"/x": {"get": {"responses": {"200": {"description": "ok"}}}}})
    head = _min_openapi({}, paths={})
    rules = CompatibilityRules(check_paths=False)
    overall, findings = analyze_schema_compatibility(base, head, rules)
    assert overall == "safe"
    assert not any(f.rule == "path_removed" for f in findings)


def test_possible_rename_unknown():
    base = _min_openapi(
        {
            "OldName": {
                "type": "object",
                "properties": {"p": {"type": "string"}},
            }
        }
    )
    head = _min_openapi(
        {
            "NewName": {
                "type": "object",
                "properties": {"p": {"type": "string"}},
            }
        }
    )
    overall, findings = analyze_schema_compatibility(base, head)
    assert overall == "unknown"
    assert any(f.rule == "possible_rename" for f in findings)
