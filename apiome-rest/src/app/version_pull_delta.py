"""
Delta pull for GET version (pull): changed OpenAPI ``components.schemas`` entities since a base revision (#2592 / P2-10).

Uses the same two-way diff as merge/rollback (``compare_schemas``) so entity coverage matches Studio semantics.
"""

from __future__ import annotations

from typing import Any, Dict, Set

from .schema_merge import compare_schemas

# Formal guarantee for API consumers (see #2592 acceptance criteria).
SCHEMA_PULL_DELTA_GUARANTEE = (
    "Let C(s) and C(h) be the components.schemas objects of the OpenAPI documents generated for "
    "sinceRevisionId and headRevisionId (same generation pipeline as a full pull). If sinceRevisionId "
    "names a revision in the same project that appears on the ancestor walk from headRevisionId "
    "(parent_version_id / merge_parent_version_id, including head), and the client's local "
    "components.schemas equals C(s), then: delete each name in removedSchemaNames from that object, "
    "then assign schemas[name] = value for each entry in schemas. The result equals C(h) up to JSON "
    "structural equality (same keys and values as a full pull of headRevisionId)."
)


def _top_level_schema_name_from_diff_path(path: str) -> str | None:
    if not path.startswith("schemas."):
        return None
    rest = path[len("schemas.") :]
    if not rest:
        return None
    return rest.split(".", 1)[0]


def _removed_top_level_schema_names_from_diff(diff) -> Set[str]:
    out: Set[str] = set()
    for d in diff.removed:
        if d.item_type != "schema":
            continue
        if not d.path.startswith("schemas."):
            continue
        rest = d.path[len("schemas.") :]
        if ".properties." in rest:
            continue
        if "." in rest:
            # e.g. schemas.Foo.bar — not used for class roots in compare_schemas
            continue
        name = rest
        if name:
            out.add(name)
    return out


def _touched_schema_names_from_diff(diff) -> Set[str]:
    touched: Set[str] = set()
    for d in diff.added + diff.removed + diff.modified:
        n = _top_level_schema_name_from_diff_path(d.path)
        if n:
            touched.add(n)
    return touched


def build_schema_pull_delta(
    since_spec: Dict[str, Any],
    head_spec: Dict[str, Any],
    *,
    since_revision_id: str,
    head_revision_id: str,
) -> Dict[str, Any]:
    """
    Build ``schemaPullDelta`` for the pull JSON body: only schema entities that differ between snapshots.

    ``removedSchemaNames`` lists top-level schema keys removed from since to head. ``schemas`` maps
    each remaining touched entity name to its **full** head snapshot (including unchanged nested
    fragments when any part of that entity changed).
    """
    diff = compare_schemas(since_spec, head_spec)
    head_schemas = (head_spec.get("components") or {}).get("schemas") or {}
    removed_names = sorted(_removed_top_level_schema_names_from_diff(diff))
    touched = _touched_schema_names_from_diff(diff)

    out_schemas: Dict[str, Any] = {}
    for name in sorted(touched):
        if name in head_schemas:
            out_schemas[name] = head_schemas[name]

    return {
        "sinceRevisionId": since_revision_id,
        "headRevisionId": head_revision_id,
        "removedSchemaNames": removed_names,
        "schemas": out_schemas,
        "guarantee": SCHEMA_PULL_DELTA_GUARANTEE,
    }


def apply_schema_pull_delta_for_test(
    since_components_schemas: Dict[str, Any],
    delta: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply delta to a components.schemas dict (tests / client reference)."""
    out = dict(since_components_schemas)
    for n in delta.get("removedSchemaNames") or []:
        out.pop(n, None)
    for k, v in (delta.get("schemas") or {}).items():
        out[k] = v
    return out
