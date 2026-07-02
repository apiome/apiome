"""Unit tests for the MCP tool/resource/prompt hygiene rule pack (V2-MCP-21.2, #3683).

These exercise :mod:`app.mcp_lint_hygiene`: the concrete per-kind hygiene rules that plug
into the pure engine in :mod:`app.mcp_lint`. The contract for every rule is the same and is
asserted twice per rule: it *fires on a crafted bad surface* and *stays silent on a clean
one*, and MUST-level (``error``) findings are kept distinct from SHOULD/advisory
(``warning``/``info``) ones.

The rules self-register when :mod:`app.mcp_lint` is imported (the engine imports the pack at
load time), so the tests drive everything through :func:`app.mcp_lint.lint_mcp_surface` plus a
few direct calls into the predicate helpers.
"""

from __future__ import annotations

from typing import Any, List, Optional

from app.mcp_client.handshake import ServerInfo
from app.mcp_client.normalize import (
    ITEM_TYPE_PROMPT,
    ITEM_TYPE_RESOURCE,
    ITEM_TYPE_RESOURCE_TEMPLATE,
    ITEM_TYPE_TOOL,
    CapabilityItem,
    DiscoverySurface,
)
from app.mcp_lint import RULE_CATALOGUE, SEVERITY_PENALTY, lint_mcp_surface
from app.mcp_lint_hygiene import (
    HYGIENE_RULES,
    _expression_problem,
    _is_blank,
    _tool_input_schema_problem,
    _uri_problem,
    _uri_template_problem,
)

# --- Fixture builders -----------------------------------------------------------------------

# A minimal, fully clean inputSchema: a valid draft 2020-12 ``type: object`` schema.
_GOOD_SCHEMA = {"type": "object", "properties": {"q": {"type": "string"}}}


def _tool(name: str = "tool", ordinal: int = 0, **extra: Any) -> CapabilityItem:
    return CapabilityItem(item_type=ITEM_TYPE_TOOL, name=name, ordinal=ordinal, **extra)


def _clean_tool(name: str = "search", ordinal: int = 0) -> CapabilityItem:
    """A tool with no hygiene defects: schema, description, title, and output schema."""
    return _tool(
        name=name,
        ordinal=ordinal,
        title="Search",
        description="Search the corpus.",
        input_schema=dict(_GOOD_SCHEMA),
        output_schema={"type": "object"},
        raw={"name": name, "inputSchema": dict(_GOOD_SCHEMA)},
    )


def _resource(name: str = "doc", ordinal: int = 0, **extra: Any) -> CapabilityItem:
    return CapabilityItem(item_type=ITEM_TYPE_RESOURCE, name=name, ordinal=ordinal, **extra)


def _clean_resource(name: str = "doc", ordinal: int = 0) -> CapabilityItem:
    return _resource(
        name=name,
        ordinal=ordinal,
        title="Doc",
        uri="file:///docs/readme.md",
        raw={"name": name, "uri": "file:///docs/readme.md", "mimeType": "text/markdown"},
    )


def _template(name: str = "tpl", ordinal: int = 0, **extra: Any) -> CapabilityItem:
    return CapabilityItem(
        item_type=ITEM_TYPE_RESOURCE_TEMPLATE, name=name, ordinal=ordinal, **extra
    )


def _clean_template(name: str = "tpl", ordinal: int = 0) -> CapabilityItem:
    return _template(
        name=name,
        ordinal=ordinal,
        title="Doc by id",
        uri_template="file:///docs/{id}.md",
        raw={
            "name": name,
            "uriTemplate": "file:///docs/{id}.md",
            "mimeType": "text/markdown",
        },
    )


def _prompt(name: str = "greet", ordinal: int = 0, **extra: Any) -> CapabilityItem:
    return CapabilityItem(item_type=ITEM_TYPE_PROMPT, name=name, ordinal=ordinal, **extra)


def _clean_prompt(name: str = "greet", ordinal: int = 0) -> CapabilityItem:
    return _prompt(
        name=name,
        ordinal=ordinal,
        title="Greet",
        raw={
            "name": name,
            "arguments": [
                {"name": "who", "description": "Whom to greet.", "required": True}
            ],
        },
    )


def _surface(
    tools: Optional[List[CapabilityItem]] = None,
    resources: Optional[List[CapabilityItem]] = None,
    resource_templates: Optional[List[CapabilityItem]] = None,
    prompts: Optional[List[CapabilityItem]] = None,
) -> DiscoverySurface:
    return DiscoverySurface(
        protocol_version="2025-06-18",
        server_info=ServerInfo(name="srv", title="Server", version="1.0.0"),
        capabilities={},
        instructions=None,
        tools=tuple(tools or ()),
        resources=tuple(resources or ()),
        resource_templates=tuple(resource_templates or ()),
        prompts=tuple(prompts or ()),
    )


