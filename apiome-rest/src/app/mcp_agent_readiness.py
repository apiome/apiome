"""Agent-readiness rule pack for the MCP conformance engine (CLX-3.1, #4855).

The second pack plugging into :mod:`app.mcp_conformance`. Where
:mod:`app.mcp_conformance_rules` asks "did the server behave like an MCP server?", this pack
asks the question a *model* has to answer: **can an agent actually pick this tool, call it
correctly, and recover when it fails?**

A tool can be perfectly conformant and still be unusable. A tool named ``run`` with the
description ``"Runs it."``, a free-text ``mode`` parameter with no enum, no output schema, and
no destructive-operation annotation is, from an agent's point of view, a coin flip: it cannot
tell when to select the tool, what to pass, what it will get back, or whether calling it is
safe to retry. Every rule here targets one of those failure modes.

Relationship to ToolBench
-------------------------

The public tool-definition-quality literature — ToolBench's published evaluation categories,
and Anthropic's tool-authoring guidance — converges on the same short list of properties that
make a tool usable by a model: substantive descriptions, documented and *constrained*
parameters, a declared output shape, guidance for the failure path, bounded (paginated) result
sets, explicitly declared destructive operations, consistent naming, and behavioural
annotations.

Those *concepts* are what this pack encodes. What it deliberately does **not** do is reproduce
any third-party score: nothing is copied, imported, or numerically approximated, and there is
no opaque composite hiding a judgement. Each rule is an independent, transparent Apiome rule
that states its own threshold as a named constant and its own rationale in its descriptor, and
each finding names the exact tool and parameter it refers to. A team that disagrees with a
threshold can see it, cite it, and gate around it — which is the entire point of preferring
transparent rules to a borrowed score.

Severity reflects how badly the gap degrades an agent's behaviour, not how offended a
specification would be — nothing here is a protocol violation, so nothing here is an ``error``:

* ``warning`` — the agent will predictably misuse the tool (an undocumented parameter, an
  undeclared destructive operation, an unbounded list, a description too thin to select on).
* ``info``    — the agent is working with less than it could (no output schema, no recovery
  guidance, no annotations, an unconventional name).

References:
  * tools           — https://modelcontextprotocol.io/specification/2025-06-18/server/tools
  * tool authoring  — https://www.anthropic.com/engineering/writing-tools-for-agents

The module self-registers on import from :mod:`app.mcp_conformance`.
"""

from __future__ import annotations

import re
from typing import Any, List, Mapping, Optional, Tuple

from .mcp_client.normalize import CapabilityItem
from .mcp_conformance import (
    CATEGORY_READINESS,
    MCP_SPEC_VERSION,
    REFERENCE_TOOL_AUTHORING,
    SPEC_TOOLS,
    ConformanceContext,
    ConformanceFinding,
    ConformanceRule,
    conformance_rule,
    make_finding,
    register_rules,
)
from .mcp_lint import item_path

# --- Published thresholds ----------------------------------------------------------------------
# Every threshold this pack applies is a named constant with a stated reason, so a finding is
# always explainable and arguable rather than the output of a hidden model.

#: Minimum tool-description length (characters) an agent can realistically select on. A
#: description shorter than this is, in practice, a restatement of the tool's name ("Get user.")
#: and gives a model nothing to disambiguate it from a sibling tool. Chosen as roughly one
#: informative clause; it is a floor for *presence of content*, not a style rule.
MIN_TOOL_DESCRIPTION_CHARS = 40

#: Minimum parameter-description length. Parameters need less prose than tools, but a one-word
#: description ("The id.") tells a model nothing about format, source, or constraints.
MIN_PARAM_DESCRIPTION_CHARS = 12

#: JSON Schema keywords that meaningfully constrain a value, so a model can generate a valid
#: argument instead of guessing. A property carrying none of these — and not being an
#: enumeration, a reference, or a composed schema — is unconstrained free text.
CONSTRAINT_KEYWORDS: frozenset = frozenset(
    {
        "enum",
        "const",
        "pattern",
        "format",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "items",
        "properties",
        "oneOf",
        "anyOf",
        "allOf",
        "$ref",
    }
)

