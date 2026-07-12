"""HL7 v2.x → canonical model normalizer — MFI-22.4.

Maps a parsed :class:`~app.hl7v2_parser.Hl7V2Document` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA`.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Type,
    TypeKind,
    TypeRef,
)
from .hl7v2_parser import Hl7Message, Hl7Segment, Hl7V2Document
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["Hl7V2Normalizer"]

_FORMAT_KEY = "hl7v2"


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _namespace_from_message_type(message_type: Optional[str]) -> str:
    if not message_type:
        return "HL7"
    return message_type.replace("^", "-").replace(" ", "-")


def _field_name(segment_id: str, field_index: int) -> str:
    return f"{segment_id}-{field_index:02d}"


def _segment_record_type(segment: Hl7Segment, *, namespace: Optional[str]) -> Type:
    type_key = _type_key(segment.id, namespace)
    fields = tuple(
        CanonicalField(
            key=Keys.field(type_key, _field_name(segment.id, field.index)),
            name=_field_name(segment.id, field.index),
            type=TypeRef(name="string", nullable=False),
            field_number=index,
            default=field.value or None,
            extras={"hl7v2_field_index": field.index},
        )
        for index, field in enumerate(segment.fields, start=1)
    )
    return Type(
        key=type_key,
        name=segment.id,
        kind=TypeKind.RECORD,
        fields=fields,
        extras={"hl7v2_kind": "segment"},
    )


def _segment_template(segment: Hl7Segment) -> Dict[str, object]:
    return {
        "id": segment.id,
        "fields": [
            {"index": field.index, "value": field.value}
            for field in segment.fields
        ],
    }


def _canonical_message_type(
    message: Hl7Message,
    *,
    namespace: Optional[str],
) -> tuple[Type, List[Type]]:
    non_msh_segments = [segment for segment in message.segments if segment.id != "MSH"]
    counts = Counter(segment.id for segment in non_msh_segments)
    repeating_ids = {seg_id for seg_id, count in counts.items() if count > 1}
    prototypes: Dict[str, Hl7Segment] = {}
    for segment in non_msh_segments:
        prototypes.setdefault(segment.id, segment)

    segment_types: List[Type] = []
    fields: List[CanonicalField] = []
    field_number = 1
    seen_single_segments: set[str] = set()
    seen_repeating_segments: set[str] = set()
    message_type_name = f"Message{_namespace_from_message_type(message.message_type).replace('-', '')}"

    for segment in non_msh_segments:
        if segment.id in repeating_ids:
            if segment.id in seen_repeating_segments:
                continue
            seen_repeating_segments.add(segment.id)
            segment_types.append(_segment_record_type(prototypes[segment.id], namespace=namespace))
            fields.append(
                CanonicalField(
                    key=Keys.field(_type_key(message_type_name, namespace), segment.id),
                    name=segment.id,
                    type=TypeRef(
                        item=TypeRef(name=_type_key(segment.id, namespace), nullable=False),
                        nullable=False,
                    ),
                    field_number=field_number,
                )
            )
            field_number += 1
            continue
        if segment.id in seen_single_segments:
            continue
        seen_single_segments.add(segment.id)
        for field in segment.fields:
            fields.append(
                CanonicalField(
                    key=Keys.field(
                        _type_key(message_type_name, namespace),
                        _field_name(segment.id, field.index),
                    ),
                    name=_field_name(segment.id, field.index),
                    type=TypeRef(name="string", nullable=False),
                    field_number=field_number,
                    default=field.value or None,
                    extras={"hl7v2_segment": segment.id, "hl7v2_field_index": field.index},
                )
            )
            field_number += 1

    message_key = _type_key(message_type_name, namespace)
    message_record = Type(
        key=message_key,
        name=message_type_name,
        kind=TypeKind.RECORD,
        fields=tuple(fields),
        extras={"hl7v2_kind": "message"},
    )
    msh_type = _segment_record_type(message.segments[0], namespace=namespace)
    return message_record, [msh_type, *segment_types]


class Hl7V2Normalizer(Normalizer, register=True):
    """Normalize a parsed HL7 v2 document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, Hl7V2Document):
            raise ValueError(
                "HL7 v2 source must be an Hl7V2Document (see app.hl7v2_parser.parse_hl7v2)"
            )

        message = source.message
        namespace = _namespace_from_message_type(message.message_type)
        message_type, segment_types = _canonical_message_type(message, namespace=namespace)
        types: List[Type] = [message_type, *segment_types]

        title = message.message_type or "HL7 v2 Message"
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=title, namespace=namespace),
            title=title,
            types=types,
            raw={"hl7v2": source.raw} if include_raw else None,
            extras={
                "hl7v2_message_type": message.message_type,
                "hl7v2_version": message.version_id,
                "hl7v2_control_id": message.message_control_id,
                "hl7v2_envelope": {
                    "field_separator": message.field_separator,
                    "encoding_characters": message.encoding_characters,
                    "sending_application": message.sending_application,
                    "sending_facility": message.sending_facility,
                    "receiving_application": message.receiving_application,
                    "receiving_facility": message.receiving_facility,
                    "processing_id": message.processing_id,
                },
                "hl7v2_segments": [_segment_template(segment) for segment in message.segments],
            },
        )
        return normalize_ordering(api)
