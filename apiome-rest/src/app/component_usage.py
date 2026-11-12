"""Component usage report — DCW-3.3 (private-suite#2361), served for DCW-EPIC-3 (#2349).

A pure module behind ``GET /v1/component-library/{tenant}/components/{id}/usage``: the
authoritative, tenant-scale form of the dependency rule the Designer mirrors in
``designer/src/lib/component-library/library-impact.ts`` (``collectComponentRefs``,
``buildLibraryDependencyGraph``, ``computeTransitiveDependents``). The two must agree, so the
rule is spelled out once here:

* A component's payload is its **published head** (highest semver published revision). A
  component with no published revision references nothing.
* A reference is any ``$ref`` of the form ``#/components/<section>/<name>``; a deeper pointer
  (``#/components/responses/X/headers/Y``) counts as a use of ``responses/X``. Pointer segments
  are unescaped (``~1`` → ``/``, ``~0`` → ``~``).
* ``<section>/<name>`` resolves to the library component whose kind maps to ``section`` and whose
  name is ``name``. Self-references are ignored.
* Dependents are found breadth-first over the inverted graph, so each dependent carries its
  shortest reference distance (1 = direct), and cycles terminate. They are ordered by depth, then
  name, then id.

The work is one pass over the tenant's heads plus a BFS — linear in the size of the graph — so a
tenant-scale library answers in one request instead of the client downloading every payload.
"""

from __future__ import annotations

import re
from collections import deque
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

from .component_library import KIND_SECTIONS, parse_semver

__all__ = [
    "build_dependency_graph",
    "collect_component_refs",
    "head_payloads",
    "transitive_dependents",
]

_REF_RE = re.compile(r"^#/components/([^/]+)/([^/]+)")


def _unescape(segment: str) -> str:
    return segment.replace("~1", "/").replace("~0", "~")


def collect_component_refs(node: Any) -> Set[str]:
    """Collect every canonical component reference in a JSON subtree.

    Args:
        node: Any JSON value (a payload or a document fragment).

    Returns:
        The referenced ``<section>/<name>`` keys.
    """
    refs: Set[str] = set()
    stack: List[Any] = [node]
    seen: Set[int] = set()
    while stack:
        value = stack.pop()
        if isinstance(value, (dict, list)):
            if id(value) in seen:
                continue
            seen.add(id(value))
        if isinstance(value, list):
            stack.extend(value)
            continue
        if not isinstance(value, dict):
            continue
        ref = value.get("$ref")
        if isinstance(ref, str):
            match = _REF_RE.match(ref)
            if match:
                refs.add(f"{_unescape(match.group(1))}/{_unescape(match.group(2))}")
        stack.extend(value.values())
    return refs


def head_payloads(revisions: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Pick each component's published head payload.

    Args:
        revisions: Published revision rows (``component_id``, ``revision``,
            ``canonical_payload``), in any order.

    Returns:
        Component id → the payload of its highest-semver published revision.
    """
    best: Dict[str, Mapping[str, Any]] = {}
    for row in revisions:
        version = parse_semver(row.get("revision"))
        if version is None:
            continue
        component_id = str(row.get("component_id"))
        current = best.get(component_id)
        if current is None or version > (parse_semver(current.get("revision")) or (0, 0, 0)):
            best[component_id] = row
    return {component_id: row.get("canonical_payload") for component_id, row in best.items()}


def build_dependency_graph(
    components: Iterable[Mapping[str, Any]], payloads: Mapping[str, Any]
) -> Dict[str, Set[str]]:
    """Component id → ids of the library components its head payload references.

    Args:
        components: Live components (``id``, ``name``, ``kind``).
        payloads: Head payloads from :func:`head_payloads`.

    Returns:
        The dependency graph; every component appears as a key.
    """
    rows = list(components)
    by_key = {
        f"{KIND_SECTIONS.get(str(row['kind']), str(row['kind']))}/{row['name']}": str(row["id"])
        for row in rows
    }
    graph: Dict[str, Set[str]] = {}
    for row in rows:
        component_id = str(row["id"])
        references = {
            by_key[key]
            for key in collect_component_refs(payloads.get(component_id))
            if key in by_key and by_key[key] != component_id
        }
        graph[component_id] = references
    return graph


def transitive_dependents(
    components: Iterable[Mapping[str, Any]],
    payloads: Mapping[str, Any],
    target_component_id: str,
) -> List[Dict[str, Any]]:
    """Every component that reaches the target through the dependency graph.

    Args:
        components: Live components (``id``, ``name``, ``kind``).
        payloads: Head payloads from :func:`head_payloads`.
        target_component_id: The component being analyzed.

    Returns:
        ``[{componentId, name, kind, depth}]``, nearest first (depth, name, id).
    """
    rows = {str(row["id"]): row for row in components}
    graph = build_dependency_graph(rows.values(), payloads)
    dependents_of: Dict[str, Set[str]] = {}
    for component_id, references in graph.items():
        for referenced in references:
            dependents_of.setdefault(referenced, set()).add(component_id)

    target = str(target_component_id)
    depths: Dict[str, int] = {}
    queue: deque = deque([(target, 0)])
    while queue:
        current, depth = queue.popleft()
        for dependent in sorted(dependents_of.get(current, ())):
            if dependent == target or dependent in depths:
                continue
            depths[dependent] = depth + 1
            queue.append((dependent, depth + 1))

    result: List[Dict[str, Any]] = []
    for component_id, depth in depths.items():
        row: Optional[Mapping[str, Any]] = rows.get(component_id)
        if row is None:
            continue
        result.append(
            {
                "componentId": component_id,
                "name": str(row["name"]),
                "kind": str(row["kind"]),
                "depth": depth,
            }
        )
    result.sort(key=lambda item: (item["depth"], item["name"], item["componentId"]))
    return result
