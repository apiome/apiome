"""Tool / resource / prompt hygiene rules for the MCP lint engine (V2-MCP-21.2).

This is the first concrete *rule pack* that plugs into the deterministic engine in
:mod:`app.mcp_lint`. It adds per-kind hygiene checks over a normalized
:class:`~app.mcp_client.normalize.DiscoverySurface` — does each tool declare a usable
``inputSchema``? do resources carry a valid ``uri`` and a ``mimeType``? do prompt
arguments document themselves? — without touching the engine itself: every rule
registers its ``(category, severity)`` via :func:`~app.mcp_lint.register_rule_metadata`
and appends findings through the shared :func:`~app.mcp_lint.lint_rule` registry, so the
engine's ordering, hashing, and determinism guarantees apply unchanged.

Severity encodes the spec's normative force, so downstream scoring (V2-MCP-21.4) can
weight a hard protocol violation more heavily than a style nit:

* ``error``   — a normative **MUST**: the item is malformed or unusable as specified
  (e.g. a tool whose ``inputSchema`` is absent or is not a ``type: object`` JSON Schema,
  a resource with no valid ``uri``). These break interoperability.
* ``warning`` — a **SHOULD**: a strongly recommended best practice is missing (e.g. a
  tool with no ``description``, a resource with no ``mimeType``, a prompt argument with
  no ``description``). The item still works but is harder to use well.
* ``info``    — an optional, purely advisory signal (e.g. a missing ``title``, a tool
  without an ``outputSchema``, a prompt argument that does not declare ``required``).

Two rule groups (``category``) are introduced here, in addition to the engine's
foundational ``naming``/``structure`` groups:

* ``schema``  — structural correctness of a kind's machine-readable contract: a tool's
  ``inputSchema``, a resource's ``uri``, a resource template's ``uriTemplate``.
* ``quality`` — best-practice descriptive metadata: descriptions, titles, output
  schemas, mime types, and prompt-argument documentation.

References (2025-06-18):
  * tools     — https://modelcontextprotocol.io/specification/2025-06-18/server/tools
  * resources — https://modelcontextprotocol.io/specification/2025-06-18/server/resources
  * prompts   — https://modelcontextprotocol.io/specification/2025-06-18/server/prompts

The module is imported (and therefore self-registers) by :mod:`app.mcp_lint` at load
time, so any caller of :func:`app.mcp_lint.lint_mcp_surface` gets these rules with no
extra wiring.
"""

from __future__ import annotations

from typing import Any, List, Optional
from urllib.parse import urlparse

from jsonschema.exceptions import SchemaError
from jsonschema.validators import Draft202012Validator

from .mcp_client.normalize import CapabilityItem, DiscoverySurface
from .mcp_lint import (
    LintFinding,
    item_path,
    lint_rule,
    make_finding,
    register_rule_metadata,
)

# --- Rule metadata registration -------------------------------------------------------------
# Declared once, centrally, so the engine and every consumer agree on each rule's group and
# weight. ``schema`` rules are MUST violations (error); ``quality`` rules are SHOULD/advisory.

#: Rule id -> (category, severity) for every rule defined in this pack.
HYGIENE_RULES = {
    # schema: structural MUSTs.
    "schema.tool-input-schema-invalid": ("schema", "error"),
    "schema.resource-invalid-uri": ("schema", "error"),
    "schema.resource-template-invalid-uri-template": ("schema", "error"),
    # quality: SHOULD / advisory best practices.
    "quality.tool-missing-description": ("quality", "warning"),
    "quality.tool-missing-output-schema": ("quality", "info"),
    "quality.item-missing-title": ("quality", "info"),
    "quality.resource-missing-mime-type": ("quality", "warning"),
    "quality.resource-template-missing-mime-type": ("quality", "warning"),
    "quality.prompt-argument-missing-description": ("quality", "warning"),
    "quality.prompt-argument-missing-required": ("quality", "info"),
}

