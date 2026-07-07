"""Unit tests for the MCP breaking-change classifier (V2-MCP-30.3 / MCAT-16.3, #4638).

Exercises :mod:`app.mcp_change_severity`: :func:`~app.mcp_change_severity.classify_change`
assigning each surface change a ``breaking`` / ``additive`` / ``review`` severity, and
:func:`~app.mcp_change_severity.severity_counts` rolling a collection up. Coverage spans the
ticket's enumerated cases (removed capability; a modification that adds a required param,
removes a param, narrows an enum, or changes a type; descriptive and additive-optional edits),
the "unknown/edge shapes default to review, not silent additive" guarantee, prompt-argument
and server-metadata rules, an end-to-end pass over the real diff engine's output, and the
wiring into the wire models (``McpVersionChangeOut.severity`` and the evolution rollup).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.mcp_change_severity import (
    SEVERITY_ADDITIVE,
    SEVERITY_BREAKING,
    SEVERITY_REVIEW,
    classify_change,
    severity_counts,
)
from app.mcp_client.diff import diff_surfaces
from app.mcp_client.discovery import DiscoveryListings
from app.mcp_client.handshake import InitializeResult, ServerInfo
from app.mcp_client.normalize import DiscoverySurface
from app.models import (
    mcp_evolution_point_from_row,
    mcp_version_change_out_from_row,
)

# ===========================================================================
# Builders
# ===========================================================================


def _change(
    change_type: str,
    item_type: str,
    name: str,
    *,
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A change record shaped like an ``mcp_version_changes`` row / a ``to_change_rows`` dict."""
    detail: Dict[str, Any] = {}
    if before is not None:
        detail["before"] = before
    if after is not None:
        detail["after"] = after
    return {
        "change_type": change_type,
        "item_type": item_type,
        "item_name": name,
        "detail": detail,
    }


