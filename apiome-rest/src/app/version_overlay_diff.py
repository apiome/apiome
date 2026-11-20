"""Before / after view of what an overlay chain changed — COA-2.7 (#7050).

The overlay manager on the Versions screen shows, for every value the chain changed, the value in
the revision's source next to the value in the resolved document, and the overlay action(s) that
changed it (per-value provenance). This module builds those rows from the provenance ledger the
render already produces (:class:`app.export_overlay.ExportOverlayReport`), so the diff can never
disagree with what an export renders.

Pure: no I/O, inputs are never mutated.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .export_overlay import ExportOverlayLedgerRow

__all__ = ["MISSING", "overlay_value_diff", "resolve_pointer"]


class _Missing:
    """Sentinel for "no value at this pointer" (distinct from a JSON ``null``)."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "MISSING"


#: Returned by :func:`resolve_pointer` when the pointer does not resolve.
MISSING = _Missing()


def _unescape(token: str) -> str:
    """Decode one RFC 6901 reference token (``~1`` → ``/``, then ``~0`` → ``~``)."""
    return token.replace("~1", "/").replace("~0", "~")


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 JSON Pointer against ``document``.

    Args:
        document: Any parsed JSON value.
        pointer: ``""`` for the whole document, else ``/a/b/0``.

    Returns:
        The value at the pointer, or :data:`MISSING` when any step does not exist.
    """
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        return MISSING
    node = document
    for raw in pointer[1:].split("/"):
        token = _unescape(raw)
        if isinstance(node, Mapping):
            if token not in node:
                return MISSING
            node = node[token]
        elif isinstance(node, list):
            if not token.isdigit() or int(token) >= len(node):
                return MISSING
            node = node[int(token)]
        else:
            return MISSING
    return node


def overlay_value_diff(
    source: Mapping[str, Any],
    resolved: Mapping[str, Any],
    ledger: Sequence[ExportOverlayLedgerRow],
) -> List[Dict[str, Any]]:
    """One before / after row per value the chain changed, with the actions that changed it.

    Rows follow the order each pointer was first changed. When several actions change the same
    value, every one is listed in ``changed_by`` (application order), so the last entry is the
    value's final writer. The declared-truncation ledger row is skipped (the report says how many
    changes the cap left out).

    A pointer is resolved against the source for ``before`` and the resolved document for
    ``after``; a value the chain added has no ``before`` and a value it removed has no ``after``
    (``before_present`` / ``after_present`` tell an absent value from a JSON ``null``). A later
    removal inside the same array can shift an earlier pointer; the row then shows the value now
    at that position.

    Args:
        source: The revision's source document (before the chain).
        resolved: The document after the chain.
        ledger: The report's ledger rows, in application order.

    Returns:
        ``[{pointer, kind, before, before_present, after, after_present, changed_by}]`` where
        ``kind`` is the last action's change kind and ``changed_by`` is
        ``[{overlay, action_index, target, kind}]``.
    """
    order: List[str] = []
    writers: Dict[str, List[Dict[str, Any]]] = {}
    for row in ledger:
        if row.kind == "truncated":
            continue
        if row.pointer not in writers:
            order.append(row.pointer)
            writers[row.pointer] = []
        writers[row.pointer].append(
            {"overlay": row.overlay, "action_index": row.action_index, "target": row.target, "kind": row.kind}
        )

    rows: List[Dict[str, Any]] = []
    for pointer in order:
        before, before_present = _value(source, pointer)
        after, after_present = _value(resolved, pointer)
        changed_by = writers[pointer]
        rows.append(
            {
                "pointer": pointer,
                "kind": changed_by[-1]["kind"],
                "before": before,
                "before_present": before_present,
                "after": after,
                "after_present": after_present,
                "changed_by": changed_by,
            }
        )
    return rows


def _value(document: Mapping[str, Any], pointer: str) -> Tuple[Optional[Any], bool]:
    """``(value, present)`` for a pointer; ``(None, False)`` when it does not resolve."""
    value = resolve_pointer(document, pointer)
    if value is MISSING:
        return None, False
    return value, True
