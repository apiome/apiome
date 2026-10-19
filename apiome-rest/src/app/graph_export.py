"""Export the catalog graph as JSON or Graphviz DOT — CDG-3.6 (#5971).

``GET /v1/graph/{tenant}/export?format=json|dot`` and ``apiome graph export`` write the tenant's
dependency graph (:mod:`app.catalog_graph`) for other tools: a JSON document a script can read, or a
DOT file Graphviz draws (``dot -Tsvg graph.dot``).

The export is **bounded**: at most :data:`MAX_EXPORT_EDGES` edges, chosen in a stable order (current
edges before stale ones), with ``truncated`` saying more matched. It is **streamed**: the renderers
yield the document a node or an edge at a time, so the response starts at once and is never built
as one string.

Two scopes:

* the **whole tenant**, narrowed by ``kind`` (an edge with either end of these node kinds), ``team``
  (either end owned by this team), ``provenance`` and ``stale``;
* a **neighbourhood**: ``entity=kind:id`` and ``depth`` (1–5, default 2) walk the edges touching the
  entity, in both directions, ``depth`` hops out; the other filters still apply.

Every node carries its name, slug and owner team (:func:`app.graph_nodes.node_labels_with_owners`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple

from .catalog_graph import NODE_KINDS, PROVENANCES, GraphValidationError
from .graph_nodes import PROJECT_KINDS, current_node_kinds, node_labels_with_owners

__all__ = [
    "DEFAULT_DEPTH",
    "EXPORT_FORMAT",
    "FORMATS",
    "MAX_DEPTH",
    "MAX_EXPORT_EDGES",
    "GraphExport",
    "export_graph",
    "parse_entity",
    "render_dot",
    "render_json",
]

#: The most edges one export holds.
MAX_EXPORT_EDGES = 10_000

#: Hops a neighbourhood export walks by default, and at most.
DEFAULT_DEPTH = 2
MAX_DEPTH = 5

#: The output formats.
FORMATS = ("json", "dot")

#: Names the JSON document's shape.
EXPORT_FORMAT = "apiome.graph.export/v1"

_EDGE_COLUMNS = """
    id::text AS id, from_kind, from_id::text AS from_id, to_kind, to_id::text AS to_id, edge_kind,
    pointer, provenance, source_ref, first_seen_at, last_seen_at, stale_since
"""
_EDGE_ORDER = "(stale_since IS NOT NULL), edge_kind, from_kind, from_id, to_kind, to_id, pointer NULLS FIRST, id"


@dataclass(frozen=True)
class GraphExport:
    """What an export holds.

    Attributes:
        nodes: ``{kind, id, name, slug, owner}`` for every edge end, sorted by kind and id.
        edges: ``{id, from_kind, from_id, to_kind, to_id, edge_kind, pointer, provenance, source_ref,
            first_seen_at, last_seen_at, stale_since, stale}``, in a stable order.
        truncated: True when more edges matched than :data:`MAX_EXPORT_EDGES`.
        filters: The filters the export applied, echoed into the document.
    """

    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    truncated: bool
    filters: Dict[str, Any]


def parse_entity(value: str) -> Tuple[str, str]:
    """Split an ``entity=kind:id`` filter.

    Args:
        value: ``<node kind>:<uuid>``, e.g. ``project:6f1c…``.

    Returns:
        ``(kind, id)``.

    Raises:
        GraphValidationError: ``graph-invalid`` when the kind is unknown or the id is missing.
    """
    kind, sep, entity_id = (value or "").partition(":")
    if not sep or kind not in NODE_KINDS or not entity_id.strip():
        raise GraphValidationError("graph-invalid", "entity must be <kind>:<id> with a known node kind")
    return kind, entity_id.strip()


def _iso(value: Any) -> Optional[str]:
    """ISO-8601 for a timestamp."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


def _edge_out(row: Any) -> Dict[str, Any]:
    """An edge row as export data."""
    edge = dict(row)
    for key in ("first_seen_at", "last_seen_at", "stale_since"):
        edge[key] = _iso(edge.get(key))
    edge["stale"] = edge["stale_since"] is not None
    return edge


def _edge_filters(provenances: Sequence[str], include_stale: bool) -> Tuple[List[str], List[Any]]:
    """The SQL clauses every export applies, after ``tenant_id``."""
    clauses: List[str] = []
    params: List[Any] = []
    if provenances:
        clauses.append("provenance = ANY(%s::text[])")
        params.append(list(provenances))
    if not include_stale:
        clauses.append("stale_since IS NULL")
    return clauses, params


