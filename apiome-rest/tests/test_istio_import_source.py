"""Unit tests for the Istio VirtualService ImportSource (FMT-7.4 / #5458)."""

from __future__ import annotations

import pytest

from app.envoy_xds_import_source import EnvoyXdsImportSource
from app.fileset import IntakeFileset
from app.gateway_api_import_source import GatewayApiImportSource
from app.import_source import DetectionInput, ImportSourceError
from app.istio_import_source import IstioImportSource
from app.istio_parser import is_istio, parse_istio


@pytest.fixture
def adapter() -> IstioImportSource:
    return IstioImportSource()


VIRTUAL_SERVICE = """\
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata: {name: orders, namespace: shop}
spec:
  hosts: [api.example.com]
  gateways: [shop/public]
  http:
    - name: orders
      match:
        - uri: {prefix: /orders}
          method: {exact: GET}
          headers:
            x-tenant: {prefix: acme-}
          queryParams:
            page: {regex: "^[0-9]+$"}
      route:
        - destination: {host: orders, subset: v1, port: {number: 8080}}
          weight: 90
        - destination: {host: orders, subset: v2, port: {number: 8080}}
          weight: 10
      timeout: 15s
      retries: {attempts: 3}
"""

GATEWAY = """\
apiVersion: networking.istio.io/v1
kind: Gateway
metadata: {name: public, namespace: shop}
spec:
  servers:
    - port: {number: 443, protocol: HTTPS}
      hosts: [api.example.com]
"""

DESTINATION_RULE = """\
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata: {name: orders, namespace: shop}
spec:
  host: orders.shop.svc.cluster.local
  subsets:
    - {name: v1, labels: {version: v1}}
    - {name: v2, labels: {version: v2}}
"""


def _stream(*documents: str) -> str:
    return "---\n".join(documents)


def _ops(adapter: IstioImportSource, text: str):
    model = adapter.normalize(adapter.parse(text, source_label="istio.yaml"))
    return model, {op.key: op for op in model.operations()}


# ---------------------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------------------


def test_detect_claims_a_virtual_service(adapter: IstioImportSource) -> None:
    result = adapter.detect(DetectionInput(text=VIRTUAL_SERVICE))
    assert (result.format, result.confidence) == ("istio", 0.97)


def test_detect_claims_supporting_kinds_lower(adapter: IstioImportSource) -> None:
    result = adapter.detect(DetectionInput(text=DESTINATION_RULE))
    assert result.format == "istio"
    assert 0.0 < result.confidence < 0.97
    assert is_istio(_stream(DESTINATION_RULE, VIRTUAL_SERVICE)) == "VirtualService"


def test_detect_declines_gateway_api_and_envoy(adapter: IstioImportSource) -> None:
    httproute = "apiVersion: gateway.networking.k8s.io/v1\nkind: HTTPRoute\nspec: {}\n"
    envoy = "name: r\nvirtual_hosts: []\n"
    for text in (httproute, envoy, "apiVersion: networking.istio.io/v1\nkind: Unknown\n"):
        assert adapter.detect(DetectionInput(text=text)).confidence == 0.0


def test_siblings_decline_istio() -> None:
    for sibling in (EnvoyXdsImportSource(), GatewayApiImportSource()):
        assert sibling.detect(DetectionInput(text=VIRTUAL_SERVICE)).confidence == 0.0


def test_detect_uses_a_pre_parsed_document(adapter: IstioImportSource) -> None:
    document = {"apiVersion": "networking.istio.io/v1beta1", "kind": "VirtualService"}
    assert adapter.detect(DetectionInput(document=document)).confidence == 0.97


# ---------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------


def test_rule_becomes_operations_with_matches_and_backends(adapter: IstioImportSource) -> None:
    model, ops = _ops(adapter, VIRTUAL_SERVICE)
    op = ops["GET /orders"]
    assert {(p.name, p.location.value, p.extras["match_value"]) for p in op.parameters} == {
        ("x-tenant", "header", "prefix:acme-"),
        ("page", "query", "regex:^[0-9]+$"),
    }
    assert op.extras["backends"] == [
        {"name": "orders", "namespace": "shop", "port": 8080, "weight": 90, "subset": "v1"},
        {"name": "orders", "namespace": "shop", "port": 8080, "weight": 10, "subset": "v2"},
    ]
    assert op.extras["plugins"] == ["retries", "timeout"]
    assert op.extras["gateway_route"] == "orders"
    assert op.extras["gateways"] == ["shop/public"]
    assert [service.name for service in model.services] == ["shop/orders"]
    # Bound to a gateway the input does not include: it may terminate TLS.
    assert [server.url for server in model.servers] == ["https://api.example.com"]


