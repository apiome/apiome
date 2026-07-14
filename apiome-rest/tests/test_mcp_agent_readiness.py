"""Unit tests for the agent-readiness rule pack (CLX-3.1, #4855).

These exercise :mod:`app.mcp_agent_readiness` — "can an agent actually pick this tool, call it
correctly, and recover when it fails?" — over hand-built tool definitions.

The pack encodes published tool-definition-quality *concepts* (ToolBench's evaluation categories,
Anthropic's tool-authoring guidance) as transparent Apiome rules with their own stated thresholds.
The tests assert both directions for each rule: the defect fires, and a well-authored tool does
NOT — a rule that flagged everything would be as useless as one that flagged nothing.
"""

from __future__ import annotations

from app.mcp_agent_readiness import (
    MIN_PARAM_DESCRIPTION_CHARS,
    MIN_TOOL_DESCRIPTION_CHARS,
)
from app.mcp_client.handshake import ServerInfo
from app.mcp_client.normalize import ITEM_TYPE_TOOL, CapabilityItem, DiscoverySurface
from app.mcp_conformance import PROFILE_READINESS, ConformanceContext, run_conformance

#: A description long enough to clear the threshold and mention the failure path.
GOOD_DESCRIPTION = (
    "Search the item catalog by keyword and return matching items; "
    "returns an empty list when nothing matches."
)


def _tool(name: str = "search_items", ordinal: int = 0, **overrides) -> CapabilityItem:
    """A fully agent-ready tool; each test overrides only the facet it is about."""
    attrs = {
        "description": GOOD_DESCRIPTION,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The keyword to search the catalog for.",
                    "minLength": 1,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of items to return.",
                    "minimum": 1,
                    "maximum": 100,
                },
            },
        },
        "output_schema": {"type": "object", "properties": {"items": {"type": "array"}}},
        "annotations": {"readOnlyHint": True},
    }
    attrs.update(overrides)
    return CapabilityItem(item_type=ITEM_TYPE_TOOL, name=name, ordinal=ordinal, **attrs)


def _rules(*tools) -> set:
    """Run the agent-readiness profile over ``tools`` and return the rule ids reported."""
    surface = DiscoverySurface(
        protocol_version="2025-06-18",
        server_info=ServerInfo(name="demo", version="1.0.0"),
        capabilities={"tools": {}},
        tools=tuple(tools),
    )
    report = run_conformance(ConformanceContext(surface=surface), profile=PROFILE_READINESS)
    return {finding.rule for finding in report.findings}


# --- Baseline -------------------------------------------------------------------------------------


def test_a_well_authored_tool_reports_nothing():
    """The baseline is genuinely clean, so every test below isolates its own defect.

    This also guards against the pack becoming noise: if a good tool started tripping rules, the
    findings would be ignored wholesale and the pack would be worse than useless.
    """
    assert _rules(_tool()) == set()


# --- Descriptions ----------------------------------------------------------------------------------


def test_missing_description_is_flagged():
    """With no description an agent can only select the tool by name."""
    assert "readiness.tool-description-too-brief" in _rules(_tool(description=None))


def test_description_below_the_threshold_is_flagged():
    """A too-thin description cannot distinguish a tool from its siblings."""
    brief = "Gets it."
    assert len(brief) < MIN_TOOL_DESCRIPTION_CHARS
    assert "readiness.tool-description-too-brief" in _rules(_tool(description=brief))


def test_description_at_the_threshold_is_accepted():
    """The threshold is a published constant, and a description meeting it passes."""
    at_threshold = "x" * MIN_TOOL_DESCRIPTION_CHARS + " returns empty if not found"
    assert "readiness.tool-description-too-brief" not in _rules(_tool(description=at_threshold))


# --- Recovery guidance -----------------------------------------------------------------------------


def test_description_without_failure_guidance_is_flagged():
    """A description that never addresses failure leaves an agent with no recovery strategy."""
    no_recovery = "Searches the catalog of items and returns every matching item to the caller."
    assert len(no_recovery) >= MIN_TOOL_DESCRIPTION_CHARS  # long enough; only guidance is missing
    assert "readiness.tool-missing-recovery-guidance" in _rules(_tool(description=no_recovery))


