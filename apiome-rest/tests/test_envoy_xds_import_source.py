"""Unit tests for the Envoy xDS route-configuration ImportSource (FMT-7.4 / #5458)."""

from __future__ import annotations

import json

import pytest

from app.envoy_xds_import_source import EnvoyXdsImportSource
from app.envoy_xds_parser import classify_envoy_document, parse_envoy_xds
from app.fileset import IntakeFileset
from app.gateway_api_import_source import GatewayApiImportSource
from app.import_source import DetectionInput, ImportSourceError
from app.istio_import_source import IstioImportSource
from app.kong_import_source import KongImportSource

#: The HttpConnectionManager ``@type`` URL, spliced into the YAML fixtures below.
HCM_TYPE_URL = (
    "type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3."
    "HttpConnectionManager"
)


@pytest.fixture
def adapter() -> EnvoyXdsImportSource:
    return EnvoyXdsImportSource()


ROUTE_CONFIG = """\
name: shop_route
virtual_hosts:
  - name: shop
    domains: ["shop.example.com", "*"]
    routes:
      - match: {prefix: /orders}
        route: {cluster: orders, timeout: 15s}
"""

BOOTSTRAP = """\
static_resources:
  listeners:
    - name: ingress
      filter_chains:
        - transport_socket: {name: envoy.transport_sockets.tls}
          filters:
            - name: envoy.filters.network.http_connection_manager
              typed_config:
                "@type": HCM_TYPE_URL
                route_config:
                  name: shop_route
                  virtual_hosts:
                    - name: shop
                      domains: [shop.example.com]
                      routes:
                        - match:
                            prefix: /orders
                            headers:
                              - name: ":method"
                                string_match: {exact: POST}
                              - name: x-tenant
                                string_match: {prefix: acme-}
                          route: {cluster: orders}
                http_filters:
                  - name: envoy.filters.http.jwt_authn
                    typed_config:
                      providers:
                        issuer-a: {issuer: https://login.example.com/}
                  - name: envoy.filters.http.cors
                  - name: envoy.filters.http.router
  clusters:
    - name: orders
""".replace("HCM_TYPE_URL", HCM_TYPE_URL)


def _ops(adapter: EnvoyXdsImportSource, text: str):
    model = adapter.normalize(adapter.parse(text, source_label="envoy.yaml"))
    return model, {op.key: op for op in model.operations()}


# ---------------------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        ROUTE_CONFIG,
        BOOTSTRAP,
        json.dumps(
            {
                "type_url": "type.googleapis.com/envoy.config.route.v3.RouteConfiguration",
                "resources": [{"@type": "type.googleapis.com/envoy.config.route.v3.RouteConfiguration"}],
            }
        ),
    ],
)
def test_detect_claims_envoy_shapes(adapter: EnvoyXdsImportSource, text: str) -> None:
    result = adapter.detect(DetectionInput(text=text, filename="envoy.yaml"))
    assert result.format == "envoy-xds"
    assert result.confidence >= 0.85


def test_detect_declines_siblings(adapter: EnvoyXdsImportSource) -> None:
    istio = "apiVersion: networking.istio.io/v1\nkind: VirtualService\nspec: {http: []}\n"
    httproute = "apiVersion: gateway.networking.k8s.io/v1\nkind: HTTPRoute\nspec: {}\n"
    kong = "_format_version: '3.0'\nservices: []\n"
    for text in (istio, httproute, kong, "openapi: 3.1.0\ninfo: {title: x}\n"):
        assert adapter.detect(DetectionInput(text=text)).confidence == 0.0


def test_siblings_decline_envoy() -> None:
    for sibling in (IstioImportSource(), GatewayApiImportSource(), KongImportSource()):
        assert sibling.detect(DetectionInput(text=ROUTE_CONFIG)).confidence < 0.85


def test_detect_uses_a_pre_parsed_document(adapter: EnvoyXdsImportSource) -> None:
    document = {"name": "r", "virtual_hosts": []}
    assert adapter.detect(DetectionInput(document=document)).format == "envoy-xds"


