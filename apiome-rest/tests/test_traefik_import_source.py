"""Unit tests for the Traefik dynamic-configuration ImportSource (FMT-7.5 / #5459)."""

from __future__ import annotations

import pytest

from app.fileset import IntakeFileset
from app.import_source import DetectionInput, ImportSourceError
from app.traefik_import_source import TraefikImportSource
from app.traefik_parser import TraefikRuleError, is_traefik, parse_rule


@pytest.fixture
def adapter() -> TraefikImportSource:
    return TraefikImportSource()


DYNAMIC = """\
http:
  routers:
    orders:
      rule: Host(`api.example.com`) && PathPrefix(`/v2/orders`) && (Method(`GET`) || Method(`POST`))
      service: orders-service
      middlewares: [auth, limit]
      tls: {certResolver: letsencrypt}
    health:
      rule: Path(`/healthz`)
      service: orders-service
  services:
    orders-service:
      loadBalancer:
        servers:
          - url: http://orders-1.internal:8080
          - url: http://orders-2.internal:8080
  middlewares:
    auth:
      basicAuth:
        users: ["admin:$apr1$secret-hash"]
    limit:
      rateLimit: {average: 100}
"""

TOML = """\
[http.routers.api]
  rule = "Host(`api.example.com`) && PathPrefix(`/v3`)"
  service = "api"

[http.services.api.loadBalancer]
  [[http.services.api.loadBalancer.servers]]
    url = "http://api.internal:8080"
"""

CRD = """\
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata: {name: orders, namespace: shop}
spec:
  entryPoints: [websecure]
  routes:
    - match: Host(`api.example.com`) && Path(`/v2/orders/{id:[0-9]+}`)
      kind: Rule
      services:
        - {name: orders, port: 8080}
      middlewares:
        - name: limit
  tls: {secretName: cert}
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata: {name: limit, namespace: shop}
spec:
  rateLimit: {average: 10}
"""


def _ops(adapter: TraefikImportSource, text: str):
    model = adapter.normalize(adapter.parse(text, source_label="dynamic.yml"))
    return model, {op.key: op for op in model.operations()}


# ---------------------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------------------


def test_detects_dynamic_config_toml_and_crd(adapter: TraefikImportSource) -> None:
    for text in (DYNAMIC, TOML, CRD):
        result = adapter.detect(DetectionInput(text=text))
        assert result.matched and result.confidence >= 0.9 and result.format == "traefik"


def test_services_only_file_is_traefik_but_weak(adapter: TraefikImportSource) -> None:
    text = "http:\n  services:\n    a:\n      loadBalancer:\n        servers: [{url: http://a}]\n"
    assert is_traefik(text) == "supporting"
    assert adapter.detect(DetectionInput(text=text)).confidence < 0.85


@pytest.mark.parametrize("text", ["openapi: 3.1.0\ninfo: {title: x, version: '1'}\n", "server {\n listen 80;\n}\n"])
def test_does_not_claim_other_formats(adapter: TraefikImportSource, text: str) -> None:
    assert not adapter.detect(DetectionInput(text=text)).matched


# ---------------------------------------------------------------------------------------
# Rule grammar
# ---------------------------------------------------------------------------------------


def test_rule_expands_to_disjunctive_normal_form() -> None:
    dnf = parse_rule("Host(`a`) && (Method(`GET`) || Method(`HEAD`))")
    assert [[lit.render() for lit in conj] for conj in dnf] == [
        ["Host(`a`)", "Method(`GET`)"],
        ["Host(`a`)", "Method(`HEAD`)"],
    ]


def test_negation_binds_to_one_matcher() -> None:
    dnf = parse_rule("PathPrefix(`/p`) && !Header(`X-Internal`, `true`)")
    assert dnf[0][1].negated and dnf[0][1].args == ("X-Internal", "true")


@pytest.mark.parametrize("rule", ["Host(`a`", "Host(`a`) &&", "Path(/x)", "Host(`a`) Path(`b`)"])
def test_malformed_rules_raise(rule: str) -> None:
    with pytest.raises(TraefikRuleError):
        parse_rule(rule)


# ---------------------------------------------------------------------------------------
# Routes → operations
# ---------------------------------------------------------------------------------------


def test_router_rule_becomes_operations(adapter: TraefikImportSource) -> None:
    model, ops = _ops(adapter, DYNAMIC)
    assert model.format == "traefik"
    assert {"GET /v2/orders", "POST /v2/orders", "ANY /healthz"} <= set(ops)
    get = ops["GET /v2/orders"]
    assert get.extras["provenance"] == "inferred"
    assert get.extras["path_match"]["kind"] == "prefix"
    assert get.extras["hosts"] == ["api.example.com"]
    assert get.extras["plugins"] == ["rateLimit"]
    assert get.extras["security"][0]["scheme"] == "basic"
    assert [server.url for server in model.servers] == ["https://api.example.com"]


def test_basic_auth_users_are_redacted(adapter: TraefikImportSource) -> None:
    model, _ops_ = _ops(adapter, DYNAMIC)
    assert model.extras["gateway"]["credential_redactions"] == 1
    assert "secret-hash" not in str(model.model_dump())


