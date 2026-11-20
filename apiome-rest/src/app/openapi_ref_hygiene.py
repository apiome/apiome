"""``$ref`` hygiene for a project's OpenAPI document — COA-2.8 (#7051).

Pure helpers behind the Versions screen's **References** tab:

* :func:`external_ref_groups` — every external ``$ref`` the document depends on, grouped by the
  URL it fetches, with every place it is used. Built on
  :func:`app.remote_ref_resolver.scan_external_refs`, so the panel lists exactly what an import
  would try to resolve.
* :func:`find_ref_cycles` — the document's circular internal references, each as one group of
  references that reach each other plus a concrete path round the loop
  (``#/components/schemas/Node → …/Edge → …/Node``).
* :func:`json_value_diff` — what changed between two versions of a fetched document, as JSON
  Pointer rows (``added`` / ``removed`` / ``changed``). A refresh that finds a remote reference
  changed reports this diff.

No I/O; inputs are never mutated.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .openapi_ref_modes import _escape, _is_internal_pointer, _is_literal, _resolve_pointer
from .remote_ref_resolver import scan_external_refs

__all__ = [
    "MAX_CYCLES",
    "MAX_DIFF_CHANGES",
    "external_ref_groups",
    "find_ref_cycles",
    "json_value_diff",
]

#: Most cycle groups reported for one document; the rest are counted, not listed.
MAX_CYCLES = 100

#: Most diff rows kept for one changed reference; the total is always reported.
MAX_DIFF_CHANGES = 200


# ===========================================================================
# External references
# ===========================================================================


def external_ref_groups(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Every external ``$ref`` of ``document``, grouped by the URL it resolves to.

    Args:
        document: The parsed OpenAPI / Swagger document.

    Returns:
        ``[{url, locations: [{location, ref}]}]`` sorted by URL; ``location`` is the JSON Pointer
        of the ``$ref`` (``#/components/schemas/Money``) and ``ref`` the reference as written.
    """
    groups: Dict[str, List[Dict[str, str]]] = {}
    for found in scan_external_refs({"": dict(document)}):
        groups.setdefault(found.url, []).append({"location": found.location, "ref": found.ref})
    return [{"url": url, "locations": groups[url]} for url in sorted(groups)]


# ===========================================================================
# Cycles
# ===========================================================================


def _internal_refs(value: Any, key: Optional[str] = None) -> List[str]:
    """The internal references (``#/…``) inside ``value``, in document order, without repeats.

    Literal data (``example``, ``default``, ``enum`` …) is skipped, as the dereferencer skips it,
    so an example that happens to hold a ``$ref`` key is not mistaken for a reference.
    """
    found: Dict[str, None] = {}

    def walk(node: Any, node_key: Optional[str]) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item, None)
            return
        if not isinstance(node, dict):
            return
        ref = node.get("$ref")
        if _is_internal_pointer(ref):
            found.setdefault(ref, None)
        for name, item in node.items():
            if name == "$ref" or _is_literal(name, item, node_key):
                continue
            walk(item, name)

    walk(value, key)
    return list(found)


def _ref_graph(document: Mapping[str, Any]) -> Dict[str, List[str]]:
    """``reference → references inside its target`` for every reference reachable from the root."""
    graph: Dict[str, List[str]] = {}
    pending = _internal_refs(dict(document))
    while pending:
        ref = pending.pop()
        if ref in graph:
            continue
        found, target = _resolve_pointer(document, ref)
        edges = _internal_refs(target) if found else []
        graph[ref] = edges
        pending.extend(edge for edge in edges if edge not in graph)
    return graph


def _strongly_connected(graph: Mapping[str, Sequence[str]]) -> List[List[str]]:
    """Tarjan's strongly connected components of ``graph`` (iterative, so deep chains are safe)."""
    index: Dict[str, int] = {}
    low: Dict[str, int] = {}
    on_stack: Dict[str, bool] = {}
    stack: List[str] = []
    components: List[List[str]] = []
    counter = 0

    for root in sorted(graph):
        if root in index:
            continue
        work: List[Tuple[str, int]] = [(root, 0)]
        while work:
            node, child = work.pop()
            if child == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack[node] = True
            edges = graph.get(node, ())
            if child < len(edges):
                work.append((node, child + 1))
                nxt = edges[child]
                if nxt not in index:
                    work.append((nxt, 0))
                elif on_stack.get(nxt):
                    low[node] = min(low[node], index[nxt])
                continue
            if low[node] == index[node]:
                component: List[str] = []
                while True:
                    member = stack.pop()
                    on_stack[member] = False
                    component.append(member)
                    if member == node:
                        break
                components.append(component)
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return components


