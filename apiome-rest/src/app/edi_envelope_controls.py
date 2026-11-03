"""EDI envelope controls — MFI-20.5 (#3989).

Every EDI envelope closes with a trailer that repeats its header's **control number** and declares a
**control total**: how many segments, transaction sets or groups it closed. A receiver checks both
before it reads a single business value, and an interchange whose trailers disagree with what they
close is rejected (an X12 ``997`` / ``999`` or an EDIFACT ``CONTRL`` says so). The parsers read the
structure and move on, so this module records the declared and the observed figures side by side,
for the lint packs (:mod:`app.edix12_lint`, :mod:`app.edifact_lint`) to compare:

* :func:`x12_controls` — ``ISA``/``IEA``, ``GS``/``GE`` and ``ST``/``SE``, read from the interchange
  text with the delimiter-aware scanner (:mod:`app.edix12_segment_scan`), because ``pyx12`` drops the
  trailers;
* :func:`edifact_controls` — ``UNB``/``UNZ``, ``UNG``/``UNE`` and ``UNH``/``UNT``, read from the
  trailers :mod:`app.edifact_parser` keeps.

Both return JSON-ready mappings the normalizers store under ``extras`` (``x12_controls`` /
``edifact_controls``). A figure the source does not carry is ``None``, never a guess, so a rule can
tell "declared wrong" from "not declared".

**Counting.** X12 ``SE01`` counts the segments from ``ST`` to ``SE`` inclusive; ``GE01`` counts the
group's transaction sets; ``IEA01`` counts the interchange's functional groups. EDIFACT ``UNT`` 0074
counts the segments from ``UNH`` to ``UNT`` inclusive; ``UNE`` 0060 counts the group's messages;
``UNZ`` 0036 counts the interchange's groups, or its messages when it has no groups.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .edifact_parser import EdifactDocument, EdifactMessage, EdifactSegment
from .edix12_segment_scan import detect_delimiters, scan_segments, split_elements

__all__ = [
    "EDIFACT_CONTROLS_KEY",
    "X12_CONTROLS_KEY",
    "edifact_controls",
    "x12_controls",
]

#: The canonical-model extras key the X12 normalizer records :func:`x12_controls` under.
X12_CONTROLS_KEY = "x12_controls"

#: The canonical-model extras key the EDIFACT normalizer records :func:`edifact_controls` under.
EDIFACT_CONTROLS_KEY = "edifact_controls"


def _int_or_none(text: Optional[str]) -> Optional[int]:
    """``text`` as an integer, or ``None`` when it is missing or not a whole number."""
    value = (text or "").strip()
    return int(value) if value.isdigit() else None


def _element(elements: List[str], position: int) -> Optional[str]:
    """The stripped value at 1-based ``position`` of a split segment, or ``None`` when not written."""
    if position < len(elements):
        return elements[position].strip()
    return None


# ===========================================================================
# X12
# ===========================================================================


def x12_controls(source: str) -> Optional[Dict[str, Any]]:
    """Read every X12 envelope's control number and control total, declared beside observed.

    The scan is sequential: ``GS`` opens a group, ``ST`` a transaction set, and each trailer closes
    the innermost open envelope. Segments outside any envelope are ignored; an envelope the text
    never closes keeps ``None`` for its trailer's figures.

    Args:
        source: The interchange text, exactly as imported.

    Returns:
        ``{"interchange": {...}, "groups": [{..., "transactions": [{...}]}]}`` — see the module
        docstring for what each total counts — or ``None`` when the text has no readable ``ISA``
        header.
    """
    delimiters = detect_delimiters(source)
    if delimiters is None:
        return None
    segments, _complete = scan_segments(source, delimiters)
    if not segments or segments[0].segment_id != "ISA":
        return None

    isa = split_elements(segments[0].text, delimiters)
    interchange: Dict[str, Any] = {
        "control_number": _element(isa, 13),
        "usage_indicator": _element(isa, 15),
        "trailer_control_number": None,
        "declared_group_count": None,
        "group_count": 0,
    }
    groups: List[Dict[str, Any]] = []
    group: Optional[Dict[str, Any]] = None
    transaction: Optional[Dict[str, Any]] = None

    for segment in segments[1:]:
        elements = split_elements(segment.text, delimiters)
        seg_id = segment.segment_id
        if seg_id == "GS":
            group = {
                "functional_id": _element(elements, 1),
                "control_number": _element(elements, 6),
                "version": _element(elements, 8),
                "trailer_control_number": None,
                "declared_transaction_count": None,
                "transaction_count": 0,
                "transactions": [],
            }
            groups.append(group)
            interchange["group_count"] += 1
        elif seg_id == "ST":
            transaction = {
                "set_id": _element(elements, 1),
                "control_number": _element(elements, 2),
                "trailer_control_number": None,
                "declared_segment_count": None,
                # ST itself; SE adds one more when it closes the set.
                "segment_count": 1,
            }
            if group is not None:
                group["transactions"].append(transaction)
                group["transaction_count"] += 1
        elif seg_id == "SE" and transaction is not None:
            transaction["segment_count"] += 1
            transaction["declared_segment_count"] = _int_or_none(_element(elements, 1))
            transaction["trailer_control_number"] = _element(elements, 2)
            transaction = None
        elif seg_id == "GE" and group is not None:
            group["declared_transaction_count"] = _int_or_none(_element(elements, 1))
            group["trailer_control_number"] = _element(elements, 2)
            group = None
        elif seg_id == "IEA":
            interchange["declared_group_count"] = _int_or_none(_element(elements, 1))
            interchange["trailer_control_number"] = _element(elements, 2)
        elif transaction is not None:
            transaction["segment_count"] += 1

    return {"interchange": interchange, "groups": groups}


# ===========================================================================
# EDIFACT
# ===========================================================================


def _trailer(segment: Optional[EdifactSegment]) -> Dict[str, Any]:
    """The control total (element 1) and control reference (element 2) of a ``UNT``/``UNE``/``UNZ``."""
    if segment is None:
        return {"declared_count": None, "trailer_reference": None}
    return {
        "declared_count": _int_or_none(segment.component(1)),
        "trailer_reference": segment.component(2).strip() or None,
    }


def _message_controls(message: EdifactMessage) -> Dict[str, Any]:
    """One message's ``UNH`` reference, ``UNT`` figures and its observed segment count."""
    trailer = _trailer(message.trailer)
    return {
        "message_type": message.message_type,
        "reference": message.reference or None,
        "directory": message.directory or None,
        "trailer_reference": trailer["trailer_reference"],
        "declared_segment_count": trailer["declared_count"],
        # UNH and UNT around the body segments.
        "segment_count": len(message.segments) + 2,
    }


