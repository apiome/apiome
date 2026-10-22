"""The shared gateway middle across the whole family — FMT-7.6 (#5460).

Three properties, each checked over every family member rather than per adapter:

* **One match-normalization table.** Every front end's own matcher table maps onto the
  Gateway API path types of :data:`app.gateway_match.PATH_TYPE_KINDS`, no front-end module
  builds a pattern or renders a value operator any other way, and the *same* route written
  in each of the nine formats normalizes to the same path match.
* **One provenance classification.** :func:`app.gateway_family.provenance_stamp` decides
  every stamp, and a document normalizes with the same stamps whatever flavor carries it,
  differing only by the flavor's declared route provenance.
* **A front end is a declaration plus a route-extraction function.** A throwaway flavor
  registered here gets a normalizer, the ledger label, the routing reason and the
  provenance without any other code.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator

import pytest

from app import normalizer as normalizer_registry
from app.consul_import_source import ConsulImportSource
from app.consul_parser import _PATH_KEYS as CONSUL_PATH_KEYS
from app.envoy_xds_import_source import EnvoyXdsImportSource
from app.envoy_xds_parser import ENVOY_PATH_MATCHERS
from app.gateway_api_import_source import GatewayApiImportSource
from app.gateway_api_parser import PATH_KIND_TYPES as GATEWAY_API_KIND_TYPES
from app.gateway_api_parser import PATH_TYPE_KINDS as GATEWAY_API_TYPE_KINDS
from app.gateway_config_model import (
    GatewayAuthHint,
    GatewayConfigDocument,
    GatewayMatch,
    GatewayRoute,
)
from app.gateway_config_normalizer import (
    INFERRED_ROUTE_FLAVORS,
    POLICY_PLUGIN_FLAVORS,
    gateway_report,
    normalize_gateway_config,
    register_gateway_flavor,
)
from app.gateway_family import (
    DECLARED,
    GATEWAY_FAMILY,
    INFERRED,
    GatewayFlavor,
    add_flavor,
    flavor_for,
    gateway_config_formats,
    provenance_stamp,
)
from app.gateway_match import PATH_KIND_TYPES, PATH_TYPE_KINDS, path_pattern, render_match_value
from app.haproxy_import_source import HaproxyImportSource
from app.haproxy_parser import HAPROXY_PATH_FETCHES
from app.import_preview_manifest import _gateway_capability_rows
from app.import_routing import GATEWAY_CONFIG_FORMATS, decide_import_routing
from app.import_source import NO_MATCH, ImportSource, ImportSourceError
from app.istio_import_source import IstioImportSource
from app.istio_parser import ISTIO_URI_MATCHERS
from app.kong_import_source import KongImportSource
from app.nginx_import_source import NginxImportSource
from app.nginx_parser import NGINX_LOCATION_MODIFIERS
from app.proxy_import_source import ProxyRouteImportSource
from app.traefik_import_source import TraefikImportSource
from app.traefik_parser import TRAEFIK_PATH_MATCHERS
from app.tyk_import_source import TykImportSource

_APP = Path(__file__).resolve().parents[1] / "src" / "app"

#: The route-extraction modules of every front end.
_FRONT_ENDS = (
    "kong_parser.py",
    "gateway_api_parser.py",
    "envoy_xds_parser.py",
    "istio_parser.py",
    "traefik_parser.py",
    "nginx_parser.py",
    "haproxy_parser.py",
    "consul_parser.py",
    "tyk_parser.py",
    "mesh_route_common.py",
    "proxy_route_common.py",
)


# ---------------------------------------------------------------------------------------
# One match-normalization table
# ---------------------------------------------------------------------------------------


def test_the_gateway_api_tables_are_the_shared_ones() -> None:
    assert GATEWAY_API_TYPE_KINDS is PATH_TYPE_KINDS
    assert GATEWAY_API_KIND_TYPES is PATH_KIND_TYPES
    assert {PATH_TYPE_KINDS[path_type] for path_type in PATH_TYPE_KINDS} == set(PATH_KIND_TYPES)


@pytest.mark.parametrize(
    "table",
    [
        ENVOY_PATH_MATCHERS,
        ISTIO_URI_MATCHERS,
        TRAEFIK_PATH_MATCHERS,
        {key: value for key, value in NGINX_LOCATION_MODIFIERS.items() if value is not None},
        HAPROXY_PATH_FETCHES,
        CONSUL_PATH_KEYS,
    ],
    ids=["envoy-xds", "istio", "traefik", "nginx", "haproxy", "consul"],
)
def test_every_front_end_table_maps_onto_the_shared_path_types(table) -> None:
    assert set(table.values()) <= set(PATH_TYPE_KINDS)


@pytest.mark.parametrize("module", _FRONT_ENDS)
def test_no_front_end_builds_a_pattern_or_renders_an_operator_itself(module: str) -> None:
    source = (_APP / module).read_text(encoding="utf-8")
    assert "build_path_pattern(" not in source, f"{module} must build paths with gateway_match.path_pattern"
    assert not re.search(
        r"""f["'](?:prefix|suffix|contains|regex|\{operator\}):""", source
    ), f"{module} renders a match operator itself instead of gateway_match.render_match_value"
    assert not re.search(r"""\{\s*["']Exact["']\s*:\s*["']exact["']""", source), f"{module} spells its own kind table"


