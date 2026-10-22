"""Unit tests for the shared reverse-proxy route seams (FMT-7.5 / #5459)."""

from __future__ import annotations

import pytest

from app.consul_import_source import ConsulImportSource
from app.gateway_config_model import GatewayConfigParseError
from app.gateway_config_normalizer import INFERRED_ROUTE_FLAVORS, POLICY_PLUGIN_FLAVORS, PROXY_ROUTE_FLAVORS
from app.haproxy_import_source import HaproxyImportSource
from app.import_preview_manifest import KNOWN_PARSER_LIMITS, _gateway_capability_rows
from app.import_routing import GATEWAY_CONFIG_FORMATS, decide_import_routing
from app.intake_scrub_policy import ALWAYS_ENFORCED_FORMATS
from app.nginx_import_source import NginxImportSource
from app.proxy_route_common import load_json_document, ordered_members, split_address, template_pattern
from app.traefik_import_source import TraefikImportSource
from app.tyk_import_source import TykImportSource

_SAMPLES = [
    (TraefikImportSource(), "http:\n  routers:\n    a: {rule: Path(`/a`), service: noop@internal}\n"),
    (NginxImportSource(), "server {\n listen 80;\n location /a { return 200; }\n}\n"),
    (
        HaproxyImportSource(),
        "defaults\n    mode http\nfrontend f\n    bind :80\n    default_backend b\nbackend b\n    server s b:80\n",
    ),
    (ConsulImportSource(), '{"service": {"name": "a", "port": 80}}'),
    (TykImportSource(), '{"api_id": "a", "use_keyless": true, "proxy": {"listen_path": "/a/"}}'),
]


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ('{"a": 1,}', "INPUT_MALFORMED"),
        ('{"a": 1 "b": 2}', "INPUT_MALFORMED"),
        ('{"a": [1, 2', "INPUT_TRUNCATED"),
        ('{"a": "cut', "INPUT_TRUNCATED"),
        ("   ", "INPUT_MALFORMED"),
    ],
)
def test_json_truncation_is_judged_by_open_containers(text: str, code: str) -> None:
    with pytest.raises(GatewayConfigParseError) as exc:
        load_json_document(text, format_label="T")
    assert exc.value.code == code


def test_braces_inside_strings_do_not_count() -> None:
    with pytest.raises(GatewayConfigParseError) as exc:
        load_json_document('{"a": "{[", }', format_label="T")
    assert exc.value.code == "INPUT_MALFORMED"


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("http://orders.internal:8080/v2", ("orders.internal", "http", 8080)),
        ("orders:80", ("orders", None, 80)),
        ("[::1]:443", ("::1", None, 443)),
        ("Orders.Internal", ("orders.internal", None, None)),
    ],
)
def test_split_address(address: str, expected: tuple) -> None:
    assert split_address(address) == expected


def test_template_pattern_keeps_parameter_names_once() -> None:
    pattern = template_pattern("v2/{id}/items/{id}", "prefix")
    assert pattern.template == "/v2/{id}/items/{id}"
    assert pattern.param_names == ("id",)
    assert pattern.kind == "prefix"


def test_ordered_members_reads_the_root_first() -> None:
    assert ordered_members({"b": "", "a": "", "root": ""}, "root") == ["root", "a", "b"]
    assert ordered_members({"b": "", "a": ""}, None) == ["a", "b"]


def test_proxy_flavors_are_inferred_policy_flavors() -> None:
    assert PROXY_ROUTE_FLAVORS == {"traefik", "nginx", "haproxy", "consul", "tyk"}
    assert PROXY_ROUTE_FLAVORS <= INFERRED_ROUTE_FLAVORS
    assert PROXY_ROUTE_FLAVORS <= POLICY_PLUGIN_FLAVORS
    assert PROXY_ROUTE_FLAVORS <= GATEWAY_CONFIG_FORMATS
    assert PROXY_ROUTE_FLAVORS <= set(KNOWN_PARSER_LIMITS)


@pytest.mark.parametrize(("adapter", "text"), _SAMPLES, ids=[adapter.key for adapter, _text in _SAMPLES])
def test_every_proxy_source_is_an_inferred_schemaless_catalog_item(adapter, text: str) -> None:
    model = adapter.normalize(adapter.parse(text, source_label="sample"))
    assert model.format == adapter.key
    assert all(op.extras["provenance"] == "inferred" and not op.messages for op in model.operations())
    decision = decide_import_routing(adapter, model)
    assert decision.target.value == "catalog" and decision.publishable is False
    assert "no request/response schemas" in decision.reason
    rows = _gateway_capability_rows(model)
    assert any(row.source_construct == "gateway#request-response-schemas" for row in rows)


def test_credential_carrying_proxy_formats_are_always_scrubbed() -> None:
    assert {"traefik", "tyk"} <= ALWAYS_ENFORCED_FORMATS
