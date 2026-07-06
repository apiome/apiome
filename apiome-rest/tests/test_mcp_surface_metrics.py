"""Unit tests for the deterministic capability-surface metrics engine (V2-MCP-28.1, #4627).

These exercise :mod:`app.mcp_surface_metrics`: the pure, no-I/O module that walks a normalized
:class:`~app.mcp_client.normalize.DiscoverySurface` and returns a stable
:class:`~app.mcp_surface_metrics.SurfaceMetrics` object (per-type counts, per-tool input-schema
complexity, output-schema presence, annotation coverage, and documentation coverage) together
with a ``metrics_fingerprint``.

The tests pin the documented contract on hand-built fixtures and cover the acceptance criteria:
a documented metric object for a known surface, a schema walk that survives nested/``$ref``/array
schemas, coverage percentages bounded to 0-100, and identical output for identical surfaces.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.mcp_client.handshake import ServerInfo
from app.mcp_client.normalize import (
    ITEM_TYPE_PROMPT,
    ITEM_TYPE_RESOURCE,
    ITEM_TYPE_RESOURCE_TEMPLATE,
    ITEM_TYPE_TOOL,
    CapabilityItem,
    DiscoverySurface,
)
from app.mcp_surface_metrics import (
    ANNOTATION_HINTS,
    MAX_SCHEMA_DEPTH,
    AnnotationCoverage,
    SurfaceMetrics,
    ToolComplexity,
    TypeCounts,
    _pct,
    _walk_schema,
    compute_surface_metrics,
)

# --- Fixture builders -----------------------------------------------------------------------


def _tool(name: str, ordinal: int = 0, **extra: Any) -> CapabilityItem:
    return CapabilityItem(item_type=ITEM_TYPE_TOOL, name=name, ordinal=ordinal, **extra)


def _resource(name: str, ordinal: int = 0, **extra: Any) -> CapabilityItem:
    return CapabilityItem(item_type=ITEM_TYPE_RESOURCE, name=name, ordinal=ordinal, **extra)


def _resource_template(name: str, ordinal: int = 0, **extra: Any) -> CapabilityItem:
    return CapabilityItem(
        item_type=ITEM_TYPE_RESOURCE_TEMPLATE, name=name, ordinal=ordinal, **extra
    )


def _prompt(name: str, ordinal: int = 0, **extra: Any) -> CapabilityItem:
    return CapabilityItem(item_type=ITEM_TYPE_PROMPT, name=name, ordinal=ordinal, **extra)


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


# A richly-populated tool: two top-level params (one required, one optional), a nested object,
# an array of objects, an enum and a oneOf, one documented param and one undocumented, plus an
# output schema and the full behavioural-annotation set.
_RICH_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["query", "not_a_real_property"],  # stray required name must be ignored
    "properties": {
        "query": {"type": "string", "description": "The search text."},
        "filters": {
            "type": "object",
            "properties": {
                "kind": {"enum": ["a", "b"]},
                "nested": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"leaf": {"type": "string"}},
                    },
                },
            },
        },
        "mode": {"oneOf": [{"type": "string"}, {"type": "integer"}]},
    },
}

RICH_TOOL = _tool(
    "search",
    ordinal=0,
    title="Search",
    description="Search the corpus.",
    input_schema=_RICH_TOOL_SCHEMA,
    output_schema={"type": "object", "properties": {"hits": {"type": "integer"}}},
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)


# --- _walk_schema (complexity primitive) ----------------------------------------------------


def test_walk_flat_object_is_depth_one() -> None:
    walk = _walk_schema({"type": "object", "properties": {"a": {"type": "string"}}}, MAX_SCHEMA_DEPTH)
    assert walk.depth == 1
    assert walk.uses_enum is False
    assert walk.uses_one_of is False


def test_walk_scalar_leaf_is_depth_zero() -> None:
    assert _walk_schema({"type": "string"}, MAX_SCHEMA_DEPTH).depth == 0


def test_walk_non_mapping_is_empty() -> None:
    walk = _walk_schema(None, MAX_SCHEMA_DEPTH)
    assert walk.depth == 0 and walk.uses_enum is False and walk.uses_one_of is False


def test_walk_counts_nested_object_and_array_levels() -> None:
    # object -> filters(object) -> nested(array) -> items(object) -> leaf  == depth 4
    walk = _walk_schema(_RICH_TOOL_SCHEMA, MAX_SCHEMA_DEPTH)
    assert walk.depth == 4
    assert walk.uses_enum is True
    assert walk.uses_one_of is True


def test_walk_treats_ref_node_as_leaf_without_resolving() -> None:
    schema = {"type": "object", "properties": {"self": {"$ref": "#/$defs/Node"}}}
    walk = _walk_schema(schema, MAX_SCHEMA_DEPTH)
    assert walk.depth == 1  # object with a leaf $ref property


def test_walk_survives_self_referential_ref_definitions() -> None:
    # A recursive $ref must not send the walk into infinite recursion; $refs are never resolved.
    schema = {
        "type": "object",
        "properties": {"child": {"$ref": "#/$defs/Node"}},
        "$defs": {"Node": {"$ref": "#/$defs/Node"}},
    }
    walk = _walk_schema(schema, MAX_SCHEMA_DEPTH)
    assert walk.depth == 1


def test_walk_handles_tuple_items_and_prefix_items() -> None:
    draft04 = {"type": "array", "items": [{"type": "string"}, {"enum": [1, 2]}]}
    assert _walk_schema(draft04, MAX_SCHEMA_DEPTH).uses_enum is True
    v2020 = {"type": "array", "prefixItems": [{"oneOf": [{"type": "string"}]}]}
    assert _walk_schema(v2020, MAX_SCHEMA_DEPTH).uses_one_of is True


def test_walk_saturates_at_depth_budget() -> None:
    # Build a deeply nested object chain longer than the budget; depth must clamp, not overflow.
    schema: Dict[str, Any] = {"type": "object", "properties": {"leaf": {"type": "string"}}}
    for _ in range(MAX_SCHEMA_DEPTH + 20):
        schema = {"type": "object", "properties": {"child": schema}}
    depth = _walk_schema(schema, MAX_SCHEMA_DEPTH).depth
    assert depth == MAX_SCHEMA_DEPTH


# --- _pct (bounded percentage) --------------------------------------------------------------


def test_pct_zero_denominator_is_zero() -> None:
    assert _pct(0, 0) == 0.0
    assert _pct(5, 0) == 0.0


def test_pct_is_bounded_and_rounded() -> None:
    assert _pct(1, 3) == 33.33
    assert _pct(2, 3) == 66.67
    assert _pct(3, 3) == 100.0
    assert _pct(0, 3) == 0.0


# --- Type counts ----------------------------------------------------------------------------


def test_type_counts_partition_and_total() -> None:
    surface = _surface(
        tools=[_tool("a"), _tool("b", 1)],
        resources=[_resource("r")],
        resource_templates=[_resource_template("t")],
        prompts=[_prompt("p"), _prompt("q", 1), _prompt("z", 2)],
    )
    counts = compute_surface_metrics(surface).type_counts
    assert counts == TypeCounts(
        tools=2, resources=1, resource_templates=1, prompts=3, total=7
    )


def test_empty_surface_is_all_zero_and_total_zero() -> None:
    metrics = compute_surface_metrics(_surface())
    assert metrics.type_counts == TypeCounts(0, 0, 0, 0, 0)
    assert metrics.tool_complexity == ()
    assert metrics.output_schema_count == 0
    assert metrics.documentation_coverage.description_pct == 0.0
    assert metrics.annotation_coverage.tool_count == 0


# --- Tool complexity ------------------------------------------------------------------------


def test_rich_tool_complexity_profile() -> None:
    metrics = compute_surface_metrics(_surface(tools=[RICH_TOOL]))
    assert len(metrics.tool_complexity) == 1
    tool = metrics.tool_complexity[0]
    assert tool == ToolComplexity(
        name="search",
        property_count=3,  # query, filters, mode
        required_count=1,  # only "query" is a real required property; the stray name is dropped
        optional_count=2,
        documented_property_count=1,  # only "query" carries a description
        max_nesting_depth=4,
        uses_enum=True,
        uses_one_of=True,
        has_output_schema=True,
    )


def test_tool_without_input_schema_is_all_zero() -> None:
    tool = _tool("noargs", input_schema=None, output_schema=None)
    profile = compute_surface_metrics(_surface(tools=[tool])).tool_complexity[0]
    assert profile.property_count == 0
    assert profile.required_count == 0
    assert profile.optional_count == 0
    assert profile.documented_property_count == 0
    assert profile.max_nesting_depth == 0
    assert profile.uses_enum is False
    assert profile.uses_one_of is False
    assert profile.has_output_schema is False


def test_tool_with_non_object_input_schema_does_not_throw() -> None:
    # A malformed (non-object) input schema must be tolerated, not raise.
    tool = _tool("weird", input_schema={"type": "string", "enum": ["x"]})
    profile = compute_surface_metrics(_surface(tools=[tool])).tool_complexity[0]
    assert profile.property_count == 0
    assert profile.max_nesting_depth == 0  # a scalar leaf
    assert profile.uses_enum is True  # enum still detected on the root


def test_optional_never_negative_when_required_lists_unknown_names() -> None:
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a", "b", "c"]}
    profile = compute_surface_metrics(_surface(tools=[_tool("t", input_schema=schema)])).tool_complexity[0]
    assert profile.required_count == 1
    assert profile.optional_count == 0


def test_output_schema_count_tracks_tools_with_output_schema() -> None:
    surface = _surface(
        tools=[
            _tool("a", 0, output_schema={"type": "object"}),
            _tool("b", 1, output_schema=None),
            _tool("c", 2, output_schema={"type": "array"}),
        ]
    )
    metrics = compute_surface_metrics(surface)
    assert metrics.output_schema_count == 2
    assert [t.has_output_schema for t in metrics.tool_complexity] == [True, False, True]


def test_tool_complexity_preserves_surface_order() -> None:
    surface = _surface(tools=[_tool("first", 0), _tool("second", 1), _tool("third", 2)])
    names = [t.name for t in compute_surface_metrics(surface).tool_complexity]
    assert names == ["first", "second", "third"]


# --- Annotation coverage --------------------------------------------------------------------


def test_annotation_coverage_counts_asserted_hints() -> None:
    surface = _surface(
        tools=[
            RICH_TOOL,  # all four hints asserted
            _tool("t2", 1, annotations={"readOnlyHint": False}),  # readOnlyHint:false still asserted
            _tool("t3", 2, annotations={"readOnlyHint": "yes"}),  # non-bool => not asserted
            _tool("t4", 3),  # no annotations at all
        ]
    )
    cov = compute_surface_metrics(surface).annotation_coverage
    assert cov == AnnotationCoverage(
        tool_count=4,
        annotated_tools=2,  # RICH_TOOL and t2
        read_only_hint=2,  # RICH_TOOL (True) + t2 (False)
        destructive_hint=1,
        idempotent_hint=1,
        open_world_hint=1,
    )


def test_annotation_hints_constant_matches_wire_spelling() -> None:
    assert ANNOTATION_HINTS == (
        "readOnlyHint",
        "destructiveHint",
        "idempotentHint",
        "openWorldHint",
    )


# --- Documentation coverage -----------------------------------------------------------------


def test_documentation_coverage_item_and_param_levels() -> None:
    surface = _surface(
        tools=[RICH_TOOL],  # described + titled; 3 params, 1 documented
        resources=[
            _resource("r1", 0, description="A resource."),  # described, not titled
            _resource("r2", 1, title="R2"),  # titled, not described
        ],
        prompts=[_prompt("p1", 0)],  # neither
    )
    cov = compute_surface_metrics(surface).documentation_coverage
    assert cov.item_count == 4
    assert cov.described_items == 2  # RICH_TOOL, r1
    assert cov.titled_items == 2  # RICH_TOOL, r2
    assert cov.description_pct == 50.0
    assert cov.title_pct == 50.0
    assert cov.tool_param_count == 3
    assert cov.documented_tool_params == 1
    assert cov.tool_param_description_pct == _pct(1, 3)


def test_blank_strings_do_not_count_as_documented() -> None:
    tool = _tool(
        "t",
        title="   ",
        description="",
        input_schema={"type": "object", "properties": {"a": {"type": "string", "description": "  "}}},
    )
    cov = compute_surface_metrics(_surface(tools=[tool])).documentation_coverage
    assert cov.described_items == 0
    assert cov.titled_items == 0
    assert cov.documented_tool_params == 0


def test_coverage_percentages_within_bounds_across_surfaces() -> None:
    surfaces = [
        _surface(),
        _surface(tools=[RICH_TOOL]),
        _surface(prompts=[_prompt("p", description="d", title="T")]),
        _surface(tools=[_tool("bare")], resources=[_resource("r")]),
    ]
    for surface in surfaces:
        cov = compute_surface_metrics(surface).documentation_coverage
        for value in (cov.description_pct, cov.title_pct, cov.tool_param_description_pct):
            assert 0.0 <= value <= 100.0


# --- Determinism / purity -------------------------------------------------------------------


def test_identical_surfaces_yield_identical_metrics_and_fingerprint() -> None:
    a = compute_surface_metrics(_surface(tools=[RICH_TOOL], resources=[_resource("r", description="d")]))
    b = compute_surface_metrics(_surface(tools=[RICH_TOOL], resources=[_resource("r", description="d")]))
    assert a == b
    assert a.metrics_fingerprint == b.metrics_fingerprint
    assert a.as_dict() == b.as_dict()


def test_fingerprint_is_stable_hex_and_changes_with_content() -> None:
    base = compute_surface_metrics(_surface(tools=[RICH_TOOL]))
    assert isinstance(base.metrics_fingerprint, str)
    assert len(base.metrics_fingerprint) == 64  # sha256 hex
    changed = compute_surface_metrics(_surface(tools=[RICH_TOOL, _tool("extra", 1)]))
    assert changed.metrics_fingerprint != base.metrics_fingerprint


def test_fingerprint_excludes_itself_and_matches_recompute() -> None:
    metrics = compute_surface_metrics(_surface(tools=[RICH_TOOL]))
    payload = metrics.as_dict()
    # The published fingerprint is a field on the payload but is not part of what it hashes.
    assert "metrics_fingerprint" in payload
    assert payload["metrics_fingerprint"] == metrics.metrics_fingerprint


def test_compute_does_not_mutate_surface() -> None:
    schema_before = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    tool = _tool("t", input_schema=dict(schema_before))
    surface = _surface(tools=[tool])
    compute_surface_metrics(surface)
    assert tool.input_schema == schema_before  # untouched


# --- Full object shape (documented metric object) -------------------------------------------


def test_as_dict_has_documented_shape() -> None:
    metrics = compute_surface_metrics(_surface(tools=[RICH_TOOL]))
    payload = metrics.as_dict()
    assert set(payload) == {
        "type_counts",
        "tool_complexity",
        "output_schema_count",
        "annotation_coverage",
        "documentation_coverage",
        "metrics_fingerprint",
    }
    assert isinstance(payload["tool_complexity"], list)
    assert set(payload["type_counts"]) == {
        "tools",
        "resources",
        "resource_templates",
        "prompts",
        "total",
    }
    assert set(payload["tool_complexity"][0]) == {
        "name",
        "property_count",
        "required_count",
        "optional_count",
        "documented_property_count",
        "max_nesting_depth",
        "uses_enum",
        "uses_one_of",
        "has_output_schema",
    }


def test_returns_surface_metrics_instance() -> None:
    assert isinstance(compute_surface_metrics(_surface()), SurfaceMetrics)
