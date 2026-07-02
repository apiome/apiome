"""Unit tests for MCP capability-surface normalization (V2-MCP-16.4, #3660).

These exercise :mod:`app.mcp_client.normalize`: turning an
:class:`~app.mcp_client.handshake.InitializeResult` plus a
:class:`~app.mcp_client.discovery.DiscoveryListings` into a canonical
:class:`~app.mcp_client.normalize.DiscoverySurface`, the version-tolerant parsing
of each item kind (absent ``title``/``outputSchema`` on 2025-03-26 → ``None``),
byte-stable canonical serialization that is invariant to wire map ordering but
sensitive to list ordering, and the lossless round-trip to and from
``mcp_capability_items`` rows.

Also covers the canonical surface fingerprint (V2-MCP-18.1, #3668): the semantic
projection that feeds ``surface_fingerprint`` — identical across runs/hosts for an
identical offering, flipped by any semantically meaningful change, and unaffected by
volatile fields (the reserved ``_meta`` block, a resource ``size`` hint, vendor keys).
"""

from __future__ import annotations

import json
from typing import Any, Dict

from app.mcp_client.discovery import DiscoveryListings
from app.mcp_client.handshake import InitializeResult, ServerInfo
from app.mcp_client.normalize import (
    FINGERPRINT_FIELDS,
    ITEM_TYPE_PROMPT,
    ITEM_TYPE_RESOURCE,
    ITEM_TYPE_RESOURCE_TEMPLATE,
    ITEM_TYPE_TOOL,
    CapabilityItem,
    DiscoverySurface,
)

# ===========================================================================
# Fixtures / builders
# ===========================================================================


def _tool(name: str, *, with_modern: bool = True) -> Dict[str, Any]:
    """A ``tools/list`` wire entry; ``with_modern`` toggles 2025-06-18-only fields."""
    entry: Dict[str, Any] = {
        "name": name,
        "description": f"{name} description",
        "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
    }
    if with_modern:
        entry["title"] = f"{name} title"
        entry["outputSchema"] = {"type": "object"}
        entry["annotations"] = {"readOnlyHint": True}
    return entry


def _resource(name: str) -> Dict[str, Any]:
    return {
        "name": name,
        "title": f"{name} title",
        "uri": f"file:///{name}.txt",
        "mimeType": "text/plain",
    }


def _resource_template(name: str) -> Dict[str, Any]:
    return {
        "name": name,
        "uriTemplate": f"file:///{{path}}/{name}",
    }


def _prompt(name: str) -> Dict[str, Any]:
    return {
        "name": name,
        "description": f"{name} prompt",
        "arguments": [{"name": "topic", "required": True}],
    }


def _listings(**kwargs: Any) -> DiscoveryListings:
    return DiscoveryListings(
        tools=kwargs.get("tools", []),
        resources=kwargs.get("resources", []),
        resource_templates=kwargs.get("resource_templates", []),
        prompts=kwargs.get("prompts", []),
        skipped=kwargs.get("skipped", ()),
    )


def _initialize(version: str = "2025-06-18", **kwargs: Any) -> InitializeResult:
    return InitializeResult(
        protocol_version=version,
        server_info=kwargs.get("server_info", ServerInfo(name="srv", title="Srv", version="1.0")),
        capabilities=kwargs.get("capabilities", {"tools": {}, "resources": {}, "prompts": {}}),
        instructions=kwargs.get("instructions", "be helpful"),
        raw=kwargs.get("raw", {}),
    )


# ===========================================================================
# Item-level parsing + version tolerance
# ===========================================================================


def test_from_tool_promotes_all_modern_fields() -> None:
    item = CapabilityItem.from_tool(_tool("search"), 3)
    assert item.item_type == ITEM_TYPE_TOOL
    assert item.name == "search"
    assert item.ordinal == 3
    assert item.title == "search title"
    assert item.description == "search description"
    assert item.input_schema == {"type": "object", "properties": {"q": {"type": "string"}}}
    assert item.output_schema == {"type": "object"}
    assert item.annotations == {"readOnlyHint": True}
    # Non-tool columns stay None.
    assert item.uri is None and item.uri_template is None
    # Raw is the verbatim wire entry.
    assert item.raw == _tool("search")


