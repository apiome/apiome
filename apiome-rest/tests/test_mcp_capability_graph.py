"""Unit tests for the capability relationship graph engine (V2-MCP-29.2 / MCAT-15.2, #4632).

These exercise :mod:`app.mcp_capability_graph`: the pure, no-I/O module that turns a normalized
:class:`~app.mcp_client.normalize.DiscoverySurface` into a node-link graph — one node per capability
plus edges inferred from three *concrete* signals (a prompt naming a tool, a tool referencing a
resource URI, and two items sharing a schema type). The tests pin the documented contract on
hand-built fixtures and cover the acceptance criteria:

* a graph renders for a multi-capability server, with isolated nodes shown;
* edge inference is unit-tested per signal;
* no edge is invented without a concrete signal (precision over recall);
* the schema walk survives nested/``$ref``/array schemas;
* identical surfaces produce identical graphs (deterministic ``graph_fingerprint``).
"""

from __future__ import annotations

from typing import Any, List, Optional

from app.mcp_capability_graph import (
    EDGE_PROMPT_REFERENCE,
    EDGE_RESOURCE_REFERENCE,
    EDGE_SHARED_TYPE,
    MAX_SCHEMA_DEPTH,
    MIN_NAME_REF_LENGTH,
    CapabilityGraph,
    GraphEdge,
    GraphNode,
    _references_token,
    _template_prefix,
    compute_capability_graph,
)
from app.mcp_client.handshake import ServerInfo
from app.mcp_client.normalize import (
    ITEM_TYPE_PROMPT,
    ITEM_TYPE_RESOURCE,
    ITEM_TYPE_RESOURCE_TEMPLATE,
    ITEM_TYPE_TOOL,
    CapabilityItem,
    DiscoverySurface,
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


def _edges_of_kind(graph: CapabilityGraph, kind: str) -> List[GraphEdge]:
    return [e for e in graph.edges if e.kind == kind]


def _node_by_name(graph: CapabilityGraph, name: str) -> GraphNode:
    return next(n for n in graph.nodes if n.name == name)


# ============================================================================================
# Nodes: every capability becomes a node; isolated nodes are shown.
# ============================================================================================


def test_every_capability_becomes_a_node_in_order() -> None:
    surface = _surface(
        tools=[_tool("search", 0), _tool("write", 1)],
        resources=[_resource("cfg", 0)],
        resource_templates=[_resource_template("byid", 0)],
        prompts=[_prompt("triage", 0)],
    )
    graph = compute_capability_graph(surface)

    assert graph.node_count == 5
    assert [n.name for n in graph.nodes] == ["search", "write", "cfg", "byid", "triage"]
    # Node ids are the stable, Mermaid-safe kind_prefix + ordinal.
    assert [n.id for n in graph.nodes] == ["t_0", "t_1", "r_0", "rt_0", "p_0"]
    assert [n.item_type for n in graph.nodes] == [
        ITEM_TYPE_TOOL,
        ITEM_TYPE_TOOL,
        ITEM_TYPE_RESOURCE,
        ITEM_TYPE_RESOURCE_TEMPLATE,
        ITEM_TYPE_PROMPT,
    ]


def test_node_label_prefers_title_then_name() -> None:
    surface = _surface(tools=[_tool("search", 0, title="Search the corpus"), _tool("write", 1)])
    graph = compute_capability_graph(surface)
    assert _node_by_name(graph, "search").label == "Search the corpus"
    # No title → the programmatic name is the label; title stays None.
    write = _node_by_name(graph, "write")
    assert write.label == "write"
    assert write.title is None


def test_isolated_nodes_are_shown_with_zero_degree() -> None:
    # Two unrelated tools: both are nodes, both isolated, no edges invented.
    surface = _surface(tools=[_tool("alpha", 0), _tool("beta", 1)])
    graph = compute_capability_graph(surface)
    assert graph.edge_count == 0
    assert graph.isolated_count == 2
    assert all(n.degree == 0 for n in graph.nodes)


def test_empty_surface_yields_empty_graph() -> None:
    graph = compute_capability_graph(_surface())
    assert graph.node_count == 0
    assert graph.edge_count == 0
    assert graph.isolated_count == 0
    assert graph.nodes == ()
    assert graph.edges == ()
    # Still a stable fingerprint (of the empty payload).
    assert isinstance(graph.graph_fingerprint, str) and graph.graph_fingerprint


# ============================================================================================
# Signal 1 — prompt → tool (a prompt whose text names a tool).
# ============================================================================================


def test_prompt_description_naming_tool_creates_directed_edge() -> None:
    surface = _surface(
        tools=[_tool("search_logs", 0)],
        prompts=[_prompt("triage", 0, description="Use search_logs to find the error.")],
    )
    graph = compute_capability_graph(surface)
    edges = _edges_of_kind(graph, EDGE_PROMPT_REFERENCE)
    assert len(edges) == 1
    edge = edges[0]
    assert (edge.source, edge.target) == ("p_0", "t_0")
    assert edge.directed is True
    assert edge.label == "search_logs"
    assert edge.signals == ("search_logs",)


def test_prompt_argument_text_naming_tool_creates_edge() -> None:
    # The tool name appears only in a prompt *argument* description (read from raw.arguments).
    surface = _surface(
        tools=[_tool("fetch_page", 0)],
        prompts=[
            _prompt(
                "summarize",
                0,
                raw={"arguments": [{"name": "url", "description": "passed to fetch_page"}]},
            )
        ],
    )
    graph = compute_capability_graph(surface)
    assert len(_edges_of_kind(graph, EDGE_PROMPT_REFERENCE)) == 1


def test_prompt_reference_requires_whole_token_not_substring() -> None:
    # "search" must not match inside "research" — precision over recall.
    surface = _surface(
        tools=[_tool("search", 0)],
        prompts=[_prompt("p", 0, description="This is background research only.")],
    )
    graph = compute_capability_graph(surface)
    assert _edges_of_kind(graph, EDGE_PROMPT_REFERENCE) == []


def test_prompt_reference_skips_too_short_tool_names() -> None:
    # A 2-char tool name is below MIN_NAME_REF_LENGTH: too collision-prone to be a concrete signal.
    assert MIN_NAME_REF_LENGTH == 3
    surface = _surface(
        tools=[_tool("go", 0)],
        prompts=[_prompt("p", 0, description="then go run it")],
    )
    graph = compute_capability_graph(surface)
    assert _edges_of_kind(graph, EDGE_PROMPT_REFERENCE) == []


def test_prompt_reference_is_case_sensitive() -> None:
    # Tool names are case-sensitive identifiers; a differently-cased mention is not a reference.
    surface = _surface(
        tools=[_tool("SearchLogs", 0)],
        prompts=[_prompt("p", 0, description="use searchlogs here")],
    )
    graph = compute_capability_graph(surface)
    assert _edges_of_kind(graph, EDGE_PROMPT_REFERENCE) == []


def test_prompt_naming_two_tools_yields_two_edges() -> None:
    surface = _surface(
        tools=[_tool("open_file", 0), _tool("close_file", 1)],
        prompts=[_prompt("p", 0, description="open_file then close_file")],
    )
    graph = compute_capability_graph(surface)
    edges = _edges_of_kind(graph, EDGE_PROMPT_REFERENCE)
    assert {e.target for e in edges} == {"t_0", "t_1"}


# ============================================================================================
# Signal 2 — tool → resource (a tool referencing a resource URI).
# ============================================================================================


def test_tool_description_referencing_resource_uri_creates_edge() -> None:
    surface = _surface(
        tools=[_tool("read_cfg", 0, description="Reads config://app/settings for defaults.")],
        resources=[_resource("cfg", 0, uri="config://app/settings")],
    )
    graph = compute_capability_graph(surface)
    edges = _edges_of_kind(graph, EDGE_RESOURCE_REFERENCE)
    assert len(edges) == 1
    edge = edges[0]
    assert (edge.source, edge.target) == ("t_0", "r_0")
    assert edge.directed is True
    assert edge.label == "config://app/settings"


def test_tool_uri_shaped_param_default_referencing_resource_uri() -> None:
    # The URI appears only in a uri-shaped parameter's default literal, not the description.
    surface = _surface(
        tools=[
            _tool(
                "load",
                0,
                input_schema={
                    "type": "object",
                    "properties": {
                        "target_uri": {
                            "type": "string",
                            "format": "uri",
                            "default": "file:///data/main.db",
                        }
                    },
                },
            )
        ],
        resources=[_resource("db", 0, uri="file:///data/main.db")],
    )
    graph = compute_capability_graph(surface)
    assert len(_edges_of_kind(graph, EDGE_RESOURCE_REFERENCE)) == 1


def test_no_resource_edge_without_a_literal_uri_mention() -> None:
    # The tool talks about "the database" but never names the concrete URI: no invented edge.
    surface = _surface(
        tools=[_tool("load", 0, description="Loads records from the database.")],
        resources=[_resource("db", 0, uri="file:///data/main.db")],
    )
    graph = compute_capability_graph(surface)
    assert _edges_of_kind(graph, EDGE_RESOURCE_REFERENCE) == []


def test_tool_referencing_resource_template_prefix() -> None:
    surface = _surface(
        tools=[_tool("get_user", 0, description="Fetches db://users/ records by id.")],
        resource_templates=[_resource_template("user", 0, uri_template="db://users/{id}")],
    )
    graph = compute_capability_graph(surface)
    edges = _edges_of_kind(graph, EDGE_RESOURCE_REFERENCE)
    assert len(edges) == 1
    assert edges[0].target == "rt_0"
    assert edges[0].label == "db://users/"


def test_template_prefix_helper_rejects_schemeless_or_short_prefixes() -> None:
    assert _template_prefix("db://users/{id}") == "db://users/"
    assert _template_prefix("file:///a/{b}") == "file:///a/"
    # No scheme (no ":") → not a concrete signal.
    assert _template_prefix("/records/{id}") is None
    # Too short (< 4 chars before the brace) → skipped.
    assert _template_prefix("x:{id}") is None
    assert _template_prefix(None) is None


# ============================================================================================
# Signal 3 — shared type (two items whose schemas share a $ref or non-generic title).
# ============================================================================================


def test_shared_ref_creates_undirected_edge() -> None:
    shared = {"type": "object", "properties": {"q": {"$ref": "#/$defs/Filter"}}}
    surface = _surface(tools=[_tool("a", 0, input_schema=shared), _tool("b", 1, input_schema=shared)])
    graph = compute_capability_graph(surface)
    edges = _edges_of_kind(graph, EDGE_SHARED_TYPE)
    assert len(edges) == 1
    edge = edges[0]
    assert edge.directed is False
    # Node order is normalized (source <= target) and de-duplicated to a single edge.
    assert (edge.source, edge.target) == ("t_0", "t_1")
    assert "#/$defs/Filter" in edge.signals


def test_shared_edge_across_input_and_output_schema() -> None:
    # Tool A exposes the type on its *output*; tool B on its *input* — still a shared coupling.
    a = _tool("a", 0, output_schema={"$ref": "#/$defs/Invoice"})
    b = _tool("b", 1, input_schema={"type": "object", "properties": {"x": {"$ref": "#/$defs/Invoice"}}})
    graph = compute_capability_graph(_surface(tools=[a, b]))
    assert len(_edges_of_kind(graph, EDGE_SHARED_TYPE)) == 1


def test_generic_titles_do_not_create_shared_edges() -> None:
    # Two schemas both titled "Result" are not thereby related (title is in the stop-list).
    a = _tool("a", 0, input_schema={"type": "object", "title": "Result"})
    b = _tool("b", 1, input_schema={"type": "object", "title": "Result"})
    graph = compute_capability_graph(_surface(tools=[a, b]))
    assert _edges_of_kind(graph, EDGE_SHARED_TYPE) == []


def test_specific_shared_title_creates_edge() -> None:
    a = _tool("a", 0, input_schema={"type": "object", "title": "InvoiceLine"})
    b = _tool("b", 1, output_schema={"type": "object", "title": "InvoiceLine"})
    graph = compute_capability_graph(_surface(tools=[a, b]))
    edges = _edges_of_kind(graph, EDGE_SHARED_TYPE)
    assert len(edges) == 1
    assert edges[0].signals == ("title:InvoiceLine",)


def test_shared_type_across_three_tools_forms_pairwise_edges() -> None:
    schema = {"$ref": "#/$defs/Common"}
    surface = _surface(
        tools=[
            _tool("a", 0, input_schema=schema),
            _tool("b", 1, input_schema=schema),
            _tool("c", 2, input_schema=schema),
        ]
    )
    graph = compute_capability_graph(surface)
    edges = _edges_of_kind(graph, EDGE_SHARED_TYPE)
    # Three items sharing one type ⇒ the three unordered pairs.
    assert {(e.source, e.target) for e in edges} == {("t_0", "t_1"), ("t_0", "t_2"), ("t_1", "t_2")}


# ============================================================================================
# Totality — adversarial schemas must not throw.
# ============================================================================================


def test_walk_survives_recursive_and_deep_schemas() -> None:
    recursive: dict = {"type": "object", "properties": {}}
    recursive["properties"]["self"] = recursive  # cyclic reference
    deep: dict = {"type": "object"}
    cursor = deep
    for _ in range(MAX_SCHEMA_DEPTH * 2):
        child: dict = {"type": "object", "properties": {}}
        cursor["properties"] = {"next": child}
        cursor = child
    surface = _surface(
        tools=[_tool("a", 0, input_schema=recursive), _tool("b", 1, output_schema=deep)]
    )
    # Must simply not raise.
    graph = compute_capability_graph(surface)
    assert graph.node_count == 2


def test_malformed_schema_values_are_ignored() -> None:
    surface = _surface(
        tools=[
            _tool("a", 0, input_schema={"properties": "not-a-dict", "items": 5}),
            _tool("b", 1, input_schema=None),
        ]
    )
    graph = compute_capability_graph(surface)
    assert graph.edge_count == 0


# ============================================================================================
# Reference-token matcher unit tests.
# ============================================================================================


def test_references_token_boundaries() -> None:
    assert _references_token("run search now", "search") is True
    assert _references_token("(search)", "search") is True
    assert _references_token("call `search`", "search") is True
    assert _references_token("research topic", "search") is False
    assert _references_token("search_v2 ran", "search") is False
    assert _references_token("", "search") is False
    assert _references_token("search", "") is False


# ============================================================================================
# Determinism & degree accounting.
# ============================================================================================


def test_identical_surfaces_produce_identical_graphs() -> None:
    def build() -> DiscoverySurface:
        return _surface(
            tools=[_tool("search_logs", 0, description="reads file:///l.log")],
            resources=[_resource("l", 0, uri="file:///l.log")],
            prompts=[_prompt("p", 0, description="call search_logs")],
        )

    a = compute_capability_graph(build())
    b = compute_capability_graph(build())
    assert a.graph_fingerprint == b.graph_fingerprint
    assert a.as_dict() == b.as_dict()


def test_degree_counts_incident_edges_for_both_endpoints() -> None:
    surface = _surface(
        tools=[_tool("search_logs", 0)],
        prompts=[_prompt("p", 0, description="call search_logs and search_logs again")],
    )
    graph = compute_capability_graph(surface)
    # The duplicate mention is de-duplicated to a single edge.
    assert graph.edge_count == 1
    assert _node_by_name(graph, "search_logs").degree == 1
    assert _node_by_name(graph, "p").degree == 1
    assert graph.isolated_count == 0


def test_as_dict_shape_is_stable() -> None:
    surface = _surface(tools=[_tool("a", 0)])
    payload = compute_capability_graph(surface).as_dict()
    assert set(payload) == {
        "nodes",
        "edges",
        "node_count",
        "edge_count",
        "isolated_count",
        "graph_fingerprint",
    }
    assert set(payload["nodes"][0]) == {"id", "item_type", "name", "title", "label", "degree"}


def test_multi_capability_server_renders_mixed_edges() -> None:
    # An end-to-end fixture proving all three signals coexist on one realistic server.
    surface = _surface(
        tools=[
            _tool(
                "search_docs",
                0,
                description="Searches docs://index and returns matches.",
                input_schema={"type": "object", "properties": {"filter": {"$ref": "#/$defs/Filter"}}},
            ),
            _tool(
                "count_docs",
                1,
                input_schema={"type": "object", "properties": {"filter": {"$ref": "#/$defs/Filter"}}},
            ),
        ],
        resources=[_resource("index", 0, uri="docs://index")],
        prompts=[_prompt("research", 0, description="Use search_docs to gather sources.")],
    )
    graph = compute_capability_graph(surface)
    kinds = {e.kind for e in graph.edges}
    assert kinds == {EDGE_PROMPT_REFERENCE, EDGE_RESOURCE_REFERENCE, EDGE_SHARED_TYPE}
    assert graph.isolated_count == 0
