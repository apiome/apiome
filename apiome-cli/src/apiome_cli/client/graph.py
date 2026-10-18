"""Pure helpers for ``apiome graph`` — CDG-3.2 (#5967).

The ``--depends-on`` grammar is the one ``x-apiome-depends-on`` uses in a spec:
``<slug>[#<pointer>]`` names a project or catalog item by slug, with an optional JSON pointer into
it. ``<kind>:<id>[#<pointer>]`` names any entity by id.
"""

from __future__ import annotations

from typing import Any

from apiome_cli.client.teams import ENTITY_KINDS


def parse_depends_on(spec: str, *, note: str | None = None) -> dict[str, Any]:
    """Turn one ``--depends-on`` value into a REST dependency entry.

    Args:
        spec: ``payments``, ``customers#/components/schemas/Customer`` or ``consumer:<id>``.
        note: A note attached to the entry, if any.

    Returns:
        ``{"to": {...}, "pointer"?: ..., "note"?: ...}``.

    Raises:
        ValueError: The value is empty, the kind is unknown, or the pointer is not ``/…``.
    """
    raw = (spec or "").strip()
    name, _, pointer = raw.partition("#")
    name = name.strip()
    if not name:
        raise ValueError(f"'{spec}' names no entity; use <slug>[#<pointer>] or <kind>:<id>")
    kind, sep, entity_id = name.partition(":")
    if sep:
        kind = kind.strip().replace("-", "_")
        if kind not in ENTITY_KINDS:
            raise ValueError(f"unknown kind '{kind}' in '{spec}'; use one of {', '.join(ENTITY_KINDS)}")
        if not entity_id.strip():
            raise ValueError(f"'{spec}' names a kind but no id")
        entry: dict[str, Any] = {"to": {"kind": kind, "id": entity_id.strip()}}
    else:
        entry = {"to": {"slug": name}}
    pointer = pointer.strip()
    if pointer:
        if not pointer.startswith("/"):
            raise ValueError(f"pointer '{pointer}' in '{spec}' must start with '/'")
        entry["pointer"] = pointer
    if note:
        entry["note"] = note
    return entry


def dependency_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    """One table row per declared edge, then per unresolved reference.

    Args:
        body: The ``GET``/``PUT …/dependencies`` response.

    Returns:
        Rows with ``status`` (``declared`` / ``unresolved: <reason>``), ``edge``, ``target``,
        ``pointer`` and ``source``.
    """
    rows: list[dict[str, Any]] = []
    for edge in body.get("declared") or []:
        evidence = edge.get("evidence") or {}
        rows.append(
            {
                "status": "declared",
                "edge": edge.get("edge_kind") or "",
                "target": evidence.get("reference") or f"{edge.get('to_kind')}:{edge.get('to_id')}",
                "pointer": edge.get("pointer") or "",
                "source": edge.get("source_ref") or "",
            }
        )
    for item in body.get("unresolved") or []:
        rows.append(
            {
                "status": f"unresolved: {item.get('reason') or 'not-found'}",
                "edge": item.get("edge_kind") or "",
                "target": item.get("reference") or "",
                "pointer": item.get("pointer") or "",
                "source": item.get("source_ref") or "",
            }
        )
    return rows
