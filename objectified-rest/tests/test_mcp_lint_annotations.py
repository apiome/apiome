"""Unit tests for the MCP annotation-consistency & security rule pack (V2-MCP-21.3, #3684).

These exercise :mod:`app.mcp_lint_annotations`: the concrete annotation-consistency and
security-posture rules that plug into the pure engine in :mod:`app.mcp_lint`. The contract
for every rule is the same and is asserted twice per rule: it *fires on a crafted bad
surface* and *stays silent on a clean one*, and the security/annotation ``warning`` signals
are kept distinct from the advisory ``info`` missing-instructions hint.

The rules self-register when :mod:`app.mcp_lint` is imported (the engine imports the pack at
load time), so the tests drive everything through :func:`app.mcp_lint.lint_mcp_surface` plus
a few direct calls into the predicate helpers.
"""

from __future__ import annotations

from typing import Any, List, Optional

from app.mcp_client.handshake import ServerInfo
from app.mcp_client.normalize import (
    ITEM_TYPE_RESOURCE,
    ITEM_TYPE_RESOURCE_TEMPLATE,
    ITEM_TYPE_TOOL,
    CapabilityItem,
    DiscoverySurface,
)
from app.mcp_lint import RULE_CATALOGUE, SEVERITY_PENALTY, lint_mcp_surface
from app.mcp_lint_annotations import (
    ANNOTATION_RULES,
    _bool_hint,
    _credential_parameters,
    _host_ssrf_reason,
    _is_overbroad_scope,
    _iter_scope_values,
    _normalize_param_name,
    _uri_ssrf_reason,
)

# --- Fixture builders -----------------------------------------------------------------------

_GOOD_SCHEMA = {"type": "object", "properties": {"q": {"type": "string"}}}


def _tool(name: str = "tool", ordinal: int = 0, **extra: Any) -> CapabilityItem:
    return CapabilityItem(item_type=ITEM_TYPE_TOOL, name=name, ordinal=ordinal, **extra)


def _resource(name: str = "doc", ordinal: int = 0, **extra: Any) -> CapabilityItem:
    return CapabilityItem(item_type=ITEM_TYPE_RESOURCE, name=name, ordinal=ordinal, **extra)


def _template(name: str = "tpl", ordinal: int = 0, **extra: Any) -> CapabilityItem:
    return CapabilityItem(
        item_type=ITEM_TYPE_RESOURCE_TEMPLATE, name=name, ordinal=ordinal, **extra
    )


def _surface(
    tools: Optional[List[CapabilityItem]] = None,
    resources: Optional[List[CapabilityItem]] = None,
    resource_templates: Optional[List[CapabilityItem]] = None,
    prompts: Optional[List[CapabilityItem]] = None,
    capabilities: Optional[dict] = None,
    instructions: Optional[str] = "Use search before fetch.",
) -> DiscoverySurface:
    return DiscoverySurface(
        protocol_version="2025-06-18",
        server_info=ServerInfo(name="srv", title="Server", version="1.0.0"),
        capabilities=capabilities or {},
        instructions=instructions,
        tools=tuple(tools or ()),
        resources=tuple(resources or ()),
        resource_templates=tuple(resource_templates or ()),
        prompts=tuple(prompts or ()),
    )


def _rules_for(surface: DiscoverySurface) -> set:
    return {finding.rule for finding in lint_mcp_surface(surface)}


# A surface with one clean tool/resource and server instructions. No 21.3 rule should fire.
CLEAN_SURFACE = _surface(
    tools=[
        _tool(
            name="search",
            input_schema=dict(_GOOD_SCHEMA),
            annotations={"readOnlyHint": True, "idempotentHint": True},
            raw={"name": "search", "inputSchema": dict(_GOOD_SCHEMA)},
        )
    ],
    resources=[
        _resource(name="doc", uri="https://example.com/doc", raw={"name": "doc"})
    ],
    capabilities={"tools": {"listChanged": True}},
    instructions="Call search before fetch.",
)


# --- Clean surface: no 21.3 rule fires ------------------------------------------------------


def test_clean_surface_emits_no_annotation_findings() -> None:
    fired = _rules_for(CLEAN_SURFACE)
    assert fired.isdisjoint(ANNOTATION_RULES.keys()), sorted(fired & ANNOTATION_RULES.keys())


# --- Catalogue / registration --------------------------------------------------------------


