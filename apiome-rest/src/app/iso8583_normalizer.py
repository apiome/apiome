"""ISO 8583 → canonical model normalizer — MFI-22.6 / MFI-20.6.

Maps a parsed :class:`~app.iso8583_parser.Iso8583Document` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA`: one record type for the message, whose
fields are the data elements numbered by their **data element number** (the wire identity ISO
8583 pairs fields by), and one record type per data element. The message's definition is recorded
beside the model (MFI-20.6): the decoded MTI (``extras["iso8583_mti_decoded"]``) and the primary
and secondary bitmaps the elements present imply (``extras["iso8583_bitmap"]``), from
:mod:`app.iso8583_message_type`.
"""

from __future__ import annotations

from typing import Any, Optional

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Type,
    TypeKind,
    TypeRef,
)
from .iso8583_message_type import bitmaps_for, decode_mti
from .iso8583_parser import Iso8583DataElement, Iso8583Document, data_element_template
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["Iso8583Normalizer"]

_FORMAT_KEY = "iso8583"


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _field_name(number: str) -> str:
    return f"DE{number}"


def _canonical_type_for_element(
    element: Iso8583DataElement,
    *,
    namespace: Optional[str],
) -> Type:
    type_key = _type_key(_field_name(element.number), namespace)
    return Type(
        key=type_key,
        name=_field_name(element.number),
        kind=TypeKind.RECORD,
        description=element.name,
        fields=(
            CanonicalField(
                key=Keys.field(type_key, "value"),
                name="value",
                type=TypeRef(name="string", nullable=False),
                field_number=1,
                default=element.value,
            ),
        ),
        extras={
            "iso8583_de_number": element.number,
            "iso8583_de_name": element.name,
            "iso8583_de_type": element.type_expr,
            "iso8583_de_length": element.length,
        },
    )


class Iso8583Normalizer(Normalizer, register=True):
    """Normalize a parsed ISO 8583 document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, Iso8583Document):
            raise ValueError(
                "ISO 8583 source must be an Iso8583Document (see app.iso8583_parser.parse_iso8583)"
            )

        namespace = source.mti
        message_name = f"Message{source.mti}"
        message_key = _type_key(message_name, namespace)
        fields = tuple(
            CanonicalField(
                key=Keys.field(message_key, _field_name(element.number)),
                name=_field_name(element.number),
                type=TypeRef(name="string", nullable=False),
                # The data element number is the field's wire identity (MFI-20.6); a number
                # that is not numeric keeps its position.
                field_number=int(element.number) if element.number.isdigit() else index,
                description=element.name,
                default=element.value,
                extras={
                    "iso8583_de_number": element.number,
                    "iso8583_de_name": element.name,
                    "iso8583_de_type": element.type_expr,
                    "iso8583_de_length": element.length,
                },
            )
            for index, element in enumerate(source.data_elements, start=1)
        )
        message_type = Type(
            key=message_key,
            name=message_name,
            kind=TypeKind.RECORD,
            description=source.name,
            fields=fields,
            extras={
                "iso8583_kind": "message",
                "iso8583_mti": source.mti,
                "iso8583_bitmap": bitmaps_for(element.number for element in source.data_elements),
            },
        )
        element_types = [
            _canonical_type_for_element(element, namespace=namespace)
            for element in source.data_elements
        ]
        title = source.name or f"ISO 8583 MTI {source.mti}"
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=title, namespace=namespace),
            title=title,
            types=[message_type, *element_types],
            raw={"iso8583": source.raw} if include_raw else None,
            extras={
                "iso8583_mti": source.mti,
                "iso8583_mti_decoded": decode_mti(source.mti),
                "iso8583_bitmap": bitmaps_for(element.number for element in source.data_elements),
                "iso8583_name": source.name,
                "iso8583_data_elements": [
                    data_element_template(element) for element in source.data_elements
                ],
            },
        )
        return normalize_ordering(api)
