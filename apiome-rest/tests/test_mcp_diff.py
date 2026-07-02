"""Unit tests for the MCP surface diff engine (V2-MCP-18.2, #3669).

These exercise :mod:`app.mcp_client.diff`: :func:`~app.mcp_client.diff.diff_surfaces`
classifying capability items as added / removed / modified (with per-field before/after
detail) and server-metadata changes between two
:class:`~app.mcp_client.normalize.DiscoverySurface` objects. Coverage spans adjacent and
non-adjacent (arbitrarily distant) pairs, the identical-surface empty diff with its
"fingerprint unchanged" signal, deterministic ordering, the volatile-field exclusions it
inherits from the fingerprint projection, and the mapping onto ``mcp_version_changes``
rows.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.mcp_client.diff import (
    CHANGE_ADDED,
    CHANGE_MODIFIED,
    CHANGE_REMOVED,
    ITEM_TYPE_SERVER,
    FieldChange,
    ItemChange,
    SurfaceDiff,
    diff_surfaces,
)
from app.mcp_client.discovery import DiscoveryListings
from app.mcp_client.handshake import InitializeResult, ServerInfo
from app.mcp_client.normalize import (
    ITEM_TYPE_PROMPT,
    ITEM_TYPE_RESOURCE,
    ITEM_TYPE_RESOURCE_TEMPLATE,
    ITEM_TYPE_TOOL,
    DiscoverySurface,
)

# ===========================================================================
# Fixtures / builders
# ===========================================================================


def _tool(name: str, *, description: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    """A ``tools/list`` wire entry; ``overrides`` patch/extend the default shape."""
    entry: Dict[str, Any] = {
        "name": name,
        "title": f"{name} title",
        "description": description if description is not None else f"{name} description",
        "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
        "outputSchema": {"type": "object"},
        "annotations": {"readOnlyHint": True},
    }
    entry.update(overrides)
    return entry


def _resource(name: str, **overrides: Any) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "name": name,
        "title": f"{name} title",
        "description": f"{name} description",
        "uri": f"file:///{name}.txt",
        "mimeType": "text/plain",
    }
    entry.update(overrides)
    return entry


def _resource_template(name: str, **overrides: Any) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "name": name,
        "uriTemplate": f"file:///{{path}}/{name}",
    }
    entry.update(overrides)
    return entry


def _prompt(name: str, **overrides: Any) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "name": name,
        "description": f"{name} prompt",
        "arguments": [{"name": "topic", "required": True}],
    }
    entry.update(overrides)
    return entry


def _surface(
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
    resources: Optional[List[Dict[str, Any]]] = None,
    resource_templates: Optional[List[Dict[str, Any]]] = None,
    prompts: Optional[List[Dict[str, Any]]] = None,
    protocol_version: str = "2025-06-18",
    server_name: Optional[str] = "demo-server",
    server_title: Optional[str] = "Demo Server",
    server_version: Optional[str] = "1.0.0",
    capabilities: Optional[Dict[str, Any]] = None,
    instructions: Optional[str] = "use responsibly",
) -> DiscoverySurface:
    """Build a normalized surface from wire-shaped listings + identity fields."""
    initialize = InitializeResult(
        protocol_version=protocol_version,
        server_info=ServerInfo(name=server_name, title=server_title, version=server_version),
        capabilities=capabilities if capabilities is not None else {"tools": {}},
        instructions=instructions,
    )
    listings = DiscoveryListings(
        tools=tools or [],
        resources=resources or [],
        resource_templates=resource_templates or [],
        prompts=prompts or [],
    )
    return DiscoverySurface.from_discovery(initialize, listings)


def _by_name(diff: SurfaceDiff) -> Dict[str, ItemChange]:
    """Index a diff's changes by ``(item_type, name)`` -> change for easy assertions."""
    return {f"{change.item_type}:{change.name}": change for change in diff.changes}


# ===========================================================================
# Identical surfaces / fingerprint-unchanged
# ===========================================================================