#: Scalar JSON Schema types whose values a model must synthesize, and which therefore benefit
#: from a constraint. Booleans and nulls are inherently constrained and are never flagged.
CONSTRAINABLE_TYPES: frozenset = frozenset({"string", "number", "integer", "array"})

#: Tokens in a tool's name or description implying it returns a *collection*. Such a tool needs
#: a way to bound its result set, or a large backing store floods the model's context window.
COLLECTION_TOKENS: Tuple[str, ...] = (
    "list",
    "search",
    "query",
    "find",
    "browse",
    "fetch all",
    "get all",
    "enumerate",
    "all ",
)

#: Parameter names (normalized) that bound a result set. Any one of these satisfies the
#: bounded-list rule; a tool needs only one way to say "give me less".
BOUNDING_PARAMS: frozenset = frozenset(
    {
        "limit",
        "max",
        "maxresults",
        "maxitems",
        "count",
        "top",
        "size",
        "pagesize",
        "perpage",
        "page",
        "offset",
        "cursor",
        "after",
        "before",
        "start",
        "first",
    }
)

#: Tokens implying a tool performs an irreversible, state-destroying operation. A tool matching
#: one of these MUST declare its ``destructiveHint`` so a host can decide whether to require
#: confirmation rather than auto-approving the call.
DESTRUCTIVE_TOKENS: Tuple[str, ...] = (
    "delete",
    "remove",
    "drop",
    "purge",
    "truncate",
    "destroy",
    "erase",
    "wipe",
    "revoke",
    "terminate",
    "uninstall",
)

#: Tokens indicating a description tells the agent what happens when the call *fails* — the
#: recovery path. A model that knows the failure modes retries intelligently instead of
#: abandoning the task or looping.
RECOVERY_TOKENS: Tuple[str, ...] = (
    "error",
    "fail",
    "invalid",
    "not found",
    "missing",
    "retry",
    "raise",
    "throw",
    "exception",
    "empty",
    "null",
    "if no",
    "when no",
    "otherwise",
)

#: Naming conventions a tool name may follow. A name matching none of them (a space, a leading
#: digit, mixed separators) is hard for a model to recall and reproduce exactly.
NAMING_CONVENTIONS: Mapping[str, re.Pattern] = {
    "snake_case": re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$"),
    "camelCase": re.compile(r"^[a-z][a-zA-Z0-9]*$"),
    "kebab-case": re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$"),
    "dotted.case": re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9]+)*$"),
}


# --- Rule descriptors ---------------------------------------------------------------------------


def _rule(
    rule_id: str,
    severity: str,
    rationale: str,
    *,
    reference: str = REFERENCE_TOOL_AUTHORING,
) -> ConformanceRule:
    """Build one readiness-category descriptor.

    Readiness rules are surface-derived without exception — every one reads only the persisted
    tool definitions — so none requires a transcript and all are deterministic.
    """
    return ConformanceRule(
        rule_id=rule_id,
        category=CATEGORY_READINESS,
        severity=severity,
        spec_version=MCP_SPEC_VERSION,
        spec_reference=reference,
        rationale=rationale,
        requires_transcript=False,
    )


