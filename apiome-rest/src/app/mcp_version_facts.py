"""Derived facts of an MCP endpoint version, stored on the snapshot row (DBP-1.17, #7200).

An ``mcp_endpoint_versions`` row is write-once, and so are its capability items and change rows:
everything the catalog derives from them can be computed when the snapshot is recorded and never
again. :func:`derive_version_facts` computes those facts from the rows
:meth:`app.database.Database.record_mcp_discovery_version` is about to insert, and the method
stores them in the snapshot's own ``INSERT``.

The facts and the SQL they must agree with (migration ``V425``):

==========================  =====================================================================
``tool_count`` …            Items of each kind (``tool`` / ``resource`` / ``resource_template`` /
``prompt_count``            ``prompt``).
``has_destructive``         A tool's ``annotations`` assert ``destructiveHint: true`` — the JSON
                            boolean. A string ``"true"`` does not count.
``read_only_only``          There is at least one tool and *every* tool asserts
                            ``readOnlyHint: true``. A tool with no annotations breaks the claim.
``max_tool_props``          The most top-level ``input_schema.properties`` keys of any tool; ``0``
                            for a tool whose schema has no ``properties`` object; ``None`` when the
                            snapshot has no tools.
``change_count``            Change rows the snapshot introduced.
==========================  =====================================================================

There are two more implementations of the same definitions, both in SQL: the backfill
(``apiome.derive_mcp_version_facts``), for snapshots recorded before the columns existed, and the
expressions the catalog readers fall back to for a snapshot whose facts are still ``NULL``
(``Database._MCP_*_EXPR``). ``apiome.verify_mcp_version_facts()`` compares stored facts with the
recomputed ones; ``tests/test_mcp_version_facts_db.py`` runs it over snapshots recorded through
this module, which is what keeps the three from drifting.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

#: The fact columns of ``mcp_endpoint_versions``, in the order the snapshot ``INSERT`` binds them.
VERSION_FACT_COLUMNS = (
    "tool_count",
    "resource_count",
    "resource_template_count",
    "prompt_count",
    "has_destructive",
    "read_only_only",
    "max_tool_props",
    "change_count",
)

#: Capability kind → the fact column that counts it. Any other kind is not counted.
_KIND_COLUMNS = {
    "tool": "tool_count",
    "resource": "resource_count",
    "resource_template": "resource_template_count",
    "prompt": "prompt_count",
}


def _asserts(annotations: Any, hint: str) -> bool:
    """Whether a tool's annotations assert ``hint`` as the JSON boolean ``true``.

    Args:
        annotations: The tool's ``annotations`` value; anything but a mapping asserts nothing.
        hint: The annotation key (``destructiveHint`` / ``readOnlyHint``).

    Returns:
        ``True`` only for a mapping whose ``hint`` is exactly ``True``.
    """
    return isinstance(annotations, Mapping) and annotations.get(hint) is True


def _top_level_property_count(input_schema: Any) -> int:
    """The number of top-level ``properties`` of a tool's input schema.

    Args:
        input_schema: The tool's ``input_schema``; may be ``None`` or not a mapping.

    Returns:
        The key count of ``input_schema["properties"]`` when that is a mapping, otherwise ``0``.
    """
    if not isinstance(input_schema, Mapping):
        return 0
    properties = input_schema.get("properties")
    return len(properties) if isinstance(properties, Mapping) else 0


def derive_version_facts(
    capability_rows: Iterable[Mapping[str, Any]],
    change_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Compute the facts stored on a snapshot row from the rows written with it.

    Args:
        capability_rows: The snapshot's capability items, as
            :meth:`app.mcp_discovery_engine.DiscoverySurface.to_capability_rows` returns them
            (``item_type``, ``input_schema`` and ``annotations`` are read).
        change_rows: The change rows the snapshot introduces; only their number matters.

    Returns:
        One value per name in :data:`VERSION_FACT_COLUMNS`. Counts and flags are never ``None``;
        ``max_tool_props`` is ``None`` when the snapshot has no tools.
    """
    counts = {column: 0 for column in _KIND_COLUMNS.values()}
    has_destructive = False
    every_tool_read_only = True
    max_tool_props: Optional[int] = None

    for row in capability_rows:
        column = _KIND_COLUMNS.get(str(row.get("item_type")))
        if column is None:
            continue
        counts[column] += 1
        if column != "tool_count":
            continue
        annotations = row.get("annotations")
        if _asserts(annotations, "destructiveHint"):
            has_destructive = True
        if not _asserts(annotations, "readOnlyHint"):
            every_tool_read_only = False
        properties = _top_level_property_count(row.get("input_schema"))
        max_tool_props = properties if max_tool_props is None else max(max_tool_props, properties)

    return {
        **counts,
        "has_destructive": has_destructive,
        "read_only_only": counts["tool_count"] > 0 and every_tool_read_only,
        "max_tool_props": max_tool_props,
        "change_count": len(change_rows),
    }