for _rule, (_category, _severity) in HYGIENE_RULES.items():
    register_rule_metadata(_rule, _category, _severity)


# --- Structural helpers ---------------------------------------------------------------------
# Each returns a human-readable reason string when the value is defective, or ``None`` when it
# is acceptable. Keeping the predicate logic out of the rule bodies keeps the rules readable and
# lets the reasons be unit-tested directly.

# Sentinel distinguishing "key absent" from "key present but null/non-object" so the input-schema
# rule can give a precise message. (``item.raw.get("inputSchema")`` alone cannot tell the two
# apart, and the normalized ``input_schema`` is ``None`` in both cases.)
_MISSING = object()


def _tool_input_schema_problem(item: CapabilityItem) -> Optional[str]:
    """Return why ``item``'s ``inputSchema`` is unusable, or ``None`` if it is valid.

    Per the tools spec a tool MUST advertise an ``inputSchema`` that is a JSON Schema
    object describing its parameters, and in practice that object MUST declare
    ``"type": "object"`` (tool arguments are always a named-parameter map). This checks,
    in order: the field is present; it is a JSON object; it declares ``type: object``;
    and it is itself a structurally valid JSON Schema (draft 2020-12 meta-schema).

    Args:
        item: A normalized ``tool`` capability item.

    Returns:
        A reason string for the first defect found, or ``None`` when the schema is a
        valid ``type: object`` JSON Schema.
    """
    if item.raw.get("inputSchema", _MISSING) is _MISSING:
        return "inputSchema is absent; a tool MUST declare an inputSchema object."
    schema = item.input_schema
    if schema is None:
        return "inputSchema is not a JSON object."
    declared_type = schema.get("type")
    if declared_type != "object":
        return f"inputSchema must declare type 'object', not {declared_type!r}."
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        return f"inputSchema is not a valid JSON Schema: {exc.message.splitlines()[0]}"
    return None


def _uri_problem(uri: Optional[str]) -> Optional[str]:
    """Return why a resource ``uri`` is invalid, or ``None`` if it is acceptable.

    A concrete resource ``uri`` MUST be an absolute URI — it must carry a scheme (e.g.
    ``file://…``, ``https://…``, or a server-defined custom scheme). A missing or
    scheme-less value cannot be dereferenced.

    Args:
        uri: The resource's normalized ``uri`` (``None`` when absent/blank).

    Returns:
        A reason string, or ``None`` when the uri is a scheme-bearing absolute URI.
    """
    if not uri:
        return "resource has no uri."
    if not urlparse(uri).scheme:
        return f"resource uri '{uri}' is not an absolute URI (missing scheme)."
    return None


def _uri_template_problem(template: Optional[str]) -> Optional[str]:
    """Return why a ``uriTemplate`` is invalid, or ``None`` if it is acceptable.

    A resource template's ``uriTemplate`` MUST be a syntactically valid RFC 6570 URI
    Template. Rather than depend on a full RFC 6570 parser, this performs the structural
    check that matters for hygiene: every ``{`` is matched by a ``}``, expressions are
    neither nested nor empty (``{}``), and there is no unterminated/orphaned brace. A
    template may legitimately omit a literal scheme (the scheme itself can be an
    expression), so — unlike a concrete resource ``uri`` — no scheme is required here.

    Args:
        template: The template's normalized ``uri_template`` (``None`` when absent).

    Returns:
        A reason string, or ``None`` when the template is structurally well-formed.
    """
    if not template:
        return "resource template has no uriTemplate."
    problem = _expression_problem(template)
    if problem is not None:
        return f"uriTemplate '{template}' is malformed: {problem}."
    return None