READINESS_RULES: Tuple[ConformanceRule, ...] = (
    _rule(
        "readiness.tool-description-too-brief",
        "warning",
        f"A description under {MIN_TOOL_DESCRIPTION_CHARS} characters cannot distinguish a "
        f"tool from its siblings, so an agent selects it by name alone.",
        reference=SPEC_TOOLS,
    ),
    _rule(
        "readiness.tool-parameter-missing-description",
        "warning",
        "An undocumented parameter forces an agent to infer its meaning from its name.",
        reference=SPEC_TOOLS,
    ),
    _rule(
        "readiness.tool-parameter-unconstrained",
        "info",
        "A free-text parameter with no enum, format, pattern, or bounds invites invalid "
        "arguments an agent cannot self-check.",
        reference=SPEC_TOOLS,
    ),
    _rule(
        "readiness.tool-missing-output-schema",
        "info",
        "Without an outputSchema an agent cannot predict or validate a tool's result shape.",
        reference=SPEC_TOOLS,
    ),
    _rule(
        "readiness.tool-missing-recovery-guidance",
        "info",
        "A description that never mentions the failure path leaves an agent with no recovery "
        "strategy when the call errors.",
    ),
    _rule(
        "readiness.tool-unbounded-list",
        "warning",
        "A collection-returning tool with no limit/cursor parameter can flood an agent's "
        "context with an unbounded result set.",
    ),
    _rule(
        "readiness.tool-destructive-not-declared",
        "warning",
        "A destructive operation that does not declare destructiveHint may be auto-approved "
        "by a host that would otherwise have demanded confirmation.",
        reference=SPEC_TOOLS,
    ),
    _rule(
        "readiness.tool-missing-annotations",
        "info",
        "Without behavioural annotations a host cannot reason about a tool's safety at all.",
        reference=SPEC_TOOLS,
    ),
    _rule(
        "readiness.tool-name-unconventional",
        "info",
        "A name matching no common convention is hard for a model to reproduce exactly.",
    ),
    _rule(
        "readiness.tool-naming-inconsistent",
        "info",
        "Mixed naming conventions across one server's tools make every name a guess.",
    ),
)

register_rules(READINESS_RULES)


# --- Helpers --------------------------------------------------------------------------------------


def _is_blank(value: Any) -> bool:
    """True when ``value`` is absent or an empty/whitespace-only string."""
    return not (isinstance(value, str) and value.strip())


def _text(value: Any) -> str:
    """Return ``value`` as stripped text, or ``""`` when it is not a usable string."""
    return value.strip() if isinstance(value, str) else ""


def _tool_label(tool: CapabilityItem) -> str:
    """Human label for a tool in a message — its name, or its ordinal when unnamed."""
    return str(tool.name or tool.ordinal)


def _properties(tool: CapabilityItem) -> Mapping[str, Any]:
    """Return a tool's top-level ``inputSchema.properties`` map, or ``{}`` when it has none.

    Only top-level properties are inspected. They are the named arguments a caller actually
    fills in, and keeping the walk shallow keeps every finding directly actionable — a finding
    about a deeply nested sub-property of a composed schema is rarely something a tool author
    can act on from the message alone.
    """
    schema = tool.input_schema
    if not isinstance(schema, Mapping):
        return {}
    properties = schema.get("properties")
    return properties if isinstance(properties, Mapping) else {}


def _normalize_name(name: str) -> str:
    """Lowercase ``name`` and strip non-alphanumerics, for tolerant parameter-name matching.

    Collapses ``page_size``/``pageSize``/``page-size`` onto one comparable token so all three
    spellings satisfy the bounded-list rule.
    """
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _mentions_any(text: str, tokens: Tuple[str, ...]) -> bool:
    """True when ``text`` (case-insensitively) contains any of ``tokens``."""
    lowered = text.lower()
    return any(token in lowered for token in tokens)


def _unconstrained_reason(schema: Any) -> Optional[str]:
    """Return why a parameter ``schema`` is unconstrained, or ``None`` when it is constrained.

    A property is considered constrained when it carries any keyword in
    :data:`CONSTRAINT_KEYWORDS` — an enum, a format, a pattern, numeric bounds, an item schema,
    a ``$ref``, or a composition. Only :data:`CONSTRAINABLE_TYPES` are judged: a boolean has
    exactly two valid values already, and a typeless schema is too vague to have an opinion
    about here.

    Args:
        schema: The property's JSON Schema.

    Returns:
        A reason string, or ``None`` when the property is adequately constrained or out of
        scope for this rule.
    """
    if not isinstance(schema, Mapping):
        return None
    declared_type = schema.get("type")
    if not isinstance(declared_type, str) or declared_type not in CONSTRAINABLE_TYPES:
        return None
    if any(keyword in schema for keyword in CONSTRAINT_KEYWORDS):
        return None
    return f"'{declared_type}' parameter declares no enum, format, pattern, or bounds"