def test_description_mentioning_the_failure_path_is_accepted():
    """Naming the failure mode ('returns an empty list when…') satisfies the rule."""
    assert "readiness.tool-missing-recovery-guidance" not in _rules(_tool())


def test_a_tool_with_no_description_is_not_double_reported():
    """An absent description is one defect, not two — the recovery rule skips it.

    Reporting 'your absent description lacks error guidance' alongside 'you have no description'
    would inflate the finding count for a single fix.
    """
    found = _rules(_tool(description=None))
    assert "readiness.tool-description-too-brief" in found
    assert "readiness.tool-missing-recovery-guidance" not in found


# --- Parameters -------------------------------------------------------------------------------------


def test_undocumented_parameter_is_flagged():
    """An undocumented parameter forces an agent to infer meaning from the name alone."""
    schema = {"type": "object", "properties": {"q": {"type": "string", "minLength": 1}}}
    assert "readiness.tool-parameter-missing-description" in _rules(_tool(input_schema=schema))


def test_parameter_description_below_the_threshold_is_flagged():
    """A one-word parameter description conveys no format, source, or constraint."""
    terse = "The id."
    assert len(terse) < MIN_PARAM_DESCRIPTION_CHARS
    schema = {
        "type": "object",
        "properties": {"id": {"type": "string", "description": terse, "pattern": "^[0-9]+$"}},
    }
    assert "readiness.tool-parameter-missing-description" in _rules(_tool(input_schema=schema))


def test_unconstrained_parameter_is_flagged():
    """A free-text parameter with no enum/format/pattern/bounds invites invalid arguments."""
    schema = {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "description": "The mode to operate the tool in."}
        },
    }
    assert "readiness.tool-parameter-unconstrained" in _rules(_tool(input_schema=schema))


def test_enum_constrained_parameter_is_accepted():
    """An enum tells the model exactly which values are legal, so it is not flagged."""
    schema = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "description": "The mode to operate the tool in.",
                "enum": ["fast", "thorough"],
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of items to return.",
                "maximum": 50,
            },
        },
    }
    assert "readiness.tool-parameter-unconstrained" not in _rules(_tool(input_schema=schema))


def test_boolean_parameter_is_never_flagged_as_unconstrained():
    """A boolean already has exactly two legal values; demanding a constraint would be noise."""
    schema = {
        "type": "object",
        "properties": {
            "verbose": {"type": "boolean", "description": "Whether to include full detail."},
            "limit": {
                "type": "integer",
                "description": "Maximum number of items to return.",
                "maximum": 10,
            },
        },
    }
    assert "readiness.tool-parameter-unconstrained" not in _rules(_tool(input_schema=schema))


# --- Output schema -----------------------------------------------------------------------------------


def test_missing_output_schema_is_flagged():
    """Without an outputSchema an agent cannot predict or validate the result shape."""
    assert "readiness.tool-missing-output-schema" in _rules(_tool(output_schema=None))


# --- Bounded lists -------------------------------------------------------------------------------------


def test_collection_tool_without_a_bounding_parameter_is_flagged():
    """A search tool with no limit/cursor can only return everything, flooding the context."""
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The keyword to search for.", "minLength": 1}
        },
    }
    assert "readiness.tool-unbounded-list" in _rules(_tool(input_schema=schema))


def test_collection_tool_with_a_cursor_is_accepted():
    """Any one bounding parameter satisfies the rule — a cursor is as good as a limit."""
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The keyword to search for.", "minLength": 1},
            "cursor": {
                "type": "string",
                "description": "Opaque cursor for the next page of results.",
                "minLength": 1,
            },
        },
    }
    assert "readiness.tool-unbounded-list" not in _rules(_tool(input_schema=schema))