def _rules_for(surface: DiscoverySurface) -> set:
    return {finding.rule for finding in lint_mcp_surface(surface)}


# A surface with one fully clean item of every kind. Every hygiene rule MUST stay silent.
CLEAN_SURFACE = _surface(
    tools=[_clean_tool()],
    resources=[_clean_resource()],
    resource_templates=[_clean_template()],
    prompts=[_clean_prompt()],
)


# --- Clean surface: no hygiene rule fires ---------------------------------------------------


def test_clean_surface_emits_no_hygiene_findings() -> None:
    fired = _rules_for(CLEAN_SURFACE)
    assert fired.isdisjoint(HYGIENE_RULES.keys()), sorted(fired & HYGIENE_RULES.keys())


# --- Catalogue / registration --------------------------------------------------------------


def test_hygiene_rules_are_registered_with_declared_metadata() -> None:
    for rule, (category, severity) in HYGIENE_RULES.items():
        assert RULE_CATALOGUE[rule] == (category, severity)
        assert severity in SEVERITY_PENALTY
        assert rule.split(".")[0] == category


def test_must_vs_should_severities_are_distinguished() -> None:
    # schema.* are normative MUSTs (error); quality.* are SHOULD/advisory (warning/info).
    for rule, (category, severity) in HYGIENE_RULES.items():
        if category == "schema":
            assert severity == "error", rule
        else:
            assert severity in ("warning", "info"), rule


# --- Tool: inputSchema (schema, error) -----------------------------------------------------


def test_tool_missing_input_schema_flagged() -> None:
    tool = _tool(raw={"name": "tool"})  # no inputSchema key at all
    assert "schema.tool-input-schema-invalid" in _rules_for(_surface(tools=[tool]))


def test_tool_non_object_input_schema_flagged() -> None:
    # inputSchema present on the wire but not a JSON object -> normalized to None.
    tool = _tool(input_schema=None, raw={"name": "tool", "inputSchema": "nope"})
    assert "schema.tool-input-schema-invalid" in _rules_for(_surface(tools=[tool]))


def test_tool_input_schema_wrong_type_flagged() -> None:
    tool = _tool(
        input_schema={"type": "array"},
        raw={"name": "tool", "inputSchema": {"type": "array"}},
    )
    assert "schema.tool-input-schema-invalid" in _rules_for(_surface(tools=[tool]))


def test_tool_structurally_invalid_input_schema_flagged() -> None:
    bad = {"type": "object", "properties": "not-an-object"}
    tool = _tool(input_schema=bad, raw={"name": "tool", "inputSchema": bad})
    assert "schema.tool-input-schema-invalid" in _rules_for(_surface(tools=[tool]))


def test_tool_input_schema_problem_messages_are_specific() -> None:
    assert "absent" in (_tool_input_schema_problem(_tool(raw={})) or "")
    assert "not a JSON object" in (
        _tool_input_schema_problem(_tool(input_schema=None, raw={"inputSchema": 1})) or ""
    )
    assert "type 'object'" in (
        _tool_input_schema_problem(
            _tool(input_schema={"type": "string"}, raw={"inputSchema": {"type": "string"}})
        )
        or ""
    )
    assert (
        _tool_input_schema_problem(
            _tool(input_schema=dict(_GOOD_SCHEMA), raw={"inputSchema": dict(_GOOD_SCHEMA)})
        )
        is None
    )


# --- Tool: description / outputSchema / title (quality) ------------------------------------


def test_tool_missing_description_flagged_as_warning() -> None:
    tool = _tool(
        name="t",
        title="T",
        input_schema=dict(_GOOD_SCHEMA),
        output_schema={"type": "object"},
        description=None,
        raw={"name": "t", "inputSchema": dict(_GOOD_SCHEMA)},
    )
    findings = lint_mcp_surface(_surface(tools=[tool]))
    desc = [f for f in findings if f.rule == "quality.tool-missing-description"]
    assert len(desc) == 1
    assert desc[0].severity == "warning"


def test_tool_blank_description_flagged() -> None:
    tool = _tool(
        name="t",
        title="T",
        description="   ",
        input_schema=dict(_GOOD_SCHEMA),
        output_schema={"type": "object"},
        raw={"name": "t", "inputSchema": dict(_GOOD_SCHEMA)},
    )
    assert "quality.tool-missing-description" in _rules_for(_surface(tools=[tool]))


