"""Unit tests for the bounded nginx configuration ImportSource (FMT-7.5 / #5459)."""

from __future__ import annotations

import pytest

from app.fileset import IntakeFileset
from app.format_capability_registry import CapabilityProvenance, capability_for
from app.gateway_config_model import GatewayConfigParseError
from app.import_source import DetectionInput, ImportSourceError, load_builtin_import_sources
from app.nginx_import_source import NginxImportSource
from app.nginx_parser import (
    NGINX_CARRIED_DIRECTIVES,
    NGINX_DECLARED_DIRECTIVES,
    NGINX_READ_DIRECTIVES,
    tokenize_nginx,
)

load_builtin_import_sources()


@pytest.fixture
def adapter() -> NginxImportSource:
    return NginxImportSource()


CONFIG = """\
upstream orders_backend {
    server orders-1.internal:8080;
    server orders-2.internal:8080;
}

proxy_read_timeout 30s;

server {
    listen 443 ssl;
    server_name api.example.com *.api.example.com;
    proxy_set_header Authorization "Bearer s3cr3t";

    location = /healthz {
        return 200 'ok';
    }

    location ^~ /v2/orders {
        proxy_pass http://orders_backend;
        proxy_read_timeout 5s;
        limit_except GET POST { deny all; }
    }

    location ~* ^/assays/(?<assay_id>[a-f0-9]{8})$ {
        proxy_pass http://orders_backend;
    }

    location @fallback {
        proxy_pass http://orders_backend;
    }

    location /exp {
        if ($http_x_beta) { return 403; }
        proxy_pass http://orders_backend;
    }
}

server {
    listen 80;
    server_name api.example.com;
    return 301 https://$host$request_uri;
}
"""


def _ops(adapter: NginxImportSource, text: str):
    model = adapter.normalize(adapter.parse(text, source_label="nginx.conf"))
    return model, {op.key: op for op in model.operations()}


def _ignored(model) -> set:
    return {entry["construct"] for entry in model.extras["gateway"]["ignored_constructs"]}


# ---------------------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------------------


def test_tokenizer_keeps_regex_quantifiers_inside_a_word() -> None:
    tokens = tokenize_nginx("location ~ ^/o/[0-9]{6}$ { return 200; }", origin="t")
    assert ("word", "^/o/[0-9]{6}$", 1) in tokens
    assert [kind for kind, _v, _l in tokens].count("{") == 1


def test_tokenizer_strips_quotes_and_comments() -> None:
    tokens = tokenize_nginx("add_header X 'a b'; # comment\n", origin="t")
    assert [value for _k, value, _l in tokens] == ["add_header", "X", "a b", ";"]


# ---------------------------------------------------------------------------------------
# Locations → operations
# ---------------------------------------------------------------------------------------


def test_location_modifiers_map_to_path_kinds(adapter: NginxImportSource) -> None:
    _model, ops = _ops(adapter, CONFIG)
    assert ops["ANY /healthz"].extras["path_match"]["kind"] == "exact"
    assert ops["GET /v2/orders"].extras["path_match"]["kind"] == "prefix"
    assert ops["GET /v2/orders"].extras["stops_regex_evaluation"] is True
    regex = ops["ANY /assays/{assay_id}"]
    assert regex.extras["path_match"]["kind"] == "regex"
    assert regex.extras["case_insensitive"] is True
    assert [param.name for param in regex.parameters] == ["assay_id"]


def test_limit_except_with_deny_all_pins_the_methods(adapter: NginxImportSource) -> None:
    _model, ops = _ops(adapter, CONFIG)
    assert {"GET /v2/orders", "HEAD /v2/orders", "POST /v2/orders"} <= set(ops)


def test_carried_directives_follow_nginx_inheritance(adapter: NginxImportSource) -> None:
    model, ops = _ops(adapter, CONFIG)
    orders = ops["GET /v2/orders"]
    assert {"proxy_read_timeout", "proxy_set_header"} <= set(orders.extras["plugins"])
    assert model.extras["gateway"]["credential_redactions"] >= 1
    assert "s3cr3t" not in str(model.model_dump())


def test_hosts_scheme_and_upstream(adapter: NginxImportSource) -> None:
    model, ops = _ops(adapter, CONFIG)
    assert ops["GET /v2/orders"].extras["hosts"] == ["*.api.example.com", "api.example.com"]
    assert ops["GET /v2/orders"].extras["backends"] == [{"name": "orders_backend"}]
    assert "https://api.example.com" in [server.url for server in model.servers]
    assert all(op.extras["provenance"] == "inferred" for op in model.operations())


def test_server_level_return_is_a_route(adapter: NginxImportSource) -> None:
    _model, ops = _ops(adapter, CONFIG)
    redirect = next(op for op in ops.values() if op.extras.get("server_level_return"))
    assert redirect.extras["handler"]["status"] == "301"


def test_constructs_outside_the_subset_are_declared(adapter: NginxImportSource) -> None:
    model, ops = _ops(adapter, CONFIG)
    assert {"location.named", "if"} <= _ignored(model)
    assert not any("fallback" in key for key in ops)