def test_annotation_rules_are_registered_with_declared_metadata() -> None:
    for rule, (category, severity) in ANNOTATION_RULES.items():
        assert RULE_CATALOGUE[rule] == (category, severity)
        assert severity in SEVERITY_PENALTY
        assert rule.split(".")[0] == category


def test_severities_match_normative_force() -> None:
    # annotation/security are SHOULD-level warnings; quality.* here is advisory info.
    for rule, (category, severity) in ANNOTATION_RULES.items():
        if category in ("annotation", "security"):
            assert severity == "warning", rule
        else:
            assert severity == "info", rule


# --- Annotation contradictions (annotation, warning) ---------------------------------------


def test_read_only_with_destructive_flagged() -> None:
    tool = _tool(
        annotations={"readOnlyHint": True, "destructiveHint": True},
        raw={"name": "tool"},
    )
    findings = lint_mcp_surface(_surface(tools=[tool]))
    hit = [f for f in findings if f.rule == "annotation.read-only-contradicts-destructive"]
    assert len(hit) == 1
    assert hit[0].severity == "warning"


def test_read_only_with_non_idempotent_flagged() -> None:
    tool = _tool(
        annotations={"readOnlyHint": True, "idempotentHint": False},
        raw={"name": "tool"},
    )
    assert "annotation.read-only-contradicts-non-idempotent" in _rules_for(_surface(tools=[tool]))


def test_read_only_tool_can_trip_both_contradictions() -> None:
    tool = _tool(
        annotations={"readOnlyHint": True, "destructiveHint": True, "idempotentHint": False},
        raw={"name": "tool"},
    )
    fired = _rules_for(_surface(tools=[tool]))
    assert "annotation.read-only-contradicts-destructive" in fired
    assert "annotation.read-only-contradicts-non-idempotent" in fired


def test_write_tool_with_destructive_hint_is_clean() -> None:
    # readOnlyHint is false (a writing tool), so destructive/non-idempotent are consistent.
    tool = _tool(
        annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False},
        raw={"name": "tool"},
    )
    fired = _rules_for(_surface(tools=[tool]))
    assert "annotation.read-only-contradicts-destructive" not in fired
    assert "annotation.read-only-contradicts-non-idempotent" not in fired


def test_read_only_consistent_hints_are_clean() -> None:
    tool = _tool(
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
        raw={"name": "tool"},
    )
    assert _rules_for(_surface(tools=[tool])).isdisjoint(
        {
            "annotation.read-only-contradicts-destructive",
            "annotation.read-only-contradicts-non-idempotent",
        }
    )


def test_non_boolean_hints_are_ignored() -> None:
    # A non-boolean hint value is treated as unset, not as a contradiction.
    tool = _tool(
        annotations={"readOnlyHint": "true", "destructiveHint": "true"},
        raw={"name": "tool"},
    )
    assert _rules_for(_surface(tools=[tool])).isdisjoint(ANNOTATION_RULES.keys())


def test_bool_hint_predicate() -> None:
    assert _bool_hint({"readOnlyHint": True}, "readOnlyHint") is True
    assert _bool_hint({"readOnlyHint": False}, "readOnlyHint") is False
    assert _bool_hint({"readOnlyHint": "true"}, "readOnlyHint") is None
    assert _bool_hint({}, "readOnlyHint") is None
    assert _bool_hint(None, "readOnlyHint") is None


# --- Token passthrough (security, warning) -------------------------------------------------


def test_tool_credential_parameter_flagged() -> None:
    schema = {"type": "object", "properties": {"access_token": {"type": "string"}}}
    tool = _tool(input_schema=schema, raw={"name": "tool", "inputSchema": schema})
    findings = lint_mcp_surface(_surface(tools=[tool]))
    hit = [f for f in findings if f.rule == "security.tool-token-passthrough-parameter"]
    assert len(hit) == 1
    assert hit[0].severity == "warning"
    assert hit[0].path == "tools.tool.inputSchema.access_token"


def test_multiple_credential_parameters_each_flagged() -> None:
    schema = {
        "type": "object",
        "properties": {
            "api_key": {"type": "string"},
            "password": {"type": "string"},
            "query": {"type": "string"},
        },
    }
    tool = _tool(input_schema=schema, raw={"name": "tool", "inputSchema": schema})
    paths = {
        f.path
        for f in lint_mcp_surface(_surface(tools=[tool]))
        if f.rule == "security.tool-token-passthrough-parameter"
    }
    assert paths == {"tools.tool.inputSchema.api_key", "tools.tool.inputSchema.password"}