def edifact_controls(document: EdifactDocument) -> Dict[str, Any]:
    """Read every EDIFACT envelope's control reference and control count, declared beside observed.

    Args:
        document: The parsed interchange.

    Returns:
        ``{"interchange": {...}, "groups": [{..., "messages": [...]}], "messages": [...]}``. Exactly
        one of ``groups`` and ``messages`` is non-empty, as in the interchange itself (ISO 9735).
    """
    interchange = document.interchange
    trailer = _trailer(interchange.trailer)
    groups = [
        {
            "group_id": group.group_id or None,
            "reference": group.reference or None,
            "trailer_reference": _trailer(group.trailer)["trailer_reference"],
            "declared_message_count": _trailer(group.trailer)["declared_count"],
            "message_count": len(group.messages),
            "messages": [_message_controls(message) for message in group.messages],
        }
        for group in interchange.functional_groups
    ]
    return {
        "interchange": {
            "control_reference": interchange.control_reference or None,
            "test_indicator": interchange.test_indicator or None,
            "trailer_reference": trailer["trailer_reference"],
            "declared_count": trailer["declared_count"],
            # UNZ counts the groups when there are any, else the messages.
            "count": len(groups) if groups else len(interchange.messages),
        },
        "groups": groups,
        "messages": [_message_controls(message) for message in interchange.messages],
    }