def test_identical_surfaces_yield_empty_diff_and_fingerprint_unchanged() -> None:
    base = _surface(tools=[_tool("alpha"), _tool("beta")], prompts=[_prompt("p")])
    target = _surface(tools=[_tool("alpha"), _tool("beta")], prompts=[_prompt("p")])

    diff = diff_surfaces(base, target)

    assert diff.is_empty()
    assert diff.changes == ()
    assert diff.fingerprint_unchanged is True
    assert diff.base_fingerprint == diff.target_fingerprint
    assert diff.counts == {CHANGE_ADDED: 0, CHANGE_REMOVED: 0, CHANGE_MODIFIED: 0, "total": 0}


def test_self_diff_is_empty() -> None:
    surface = _surface(tools=[_tool("only")])
    diff = diff_surfaces(surface, surface)
    assert diff.is_empty()
    assert diff.fingerprint_unchanged is True


# ===========================================================================
# Added / removed
# ===========================================================================


def test_added_tool_is_classified_with_after_only() -> None:
    base = _surface(tools=[_tool("alpha")])
    target = _surface(tools=[_tool("alpha"), _tool("beta")])

    diff = diff_surfaces(base, target)

    assert diff.fingerprint_unchanged is False
    assert len(diff.changes) == 1
    change = diff.changes[0]
    assert change.change_type == CHANGE_ADDED
    assert change.item_type == ITEM_TYPE_TOOL
    assert change.name == "beta"
    assert change.before is None
    assert change.after["name"] == "beta"
    assert change.fields == ()
    assert change.to_detail() == {"after": change.after}
    assert diff.counts[CHANGE_ADDED] == 1


def test_removed_resource_is_classified_with_before_only() -> None:
    base = _surface(resources=[_resource("doc"), _resource("img")])
    target = _surface(resources=[_resource("doc")])

    diff = diff_surfaces(base, target)

    assert len(diff.changes) == 1
    change = diff.changes[0]
    assert change.change_type == CHANGE_REMOVED
    assert change.item_type == ITEM_TYPE_RESOURCE
    assert change.name == "img"
    assert change.after is None
    assert change.before["uri"] == "file:///img.txt"
    assert change.to_detail() == {"before": change.before}


def test_rename_reads_as_remove_plus_add() -> None:
    base = _surface(tools=[_tool("old")])
    target = _surface(tools=[_tool("new")])

    diff = diff_surfaces(base, target)
    indexed = _by_name(diff)

    assert indexed[f"{ITEM_TYPE_TOOL}:old"].change_type == CHANGE_REMOVED
    assert indexed[f"{ITEM_TYPE_TOOL}:new"].change_type == CHANGE_ADDED
    assert diff.counts == {CHANGE_ADDED: 1, CHANGE_REMOVED: 1, CHANGE_MODIFIED: 0, "total": 2}


# ===========================================================================
# Modified — per-field before/after
# ===========================================================================


def test_modified_tool_description_records_field_before_after() -> None:
    base = _surface(tools=[_tool("alpha", description="old text")])
    target = _surface(tools=[_tool("alpha", description="new text")])

    diff = diff_surfaces(base, target)

    assert len(diff.changes) == 1
    change = diff.changes[0]
    assert change.change_type == CHANGE_MODIFIED
    assert change.name == "alpha"
    assert change.before["description"] == "old text"
    assert change.after["description"] == "new text"
    assert change.fields == (
        FieldChange(field="description", before="old text", after="new text"),
    )
    detail = change.to_detail()
    assert detail["before"]["description"] == "old text"
    assert detail["after"]["description"] == "new text"
    assert detail["fields"] == [
        {"field": "description", "before": "old text", "after": "new text"}
    ]


def test_modified_tool_schema_and_annotations_each_reported() -> None:
    base = _surface(tools=[_tool("alpha")])
    target = _surface(
        tools=[
            _tool(
                "alpha",
                inputSchema={"type": "object", "properties": {"q": {"type": "integer"}}},
                annotations={"readOnlyHint": False},
            )
        ]
    )

    diff = diff_surfaces(base, target)
    change = diff.changes[0]
    changed_fields = {fc.field for fc in change.fields}
    assert changed_fields == {"inputSchema", "annotations"}