def _cycle_path(start: str, members: set, graph: Mapping[str, Sequence[str]]) -> List[str]:
    """A shortest path from ``start`` back to itself inside one strongly connected group."""
    previous: Dict[str, str] = {}
    queue = [start]
    seen = {start}
    while queue:
        node = queue.pop(0)
        for nxt in graph.get(node, ()):
            if nxt not in members:
                continue
            if nxt == start:
                path = [node]
                while path[-1] != start:
                    path.append(previous[path[-1]])
                return list(reversed(path)) + [start]
            if nxt not in seen:
                seen.add(nxt)
                previous[nxt] = node
                queue.append(nxt)
    return [start, start]


def find_ref_cycles(document: Mapping[str, Any]) -> Dict[str, Any]:
    """The circular internal references of ``document``.

    A cycle group is a set of references that all reach each other (a self-recursive schema is
    a group of one). Each group is reported with a concrete path round the loop, starting and
    ending at its alphabetically first reference.

    Args:
        document: The parsed OpenAPI / Swagger document.

    Returns:
        ``{cycles: [{refs, path}], total, truncated}`` — at most :data:`MAX_CYCLES` groups,
        ordered by their first reference.
    """
    graph = _ref_graph(document)
    groups = []
    for component in _strongly_connected(graph):
        members = set(component)
        start = min(members)
        if len(members) == 1 and start not in graph.get(start, ()):
            continue
        groups.append({"refs": sorted(members), "path": _cycle_path(start, members, graph)})
    groups.sort(key=lambda group: group["refs"][0])
    return {"cycles": groups[:MAX_CYCLES], "total": len(groups), "truncated": len(groups) > MAX_CYCLES}


# ===========================================================================
# Diff
# ===========================================================================


def json_value_diff(before: Any, after: Any, *, limit: int = MAX_DIFF_CHANGES) -> Dict[str, Any]:
    """What changed from ``before`` to ``after``, as JSON Pointer rows.

    Objects are compared key by key and arrays index by index; any other difference (a changed
    scalar, or a value whose type changed) is one ``changed`` row. A key or array item present
    on one side only is one ``added`` / ``removed`` row carrying the whole value.

    Args:
        before: The earlier document (the pinned or last fetched one).
        after: The document just fetched.
        limit: Most rows to keep.

    Returns:
        ``{changes: [{pointer, kind, before?, after?}], total, truncated}``.
    """
    changes: List[Dict[str, Any]] = []
    total = 0

    def record(row: Dict[str, Any]) -> None:
        nonlocal total
        total += 1
        if len(changes) < limit:
            changes.append(row)

    def walk(old: Any, new: Any, pointer: str) -> None:
        if isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(set(old) | set(new)):
                at = f"{pointer}/{_escape(str(key))}"
                if key not in new:
                    record({"pointer": at, "kind": "removed", "before": old[key]})
                elif key not in old:
                    record({"pointer": at, "kind": "added", "after": new[key]})
                else:
                    walk(old[key], new[key], at)
            return
        if isinstance(old, list) and isinstance(new, list):
            for position in range(max(len(old), len(new))):
                at = f"{pointer}/{position}"
                if position >= len(new):
                    record({"pointer": at, "kind": "removed", "before": old[position]})
                elif position >= len(old):
                    record({"pointer": at, "kind": "added", "after": new[position]})
                else:
                    walk(old[position], new[position], at)
            return
        if old != new or type(old) is not type(new):
            record({"pointer": pointer, "kind": "changed", "before": old, "after": new})

    walk(before, after, "")
    return {"changes": changes, "total": total, "truncated": total > limit}
