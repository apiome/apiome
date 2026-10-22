"""Unit tests for the Consul service-definition ImportSource (FMT-7.5 / #5459)."""

from __future__ import annotations

import json

import pytest

from app.consul_import_source import ConsulImportSource
from app.consul_parser import parse_hcl
from app.fileset import IntakeFileset
from app.gateway_config_model import GatewayConfigParseError
from app.import_source import DetectionInput, ImportSourceError


@pytest.fixture
def adapter() -> ConsulImportSource:
    return ConsulImportSource()


SERVICE = json.dumps(
    {
        "service": {
            "name": "orders",
            "port": 8080,
            "tags": ["http", "urlprefix-/v2/orders"],
            "meta": {"protocol": "http"},
        }
    }
)

ROUTER_HCL = """\
services {
  name = "payments"
  port = 8443
  meta = { protocol = "http" }
}

Kind = "service-resolver"
Name = "payments"
Subsets = {
  canary = { Filter = "Service.Meta.version == 2" }
}

Kind = "service-router"
Name = "payments"
Routes = [
  {
    Match {
      HTTP {
        PathPrefix = "/v3/payments"
        Methods    = ["POST"]
        Header = [ { Name = "x-employee", Exact = "true" }, { Name = "x-bot", Present = true, Invert = true } ]
        QueryParam = [ { Name = "mode", Exact = "final" } ]
      }
    }
    Destination {
      Service       = "payments"
      ServiceSubset = "canary"
      NumRetries    = 2
    }
  },
]
"""


def _ops(adapter: ConsulImportSource, text: str):
    model = adapter.normalize(adapter.parse(text, source_label="consul"))
    return model, {op.key: op for op in model.operations()}


def _ignored(model) -> set:
    return {entry["construct"] for entry in model.extras["gateway"]["ignored_constructs"]}


# ---------------------------------------------------------------------------------------
# HCL
# ---------------------------------------------------------------------------------------


def test_hcl_splits_entries_on_each_kind() -> None:
    documents = parse_hcl(ROUTER_HCL)
    assert [document.get("Kind") for document in documents] == [None, "service-resolver", "service-router"]
    assert documents[0]["services"]["meta"] == {"protocol": "http"}


def test_hcl_repeated_blocks_become_a_list() -> None:
    documents = parse_hcl('services {\n name = "a"\n}\nservices {\n name = "b"\n}\n')
    assert [entry["name"] for entry in documents[0]["services"]] == ["a", "b"]


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ('services {\n name = "a"\n', "INPUT_TRUNCATED"),
        ('name = "a\n', "INPUT_TRUNCATED"),
        ("name = = 1\n", "INPUT_MALFORMED"),
    ],
)
def test_hcl_errors(text: str, code: str) -> None:
    with pytest.raises(GatewayConfigParseError) as exc:
        parse_hcl(text)
    assert exc.value.code == code


# ---------------------------------------------------------------------------------------
# Detection and import
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", [SERVICE, ROUTER_HCL, json.dumps({"Kind": "ingress-gateway", "Name": "g"})])
def test_detection(adapter: ConsulImportSource, text: str) -> None:
    result = adapter.detect(DetectionInput(text=text))
    assert result.matched and result.confidence >= 0.8


def test_kong_services_are_not_consul(adapter: ConsulImportSource) -> None:
    kong = json.dumps({"_format_version": "3.0", "services": [{"name": "a", "url": "http://a", "routes": []}]})
    assert not adapter.detect(DetectionInput(text=kong)).matched


def test_urlprefix_tag_is_an_inferred_convention_route(adapter: ConsulImportSource) -> None:
    model, ops = _ops(adapter, SERVICE)
    op = ops["ANY /v2/orders"]
    assert op.extras["path_source"] == "urlprefix-tag"
    assert op.extras["provenance"] == "inferred"
    assert model.services[0].extras["backend"] == {"protocol": "http", "port": 8080}


def test_plain_service_is_a_catch_all(adapter: ConsulImportSource) -> None:
    _model, ops = _ops(adapter, json.dumps({"service": {"name": "ping", "port": 80}}))
    assert list(ops) == ["ANY /"]