def test_modified_prompt_arguments_detected_from_raw() -> None:
    # ``arguments`` has no promoted column; the diff must still see it via the projection.
    base = _surface(prompts=[_prompt("p", arguments=[{"name": "topic"}])])
    target = _surface(prompts=[_prompt("p", arguments=[{"name": "topic"}, {"name": "tone"}])])

    diff = diff_surfaces(base, target)
    change = diff.changes[0]
    assert change.item_type == ITEM_TYPE_PROMPT
    assert change.change_type == CHANGE_MODIFIED
    assert {fc.field for fc in change.fields} == {"arguments"}


def test_modified_resource_template_uri_template() -> None:
    base = _surface(resource_templates=[_resource_template("t", uriTemplate="a/{x}")])
    target = _surface(resource_templates=[_resource_template("t", uriTemplate="b/{x}")])

    diff = diff_surfaces(base, target)
    change = diff.changes[0]
    assert change.item_type == ITEM_TYPE_RESOURCE_TEMPLATE
    assert {fc.field for fc in change.fields} == {"uriTemplate"}


# ===========================================================================
# Server metadata
# ===========================================================================


def test_server_metadata_changes_each_field() -> None:
    base = _surface(
        tools=[_tool("a")],
        protocol_version="2025-03-26",
        server_name="srv",
        server_title="Old",
        server_version="1.0.0",
        instructions=None,
        capabilities={"tools": {}},
    )
    target = _surface(
        tools=[_tool("a")],
        protocol_version="2025-06-18",
        server_name="srv",
        server_title="New",
        server_version="2.0.0",
        instructions="hello",
        capabilities={"tools": {}, "prompts": {}},
    )

    diff = diff_surfaces(base, target)
    indexed = _by_name(diff)

    changed = {c.name for c in diff.changes if c.item_type == ITEM_TYPE_SERVER}
    assert changed == {"protocol_version", "server_title", "server_version", "instructions", "capabilities"}
    # server_name was unchanged -> no entry.
    assert f"{ITEM_TYPE_SERVER}:server_name" not in indexed

    proto = indexed[f"{ITEM_TYPE_SERVER}:protocol_version"]
    assert proto.change_type == CHANGE_MODIFIED
    assert proto.before == "2025-03-26"
    assert proto.after == "2025-06-18"
    assert proto.to_detail() == {"before": "2025-03-26", "after": "2025-06-18"}

    # instructions appearing for the first time: before is None, still "modified".
    instr = indexed[f"{ITEM_TYPE_SERVER}:instructions"]
    assert instr.before is None
    assert instr.after == "hello"

    caps = indexed[f"{ITEM_TYPE_SERVER}:capabilities"]
    assert caps.before == {"tools": {}}
    assert caps.after == {"tools": {}, "prompts": {}}


# ===========================================================================
# Volatile-field exclusions (inherited from the fingerprint projection)
# ===========================================================================


def test_meta_only_change_is_invisible() -> None:
    base = _surface(tools=[_tool("alpha")])
    target = _surface(tools=[_tool("alpha", _meta={"trace": "xyz"})])

    diff = diff_surfaces(base, target)

    assert diff.is_empty()
    assert diff.fingerprint_unchanged is True


def test_resource_size_hint_is_invisible() -> None:
    base = _surface(resources=[_resource("doc", size=10)])
    target = _surface(resources=[_resource("doc", size=99)])

    diff = diff_surfaces(base, target)

    assert diff.is_empty()


# ===========================================================================
# Ordering-only change: empty diff but fingerprint differs
# ===========================================================================


def test_reorder_only_yields_empty_diff_but_changed_fingerprint() -> None:
    base = _surface(tools=[_tool("alpha"), _tool("beta")])
    target = _surface(tools=[_tool("beta"), _tool("alpha")])

    diff = diff_surfaces(base, target)

    assert diff.is_empty()
    assert diff.fingerprint_unchanged is False


# ===========================================================================
# Non-adjacent pairs (arbitrary versions)
# ===========================================================================