def test_page_size_spelling_variants_all_satisfy_the_rule():
    """pageSize / page_size / per_page normalize to the same bounding parameter."""
    for spelling in ("pageSize", "page_size", "per_page", "maxResults"):
        schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The keyword to search for.",
                    "minLength": 1,
                },
                spelling: {
                    "type": "integer",
                    "description": "How many results to return at most.",
                    "maximum": 100,
                },
            },
        }
        assert "readiness.tool-unbounded-list" not in _rules(_tool(input_schema=schema)), spelling


def test_non_collection_tool_is_not_required_to_paginate():
    """A single-record tool returns one thing, so demanding a limit would be noise."""
    non_collection = _tool(
        name="get_user",
        description="Fetch one user by id; errors when the id does not exist.",
        input_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "The user's id.", "pattern": "^u[0-9]+$"}
            },
        },
    )
    assert "readiness.tool-unbounded-list" not in _rules(non_collection)


# --- Destructive operations ---------------------------------------------------------------------------


def test_destructive_tool_without_a_destructive_hint_is_flagged():
    """An undeclared destructive tool may be auto-approved by a host that would have asked first.

    This is the highest-consequence gap detectable from the surface alone, hence a ``warning``.
    """
    dangerous = _tool(
        name="delete_user",
        description="Permanently delete a user account; errors when the id does not exist.",
        input_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "The user's id.", "pattern": "^u[0-9]+$"}
            },
        },
        annotations={},
    )
    assert "readiness.tool-destructive-not-declared" in _rules(dangerous)


def test_declaring_destructive_hint_false_still_satisfies_the_rule():
    """The rule demands a *declaration*, not a particular answer.

    A tool that asserts ``destructiveHint: false`` has made an explicit, auditable claim about
    itself. Forcing it to say ``true`` would be the lint dictating behaviour rather than
    demanding disclosure.
    """
    declared = _tool(
        name="delete_draft",
        description="Delete a draft; returns an error when the draft does not exist.",
        input_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "The draft's id.", "pattern": "^d[0-9]+$"}
            },
        },
        annotations={"destructiveHint": False},
    )
    assert "readiness.tool-destructive-not-declared" not in _rules(declared)


def test_read_only_tool_with_a_destructive_sounding_name_is_not_flagged():
    """A tool asserting readOnlyHint has already declared its nature."""
    read_only = _tool(
        name="find_deleted_items",
        description="List items that were deleted; returns an empty list when none were.",
        input_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of items to return.",
                    "maximum": 50,
                }
            },
        },
        annotations={"readOnlyHint": True},
    )
    assert "readiness.tool-destructive-not-declared" not in _rules(read_only)


# --- Annotations ----------------------------------------------------------------------------------------


def test_tool_with_no_annotations_is_flagged():
    """With no annotations a host has no basis at all on which to reason about safety."""
    assert "readiness.tool-missing-annotations" in _rules(_tool(annotations=None))
    assert "readiness.tool-missing-annotations" in _rules(_tool(annotations={}))


# --- Naming ----------------------------------------------------------------------------------------------


def test_unconventional_tool_name_is_flagged():
    """A name with a space matches no convention and cannot be reliably reproduced by a model."""
    assert "readiness.tool-name-unconventional" in _rules(_tool(name="Search Items"))


def test_mixed_naming_conventions_across_the_surface_are_flagged():
    """Individually fine names that mix conventions force an agent to memorize rather than infer."""
    found = _rules(_tool(name="get_user"), _tool(name="createUser", ordinal=1))
    assert "readiness.tool-naming-inconsistent" in found


def test_a_consistent_convention_is_not_flagged():
    """Every name in one convention lets an agent generalize the pattern."""
    found = _rules(_tool(name="get_user"), _tool(name="create_user", ordinal=1))
    assert "readiness.tool-naming-inconsistent" not in found


def test_single_word_names_do_not_look_like_a_mixed_convention():
    """A one-word lowercase name matches several conventions; it must not fake an inconsistency.

    ``search`` is valid snake_case *and* camelCase. Resolving it to the first match keeps a
    surface of simple one-word names from being reported as mixing conventions.
    """
    found = _rules(_tool(name="search"), _tool(name="lookup", ordinal=1))
    assert "readiness.tool-naming-inconsistent" not in found
