"""The gateway family's new emit modes — FMT-7.7 (#5461).

Envoy xDS, Istio, Traefik, AWS API Gateway, Azure API Management and Apigee: each emits,
passes its product gate, re-imports, declares what it cannot carry, and has an honest fidelity
pack. Shared behaviour is parametrized over all six; per-product rules have their own tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import pytest
import yaml

from app.apigee_emitter import ApigeeEmitter, apigee_bundle_violations, validate_apigee_bundle
from app.aws_apigateway_emitter import AwsApiGatewayEmitter, aws_document_violations, validate_aws_apigateway_document
from app.azure_apim_emitter import AzureApimEmitter, azure_apim_bundle_violations, validate_azure_apim_bundle
from app.emitter import available_emit_formats, load_builtin_emitters
from app.envoy_xds_emitter import (
    EnvoyXdsEmitter,
    route_configuration_violations,
    validate_route_configuration_document,
)
from app.export_validation import _VALIDATORS
from app.fidelity_engine import compute_lossiness_for_emitter
from app.fileset import IntakeFileset
from app.gateway_configs import push_back
from app.gateway_match import parse_match_value, render_match_value
from app.import_source import get_import_source, load_builtin_import_sources
from app.istio_emitter import IstioEmitter, validate_virtualservice_stream, virtualservice_violations
from app.lossiness import LossinessKind
from app.traefik_emitter import (
    TraefikEmitter,
    dynamic_config_violations,
    render_rule,
    validate_traefik_dynamic_config,
)

load_builtin_import_sources()
load_builtin_emitters()

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"

#: emitter, its product gate, the adapter that re-imports it, multi-file.
_TARGETS = [
    (EnvoyXdsEmitter, validate_route_configuration_document, "envoy-xds", False),
    (IstioEmitter, validate_virtualservice_stream, "istio", False),
    (TraefikEmitter, validate_traefik_dynamic_config, "traefik", False),
    (AwsApiGatewayEmitter, validate_aws_apigateway_document, "aws-apigateway", False),
    (AzureApimEmitter, validate_azure_apim_bundle, "azure-apim", True),
    (ApigeeEmitter, validate_apigee_bundle, "apigee", True),
]

_SOURCES = [
    ("kong", "kong/02-typical-single-service-auth.yaml"),
    ("nginx", "nginx/02-typical-reverse-proxy.conf"),
    ("openapi", "openapi/30-openapi-3.0-petstore.yaml"),
    ("istio", "istio/02-typical-virtualservice.yaml"),
]


def _import(fmt: str, path: str):
    adapter = get_import_source(fmt)
    return adapter.normalize(adapter.parse((_EXAMPLES / path).read_text(), source_label=path))


def _members(result) -> Dict[str, str]:
    return {f.path: f.content for f in result.files}


def _validate_and_reimport(emitter_cls, gate, adapter_key, multi, model):
    result = emitter_cls().emit(model)
    adapter = get_import_source(adapter_key)
    if multi:
        gate(_members(result))
        fileset = IntakeFileset.from_members(_members(result), root=result.files[0].path)
        return result, adapter.normalize(adapter.parse_fileset(fileset))
    assert len(result.files) == 1
    gate(result.files[0].content)
    return result, adapter.normalize(adapter.parse(result.files[0].content))


def _coordinates(model):
    return sorted((op.http_method, op.http_path) for op in model.operations())


# ---------------------------------------------------------------------------------------
# Every target
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(("emitter_cls", "gate", "adapter_key", "multi"), _TARGETS, ids=[t[2] for t in _TARGETS])
def test_registered_with_a_gate_and_a_rest_card(emitter_cls, gate, adapter_key, multi) -> None:
    assert adapter_key in available_emit_formats()
    assert adapter_key in _VALIDATORS
    descriptor = emitter_cls.descriptor()
    assert descriptor.paradigm.value == "rest"  # the Export Studio's REST & HTTP family
    assert emitter_cls.multi_file is multi
    assert emitter_cls.capability_profile().operations is True
    assert emitter_cls.capability_profile().events is False


@pytest.mark.parametrize("source", _SOURCES, ids=[s[0] for s in _SOURCES])
@pytest.mark.parametrize(("emitter_cls", "gate", "adapter_key", "multi"), _TARGETS, ids=[t[2] for t in _TARGETS])
def test_emits_a_valid_reimportable_artifact(emitter_cls, gate, adapter_key, multi, source) -> None:
    model = _import(*source)
    result, back = _validate_and_reimport(emitter_cls, gate, adapter_key, multi, model)
    # nginx routes match any method, which an APIM operation cannot: the export is declared, not padded.
    assert back.operations() or (adapter_key == "azure-apim" and source[0] == "nginx")
    if adapter_key not in ("apigee", "azure-apim"):  # Apigee renames path parameters; APIM drops ANY
        assert set(_coordinates(back)) == set(_coordinates(model))
    assert result.losses, "a cross-format export always declares something it could not carry"


@pytest.mark.parametrize(("emitter_cls", "gate", "adapter_key", "multi"), _TARGETS, ids=[t[2] for t in _TARGETS])
def test_a_model_with_no_http_operation_is_refused(emitter_cls, gate, adapter_key, multi) -> None:
    model = _import("openapi", "openapi/30-openapi-3.0-petstore.yaml")
    for service in model.services:
        service.operations = []
    with pytest.raises(ValueError):
        emitter_cls().emit(model)


def test_push_back_targets_the_cloud_gateways() -> None:
    for kind in ("aws-apigateway", "azure-apim", "apigee"):
        assert push_back(kind) == {"target": kind, "reason": None}


def test_match_value_round_trips_through_its_inverse() -> None:
    for operator, value in (("exact", "GET"), ("prefix", "acme-"), ("regex", "^x$"), ("suffix", ".json")):
        assert parse_match_value(render_match_value(operator, value)) == (operator, value)


# ---------------------------------------------------------------------------------------
# Honest fidelity packs
# ---------------------------------------------------------------------------------------


def _verdicts(emitter_cls, model) -> Dict[str, LossinessKind]:
    report = compute_lossiness_for_emitter(model, emitter_cls)
    return {
        item.construct_key: item.kind
        for item in report.items
        if item.construct_key in {o.key for o in model.operations()}
    }


def test_a_cross_format_route_is_approximated_not_ok() -> None:
    kinds = _verdicts(EnvoyXdsEmitter, _import("kong", "kong/02-typical-single-service-auth.yaml"))
    assert set(kinds.values()) == {LossinessKind.APPROX}


def test_a_same_format_route_without_policies_is_ok() -> None:
    model = _import("envoy-xds", "envoy-xds/01-minimal-route-config.yaml")
    assert set(_verdicts(EnvoyXdsEmitter, model).values()) == {LossinessKind.OK}


def test_a_policy_carrying_route_is_approximated_even_in_its_own_format() -> None:
    model = _import("istio", "istio/02-typical-virtualservice.yaml")
    kinds = _verdicts(IstioEmitter, model)
    with_plugins = {op.key for op in model.operations() if op.extras.get("plugins")}
    assert with_plugins and all(kinds[key] is LossinessKind.APPROX for key in with_plugins)


def test_apim_drops_any_method_operations_in_its_pack() -> None:
    model = _import("nginx", "nginx/01-minimal-server.conf")
    assert set(_verdicts(AzureApimEmitter, model).values()) == {LossinessKind.DROP}


# ---------------------------------------------------------------------------------------
# Envoy
# ---------------------------------------------------------------------------------------


def test_envoy_merges_virtual_hosts_that_share_a_domain() -> None:
    result = EnvoyXdsEmitter().emit(_import("nginx", "nginx/02-typical-reverse-proxy.conf"))
    document = yaml.safe_load(result.files[0].content)
    domains = [domain for vhost in document["virtual_hosts"] for domain in vhost["domains"]]
    assert len(domains) == len(set(domains))
    assert any(loss.subject == "merged-virtual-host" for loss in result.losses)


def test_envoy_pins_the_method_with_a_method_header_and_declares_auth() -> None:
    result = EnvoyXdsEmitter().emit(_import("kong", "kong/02-typical-single-service-auth.yaml"))
    routes = yaml.safe_load(result.files[0].content)["virtual_hosts"][0]["routes"]
    assert any({"name": ":method", "string_match": {"exact": "GET"}} in r["match"].get("headers", []) for r in routes)
    assert any(loss.subject == "auth-not-emitted" for loss in result.losses)


@pytest.mark.parametrize(
    ("document", "fragment"),
    [
        ({"virtual_hosts": []}, "name"),
        (
            {"name": "r", "virtual_hosts": [{"name": "v", "domains": ["*"], "routes": [{"match": {"prefix": "/"}}]}]},
            "exactly one of route",
        ),
        (
            {
                "name": "r",
                "virtual_hosts": [
                    {
                        "name": "v",
                        "domains": ["*"],
                        "routes": [{"match": {"prefix": "/", "path": "/x"}, "route": {"cluster": "c"}}],
                    }
                ],
            },
            "exactly one of prefix",
        ),
        (
            {"name": "r", "virtual_hosts": [{"name": "v", "domains": ["a"]}, {"name": "w", "domains": ["a"]}]},
            "already served",
        ),
    ],
)
def test_envoy_gate_rules(document, fragment) -> None:
    assert any(fragment in violation for violation in route_configuration_violations(document))


# ---------------------------------------------------------------------------------------
# Istio
# ---------------------------------------------------------------------------------------


def test_istio_synthesizes_a_host_and_splits_unweighted_destinations() -> None:
    model = _import("openapi", "openapi/30-openapi-3.0-petstore.yaml")
    model.servers = []  # no declared host at all
    result = IstioEmitter().emit(model)
    documents = list(yaml.safe_load_all(result.files[0].content))
    assert all(document["spec"]["hosts"] for document in documents)
    assert any(loss.subject == "synthesized-host" for loss in result.losses)


def test_istio_gate_requires_weights_that_sum_to_100() -> None:
    document = {
        "apiVersion": "networking.istio.io/v1",
        "kind": "VirtualService",
        "metadata": {"name": "a"},
        "spec": {
            "hosts": ["a"],
            "http": [
                {"route": [{"destination": {"host": "a"}, "weight": 50}, {"destination": {"host": "b"}, "weight": 10}]}
            ],
        },
    }
    assert any("sum to 100" in violation for violation in virtualservice_violations(document))


# ---------------------------------------------------------------------------------------
# Traefik
# ---------------------------------------------------------------------------------------


def test_traefik_rule_is_the_inverse_of_the_importers_dnf() -> None:
    model = _import("traefik", "traefik/04-stress-rule-grammar.yml")
    result, back = _validate_and_reimport(TraefikEmitter, validate_traefik_dynamic_config, "traefik", False, model)
    assert _coordinates(back) == _coordinates(model)
    from app.gateway_config_model import GatewayMatch
    from app.gateway_match import path_pattern

    match = GatewayMatch(path=path_pattern("PathPrefix", "/v2"), method="GET", headers=(("x-t", "prefix:acme"),))
    rule, approximated = render_rule([match], ["a.example.com", "b.example.com"])
    assert rule == (
        "(Host(`a.example.com`) || Host(`b.example.com`)) && PathPrefix(`/v2`) && Method(`GET`) && "
        "HeaderRegexp(`x-t`, `^acme`)"
    )
    assert approximated is True


def test_traefik_gate_refuses_a_router_naming_no_service() -> None:
    document = {"http": {"routers": {"r": {"rule": "Path(`/a`)", "service": "missing"}}, "services": {}}}
    assert any("not a declared service" in violation for violation in dynamic_config_violations(document))


# ---------------------------------------------------------------------------------------
# AWS API Gateway
# ---------------------------------------------------------------------------------------


def test_aws_re_emits_recorded_integrations_and_authorizers_verbatim() -> None:
    model = _import("aws-apigateway", "aws-apigateway/02-typical-rest-api-export.json")
    result, back = _validate_and_reimport(
        AwsApiGatewayEmitter, validate_aws_apigateway_document, "aws-apigateway", False, model
    )
    by_key = {op.key: op for op in back.operations()}
    for op in model.operations():
        assert by_key[op.key].extras.get("aws_apigateway", {}).get("integration") == op.extras.get(
            "aws_apigateway", {}
        ).get("integration")
        assert by_key[op.key].extras.get("security") == op.extras.get("security")


def test_aws_integrates_a_gateway_route_to_its_upstream() -> None:
    result = AwsApiGatewayEmitter().emit(_import("kong", "kong/02-typical-single-service-auth.yaml"))
    document = json.loads(result.files[0].content)
    integration = document["paths"]["/users/{userId}"]["get"]["x-amazon-apigateway-integration"]
    assert integration["type"] == "http_proxy" and integration["uri"].endswith("/users/{userId}")
    assert integration["requestParameters"] == {"integration.request.path.userId": "method.request.path.userId"}
    assert document["paths"]["/users/{userId}"]["get"]["security"] == [{"api_key": []}]


def test_aws_writes_any_method_and_a_mock_when_no_upstream_is_known() -> None:
    model = _import("nginx", "nginx/01-minimal-server.conf")
    model.servers = []
    for service in model.services:
        service.extras.pop("backend", None)
    document = json.loads(AwsApiGatewayEmitter().emit(model).files[0].content)
    item = next(iter(document["paths"].values()))
    assert item["x-amazon-apigateway-any-method"]["x-amazon-apigateway-integration"]["type"] in ("mock", "http_proxy")


def test_aws_gate_requires_an_integration_on_every_method() -> None:
    document = {"openapi": "3.0.3", "paths": {"/a": {"get": {"responses": {}}}}}
    assert any("needs an x-amazon-apigateway-integration" in v for v in aws_document_violations(document))


# ---------------------------------------------------------------------------------------
# Azure API Management
# ---------------------------------------------------------------------------------------


def test_apim_rebuilds_recorded_policy_facts_at_their_scope() -> None:
    model = _import("azure-apim", "azure-apim/02-typical-arm-api.json")
    result, back = _validate_and_reimport(AzureApimEmitter, validate_azure_apim_bundle, "azure-apim", True, model)
    by_key = {op.key: op for op in back.operations()}
    for op in model.operations():
        for key in ("backend", "rate_limits", "rewrite", "security"):
            assert by_key[op.key].extras.get(key) == op.extras.get(key), (op.key, key)


def test_apim_gate_checks_policy_documents() -> None:
    files = {
        "openapi.json": json.dumps({"openapi": "3.0.1", "paths": {"/a": {"get": {"operationId": "getA"}}}}),
        "policy.xml": "<policies><inbound><base /><made-up /></inbound></policies>",
        "operations/unknown.xml": "<policies><inbound><base /></inbound></policies>",
    }
    violations = azure_apim_bundle_violations(files)
    assert any("made-up" in v for v in violations)
    assert any("unknown" in v for v in violations)
    nested = dict(
        files,
        **{
            "policy.xml": (
                '<policies><inbound><ip-filter action="allow"><address>1.2.3.4</address></ip-filter>'
                "</inbound></policies>"
            )
        },
    )
    assert not any("address" in v for v in azure_apim_bundle_violations(nested))


# ---------------------------------------------------------------------------------------
# Apigee
# ---------------------------------------------------------------------------------------


def test_apigee_flows_reduce_back_to_path_and_verb() -> None:
    result = ApigeeEmitter().emit(_import("kong", "kong/02-typical-single-service-auth.yaml"))
    proxy = _members(result)["apiproxy/proxies/default.xml"]
    assert 'proxy.pathsuffix MatchesPath "/users/*"' in proxy.replace("&quot;", '"')
    assert "apiproxy/policies/verify-api-key.xml" in _members(result)
    assert any(loss.subject == "unnamed-path-parameter" for loss in result.losses)


def test_apigee_re_emits_a_recorded_bundle_verbatim() -> None:
    adapter = get_import_source("apigee")
    model = adapter.normalize(
        adapter.parse_bytes((_EXAMPLES / "apigee/02-typical-proxy-bundle.zip").read_bytes(), source_label="b.zip")
    )
    result = ApigeeEmitter().emit(model)
    assert _members(result) == {path: str(text) for path, text in model.raw["members"].items()}


def test_apigee_gate_requires_policy_files_for_steps() -> None:
    files = {
        "apiproxy/p.xml": (
            "<APIProxy name='p'><ProxyEndpoints><ProxyEndpoint>default</ProxyEndpoint></ProxyEndpoints>"
            "</APIProxy>"
        ),
        "apiproxy/proxies/default.xml": (
            "<ProxyEndpoint name='default'><Flows><Flow name='f'><Condition>x</Condition><Request><Step>"
            "<Name>missing</Name></Step></Request></Flow></Flows><HTTPProxyConnection><BasePath>/</BasePath></HTTPProxyConnection>"
            "<RouteRule name='default'/></ProxyEndpoint>"
        ),
    }
    assert any("names no policy" in v for v in apigee_bundle_violations(files))