def test_from_tool_legacy_server_nulls_title_and_output_schema() -> None:
    # A 2025-03-26 tool omits title/outputSchema/annotations entirely.
    item = CapabilityItem.from_tool(_tool("legacy", with_modern=False), 0)
    assert item.title is None
    assert item.output_schema is None
    assert item.annotations is None
    # input_schema and description still parse.
    assert item.input_schema is not None
    assert item.description == "legacy description"


def test_from_resource_and_template_promote_uri_fields() -> None:
    res = CapabilityItem.from_resource(_resource("doc"), 0)
    assert res.item_type == ITEM_TYPE_RESOURCE
    assert res.uri == "file:///doc.txt"
    assert res.uri_template is None
    # mimeType has no promoted column but survives in raw.
    assert res.raw["mimeType"] == "text/plain"

    tmpl = CapabilityItem.from_resource_template(_resource_template("page"), 1)
    assert tmpl.item_type == ITEM_TYPE_RESOURCE_TEMPLATE
    assert tmpl.uri_template == "file:///{path}/page"
    assert tmpl.uri is None
    assert tmpl.title is None  # absent on the wire


def test_from_prompt_keeps_arguments_in_raw_only() -> None:
    item = CapabilityItem.from_prompt(_prompt("summarize"), 2)
    assert item.item_type == ITEM_TYPE_PROMPT
    assert item.description == "summarize prompt"
    # arguments have no promoted column; preserved verbatim.
    assert item.raw["arguments"] == [{"name": "topic", "required": True}]
    assert item.input_schema is None and item.uri is None


def test_missing_name_coerced_to_empty_string_not_dropped() -> None:
    item = CapabilityItem.from_tool({"description": "anon"}, 0)
    assert item.name == ""
    assert item.raw == {"description": "anon"}


def test_non_object_schema_normalizes_to_none() -> None:
    # A malformed inputSchema (not an object) becomes None rather than raising.
    item = CapabilityItem.from_tool({"name": "bad", "inputSchema": "nope"}, 0)
    assert item.input_schema is None


# ===========================================================================
# Surface construction from discovery
# ===========================================================================


def test_from_discovery_assigns_ordinals_and_copies_identity() -> None:
    surface = DiscoverySurface.from_discovery(
        _initialize(),
        _listings(
            tools=[_tool("a"), _tool("b")],
            resources=[_resource("r")],
            resource_templates=[_resource_template("t")],
            prompts=[_prompt("p")],
        ),
    )
    assert surface.protocol_version == "2025-06-18"
    assert surface.server_info.name == "srv"
    assert surface.instructions == "be helpful"
    assert [t.ordinal for t in surface.tools] == [0, 1]
    assert [t.name for t in surface.tools] == ["a", "b"]
    assert surface.resources[0].ordinal == 0
    assert len(surface.all_items()) == 5


def test_all_items_ordered_by_kind_then_ordinal() -> None:
    surface = DiscoverySurface.from_discovery(
        _initialize(),
        _listings(
            tools=[_tool("t0"), _tool("t1")],
            resources=[_resource("r0")],
            prompts=[_prompt("p0")],
        ),
    )
    kinds = [item.item_type for item in surface.all_items()]
    assert kinds == [ITEM_TYPE_TOOL, ITEM_TYPE_TOOL, ITEM_TYPE_RESOURCE, ITEM_TYPE_PROMPT]


# ===========================================================================
# Byte-stable canonical serialization
# ===========================================================================