def _tenant_edges(
    db: Any, tenant_id: str, kinds: Sequence[str], provenances: Sequence[str], include_stale: bool, limit: int
) -> List[Any]:
    """Up to ``limit`` of the tenant's edges matching the SQL-side filters."""
    clauses, params = _edge_filters(provenances, include_stale)
    if kinds:
        # A projects row can be named either way on an edge; the exact kind is checked afterwards.
        sql_kinds = sorted(set(kinds) | (set(PROJECT_KINDS) if set(kinds) & set(PROJECT_KINDS) else set()))
        clauses.append("(from_kind = ANY(%s::text[]) OR to_kind = ANY(%s::text[]))")
        params.extend([sql_kinds, sql_kinds])
    where = " AND ".join(["tenant_id = %s::uuid"] + clauses)
    return list(
        db.execute_query(
            f"SELECT {_EDGE_COLUMNS} FROM apiome.catalog_edges WHERE {where} ORDER BY {_EDGE_ORDER} LIMIT %s",
            tuple([tenant_id] + params + [int(limit)]),
        )
        or []
    )


def _neighbourhood_edges(
    db: Any,
    tenant_id: str,
    entity_id: str,
    depth: int,
    provenances: Sequence[str],
    include_stale: bool,
    limit: int,
) -> List[Any]:
    """Up to ``limit`` edges within ``depth`` hops of the entity, in both directions."""
    clauses, params = _edge_filters(provenances, include_stale)
    where = " AND ".join(["tenant_id = %s::uuid", "(from_id = ANY(%s::uuid[]) OR to_id = ANY(%s::uuid[]))"] + clauses)
    seen_nodes: Set[str] = {entity_id}
    frontier = [entity_id]
    found: Dict[str, Any] = {}
    for _hop in range(depth):
        if not frontier or len(found) >= limit:
            break
        rows = (
            db.execute_query(
                f"SELECT {_EDGE_COLUMNS} FROM apiome.catalog_edges WHERE {where} ORDER BY {_EDGE_ORDER} LIMIT %s",
                tuple([tenant_id, frontier, frontier] + params + [int(limit) - len(found)]),
            )
            or []
        )
        next_frontier: List[str] = []
        for row in rows:
            if row["id"] in found:
                continue
            found[row["id"]] = row
            for end in (str(row["from_id"]), str(row["to_id"])):
                if end not in seen_nodes:
                    seen_nodes.add(end)
                    next_frontier.append(end)
        frontier = next_frontier
    return list(found.values())


def export_graph(
    db: Any,
    tenant_id: str,
    *,
    kinds: Sequence[str] = (),
    team: Optional[str] = None,
    provenances: Sequence[str] = (),
    include_stale: bool = True,
    entity: Optional[str] = None,
    depth: int = DEFAULT_DEPTH,
    max_edges: int = MAX_EXPORT_EDGES,
) -> GraphExport:
    """Collect the graph an export writes.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        kinds: Keep edges with at least one end of these node kinds (empty for all).
        team: Keep edges with at least one end owned by this team slug.
        provenances: Keep edges of these provenances (empty for all).
        include_stale: False drops stale edges.
        entity: ``kind:id`` to export that entity's neighbourhood instead of the whole tenant.
        depth: Hops the neighbourhood walks, 1..:data:`MAX_DEPTH` (ignored without ``entity``).
        max_edges: The bound, 1..:data:`MAX_EXPORT_EDGES`.

    Returns:
        The nodes and edges, and whether the bound cut the export short.

    Raises:
        GraphValidationError: ``graph-invalid`` for an unknown kind or provenance, a bad entity, or
            a depth or bound out of range.
    """
    bad = [k for k in kinds if k not in NODE_KINDS] + [p for p in provenances if p not in PROVENANCES]
    if bad:
        raise GraphValidationError("graph-invalid", f"unknown filter values: {', '.join(bad)}")
    if not 1 <= int(max_edges) <= MAX_EXPORT_EDGES:
        raise GraphValidationError("graph-invalid", f"max_edges must be between 1 and {MAX_EXPORT_EDGES}")
    if not 1 <= int(depth) <= MAX_DEPTH:
        raise GraphValidationError("graph-invalid", f"depth must be between 1 and {MAX_DEPTH}")
    team = (team or "").strip() or None
    center = parse_entity(entity) if entity else None

    # One row past the bound tells whether the export was cut short.
    if center:
        rows = _neighbourhood_edges(db, tenant_id, center[1], int(depth), provenances, include_stale, max_edges + 1)
    else:
        rows = _tenant_edges(db, tenant_id, kinds, provenances, include_stale, max_edges + 1)
    truncated = len(rows) > max_edges
    edges = [_edge_out(row) for row in rows[:max_edges]]

    refs = sorted({(e["from_kind"], e["from_id"]) for e in edges} | {(e["to_kind"], e["to_id"]) for e in edges})
    current = current_node_kinds(db, tenant_id, refs)
    info = node_labels_with_owners(db, tenant_id, refs)

    def kind_of(kind: str, node_id: str) -> str:
        return current.get(node_id, kind)

    def keep(edge: Dict[str, Any]) -> bool:
        ends = ((edge["from_kind"], edge["from_id"]), (edge["to_kind"], edge["to_id"]))
        if kinds and not any(kind_of(k, i) in kinds for k, i in ends):
            return False
        if team and not any(((info.get(i) or {}).get("owner") or {}).get("slug") == team for _k, i in ends):
            return False
        return True

    edges = [edge for edge in edges if keep(edge)]
    for edge in edges:
        edge["from_kind"] = kind_of(edge["from_kind"], edge["from_id"])
        edge["to_kind"] = kind_of(edge["to_kind"], edge["to_id"])
    nodes: Dict[str, Dict[str, Any]] = {}
    for edge in edges:
        for kind, node_id in ((edge["from_kind"], edge["from_id"]), (edge["to_kind"], edge["to_id"])):
            item = info.get(node_id) or {}
            nodes.setdefault(
                node_id,
                {
                    "kind": kind,
                    "id": node_id,
                    "name": item.get("name"),
                    "slug": item.get("slug"),
                    "owner": item.get("owner"),
                },
            )
    filters: Dict[str, Any] = {
        "kind": sorted(kinds),
        "team": team,
        "provenance": sorted(provenances),
        "stale": include_stale,
        "entity": f"{center[0]}:{center[1]}" if center else None,
        "depth": int(depth) if center else None,
    }
    return GraphExport(
        nodes=sorted(nodes.values(), key=lambda n: (n["kind"], n["id"])),
        edges=edges,
        truncated=truncated,
        filters=filters,
    )