def test_render_match_value_is_one_rule() -> None:
    assert render_match_value("exact", "GET") == "GET"
    assert render_match_value("prefix", "acme-") == "prefix:acme-"
    assert render_match_value("regex", "") == ""  # presence-only, whatever the operator
    with pytest.raises(KeyError):
        render_match_value("glob", "*")


def test_path_pattern_refuses_an_unknown_path_type_and_templates_on_request() -> None:
    with pytest.raises(KeyError):
        path_pattern("Glob", "/x")
    assert path_pattern("Exact", "/o/{id}").param_names == ()
    assert path_pattern("Exact", "/o/{id}", templated=True).param_names == ("id",)
    assert path_pattern("RegularExpression", r"^/o/(?P<id>\d+)$", templated=True).template == "/o/{id}"


#: The same route — prefix ``/orders``, ``GET``, header ``x-tenant`` starting ``acme-`` —
#: in every format that can say all three things.
_SAME_ROUTE = [
    (
        KongImportSource(),
        "_format_version: '3.0'\nservices:\n  - name: s\n    url: http://s\n    routes:\n"
        "      - name: r\n        paths: [/orders]\n        methods: [GET]\n",
        False,
    ),
    (
        GatewayApiImportSource(),
        "apiVersion: gateway.networking.k8s.io/v1\nkind: HTTPRoute\nmetadata: {name: r}\nspec:\n  rules:\n"
        "    - matches:\n        - path: {type: PathPrefix, value: /orders}\n          method: GET\n"
        "          headers: [{type: RegularExpression, name: x-tenant, value: '^acme-'}]\n",
        False,
    ),
    (
        EnvoyXdsImportSource(),
        "name: rc\nvirtual_hosts:\n  - name: vh\n    domains: ['*']\n    routes:\n"
        "      - match:\n          prefix: /orders\n          headers:\n"
        "            - {name: ':method', string_match: {exact: GET}}\n"
        "            - {name: x-tenant, string_match: {prefix: acme-}}\n"
        "        route: {cluster: c}\n",
        True,
    ),
    (
        IstioImportSource(),
        "apiVersion: networking.istio.io/v1\nkind: VirtualService\nmetadata: {name: r}\nspec:\n  hosts: [a]\n"
        "  http:\n    - match:\n        - uri: {prefix: /orders}\n          method: {exact: GET}\n"
        "          headers: {x-tenant: {prefix: acme-}}\n      route: [{destination: {host: s}}]\n",
        True,
    ),
    (
        TraefikImportSource(),
        "http:\n  routers:\n    r:\n      rule: PathPrefix(`/orders`) && Method(`GET`) && "
        "HeaderRegexp(`x-tenant`, `^acme-`)\n      service: noop@internal\n",
        False,
    ),
    (
        HaproxyImportSource(),
        "defaults\n    mode http\nfrontend f\n    bind :80\n    acl p path_beg /orders\n    acl m method GET\n"
        "    acl h req.hdr(x-tenant) -m beg acme-\n    use_backend b if p m h\nbackend b\n    server s s:80\n",
        True,
    ),
    (
        ConsulImportSource(),
        json.dumps(
            {
                "Kind": "service-router",
                "Name": "s",
                "Routes": [
                    {
                        "Match": {
                            "HTTP": {
                                "PathPrefix": "/orders",
                                "Methods": ["GET"],
                                "Header": [{"Name": "x-tenant", "Prefix": "acme-"}],
                            }
                        }
                    }
                ],
            }
        ),
        True,
    ),
]