def test_multi_document_stream_resolves_gateway_and_subsets(adapter: IstioImportSource) -> None:
    model, ops = _ops(adapter, _stream(GATEWAY, VIRTUAL_SERVICE, DESTINATION_RULE))
    assert list(ops) == ["GET /orders"]
    ignored = {entry["construct"]: entry["count"] for entry in model.extras["gateway"]["ignored_constructs"]}
    assert ignored == {"DestinationRule": 1, "Gateway": 1}


def test_unconditional_rule_matches_every_path(adapter: IstioImportSource) -> None:
    text = """\
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata: {name: ping}
spec:
  hosts: [ping]
  http:
    - route:
        - destination: {host: ping}
"""
    model, ops = _ops(adapter, text)
    assert list(ops) == ["ANY /"]
    assert ops["ANY /"].extras["path_match"] == {"kind": "prefix", "raw": "/"}
    # A mesh-internal host with no gateway is plain HTTP.
    assert [server.url for server in model.servers] == ["http://ping"]


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ({"exact": "post"}, ["POST /x"]),
        ({"regex": "GET|HEAD"}, ["GET /x", "HEAD /x"]),
        ({"regex": "^(GET|PUT)$"}, ["GET /x", "PUT /x"]),
        ({"prefix": "P"}, ["ANY /x"]),
    ],
)
def test_method_matches(adapter: IstioImportSource, method, expected) -> None:
    import yaml

    document = yaml.safe_load(VIRTUAL_SERVICE)
    rule = document["spec"]["http"][0]
    rule["match"] = [{"uri": {"exact": "/x"}, "method": method}]
    rule["route"] = [{"destination": {"host": "orders"}}]
    _model, ops = _ops(adapter, yaml.safe_dump(document))
    assert sorted(ops) == expected


def test_unmodeled_constructs_are_declared_not_flattened(adapter: IstioImportSource) -> None:
    text = """\
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata: {name: lab, namespace: lab}
spec:
  hosts: [lab.example.com]
  http:
    - name: kept
      match:
        - uri: {prefix: /kept}
          sourceLabels: {app: front}
          withoutHeaders: {x-blocked: {exact: "true"}}
          scheme: {exact: https}
          port: 443
      route: [{destination: {host: kept}}]
    - name: handed-off
      match: [{uri: {prefix: /delegated}}]
      delegate: {name: other, namespace: lab}
  tls:
    - match: [{port: 8443, sniHosts: [s.example.com]}]
      route: [{destination: {host: s}}]
  tcp:
    - match: [{port: 5432}]
      route: [{destination: {host: db}}]
---
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata: {name: deny}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: lab}
"""
    model, ops = _ops(adapter, text)
    assert list(ops) == ["ANY /kept"]
    assert ops["ANY /kept"].extras["match_qualifiers"] == {"scheme": [{"exact": "https"}], "port": [443]}
    ignored = {entry["construct"] for entry in model.extras["gateway"]["ignored_constructs"]}
    assert ignored == {
        "delegate",
        "tls",
        "tcp",
        "match.sourceLabels",
        "match.withoutHeaders",
        "AuthorizationPolicy",
        "Deployment",
    }


def test_policy_plugins_are_listed_on_the_report(adapter: IstioImportSource) -> None:
    model, _ = _ops(adapter, VIRTUAL_SERVICE)
    assert {"name": "timeout", "scope": "route"} in model.extras["gateway"]["unmodeled_plugins"]


