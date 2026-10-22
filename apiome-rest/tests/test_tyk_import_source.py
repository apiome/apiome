"""Unit tests for the Tyk API definition ImportSource (FMT-7.5 / #5459)."""

from __future__ import annotations

import json

import pytest

from app.fileset import IntakeFileset
from app.import_routing import decide_import_routing
from app.import_source import DetectionInput, ImportSourceError
from app.openapi_import_source import OpenApiImportSource
from app.tyk_import_source import TykImportSource


@pytest.fixture
def adapter() -> TykImportSource:
    return TykImportSource()


CLASSIC = {
    "api_id": "orders-api",
    "name": "Orders API",
    "use_keyless": False,
    "enable_jwt": True,
    "jwt_signing_method": "hmac",
    "jwt_source": "c2VjcmV0LWtleQ==",
    "proxy": {"listen_path": "/v2/orders/", "target_url": "http://orders.internal:8080", "strip_listen_path": True},
    "version_data": {
        "not_versioned": False,
        "default_version": "v2",
        "versions": {
            "v2": {
                "name": "v2",
                "use_extended_paths": True,
                "extended_paths": {
                    "white_list": [
                        {"path": "/orders", "method_actions": {"GET": {"action": "no_action"}, "POST": {}}},
                        {"path": "/orders/{id}", "method_actions": {"GET": {}}},
                    ],
                    "ignored": [{"path": "/healthz", "method_actions": {"GET": {}}}],
                    "hard_timeouts": [{"path": "/orders", "method": "POST", "timeout": 10}],
                    "validate_json": [{"path": "/orders", "method": "POST", "schema": {"type": "object"}}],
                },
            }
        },
    },
    "definition": {"location": "header", "key": "x-api-version"},
    "global_rate_limit": {"rate": 100, "per": 60},
}

OAS = {
    "openapi": "3.0.3",
    "info": {"title": "Lab", "version": "1"},
    "paths": {
        "/assays": {
            "get": {"operationId": "listAssays", "responses": {"200": {"description": "ok"}}},
        }
    },
    "x-tyk-api-gateway": {
        "info": {"id": "lab", "name": "Lab"},
        "upstream": {"url": "http://lab.internal"},
        "server": {
            "listenPath": {"value": "/lab/"},
            "authentication": {
                "enabled": True,
                "securitySchemes": {"jwt": {"enabled": True, "jwt": {"enabled": True}}},
            },
        },
        "middleware": {
            "global": {"cors": {"enabled": True}, "cache": {"enabled": False}},
            "operations": {"listAssays": {"cache": {"enabled": True}}, "ghost": {"cache": {"enabled": True}}},
        },
    },
}


def _ops(adapter: TykImportSource, text: str):
    model = adapter.normalize(adapter.parse(text, source_label="tyk.json"))
    return model, {op.key: op for op in model.operations()}


def _ignored(model) -> set:
    return {entry["construct"] for entry in model.extras["gateway"]["ignored_constructs"]}


# ---------------------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------------------


def test_detects_classic_and_oas(adapter: TykImportSource) -> None:
    assert adapter.detect(DetectionInput(text=json.dumps(CLASSIC))).confidence >= 0.9
    assert adapter.detect(DetectionInput(text=json.dumps(OAS))).confidence >= 0.95


def test_plain_openapi_is_not_claimed_and_tyk_oas_makes_openapi_step_down(adapter: TykImportSource) -> None:
    plain = {key: value for key, value in OAS.items() if key != "x-tyk-api-gateway"}
    assert not adapter.detect(DetectionInput(text=json.dumps(plain))).matched
    openapi = OpenApiImportSource().detect(DetectionInput(text=json.dumps(OAS)))
    assert openapi.confidence <= 0.8


# ---------------------------------------------------------------------------------------
# Classic
# ---------------------------------------------------------------------------------------


def test_white_list_becomes_operations_under_the_listen_path(adapter: TykImportSource) -> None:
    model, ops = _ops(adapter, json.dumps(CLASSIC))
    assert {
        "GET /v2/orders/orders",
        "POST /v2/orders/orders",
        "GET /v2/orders/orders/{id}",
        "GET /v2/orders/healthz",
    } <= set(ops)
    item = ops["GET /v2/orders/orders/{id}"]
    assert [param.name for param in item.parameters] == ["id"]
    assert item.extras["provenance"] == "inferred"
    assert item.extras["api_version"] == "v2"
    assert item.extras["version_selector"] == {"location": "header", "key": "x-api-version"}
    assert model.format == "tyk"


def test_per_path_rules_ride_on_their_route(adapter: TykImportSource) -> None:
    model, ops = _ops(adapter, json.dumps(CLASSIC))
    assert set(ops["POST /v2/orders/orders"].extras["plugins"]) == {"hard_timeouts", "validate_json"}
    assert "validate_json.schema" in _ignored(model)
    assert "version_selector" in _ignored(model)