def _expression_problem(template: str) -> Optional[str]:
    """Scan ``template`` for malformed RFC 6570 ``{…}`` expressions.

    Returns a description of the first structural defect (nested ``{``, empty ``{}``,
    an orphan ``}``, or an unterminated ``{``), or ``None`` if all brace expressions are
    well-formed.
    """
    depth = 0
    expr_start = -1
    for index, char in enumerate(template):
        if char == "{":
            if depth:
                return "nested '{' is not allowed"
            depth = 1
            expr_start = index
        elif char == "}":
            if not depth:
                return "'}' without a matching '{'"
            if index == expr_start + 1:
                return "empty '{}' expression"
            depth = 0
    if depth:
        return "unterminated '{' expression"
    return None


def _is_blank(value: Any) -> bool:
    """Return ``True`` when ``value`` is absent or an empty/whitespace-only string.

    Used by the descriptive-metadata rules: a field that is missing, ``None``, or blank
    carries no information and is treated as not provided.
    """
    return not (isinstance(value, str) and value.strip())


def _argument_key(argument: Any, index: int) -> str:
    """Return the finding-path segment for a prompt ``argument`` at ``index``.

    Uses the argument's ``name`` when present (the stable identifier a client passes),
    falling back to the ordinal (``#<index>``) so the path is always unique and non-empty.
    """
    if isinstance(argument, dict):
        name = argument.get("name")
        if isinstance(name, str) and name:
            return name
    return f"#{index}"


# --- Rules ----------------------------------------------------------------------------------


@lint_rule
def _rule_tool_input_schema(surface: DiscoverySurface, findings: List[LintFinding]) -> None:
    """Flag tools whose ``inputSchema`` is absent or not a valid ``type: object`` schema.

    A normative MUST: clients rely on ``inputSchema`` to construct and validate tool
    calls, so an unusable schema makes the tool uncallable (``error``).
    """
    for tool in surface.tools:
        problem = _tool_input_schema_problem(tool)
        if problem is not None:
            findings.append(
                make_finding(
                    item_path(tool),
                    "schema.tool-input-schema-invalid",
                    f"Tool '{tool.name or tool.ordinal}': {problem}",
                )
            )


@lint_rule
def _rule_tool_missing_description(surface: DiscoverySurface, findings: List[LintFinding]) -> None:
    """Flag tools with no (or blank) ``description``.

    Descriptions are how an agent decides whether and how to call a tool; the spec
    recommends them (SHOULD), so a missing one is a ``warning``.
    """
    for tool in surface.tools:
        if _is_blank(tool.description):
            findings.append(
                make_finding(
                    item_path(tool),
                    "quality.tool-missing-description",
                    f"Tool '{tool.name or tool.ordinal}' has no description.",
                )
            )


@lint_rule
def _rule_tool_missing_output_schema(
    surface: DiscoverySurface, findings: List[LintFinding]
) -> None:
    """Flag tools that declare no ``outputSchema``.

    An ``outputSchema`` lets clients validate and structure a tool's results; it is
    optional (2025-06-18+), so its absence is advisory only (``info``).
    """
    for tool in surface.tools:
        if tool.output_schema is None:
            findings.append(
                make_finding(
                    item_path(tool),
                    "quality.tool-missing-output-schema",
                    f"Tool '{tool.name or tool.ordinal}' declares no outputSchema.",
                )
            )


@lint_rule
def _rule_item_missing_title(surface: DiscoverySurface, findings: List[LintFinding]) -> None:
    """Flag any capability item (tool/resource/template/prompt) with no ``title``.

    ``title`` is the optional human-facing display label (2025-06-18+). A single
    kind-agnostic rule mirrors the engine's foundational ``naming.item-name-missing``
    check; absence is advisory (``info``) and is expected on pre-2025-06-18 servers,
    which omit ``title`` entirely.
    """
    for item in surface.all_items():
        if _is_blank(item.title):
            findings.append(
                make_finding(
                    item_path(item),
                    "quality.item-missing-title",
                    f"{item.item_type} '{item.name or item.ordinal}' has no title.",
                )
            )


