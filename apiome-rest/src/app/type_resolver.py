"""Re-resolution and dependency listing for the type registry (#3459).

The ``$ref`` edges of every primitive are computed and flagged ``resolved`` /
``unresolved`` on save / import (#3456, #3457): each edge is a persisted
``{relative_ref, resolved_target, status}`` record on ``apiome.primitives.refs``. Over
time those statuses drift from reality — a missing target is later created (the edge
should now resolve) or a referenced type is deleted (a resolved edge should now dangle).

This module backs the resolver API (``POST /v1/types/{tenant_slug}/resolve``): given a
primitive's stored edges and a lookup that maps an absolute registry ``$id`` to the
primitive currently carrying it (within the caller's read scope), it **re-evaluates each
edge's status** against the present registry state and, for resolved edges, **attaches the
dependency target's identity** (id + name) so the resolver UI (#3470) can render the
dependency graph. The status recomputation uses exactly the same existence test as
save-time resolution (``get_primitive_by_schema_id`` is not ``None``), so a re-resolve and
a re-save converge on the same answer.

Edge *set* discovery (walking a schema's ``$ref`` values) and relative-URI resolution stay
in :mod:`app.primitives_resolver` / :mod:`app.primitives_scope`; this module only refreshes
the status of edges that were already discovered, which is the "re-resolve updates statuses"
half of the acceptance criteria and avoids needing each primitive's ``base_uri`` again.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

__all__ = [
    "STATUS_RESOLVED",
    "STATUS_UNRESOLVED",
    "reresolve_edges",
]

# Edge status values, matching app.primitives_resolver. Cycle detection (``circular``)
# is a separate ticket (#3458); this pass emits only resolved / unresolved.
STATUS_RESOLVED = "resolved"
STATUS_UNRESOLVED = "unresolved"

# A lookup mapping an absolute registry ``$id`` to the primitive row that carries it
# (within the caller's read scope), or ``None`` when no such visible primitive exists.
TargetLookup = Callable[[str], Optional[Dict[str, Any]]]


def reresolve_edges(
    edges: Optional[List[Dict[str, Any]]],
    target_lookup: TargetLookup,
) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]], bool]:
    """Re-evaluate a primitive's ``$ref`` edges against the current registry state (#3459).

    For each stored edge, the target ``$id`` (``resolved_target``) is looked up in the
    caller's read scope. The edge is ``resolved`` when a visible primitive currently
    carries that ``$id``, else ``unresolved`` — recomputed fresh, regardless of the
    status persisted earlier. Edge order is preserved, and an edge with no
    ``resolved_target`` (a malformed/legacy row) is treated as ``unresolved``.

    Two views are returned for the same edges:

    * the **persisted** form (``{relative_ref, resolved_target, status}``) — the exact
      shape stored on ``apiome.primitives.refs``, written back only when a status changed;
    * the **dependency** form — the persisted fields plus the resolved target's
      ``target_id`` / ``target_name`` (both ``None`` for an unresolved edge) — the
      dependency-graph edges the resolver UI lists (#3470).

    Args:
        edges: The primitive's stored ``refs`` edge list (may be ``None`` or empty).
        target_lookup: Maps an absolute registry ``$id`` to the visible primitive row
            carrying it, or ``None`` when none exists. The route backs this with a
            tenant-scoped, memoized ``get_primitive_by_schema_id`` so scope (#3453) is
            honored and each distinct target is queried once.

    Returns:
        A ``(persisted_edges, dependency_edges, changed)`` triple, where ``changed`` is
        ``True`` when at least one edge's recomputed status differs from its stored one
        (the signal to persist ``persisted_edges`` back to the primitive).
    """
    persisted: List[Dict[str, str]] = []
    dependencies: List[Dict[str, Any]] = []
    changed = False

    for edge in edges or []:
        relative_ref = edge.get("relative_ref")
        resolved_target = edge.get("resolved_target")
        prior_status = edge.get("status")

        target_row = target_lookup(resolved_target) if resolved_target else None
        status = STATUS_RESOLVED if target_row is not None else STATUS_UNRESOLVED
        if status != prior_status:
            changed = True

        persisted_edge = {
            "relative_ref": relative_ref,
            "resolved_target": resolved_target,
            "status": status,
        }
        persisted.append(persisted_edge)
        dependencies.append(
            {
                **persisted_edge,
                "target_id": str(target_row["id"]) if target_row is not None else None,
                "target_name": target_row.get("name") if target_row is not None else None,
            }
        )

    return persisted, dependencies, changed