def test_non_credential_lookalike_parameter_not_flagged() -> None:
    # "tokenizer"/"passwordPolicyUrl" merely contain a credential word; must NOT match.
    schema = {
        "type": "object",
        "properties": {
            "tokenizer": {"type": "string"},
            "passwordPolicyUrl": {"type": "string"},
        },
    }
    tool = _tool(input_schema=schema, raw={"name": "tool", "inputSchema": schema})
    assert "security.tool-token-passthrough-parameter" not in _rules_for(_surface(tools=[tool]))


def test_credential_parameters_helper() -> None:
    schema = {
        "type": "object",
        "properties": {"Authorization": {}, "apiKey": {}, "q": {}},
    }
    tool = _tool(input_schema=schema)
    assert _credential_parameters(tool) == ["Authorization", "apiKey"]
    # No properties / non-object schema -> nothing.
    assert _credential_parameters(_tool(input_schema={"type": "object"})) == []
    assert _credential_parameters(_tool(input_schema=None)) == []


def test_normalize_param_name() -> None:
    assert _normalize_param_name("access_token") == "accesstoken"
    assert _normalize_param_name("API-Key") == "apikey"
    assert _normalize_param_name("Bearer Token") == "bearertoken"


# --- Over-broad scope (security, warning) --------------------------------------------------


def test_wildcard_scope_flagged() -> None:
    caps = {"experimental": {"auth": {"scopes": ["read:*"]}}}
    findings = lint_mcp_surface(_surface(capabilities=caps))
    hit = [f for f in findings if f.rule == "security.over-broad-auth-scope"]
    assert len(hit) == 1
    assert hit[0].severity == "warning"
    assert hit[0].path == "surface.capabilities"


def test_admin_scope_flagged() -> None:
    caps = {"auth": {"scope": "admin"}}
    assert "security.over-broad-auth-scope" in _rules_for(_surface(capabilities=caps))


def test_least_privilege_scopes_are_clean() -> None:
    caps = {"auth": {"scopes": ["repo:read", "issues:write"]}}
    assert "security.over-broad-auth-scope" not in _rules_for(_surface(capabilities=caps))


def test_distinct_over_broad_scopes_each_flagged_once() -> None:
    caps = {"auth": {"scopes": ["*", "*", "admin"]}}
    msgs = [
        f.message
        for f in lint_mcp_surface(_surface(capabilities=caps))
        if f.rule == "security.over-broad-auth-scope"
    ]
    # "*" de-duplicated to one finding; "admin" adds a second.
    assert len(msgs) == 2


def test_is_overbroad_scope_predicate() -> None:
    assert _is_overbroad_scope("*") is True
    assert _is_overbroad_scope("read:*") is True
    assert _is_overbroad_scope("admin") is True
    assert _is_overbroad_scope("full_access") is True
    assert _is_overbroad_scope("repo:read") is False
    assert _is_overbroad_scope("") is False


def test_iter_scope_values_walks_nested_capabilities() -> None:
    caps = {"a": {"scope": "x"}, "b": [{"scopes": ["y", "z"]}], "c": {"scopes": "w"}}
    assert sorted(_iter_scope_values(caps)) == ["w", "x", "y", "z"]


# --- SSRF-risky resource URIs (security, warning) ------------------------------------------


def test_loopback_resource_uri_flagged() -> None:
    res = _resource(uri="http://127.0.0.1/admin", raw={"name": "doc"})
    findings = lint_mcp_surface(_surface(resources=[res]))
    hit = [f for f in findings if f.rule == "security.ssrf-risky-resource-uri"]
    assert len(hit) == 1
    assert hit[0].severity == "warning"
    assert hit[0].path == "resources.doc"


def test_cloud_metadata_resource_uri_flagged() -> None:
    res = _resource(uri="http://169.254.169.254/latest/meta-data/", raw={"name": "doc"})
    assert "security.ssrf-risky-resource-uri" in _rules_for(_surface(resources=[res]))


def test_internal_hostname_resource_uri_flagged() -> None:
    res = _resource(uri="https://db.internal/dump", raw={"name": "doc"})
    assert "security.ssrf-risky-resource-uri" in _rules_for(_surface(resources=[res]))


def test_localhost_resource_uri_flagged() -> None:
    res = _resource(uri="http://localhost:8080/x", raw={"name": "doc"})
    assert "security.ssrf-risky-resource-uri" in _rules_for(_surface(resources=[res]))


