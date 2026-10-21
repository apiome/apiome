"""UN/EDIFACT → canonical model normalizer — FMT-6.1 (#5445).

Maps a parsed :class:`~app.edifact_parser.EdifactDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA`, exactly the way the X12 normalizer
(:mod:`app.edix12_normalizer`) maps an X12 interchange:

* the canonical model describes **one** schema, so it is derived from the first functional group's
  first message (or the first message, when the interchange carries no groups). The payload analysis
  keeps the rest and says so (``edifact.canonical_projection_subset``);
* a segment that occurs once contributes its element values as fields of the message type, named by
  reference (``BGM01``, ``DTM01-2`` for a composite's second component);
* a segment that repeats becomes its own record type, referenced from the message type as a list,
  with the first occurrence as its prototype;
* the dialect profile the interchange is written in (EANCOM, ODETTE/VDA or plain UN/EDIFACT,
  FMT-6.5 — :mod:`app.edi_dialect_profiles`) is recorded under ``format_profile`` with its evidence.

Empty positions contribute no field — a field is a value the message carried — and the envelope
(``UNB``/``UNG``/``UNH``/``UNT``/``UNE``/``UNZ``) is recorded in ``extras`` rather than as types.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Type,
    TypeKind,
    TypeRef,
)
from .edi_dialect_profiles import PROFILE_EXTRAS_KEY, edifact_profile
from .edifact_parser import (
    EdifactDocument,
    EdifactElement,
    EdifactFunctionalGroup,
    EdifactMessage,
    EdifactSegment,
)
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = [
    "EdifactNormalizer",
    "canonical_message",
    "element_values",
    "message_record_types",
    "segment_template",
]

_FORMAT_KEY = "edifact"


def element_values(segment: EdifactSegment) -> List[Tuple[str, str]]:
    """Return a segment's non-empty values as ``(reference, value)`` pairs, in position order.

    A simple element is named ``TAG`` + its two-digit position (``BGM01``); each component of a
    composite element is named with its 1-based index appended (``DTM01-2``). Only the first
    occurrence of a repeated element is read — repetition is the analysis's to describe.

    Args:
        segment: The parsed segment.

    Returns:
        The pairs; empty positions and empty components are omitted.
    """
    values: List[Tuple[str, str]] = []
    for element in segment.elements:
        reference = f"{segment.tag}{element.position:02d}"
        if element.is_composite:
            for index, component in enumerate(element.components, start=1):
                if component:
                    values.append((f"{reference}-{index}", component))
        elif element.value:
            values.append((reference, element.value))
    return values


def canonical_message(
    document: EdifactDocument,
) -> Tuple[Optional[EdifactFunctionalGroup], EdifactMessage]:
    """Return the message the canonical model is derived from, with its group.

    Args:
        document: The parsed interchange.

    Returns:
        ``(group, message)`` — the first functional group and its first message, or ``(None, first
        message)`` when the interchange carries no groups.
    """
    interchange = document.interchange
    for group in interchange.functional_groups:
        if group.messages:
            return group, group.messages[0]
    return None, interchange.messages[0]


def _segment_record_type(segment: EdifactSegment, *, namespace: str) -> Type:
    """Build the record type for a repeating segment from its prototype occurrence."""
    type_key = Keys.type(segment.tag, namespace)
    fields = tuple(
        CanonicalField(
            key=Keys.field(type_key, reference),
            name=reference,
            type=TypeRef(name="string", nullable=False),
            field_number=index,
            default=value or None,
        )
        for index, (reference, value) in enumerate(element_values(segment), start=1)
    )
    return Type(key=type_key, name=segment.tag, kind=TypeKind.RECORD, fields=fields)


def message_record_types(
    message_type: str, segments: Sequence[EdifactSegment], *, namespace: str
) -> Tuple[Type, List[Type]]:
    """Build a message's record type and the record types of its repeating segments.

    Shared with the TRADACOMS normalizer (FMT-6.5), whose messages are EDIFACT-style segments
    between their own ``MHD`` and ``MTR`` brackets.

    Args:
        message_type: The message type (``ORDERS``); the record is named ``Message`` + it.
        segments: The message's body segments, envelope segments excluded, in source order.
        namespace: The type-key namespace.

    Returns:
        ``(message record, repeating-segment records)``.
    """
    type_name = f"Message{message_type}"
    type_key = Keys.type(type_name, namespace)
    counts = Counter(segment.tag for segment in segments)
    prototypes: Dict[str, EdifactSegment] = {}
    for segment in segments:
        prototypes.setdefault(segment.tag, segment)

    segment_types: List[Type] = []
    fields: List[CanonicalField] = []
    field_number = 1
    seen: set[str] = set()
    for segment in segments:
        if segment.tag in seen:
            continue
        seen.add(segment.tag)
        if counts[segment.tag] > 1:
            segment_types.append(_segment_record_type(prototypes[segment.tag], namespace=namespace))
            fields.append(
                CanonicalField(
                    key=Keys.field(type_key, segment.tag),
                    name=segment.tag,
                    type=TypeRef(
                        item=TypeRef(name=Keys.type(segment.tag, namespace), nullable=False),
                        nullable=False,
                    ),
                    field_number=field_number,
                )
            )
            field_number += 1
            continue
        for reference, value in element_values(segment):
            fields.append(
                CanonicalField(
                    key=Keys.field(type_key, reference),
                    name=reference,
                    type=TypeRef(name="string", nullable=False),
                    field_number=field_number,
                    default=value or None,
                )
            )
            field_number += 1

    message_type = Type(key=type_key, name=type_name, kind=TypeKind.RECORD, fields=tuple(fields))
    return message_type, segment_types


def _element_template(segment_tag: str, element: EdifactElement) -> Dict[str, object]:
    """One element as written, for the ``edifact_messages`` extras."""
    return {
        "reference": f"{segment_tag}{element.position:02d}",
        "position": f"{element.position:02d}",
        "repetitions": [list(occurrence) for occurrence in element.repetitions],
    }


def segment_template(segment: EdifactSegment) -> Dict[str, object]:
    """One segment as written, for the ``edifact_messages`` (and ``tradacoms_messages``) extras."""
    return {
        "tag": segment.tag,
        "elements": [_element_template(segment.tag, element) for element in segment.elements],
    }


class EdifactNormalizer(Normalizer, register=True):
    """Normalize a parsed UN/EDIFACT interchange into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, EdifactDocument):
            raise ValueError(
                "EDIFACT source must be an EdifactDocument (see app.edifact_parser.parse_edifact)"
            )

        interchange = source.interchange
        group, message = canonical_message(source)
        namespace = f"EDIFACT-{message.message_type}"
        message_type, segment_types = message_record_types(
            message.message_type, message.segments, namespace=namespace
        )
        siblings = group.messages if group is not None else interchange.messages
        delimiters = interchange.delimiters

        title = f"EDIFACT {message.message_type}"
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=title, namespace=namespace),
            title=title,
            types=[message_type, *segment_types],
            raw={"edifact": source.raw} if include_raw else None,
            extras={
                # FMT-6.5: the dialect profile (EANCOM, ODETTE/VDA or plain UN/EDIFACT) and the
                # evidence it was recognised on — lifted into the revision's provenance.
                PROFILE_EXTRAS_KEY: edifact_profile(source).extras(),
                "edifact_message_type": message.message_type,
                "edifact_directory": message.directory,
                "edifact_envelope": {
                    "syntax_identifier": interchange.syntax_identifier,
                    "syntax_version": interchange.syntax_version,
                    "sender_id": interchange.sender_id,
                    "sender_qualifier": interchange.sender_qualifier,
                    "recipient_id": interchange.recipient_id,
                    "recipient_qualifier": interchange.recipient_qualifier,
                    "interchange_control_reference": interchange.control_reference,
                    "group_id": group.group_id if group is not None else None,
                    "group_reference": group.reference if group is not None else None,
                    "message_reference": message.reference,
                    "controlling_agency": message.agency,
                    "association_code": message.association or None,
                    "component_separator": delimiters.component,
                    "element_separator": delimiters.element,
                    "decimal_mark": delimiters.decimal,
                    "release_character": delimiters.release,
                    "repetition_separator": delimiters.repetition,
                    "segment_terminator": delimiters.segment,
                    "service_string_advice": delimiters.declared,
                },
                "edifact_messages": [
                    {
                        "message_type": item.message_type,
                        "reference": item.reference,
                        "directory": item.directory,
                        "segments": [segment_template(segment) for segment in item.segments],
                    }
                    for item in siblings
                ],
            },
        )
        return normalize_ordering(api)