@lint_rule
def _rule_resource_uri(surface: DiscoverySurface, findings: List[LintFinding]) -> None:
    """Flag resources whose concrete ``uri`` is missing or not an absolute URI (MUST)."""
    for resource in surface.resources:
        problem = _uri_problem(resource.uri)
        if problem is not None:
            findings.append(
                make_finding(
                    item_path(resource),
                    "schema.resource-invalid-uri",
                    f"Resource '{resource.name or resource.ordinal}': {problem}",
                )
            )


@lint_rule
def _rule_resource_template_uri(
    surface: DiscoverySurface, findings: List[LintFinding]
) -> None:
    """Flag resource templates whose ``uriTemplate`` is missing or malformed (MUST)."""
    for template in surface.resource_templates:
        problem = _uri_template_problem(template.uri_template)
        if problem is not None:
            findings.append(
                make_finding(
                    item_path(template),
                    "schema.resource-template-invalid-uri-template",
                    f"Resource template '{template.name or template.ordinal}': {problem}",
                )
            )


@lint_rule
def _rule_resource_mime_type(surface: DiscoverySurface, findings: List[LintFinding]) -> None:
    """Flag resources that advertise no ``mimeType``.

    ``mimeType`` tells clients how to interpret the resource's contents; it is
    recommended (SHOULD), so its absence is a ``warning``. ``mimeType`` has no promoted
    column, so it is read from the verbatim wire entry.
    """
    for resource in surface.resources:
        if _is_blank(resource.raw.get("mimeType")):
            findings.append(
                make_finding(
                    item_path(resource),
                    "quality.resource-missing-mime-type",
                    f"Resource '{resource.name or resource.ordinal}' has no mimeType.",
                )
            )


@lint_rule
def _rule_resource_template_mime_type(
    surface: DiscoverySurface, findings: List[LintFinding]
) -> None:
    """Flag resource templates that advertise no ``mimeType`` (SHOULD, ``warning``)."""
    for template in surface.resource_templates:
        if _is_blank(template.raw.get("mimeType")):
            findings.append(
                make_finding(
                    item_path(template),
                    "quality.resource-template-missing-mime-type",
                    f"Resource template '{template.name or template.ordinal}' has no mimeType.",
                )
            )


@lint_rule
def _rule_prompt_arguments(surface: DiscoverySurface, findings: List[LintFinding]) -> None:
    """Flag prompt arguments that omit a ``description`` (SHOULD) or ``required`` (advisory).

    A prompt's ``arguments`` have no promoted column and are read from the verbatim wire
    entry. Each argument is checked independently and produces findings anchored at
    ``<prompt path>.arguments.<arg>``:

    * a missing/blank ``description`` is a ``warning`` (clients show it to users);
    * an absent ``required`` field is ``info`` (it defaults to optional, but declaring it
      explicitly removes ambiguity).

    Non-list ``arguments`` (or non-object entries) are ignored here; malformedness of the
    prompt envelope itself is out of scope for these per-argument checks.
    """
    for prompt in surface.prompts:
        arguments = prompt.raw.get("arguments")
        if not isinstance(arguments, list):
            continue
        for index, argument in enumerate(arguments):
            if not isinstance(argument, dict):
                continue
            base = f"{item_path(prompt)}.arguments.{_argument_key(argument, index)}"
            if _is_blank(argument.get("description")):
                findings.append(
                    make_finding(
                        base,
                        "quality.prompt-argument-missing-description",
                        f"Prompt '{prompt.name or prompt.ordinal}' argument "
                        f"'{_argument_key(argument, index)}' has no description.",
                    )
                )
            if "required" not in argument:
                findings.append(
                    make_finding(
                        base,
                        "quality.prompt-argument-missing-required",
                        f"Prompt '{prompt.name or prompt.ordinal}' argument "
                        f"'{_argument_key(argument, index)}' does not declare 'required'.",
                    )
                )