def _naming_convention(name: str) -> Optional[str]:
    """Return the naming convention ``name`` follows, or ``None`` when it follows none.

    Checked in :data:`NAMING_CONVENTIONS` order. A single-word lowercase name (``search``)
    legitimately matches several conventions at once; the first match wins, which keeps the
    consistency rule below from reading a one-word name as evidence of a mixed convention.
    """
    for convention, pattern in NAMING_CONVENTIONS.items():
        if pattern.match(name):
            return convention
    return None


# --- Rules ------------------------------------------------------------------------------------------


@conformance_rule()
def _rule_tool_description(
    context: ConformanceContext, findings: List[ConformanceFinding]
) -> None:
    """Flag tools whose description is too thin for an agent to select on.

    An absent description and a two-word one fail for the same reason — the model has nothing
    to go on — so both are reported through this one rule, with the message distinguishing
    them. The threshold is :data:`MIN_TOOL_DESCRIPTION_CHARS`, stated as a constant so it can
    be cited and argued with.
    """
    for tool in context.surface.tools:
        description = _text(tool.description)
        if not description:
            findings.append(
                make_finding(
                    item_path(tool),
                    "readiness.tool-description-too-brief",
                    f"Tool '{_tool_label(tool)}' has no description, so an agent can only "
                    f"select it by name.",
                )
            )
        elif len(description) < MIN_TOOL_DESCRIPTION_CHARS:
            findings.append(
                make_finding(
                    item_path(tool),
                    "readiness.tool-description-too-brief",
                    f"Tool '{_tool_label(tool)}' has a {len(description)}-character "
                    f"description; at least {MIN_TOOL_DESCRIPTION_CHARS} are needed to "
                    f"distinguish it from a sibling tool.",
                )
            )


@conformance_rule()
def _rule_tool_parameters(
    context: ConformanceContext, findings: List[ConformanceFinding]
) -> None:
    """Flag input parameters that are undocumented or unconstrained.

    Both checks live in one function because both walk the same ``inputSchema.properties`` map,
    and each parameter is judged independently:

    * **Undocumented** (``warning``) — no description, or one under
      :data:`MIN_PARAM_DESCRIPTION_CHARS`. The agent has to infer the parameter's meaning from
      its name, which is how tools get called with a display name where they wanted an id.
    * **Unconstrained** (``info``) — a scalar/array parameter with no enum, format, pattern, or
      bounds (see :func:`_unconstrained_reason`). The agent cannot check its own argument
      before spending a call to discover it was invalid.

    Findings are anchored at ``<tool path>.inputSchema.<param>`` so each parameter is
    independently addressable, and parameters are walked in sorted order for determinism.
    """
    for tool in context.surface.tools:
        properties = _properties(tool)
        for param in sorted(str(name) for name in properties):
            schema = properties[param]
            path = f"{item_path(tool)}.inputSchema.{param}"

            description = _text(schema.get("description")) if isinstance(schema, Mapping) else ""
            if len(description) < MIN_PARAM_DESCRIPTION_CHARS:
                detail = (
                    "has no description"
                    if not description
                    else f"has only a {len(description)}-character description"
                )
                findings.append(
                    make_finding(
                        path,
                        "readiness.tool-parameter-missing-description",
                        f"Tool '{_tool_label(tool)}' parameter '{param}' {detail}; an agent "
                        f"must infer its meaning from its name.",
                    )
                )

            reason = _unconstrained_reason(schema)
            if reason is not None:
                findings.append(
                    make_finding(
                        path,
                        "readiness.tool-parameter-unconstrained",
                        f"Tool '{_tool_label(tool)}' parameter '{param}': {reason}, so an "
                        f"agent cannot validate its own argument before calling.",
                    )
                )


