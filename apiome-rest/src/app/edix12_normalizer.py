"""EDI X12 → canonical model normalizer — MFI-20.5.

Maps a parsed :class:`~app.edix12_parser.EdiX12Document` into a
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
from .edix12_parser import EdiX12Document, X12Segment, X12TransactionSet
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["EdiX12Normalizer"]

_FORMAT_KEY = "edix12"


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _segment_record_type(segment: X12Segment, *, namespace: Optional[str]) -> Type:
    type_key = _type_key(segment.id, namespace)
    fields = tuple(
        CanonicalField(
            key=Keys.field(type_key, element.ref),
            name=element.ref,
            type=TypeRef(name="string", nullable=False),
            field_number=index,
            default=element.value or None,
        )
        for index, element in enumerate(segment.elements, start=1)
    )
    return Type(key=type_key, name=segment.id, kind=TypeKind.RECORD, fields=fields)


def _segment_template(segment: X12Segment) -> Dict[str, object]:
    return {
        "id": segment.id,
        "elements": [
            {"ref": element.ref, "position": element.position, "value": element.value}
            for element in segment.elements
        ],
    }


def _transaction_templates(transaction: X12TransactionSet) -> List[Dict[str, object]]:
    return [_segment_template(segment) for segment in transaction.segments]


def _canonical_transaction_type(
    transaction: X12TransactionSet,
    *,
    namespace: Optional[str],
) -> tuple[Type, List[Type]]:
    counts = Counter(segment.id for segment in transaction.segments)
    repeating_ids = {seg_id for seg_id, count in counts.items() if count > 1}
    prototypes: Dict[str, X12Segment] = {}
    for segment in transaction.segments:
        prototypes.setdefault(segment.id, segment)

    segment_types: List[Type] = []
    fields: List[CanonicalField] = []
    field_number = 1
    seen_single_segments: set[str] = set()
    seen_repeating_segments: set[str] = set()

    for segment in transaction.segments:
        if segment.id in repeating_ids:
            if segment.id in seen_repeating_segments:
                continue
            seen_repeating_segments.add(segment.id)
            segment_types.append(_segment_record_type(prototypes[segment.id], namespace=namespace))
            fields.append(
                CanonicalField(
                    key=Keys.field(
                        _type_key(f"TransactionSet{transaction.set_id}", namespace),
                        segment.id,
                    ),
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
        for element in segment.elements:
            fields.append(
                CanonicalField(
                    key=Keys.field(
                        _type_key(f"TransactionSet{transaction.set_id}", namespace),
                        element.ref,
                    ),
                    name=element.ref,
                    type=TypeRef(name="string", nullable=False),
                    field_number=field_number,
                    default=element.value or None,
                )
            )
            field_number += 1

    type_name = f"TransactionSet{transaction.set_id}"
    type_key = _type_key(type_name, namespace)
    transaction_type = Type(
        key=type_key,
        name=type_name,
        kind=TypeKind.RECORD,
        fields=tuple(fields),
    )
    return transaction_type, segment_types


class EdiX12Normalizer(Normalizer, register=True):
    """Normalize a parsed EDI X12 interchange into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, EdiX12Document):
            raise ValueError(
                "EDI X12 source must be an EdiX12Document (see app.edix12_parser.parse_edix12)"
            )

        group = source.interchange.functional_groups[0]
        transaction = group.transaction_sets[0]
        namespace = f"X12-{transaction.set_id}"
        transaction_type, segment_types = _canonical_transaction_type(
            transaction,
            namespace=namespace,
        )
        types: List[Type] = [transaction_type, *segment_types]

        title = f"X12 {transaction.set_id}"
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=title, namespace=namespace),
            title=title,
            types=types,
            raw={"edix12": source.raw} if include_raw else None,
            extras={
                "x12_set_id": transaction.set_id,
                "x12_version": group.version,
                "x12_envelope": {
                    "sender_id": source.interchange.sender_id,
                    "receiver_id": source.interchange.receiver_id,
                    "interchange_version": source.interchange.version,
                    "interchange_control_number": source.interchange.control_number,
                    "functional_id": group.functional_id,
                    "group_sender": group.sender,
                    "group_receiver": group.receiver,
                    "group_control_number": group.control_number,
                    "element_separator": source.interchange.element_separator,
                    "segment_terminator": source.interchange.segment_terminator,
                },
                "x12_transactions": [
                    {
                        "set_id": item.set_id,
                        "control_number": item.control_number,
                        "segments": _transaction_templates(item),
                    }
                    for item in group.transaction_sets
                ],
            },
        )
        return normalize_ordering(api)