def render_json(export: GraphExport, *, tenant: str, generated_at: Optional[datetime] = None) -> Iterator[str]:
    """Stream the export as one JSON document.

    The document is ``{format, tenant, generated_at, filters, limit, truncated, node_count,
    edge_count, nodes: [...], edges: [...]}``; keys are sorted inside each node and edge.

    Args:
        export: What :func:`export_graph` collected.
        tenant: The tenant slug, echoed into the document.
        generated_at: The timestamp to write (now, by default).

    Yields:
        Chunks that concatenate to the document.
    """
    moment = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    head = {
        "format": EXPORT_FORMAT,
        "tenant": tenant,
        "generated_at": moment.isoformat().replace("+00:00", "Z"),
        "filters": export.filters,
        "limit": MAX_EXPORT_EDGES,
        "truncated": export.truncated,
        "node_count": len(export.nodes),
        "edge_count": len(export.edges),
    }
    yield json.dumps(head, sort_keys=True)[:-1] + ', "nodes": ['
    for index, node in enumerate(export.nodes):
        yield ("," if index else "") + "\n" + json.dumps(node, sort_keys=True)
    yield '\n], "edges": ['
    for index, edge in enumerate(export.edges):
        yield ("," if index else "") + "\n" + json.dumps(edge, sort_keys=True)
    yield "\n]}\n"


def _dot_string(value: Any) -> str:
    """A DOT double-quoted string: quotes and backslashes escaped, line breaks as ``\\n``."""
    text = str(value if value is not None else "")
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + text.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n") + '"'


def _dot_id(kind: str, node_id: str) -> str:
    """A node's DOT id: ``"kind:id"``."""
    return _dot_string(f"{kind}:{node_id}")


def render_dot(export: GraphExport, *, tenant: str) -> Iterator[str]:
    """Stream the export as a Graphviz ``digraph``.

    Each node is a box labelled with its name (else slug, else id), its kind and its owner team.
    Each edge points from the dependent to what it depends on, labelled with its kind (and pointer).
    Stale edges are dashed and grey, ``declared`` edges bold and ``runtime`` edges dotted. A cut-short
    export says so in a comment on the first line.

    Args:
        export: What :func:`export_graph` collected.
        tenant: The tenant slug, written into the header comment and the graph label.

    Yields:
        Lines of the DOT file.
    """
    note = f"; truncated at {MAX_EXPORT_EDGES} edges" if export.truncated else ""
    yield f"// apiome graph export: {len(export.nodes)} nodes, {len(export.edges)} edges{note}\n"
    yield "digraph apiome {\n"
    yield f"  label={_dot_string('Apiome dependency graph: ' + tenant)};\n"
    yield "  rankdir=LR;\n  node [shape=box];\n"
    for node in export.nodes:
        owner = (node.get("owner") or {}).get("slug")
        title = node.get("name") or node.get("slug") or node["id"]
        label = f"{title}\n{node['kind']}" + (f" · {owner}" if owner else "")
        attrs = [f"label={_dot_string(label)}", f"kind={_dot_string(node['kind'])}"]
        if owner:
            attrs.append(f"owner={_dot_string(owner)}")
        yield f"  {_dot_id(node['kind'], node['id'])} [{', '.join(attrs)}];\n"
    for edge in export.edges:
        label = edge["edge_kind"] + (f"\n{edge['pointer']}" if edge.get("pointer") else "")
        attrs = [f"label={_dot_string(label)}", f"provenance={_dot_string(edge['provenance'])}"]
        if edge["stale"]:
            attrs.append('style="dashed", color="gray"')
        elif edge["provenance"] == "declared":
            attrs.append('style="bold"')
        elif edge["provenance"] == "runtime":
            attrs.append('style="dotted"')
        yield (
            f"  {_dot_id(edge['from_kind'], edge['from_id'])} -> {_dot_id(edge['to_kind'], edge['to_id'])} "
            f"[{', '.join(attrs)}];\n"
        )
    yield "}\n"
