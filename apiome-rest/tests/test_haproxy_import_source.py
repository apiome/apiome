"""Unit tests for the HAProxy configuration ImportSource (FMT-7.5 / #5459)."""

from __future__ import annotations

import pytest

from app.fileset import IntakeFileset
from app.haproxy_import_source import HaproxyImportSource
from app.import_source import DetectionInput, ImportSourceError


@pytest.fixture
def adapter() -> HaproxyImportSource:
    return HaproxyImportSource()


CONFIG = """\
global
    maxconn 1000

defaults
    mode http
    timeout client 30s

frontend api
    bind :80
    bind :443 ssl crt /etc/cert.pem
    acl is_orders  path_beg /v2/orders /v2/order-lines
    acl is_reads   method GET HEAD
    acl host_api   hdr(host) -i api.example.com
    acl is_health  path /healthz
    acl tenant     req.hdr(x-tenant) -m beg acme-
    acl office     src 10.0.0.0/8
    acl lua_check  lua.allowed
    http-request return status 200 string ok if is_health
    http-request deny if !office is_orders
    use_backend orders if host_api is_orders is_reads
    use_backend tenants if tenant || { path_reg ^/t/[0-9]+$ }
    use_backend scripted if lua_check
    default_backend legacy

backend orders
    balance roundrobin
    server o1 orders-1.internal:8080 check

backend tenants
    server t1 tenants.internal:8080 check

backend scripted
    server s1 scripted.internal:8080 check

backend legacy
    server l1 legacy.internal:80 check
"""


def _ops(adapter: HaproxyImportSource, text: str):
    model = adapter.normalize(adapter.parse(text, source_label="haproxy.cfg"))
    return model, {op.key: op for op in model.operations()}


def _ignored(model) -> set:
    return {entry["construct"] for entry in model.extras["gateway"]["ignored_constructs"]}


def test_detection(adapter: HaproxyImportSource) -> None:
    assert adapter.detect(DetectionInput(text=CONFIG)).confidence >= 0.9
    assert not adapter.detect(DetectionInput(text="http:\n  routers: {}\n")).matched


def test_acl_conjunction_becomes_operations(adapter: HaproxyImportSource) -> None:
    _model, ops = _ops(adapter, CONFIG)
    for key in ("GET /v2/orders", "HEAD /v2/orders", "GET /v2/order-lines", "HEAD /v2/order-lines"):
        assert key in ops, key
        assert ops[key].extras["hosts"] == ["api.example.com"]
        assert ops[key].extras["backends"] == [{"name": "orders", "port": 8080}]
        assert ops[key].extras["provenance"] == "inferred"


def test_or_and_anonymous_acls(adapter: HaproxyImportSource) -> None:
    _model, ops = _ops(adapter, CONFIG)
    header_route = next(op for op in ops.values() if any(p.name == "x-tenant" for p in op.parameters))
    assert header_route.parameters[0].extras["match_value"] == "prefix:acme-"
    assert "ANY /t/{param1}" in ops


def test_inline_return_and_default_are_routes(adapter: HaproxyImportSource) -> None:
    _model, ops = _ops(adapter, CONFIG)
    assert ops["ANY /healthz"].extras["handler"]["directive"] == "http-request return"
    assert any(op.extras.get("default_route") for op in ops.values())


def test_runtime_conditions_are_declared(adapter: HaproxyImportSource) -> None:
    model, ops = _ops(adapter, CONFIG)
    assert {"acl.lua", "global"} <= _ignored(model)
    scripted = next(op for op in ops.values() if op.extras.get("backends") == [{"name": "scripted", "port": 8080}])
    assert scripted.extras["unmodelled_conditions"] == ["lua_check"]


def test_policy_directives_are_carried(adapter: HaproxyImportSource) -> None:
    _model, ops = _ops(adapter, CONFIG)
    assert "http-request deny" in ops["GET /v2/orders"].extras["plugins"]


def test_tcp_mode_imports_with_no_operation(adapter: HaproxyImportSource) -> None:
    text = (
        "defaults\n    mode tcp\n\nfrontend db\n    bind :5432\n    default_backend pg\n\n"
        "backend pg\n    server p pg:5432\n"
    )
    model, ops = _ops(adapter, text)
    assert ops == {}
    assert "mode.tcp" in _ignored(model)


def test_named_defaults_are_inherited_by_position(adapter: HaproxyImportSource) -> None:
    text = (
        "defaults web\n    mode http\n\nfrontend a\n    bind :80\n    default_backend b\n\n"
        "defaults raw\n    mode tcp\n\nfrontend c\n    bind :81\n    default_backend b\n\n"
        "backend b\n    server s s:80\n"
    )
    model, ops = _ops(adapter, text)
    assert list(ops) == ["ANY /"]
    assert "mode.tcp" in _ignored(model)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("defaults\n    mode http\nfrontnend x\n    bind :80\n", "INPUT_MALFORMED"),
        ("frontend x\n    bind :80\n    default_backend b\nbackend b\n    server s1 b.internal.exa", "INPUT_TRUNCATED"),
        ("frontend x\n    bind :80 \\\n", "INPUT_TRUNCATED"),
        ("defaults\n    mode http\nbackend b\n    server s b:80\n", "INPUT_SEMANTIC_INVALID"),
        ("defaults\n    mode http\nfrontend x\n    bind :80\n    default_backend nope\n", "INPUT_REFERENCE_UNRESOLVED"),
        (
            "defaults\n    mode http\nfrontend x\n    bind :80\n    use_backend b if undeclared_acl\n"
            "backend b\n    server s b:80\n",
            "INPUT_REFERENCE_UNRESOLVED",
        ),
        ("http:\n  routers: {}\n", "FORMAT_MISMATCH"),
    ],
)
def test_error_codes(adapter: HaproxyImportSource, text: str, code: str) -> None:
    with pytest.raises(ImportSourceError) as exc:
        adapter.parse(text)
    assert exc.value.code == code


def test_map_file_resolves_a_computed_backend(adapter: HaproxyImportSource) -> None:
    config = (
        "defaults\n    mode http\n\nfrontend f\n    bind :80\n"
        "    use_backend %[req.hdr(x-tenant),lower,map_str(/etc/haproxy/tenants.map,b)]\n"
        "    default_backend b\n\nbackend b\n    server s b:80\n\nbackend acme\n    server a a:80\n"
    )
    fileset = IntakeFileset.from_members({"haproxy.cfg": config, "tenants.map": "acme acme\n"}, root="haproxy.cfg")
    model = adapter.normalize(adapter.parse_fileset(fileset))
    mapped = [op for op in model.operations() if op.extras.get("map_key") == "acme"]
    assert mapped and mapped[0].parameters[0].name == "x-tenant"
    # Without the map, the computed backend is declared instead.
    alone = adapter.normalize(adapter.parse(config))
    assert "use_backend.dynamic" in _ignored(alone)


def test_map_entry_naming_an_undeclared_backend_is_refused(adapter: HaproxyImportSource) -> None:
    config = (
        "defaults\n    mode http\nfrontend f\n    bind :80\n"
        "    use_backend %[req.hdr(x),map_str(m.map,b)]\n    default_backend b\nbackend b\n    server s b:80\n"
    )
    fileset = IntakeFileset.from_members({"haproxy.cfg": config, "m.map": "k gone\n"}, root="haproxy.cfg")
    with pytest.raises(ImportSourceError) as exc:
        adapter.parse_fileset(fileset)
    assert exc.value.code == "INPUT_REFERENCE_UNRESOLVED"