@pytest.mark.parametrize(
    ("document", "shape"),
    [
        ({"static_resources": {}}, "bootstrap"),
        ({"dynamic_resources": {}}, "bootstrap"),
        ({"type_url": "type.googleapis.com/envoy.config.route.v3.RouteConfiguration"}, "discovery-response"),
        ({"resources": [{"@type": "type.googleapis.com/envoy.config.cluster.v3.Cluster"}]}, "resources"),
        ({"name": "r", "virtual_hosts": []}, "route-config"),
        ({"name": "r", "validate_clusters": True}, "route-config"),
        ({"name": "r"}, None),
        ({"apiVersion": "networking.istio.io/v1"}, None),
        (["not", "a", "mapping"], None),
    ],
)
def test_classify(document, shape) -> None:
    assert classify_envoy_document(document) == shape


# ---------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------


def test_route_config_imports_one_operation_per_route(adapter: EnvoyXdsImportSource) -> None:
    model, ops = _ops(adapter, ROUTE_CONFIG)
    op = ops["ANY /orders"]
    assert op.extras["path_match"] == {"kind": "prefix", "raw": "/orders"}
    assert op.extras["methods_unrestricted"] is True
    assert op.extras["backends"] == [{"name": "orders"}]
    assert op.extras["plugins"] == ["timeout"]
    assert op.extras["virtual_host"] == "shop"
    # "*" matches any host and is not a server.
    assert [server.url for server in model.servers] == ["http://shop.example.com"]


def test_bootstrap_reads_method_headers_auth_and_tls(adapter: EnvoyXdsImportSource) -> None:
    model, ops = _ops(adapter, BOOTSTRAP)
    op = ops["POST /orders"]
    assert [(p.name, p.location.value, p.extras) for p in op.parameters] == [
        ("x-tenant", "header", {"match_value": "prefix:acme-"})
    ]
    assert op.extras["security"][0]["scheme"] == "bearer"
    assert op.extras["security"][0]["detail"] == {
        "providers": ["issuer-a"],
        "issuers": ["https://login.example.com/"],
    }
    assert [server.url for server in model.servers] == ["https://shop.example.com"]
    report = model.extras["gateway"]
    assert report["global_plugins"] == ["envoy.filters.http.cors"]
    assert {"name": "envoy.filters.http.cors", "scope": "global"} in report["unmodeled_plugins"]
    assert model.extras["inferred_auth_schemes"] == ["bearer"]


def test_every_path_matcher_and_qualifier(adapter: EnvoyXdsImportSource) -> None:
    text = """\
name: m
virtual_hosts:
  - name: v
    domains: ["*"]
    routes:
      - match: {path: /a}
        route: {cluster: c}
      - match: {path_separated_prefix: /seg}
        route: {cluster: c}
      - match: {safe_regex: {regex: "^/u/(?P<id>[0-9]+)$"}}
        route: {cluster: c}
      - match: {prefix: /exp, runtime_fraction: {default_value: {numerator: 5}}, grpc: {}}
        route: {cluster: c}
      - match: {connect_matcher: {}}
        route: {cluster: c}
      - match:
          prefix: /q
          headers:
            - {name: x-debug, invert_match: true, present_match: true}
            - {name: ":authority", string_match: {exact: a}}
          query_parameters:
            - {name: q, present_match: true}
            - {name: page, string_match: {safe_regex: {regex: "^[0-9]+$"}}}
        route: {cluster: c}
"""
    model, ops = _ops(adapter, text)
    assert ops["ANY /a"].extras["path_match"]["kind"] == "exact"
    assert ops["ANY /seg"].extras["path_match"]["kind"] == "prefix"
    regex_op = ops["ANY /u/{id}"]
    assert regex_op.parameters[0].extras["provenance"] == "inferred"
    assert {(p.name, p.extras.get("match_value", "")) for p in ops["ANY /q"].parameters} == {
        ("q", ""),
        ("page", "regex:^[0-9]+$"),
    }
    ignored = {entry["construct"]: entry for entry in model.extras["gateway"]["ignored_constructs"]}
    assert set(ignored) == {
        "match.connect_matcher",
        "match.grpc",
        "match.runtime_fraction",
        "match.headers.invert_match",
        "match.headers.:authority",
    }
    # The CONNECT route is declared, not turned into an operation.
    assert len(ops) == 5