def test_router_matches_become_operations(adapter: ConsulImportSource) -> None:
    model, ops = _ops(adapter, ROUTER_HCL)
    op = ops["POST /v3/payments"]
    assert {(p.location.value, p.name) for p in op.parameters} == {("header", "x-employee"), ("query", "mode")}
    assert op.extras["backends"] == [{"name": "payments", "subset": "canary"}]
    assert op.extras["plugins"] == ["NumRetries"]
    assert "ANY /" in ops  # the router's fall-through
    assert "match.Header.Invert" in _ignored(model)


def test_grpc_service_is_declared_not_routed(adapter: ConsulImportSource) -> None:
    text = json.dumps({"service": {"name": "rpc", "port": 9000, "meta": {"protocol": "grpc"}}})
    model, ops = _ops(adapter, text)
    assert ops == {}
    assert "service.non-http" in _ignored(model)


def test_ingress_gateway_http_listener(adapter: ConsulImportSource) -> None:
    entry = {
        "Kind": "ingress-gateway",
        "Name": "edge",
        "TLS": {"Enabled": True},
        "Listeners": [
            {"Port": 8443, "Protocol": "http", "Services": [{"Name": "orders", "Hosts": ["api.example.com"]}]},
            {"Port": 5432, "Protocol": "tcp", "Services": [{"Name": "db"}]},
        ],
    }
    model, ops = _ops(adapter, json.dumps(entry))
    assert ops["ANY /"].extras["hosts"] == ["api.example.com"]
    assert [server.url for server in model.servers] == ["https://api.example.com"]
    assert "ingress-gateway.tcp-listener" in _ignored(model)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ('{"service": {"name": "a", "port": 1,}}', "INPUT_MALFORMED"),
        ('{"service": {"name": "a", "checks": [{"http": "http://x', "INPUT_TRUNCATED"),
        ('{"service": {"name": "a", "tags": ["x"]}}', "INPUT_SEMANTIC_INVALID"),
        ('{"api_id": "x", "proxy": {}}', "FORMAT_MISMATCH"),
        (
            '{"Kind": "service-router", "Name": "a", "Routes": [{"Destination": {"Service": "b"}}]}',
            "INPUT_REFERENCE_UNRESOLVED",
        ),
    ],
)
def test_error_codes(adapter: ConsulImportSource, text: str, code: str) -> None:
    with pytest.raises(ImportSourceError) as exc:
        adapter.parse(text)
    assert exc.value.code == code


def test_undefined_subset_is_refused_when_the_resolver_is_present(adapter: ConsulImportSource) -> None:
    with pytest.raises(ImportSourceError) as exc:
        adapter.parse(ROUTER_HCL.replace('ServiceSubset = "canary"', 'ServiceSubset = "blue"'))
    assert exc.value.code == "INPUT_REFERENCE_UNRESOLVED"


def test_service_set_resolves_router_destinations(adapter: ConsulImportSource) -> None:
    router = {
        "Kind": "service-router",
        "Name": "orders",
        "Routes": [{"Match": {"HTTP": {"PathPrefix": "/v2/products"}}, "Destination": {"Service": "catalogue"}}],
    }
    fileset = IntakeFileset.from_members(
        {
            "orders.json": json.dumps({"service": {"name": "orders", "port": 1}}),
            "catalogue.json": json.dumps({"service": {"name": "catalogue", "port": 2}}),
            "router.json": json.dumps(router),
        },
        root="orders.json",
    )
    model = adapter.normalize(adapter.parse_fileset(fileset))
    keys = {op.key.split("#")[0] for op in model.operations()}
    assert {"ANY /v2/products", "ANY /"} <= keys


def test_catalog_export_merges_instances(adapter: ConsulImportSource) -> None:
    export = {
        "Nodes": [
            {"Node": "n1", "Services": {"a-1": {"Service": "a", "Port": 80, "Address": "10.0.0.1", "Tags": ["http"]}}},
            {"Node": "n2", "Services": {"a-2": {"Service": "a", "Port": 80, "Address": "10.0.0.2"}}},
        ]
    }
    model, _ops_ = _ops(adapter, json.dumps(export))
    assert len(model.services[0].extras["instances"]) == 2