def test_tool_missing_output_schema_flagged_as_info() -> None:
    tool = _tool(
        name="t",
        title="T",
        description="d",
        input_schema=dict(_GOOD_SCHEMA),
        output_schema=None,
        raw={"name": "t", "inputSchema": dict(_GOOD_SCHEMA)},
    )
    findings = lint_mcp_surface(_surface(tools=[tool]))
    out = [f for f in findings if f.rule == "quality.tool-missing-output-schema"]
    assert len(out) == 1
    assert out[0].severity == "info"


def test_missing_title_flagged_for_every_kind() -> None:
    surface = _surface(
        tools=[
            _tool(
                name="t",
                description="d",
                input_schema=dict(_GOOD_SCHEMA),
                output_schema={"type": "object"},
                raw={"name": "t", "inputSchema": dict(_GOOD_SCHEMA)},
            )
        ],
        resources=[
            _resource(name="r", uri="file:///r", raw={"name": "r", "uri": "file:///r", "mimeType": "text/plain"})
        ],
        resource_templates=[
            _template(
                name="tpl",
                uri_template="file:///{id}",
                raw={"name": "tpl", "uriTemplate": "file:///{id}", "mimeType": "text/plain"},
            )
        ],
        prompts=[_prompt(name="p", raw={"name": "p", "arguments": []})],
    )
    titles = [
        f for f in lint_mcp_surface(surface) if f.rule == "quality.item-missing-title"
    ]
    assert len(titles) == 4
    assert all(f.severity == "info" for f in titles)


# --- Resource: uri (schema, error) & mimeType (quality, warning) ---------------------------


def test_resource_missing_uri_flagged() -> None:
    res = _resource(uri=None, raw={"name": "doc", "mimeType": "text/plain"})
    assert "schema.resource-invalid-uri" in _rules_for(_surface(resources=[res]))


def test_resource_schemeless_uri_flagged() -> None:
    res = _resource(uri="docs/readme.md", raw={"name": "doc", "uri": "docs/readme.md", "mimeType": "text/plain"})
    assert "schema.resource-invalid-uri" in _rules_for(_surface(resources=[res]))


def test_resource_custom_scheme_uri_is_clean() -> None:
    res = _resource(
        name="screen",
        title="Screen",
        uri="screen://localhost/main",
        raw={"name": "screen", "uri": "screen://localhost/main", "mimeType": "image/png"},
    )
    assert "schema.resource-invalid-uri" not in _rules_for(_surface(resources=[res]))


def test_resource_missing_mime_type_flagged_as_warning() -> None:
    res = _resource(
        name="doc", title="Doc", uri="file:///doc", raw={"name": "doc", "uri": "file:///doc"}
    )
    findings = lint_mcp_surface(_surface(resources=[res]))
    mime = [f for f in findings if f.rule == "quality.resource-missing-mime-type"]
    assert len(mime) == 1
    assert mime[0].severity == "warning"


# --- Resource template: uriTemplate (schema, error) & mimeType -----------------------------


def test_template_missing_uri_template_flagged() -> None:
    tpl = _template(uri_template=None, raw={"name": "tpl", "mimeType": "text/plain"})
    assert "schema.resource-template-invalid-uri-template" in _rules_for(
        _surface(resource_templates=[tpl])
    )


def test_template_malformed_uri_template_flagged() -> None:
    tpl = _template(
        uri_template="file:///docs/{id",
        raw={"name": "tpl", "uriTemplate": "file:///docs/{id", "mimeType": "text/plain"},
    )
    assert "schema.resource-template-invalid-uri-template" in _rules_for(
        _surface(resource_templates=[tpl])
    )


def test_template_schemeless_but_well_formed_is_clean() -> None:
    # A relative RFC 6570 template (no literal scheme) is valid; only brace syntax matters.
    tpl = _template(
        name="rel",
        title="Rel",
        uri_template="items/{id}",
        raw={"name": "rel", "uriTemplate": "items/{id}", "mimeType": "text/plain"},
    )
    assert "schema.resource-template-invalid-uri-template" not in _rules_for(
        _surface(resource_templates=[tpl])
    )


def test_template_missing_mime_type_flagged() -> None:
    tpl = _template(
        name="tpl",
        title="Tpl",
        uri_template="file:///{id}",
        raw={"name": "tpl", "uriTemplate": "file:///{id}"},
    )
    assert "quality.resource-template-missing-mime-type" in _rules_for(
        _surface(resource_templates=[tpl])
    )


# --- Prompt arguments (quality) ------------------------------------------------------------