def _obj_schema(properties: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    """A minimal JSON-Schema object with the given properties (and optional required list)."""
    schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required is not None:
        schema["required"] = required
    return schema


# ===========================================================================
# Added / removed capabilities
# ===========================================================================


def test_removed_capability_is_breaking() -> None:
    change = _change("removed", "tool", "search", before={"name": "search"})
    assert classify_change(change) == SEVERITY_BREAKING


def test_added_capability_is_additive() -> None:
    change = _change("added", "tool", "search", after={"name": "search"})
    assert classify_change(change) == SEVERITY_ADDITIVE


# ===========================================================================
# Modified tool — input-schema classification (the enumerated breaking cases)
# ===========================================================================


def test_modification_adding_required_param_is_breaking() -> None:
    before = {"inputSchema": _obj_schema({"q": {"type": "string"}})}
    after = {"inputSchema": _obj_schema({"q": {"type": "string"}}, required=["q"])}
    assert classify_change(_change("modified", "tool", "t", before=before, after=after)) == SEVERITY_BREAKING


def test_modification_removing_param_is_breaking() -> None:
    before = {"inputSchema": _obj_schema({"q": {"type": "string"}, "limit": {"type": "integer"}})}
    after = {"inputSchema": _obj_schema({"q": {"type": "string"}})}
    assert classify_change(_change("modified", "tool", "t", before=before, after=after)) == SEVERITY_BREAKING


def test_modification_narrowing_enum_is_breaking() -> None:
    before = {"inputSchema": _obj_schema({"mode": {"type": "string", "enum": ["a", "b", "c"]}})}
    after = {"inputSchema": _obj_schema({"mode": {"type": "string", "enum": ["a", "b"]}})}
    assert classify_change(_change("modified", "tool", "t", before=before, after=after)) == SEVERITY_BREAKING


def test_modification_changing_type_is_breaking() -> None:
    before = {"inputSchema": _obj_schema({"q": {"type": "string"}})}
    after = {"inputSchema": _obj_schema({"q": {"type": "integer"}})}
    assert classify_change(_change("modified", "tool", "t", before=before, after=after)) == SEVERITY_BREAKING


def test_adding_optional_param_is_additive() -> None:
    before = {"inputSchema": _obj_schema({"q": {"type": "string"}})}
    after = {"inputSchema": _obj_schema({"q": {"type": "string"}, "limit": {"type": "integer"}})}
    assert classify_change(_change("modified", "tool", "t", before=before, after=after)) == SEVERITY_ADDITIVE


def test_widening_enum_is_additive() -> None:
    before = {"inputSchema": _obj_schema({"mode": {"type": "string", "enum": ["a"]}})}
    after = {"inputSchema": _obj_schema({"mode": {"type": "string", "enum": ["a", "b"]}})}
    assert classify_change(_change("modified", "tool", "t", before=before, after=after)) == SEVERITY_ADDITIVE


# ===========================================================================
# Modified tool — descriptive edits, and worst-field wins
# ===========================================================================


def test_description_only_change_is_additive() -> None:
    before = {"description": "old", "title": "Old"}
    after = {"description": "new", "title": "New"}
    assert classify_change(_change("modified", "tool", "t", before=before, after=after)) == SEVERITY_ADDITIVE


def test_worst_field_wins_description_plus_breaking_schema() -> None:
    before = {"description": "old", "inputSchema": _obj_schema({"q": {"type": "string"}})}
    after = {"description": "new", "inputSchema": _obj_schema({"q": {"type": "integer"}})}
    assert classify_change(_change("modified", "tool", "t", before=before, after=after)) == SEVERITY_BREAKING


def test_annotations_change_is_review() -> None:
    before = {"annotations": {"readOnlyHint": True}}
    after = {"annotations": {"readOnlyHint": False, "destructiveHint": True}}
    assert classify_change(_change("modified", "tool", "t", before=before, after=after)) == SEVERITY_REVIEW


# ===========================================================================
# Unknown / edge schema shapes default to review, never silent additive
# ===========================================================================


def test_schema_appearing_is_review_not_additive() -> None:
    # outputSchema going from absent (None) to a concrete object is an edge case.
    before = {"outputSchema": None}
    after = {"outputSchema": _obj_schema({"result": {"type": "string"}})}
    assert classify_change(_change("modified", "tool", "t", before=before, after=after)) == SEVERITY_REVIEW


def test_schema_vanishing_is_review_not_additive() -> None:
    before = {"inputSchema": _obj_schema({"q": {"type": "string"}})}
    after = {"inputSchema": None}
    assert classify_change(_change("modified", "tool", "t", before=before, after=after)) == SEVERITY_REVIEW


def test_pattern_change_is_review() -> None:
    before = {"inputSchema": _obj_schema({"q": {"type": "string", "pattern": "^a"}})}
    after = {"inputSchema": _obj_schema({"q": {"type": "string", "pattern": "^b"}})}
    assert classify_change(_change("modified", "tool", "t", before=before, after=after)) == SEVERITY_REVIEW


def test_modification_without_both_projections_is_review() -> None:
    # A "modified" row missing before/after cannot be judged — review, not additive.
    assert classify_change(_change("modified", "tool", "t", after={"description": "x"})) == SEVERITY_REVIEW


def test_unrecognized_change_type_is_review() -> None:
    assert classify_change(_change("renamed", "tool", "t")) == SEVERITY_REVIEW


# ===========================================================================
# Resource / resource-template addressing fields → review
# ===========================================================================


def test_resource_uri_change_is_review() -> None:
    before = {"uri": "file:///a.txt", "mimeType": "text/plain"}
    after = {"uri": "file:///b.txt", "mimeType": "text/plain"}
    assert classify_change(_change("modified", "resource", "r", before=before, after=after)) == SEVERITY_REVIEW


def test_resource_mimetype_change_is_review() -> None:
    before = {"uri": "file:///a.txt", "mimeType": "text/plain"}
    after = {"uri": "file:///a.txt", "mimeType": "application/json"}
    assert classify_change(_change("modified", "resource", "r", before=before, after=after)) == SEVERITY_REVIEW


# ===========================================================================
# Prompt arguments — param-style rules
# ===========================================================================


def _args(*specs: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(specs)


def test_prompt_adding_required_argument_is_breaking() -> None:
    before = {"arguments": _args({"name": "topic", "required": True})}
    after = {"arguments": _args({"name": "topic", "required": True}, {"name": "lang", "required": True})}
    assert classify_change(_change("modified", "prompt", "p", before=before, after=after)) == SEVERITY_BREAKING


def test_prompt_adding_optional_argument_is_additive() -> None:
    before = {"arguments": _args({"name": "topic", "required": True})}
    after = {"arguments": _args({"name": "topic", "required": True}, {"name": "lang"})}
    assert classify_change(_change("modified", "prompt", "p", before=before, after=after)) == SEVERITY_ADDITIVE


def test_prompt_removing_argument_is_breaking() -> None:
    before = {"arguments": _args({"name": "topic", "required": True}, {"name": "lang"})}
    after = {"arguments": _args({"name": "topic", "required": True})}
    assert classify_change(_change("modified", "prompt", "p", before=before, after=after)) == SEVERITY_BREAKING


def test_prompt_optional_to_required_is_breaking() -> None:
    before = {"arguments": _args({"name": "topic"})}
    after = {"arguments": _args({"name": "topic", "required": True})}
    assert classify_change(_change("modified", "prompt", "p", before=before, after=after)) == SEVERITY_BREAKING


def test_prompt_required_to_optional_is_additive() -> None:
    before = {"arguments": _args({"name": "topic", "required": True})}
    after = {"arguments": _args({"name": "topic"})}
    assert classify_change(_change("modified", "prompt", "p", before=before, after=after)) == SEVERITY_ADDITIVE


def test_prompt_malformed_arguments_is_review() -> None:
    before = {"arguments": _args({"name": "topic"})}
    after = {"arguments": ["not-an-object"]}
    assert classify_change(_change("modified", "prompt", "p", before=before, after=after)) == SEVERITY_REVIEW


# ===========================================================================
# Server-metadata modifications
# ===========================================================================


def test_server_descriptive_field_is_additive() -> None:
    change = _change("modified", "server", "server_version", before="1.0.0", after="1.1.0")
    assert classify_change(change) == SEVERITY_ADDITIVE


def test_server_protocol_change_is_review() -> None:
    change = _change("modified", "server", "protocol_version", before="2025-03-26", after="2025-06-18")
    assert classify_change(change) == SEVERITY_REVIEW


def test_server_capabilities_change_is_review() -> None:
    change = _change("modified", "server", "capabilities", before={"tools": {}}, after={})
    assert classify_change(change) == SEVERITY_REVIEW


# ===========================================================================
# Determinism & rollup
# ===========================================================================


def test_classification_is_deterministic() -> None:
    before = {"inputSchema": _obj_schema({"q": {"type": "string"}})}
    after = {"inputSchema": _obj_schema({"q": {"type": "integer"}})}
    change = _change("modified", "tool", "t", before=before, after=after)
    assert classify_change(change) == classify_change(change) == SEVERITY_BREAKING


def test_severity_counts_rolls_up_with_total() -> None:
    changes = [
        _change("removed", "tool", "gone"),  # breaking
        _change("added", "tool", "fresh"),  # additive
        _change(
            "modified",
            "tool",
            "t",
            before={"inputSchema": _obj_schema({"q": {"type": "string"}})},
            after={"inputSchema": _obj_schema({"q": {"type": "integer"}})},
        ),  # breaking
        _change("modified", "resource", "r", before={"uri": "a"}, after={"uri": "b"}),  # review
    ]
    counts = severity_counts(changes)
    assert counts == {
        SEVERITY_BREAKING: 2,
        SEVERITY_ADDITIVE: 1,
        SEVERITY_REVIEW: 1,
        "total": 4,
    }


def test_severity_counts_empty_is_all_zero() -> None:
    assert severity_counts([]) == {
        SEVERITY_BREAKING: 0,
        SEVERITY_ADDITIVE: 0,
        SEVERITY_REVIEW: 0,
        "total": 0,
    }


# ===========================================================================
# End-to-end over the real diff engine output
# ===========================================================================


def _surface(
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
    prompts: Optional[List[Dict[str, Any]]] = None,
) -> DiscoverySurface:
    initialize = InitializeResult(
        protocol_version="2025-06-18",
        server_info=ServerInfo(name="demo", title="Demo", version="1.0.0"),
        capabilities={"tools": {}},
        instructions="use responsibly",
    )
    listings = DiscoveryListings(
        tools=tools or [],
        resources=[],
        resource_templates=[],
        prompts=prompts or [],
    )
    return DiscoverySurface.from_discovery(initialize, listings)


def test_end_to_end_diff_rows_classify_correctly() -> None:
    base = _surface(
        tools=[
            {
                "name": "search",
                "description": "search things",
                "inputSchema": _obj_schema({"q": {"type": "string"}}),
            },
            {"name": "legacy", "inputSchema": _obj_schema({})},
        ],
    )
    target = _surface(
        tools=[
            {
                "name": "search",
                "description": "search things",
                # q went string -> integer: a breaking type change.
                "inputSchema": _obj_schema({"q": {"type": "integer"}}),
            },
            {"name": "brand_new", "inputSchema": _obj_schema({})},
        ],
    )

    rows = diff_surfaces(base, target).to_change_rows(version_id="v2")
    by_name = {(r["item_type"], r["item_name"]): classify_change(r) for r in rows}

    assert by_name[("tool", "search")] == SEVERITY_BREAKING  # type change
    assert by_name[("tool", "legacy")] == SEVERITY_BREAKING  # removed
    assert by_name[("tool", "brand_new")] == SEVERITY_ADDITIVE  # added


# ===========================================================================
# Wire-model integration
# ===========================================================================


def test_version_change_out_carries_severity() -> None:
    row = _change(
        "modified",
        "tool",
        "t",
        before={"inputSchema": _obj_schema({"q": {"type": "string"}})},
        after={"inputSchema": _obj_schema({"q": {"type": "string"}}, required=["q"])},
    )
    out = mcp_version_change_out_from_row(row)
    assert out.severity == SEVERITY_BREAKING
    assert out.item_name == "t"


def test_evolution_point_rolls_up_severity_counts() -> None:
    version_row = {
        "id": "v2",
        "version_seq": 2,
        "version_tag": "2026-07-07T00:00Z",
        "discovered_at": None,
        "tool_count": 1,
        "resource_count": 0,
        "resource_template_count": 0,
        "prompt_count": 0,
        "score": None,
        "grade": None,
        "added_count": 1,
        "removed_count": 1,
        "modified_count": 1,
    }
    change_rows = [
        _change("removed", "tool", "gone"),  # breaking
        _change("added", "tool", "fresh"),  # additive
        _change(
            "modified",
            "tool",
            "t",
            before={"inputSchema": _obj_schema({"q": {"type": "string"}})},
            after={"inputSchema": _obj_schema({"q": {"type": "integer"}})},
        ),  # breaking
    ]
    point = mcp_evolution_point_from_row(version_row, "v2", change_rows)
    assert point.severity_counts.breaking == 2
    assert point.severity_counts.additive == 1
    assert point.severity_counts.review == 0
    assert point.severity_counts.total == 3
    assert point.is_current is True


def test_evolution_point_without_changes_has_zero_severity_counts() -> None:
    version_row = {
        "id": "v1",
        "version_seq": 1,
        "version_tag": "2026-07-06T00:00Z",
        "discovered_at": None,
        "tool_count": 0,
        "resource_count": 0,
        "resource_template_count": 0,
        "prompt_count": 0,
        "score": None,
        "grade": None,
        "added_count": 0,
        "removed_count": 0,
        "modified_count": 0,
    }
    point = mcp_evolution_point_from_row(version_row, None)
    assert point.severity_counts.total == 0
    assert point.severity_counts.breaking == 0
