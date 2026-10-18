"""The AWS API Gateway export import source (FMT-7.1, #5455).

Drives the adapter over the committed corpus (``apiome-ui/examples/aws-apigateway``) and small
inline documents. Covers the acceptance criteria: a REST API export and an HTTP API export both
import; integration, authorizer, validator and CORS extensions map to canonical constructs with
``declared`` provenance; a plain OpenAPI document still routes to the OpenAPI adapter; and an
unknown extension is preserved and reported.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from app.aws_apigateway_extensions import (
    backend_for_integration,
    cors_from_mock_options,
    extension_sites,
    has_aws_extensions,
    integration_problems,
    security_for_scheme,
    validation_posture,
)
from app.aws_apigateway_import_source import AwsApiGatewayImportSource
from app.canonical_security import operation_security_schemes
from app.fileset import IntakeFileset
from app.format_detection import detect_format
from app.import_preview_manifest import (
    CoverageClass,
    build_import_preview_manifest,
    paginate_import_preview_manifest,
)
from app.import_routing import decide_import_routing
from app.import_source import DetectionInput, ImportSourceError
from app.openapi_fileset_bundle import bundle_openapi_fileset
from app.openapi_import_source import OpenApiImportSource

EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "aws-apigateway"


@pytest.fixture
def adapter() -> AwsApiGatewayImportSource:
    return AwsApiGatewayImportSource()


def _model(adapter: AwsApiGatewayImportSource, name: str):
    text = (EXAMPLES / name).read_text(encoding="utf-8")
    return adapter.normalize(adapter.parse(text, source_label=name))


def _ops(model) -> Dict[str, Any]:
    return {op.key: op for op in model.operations()}


def _ledger(model) -> Dict[str, Any]:
    page = paginate_import_preview_manifest(
        build_import_preview_manifest(model, adapter_key="aws-apigateway", options={})
    )
    return {row.source_construct: row for row in page.coverage}


# --- acceptance: both flavours import --------------------------------------------------


def test_a_rest_api_export_imports_with_every_operation(adapter):
    model = _model(adapter, "02-typical-rest-api-export.json")
    assert model.format == "aws-apigateway"
    assert model.extras["aws_apigateway"]["flavor"] == "rest"
    assert sorted(_ops(model)) == ["GET /orders", "GET /orders/{orderId}", "OPTIONS /orders", "POST /orders"]
    assert {t.key for t in model.types} >= {"NewOrder", "Order", "OrderList"}
    # The base document is the export, verbatim, for the OpenAPI linter.
    assert "x-amazon-apigateway-request-validators" in model.raw


def test_an_http_api_export_imports_with_its_v2_constructs(adapter):
    model = _model(adapter, "06-typical-http-api-export.yaml")
    report = model.extras["aws_apigateway"]
    assert report["flavor"] == "http"
    ops = _ops(model)
    assert "ANY /$default" in ops and ops["ANY /$default"].http_method == "ANY"
    get = ops["GET /subscriptions"]
    assert get.extras["backend"]["payloadFormatVersion"] == "2.0"
    [security] = get.extras["security"]
    assert security["scheme"] == "bearer" and security["scopes"] == ["subscriptions:read"]
    assert security["authorizer"]["jwtConfiguration"]["issuer"] == "https://auth.example.com/"
    assert security["provenance"] == "declared"
    cors = model.extras["cors"]
    assert cors["allowOrigins"] == ["https://app.example.com"] and cors["allowCredentials"] is True
    assert cors["provenance"] == "declared" and cors["source"] == "x-amazon-apigateway-cors"
    assert report["server_extensions"] == {
        "https://p1q2r3s4t5.execute-api.eu-west-1.amazonaws.com/": {
            "x-amazon-apigateway-endpoint-configuration": {"disableExecuteApiEndpoint": False}
        }
    }


# --- acceptance: declared canonical constructs -----------------------------------------


def test_integrations_become_declared_backends(adapter):
    ops = _ops(_model(adapter, "04-stress-extension-coverage.yaml"))
    assert ops["ANY /lambda-proxy"].extras["backend"]["kind"] == "lambda-proxy"
    proxy = ops["ANY /{proxy+}"].extras["backend"]
    assert proxy["kind"] == "http-proxy" and proxy["uri"] == "https://legacy.internal.example.com/{proxy}"
    sqs = ops["POST /aws-service"].extras["backend"]
    assert sqs["kind"] == "aws-service" and sqs["service"] == "sqs"
    assert ops["GET /throttled"].extras["backend"]["kind"] == "mock"
    for op in ops.values():
        assert op.extras["backend"]["provenance"] == "declared"
    # Templates and mappings are kept verbatim beside the backend.
    templates = ops["POST /aws-service"].extras["aws_apigateway"]["integration"]["requestTemplates"]
    assert templates == {"application/json": "Action=SendMessage&MessageBody=$input.body"}


def test_stage_variables_and_vpc_links_are_recorded(adapter):
    ops = _ops(_model(adapter, "03-composition-stage-variables-and-refs.yaml"))
    backend = ops["GET /products"].extras["backend"]
    assert backend["connectionType"] == "VPC_LINK"
    assert backend["stageVariables"] == ["backendHost", "vpcLinkId"]
    assert ops["GET /categories"].extras["backend"]["stageVariables"] == ["categoriesFn"]


def test_authorizers_become_declared_security(adapter):
    model = _model(adapter, "04-stress-extension-coverage.yaml")
    op = _ops(model)["GET /throttled"]
    [security] = op.extras["security"]  # inherited from the root `security`
    assert security["scheme"] == "authorization" and security["name"] == "jwt-authorizer"
    assert security["authType"] == "cognito_user_pools"
    assert security["authorizer"]["type"] == "cognito_user_pools"
    # The shared security reader sees it as a per-operation requirement.
    assert operation_security_schemes(model, op)[0] == ["authorization"]
    names = [a["name"] for a in model.extras["aws_apigateway"]["authorizers"]]
    assert names == ["jwt-authorizer", "token-authorizer"]


def test_request_validators_become_a_declared_validation_posture(adapter):
    ops = _ops(_model(adapter, "02-typical-rest-api-export.json"))
    posture = ops["POST /orders"].extras["validation"]
    assert posture["validator"] == "body-and-params" and posture["defined"] is True
    assert posture["validateRequestBody"] is True and posture["provenance"] == "declared"


def test_a_mock_options_integration_declares_cors(adapter):
    ops = _ops(_model(adapter, "02-typical-rest-api-export.json"))
    cors = ops["OPTIONS /orders"].extras["cors"]
    assert cors["allowOrigins"] == ["https://app.example.com"]
    assert cors["allowMethods"] == ["GET", "OPTIONS", "POST"]
    assert cors["source"] == "mock-integration" and cors["provenance"] == "declared"


# --- acceptance: unknown extensions are preserved and reported ---------------------------


def test_an_unknown_extension_is_preserved_and_reported(adapter):
    model = _model(adapter, "04-stress-extension-coverage.yaml")
    op = _ops(model)["GET /throttled"]
    assert op.extras["aws_apigateway"]["extensions"]["x-example-unknown-extension"]["owner"] == "platform-team"
    sites = {s["name"]: s for s in model.extras["aws_apigateway"]["extensions"]}
    assert sites["x-example-unknown-extension"]["status"] == "unknown"
    assert sites["x-amazon-apigateway-policy"]["status"] == "preserved"
    assert sites["x-amazon-apigateway-integration"]["status"] == "interpreted"
    assert model.extras["aws_apigateway"]["settings"]["x-amazon-apigateway-minimum-compression-size"] == 1024

    rows = _ledger(model)
    unknown = rows["aws#unknown-extension.x-example-unknown-extension"]
    assert unknown.coverage is CoverageClass.PARTIALLY_MAPPED and "never dropped" in unknown.detail
    assert rows["aws#extension.x-amazon-apigateway-policy"].coverage is CoverageClass.PARTIALLY_MAPPED
    assert rows["aws#integration.mock"].coverage is CoverageClass.MAPPED
    assert rows["aws#authorizer.token-authorizer"].coverage is CoverageClass.MAPPED
    assert rows["aws#request-validator.params-only"].coverage is CoverageClass.MAPPED


# --- acceptance: detection is not greedy -----------------------------------------------


def test_a_plain_openapi_document_routes_to_the_openapi_adapter(adapter):
    text = (EXAMPLES / "negative" / "04-wrong-format-plain-openapi.yaml").read_text()
    assert adapter.detect(DetectionInput(text=text)).matched is False
    detection = detect_format(DetectionInput(text=text))
    assert detection.detected.source_key == "openapi" and not detection.ambiguous
    with pytest.raises(ImportSourceError) as info:
        adapter.parse(text)
    assert info.value.code == "FORMAT_MISMATCH"


def test_an_aws_key_inside_an_example_is_not_an_export(adapter):
    document = {
        "openapi": "3.0.1",
        "info": {"title": "t", "version": "1"},
        "paths": {
            "/a": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {"example": {"x-amazon-apigateway-integration": {"type": "mock"}}}
                            },
                        }
                    }
                }
            }
        },
    }
    assert has_aws_extensions(document) is False
    assert adapter.detect(DetectionInput(document=document)).matched is False


def test_an_export_beats_openapi_without_ambiguity(adapter):
    text = (EXAMPLES / "01-minimal-rest-api.yaml").read_text()
    detection = detect_format(DetectionInput(text=text))
    assert detection.detected.source_key == "aws-apigateway" and detection.detected.confidence == 0.99
    assert not detection.ambiguous
    openapi = OpenApiImportSource().detect(DetectionInput(text=text))
    assert openapi.confidence == 0.8 and openapi.format == "openapi-3.0"


# --- rejections ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "integration,fragment",
    [({"httpMethod": "GET"}, "declares no `type`"), ({"type": "lambda"}, "unknown type"), ("mock", "not a mapping")],
)
def test_an_uninterpretable_integration_is_a_semantic_error(adapter, integration, fragment):
    document = {
        "openapi": "3.0.1",
        "info": {"title": "t", "version": "1"},
        "paths": {"/a": {"get": {"responses": {}, "x-amazon-apigateway-integration": integration}}},
    }
    with pytest.raises(ImportSourceError) as info:
        adapter.normalize(document)
    assert info.value.code == "INPUT_SEMANTIC_INVALID" and fragment in str(info.value)


def test_a_truncated_export_is_reported_as_truncated(adapter):
    text = (EXAMPLES / "negative" / "03-truncated-mid-integration.json").read_text()
    with pytest.raises(ImportSourceError) as info:
        adapter.parse(text)
    assert info.value.code == "INPUT_TRUNCATED"


def test_a_swagger_2_export_imports_with_an_any_route(adapter):
    document = {
        "swagger": "2.0",
        "info": {"title": "legacy", "version": "1"},
        "paths": {
            "/items": {
                "get": {
                    "responses": {"200": {"description": "ok"}},
                    "x-amazon-apigateway-integration": {"type": "mock"},
                }
            },
            "/{proxy+}": {
                "x-amazon-apigateway-any-method": {
                    "responses": {"200": {"description": "ok"}},
                    "x-amazon-apigateway-integration": {"type": "http_proxy", "uri": "https://b/{proxy}"},
                }
            },
        },
    }
    model = adapter.normalize(document)
    ops = _ops(model)
    assert ops["ANY /{proxy+}"].extras["backend"]["kind"] == "http-proxy"
    assert ops["GET /items"].extras["backend"]["kind"] == "mock"


# --- fileset ---------------------------------------------------------------------------


def test_a_split_export_bundles_its_sibling_components(adapter):
    members = {p.name: p.read_text() for p in (EXAMPLES / "07-split-set").iterdir()}
    document = adapter.parse_fileset(IntakeFileset.from_members(members, root="api.yaml"))
    model = adapter.normalize(document)
    assert {t.key for t in model.types} == {"Money", "NewShipment", "Parcel", "Shipment", "ShipmentPage"}
    # The cross-file parameter is hoisted and its reference made internal.
    get = document["paths"]["/shipments/{shipmentId}"]["get"]
    assert get["parameters"] == [{"$ref": "#/components/parameters/ShipmentId"}]
    assert document["components"]["parameters"]["ShipmentId"]["name"] == "shipmentId"
    assert _ops(model)["POST /shipments"].extras["validation"]["validator"] == "body-only"


def test_the_bundler_hoists_transitively_and_refuses_conflicts():
    members = {
        "root.yaml": "openapi: 3.0.1\npaths: {}\ncomponents:\n  schemas:\n"
        "    A: {$ref: './b.yaml#/components/schemas/B'}\n",
        "b.yaml": "components:\n  schemas:\n    B: {type: object, properties: {c: {$ref: '#/components/schemas/C'}}}\n"
        "    C: {type: string}\n",
    }
    bundled = bundle_openapi_fileset(IntakeFileset.from_members(members, root="root.yaml"))
    schemas = bundled["components"]["schemas"]
    assert schemas["A"] == {"$ref": "#/components/schemas/B"}
    assert schemas["B"]["properties"]["c"] == {"$ref": "#/components/schemas/C"}
    assert schemas["C"] == {"type": "string"}

    members["root.yaml"] += "    B: {type: integer}\n"
    with pytest.raises(ImportSourceError) as info:
        bundle_openapi_fileset(IntakeFileset.from_members(members, root="root.yaml"))
    assert info.value.code == "INPUT_SEMANTIC_INVALID"

    members["root.yaml"] = "openapi: 3.0.1\npaths: {}\ncomponents: {schemas: {A: {$ref: './missing.yaml#/x'}}}\n"
    with pytest.raises(ImportSourceError) as info:
        bundle_openapi_fileset(IntakeFileset.from_members(members, root="root.yaml"))
    assert info.value.code == "INPUT_REFERENCE_UNRESOLVED"


# --- routing and lint ------------------------------------------------------------------


def test_an_export_routes_to_the_catalog_and_lints_as_openapi(adapter):
    model = _model(adapter, "05-real-world-payments-rest-api.json")
    routing = decide_import_routing(adapter, model)
    assert routing.publishable is False
    report = adapter.lint(model)
    assert report.score is not None


# --- pure helpers ----------------------------------------------------------------------


def test_backend_classification():
    assert (
        backend_for_integration({"type": "AWS_PROXY", "uri": "arn:aws:apigateway:r:lambda:path/x"})["kind"]
        == "lambda-proxy"
    )
    assert (
        backend_for_integration({"type": "aws_proxy", "uri": "arn:aws:apigateway:r:states:action/x"})["kind"]
        == "aws-proxy"
    )
    assert backend_for_integration({"type": "http"})["kind"] == "http"


def test_security_scheme_identifiers():
    assert (
        security_for_scheme(
            "iam",
            {"type": "apiKey", "name": "Authorization", "in": "header", "x-amazon-apigateway-authtype": "awsSigv4"},
            [],
        )["scheme"]
        == "awsSigv4"
    )
    assert security_for_scheme("k", {"type": "apiKey", "name": "x-api-key", "in": "header"}, [])["scheme"] == "apiKey"
    assert security_for_scheme("b", {"type": "http", "scheme": "bearer"}, [])["scheme"] == "bearer"


def test_validation_posture_for_an_undefined_validator():
    posture = validation_posture("missing", {"other": {"validateRequestBody": True}})
    assert posture["defined"] is False and posture["validateRequestBody"] is None
    assert validation_posture(None, {}) is None


def test_cors_needs_a_mock_with_allow_headers():
    assert cors_from_mock_options({"type": "http"}) is None
    assert cors_from_mock_options({"type": "mock", "responses": {"default": {}}}) is None


def test_extension_sites_skip_schemas_and_extension_payloads():
    document = {
        "x-a": {"x-nested": 1},
        "components": {"schemas": {"S": {"x-in-schema": 1}}},
        "paths": {"/p": {"get": {"x-b": 2}}},
    }
    assert extension_sites(document) == [("/x-a", "x-a"), ("/paths/~1p/get/x-b", "x-b")]


def test_integration_problems_name_the_operation():
    document = {
        "openapi": "3.0.1",
        "paths": {"/p": {"x-amazon-apigateway-any-method": {"x-amazon-apigateway-integration": {}}}},
    }
    [problem] = integration_problems(document)
    assert problem.startswith("ANY /p:")