def test_weighted_clusters_redirects_and_direct_responses(adapter: EnvoyXdsImportSource) -> None:
    text = """\
name: m
virtual_hosts:
  - name: v
    domains: ["*"]
    require_tls: ALL
    cors: {allow_methods: GET}
    routes:
      - match: {prefix: /checkout}
        route:
          weighted_clusters:
            clusters: [{name: v1, weight: 90}, {name: v2, weight: 10}]
      - match: {path: /health}
        direct_response: {status: 200}
      - match: {prefix: /old}
        redirect: {path_redirect: /new}
"""
    _model, ops = _ops(adapter, text)
    assert ops["ANY /checkout"].extras["backends"] == [{"name": "v1", "weight": 90}, {"name": "v2", "weight": 10}]
    assert ops["ANY /health"].extras["plugins"] == ["cors", "direct_response"]
    assert ops["ANY /old"].extras["plugins"] == ["cors", "redirect"]
    assert ops["ANY /old"].extras["require_tls"] == "ALL"


def test_xds_v2_typed_resources_are_read(adapter: EnvoyXdsImportSource) -> None:
    text = json.dumps(
        {
            "version_info": "1",
            "type_url": "type.googleapis.com/envoy.api.v2.RouteConfiguration",
            "resources": [
                {
                    "@type": "type.googleapis.com/envoy.api.v2.RouteConfiguration",
                    "name": "r",
                    "virtual_hosts": [
                        {
                            "name": "v",
                            "domains": ["*"],
                            "routes": [
                                {
                                    "match": {
                                        "prefix": "/v2",
                                        "headers": [{"name": "x-a", "exact_match": "1"}],
                                    },
                                    "route": {"cluster": "c"},
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )
    _model, ops = _ops(adapter, text)
    assert ops["ANY /v2"].parameters[0].extras == {"match_value": "1"}


def test_credentials_in_policy_are_redacted(adapter: EnvoyXdsImportSource) -> None:
    text = """\
name: m
virtual_hosts:
  - name: v
    domains: ["*"]
    typed_per_filter_config:
      envoy.filters.http.oauth2: {secret: s3cr3t-value}
    routes:
      - match: {prefix: /x}
        route: {cluster: c}
"""
    model, _ops_ = _ops(adapter, text)
    assert model.extras["gateway"]["credential_redactions"] == 1
    assert "s3cr3t-value" not in json.dumps(model.model_dump(mode="json"))


def test_dynamic_sources_are_declared(adapter: EnvoyXdsImportSource) -> None:
    text = """\
dynamic_resources:
  lds_config: {ads: {}}
  cds_config: {ads: {}}
static_resources:
  listeners:
    - name: l
      filter_chains:
        - filters:
            - name: envoy.filters.network.http_connection_manager
              typed_config:
                "@type": HCM_TYPE_URL
                rds: {route_config_name: remote_routes}
                route_config:
                  name: local
                  virtual_hosts:
                    - name: v
                      domains: ["*"]
                      routes:
                        - match: {prefix: /}
                          route: {cluster: from_the_control_plane}
  clusters:
    - name: something_else
""".replace("HCM_TYPE_URL", HCM_TYPE_URL)
    model, _ = _ops(adapter, text)
    ignored = {entry["construct"] for entry in model.extras["gateway"]["ignored_constructs"]}
    assert {"dynamic_resources.lds_config", "rds.remote_routes"} <= ignored
    # Clusters also come from ADS, so an unknown cluster is not provably dangling.
    assert model.operations()


# ---------------------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("   \n", "INPUT_MALFORMED"),
        ("name: r\nvirtual_hosts:\n  - name: v\n   domains: []\n  routes: []\n", "INPUT_MALFORMED"),
        ("name: r\x00\nvirtual_hosts: []\n", "INPUT_ENCODING_INVALID"),
        ("apiVersion: networking.istio.io/v1\nkind: VirtualService\n", "FORMAT_MISMATCH"),
        ("name: r\nvalidate_clusters: true\n", "INPUT_SEMANTIC_INVALID"),
        (
            "name: r\nvirtual_hosts:\n  - name: v\n    domains: ['*']\n    routes:\n"
            "      - match: {connect_matcher: {}}\n        route: {cluster: c}\n",
            "INPUT_SEMANTIC_INVALID",
        ),
        (
            "name: r\nvirtual_hosts:\n  - name: v\n    domains: ['*']\n    routes:\n"
            "      - match: {prefix: /x}\n        route:\n          cluster: c\n          timeout: 15\n",
            "INPUT_TRUNCATED",
        ),
    ],
)
def test_parse_failures_carry_codes(adapter: EnvoyXdsImportSource, text: str, code: str) -> None:
    with pytest.raises(ImportSourceError) as exc_info:
        adapter.parse(text)
    assert exc_info.value.code == code


def test_unresolved_cluster_only_when_the_input_owns_clusters(adapter: EnvoyXdsImportSource) -> None:
    owned = BOOTSTRAP.replace("cluster: orders}", "cluster: missing}")
    with pytest.raises(ImportSourceError) as exc_info:
        adapter.parse(owned)
    assert exc_info.value.code == "INPUT_REFERENCE_UNRESOLVED"
    assert "missing" in str(exc_info.value)
    # A bare route configuration declares no clusters, so its references stand.
    assert parse_envoy_xds(ROUTE_CONFIG).routes


# ---------------------------------------------------------------------------------------
# Filesystem xDS
# ---------------------------------------------------------------------------------------

FS_BOOTSTRAP = """\
dynamic_resources:
  cds_config: {path_config_source: {path: /etc/envoy/cds.yaml}}
static_resources:
  listeners:
    - name: l
      filter_chains:
        - filters:
            - name: envoy.filters.network.http_connection_manager
              typed_config:
                "@type": HCM_TYPE_URL
                rds:
                  route_config_name: edge
                  config_source: {path_config_source: {path: /etc/envoy/rds.yaml}}
""".replace("HCM_TYPE_URL", HCM_TYPE_URL)
FS_RDS = """\
resources:
  - "@type": type.googleapis.com/envoy.config.route.v3.RouteConfiguration
    name: edge
    virtual_hosts:
      - name: edge
        domains: [api.example.com]
        routes:
          - match: {prefix: /shipments}
            route: {cluster: shipments}
"""
FS_CDS = """\
resources:
  - "@type": type.googleapis.com/envoy.config.cluster.v3.Cluster
    name: shipments
"""


def test_fileset_resolves_rds_and_cds_members(adapter: EnvoyXdsImportSource) -> None:
    fileset = IntakeFileset(
        root="bootstrap.yaml",
        members={"bootstrap.yaml": FS_BOOTSTRAP, "rds.yaml": FS_RDS, "cds.yaml": FS_CDS},
    )
    model = adapter.normalize(adapter.parse_fileset(fileset))
    assert [op.key for op in model.operations()] == ["ANY /shipments"]
    ignored = {entry["construct"] for entry in model.extras["gateway"]["ignored_constructs"]}
    assert "rds.edge" not in ignored


def test_fileset_checks_clusters_its_cds_member_supplies(adapter: EnvoyXdsImportSource) -> None:
    fileset = IntakeFileset(
        root="bootstrap.yaml",
        members={
            "bootstrap.yaml": FS_BOOTSTRAP,
            "rds.yaml": FS_RDS.replace("cluster: shipments", "cluster: parcels"),
            "cds.yaml": FS_CDS,
        },
    )
    with pytest.raises(ImportSourceError) as exc_info:
        adapter.parse_fileset(fileset)
    assert exc_info.value.code == "INPUT_REFERENCE_UNRESOLVED"


def test_fileset_member_errors_name_the_member(adapter: EnvoyXdsImportSource) -> None:
    fileset = IntakeFileset(root="bootstrap.yaml", members={"bootstrap.yaml": FS_BOOTSTRAP, "rds.yaml": "a: [b\n"})
    with pytest.raises(ImportSourceError) as exc_info:
        adapter.parse_fileset(fileset)
    assert str(exc_info.value).startswith("rds.yaml:")


def test_empty_fileset_is_refused(adapter: EnvoyXdsImportSource) -> None:
    with pytest.raises(ImportSourceError):
        adapter.parse_fileset(IntakeFileset(root="x", members={}))


def test_normalize_refuses_a_foreign_ast(adapter: EnvoyXdsImportSource) -> None:
    with pytest.raises(ImportSourceError):
        adapter.normalize({"not": "a document"})