@conformance_rule()
def _rule_tool_output_schema(
    context: ConformanceContext, findings: List[ConformanceFinding]
) -> None:
    """Flag tools that declare no ``outputSchema``.

    Without one, an agent cannot predict a result's shape and must parse whatever comes back —
    so it cannot plan a second call on the first call's output without seeing it first.
    Advisory (``info``): ``outputSchema`` is optional in the specification, and a
    pre-2025-06-18 server cannot express one at all.
    """
    for tool in context.surface.tools:
        if tool.output_schema is None:
            findings.append(
                make_finding(
                    item_path(tool),
                    "readiness.tool-missing-output-schema",
                    f"Tool '{_tool_label(tool)}' declares no outputSchema, so an agent cannot "
                    f"predict or validate its result shape.",
                )
            )


@conformance_rule()
def _rule_tool_recovery_guidance(
    context: ConformanceContext, findings: List[ConformanceFinding]
) -> None:
    """Flag tools whose description never addresses the failure path.

    A model that knows *how* a tool fails ("returns an empty list when no match is found";
    "errors if the id does not exist") can recover; one that does not either abandons the task
    or retries the same failing call. The check is a transparent keyword test over the
    description against :data:`RECOVERY_TOKENS` — deliberately a coarse, explainable heuristic
    rather than a hidden judgement, which is why it is only ``info``.

    Tools with no usable description at all are skipped: they are already reported by
    :func:`_rule_tool_description`, and saying "your absent description lacks error guidance"
    adds a second finding for one defect.
    """
    for tool in context.surface.tools:
        description = _text(tool.description)
        if not description:
            continue
        if not _mentions_any(description, RECOVERY_TOKENS):
            findings.append(
                make_finding(
                    item_path(tool),
                    "readiness.tool-missing-recovery-guidance",
                    f"Tool '{_tool_label(tool)}' never describes what happens when it fails "
                    f"or returns nothing, so an agent has no recovery strategy.",
                )
            )


@conformance_rule()
def _rule_tool_bounded_list(
    context: ConformanceContext, findings: List[ConformanceFinding]
) -> None:
    """Flag collection-returning tools that offer no way to bound the result set.

    A tool whose name or description says it lists, searches, or queries — see
    :data:`COLLECTION_TOKENS` — is expected to return many rows. Unless it accepts at least one
    bounding parameter (:data:`BOUNDING_PARAMS`: a ``limit``, a ``cursor``, a ``page``…), the
    only possible result is *everything*, which floods the agent's context window and is the
    single most common way an otherwise-correct MCP server becomes unusable at scale.

    The rule reads the tool's *declared* parameters only; it never calls the tool.
    """
    for tool in context.surface.tools:
        haystack = f"{_text(tool.name)} {_text(tool.description)}"
        if not _mentions_any(haystack, COLLECTION_TOKENS):
            continue
        parameters = {_normalize_name(str(name)) for name in _properties(tool)}
        if parameters & BOUNDING_PARAMS:
            continue
        findings.append(
            make_finding(
                item_path(tool),
                "readiness.tool-unbounded-list",
                f"Tool '{_tool_label(tool)}' returns a collection but accepts no bounding "
                f"parameter (e.g. limit, page, or cursor), so its result set is unbounded.",
            )
        )