def test_canonical_json_invariant_to_wire_map_ordering() -> None:
    # Same logical tool, keys in two different orders.
    ordered = {"name": "x", "title": "X", "inputSchema": {"a": 1, "b": 2}}
    shuffled = {"inputSchema": {"b": 2, "a": 1}, "title": "X", "name": "x"}

    init = _initialize(capabilities={"tools": {}})
    s1 = DiscoverySurface.from_discovery(init, _listings(tools=[ordered]))
    s2 = DiscoverySurface.from_discovery(init, _listings(tools=[shuffled]))

    assert s1.canonical_json() == s2.canonical_json()
    assert s1.fingerprint() == s2.fingerprint()
    # And the canonical form really is sorted (deterministic bytes).
    assert s1.canonical_json() == json.dumps(
        s1.canonical_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def test_canonical_json_sensitive_to_list_ordering() -> None:
    # Reordering the items (not just object keys) IS a real change.
    init = _initialize()
    s1 = DiscoverySurface.from_discovery(init, _listings(tools=[_tool("a"), _tool("b")]))
    s2 = DiscoverySurface.from_discovery(init, _listings(tools=[_tool("b"), _tool("a")]))
    assert s1.fingerprint() != s2.fingerprint()


def test_capabilities_map_ordering_does_not_change_fingerprint() -> None:
    s1 = DiscoverySurface.from_discovery(
        _initialize(capabilities={"tools": {}, "resources": {}}), _listings()
    )
    s2 = DiscoverySurface.from_discovery(
        _initialize(capabilities={"resources": {}, "tools": {}}), _listings()
    )
    assert s1.fingerprint() == s2.fingerprint()


def test_fingerprint_is_sha256_hex() -> None:
    fp = DiscoverySurface.from_discovery(_initialize(), _listings()).fingerprint()
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


# ===========================================================================
# Canonical surface fingerprint — semantic projection (V2-MCP-18.1, #3668)
#
# The fingerprint must be identical for identical *offerings* across runs and
# hosts, flip on any semantically meaningful change, and ignore volatile fields.
# ===========================================================================


def test_fingerprint_projection_keys_match_documented_field_list() -> None:
    # Each kind's projection exposes exactly the documented allow-list, in order.
    tool = CapabilityItem.from_tool(_tool("a"), 0)
    resource = CapabilityItem.from_resource(_resource("r"), 0)
    template = CapabilityItem.from_resource_template(_resource_template("t"), 0)
    prompt = CapabilityItem.from_prompt(_prompt("p"), 0)
    assert tuple(tool.fingerprint_projection()) == FINGERPRINT_FIELDS[ITEM_TYPE_TOOL]
    assert tuple(resource.fingerprint_projection()) == FINGERPRINT_FIELDS[ITEM_TYPE_RESOURCE]
    assert tuple(template.fingerprint_projection()) == FINGERPRINT_FIELDS[ITEM_TYPE_RESOURCE_TEMPLATE]
    assert tuple(prompt.fingerprint_projection()) == FINGERPRINT_FIELDS[ITEM_TYPE_PROMPT]


def test_fingerprint_projection_recovers_non_promoted_fields_from_raw() -> None:
    # mimeType (resource) and arguments (prompt) have no promoted column.
    resource = CapabilityItem.from_resource(_resource("r"), 0)
    prompt = CapabilityItem.from_prompt(_prompt("p"), 0)
    assert resource.fingerprint_projection()["mimeType"] == "text/plain"
    assert prompt.fingerprint_projection()["arguments"] == [{"name": "topic", "required": True}]


def test_meta_block_is_excluded_from_fingerprint() -> None:
    # The reserved _meta escape hatch must never flip the fingerprint, at any depth.
    plain = _tool("a")
    noisy = _tool("a")
    noisy["_meta"] = {"progressToken": 7}
    noisy["inputSchema"] = {**noisy["inputSchema"], "_meta": {"trace": "xyz"}}
    init = _initialize()
    s1 = DiscoverySurface.from_discovery(init, _listings(tools=[plain]))
    s2 = DiscoverySurface.from_discovery(init, _listings(tools=[noisy]))
    assert s1.fingerprint() == s2.fingerprint()
    # And _meta really is gone from the canonical projection.
    assert "_meta" not in s2.canonical_dict()["tools"][0]
    assert "_meta" not in s2.canonical_dict()["tools"][0]["inputSchema"]


def test_meta_in_capabilities_is_excluded() -> None:
    s1 = DiscoverySurface.from_discovery(_initialize(capabilities={"tools": {}}), _listings())
    s2 = DiscoverySurface.from_discovery(
        _initialize(capabilities={"tools": {"_meta": {"x": 1}}}), _listings()
    )
    assert s1.fingerprint() == s2.fingerprint()


def test_volatile_and_vendor_fields_are_excluded() -> None:
    # A resource's volatile ``size`` hint and an unknown vendor key are not in the
    # allow-list, so changing them does not change the fingerprint.
    base = _resource("r")
    noisy = {**base, "size": 4096, "x-vendor-cache": "deadbeef"}
    init = _initialize()
    s1 = DiscoverySurface.from_discovery(init, _listings(resources=[base]))
    s2 = DiscoverySurface.from_discovery(init, _listings(resources=[noisy]))
    assert s1.fingerprint() == s2.fingerprint()


def test_identical_offering_same_fingerprint_across_hosts() -> None:
    # Two hosts return the same logical offering but with shuffled object keys and
    # different volatile metadata — the fingerprint must agree.
    host_a = {
        "name": "search",
        "title": "Search",
        "description": "find things",
        "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
    }
    host_b = {
        "_meta": {"progressToken": "abc"},
        "inputSchema": {"properties": {"q": {"type": "string"}}, "type": "object"},
        "description": "find things",
        "title": "Search",
        "name": "search",
    }
    init = _initialize()
    a = DiscoverySurface.from_discovery(init, _listings(tools=[host_a]))
    b = DiscoverySurface.from_discovery(init, _listings(tools=[host_b]))
    assert a.fingerprint() == b.fingerprint()


def test_single_tool_description_change_flips_fingerprint() -> None:
    init = _initialize()
    base = _tool("a")
    changed = {**base, "description": "a description (revised)"}
    s1 = DiscoverySurface.from_discovery(init, _listings(tools=[base]))
    s2 = DiscoverySurface.from_discovery(init, _listings(tools=[changed]))
    assert s1.fingerprint() != s2.fingerprint()


def test_semantic_field_changes_flip_fingerprint() -> None:
    # Each documented semantic field, when changed, must flip the fingerprint.
    init = _initialize()
    base = DiscoverySurface.from_discovery(
        init,
        _listings(
            tools=[_tool("a")],
            resources=[_resource("r")],
            resource_templates=[_resource_template("t")],
            prompts=[_prompt("p")],
        ),
    )
    base_fp = base.fingerprint()

    def fp_with(**overrides: Any) -> str:
        return DiscoverySurface.from_discovery(
            overrides.get("init", init),
            _listings(
                tools=[overrides.get("tool", _tool("a"))],
                resources=[overrides.get("resource", _resource("r"))],
                resource_templates=[overrides.get("template", _resource_template("t"))],
                prompts=[overrides.get("prompt", _prompt("p"))],
            ),
        ).fingerprint()

    # Tool inputSchema / outputSchema / annotations.
    assert fp_with(tool={**_tool("a"), "inputSchema": {"type": "string"}}) != base_fp
    assert fp_with(tool={**_tool("a"), "outputSchema": {"type": "array"}}) != base_fp
    assert fp_with(tool={**_tool("a"), "annotations": {"readOnlyHint": False}}) != base_fp
    # Resource uri / mimeType.
    assert fp_with(resource={**_resource("r"), "uri": "file:///other.txt"}) != base_fp
    assert fp_with(resource={**_resource("r"), "mimeType": "application/json"}) != base_fp
    # Resource-template uriTemplate.
    assert fp_with(template={**_resource_template("t"), "uriTemplate": "file:///{x}"}) != base_fp
    # Prompt arguments.
    assert fp_with(prompt={**_prompt("p"), "arguments": [{"name": "topic", "required": False}]}) != base_fp
    # Surface-level: protocolVersion / serverInfo.version / instructions.
    assert fp_with(init=_initialize(version="2025-03-26")) != base_fp
    assert fp_with(init=_initialize(server_info=ServerInfo(name="srv", title="Srv", version="2.0"))) != base_fp
    assert fp_with(init=_initialize(instructions="be terse")) != base_fp


def test_fingerprint_is_deterministic_across_runs() -> None:
    surface = DiscoverySurface.from_discovery(
        _initialize(),
        _listings(tools=[_tool("a")], prompts=[_prompt("p")]),
    )
    assert surface.fingerprint() == surface.fingerprint()


# ===========================================================================
# DB row mapping + round-trip
# ===========================================================================


def test_to_capability_rows_shape_and_order() -> None:
    surface = DiscoverySurface.from_discovery(
        _initialize(),
        _listings(
            tools=[_tool("a")],
            resources=[_resource("r")],
            resource_templates=[_resource_template("t")],
            prompts=[_prompt("p")],
        ),
    )
    rows = surface.to_capability_rows("ver-1")
    assert [r["item_type"] for r in rows] == [
        ITEM_TYPE_TOOL,
        ITEM_TYPE_RESOURCE,
        ITEM_TYPE_RESOURCE_TEMPLATE,
        ITEM_TYPE_PROMPT,
    ]
    # Every row carries the version id and the full column set.
    expected_cols = {
        "version_id", "item_type", "name", "title", "description", "input_schema",
        "output_schema", "annotations", "uri", "uri_template", "raw", "ordinal",
    }
    for row in rows:
        assert set(row) == expected_cols
        assert row["version_id"] == "ver-1"


def test_capability_items_round_trip_through_rows() -> None:
    surface = DiscoverySurface.from_discovery(
        _initialize(),
        _listings(
            tools=[_tool("a"), _tool("b", with_modern=False)],
            resources=[_resource("r")],
            resource_templates=[_resource_template("t")],
            prompts=[_prompt("p")],
        ),
    )
    rows = surface.to_capability_rows("ver-1")
    rebuilt = DiscoverySurface.from_rows(
        rows,
        protocol_version=surface.protocol_version,
        server_info=surface.server_info,
        capabilities=surface.capabilities,
        instructions=surface.instructions,
    )
    assert rebuilt == surface


def test_from_rows_sorts_by_ordinal_regardless_of_input_order() -> None:
    surface = DiscoverySurface.from_discovery(
        _initialize(), _listings(tools=[_tool("a"), _tool("b"), _tool("c")])
    )
    rows = surface.to_capability_rows("ver-1")
    # Read the rows back shuffled (as a DB might return them unordered).
    shuffled = [rows[2], rows[0], rows[1]]
    rebuilt = DiscoverySurface.from_rows(shuffled)
    assert [t.name for t in rebuilt.tools] == ["a", "b", "c"]
    assert [t.ordinal for t in rebuilt.tools] == [0, 1, 2]


def test_from_row_ignores_db_only_columns() -> None:
    item = CapabilityItem.from_tool(_tool("a"), 0)
    row = item.to_row("ver-1")
    row["id"] = "uuid-here"
    row["created_at"] = "2026-06-26T00:00:00Z"
    assert CapabilityItem.from_row(row) == item


def test_to_version_row_maps_snapshot_columns() -> None:
    surface = DiscoverySurface.from_discovery(_initialize(), _listings(tools=[_tool("a")]))
    row = surface.to_version_row()
    assert row["protocol_version"] == "2025-06-18"
    assert row["server_name"] == "srv"
    assert row["server_title"] == "Srv"
    assert row["server_version"] == "1.0"
    assert row["instructions"] == "be helpful"
    assert row["capabilities"] == {"tools": {}, "resources": {}, "prompts": {}}
    assert row["surface_fingerprint"] == surface.fingerprint()


def test_legacy_server_round_trip_keeps_nulls() -> None:
    surface = DiscoverySurface.from_discovery(
        _initialize(version="2025-03-26", server_info=ServerInfo(name="old", version="0.9")),
        _listings(tools=[_tool("legacy", with_modern=False)]),
    )
    # No modern fields anywhere.
    assert surface.server_info.title is None
    assert surface.tools[0].title is None
    assert surface.tools[0].output_schema is None
    row = surface.to_version_row()
    assert row["server_title"] is None
    rebuilt = DiscoverySurface.from_rows(
        surface.to_capability_rows("v"),
        protocol_version=surface.protocol_version,
        server_info=surface.server_info,
        capabilities=surface.capabilities,
        instructions=surface.instructions,
    )
    assert rebuilt == surface


def test_empty_surface_round_trips() -> None:
    surface = DiscoverySurface.from_discovery(_initialize(capabilities={}), _listings())
    assert surface.all_items() == ()
    assert surface.to_capability_rows("v") == []
    rebuilt = DiscoverySurface.from_rows([], capabilities={})
    assert rebuilt.all_items() == ()
