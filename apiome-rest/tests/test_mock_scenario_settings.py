"""Unit tests for mock scenario settings validation/canonicalization (#4454, SIM-4.2)."""

from __future__ import annotations

from app.mock_scenario_settings import (
    MAX_SCENARIOS,
    normalize_operation_key,
    scenarios_from_storage,
    scenarios_to_storage,
    validate_mock_scenarios,
)
from app.models import MockScenarioSpec

SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Pet Store", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/Pet"},
                                }
                            }
                        },
                    },
                    "429": {"description": "throttled (no content)"},
                }
            }
        },
        "/pets/{petId}": {
            "get": {
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"},
                            }
                        },
                    }
                }
            }
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
                },
                "additionalProperties": False,
            }
        }
    },
}


def _scenarios(raw: dict) -> dict[str, MockScenarioSpec]:
    return {name: MockScenarioSpec.model_validate(value) for name, value in raw.items()}


def test_valid_scenario_passes() -> None:
    scenarios = _scenarios(
        {
            "happy-path": {
                "description": "All good.",
                "operations": {
                    "GET /pets": {
                        "responses": [{"status": 200, "body": [{"id": 1, "name": "Rex"}]}]
                    }
                },
            }
        }
    )
    assert validate_mock_scenarios(scenarios, SPEC) == []


def test_unknown_operation_is_rejected() -> None:
    scenarios = _scenarios(
        {"s": {"operations": {"DELETE /pets": {"responses": [{"status": 200}]}}}}
    )
    errors = validate_mock_scenarios(scenarios, SPEC)
    assert len(errors) == 1
    assert "no operation DELETE /pets exists" in errors[0]


def test_malformed_operation_key_is_rejected() -> None:
    scenarios = _scenarios({"s": {"operations": {"pets": {"responses": [{"status": 200}]}}}})
    errors = validate_mock_scenarios(scenarios, SPEC)
    assert len(errors) == 1
    assert "GET /pets/{petId}" in errors[0]


def test_undefined_status_requires_off_spec() -> None:
    scenarios = _scenarios(
        {"s": {"operations": {"GET /pets": {"responses": [{"status": 503}]}}}}
    )
    errors = validate_mock_scenarios(scenarios, SPEC)
    assert len(errors) == 1
    assert "status 503 is not defined" in errors[0]

    off_spec = _scenarios(
        {"s": {"operations": {"GET /pets": {"responses": [{"status": 503, "offSpec": True}]}}}}
    )
    assert validate_mock_scenarios(off_spec, SPEC) == []


def test_body_schema_mismatch_requires_off_spec() -> None:
    bad_body = {"operations": {"GET /pets": {"responses": [{"status": 200, "body": [{"id": "x"}]}]}}}
    errors = validate_mock_scenarios(_scenarios({"s": bad_body}), SPEC)
    assert len(errors) == 1
    assert "does not match" in errors[0]

    bad_body["operations"]["GET /pets"]["responses"][0]["offSpec"] = True
    assert validate_mock_scenarios(_scenarios({"s": bad_body}), SPEC) == []


def test_body_on_contentless_response_requires_off_spec() -> None:
    scenarios = _scenarios(
        {"s": {"operations": {"GET /pets": {"responses": [{"status": 429, "body": {"error": "quota"}}]}}}}
    )
    errors = validate_mock_scenarios(scenarios, SPEC)
    assert len(errors) == 1
    assert "declares no response content" in errors[0]


def test_headerless_status_only_response_on_contentless_status_passes() -> None:
    scenarios = _scenarios(
        {"s": {"operations": {"GET /pets": {"responses": [{"status": 429, "headers": {"Retry-After": "60"}}]}}}}
    )
    assert validate_mock_scenarios(scenarios, SPEC) == []


def test_undeclared_media_type_requires_off_spec() -> None:
    scenarios = _scenarios(
        {
            "s": {
                "operations": {
                    "GET /pets": {
                        "responses": [{"status": 200, "body": "id,name", "mediaType": "text/csv"}]
                    }
                }
            }
        }
    )
    errors = validate_mock_scenarios(scenarios, SPEC)
    assert len(errors) == 1
    assert "media type 'text/csv' is not declared" in errors[0]


def test_scenario_name_shape_is_enforced() -> None:
    scenarios = _scenarios({"bad name!": {"operations": {}}})
    errors = validate_mock_scenarios(scenarios, SPEC)
    assert len(errors) == 1
    assert "Scenario name 'bad name!' is invalid" in errors[0]


def test_reserved_and_malformed_headers_are_rejected() -> None:
    scenarios = _scenarios(
        {
            "s": {
                "operations": {
                    "GET /pets": {
                        "responses": [
                            {
                                "status": 200,
                                "headers": {
                                    "Content-Length": "5",
                                    "Bad Header": "x",
                                    "X-Evil": "a\r\nSet-Cookie: pwn",
                                },
                                "offSpec": True,
                            }
                        ]
                    }
                }
            }
        }
    )
    errors = validate_mock_scenarios(scenarios, SPEC)
    assert len(errors) == 3
    assert any("managed by the server" in e for e in errors)
    assert any("invalid header name" in e for e in errors)
    assert any("CR/LF" in e for e in errors)


def test_scenario_count_limit() -> None:
    scenarios = _scenarios({f"s{i}": {"operations": {}} for i in range(MAX_SCENARIOS + 1)})
    errors = validate_mock_scenarios(scenarios, SPEC)
    assert any("At most" in e for e in errors)


def test_storage_canonicalization() -> None:
    scenarios = _scenarios(
        {
            "quota-exceeded": {
                "description": "Throttled.",
                "operations": {
                    "get /pets": {
                        "responses": [
                            {"status": 429, "headers": {"Retry-After": "60"}, "offSpec": True},
                            {"status": 200, "body": None, "mediaType": "application/json"},
                        ]
                    }
                },
            }
        }
    )
    storage = scenarios_to_storage(scenarios)
    ops = storage["quota-exceeded"]["operations"]
    assert set(ops) == {"GET /pets"}
    first, second = ops["GET /pets"]["responses"]
    assert first == {"status": 429, "headers": {"Retry-After": "60"}, "offSpec": True}
    assert "body" not in first
    assert second == {"status": 200, "body": None, "mediaType": "application/json"}
    assert storage["quota-exceeded"]["description"] == "Throttled."


def test_scenarios_from_storage_variants() -> None:
    assert scenarios_from_storage(None) == ({}, True)
    assert scenarios_from_storage({}) == ({}, True)
    assert scenarios_from_storage({"mode": "private"}) == ({}, True)
    assert scenarios_from_storage('{"scenarios": {"s": {}}}') == ({"s": {}}, True)
    assert scenarios_from_storage("not json") == ({}, False)
    assert scenarios_from_storage({"scenarios": "nope"}) == ({}, False)


def test_normalize_operation_key() -> None:
    assert normalize_operation_key("get /pets") == "GET /pets"
    assert normalize_operation_key("GET") is None
    assert normalize_operation_key("GET pets") is None