def test_toml_form_reads_the_same_way(adapter: TraefikImportSource) -> None:
    _model, ops = _ops(adapter, TOML)
    assert set(ops) == {"ANY /v3"}


def test_crd_form_keeps_v2_path_template_parameters(adapter: TraefikImportSource) -> None:
    model, ops = _ops(adapter, CRD)
    op = ops["ANY /v2/orders/{id}"]
    assert [param.name for param in op.parameters] == ["id"]
    assert op.extras["backends"] == [{"name": "orders", "namespace": "shop", "port": 8080}]
    assert model.services[0].name == "shop/orders"


def test_unmodelled_conditions_are_kept_and_declared(adapter: TraefikImportSource) -> None:
    text = DYNAMIC.replace("rule: Path(`/healthz`)", "rule: Path(`/healthz`) && ClientIP(`10.0.0.0/8`)")
    model, ops = _ops(adapter, text)
    assert ops["ANY /healthz"].extras["unmodelled_conditions"] == ["ClientIP(`10.0.0.0/8`)"]
    assert "rule.ClientIP" in {entry["construct"] for entry in model.extras["gateway"]["ignored_constructs"]}


def test_tcp_and_udp_routers_are_declared(adapter: TraefikImportSource) -> None:
    text = DYNAMIC + "tcp:\n  routers:\n    db: {rule: HostSNI(`*`), service: db}\n"
    model, _ops_ = _ops(adapter, text)
    assert "tcp" in {entry["construct"] for entry in model.extras["gateway"]["ignored_constructs"]}


def test_router_order_does_not_change_operation_keys(adapter: TraefikImportSource) -> None:
    first = DYNAMIC
    swapped = DYNAMIC.replace("    orders:\n", "    zz-orders:\n")
    keys_a = {op.key.split("#")[0] for op in adapter.normalize(adapter.parse(first)).operations()}
    keys_b = {op.key.split("#")[0] for op in adapter.normalize(adapter.parse(swapped)).operations()}
    assert keys_a == keys_b


# ---------------------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("http:\n  routers:\n    a:\n      rule: Path(`/a`)\n       service: s\n", "INPUT_MALFORMED"),
        (
            'http:\n  routers:\n    a: {rule: Path(`/a`), service: s}\n  services:\n    s:\n      url: "http://x',
            "INPUT_TRUNCATED",
        ),
        ("http:\n  routers:\n    a:\n      service: s\n", "INPUT_SEMANTIC_INVALID"),
        ("http:\n  routers:\n    a: {rule: Path(`/a`), service: missing}\n", "INPUT_REFERENCE_UNRESOLVED"),
        (
            "http:\n  routers:\n    a: {rule: Path(`/a`), service: noop@internal, middlewares: [gone]}\n",
            "INPUT_REFERENCE_UNRESOLVED",
        ),
        ("server {\n  listen 80;\n}\n", "FORMAT_MISMATCH"),
        ("http:\n  routers:\n    a: {rule: Path(`/a`) &&, service: noop@internal}\n", "INPUT_MALFORMED"),
    ],
)
def test_error_codes(adapter: TraefikImportSource, text: str, code: str) -> None:
    with pytest.raises(ImportSourceError) as exc:
        adapter.parse(text)
    assert exc.value.code == code


def test_other_provider_references_are_kept_as_written(adapter: TraefikImportSource) -> None:
    _model, ops = _ops(adapter, "http:\n  routers:\n    a: {rule: Path(`/a`), service: api@docker}\n")
    assert ops["ANY /a"].extras["backends"] == [{"name": "api@docker"}]


def test_utf16_is_an_encoding_error(adapter: TraefikImportSource) -> None:
    with pytest.raises(ImportSourceError) as exc:
        adapter.parse(DYNAMIC.encode("utf-16").decode("utf-8", errors="replace"))
    assert exc.value.code == "INPUT_ENCODING_INVALID"


# ---------------------------------------------------------------------------------------
# File-provider directory
# ---------------------------------------------------------------------------------------


def test_directory_resolves_services_across_files(adapter: TraefikImportSource) -> None:
    fileset = IntakeFileset.from_members(
        {
            "routers.yml": "http:\n  routers:\n    a: {rule: Path(`/a`), service: s, middlewares: [m]}\n",
            "services.yml": "http:\n  services:\n    s:\n      loadBalancer:\n        servers: [{url: http://s:80}]\n",
            "middlewares.yml": "http:\n  middlewares:\n    m: {stripPrefix: {prefixes: [/a]}}\n",
        },
        root="routers.yml",
    )
    model = adapter.normalize(adapter.parse_fileset(fileset))
    op = next(iter(model.operations()))
    assert op.extras["plugins"] == ["stripPrefix"]
    assert model.raw["gateway_config"]["shape"] == ["directory", "file"]


def test_capability_declaration_names_the_rule_grammar(adapter: TraefikImportSource) -> None:
    capabilities = adapter.analysis_capabilities()
    assert "traefik.rule.PathPrefix" in capabilities.supported
    assert "traefik.rule.negation" in capabilities.unsupported