def test_private_rfc1918_resource_uri_flagged() -> None:
    res = _resource(uri="http://10.0.0.5/secret", raw={"name": "doc"})
    assert "security.ssrf-risky-resource-uri" in _rules_for(_surface(resources=[res]))


def test_public_resource_uri_is_clean() -> None:
    res = _resource(uri="https://api.example.com/v1/doc", raw={"name": "doc"})
    assert "security.ssrf-risky-resource-uri" not in _rules_for(_surface(resources=[res]))


def test_ssrf_risky_resource_template_flagged() -> None:
    tpl = _template(uri_template="http://localhost/items/{id}", raw={"name": "tpl"})
    assert "security.ssrf-risky-resource-uri" in _rules_for(_surface(resource_templates=[tpl]))


def test_template_with_host_expression_not_flagged() -> None:
    # Host itself is a template expression; there is no literal host to assess.
    tpl = _template(uri_template="https://{host}/items/{id}", raw={"name": "tpl"})
    assert "security.ssrf-risky-resource-uri" not in _rules_for(
        _surface(resource_templates=[tpl])
    )


def test_hostless_uri_not_flagged_for_ssrf() -> None:
    # A hostless file: URI has no host to assess (the hygiene pack judges its validity).
    res = _resource(uri="file:///etc/hosts", raw={"name": "doc"})
    assert "security.ssrf-risky-resource-uri" not in _rules_for(_surface(resources=[res]))


def test_host_ssrf_reason_predicate() -> None:
    assert _host_ssrf_reason("127.0.0.1") is not None
    assert _host_ssrf_reason("169.254.169.254") is not None
    assert _host_ssrf_reason("10.1.2.3") is not None
    assert _host_ssrf_reason("192.168.1.1") is not None
    assert _host_ssrf_reason("localhost") is not None
    assert _host_ssrf_reason("foo.internal") is not None
    assert _host_ssrf_reason("metadata.google.internal") is not None
    assert _host_ssrf_reason("8.8.8.8") is None
    assert _host_ssrf_reason("example.com") is None


def test_uri_ssrf_reason_predicate() -> None:
    assert _uri_ssrf_reason("http://127.0.0.1/") is not None
    assert _uri_ssrf_reason("https://example.com/") is None
    assert _uri_ssrf_reason(None) is None
    assert _uri_ssrf_reason("") is None
    assert _uri_ssrf_reason("https://{host}/x") is None


# --- Missing server instructions (quality, info) -------------------------------------------


def test_missing_instructions_flagged_as_info() -> None:
    findings = lint_mcp_surface(_surface(instructions=None))
    hit = [f for f in findings if f.rule == "quality.server-missing-instructions"]
    assert len(hit) == 1
    assert hit[0].severity == "info"
    assert hit[0].path == "surface"


def test_blank_instructions_flagged() -> None:
    assert "quality.server-missing-instructions" in _rules_for(_surface(instructions="   "))


def test_present_instructions_are_clean() -> None:
    assert "quality.server-missing-instructions" not in _rules_for(
        _surface(instructions="Drive the server like so.")
    )


# --- Engine integration: ordering & determinism with the new rules -------------------------


def test_dirty_surface_findings_remain_sorted_and_deterministic() -> None:
    schema = {"type": "object", "properties": {"token": {"type": "string"}}}
    dirty = _surface(
        tools=[
            _tool(
                name="t",
                input_schema=schema,
                annotations={"readOnlyHint": True, "destructiveHint": True},
                raw={"name": "t", "inputSchema": schema},
            )
        ],
        resources=[_resource(name="r", uri="http://127.0.0.1/x", raw={"name": "r"})],
        capabilities={"auth": {"scopes": ["*"]}},
        instructions=None,
    )
    a = lint_mcp_surface(dirty)
    b = lint_mcp_surface(dirty)
    assert [f.id for f in a] == [f.id for f in b]
    keys = [(f.path, f.rule, f.id) for f in a]
    assert keys == sorted(keys)
    fired = {f.rule for f in a}
    assert "annotation.read-only-contradicts-destructive" in fired
    assert "security.tool-token-passthrough-parameter" in fired
    assert "security.over-broad-auth-scope" in fired
    assert "security.ssrf-risky-resource-uri" in fired
    assert "quality.server-missing-instructions" in fired
