"""
Capability relationship graph over a normalized MCP surface (V2-MCP-29.2 / MCAT-15.2).

A flat list of a server's tools/resources/prompts hides how the pieces relate. This module turns a
:class:`~app.mcp_client.normalize.DiscoverySurface` into a **node-link graph**: one node per
capability (tool / resource / resource template / prompt) and one edge per *concrete* relationship
signal the surface already holds. It is the graph counterpart to :mod:`app.mcp_surface_metrics` and
deliberately mirrors that module's pure, deterministic, value-object style so the same route layer
can fetch-and-shape it and the Insight tab's "Capability relationship graph" panel can render it.

Design goals:

* **Pure** — no database or network access; the caller passes a fully built ``DiscoverySurface``.
* **Deterministic** — the same surface always yields the same graph and the same
  ``graph_fingerprint``, so the result is safe to cache per ``surface_fingerprint``.
* **Total** — the schema/reference walks never throw on adversarial input (nested / ``$ref`` /
  array / combinator schemas, missing fields, non-string values); a depth budget caps recursion.
* **Precision over recall** — an edge is emitted only on a concrete, unambiguous signal. We would
  rather miss a real-but-fuzzy relationship than invent one that is not there. Every heuristic
  below is conservative by construction (whole-token name matches, literal URI occurrences, and a
  stop-listed schema-type overlap).

Edge inference — the three signals, all derived from data already on the surface:

1. **prompt → tool** (``prompt_reference``): a prompt whose text (its ``description`` and the
   ``name``/``description`` of each of its ``arguments``) references a tool's exact ``name`` as a
   whole token. Prompts orchestrate tools, so a prompt naming a tool is a real "drives" edge.
2. **tool → resource** (``resource_reference``): a tool whose text (its ``description`` and the
   string literals of any ``uri``-shaped input-schema parameter — ``const``/``default``/``enum``/
   ``examples``) contains a resource's concrete ``uri`` verbatim, or a resource template's literal
   URI prefix (the part before its first ``{`` placeholder, when that prefix carries a scheme).
3. **shared type** (``shared_type``, undirected): two items whose JSON Schemas share a type
   identifier — a ``$ref`` target or a (non-generic) schema ``title`` — appearing in either item's
   ``input_schema`` or ``output_schema``. Shared schema types are a real structural coupling.

Isolated nodes (degree 0) are always included: the panel shows them explicitly.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .mcp_client.normalize import (
    ITEM_TYPE_PROMPT,
    ITEM_TYPE_RESOURCE,
    ITEM_TYPE_RESOURCE_TEMPLATE,
    ITEM_TYPE_TOOL,
    CapabilityItem,
    DiscoverySurface,
)

# --- Configuration --------------------------------------------------------------------------

#: Maximum schema nesting the reference/type walks descend before they stop recursing. Mirrors
#: :data:`app.mcp_surface_metrics.MAX_SCHEMA_DEPTH`; it exists only so a pathological or malicious
#: schema cannot exhaust the Python recursion limit — realistic schemas never reach it.
MAX_SCHEMA_DEPTH: int = 64

#: Node-id prefix per capability kind. A node id is ``"{prefix}_{ordinal}"`` — unique within the
#: surface (ordinals are unique per kind), deterministic, and safe to use verbatim as a Mermaid id.
_KIND_PREFIX: Dict[str, str] = {
    ITEM_TYPE_TOOL: "t",
    ITEM_TYPE_RESOURCE: "r",
    ITEM_TYPE_RESOURCE_TEMPLATE: "rt",
    ITEM_TYPE_PROMPT: "p",
}

#: The three edge kinds. ``prompt_reference`` and ``resource_reference`` are directed (source →
#: target); ``shared_type`` is undirected (a mutual structural coupling).
EDGE_PROMPT_REFERENCE: str = "prompt_reference"
EDGE_RESOURCE_REFERENCE: str = "resource_reference"
EDGE_SHARED_TYPE: str = "shared_type"

#: Shortest capability ``name`` we will treat as a referenceable token in a prompt's text. Very
#: short names (1-2 chars) collide with ordinary words too easily; skipping them protects precision
#: at a small, documented cost to recall.
MIN_NAME_REF_LENGTH: int = 3

#: Schema ``title`` values too generic to be a meaningful "shared type" signal (compared
#: lower-cased). Two items both titling a schema ``"Result"`` are not thereby related; a ``$ref`` to
#: ``#/$defs/InvoiceLine`` or a shared title ``"InvoiceLine"`` is. Kept conservative on purpose.
_GENERIC_TITLES: frozenset = frozenset(
    {
        "object",
        "string",
        "number",
        "integer",
        "boolean",
        "array",
        "null",
        "any",
        "value",
        "data",
        "item",
        "items",
        "result",
        "results",
        "response",
        "request",
        "input",
        "output",
        "arguments",
        "argument",
        "args",
        "params",
        "parameters",
        "param",
        "options",
        "payload",
        "body",
        "content",
        "metadata",
        "error",
    }
)

#: Property-name substrings (lower-cased) that mark an input-schema parameter as "URI-shaped", so
#: its literal values are worth scanning for resource references. A parameter also qualifies when it
#: declares JSON Schema ``"format": "uri"``.
_URI_PROPERTY_HINTS: Tuple[str, ...] = ("uri", "url", "href", "endpoint", "resource")

#: Characters that may appear inside a capability name/identifier. Used for whole-token matching so
#: ``search`` does not match inside ``research`` or ``search_v2``.
_NAME_CHAR_RE = re.compile(r"[A-Za-z0-9_.\-]")


# --- Node & edge value objects --------------------------------------------------------------


@dataclass(frozen=True)
class GraphNode:
    """One capability rendered as a graph node.

    Attributes:
        id: Stable, Mermaid-safe id (``"{kind_prefix}_{ordinal}"``, e.g. ``"t_0"``).
        item_type: The capability kind (``tool``/``resource``/``resource_template``/``prompt``).
        name: The capability's programmatic name.
        title: Optional human label; ``None`` on older servers that omit it.
        label: Best display label — ``title`` when present, else ``name``.
        degree: Number of edges incident on this node (0 ⇒ isolated).
    """

    id: str
    item_type: str
    name: str
    title: Optional[str]
    label: str
    degree: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "item_type": self.item_type,
            "name": self.name,
            "title": self.title,
            "label": self.label,
            "degree": self.degree,
        }


@dataclass(frozen=True)
class GraphEdge:
    """One inferred relationship between two nodes.

    Attributes:
        source: The source node id (the referencing item for directed edges).
        target: The target node id (the referenced item for directed edges).
        kind: One of :data:`EDGE_PROMPT_REFERENCE` / :data:`EDGE_RESOURCE_REFERENCE` /
            :data:`EDGE_SHARED_TYPE`.
        directed: ``True`` for the two reference kinds; ``False`` for ``shared_type``.
        label: A short human label for the edge (the referenced name/URI, or the shared type).
        signals: The concrete evidence for the edge (referenced tokens, URIs, or shared type ids),
            sorted and de-duplicated.
    """

    source: str
    target: str
    kind: str
    directed: bool
    label: str
    signals: Tuple[str, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
            "directed": self.directed,
            "label": self.label,
            "signals": list(self.signals),
        }


@dataclass(frozen=True)
class CapabilityGraph:
    """The full capability relationship graph for one MCP discovery surface.

    Attributes:
        nodes: Every capability as a node, in deterministic (kind, ordinal) order. Isolated nodes
            (``degree == 0``) are included.
        edges: The inferred relationships, in deterministic order.
        node_count / edge_count / isolated_count: Convenience totals.
        graph_fingerprint: Stable SHA-256 over the node+edge payload; identical surfaces yield the
            same fingerprint, so a caller can cache the result per ``surface_fingerprint``.
    """

    nodes: Tuple[GraphNode, ...]
    edges: Tuple[GraphEdge, ...]
    node_count: int
    edge_count: int
    isolated_count: int
    graph_fingerprint: str

    def as_dict(self) -> Dict[str, Any]:
        """Return the whole graph as a JSON-ready dict with a stable key set/order."""
        return {
            "nodes": [node.as_dict() for node in self.nodes],
            "edges": [edge.as_dict() for edge in self.edges],
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "isolated_count": self.isolated_count,
            "graph_fingerprint": self.graph_fingerprint,
        }


# --- Small shared helpers -------------------------------------------------------------------


def _node_id(item: CapabilityItem) -> str:
    """The stable node id for an item (``"{kind_prefix}_{ordinal}"``)."""
    return f"{_KIND_PREFIX[item.item_type]}_{item.ordinal}"


def _nonempty_str(value: Any) -> Optional[str]:
    """Return ``value`` when it is a non-blank string, else ``None``."""
    if isinstance(value, str) and value.strip() != "":
        return value
    return None


def _references_token(corpus: str, token: str) -> bool:
    """True when ``token`` occurs in ``corpus`` as a whole identifier token (case-sensitive).

    A match requires the characters immediately before and after the occurrence to *not* be name
    characters (see :data:`_NAME_CHAR_RE`), so ``search`` matches in ``"run search now"`` but not
    inside ``"research"`` or ``"search_v2"``. Case-sensitive because capability names are
    case-sensitive identifiers that referencing text quotes verbatim — this keeps precision high.
    """
    if not token or not corpus:
        return False
    start = 0
    span = len(token)
    while True:
        idx = corpus.find(token, start)
        if idx < 0:
            return False
        before = corpus[idx - 1] if idx > 0 else ""
        after = corpus[idx + span] if idx + span < len(corpus) else ""
        if not _NAME_CHAR_RE.match(before) and not _NAME_CHAR_RE.match(after):
            return True
        start = idx + 1


def _walk_schema_strings(schema: Any, budget: int, out: List[str]) -> None:
    """Collect the ``$ref`` and non-generic ``title`` type-identifiers under ``schema`` into ``out``.

    Walks the same structural children as :func:`app.mcp_surface_metrics._child_schemas` (object
    ``properties``, array ``items``/``prefixItems``, schema-form ``additionalProperties``, and
    ``oneOf``/``anyOf``/``allOf`` branches), gathering every ``$ref`` string (verbatim) and every
    ``title`` string that is not in :data:`_GENERIC_TITLES` (prefixed ``title:`` so a title can never
    collide with a same-spelled ``$ref``). Totality: non-mapping nodes and exhausted budget stop the
    walk; ``$ref`` nodes are treated as leaves and never resolved.
    """
    if not isinstance(schema, Mapping) or budget <= 0:
        return

    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.strip():
        out.append(ref.strip())

    title = schema.get("title")
    if isinstance(title, str) and title.strip():
        normalized = title.strip()
        if normalized.lower() not in _GENERIC_TITLES:
            out.append(f"title:{normalized}")

    for child in _child_schemas(schema):
        _walk_schema_strings(child, budget - 1, out)


def _child_schemas(schema: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """Return the immediate sub-schemas nested inside ``schema`` (mirrors the metrics module).

    Collects object ``properties`` values, array ``items`` (single schema or tuple list) and 2020-12
    ``prefixItems``, a schema-form ``additionalProperties``, and ``oneOf``/``anyOf``/``allOf``
    branches. A pure ``$ref`` node carries none of these and is treated as a leaf, which keeps the
    walk total on recursive/``$ref`` schemas.
    """
    children: List[Mapping[str, Any]] = []

    props = schema.get("properties")
    if isinstance(props, dict):
        children.extend(v for v in props.values() if isinstance(v, Mapping))

    items = schema.get("items")
    if isinstance(items, Mapping):
        children.append(items)
    elif isinstance(items, list):
        children.extend(v for v in items if isinstance(v, Mapping))

    prefix_items = schema.get("prefixItems")
    if isinstance(prefix_items, list):
        children.extend(v for v in prefix_items if isinstance(v, Mapping))

    additional = schema.get("additionalProperties")
    if isinstance(additional, Mapping):
        children.append(additional)

    for combinator in ("oneOf", "anyOf", "allOf"):
        branch = schema.get(combinator)
        if isinstance(branch, list):
            children.extend(v for v in branch if isinstance(v, Mapping))

    return children


def _type_identifiers(item: CapabilityItem) -> Set[str]:
    """The set of schema type-identifiers an item exposes across its input and output schemas."""
    out: List[str] = []
    for schema in (item.input_schema, item.output_schema):
        if isinstance(schema, Mapping):
            _walk_schema_strings(schema, MAX_SCHEMA_DEPTH, out)
    return set(out)


def _uri_literal_values(schema: Any, budget: int, out: List[str]) -> None:
    """Collect string literals of ``uri``-shaped parameters found anywhere under ``schema``.

    A property is URI-shaped when its name contains a hint in :data:`_URI_PROPERTY_HINTS` or it
    declares ``"format": "uri"``. For such a property we harvest ``const``/``default`` strings and
    the string members of ``enum``/``examples`` — the concrete URIs a tool is wired to touch. The
    walk descends the same structural children as :func:`_child_schemas` under a depth budget.
    """
    if not isinstance(schema, Mapping) or budget <= 0:
        return

    props = schema.get("properties")
    if isinstance(props, dict):
        for prop_name, prop_schema in props.items():
            if not isinstance(prop_schema, Mapping):
                continue
            name_l = prop_name.lower() if isinstance(prop_name, str) else ""
            is_uri_shaped = any(hint in name_l for hint in _URI_PROPERTY_HINTS) or (
                prop_schema.get("format") == "uri"
            )
            if is_uri_shaped:
                _collect_literal_strings(prop_schema, out)

    for child in _child_schemas(schema):
        _uri_literal_values(child, budget - 1, out)


def _collect_literal_strings(schema: Mapping[str, Any], out: List[str]) -> None:
    """Append the ``const``/``default`` and ``enum``/``examples`` string literals of one schema node."""
    for key in ("const", "default"):
        value = schema.get(key)
        if isinstance(value, str) and value.strip():
            out.append(value.strip())
    for key in ("enum", "examples"):
        values = schema.get(key)
        if isinstance(values, list):
            out.extend(v.strip() for v in values if isinstance(v, str) and v.strip())


def _prompt_corpus(prompt: CapabilityItem) -> str:
    """The searchable text of a prompt: its description plus each argument's name and description.

    Prompt ``arguments`` have no promoted column, so they are read from the verbatim wire entry
    (:attr:`~app.mcp_client.normalize.CapabilityItem.raw`).
    """
    parts: List[str] = []
    desc = _nonempty_str(prompt.description)
    if desc:
        parts.append(desc)
    arguments = prompt.raw.get("arguments") if isinstance(prompt.raw, Mapping) else None
    if isinstance(arguments, list):
        for arg in arguments:
            if not isinstance(arg, Mapping):
                continue
            for key in ("name", "description"):
                text = _nonempty_str(arg.get(key))
                if text:
                    parts.append(text)
    return "\n".join(parts)


def _tool_corpus(tool: CapabilityItem) -> str:
    """The searchable text of a tool: its description plus the URI literals of its uri-shaped params."""
    parts: List[str] = []
    desc = _nonempty_str(tool.description)
    if desc:
        parts.append(desc)
    literals: List[str] = []
    if isinstance(tool.input_schema, Mapping):
        _uri_literal_values(tool.input_schema, MAX_SCHEMA_DEPTH, literals)
    parts.extend(literals)
    return "\n".join(parts)


def _template_prefix(uri_template: Optional[str]) -> Optional[str]:
    """The literal prefix of a resource-template URI (the part before its first ``{`` placeholder).

    Only returned when it carries a scheme (contains ``:``) and is at least 4 characters, so a bare
    ``/`` or ``{id}`` template yields no over-broad signal. Used to reference-match a template the
    way a concrete resource ``uri`` is matched.
    """
    if not isinstance(uri_template, str):
        return None
    brace = uri_template.find("{")
    prefix = uri_template if brace < 0 else uri_template[:brace]
    prefix = prefix.strip()
    if len(prefix) >= 4 and ":" in prefix:
        return prefix
    return None


# --- Edge inference -------------------------------------------------------------------------


def _prompt_reference_edges(surface: DiscoverySurface) -> List[GraphEdge]:
    """Infer ``prompt → tool`` edges from prompts whose text names a tool as a whole token.

    Tool names shorter than :data:`MIN_NAME_REF_LENGTH` are skipped (too collision-prone to be a
    concrete signal). A prompt naming several tools yields one edge per tool.
    """
    edges: List[GraphEdge] = []
    referenceable = [t for t in surface.tools if len(t.name) >= MIN_NAME_REF_LENGTH]
    for prompt in surface.prompts:
        corpus = _prompt_corpus(prompt)
        if not corpus:
            continue
        for tool in referenceable:
            if _references_token(corpus, tool.name):
                edges.append(
                    GraphEdge(
                        source=_node_id(prompt),
                        target=_node_id(tool),
                        kind=EDGE_PROMPT_REFERENCE,
                        directed=True,
                        label=tool.name,
                        signals=(tool.name,),
                    )
                )
    return edges


def _resource_reference_edges(surface: DiscoverySurface) -> List[GraphEdge]:
    """Infer ``tool → resource`` (and ``tool → resource_template``) edges from literal URI mentions.

    A tool's text (description + uri-shaped param literals) is scanned for each resource's concrete
    ``uri`` and each resource template's literal prefix. The URI must occur verbatim, which keeps
    the signal concrete — distinctive URI strings do not collide by accident.
    """
    edges: List[GraphEdge] = []
    # (target node, the literal to search for) for every resource and matchable template.
    targets: List[Tuple[CapabilityItem, str]] = []
    for resource in surface.resources:
        uri = _nonempty_str(resource.uri)
        if uri and ":" in uri:
            targets.append((resource, uri.strip()))
    for template in surface.resource_templates:
        prefix = _template_prefix(template.uri_template)
        if prefix:
            targets.append((template, prefix))

    for tool in surface.tools:
        corpus = _tool_corpus(tool)
        if not corpus:
            continue
        for target_item, literal in targets:
            if literal in corpus:
                edges.append(
                    GraphEdge(
                        source=_node_id(tool),
                        target=_node_id(target_item),
                        kind=EDGE_RESOURCE_REFERENCE,
                        directed=True,
                        label=literal,
                        signals=(literal,),
                    )
                )
    return edges


def _shared_type_edges(items: Sequence[CapabilityItem]) -> List[GraphEdge]:
    """Infer undirected ``shared_type`` edges between items whose schemas share a type identifier.

    Builds a ``type-id → node-ids`` index, then for every id shared by two or more items emits one
    edge per unordered pair, merging all shared ids of a pair into a single edge's ``signals``. Node
    order within each edge is normalized (``source <= target``) so the pair is de-duplicated and the
    output is deterministic.
    """
    # id -> list of (node_id) that expose it, preserving item order.
    index: Dict[str, List[str]] = {}
    node_ids: Dict[int, str] = {}
    for pos, item in enumerate(items):
        node_ids[pos] = _node_id(item)
        for type_id in _type_identifiers(item):
            index.setdefault(type_id, [])
            # Record this item's position once per type id.
            if not index[type_id] or index[type_id][-1] != pos:
                index[type_id].append(pos)

    # Accumulate the shared ids per unordered node pair.
    pair_signals: Dict[Tuple[str, str], Set[str]] = {}
    for type_id, positions in index.items():
        if len(positions) < 2:
            continue
        for i in range(len(positions)):
            for j in range(i + 1, len(positions)):
                a, b = node_ids[positions[i]], node_ids[positions[j]]
                if a == b:
                    continue
                pair = (a, b) if a <= b else (b, a)
                pair_signals.setdefault(pair, set()).add(type_id)

    edges: List[GraphEdge] = []
    for (a, b), signals in pair_signals.items():
        ordered = tuple(sorted(signals))
        edges.append(
            GraphEdge(
                source=a,
                target=b,
                kind=EDGE_SHARED_TYPE,
                directed=False,
                label=ordered[0],
                signals=ordered,
            )
        )
    return edges


def _edge_sort_key(edge: GraphEdge) -> Tuple[str, str, str]:
    """Deterministic ordering: by kind, then source, then target."""
    return (edge.kind, edge.source, edge.target)


def _graph_fingerprint(payload: Mapping[str, Any]) -> str:
    """Stable SHA-256 over the graph ``payload`` (sorted keys, compact separators)."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# --- Engine entry point ---------------------------------------------------------------------


def compute_capability_graph(surface: DiscoverySurface) -> CapabilityGraph:
    """Compute the deterministic :class:`CapabilityGraph` for an MCP discovery ``surface``.

    Pure and total: the surface is never mutated, no I/O is performed, and the walks never throw on
    nested/``$ref``/array/combinator schemas. The same surface always produces the same graph and
    the same ``graph_fingerprint``. Every node is emitted (isolated nodes included); edges are
    emitted only on the three concrete signals documented at the module level, then de-duplicated
    and sorted deterministically.

    Args:
        surface: The normalized MCP capability surface to map.

    Returns:
        The :class:`CapabilityGraph` (nodes with degree, inferred edges, summary counts, and a
        stable fingerprint).
    """
    items = surface.all_items()

    # Infer every edge, then de-duplicate exact repeats (same source/target/kind), merging signals.
    raw_edges: List[GraphEdge] = []
    raw_edges.extend(_prompt_reference_edges(surface))
    raw_edges.extend(_resource_reference_edges(surface))
    raw_edges.extend(_shared_type_edges(items))

    merged: Dict[Tuple[str, str, str], GraphEdge] = {}
    for edge in raw_edges:
        key = (edge.source, edge.target, edge.kind)
        existing = merged.get(key)
        if existing is None:
            merged[key] = edge
        else:
            signals = tuple(sorted(set(existing.signals) | set(edge.signals)))
            merged[key] = GraphEdge(
                source=existing.source,
                target=existing.target,
                kind=existing.kind,
                directed=existing.directed,
                label=existing.label,
                signals=signals,
            )
    edges = tuple(sorted(merged.values(), key=_edge_sort_key))

    # Degree per node — an incident edge counts for both endpoints regardless of direction.
    degree: Dict[str, int] = {}
    for edge in edges:
        degree[edge.source] = degree.get(edge.source, 0) + 1
        degree[edge.target] = degree.get(edge.target, 0) + 1

    nodes = tuple(
        GraphNode(
            id=_node_id(item),
            item_type=item.item_type,
            name=item.name,
            title=_nonempty_str(item.title),
            label=_nonempty_str(item.title) or item.name,
            degree=degree.get(_node_id(item), 0),
        )
        for item in items
    )
    isolated_count = sum(1 for node in nodes if node.degree == 0)

    payload: Dict[str, Any] = {
        "nodes": [node.as_dict() for node in nodes],
        "edges": [edge.as_dict() for edge in edges],
        "node_count": len(nodes),
        "edge_count": len(edges),
        "isolated_count": isolated_count,
    }
    fingerprint = _graph_fingerprint(payload)

    return CapabilityGraph(
        nodes=nodes,
        edges=edges,
        node_count=len(nodes),
        edge_count=len(edges),
        isolated_count=isolated_count,
        graph_fingerprint=fingerprint,
    )


__all__ = [
    "EDGE_PROMPT_REFERENCE",
    "EDGE_RESOURCE_REFERENCE",
    "EDGE_SHARED_TYPE",
    "MAX_SCHEMA_DEPTH",
    "MIN_NAME_REF_LENGTH",
    "CapabilityGraph",
    "GraphEdge",
    "GraphNode",
    "compute_capability_graph",
]