def test_unknown_directive_is_declared_by_name(adapter: NginxImportSource) -> None:
    model, _ops_ = _ops(adapter, "server {\n listen 80;\n gzip on;\n location / { return 200; }\n}\n")
    assert "directive.gzip" in _ignored(model)


def test_variable_proxy_pass_is_declared_not_resolved(adapter: NginxImportSource) -> None:
    text = "server {\n listen 80;\n location / { proxy_pass http://$backend; }\n}\n"
    model, ops = _ops(adapter, text)
    assert "proxy_pass.variable" in _ignored(model)
    assert ops["ANY /"].extras["handler"]["target"] == "http://$backend"


# ---------------------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("server {\n listen 80;\n location / {\n  return 200;\n}\n", "INPUT_MALFORMED"),
        ("server {\n listen 80;\n location / {\n  proxy_pass http://up", "INPUT_TRUNCATED"),
        ("server {\n listen 80;\n add_header X 'open", "INPUT_TRUNCATED"),
        ("events { worker_connections 10; }\nhttp { sendfile on; }\n", "INPUT_SEMANTIC_INVALID"),
        ("server {\n listen 80;\n location / { proxy_pass http://missing_up; }\n}\n", "INPUT_REFERENCE_UNRESOLVED"),
        ("frontend public\n    bind :80\n", "FORMAT_MISMATCH"),
        ("server {\n listen 80;\n}\n}\n", "INPUT_MALFORMED"),
    ],
)
def test_error_codes(adapter: NginxImportSource, text: str, code: str) -> None:
    with pytest.raises(ImportSourceError) as exc:
        adapter.parse(text)
    assert exc.value.code == code


def test_unresolved_include_suppresses_the_upstream_check(adapter: NginxImportSource) -> None:
    text = "include upstreams.conf;\nserver {\n listen 80;\n location / { proxy_pass http://up; }\n}\n"
    model, _ops_ = _ops(adapter, text)
    assert "include.unresolved" in _ignored(model)


# ---------------------------------------------------------------------------------------
# Configuration trees
# ---------------------------------------------------------------------------------------


def test_includes_are_followed_across_the_fileset(adapter: NginxImportSource) -> None:
    fileset = IntakeFileset.from_members(
        {
            "nginx.conf": "http {\n include upstreams.conf;\n include sites/*.conf;\n}\n",
            "upstreams.conf": "upstream up { server u:80; }\n",
            "api.conf": "server {\n listen 80;\n location /a { proxy_pass http://up; }\n}\n",
        },
        root="nginx.conf",
    )
    model = adapter.normalize(adapter.parse_fileset(fileset))
    assert [op.key for op in model.operations()] == ["ANY /a"]
    assert model.raw["gateway_config"]["files_read"] == ["api.conf", "nginx.conf", "upstreams.conf"]


def test_include_cycle_is_read_once(adapter: NginxImportSource) -> None:
    fileset = IntakeFileset.from_members(
        {
            "a.conf": "include b.conf;\nserver {\n listen 80;\n location /a { return 200; }\n}\n",
            "b.conf": "include a.conf;\n",
        },
        root="a.conf",
    )
    model = adapter.normalize(adapter.parse_fileset(fileset))
    assert [op.key for op in model.operations()] == ["ANY /a"]


# ---------------------------------------------------------------------------------------
# Capability registry: the subset is documented directive by directive
# ---------------------------------------------------------------------------------------


def test_registry_documents_every_subset_directive() -> None:
    entry = capability_for("nginx")
    assert entry.provenance is CapabilityProvenance.REVIEWED
    for name in NGINX_READ_DIRECTIVES:
        assert f"nginx.directive.{name}" in entry.supported_constructs
    for name in NGINX_CARRIED_DIRECTIVES:
        assert f"nginx.directive.{name}" in entry.supported_constructs
    for name in NGINX_DECLARED_DIRECTIVES:
        assert f"nginx.{name}" in entry.unsupported_constructs
        assert f"nginx.{name}" in entry.canonical_projection.dropped_constructs
    notes = " ".join(entry.notes)
    for name in (*NGINX_READ_DIRECTIVES, *NGINX_CARRIED_DIRECTIVES, *NGINX_DECLARED_DIRECTIVES):
        assert f"`{name}`" in notes, name


def test_registry_never_claims_schema_fidelity() -> None:
    for key in ("nginx", "traefik", "haproxy", "consul", "tyk"):
        entry = capability_for(key)
        assert entry.canonical_projection.coverage.value == "partial", key
        assert "inferred" in entry.canonical_projection.note, key


def test_parse_errors_are_gateway_parse_errors() -> None:
    from app.nginx_parser import parse_nginx

    with pytest.raises(GatewayConfigParseError):
        parse_nginx("server {")


def test_detection(adapter: NginxImportSource) -> None:
    assert adapter.detect(DetectionInput(text=CONFIG)).confidence >= 0.9
    assert not adapter.detect(DetectionInput(text='service {\n  name = "x"\n}\n')).matched
