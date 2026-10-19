"""Pure helpers for ``apiome graph`` — CDG-3.2 (#5967).

The ``--depends-on`` grammar is the one ``x-apiome-depends-on`` uses in a spec:
``<slug>[#<pointer>]`` names a project or catalog item by slug, with an optional JSON pointer into
it. ``<kind>:<id>[#<pointer>]`` names any entity by id.
"""

from __future__ import annotations

import json
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


_METHODS = ("GET", "PUT", "POST", "DELETE", "OPTIONS", "HEAD", "PATCH", "TRACE")

#: The evidence sections of a blast-radius answer, in display order, with their labels.
EVIDENCE_SECTIONS = (
    ("verification_runs", "Verification runs"),
    ("consumer_contracts", "Consumer contracts"),
    ("deploy_gate_evaluations", "Deploy-gate evaluations"),
    ("sdk_regen_targets", "SDK regeneration targets"),
    ("agent_toolset_tools", "Agent toolset tools"),
    ("mock_fixture_packs", "Mock fixture packs and scenarios"),
    ("sunset_consumers", "Consumers on deprecated versions"),
)


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def operation_pointer(operation: str) -> str:
    """``"GET /pets/{id}"`` → ``/paths/~1pets~1{id}/get``.

    Raises:
        ValueError: The value is not ``METHOD /path``.
    """
    method, _, path = (operation or "").strip().partition(" ")
    path = path.strip()
    if method.upper() not in _METHODS or not path.startswith("/"):
        raise ValueError(f"'{operation}' is not an operation; use METHOD /path, e.g. \"GET /pets/{{id}}\"")
    return f"/paths/{_escape(path)}/{method.lower()}"


def schema_pointer(name: str) -> str:
    """``Pet`` → ``/components/schemas/Pet``.

    Raises:
        ValueError: The name is empty.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("a schema name is required")
    return f"/components/schemas/{_escape(name)}"


def impact_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    """One table row per affected entity, direct first."""
    rows = []
    for entity in [*(body.get("direct") or []), *(body.get("transitive") or [])]:
        owner = entity.get("owner") or {}
        rows.append(
            {
                "depth": entity.get("depth"),
                "kind": entity.get("kind") or "",
                "name": entity.get("slug") or entity.get("name") or entity.get("id") or "",
                "edge": entity.get("edge_kind") or "",
                "provenance": entity.get("provenance") or "",
                "owner": owner.get("slug") or "",
            }
        )
    return rows


def evidence_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    """One table row per evidence section, with its count."""
    evidence = body.get("invalidated_evidence") or {}
    return [{"evidence": label, "count": len(evidence.get(key) or [])} for key, label in EVIDENCE_SECTIONS]


def export_truncated(text: str, export_format: str) -> bool:
    """Whether a graph export says it was cut short at its 10,000-edge bound.

    Args:
        text: The export as returned by ``GET …/export``.
        export_format: ``json`` or ``dot``.

    Returns:
        ``truncated`` of a JSON export, or whether a DOT export's first-line comment says
        "truncated". ``False`` for text that cannot be read.
    """
    if export_format == "dot":
        first = text.split("\n", 1)[0]
        return first.startswith("//") and "truncated" in first
    try:
        return bool(json.loads(text).get("truncated"))
    except (ValueError, AttributeError):
        return False
