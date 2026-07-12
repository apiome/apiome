"""EDI X12 interchange parser — MFI-20.5.

Parses ANSI ASC X12 interchange text into a typed :class:`EdiX12Document` AST using
:mod:`pyx12.x12file`. Syntax errors surface as :class:`EdiX12ParseError`.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from pyx12.x12file import X12Reader

__all__ = [
    "EdiX12ParseError",
    "X12Element",
    "X12Segment",
    "X12TransactionSet",
    "X12FunctionalGroup",
    "X12Interchange",
    "EdiX12Document",
    "is_edix12",
    "parse_edix12",
]


class EdiX12ParseError(ValueError):
    """Raised when EDI X12 text cannot be parsed."""


@dataclass(frozen=True)
class X12Element:
    ref: str
    position: str
    value: str


@dataclass(frozen=True)
class X12Segment:
    id: str
    elements: Tuple[X12Element, ...]
    raw: str


@dataclass(frozen=True)
class X12TransactionSet:
    set_id: str
    control_number: str
    segments: Tuple[X12Segment, ...]


@dataclass(frozen=True)
class X12FunctionalGroup:
    functional_id: str
    version: str
    sender: str
    receiver: str
    control_number: str
    transaction_sets: Tuple[X12TransactionSet, ...]


@dataclass(frozen=True)
class X12Interchange:
    sender_id: str
    receiver_id: str
    version: str
    control_number: str
    element_separator: str
    segment_terminator: str
    functional_groups: Tuple[X12FunctionalGroup, ...]


@dataclass(frozen=True)
class EdiX12Document:
    interchange: X12Interchange
    raw: str


_ISA_RE = re.compile(r"^ISA\*", re.MULTILINE)


def is_edix12(content: str) -> bool:
    """Return ``True`` when ``content`` looks like an ANSI X12 interchange."""
    if not content or not isinstance(content, str):
        return False
    trimmed = content.strip()
    if not trimmed:
        return False
    if not _ISA_RE.search(trimmed):
        return False
    if "GS*" not in trimmed or "ST*" not in trimmed:
        return False
    return True


def _segment_from_reader(seg) -> X12Segment:
    elements: List[X12Element] = []
    for ref, position, _sub, value in seg.values_iterator():
        elements.append(
            X12Element(
                ref=str(ref),
                position=str(position),
                value="" if value is None else str(value),
            )
        )
    return X12Segment(id=seg.get_seg_id(), elements=tuple(elements), raw=str(seg))


def _element_value(segment: X12Segment, position: str) -> str:
    for element in segment.elements:
        if element.position == position:
            return element.value
    return ""


def _parse_segments(content: str) -> List[X12Segment]:
    try:
        reader = X12Reader(io.StringIO(content))
    except Exception as exc:
        raise EdiX12ParseError(f"Malformed EDI X12 interchange: {exc}") from exc
    segments = [_segment_from_reader(seg) for seg in reader]
    if not segments:
        raise EdiX12ParseError("EDI X12 interchange contains no segments")
    if segments[0].id != "ISA":
        raise EdiX12ParseError("EDI X12 interchange must begin with an `ISA` segment")
    return segments


def _build_interchange(segments: List[X12Segment]) -> X12Interchange:
    isa = segments[0]
    element_separator = "*"
    segment_terminator = "~"
    if len(isa.raw) >= 106:
        element_separator = isa.raw[3] if len(isa.raw) > 3 else "*"
        segment_terminator = isa.raw[105] if len(isa.raw) > 105 else "~"

    sender_id = _element_value(isa, "06").strip()
    receiver_id = _element_value(isa, "08").strip()
    version = _element_value(isa, "12")
    control_number = _element_value(isa, "13")

    functional_groups: List[X12FunctionalGroup] = []
    current_group: Optional[Dict[str, object]] = None
    current_transaction: Optional[Dict[str, object]] = None
    body_segments: List[X12Segment] = []

    for segment in segments[1:]:
        seg_id = segment.id
        if seg_id == "GS":
            if current_group is not None:
                raise EdiX12ParseError("Nested `GS` segments are not supported")
            current_group = {
                "functional_id": _element_value(segment, "01"),
                "sender": _element_value(segment, "02"),
                "receiver": _element_value(segment, "03"),
                "control_number": _element_value(segment, "06"),
                "version": _element_value(segment, "08"),
                "transactions": [],
            }
            continue
        if seg_id == "ST":
            if current_group is None:
                raise EdiX12ParseError("`ST` segment encountered before `GS`")
            if current_transaction is not None:
                raise EdiX12ParseError("Nested `ST` segments are not supported in one pass")
            current_transaction = {
                "set_id": _element_value(segment, "01"),
                "control_number": _element_value(segment, "02"),
                "segments": [],
            }
            body_segments = []
            continue
        if seg_id == "SE":
            if current_transaction is None:
                raise EdiX12ParseError("`SE` segment encountered before `ST`")
            current_transaction["segments"] = tuple(body_segments)
            current_group["transactions"].append(
                X12TransactionSet(
                    set_id=str(current_transaction["set_id"]),
                    control_number=str(current_transaction["control_number"]),
                    segments=tuple(body_segments),
                )
            )
            current_transaction = None
            body_segments = []
            continue
        if seg_id == "GE":
            if current_group is None:
                raise EdiX12ParseError("`GE` segment encountered before `GS`")
            functional_groups.append(
                X12FunctionalGroup(
                    functional_id=str(current_group["functional_id"]),
                    version=str(current_group["version"]),
                    sender=str(current_group["sender"]),
                    receiver=str(current_group["receiver"]),
                    control_number=str(current_group["control_number"]),
                    transaction_sets=tuple(current_group["transactions"]),
                )
            )
            current_group = None
            continue
        if seg_id in {"IEA", "TA1"}:
            continue
        if current_transaction is not None:
            body_segments.append(segment)

    if not functional_groups:
        raise EdiX12ParseError("EDI X12 interchange defines no functional groups")
    if not any(group.transaction_sets for group in functional_groups):
        raise EdiX12ParseError("EDI X12 interchange defines no transaction sets")

    return X12Interchange(
        sender_id=sender_id,
        receiver_id=receiver_id,
        version=version,
        control_number=control_number,
        element_separator=element_separator,
        segment_terminator=segment_terminator,
        functional_groups=tuple(functional_groups),
    )


def parse_edix12(content: str, *, source_label: Optional[str] = None) -> EdiX12Document:
    """Parse EDI X12 interchange text into an :class:`EdiX12Document`."""
    if not content or not content.strip():
        raise EdiX12ParseError("Invalid or empty EDI X12 document")
    if not is_edix12(content):
        label = f" ({source_label})" if source_label else ""
        raise EdiX12ParseError(f"Content does not appear to be an EDI X12 interchange{label}")
    segments = _parse_segments(content)
    return EdiX12Document(interchange=_build_interchange(segments), raw=content)