# ---------------------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("  \n", "INPUT_MALFORMED"),
        (
            "apiVersion: networking.istio.io/v1\nkind: VirtualService\nspec:\n  hosts: [a]\n   http: []\n x: 1\n",
            "INPUT_MALFORMED",
        ),
        ("apiVersion: networking.istio.io/v1\x00\nkind: VirtualService\n", "INPUT_ENCODING_INVALID"),
        ("name: r\nvirtual_hosts: []\n", "FORMAT_MISMATCH"),
        (
            "apiVersion: networking.istio.io/v1\nkind: VirtualService\nmetadata: {name: x}\nspec: {hosts: [a]}\n",
            "INPUT_SEMANTIC_INVALID",
        ),
        (DESTINATION_RULE, "INPUT_SEMANTIC_INVALID"),
        (VIRTUAL_SERVICE.replace("timeout: 15s\n      retries: {attempts: 3}\n", "timeout: 15\n"), "INPUT_TRUNCATED"),
        (
            "apiVersion: networking.istio.io/v1\nkind: VirtualService\nmetadata: {name: o}\nspec:\n"
            "  hosts: [a]\n  http:\n    - route:\n        - destination:\n"
            "            host: orders.shop.svc.cluster\n",
            "INPUT_TRUNCATED",
        ),
    ],
)
def test_parse_failures_carry_codes(adapter: IstioImportSource, text: str, code: str) -> None:
    with pytest.raises(ImportSourceError) as exc_info:
        adapter.parse(text)
    assert exc_info.value.code == code


def test_undefined_subset_is_an_unresolved_reference(adapter: IstioImportSource) -> None:
    rule = DESTINATION_RULE.replace("    - {name: v2, labels: {version: v2}}\n", "")
    with pytest.raises(ImportSourceError) as exc_info:
        adapter.parse(_stream(VIRTUAL_SERVICE, rule))
    assert exc_info.value.code == "INPUT_REFERENCE_UNRESOLVED"
    assert "'v2'" in str(exc_info.value)


def test_subset_without_a_destination_rule_stands(adapter: IstioImportSource) -> None:
    assert parse_istio(VIRTUAL_SERVICE).routes


def test_short_host_and_fqdn_meet(adapter: IstioImportSource) -> None:
    # The route names `orders` in namespace shop; the rule names the FQDN — the same host.
    rule = DESTINATION_RULE.replace("    - {name: v2, labels: {version: v2}}\n", "")
    with pytest.raises(ImportSourceError):
        adapter.parse(_stream(VIRTUAL_SERVICE, rule))
    two_part = rule.replace("orders.shop.svc.cluster.local", "orders.shop")
    with pytest.raises(ImportSourceError):
        adapter.parse(_stream(VIRTUAL_SERVICE, two_part))


# ---------------------------------------------------------------------------------------
# GitOps directory
# ---------------------------------------------------------------------------------------


def test_fileset_reads_the_directory_as_one_stream(adapter: IstioImportSource) -> None:
    fileset = IntakeFileset(
        root="virtualservice.yaml",
        members={
            "virtualservice.yaml": VIRTUAL_SERVICE,
            "gateway.yaml": GATEWAY,
            "destinationrule.yaml": DESTINATION_RULE,
            "kustomization.yaml": "resources: [virtualservice.yaml]\n",
        },
    )
    model = adapter.normalize(adapter.parse_fileset(fileset))
    assert [op.key for op in model.operations()] == ["GET /orders"]
    assert [server.url for server in model.servers] == ["https://api.example.com"]


def test_fileset_subset_check_crosses_files(adapter: IstioImportSource) -> None:
    rule = DESTINATION_RULE.replace("    - {name: v2, labels: {version: v2}}\n", "")
    fileset = IntakeFileset(root="vs.yaml", members={"vs.yaml": VIRTUAL_SERVICE, "dr.yaml": rule})
    with pytest.raises(ImportSourceError) as exc_info:
        adapter.parse_fileset(fileset)
    assert exc_info.value.code == "INPUT_REFERENCE_UNRESOLVED"


def test_fileset_member_errors_name_the_member(adapter: IstioImportSource) -> None:
    fileset = IntakeFileset(root="vs.yaml", members={"vs.yaml": VIRTUAL_SERVICE, "bad.yaml": "a: [b\n"})
    with pytest.raises(ImportSourceError) as exc_info:
        adapter.parse_fileset(fileset)
    assert str(exc_info.value).startswith("bad.yaml:")


def test_empty_fileset_is_refused(adapter: IstioImportSource) -> None:
    with pytest.raises(ImportSourceError):
        adapter.parse_fileset(IntakeFileset(root="x", members={}))


def test_normalize_refuses_a_foreign_ast(adapter: IstioImportSource) -> None:
    with pytest.raises(ImportSourceError):
        adapter.normalize("not a document")
