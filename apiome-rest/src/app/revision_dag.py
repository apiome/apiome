"""Revision DAG queries over schema revisions — #2593.

A schema revision (a ``versions`` row) has up to two parents: ``parent_version_id`` (the first,
linear parent) and ``merge_parent_version_id`` (the second parent of a merge revision, V072). A row
with neither is a **root** — the first revision of a project, a fork into another project, or a
version created on its own. This module answers the two graph questions over that DAG without
touching the database:

* :func:`ancestors` — every revision reachable from one or more tips through parent links, each
  with its **distance** (the fewest parent steps from the nearest tip), optionally cut at a depth;
* :func:`merge_base` — the best common ancestor of two revisions (Git's merge-base), ``None``
  when their histories are disjoint.

The caller loads the ancestor closure once (``Database.fetch_revision_closure``: one recursive
query) and passes it in as :class:`RevisionNode` rows, so neither query costs a round trip per
revision.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

__all__ = [
    "DEFAULT_HISTORY_DEPTH",
    "DEFAULT_HISTORY_LIMIT",
    "MAX_HISTORY_DEPTH",
    "MAX_HISTORY_LIMIT",
    "HistoryWindow",
    "RevisionNode",
    "ancestors",
    "history_window",
    "merge_base",
    "merge_base_candidates",
]

#: Parent steps a history window walks from its tips when the caller does not say.
DEFAULT_HISTORY_DEPTH = 50
#: The deepest window a caller may ask for.
MAX_HISTORY_DEPTH = 1000
#: Revisions a history window returns when the caller does not say.
DEFAULT_HISTORY_LIMIT = 500
#: The most revisions one window may return.
MAX_HISTORY_LIMIT = 5000

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class RevisionNode:
    """One revision and its parent links.

    Attributes:
        revision_id: The revision's id (``versions.id``).
        parent_id: The first parent (``parent_version_id``); ``None`` for a root.
        merge_parent_id: The second parent of a merge (``merge_parent_version_id``).
        created_at: When the revision was created (breaks ties between merge-base candidates).
        version_label: The human version string (``versions.version_id``), for display.
    """

    revision_id: str
    parent_id: Optional[str] = None
    merge_parent_id: Optional[str] = None
    created_at: Optional[Union[datetime, str]] = None
    version_label: Optional[str] = None

    @property
    def parents(self) -> Tuple[str, ...]:
        """The parent ids, first parent first; empty for a root."""
        return tuple(p for p in (self.parent_id, self.merge_parent_id) if p)


@dataclass(frozen=True)
class HistoryWindow:
    """A bounded slice of the DAG reachable from some tips.

    Attributes:
        nodes: The revisions in the window, nearest the tips first (then newest first).
        distances: Revision id → fewest parent steps from a tip (tips are 0).
        truncated: Whether the depth or the limit cut the history short.
    """

    nodes: List[RevisionNode]
    distances: Dict[str, int]
    truncated: bool


def _index(nodes: Iterable[RevisionNode]) -> Dict[str, RevisionNode]:
    return {node.revision_id: node for node in nodes}


def ancestors(
    nodes: Union[Iterable[RevisionNode], Mapping[str, RevisionNode]],
    tips: Sequence[str],
    *,
    depth: Optional[int] = None,
) -> Dict[str, int]:
    """Every revision reachable from ``tips`` through parent links, with its distance.

    A breadth-first walk, so each revision's distance is the fewest parent steps from the nearest
    tip; a revision reached along two paths (a diamond after a merge) is visited once. A parent
    id that is not in ``nodes`` (deleted, or outside the loaded closure) ends that path.

    Args:
        nodes: The loaded revisions (an iterable, or an id → node mapping).
        tips: The revisions to start from; each is at distance 0. A tip missing from ``nodes`` is
            still returned at distance 0, as the merge code has always treated it.
        depth: The most parent steps to take; ``None`` for the whole history.

    Returns:
        Revision id → distance, tips included.
    """
    graph = nodes if isinstance(nodes, Mapping) else _index(nodes)
    distances: Dict[str, int] = {}
    queue: deque = deque()
    for tip in tips:
        if tip not in distances:
            distances[tip] = 0
            queue.append(tip)
    while queue:
        current = queue.popleft()
        step = distances[current]
        if depth is not None and step >= depth:
            continue
        node = graph.get(current)
        if node is None:
            continue
        for parent in node.parents:
            if parent not in distances:
                distances[parent] = step + 1
                queue.append(parent)
    return distances


def _created_key(node: Optional[RevisionNode]) -> Tuple[datetime, str]:
    """Sort key: creation time (unknown → the epoch), then id, so ties resolve the same way."""
    if node is None:
        return _EPOCH, ""
    created = node.created_at
    if isinstance(created, str):
        try:
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            created = None
    if isinstance(created, datetime) and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (created if isinstance(created, datetime) else _EPOCH), node.revision_id


def merge_base_candidates(
    nodes: Union[Iterable[RevisionNode], Mapping[str, RevisionNode]], rev_a: str, rev_b: str
) -> List[str]:
    """Every **best** common ancestor of two revisions: common to both, ancestor of no other.

    Usually one revision; several in a criss-cross history (two branches that merged each other).
    A revision counts as its own ancestor, so when one revision is an ancestor of the other, that
    revision is the only candidate.

    Args:
        nodes: The ancestor closure of both revisions.
        rev_a: One revision id.
        rev_b: The other.

    Returns:
        The candidates, newest first; empty when the histories are disjoint.
    """
    graph = nodes if isinstance(nodes, Mapping) else _index(nodes)
    common: Set[str] = set(ancestors(graph, [rev_a])) & set(ancestors(graph, [rev_b]))
    if not common:
        return []
    # A common revision is dominated when it is a strict ancestor of another common one. One walk
    # from all common revisions' parents marks every dominated revision at once.
    parents_of_common = [p for c in common for p in (graph[c].parents if c in graph else ())]
    dominated = set(ancestors(graph, parents_of_common)) if parents_of_common else set()
    best = [c for c in common if c not in dominated]
    return sorted(best, key=lambda rid: _created_key(graph.get(rid)), reverse=True)


def merge_base(
    nodes: Union[Iterable[RevisionNode], Mapping[str, RevisionNode]], rev_a: str, rev_b: str
) -> Optional[str]:
    """The merge base of two revisions (``mergeBase(revA, revB)``).

    Of the best common ancestors (:func:`merge_base_candidates`) the most recently created is
    chosen — the one nearest the tips in a criss-cross history — with the id breaking a tie.

    Args:
        nodes: The ancestor closure of both revisions.
        rev_a: One revision id.
        rev_b: The other.

    Returns:
        The merge-base revision id, or ``None`` when the two histories share no revision.
    """
    candidates = merge_base_candidates(nodes, rev_a, rev_b)
    return candidates[0] if candidates else None


def history_window(
    nodes: Union[Iterable[RevisionNode], Mapping[str, RevisionNode]],
    tips: Sequence[str],
    *,
    depth: int = DEFAULT_HISTORY_DEPTH,
    limit: int = DEFAULT_HISTORY_LIMIT,
) -> HistoryWindow:
    """The part of the history within ``depth`` parent steps of ``tips``, at most ``limit`` revisions.

    Revisions are ordered nearest the tips first, then newest first, and the limit keeps the
    nearest ones. A tip that is not in ``nodes`` is left out.

    Args:
        nodes: The ancestor closure of the tips.
        tips: The revisions to start from.
        depth: The most parent steps to take (clamped to ``0..MAX_HISTORY_DEPTH``).
        limit: The most revisions to return (clamped to ``1..MAX_HISTORY_LIMIT``).

    Returns:
        The window, and whether the depth or the limit cut it short.
    """
    graph = nodes if isinstance(nodes, Mapping) else _index(nodes)
    depth = max(0, min(int(depth), MAX_HISTORY_DEPTH))
    limit = max(1, min(int(limit), MAX_HISTORY_LIMIT))
    distances = {rid: d for rid, d in ancestors(graph, tips, depth=depth).items() if rid in graph}
    beyond_depth = any(
        parent in graph and parent not in distances
        for rid, d in distances.items()
        if d == depth
        for parent in graph[rid].parents
    )
    ordered = sorted(distances, key=lambda rid: (distances[rid], _negated(graph[rid])))
    kept = ordered[:limit]
    return HistoryWindow(
        nodes=[graph[rid] for rid in kept],
        distances={rid: distances[rid] for rid in kept},
        truncated=beyond_depth or len(ordered) > limit,
    )


def _negated(node: RevisionNode) -> Tuple[float, str]:
    """Newest-first sort key (``sorted`` ascending): negated timestamp, then id."""
    created, rid = _created_key(node)
    return -created.timestamp(), rid
