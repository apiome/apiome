"""Shared rules of the service-mesh route sources — FMT-7.4 (#5458).

Pins what ``envoy-xds`` and ``istio`` must agree on with each other and with the shipped
``gateway-api`` adapter: one match-normalization table, the same provenance, the same
coverage-ledger statements and catalog routing, and the end-of-stream truncation rule. The
per-format behaviour lives in ``test_envoy_xds_import_source.py`` and
``test_istio_import_source.py``.
"""

from __future__ import annotations

import pytest

from app.envoy_xds_import_source import EnvoyXdsImportSource
from app.envoy_xds_parser import ENVOY_PATH_MATCHERS
from app.gateway_api_import_source import GatewayApiImportSource
from app.gateway_api_parser import PATH_TYPE_KINDS
from app.gateway_config_model import GatewayConfigParseError
from app.gateway_config_normalizer import INFERRED_ROUTE_FLAVORS, POLICY_PLUGIN_FLAVORS
from app.import_preview_manifest import (
    KNOWN_PARSER_LIMITS,
    CoverageClass,
    build_import_preview_manifest,
    paginate_import_preview_manifest,
)
from app.import_routing import GATEWAY_CONFIG_FORMATS, decide_import_routing
from app.import_source import get_import_source, load_builtin_import_sources
from app.istio_import_source import IstioImportSource
from app.istio_parser import ISTIO_URI_MATCHERS
from app.mesh_route_common import (
    LimitCollector,
    is_duration,
    is_truncated_cluster_host,
    path_pattern_for,
    raise_if_truncated_tail,
    render_string_match,
)

ENVOY = """\
name: shop
virtual_hosts:
  - name: shop
    domains: [shop.example.com]
    routes:
      - match: {path: /exact}
        route: {cluster: c}
      - match: {prefix: /prefix}
        route: {cluster: c}
      - match: {safe_regex: {regex: "^/items/[0-9]+$"}}
        route: {cluster: c}
"""

ISTIO = """\
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata: {name: shop, namespace: retail}
spec:
  hosts: [shop.example.com]
  http:
    - match:
        - uri: {exact: /exact}
        - uri: {prefix: /prefix}
        - uri: {regex: "^/items/[0-9]+$"}
      route:
        - destination: {host: c}
"""

GATEWAY_API = """\
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata: {name: shop, namespace: retail}
spec:
  hostnames: [shop.example.com]
  rules:
    - matches:
        - path: {type: Exact, value: /exact}
        - path: {type: PathPrefix, value: /prefix}
        - path: {type: RegularExpression, value: "^/items/[0-9]+$"}
      backendRefs:
        - name: c
"""


def _path_matches(adapter, text: str) -> list:
    """The (template, kind, raw) of every operation, sorted."""
    model = adapter.normalize(adapter.parse(text, source_label="t.yaml"))
    return sorted(
        (op.http_path, op.extras["path_match"]["kind"], op.extras["path_match"]["raw"])
        for op in model.operations()
    )


# ---------------------------------------------------------------------------------------
# One match-normalization table
# ---------------------------------------------------------------------------------------


def test_every_matcher_maps_onto_a_gateway_api_path_type() -> None:
    assert set(ENVOY_PATH_MATCHERS.values()) <= set(PATH_TYPE_KINDS)
    assert set(ISTIO_URI_MATCHERS.values()) <= set(PATH_TYPE_KINDS)
    # Every Gateway API path type is reachable from both formats.
    assert set(ENVOY_PATH_MATCHERS.values()) == set(PATH_TYPE_KINDS)
    assert set(ISTIO_URI_MATCHERS.values()) == set(PATH_TYPE_KINDS)


@pytest.mark.parametrize(
    ("envoy", "istio", "gateway_api"),
    [
        ("path", "exact", "Exact"),
        ("prefix", "prefix", "PathPrefix"),
        ("safe_regex", "regex", "RegularExpression"),
    ],
)
def test_matchers_name_the_same_gateway_api_type(envoy: str, istio: str, gateway_api: str) -> None:
    assert ENVOY_PATH_MATCHERS[envoy] == gateway_api
    assert ISTIO_URI_MATCHERS[istio] == gateway_api


def test_segment_prefix_is_a_gateway_api_prefix() -> None:
    assert ENVOY_PATH_MATCHERS["path_separated_prefix"] == "PathPrefix"


def test_all_three_formats_normalize_the_same_paths_identically() -> None:
    expected = _path_matches(GatewayApiImportSource(), GATEWAY_API)
    assert _path_matches(EnvoyXdsImportSource(), ENVOY) == expected
    assert _path_matches(IstioImportSource(), ISTIO) == expected
    assert ("/items/{param1}", "regex", "^/items/[0-9]+$") in expected


def test_path_pattern_for_refuses_an_unknown_path_type() -> None:
    with pytest.raises(KeyError):
        path_pattern_for("Glob", "/x")


# ---------------------------------------------------------------------------------------
# Provenance, ledger, routing
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(("adapter", "text"), [(EnvoyXdsImportSource(), ENVOY), (IstioImportSource(), ISTIO)])
def test_mesh_operations_and_services_are_inferred(adapter, text: str) -> None:
    model = adapter.normalize(adapter.parse(text, source_label="t.yaml"))
    assert model.operations()
    assert all(op.extras.get("provenance") == "inferred" for op in model.operations())
    assert all(service.extras.get("provenance") == "inferred" for service in model.services)
    assert all(not op.messages for op in model.operations())


