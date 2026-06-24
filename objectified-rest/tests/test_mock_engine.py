"""Unit tests for the Mock Server request/response engine (#3615, RC1-2.2)."""

import pytest

from app.mock_engine import (
    BUILTIN_SCENARIOS,
    extract_operations,
    match_operation,
    normalize_scenarios,
    resolve_active_scenario_name,
    resolve_response,
)

SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Pet Store", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/Pet"},
                                    "minItems": 1,
                                }
                            }
                        },
                    }
                },
            },
            "post": {
                "operationId": "createPet",
                "responses": {
                    "201": {
                        "description": "created",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"}
                            }
                        },
                    }
                },
            },
        },
        "/pets/{petId}": {
            "get": {
                "operationId": "getPet",
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"}
                            }
                        },
                    },
                    "404": {"description": "missing"},
                },
            },
            "delete": {
                "operationId": "deletePet",
                "responses": {"204": {"description": "deleted"}},
            },
        },
    },
    "components": {
        "schemas": {
            "Pet": {
                "type": "object",
                "required": ["id", "name"],
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "tag": {"type": "string"},
                },
            }
        }
    },
}


def test_extract_operations_counts_all_methods():
    ops = extract_operations(SPEC)
    keys = {op.key for op in ops}
    assert keys == {
        "GET /pets",
        "POST /pets",
        "GET /pets/{petId}",
        "DELETE /pets/{petId}",
    }


def test_match_operation_with_path_param():
    ops = extract_operations(SPEC)
    op, params = match_operation(ops, "GET", "/pets/123")
    assert op is not None and op.key == "GET /pets/{petId}"
    assert params == {"petId": "123"}


def test_match_operation_prefers_literal_over_param():
    spec = {
        "paths": {
            "/pets/mine": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/pets/{petId}": {"get": {"responses": {"200": {"description": "ok"}}}},
        }
    }
    ops = extract_operations(spec)
    op, _ = match_operation(ops, "GET", "/pets/mine")
    assert op.path_template == "/pets/mine"


def test_no_match_returns_none():
    ops = extract_operations(SPEC)
    op, params = match_operation(ops, "GET", "/unknown")
    assert op is None and params == {}


def test_resolve_happy_path_generates_valid_body():
    ops = extract_operations(SPEC)
    result = resolve_response(SPEC, {}, ops, "GET", "/pets/1")
    assert result.matched is True
    assert result.status == 200
    assert result.validation_error is None
    assert set(["id", "name"]).issubset(result.body.keys())


def test_resolve_list_returns_array():
    ops = extract_operations(SPEC)
    result = resolve_response(SPEC, {}, ops, "GET", "/pets")
    assert isinstance(result.body, list) and len(result.body) >= 1
    assert result.validation_error is None


def test_post_uses_201_default_success():
    ops = extract_operations(SPEC)
    result = resolve_response(SPEC, {}, ops, "POST", "/pets")
    assert result.status == 201


def test_delete_204_has_no_body():
    ops = extract_operations(SPEC)
    result = resolve_response(SPEC, {}, ops, "DELETE", "/pets/9")
    assert result.status == 204
    assert result.body is None


def test_unmatched_path_is_404():
    ops = extract_operations(SPEC)
    result = resolve_response(SPEC, {}, ops, "GET", "/nope")
    assert result.matched is False and result.status == 404


def test_builtin_server_error_scenario_overrides_status_and_body():
    ops = extract_operations(SPEC)
    config = {"active_scenario": "server-error"}
    result = resolve_response(SPEC, config, ops, "GET", "/pets/1")
    assert result.status == 500
    assert result.body["error"]["code"] == "internal_error"


def test_scenario_header_overrides_instance_default():
    ops = extract_operations(SPEC)
    config = {"active_scenario": "happy-path"}
    result = resolve_response(
        SPEC, config, ops, "GET", "/pets/1", scenario_header="not-found"
    )
    assert result.status == 404


def test_slow_scenario_injects_latency():
    ops = extract_operations(SPEC)
    result = resolve_response(SPEC, {"active_scenario": "slow"}, ops, "GET", "/pets")
    assert result.latency_ms == 1500


def test_per_operation_rule_targets_one_operation():
    ops = extract_operations(SPEC)
    config = {
        "active_scenario": "custom",
        "scenarios": [
            {
                "name": "custom",
                "rules": [
                    {"operation": "GET /pets/{petId}", "status": 418, "body": {"teapot": True}}
                ],
            }
        ],
    }
    # Targeted operation gets the override...
    one = resolve_response(SPEC, config, ops, "GET", "/pets/5")
    assert one.status == 418 and one.body == {"teapot": True}
    # ...while a different operation falls through to its generated success response.
    other = resolve_response(SPEC, config, ops, "GET", "/pets")
    assert other.status == 200 and isinstance(other.body, list)


def test_rule_method_path_wildcards():
    ops = extract_operations(SPEC)
    config = {
        "active_scenario": "errs",
        "scenarios": [
            {"name": "errs", "rules": [{"method": "GET", "path": "*", "status": 503}]}
        ],
    }
    assert resolve_response(SPEC, config, ops, "GET", "/pets").status == 503
    # POST is untouched by a GET-only rule.
    assert resolve_response(SPEC, config, ops, "POST", "/pets").status == 201


def test_latency_is_clamped():
    ops = extract_operations(SPEC)
    config = {
        "active_scenario": "x",
        "scenarios": [{"name": "x", "rules": [{"operation": "*", "latency_ms": 10_000_000}]}],
    }
    result = resolve_response(SPEC, config, ops, "GET", "/pets")
    assert result.latency_ms == 30_000


def test_normalize_scenarios_always_includes_builtins():
    names = {s["name"] for s in normalize_scenarios(None)}
    assert {s["name"] for s in BUILTIN_SCENARIOS}.issubset(names)


def test_normalize_scenarios_user_overrides_builtin():
    custom = [{"name": "happy-path", "rules": [{"operation": "*", "status": 200}]}]
    scenarios = normalize_scenarios(custom)
    happy = next(s for s in scenarios if s["name"] == "happy-path")
    assert happy["rules"] == [{"operation": "*", "status": 200}]


def test_unknown_active_scenario_falls_back():
    ops = extract_operations(SPEC)
    result = resolve_response(SPEC, {"active_scenario": "does-not-exist"}, ops, "GET", "/pets/1")
    # Falls back to happy-path -> normal success.
    assert result.status == 200


def test_resolve_active_scenario_name_precedence():
    assert resolve_active_scenario_name({"active_scenario": "a"}, "b") == "b"
    assert resolve_active_scenario_name({"active_scenario": "a"}, None) == "a"
    assert resolve_active_scenario_name({}, None) == "happy-path"