def test_non_adjacent_diff_is_exact() -> None:
    # v1 -> v2 (add gamma, modify alpha) -> v3 (remove beta, modify gamma).
    v1 = _surface(tools=[_tool("alpha", description="a1"), _tool("beta")])
    v3 = _surface(
        tools=[_tool("alpha", description="a3"), _tool("gamma", description="g3")]
    )

    diff = diff_surfaces(v1, v3)
    indexed = _by_name(diff)

    # alpha existed in both but changed -> modified (before a1, after a3).
    alpha = indexed[f"{ITEM_TYPE_TOOL}:alpha"]
    assert alpha.change_type == CHANGE_MODIFIED
    assert alpha.before["description"] == "a1"
    assert alpha.after["description"] == "a3"
    # beta only in v1 -> removed; gamma only in v3 -> added.
    assert indexed[f"{ITEM_TYPE_TOOL}:beta"].change_type == CHANGE_REMOVED
    assert indexed[f"{ITEM_TYPE_TOOL}:gamma"].change_type == CHANGE_ADDED
    assert diff.counts == {CHANGE_ADDED: 1, CHANGE_REMOVED: 1, CHANGE_MODIFIED: 1, "total": 3}


# ===========================================================================
# Deterministic ordering & repeatability
# ===========================================================================


def test_changes_are_in_stable_order() -> None:
    base = _surface(
        tools=[_tool("t_keep"), _tool("t_drop")],
        resources=[_resource("r_keep")],
        instructions="before",
    )
    target = _surface(
        tools=[_tool("t_keep", description="changed"), _tool("t_new")],
        resources=[_resource("r_keep"), _resource("r_new")],
        prompts=[_prompt("p_new")],
        instructions="after",
    )

    diff = diff_surfaces(base, target)
    order = [(c.item_type, c.name) for c in diff.changes]

    # server first, then tools, resources, resource_templates, prompts; each by name.
    assert order == [
        (ITEM_TYPE_SERVER, "instructions"),
        (ITEM_TYPE_TOOL, "t_drop"),
        (ITEM_TYPE_TOOL, "t_keep"),
        (ITEM_TYPE_TOOL, "t_new"),
        (ITEM_TYPE_RESOURCE, "r_new"),
        (ITEM_TYPE_PROMPT, "p_new"),
    ]


def test_diff_is_repeatable() -> None:
    base = _surface(tools=[_tool("a"), _tool("b")], resources=[_resource("r")])
    target = _surface(tools=[_tool("a", description="x"), _tool("c")])

    first = diff_surfaces(base, target)
    second = diff_surfaces(base, target)

    assert first.changes == second.changes
    assert first.counts == second.counts


# ===========================================================================
# mcp_version_changes row mapping
# ===========================================================================


def test_to_change_rows_maps_every_change() -> None:
    base = _surface(tools=[_tool("keep"), _tool("drop")])
    target = _surface(tools=[_tool("keep", description="new"), _tool("add")])
    version_id = "11111111-1111-1111-1111-111111111111"

    diff = diff_surfaces(base, target)
    rows = diff.to_change_rows(version_id)

    assert len(rows) == len(diff.changes) == 3
    assert all(row["version_id"] == version_id for row in rows)
    assert {row["change_type"] for row in rows} == {CHANGE_ADDED, CHANGE_REMOVED, CHANGE_MODIFIED}
    assert all(row["item_type"] == ITEM_TYPE_TOOL for row in rows)
    assert {row["item_name"] for row in rows} == {"add", "drop", "keep"}

    by_name = {row["item_name"]: row for row in rows}
    assert set(by_name["add"]["detail"].keys()) == {"after"}
    assert set(by_name["drop"]["detail"].keys()) == {"before"}
    assert set(by_name["keep"]["detail"].keys()) == {"before", "after", "fields"}


def test_change_row_columns_match_schema() -> None:
    base = _surface(tools=[_tool("a")])
    target = _surface(tools=[_tool("a"), _tool("b")])
    diff = diff_surfaces(base, target)

    row = diff.to_change_rows("v-1")[0]
    assert set(row.keys()) == {"version_id", "change_type", "item_type", "item_name", "detail"}
