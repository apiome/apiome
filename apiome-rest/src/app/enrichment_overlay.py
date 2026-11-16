"""Accepted enrichment as an Overlay document — GVM-4.3 (#5878).

AGX-1.3 (#4531) stores reviewed description proposals per agent toolset (apiome-db V273,
``agent_toolset_enrichments``). Accepted ones are served to agents, but never reach an export.
:func:`enrichment_overlay_document` projects them into an Overlay 1.0 document without migrating
V273: one ``update`` action per accepted row, aimed at the operation (or parameter) by its OpenAPI
path and method. Saved into a revision's overlay chain (``source: enrichment-export``), it puts
the same descriptions in that revision's exports.

Targets are by path, method and parameter ``name``/``in``, not by array index, so the overlay
still applies to a later revision of the same API. When a target no longer exists, the next render
reports an ``overlay.unmatched-target`` finding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .catalog_agents import operation_parts

__all__ = ["ENRICHMENT_OVERLAY_VERSION", "EnrichmentOverlay", "enrichment_overlay_document"]

#: The Overlay revision the projection writes. 1.0 actions (``update``) are all it needs, and every
#: reader of Overlay 1.x accepts it.
ENRICHMENT_OVERLAY_VERSION = "1.0.0"


@dataclass
class EnrichmentOverlay:
    """The projection of a toolset's accepted enrichment.

    Attributes:
        document: The Overlay document (``overlay``, ``info``, ``actions``).
        skipped: Operation keys that are not HTTP operations (for example GraphQL ``Query.user``),
            which an OpenAPI overlay cannot address.
    """

    document: Dict[str, Any]
    skipped: List[str] = field(default_factory=list)

    @property
    def action_count(self) -> int:
        """How many actions the document carries."""
        return len(self.document.get("actions") or [])


def _quoted(value: str) -> str:
    """Quote a value for a JSONPath bracket or filter string literal."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _operation_target(path: str, method: str) -> str:
    """The JSONPath of an OpenAPI operation object."""
    return f"$.paths[{_quoted(path)}].{method}"


def _parameter_target(path: str, method: str, parameter_name: str) -> Optional[str]:
    """The JSONPath of one operation parameter, from a ``location.name`` label.

    Args:
        path: The OpenAPI path.
        method: The lower-case HTTP method.
        parameter_name: AGX-1.3's ``parameter_name`` (``query.limit``).

    Returns:
        The filter target, or ``None`` when the label has no location.
    """
    location, _, name = (parameter_name or "").partition(".")
    if not location or not name:
        return None
    return (
        f"{_operation_target(path, method)}.parameters"
        f"[?(@.name == {_quoted(name)} & @.in == {_quoted(location)})]"
    )


def enrichment_overlay_document(
    rows: Sequence[Mapping[str, Any]],
    *,
    title: str,
    version: str = "1",
) -> EnrichmentOverlay:
    """Project accepted enrichment rows into an Overlay 1.0 document.

    Args:
        rows: ``agent_toolset_enrichments`` rows. Rows that are not ``accepted`` or have no
            ``accepted_description`` are ignored.
        title: ``info.title`` of the overlay (names the toolset and its version).
        version: ``info.version`` of the overlay.

    Returns:
        The :class:`EnrichmentOverlay`. Actions are in ``target_key`` order so the same rows always
        give the same document (and the same fingerprint).
    """
    actions: List[Dict[str, Any]] = []
    skipped: List[str] = []
    accepted = [
        row
        for row in rows
        if row.get("status") == "accepted" and (row.get("accepted_description") or "").strip()
    ]
    for row in sorted(accepted, key=lambda r: str(r.get("target_key") or "")):
        operation_key = str(row.get("operation_key") or "")
        parts = operation_parts(operation_key)
        if parts is None:
            if operation_key not in skipped:
                skipped.append(operation_key)
            continue
        method, path, _pointer = parts
        description = str(row["accepted_description"]).strip()
        if row.get("target_kind") == "parameter":
            target = _parameter_target(path, method, str(row.get("parameter_name") or ""))
            if target is None:
                skipped.append(str(row.get("target_key") or operation_key))
                continue
        else:
            target = _operation_target(path, method)
        actions.append(
            {
                "target": target,
                "description": f"Accepted enrichment for {row.get('target_key') or operation_key}",
                "update": {"description": description},
            }
        )
    document = {
        "overlay": ENRICHMENT_OVERLAY_VERSION,
        "info": {"title": title, "version": version},
        "actions": actions,
    }
    return EnrichmentOverlay(document=document, skipped=skipped)