def test_prompt_argument_missing_description_flagged_as_warning() -> None:
    prompt = _prompt(
        name="p",
        title="P",
        raw={"name": "p", "arguments": [{"name": "who", "required": True}]},
    )
    findings = lint_mcp_surface(_surface(prompts=[prompt]))
    desc = [f for f in findings if f.rule == "quality.prompt-argument-missing-description"]
    assert len(desc) == 1
    assert desc[0].severity == "warning"
    assert desc[0].path == "prompts.p.arguments.who"


def test_prompt_argument_missing_required_flagged_as_info() -> None:
    prompt = _prompt(
        name="p",
        title="P",
        raw={"name": "p", "arguments": [{"name": "who", "description": "d"}]},
    )
    findings = lint_mcp_surface(_surface(prompts=[prompt]))
    req = [f for f in findings if f.rule == "quality.prompt-argument-missing-required"]
    assert len(req) == 1
    assert req[0].severity == "info"


def test_prompt_argument_without_name_uses_ordinal_path() -> None:
    # An argument with no ``name`` falls back to its ordinal in the finding path.
    prompt = _prompt(
        name="p2", title="P2", raw={"name": "p2", "arguments": [{"description": "d"}]}
    )
    findings = lint_mcp_surface(_surface(prompts=[prompt]))
    paths = {f.path for f in findings if f.rule == "quality.prompt-argument-missing-required"}
    assert "prompts.p2.arguments.#0" in paths


def test_prompt_with_clean_arguments_is_silent() -> None:
    prompt = _clean_prompt()
    fired = _rules_for(_surface(prompts=[prompt]))
    assert "quality.prompt-argument-missing-description" not in fired
    assert "quality.prompt-argument-missing-required" not in fired


def test_prompt_non_list_arguments_ignored() -> None:
    # A prompt whose ``arguments`` is not a list yields no per-argument findings (no crash).
    prompt = _prompt(name="p", title="P", raw={"name": "p", "arguments": "bogus"})
    fired = _rules_for(_surface(prompts=[prompt]))
    assert "quality.prompt-argument-missing-description" not in fired
    assert "quality.prompt-argument-missing-required" not in fired


def test_prompt_with_no_arguments_key_is_silent() -> None:
    prompt = _prompt(name="p", title="P", raw={"name": "p"})
    fired = _rules_for(_surface(prompts=[prompt]))
    assert "quality.prompt-argument-missing-description" not in fired
    assert "quality.prompt-argument-missing-required" not in fired


# --- Helper predicates ---------------------------------------------------------------------


def test_uri_problem_predicate() -> None:
    assert _uri_problem(None) is not None
    assert _uri_problem("") is not None
    assert _uri_problem("relative/path") is not None
    assert _uri_problem("https://example.com/x") is None
    assert _uri_problem("file:///etc/hosts") is None


def test_uri_template_problem_predicate() -> None:
    assert _uri_template_problem(None) is not None
    assert _uri_template_problem("a/{b") is not None  # unterminated
    assert _uri_template_problem("a/b}") is not None  # orphan close
    assert _uri_template_problem("a/{{b}}") is not None  # nested
    assert _uri_template_problem("a/{}") is not None  # empty
    assert _uri_template_problem("file:///{id}/{rev}") is None
    assert _uri_template_problem("items/{id}") is None


def test_expression_problem_distinguishes_defects() -> None:
    assert _expression_problem("{a}") is None
    assert "nested" in (_expression_problem("{a{b}}") or "")
    assert "empty" in (_expression_problem("{}") or "")
    assert "without a matching" in (_expression_problem("a}") or "")
    assert "unterminated" in (_expression_problem("{a") or "")


def test_is_blank_predicate() -> None:
    assert _is_blank(None) is True
    assert _is_blank("") is True
    assert _is_blank("   ") is True
    assert _is_blank(123) is True  # non-string is treated as not provided
    assert _is_blank("x") is False


# --- Engine integration: ordering & determinism with the new rules -------------------------


def test_dirty_surface_findings_remain_sorted_and_deterministic() -> None:
    dirty = _surface(
        tools=[_tool(name="t", raw={"name": "t"})],  # missing schema/desc/title/output
        resources=[_resource(name="r", uri=None, raw={"name": "r"})],
        prompts=[_prompt(name="p", raw={"name": "p", "arguments": [{}]})],
    )
    a = lint_mcp_surface(dirty)
    b = lint_mcp_surface(dirty)
    assert [f.id for f in a] == [f.id for f in b]
    keys = [(f.path, f.rule, f.id) for f in a]
    assert keys == sorted(keys)
    # Sanity: the crafted surface trips both schema (MUST) and quality (SHOULD/info) rules.
    fired = {f.rule for f in a}
    assert "schema.tool-input-schema-invalid" in fired
    assert "schema.resource-invalid-uri" in fired
    assert any(f.startswith("quality.") for f in fired)