@pytest.mark.parametrize(
    ("adapter", "text", "checks_header_operator"),
    _SAME_ROUTE,
    ids=[adapter.key for adapter, _text, _flag in _SAME_ROUTE],
)
def test_the_same_route_normalizes_the_same_way_in_every_format(adapter, text: str, checks_header_operator) -> None:
    model = adapter.normalize(adapter.parse(text, source_label="same-route"))
    operation = next(op for op in model.operations() if op.http_path == "/orders")
    assert operation.http_method == "GET"
    assert operation.extras["path_match"] == {"kind": "prefix", "raw": "/orders"}
    header = next((param for param in operation.parameters if param.name == "x-tenant"), None)
    if checks_header_operator:
        assert header is not None and header.extras["match_value"] == "prefix:acme-"


@pytest.mark.parametrize(
    ("adapter", "text"),
    [
        (NginxImportSource(), "server {\n listen 80;\n location /orders { return 200; }\n}\n"),
        (TykImportSource(), '{"api_id": "a", "use_keyless": true, "proxy": {"listen_path": "/orders/"}}'),
    ],
    ids=["nginx", "tyk"],
)
def test_prefix_only_formats_agree_too(adapter, text: str) -> None:
    model = adapter.normalize(adapter.parse(text, source_label="same-route"))
    assert next(iter(model.operations())).extras["path_match"]["kind"] == "prefix"


# ---------------------------------------------------------------------------------------
# One provenance classification
# ---------------------------------------------------------------------------------------


def _document(flavor: str) -> GatewayConfigDocument:
    """A two-route document: a regex path and a literal one, with an inferred auth scheme."""
    hint = GatewayAuthHint(scheme="apiKey", plugin="key", scope="route", attached_to="r1")
    return GatewayConfigDocument(
        flavor=flavor,
        title="t",
        routes=(
            GatewayRoute(
                name="r1",
                service_name="svc",
                hosts=("api.example.com",),
                matches=(GatewayMatch(path=path_pattern("RegularExpression", r"^/o/\d+$"), method="GET"),),
                auth=(hint,),
            ),
            GatewayRoute(name="r2", service_name="svc", matches=(GatewayMatch(path=path_pattern("Exact", "/h")),)),
        ),
    )


@pytest.mark.parametrize("flavor", list(GATEWAY_FAMILY))
def test_provenance_is_classified_identically_across_the_family(flavor: str) -> None:
    model = normalize_gateway_config(_document(flavor), format_key=flavor)
    inferred = GATEWAY_FAMILY[flavor].route_provenance == INFERRED
    for operation in model.operations():
        assert ("provenance" in operation.extras) is inferred, operation.key
        for parameter in operation.parameters:
            assert parameter.extras["provenance"] == "inferred"  # recovered from a regex: always
    assert ("provenance" in model.services[0].extras) is inferred
    assert model.extras["inferred_auth_schemes"] == ["apiKey"]


@pytest.mark.parametrize("flavor", list(GATEWAY_FAMILY))
def test_every_flavor_states_the_schemaless_limit_the_same_way(flavor: str) -> None:
    model = normalize_gateway_config(_document(flavor), format_key=flavor)
    report = model.extras["gateway"]
    assert report["schemaless_operation_count"] == 2
    expected = {
        "flavor",
        "route_count",
        "operation_count",
        "schemaless_operation_count",
        "credential_redactions",
        "ignored_constructs",
        "auth",
        "unmapped_plugins",
        "global_plugins",
    } | ({"unmodeled_plugins"} if GATEWAY_FAMILY[flavor].policy_plugins else set())
    assert set(report) == expected
    rows = _gateway_capability_rows(model)
    schemaless = next(row for row in rows if row.source_construct == "gateway#request-response-schemas")
    assert schemaless.detail.startswith(GATEWAY_FAMILY[flavor].label)