@conformance_rule()
def _rule_tool_destructive_declaration(
    context: ConformanceContext, findings: List[ConformanceFinding]
) -> None:
    """Flag apparently destructive tools that do not declare ``destructiveHint``.

    A host uses ``destructiveHint`` to decide whether a call may be auto-approved or must be
    confirmed by a human. A tool called ``delete_account`` that declares nothing is, to the
    host, indistinguishable from a read — so the safeguard silently does not apply. That is the
    highest-consequence gap this pack can detect from the surface alone, hence ``warning``
    rather than ``info``.

    Detection is a transparent keyword test over the tool's name and description
    (:data:`DESTRUCTIVE_TOKENS`). A tool that declares ``destructiveHint`` — with *either*
    boolean value — has made an explicit assertion and is never flagged: the rule demands a
    declaration, not a particular answer. A tool asserting ``readOnlyHint: true`` has likewise
    declared its nature (and any contradiction with a destructive name is a separate concern of
    the surface linter's annotation pack), so it is also left alone.
    """
    for tool in context.surface.tools:
        haystack = f"{_text(tool.name)} {_text(tool.description)}"
        if not _mentions_any(haystack, DESTRUCTIVE_TOKENS):
            continue
        annotations = tool.annotations if isinstance(tool.annotations, Mapping) else {}
        if "destructiveHint" in annotations:
            continue
        if annotations.get("readOnlyHint") is True:
            continue
        findings.append(
            make_finding(
                item_path(tool),
                "readiness.tool-destructive-not-declared",
                f"Tool '{_tool_label(tool)}' appears to perform a destructive operation but "
                f"declares no destructiveHint, so a host may auto-approve it without "
                f"confirmation.",
            )
        )


@conformance_rule()
def _rule_tool_annotations_present(
    context: ConformanceContext, findings: List[ConformanceFinding]
) -> None:
    """Flag tools that carry no behavioural annotations at all.

    With no ``annotations`` object a host has *no* basis on which to reason about the tool's
    safety — not whether it reads or writes, not whether it is idempotent, not whether it
    touches the outside world — and must therefore treat it with maximum suspicion (or, worse,
    with none). Annotations are optional in the specification, so this is ``info``; the
    higher-consequence special case of an undeclared *destructive* tool is raised separately as
    a ``warning`` by :func:`_rule_tool_destructive_declaration`.
    """
    for tool in context.surface.tools:
        annotations = tool.annotations
        if not isinstance(annotations, Mapping) or not annotations:
            findings.append(
                make_finding(
                    item_path(tool),
                    "readiness.tool-missing-annotations",
                    f"Tool '{_tool_label(tool)}' declares no annotations, so a host cannot "
                    f"reason about whether calling it is safe.",
                )
            )


@conformance_rule()
def _rule_tool_naming(
    context: ConformanceContext, findings: List[ConformanceFinding]
) -> None:
    """Judge tool naming: each name individually, and the surface's consistency as a whole.

    * **Unconventional name** (``info``) — a name matching none of :data:`NAMING_CONVENTIONS`
      (it contains a space, starts with a digit, mixes separators…). A model reproduces such a
      name from memory unreliably, and an invalid name is a call that never reaches the server.
    * **Inconsistent naming** (``info``) — the server's tools follow more than one convention
      (``get_user`` beside ``createUser``). Each name is individually fine; together they mean
      an agent cannot generalize the pattern and must recall every name exactly. Reported once
      at the surface level, listing the conventions found in sorted order.

    Names that are ambiguous by construction — a single lowercase word like ``search`` matches
    several conventions at once — resolve to the first matching convention and so never, on
    their own, make a surface look inconsistent.
    """
    conventions: set = set()
    for tool in context.surface.tools:
        name = _text(tool.name)
        if not name:
            continue  # an unnamed tool is the surface linter's error, not a naming style issue
        convention = _naming_convention(name)
        if convention is None:
            findings.append(
                make_finding(
                    item_path(tool),
                    "readiness.tool-name-unconventional",
                    f"Tool name '{name}' follows no common convention "
                    f"({', '.join(NAMING_CONVENTIONS)}), so an agent may reproduce it "
                    f"incorrectly.",
                )
            )
        else:
            conventions.add(convention)

    if len(conventions) > 1:
        findings.append(
            make_finding(
                "surface.tools",
                "readiness.tool-naming-inconsistent",
                f"Tool names mix {len(conventions)} naming conventions "
                f"({', '.join(sorted(conventions))}); a single convention lets an agent "
                f"generalize rather than memorize.",
            )
        )