def test_declared_gateway_flavors_stay_unstamped() -> None:
    adapter = GatewayApiImportSource()
    model = adapter.normalize(adapter.parse(GATEWAY_API, source_label="t.yaml"))
    assert all("provenance" not in op.extras for op in model.operations())
    # FMT-7.5 adds the reverse-proxy flavors; the declared gateways (kong, gateway-api) stay out.
    assert INFERRED_ROUTE_FLAVORS == {"envoy-xds", "istio", "traefik", "nginx", "haproxy", "consul", "tyk"}
    assert "gateway-api" not in POLICY_PLUGIN_FLAVORS


@pytest.mark.parametrize(
    ("adapter", "text", "key"),
    [(EnvoyXdsImportSource(), ENVOY, "envoy-xds"), (IstioImportSource(), ISTIO, "istio")],
)
def test_routes_to_the_catalog_as_a_gateway_surface(adapter, text: str, key: str) -> None:
    assert key in GATEWAY_CONFIG_FORMATS
    model = adapter.normalize(adapter.parse(text, source_label="t.yaml"))
    assert model.format == key
    decision = decide_import_routing(adapter, model)
    assert decision.target.value == "catalog"
    assert decision.publishable is False
    assert "no request/response schemas" in decision.reason


@pytest.mark.parametrize(
    ("adapter", "text", "key", "label"),
    [
        (EnvoyXdsImportSource(), ENVOY, "envoy-xds", "Envoy xDS route configuration"),
        (IstioImportSource(), ISTIO, "istio", "Istio VirtualService manifests"),
    ],
)
def test_ledger_states_inferred_operations_and_the_schema_limit(adapter, text: str, key: str, label: str) -> None:
    model = adapter.normalize(adapter.parse(text, source_label="t.yaml"))
    page = paginate_import_preview_manifest(build_import_preview_manifest(model, adapter_key=key, options={}))
    rows = {row.source_construct: row for row in page.coverage}
    schema_row = rows["gateway#request-response-schemas"]
    assert schema_row.coverage is CoverageClass.INFERRED
    assert label in schema_row.detail
    assert "not a drop" in schema_row.detail
    operation_rows = [
        row
        for row in page.coverage
        if row.source_construct.split(" ", 1)[0] in ("ANY", "GET", "POST") and "/" in row.source_construct
    ]
    assert operation_rows and all(row.coverage is CoverageClass.INFERRED for row in operation_rows)
    assert key in KNOWN_PARSER_LIMITS
    assert any(row.coverage is CoverageClass.NOT_PARSED_BY_ADAPTER for row in page.coverage)


def test_registry_holds_both_adapters() -> None:
    load_builtin_import_sources()
    assert isinstance(get_import_source("envoy-xds"), EnvoyXdsImportSource)
    assert isinstance(get_import_source("istio"), IstioImportSource)


# ---------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------


def test_limit_collector_counts_and_sorts() -> None:
    limits = LimitCollector()
    limits.add("tcp", "not HTTP", count=2)
    limits.add("delegate", "handed off")
    limits.add("tcp", "a different reason is ignored")
    assert limits.as_ignored() == (
        {"construct": "delegate", "count": 1, "reason": "handed off"},
        {"construct": "tcp", "count": 3, "reason": "not HTTP"},
    )


@pytest.mark.parametrize(
    ("spec", "rendered"),
    [
        ({"exact": "GET"}, "GET"),
        ({"prefix": "acme-"}, "prefix:acme-"),
        ({"regex": "^x$"}, "regex:^x$"),
        ({"safe_regex": {"google_re2": {}, "regex": "^[0-9]+$"}}, "regex:^[0-9]+$"),
        ({"exact": "true"}, "true"),
        ({"unknown": 1}, None),
        ("not-a-mapping", None),
    ],
)
def test_render_string_match(spec, rendered) -> None:
    assert render_string_match(spec) == rendered


@pytest.mark.parametrize(
    ("value", "ok"),
    [("15s", True), ("0.25s", True), ("10m", True), ("15", False), ("abc", False)],
)
def test_is_duration(value: str, ok: bool) -> None:
    assert is_duration(value) is ok


@pytest.mark.parametrize(
    ("host", "truncated"),
    [
        ("orders.storefront.svc.cluster", True),
        ("orders.storefront.svc.cluster.lo", True),
        ("orders.storefront.svc.c", True),
        ("orders.storefront.svc.cluster.local", False),
        ("orders.storefront.svc", False),
        ("api.example.com", False),
    ],
)
def test_is_truncated_cluster_host(host: str, truncated: bool) -> None:
    assert is_truncated_cluster_host(host) is truncated


def test_only_the_final_scalar_is_judged() -> None:
    rules = {"timeout": lambda value: not is_duration(value)}
    # Mid-file the same fault is not a truncation…
    raise_if_truncated_tail("timeout: 15\nname: x\n", format_label="T", rules=rules)
    # …a trailing comment or blank line does not hide the final scalar…
    with pytest.raises(GatewayConfigParseError) as exc_info:
        raise_if_truncated_tail("name: x\n  timeout: 15\n\n# end\n", format_label="T", rules=rules)
    assert exc_info.value.code == "INPUT_TRUNCATED"
    # …and a quoted value is a closed scalar, never a cut.
    raise_if_truncated_tail('timeout: "15"\n', format_label="T", rules=rules)
    raise_if_truncated_tail("timeout: 15s\n", format_label="T", rules=rules)