def test_the_derived_sets_match_the_declarations() -> None:
    assert INFERRED_ROUTE_FLAVORS == {
        key for key, flavor in GATEWAY_FAMILY.items() if flavor.route_provenance == INFERRED
    }
    assert POLICY_PLUGIN_FLAVORS == {key for key, flavor in GATEWAY_FAMILY.items() if flavor.policy_plugins}
    assert {"kong", "gateway-api"} == {
        key for key, flavor in GATEWAY_FAMILY.items() if flavor.route_provenance == DECLARED
    }
    assert GATEWAY_CONFIG_FORMATS == gateway_config_formats()
    assert flavor_for("kong-declarative") is GATEWAY_FAMILY["kong"]
    assert flavor_for("httproute") is GATEWAY_FAMILY["gateway-api"]


def test_provenance_stamp_rules() -> None:
    assert provenance_stamp("kong") == {}
    assert provenance_stamp("kong", derived=True) == {"provenance": "inferred"}
    assert provenance_stamp("traefik") == {"provenance": "inferred"}
    with pytest.raises(KeyError):
        provenance_stamp("openapi-3.1")


def test_tyk_oas_uses_the_shared_report_builder() -> None:
    hint = GatewayAuthHint(scheme=None, plugin="hmac", scope="global")
    report = gateway_report(
        flavor="tyk",
        route_count=1,
        operation_count=1,
        schemaless_operation_count=0,
        credential_redactions=0,
        ignored=(),
        auth_hints=[hint, hint],
        global_plugins=["cors", "cors"],
        policy_plugins=[("cors", "global"), ("cors", "global")],
    )
    assert report["unmapped_plugins"] == [{"name": "hmac", "scope": "global"}]
    assert report["global_plugins"] == ["cors"]
    assert report["unmodeled_plugins"] == [{"name": "cors", "scope": "global"}]


def test_add_flavor_refuses_a_conflicting_or_invalid_declaration() -> None:
    with pytest.raises(ValueError):
        add_flavor(GatewayFlavor("kong", "Something else", DECLARED, True))
    with pytest.raises(ValueError):
        add_flavor(GatewayFlavor("fmt76-bad", "Bad", "maybe", True))


# ---------------------------------------------------------------------------------------
# A new front end is a declaration plus a route-extraction function
# ---------------------------------------------------------------------------------------

_TOY = GatewayFlavor("fmt76-toy", "Toy route table", INFERRED, True, (), "tests.test_gateway_family.extract_routes")


def extract_routes(text: str, *, source_label=None) -> GatewayConfigDocument:
    """The only front-end code a toy gateway needs: ``METHOD PATH`` lines → routes."""
    routes = []
    for index, line in enumerate(line for line in text.splitlines() if line.strip()):
        method, path = line.split()
        routes.append(
            GatewayRoute(
                name=f"line-{index}",
                service_name="toy",
                matches=(GatewayMatch(path=path_pattern("PathPrefix", path), method=method),),
            )
        )
    return GatewayConfigDocument(flavor=_TOY.key, title="toy", routes=tuple(routes), source_label=source_label)


@pytest.fixture
def toy_front_end() -> Iterator[ImportSource]:
    register_gateway_flavor(_TOY)

    class ToyImportSource(ProxyRouteImportSource):  # not registered: the test owns it
        key = _TOY.key
        label = _TOY.label
        description = "A throwaway gateway front end."
        icon = "route"
        formats = (_TOY.key,)
        file_extensions = (".toy",)

        def detect(self, payload):  # pragma: no cover - not exercised
            return NO_MATCH

        def _parse_text(self, raw, *, source_label):
            return extract_routes(raw, source_label=source_label)

    yield ToyImportSource()
    GATEWAY_FAMILY.pop(_TOY.key, None)
    normalizer_registry._REGISTRY.pop(_TOY.key, None)


def test_a_route_extraction_function_is_a_whole_front_end(toy_front_end: ImportSource) -> None:
    model = toy_front_end.normalize(toy_front_end.parse("GET /orders\nPOST /orders\n", source_label="t.toy"))
    assert [op.key for op in model.operations()] == ["GET /orders", "POST /orders"]
    assert all(op.extras["provenance"] == "inferred" and not op.messages for op in model.operations())
    decision = decide_import_routing(toy_front_end, model)
    assert decision.publishable is False and "no request/response schemas" in decision.reason
    rows = _gateway_capability_rows(model)
    assert any(row.detail.startswith("Toy route table") for row in rows)


def test_a_document_of_another_flavor_is_refused(toy_front_end: ImportSource) -> None:
    with pytest.raises((ValueError, ImportSourceError)):
        normalizer_registry.get_normalizer(_TOY.key)().normalize(_document("kong"))
