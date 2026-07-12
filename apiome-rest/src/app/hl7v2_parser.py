"""HL7 v2.x message parser — MFI-22.4.

Parses HL7 v2 pipe-and-hat encoded messages into a typed :class:`Hl7V2Document` AST.
Syntax errors surface as :class:`Hl7V2ParseError`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

__all__ = [
    "Hl7V2ParseError",
    "Hl7Field",
    "Hl7Segment",
    "Hl7Message",
    "Hl7V2Document",
    "is_hl7v2",
    "parse_hl7v2",
]

_MSH_LINE_RE = re.compile(r"^MSH.", re.MULTILINE)
_FHIR_JSON_RE = re.compile(r'"resourceType"\s*:', re.MULTILINE)
_HL7_FHIR_URL_RE = re.compile(r"hl7\.org/fhir", re.IGNORECASE)


class Hl7V2ParseError(ValueError):
    """Raised when HL7 v2 text cannot be parsed."""


@dataclass(frozen=True)
class Hl7Field:
    index: int
    value: str


@dataclass(frozen=True)
class Hl7Segment:
    id: str
    fields: Tuple[Hl7Field, ...]
    raw: str


@dataclass(frozen=True)
class Hl7Message:
    field_separator: str
    encoding_characters: str
    sending_application: Optional[str]
    sending_facility: Optional[str]
    receiving_application: Optional[str]
    receiving_facility: Optional[str]
    message_type: Optional[str]
    message_control_id: Optional[str]
    processing_id: Optional[str]
    version_id: Optional[str]
    segments: Tuple[Hl7Segment, ...]


@dataclass(frozen=True)
class Hl7V2Document:
    message: Hl7Message
    raw: str


def is_hl7v2(content: str) -> bool:
    """Return ``True`` when ``content`` looks like an HL7 v2.x message."""
    if not content or not isinstance(content, str):
        return False
    trimmed = content.strip()
    if not trimmed:
        return False
    if _FHIR_JSON_RE.search(trimmed) or _HL7_FHIR_URL_RE.search(trimmed):
        return False
    if not _MSH_LINE_RE.search(trimmed):
        return False
    first_line = re.split(r"[\r\n]+", trimmed, maxsplit=1)[0]
    if not first_line.startswith("MSH") or len(first_line) < 8:
        return False
    field_sep = first_line[3]
    parts = first_line[4:].split(field_sep)
    if not parts or len(parts[0]) < 4:
        return False
    encoding = parts[0]
    return "^" in encoding and "\\" in encoding and "&" in encoding


def _split_segments(content: str) -> List[str]:
    normalized = content.replace("\r\n", "\r").replace("\n", "\r")
    return [segment.strip() for segment in normalized.split("\r") if segment.strip()]


def _parse_msh_fields(segment_text: str) -> Tuple[str, str, Tuple[Hl7Field, ...]]:
    if not segment_text.startswith("MSH") or len(segment_text) < 5:
        raise Hl7V2ParseError("HL7 message must begin with an `MSH` segment")
    field_sep = segment_text[3]
    remainder = segment_text[4:]
    parts = remainder.split(field_sep)
    if not parts:
        raise Hl7V2ParseError("Invalid `MSH` segment: encoding characters are required")
    encoding_characters = parts[0]
    values = parts[1:]
    fields: List[Hl7Field] = [
        Hl7Field(index=1, value=field_sep),
        Hl7Field(index=2, value=encoding_characters),
    ]
    for offset, value in enumerate(values, start=3):
        fields.append(Hl7Field(index=offset, value=value))
    return field_sep, encoding_characters, tuple(fields)


def _parse_segment(segment_text: str, *, field_sep: str) -> Hl7Segment:
    parts = segment_text.split(field_sep)
    if not parts or not parts[0]:
        raise Hl7V2ParseError(f"Invalid HL7 segment: {segment_text!r}")
    seg_id = parts[0]
    fields = tuple(Hl7Field(index=index, value=value) for index, value in enumerate(parts[1:], start=1))
    return Hl7Segment(id=seg_id, fields=fields, raw=segment_text)


def _field_value(fields: Tuple[Hl7Field, ...], index: int) -> Optional[str]:
    for field in fields:
        if field.index == index:
            return field.value
    return None


def parse_hl7v2(content: str, *, source_label: Optional[str] = None) -> Hl7V2Document:
    """Parse HL7 v2 source into an :class:`Hl7V2Document`."""
    if not content or not content.strip():
        raise Hl7V2ParseError("Invalid or empty HL7 v2 content")
    if not is_hl7v2(content):
        raise Hl7V2ParseError("Content does not appear to be an HL7 v2.x message")

    segment_texts = _split_segments(content)
    if not segment_texts or not segment_texts[0].startswith("MSH"):
        label = f" ({source_label})" if source_label else ""
        raise Hl7V2ParseError(f"HL7 v2 message must begin with `MSH`{label}")

    field_sep, encoding_characters, msh_fields = _parse_msh_fields(segment_texts[0])
    segments: List[Hl7Segment] = [
        Hl7Segment(id="MSH", fields=msh_fields, raw=segment_texts[0])
    ]
    for segment_text in segment_texts[1:]:
        segments.append(_parse_segment(segment_text, field_sep=field_sep))

    if len(segments) < 2:
        label = f" ({source_label})" if source_label else ""
        raise Hl7V2ParseError(f"No HL7 segments found after `MSH`{label}")

    message = Hl7Message(
        field_separator=field_sep,
        encoding_characters=encoding_characters,
        sending_application=_field_value(msh_fields, 3),
        sending_facility=_field_value(msh_fields, 4),
        receiving_application=_field_value(msh_fields, 5),
        receiving_facility=_field_value(msh_fields, 6),
        message_type=_field_value(msh_fields, 9),
        message_control_id=_field_value(msh_fields, 10),
        processing_id=_field_value(msh_fields, 11),
        version_id=_field_value(msh_fields, 12),
        segments=tuple(segments),
    )
    return Hl7V2Document(message=message, raw=content)
