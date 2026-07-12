"""FIX → canonical model normalizer — MFI-22.8.

Maps a parsed :class:`~app.fix_parser.FixDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA`.
"""

from __future__ import annotations

from typing import Any, List, Optional

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Type,
    TypeKind,
    TypeRef,
)
from .fix_parser import FixDocument, field_template, msg_type_name, tag_name
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["FixNormalizer"]

_FORMAT_KEY = "fix"


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _field_key(tag: str) -> str:
    return f"Tag{tag}"


class FixNormalizer(Normalizer, register=True):
    """Normalize a parsed FIX document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, FixDocument):
            raise ValueError("FIX source must be a FixDocument (see app.fix_parser.parse_fix)")

        message = source.message
        namespace = message.begin_string
        message_label = msg_type_name(message.msg_type) or "FIX Message"
        message_name = (
            f"Message{message.msg_type}"
            if message.msg_type
            else message_label.replace(" ", "")
        )
        message_key = _type_key(message_name, namespace)
        fields = tuple(
            CanonicalField(
                key=Keys.field(message_key, _field_key(field.tag)),
                name=_field_key(field.tag),
                type=TypeRef(name="string", nullable=False),
                field_number=index,
                description=tag_name(field.tag),
                default=field.value,
                extras={"fix_tag": field.tag, "fix_name": tag_name(field.tag)},
            )
            for index, field in enumerate(message.fields, start=1)
        )
        message_type = Type(
            key=message_key,
            name=message_name,
            kind=TypeKind.RECORD,
            description=message_label,
            fields=fields,
            extras={
                "fix_kind": "message",
                "fix_msg_type": message.msg_type,
                "fix_msg_type_name": message_label,
            },
        )
        title = f"{message_label} ({message.begin_string})" if message.begin_string else message_label
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=title, namespace=namespace),
            title=title,
            types=[message_type],
            raw={"fix": source.raw} if include_raw else None,
            extras={
                "fix_begin_string": message.begin_string,
                "fix_msg_type": message.msg_type,
                "fix_msg_type_name": message_label,
                "fix_sender_comp_id": message.sender_comp_id,
                "fix_target_comp_id": message.target_comp_id,
                "fix_delimiter": source.delimiter,
                "fix_fields": [field_template(field) for field in message.fields],
            },
        )
        return normalize_ordering(api)