def test_auth_flags_and_secret_jwt_source(adapter: TykImportSource) -> None:
    model, ops = _ops(adapter, json.dumps(CLASSIC))
    security = ops["GET /v2/orders/orders"].extras["security"]
    assert security[0]["scheme"] == "bearer" and security[0]["detail"]["jwt_source"] == "***"
    assert "security" not in ops["GET /v2/orders/healthz"].extras  # `ignored` bypasses auth
    assert model.extras["gateway"]["credential_redactions"] == 1
    assert "c2VjcmV0" not in str(model.model_dump())


def test_unversioned_api_without_white_list_is_a_catch_all(adapter: TykImportSource) -> None:
    classic = {
        "api_id": "p",
        "use_keyless": True,
        "proxy": {"listen_path": "/ping/"},
        "version_data": {"not_versioned": True},
    }
    _model, ops = _ops(adapter, json.dumps(classic))
    assert list(ops) == ["ANY /ping"]


def test_classic_routes_to_the_catalog_as_a_gateway_surface(adapter: TykImportSource) -> None:
    model, _ops_ = _ops(adapter, json.dumps(CLASSIC))
    decision = decide_import_routing(adapter, model)
    assert decision.publishable is False and "no request/response schemas" in decision.reason


@pytest.mark.parametrize(
    ("document", "code"),
    [
        ({"api_id": "x", "proxy": {"target_url": "http://x"}}, "INPUT_SEMANTIC_INVALID"),
        (
            {"api_id": "x", "proxy": {"listen_path": "/x/"}, "version_data": {"not_versioned": False, "versions": {}}},
            "INPUT_SEMANTIC_INVALID",
        ),
        ({"p1": {"access_rights": {"x": {}}}}, "INPUT_SEMANTIC_INVALID"),
        ({"name": "not tyk"}, "FORMAT_MISMATCH"),
    ],
)
def test_error_codes(adapter: TykImportSource, document: dict, code: str) -> None:
    with pytest.raises(ImportSourceError) as exc:
        adapter.parse(json.dumps(document))
    assert exc.value.code == code


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ('{"api_id": "x" "proxy": {}}', "INPUT_MALFORMED"),
        ('{"api_id": "x", "proxy": {"listen_path": "/x/", "target_url": "http://x', "INPUT_TRUNCATED"),
        ("_format_version: '3.0'\nservices: []\n", "FORMAT_MISMATCH"),
    ],
)
def test_text_error_codes(adapter: TykImportSource, text: str, code: str) -> None:
    with pytest.raises(ImportSourceError) as exc:
        adapter.parse(text)
    assert exc.value.code == code


def test_policies_file_attaches_consumer_policy(adapter: TykImportSource) -> None:
    policies = {
        "reader": {"_id": "reader", "rate": 10, "per": 60, "access_rights": {"orders-api": {"versions": ["v2"]}}},
        "other": {"_id": "other", "access_rights": {"another-api": {}}},
    }
    fileset = IntakeFileset.from_members(
        {"api.json": json.dumps(CLASSIC), "policies.json": json.dumps(policies)}, root="api.json"
    )
    model = adapter.normalize(adapter.parse_fileset(fileset))
    assert model.raw["gateway_config"]["policies"] == ["reader"]
    assert {"name": "policy", "scope": "consumer"} in model.extras["gateway"]["unmodeled_plugins"]
    assert "policies.other-api" in _ignored(model)


def test_second_api_definition_in_a_set_is_refused(adapter: TykImportSource) -> None:
    fileset = IntakeFileset.from_members(
        {"a.json": json.dumps(CLASSIC), "b.json": json.dumps({**CLASSIC, "api_id": "b"})}, root="a.json"
    )
    with pytest.raises(ImportSourceError) as exc:
        adapter.parse_fileset(fileset)
    assert exc.value.code == "INPUT_SEMANTIC_INVALID"


# ---------------------------------------------------------------------------------------
# Tyk OAS
# ---------------------------------------------------------------------------------------


def test_oas_keeps_openapi_schemas_and_attaches_middleware(adapter: TykImportSource) -> None:
    model, ops = _ops(adapter, json.dumps(OAS))
    assert model.format == "tyk"
    op = ops["GET /assays"]
    assert op.messages  # the OpenAPI response is kept
    assert op.extras["plugins"] == ["cache"]
    assert op.extras["tyk"]["provenance"] == "inferred"
    report = model.extras["gateway"]
    assert report["schemaless_operation_count"] == 0
    assert report["auth"][0]["scheme"] == "bearer"
    assert report["global_plugins"] == ["cors"]
    assert "middleware.operations.unknown-operation" in _ignored(model)


def test_oas_lints_as_openapi(adapter: TykImportSource) -> None:
    model, _ops_ = _ops(adapter, json.dumps(OAS))
    assert adapter.lint(model) is not None
