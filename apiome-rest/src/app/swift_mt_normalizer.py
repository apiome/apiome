"""SWIFT MT → canonical model normalizer — FMT-6.3 (#5447).

Maps a parsed :class:`~app.swift_mt_parser.SwiftMtFile` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA`. Like the other financial-messaging readers, the
model is derived from the **first** message; the analysis keeps the rest.

* The message (``MT103``, ``MT202COV``) is the root record type.
* Each field **as written with its option** (``32A``, ``50K``, ``59F``) is a record type of its own,
  ``Field50K``, holding the field's components — so ``50K`` (name and address) and ``50F``
  (structured lines) stay different shapes, and the option letter is never flattened away. A field
  that repeats (``71F``) is a list.
* Code words (``/INV/``, ``/OCMT/``) are ``CodeWord`` records with their qualifier; option-F lines
  are ``NumberedLine`` records; name/address and free narrative lines are string lists.
* In MT940/942 each ``:61:`` statement line and the ``:86:`` that follows it form one repeated
  ``StatementLine``; an MT202 COV's sequence B is a nested record.
* Payload values are never defaults. Header blocks are recorded in ``swift_headers`` as structure, and
  the documented MX counterpart in ``swift_mx_correspondence`` — as a note, with its disclaimer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
from .normalizer import Keys, Normalizer, normalize_ordering
from .swift_mt_fields import MX_CORRESPONDENCE, MX_CORRESPONDENCE_DISCLAIMER, field_name
from .swift_mt_parser import SwiftHeaderBlock, SwiftMtField, SwiftMtFile, SwiftMtMessage

__all__ = ["SwiftMtNormalizer", "mx_correspondence", "statement_groups"]

_FORMAT_KEY = "swift-mt"


def mx_correspondence(message: SwiftMtMessage) -> Optional[Dict[str, Any]]:
    """The documented MX counterpart of ``message`` as a note, or ``None`` when none is listed.

    The note always carries ``verified: False`` and the disclaimer: it names a correspondence, it
    does not claim one was checked.
    """
    note = MX_CORRESPONDENCE.get(message.name)
    if note is None:
        return None
    return {
        "mt": note.mt,
        "mx": note.mx,
        "mxName": note.mx_name,
        "basis": note.basis,
        "verified": False,
        "disclaimer": MX_CORRESPONDENCE_DISCLAIMER,
    }


def statement_groups(fields: Sequence[SwiftMtField]) -> List[Any]:
    """Group a statement's ``:61:`` lines with the ``:86:`` that follows each.

    Returns:
        The fields in order, with each statement line replaced by a ``(61, 86 or None)`` tuple.
    """
    out: List[Any] = []
    index = 0
    while index < len(fields):
        item = fields[index]
        if item.tag == "61":
            following = fields[index + 1] if index + 1 < len(fields) else None
            info = following if following is not None and following.tag == "86" else None
            out.append((item, info))
            index += 2 if info is not None else 1
            continue
        out.append(item)
        index += 1
    return out


@dataclass
class _FieldShape:
    """Every occurrence of one field label, folded together."""

    tag: str
    option: Optional[str]
    components: Dict[str, None] = field(default_factory=dict)
    lines: bool = False
    numbered: bool = False
    code_words: bool = False


class _Builder:
    """Collects the record types of one message."""

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace
        self.shapes: Dict[str, _FieldShape] = {}
        self.extra_types: Dict[str, Type] = {}

    def key(self, name: str) -> str:
        return Keys.type(name, self.namespace)

    def observe(self, item: SwiftMtField) -> str:
        """Fold one field occurrence into its shape; return its type name."""
        shape = self.shapes.setdefault(item.label, _FieldShape(item.tag, item.option))
        for name, _ in item.reading.components:
            shape.components.setdefault(name)
        shape.lines = shape.lines or bool(item.reading.lines)
        shape.numbered = shape.numbered or bool(item.reading.numbered_lines)
        shape.code_words = shape.code_words or bool(item.reading.code_words)
        return f"Field{item.label}"

    def _helper(self, name: str, members: Tuple[str, ...]) -> str:
        key = self.key(name)
        if key not in self.extra_types:
            self.extra_types[key] = Type(
                key=key,
                name=name,
                kind=TypeKind.RECORD,
                fields=[
                    CanonicalField(
                        key=Keys.field(key, member),
                        name=member,
                        type=TypeRef(name="string"),
                        field_number=index,
                    )
                    for index, member in enumerate(members, start=1)
                ],
            )
        return key

    def field_types(self) -> List[Type]:
        """One record type per field label, from its folded shape."""
        types: List[Type] = []
        for label, shape in self.shapes.items():
            key = self.key(f"Field{label}")
            members: List[CanonicalField] = [
                CanonicalField(
                    key=Keys.field(key, name), name=name, type=TypeRef(name="string"), field_number=0
                )
                for name in shape.components
            ]
            if shape.lines:
                members.append(
                    CanonicalField(
                        key=Keys.field(key, "lines"),
                        name="lines",
                        type=TypeRef(item=TypeRef(name="string", nullable=False), nullable=False),
                        field_number=0,
                    )
                )
            for flag, member, helper, helper_fields in (
                (shape.numbered, "numberedLines", "NumberedLine", ("number", "text")),
                (shape.code_words, "codeWords", "CodeWord", ("code", "text")),
            ):
                if flag:
                    reference = TypeRef(name=self._helper(helper, helper_fields), nullable=False)
                    members.append(
                        CanonicalField(
                            key=Keys.field(key, member),
                            name=member,
                            type=TypeRef(item=reference, nullable=False),
                            field_number=0,
                        )
                    )
            for index, member in enumerate(members, start=1):
                member.field_number = index
            name = field_name(shape.tag, shape.option)
            option = f", option {shape.option}" if shape.option else ""
            types.append(
                Type(
                    key=key,
                    name=f"Field{label}",
                    kind=TypeKind.RECORD,
                    fields=members,
                    description=f"Field {shape.tag}{option}" + (f": {name}" if name else ""),
                )
            )
        return types

    def record(self, name: str, entries: Sequence[Any], description: Optional[str] = None) -> Type:
        """A record of fields (and statement-line groups), lists where a label repeats."""
        key = self.key(name)
        counts: Dict[str, int] = {}
        order: List[Tuple[str, str]] = []  # (field name, type key)
        for entry in entries:
            if isinstance(entry, tuple):
                line, info = entry
                group_key = self._statement_line(line, info)
                member = ("StatementLines", group_key)
            elif isinstance(entry, Type):
                member = ("Sequence" + entry.name.rsplit("Sequence", 1)[-1], entry.key)
            else:
                member = (entry.label, self.key(self.observe(entry)))
            if member[0] not in counts:
                order.append(member)
            counts[member[0]] = counts.get(member[0], 0) + 1
        fields = []
        for index, (member, type_key) in enumerate(order, start=1):
            reference = TypeRef(name=type_key, nullable=False)
            repeated = counts[member] > 1 or member == "StatementLines"
            fields.append(
                CanonicalField(
                    key=Keys.field(key, member),
                    name=member,
                    type=TypeRef(item=reference, nullable=False) if repeated else reference,
                    field_number=index,
                )
            )
        return Type(key=key, name=name, kind=TypeKind.RECORD, fields=fields, description=description)

    def _statement_line(self, line: SwiftMtField, info: Optional[SwiftMtField]) -> str:
        """The ``StatementLine`` record: the ``:61:`` and its ``:86:``."""
        key = self.key("StatementLine")
        members = [("61", self.key(self.observe(line)))]
        if info is not None:
            members.append(("86", self.key(self.observe(info))))
        existing = self.extra_types.get(key)
        names = {item.name for item in existing.fields} if existing else set()
        fields = list(existing.fields) if existing else []
        for member, type_key in members:
            if member not in names:
                fields.append(
                    CanonicalField(
                        key=Keys.field(key, member),
                        name=member,
                        type=TypeRef(name=type_key, nullable=False),
                        field_number=len(fields) + 1,
                    )
                )
        self.extra_types[key] = Type(
            key=key,
            name="StatementLine",
            kind=TypeKind.RECORD,
            fields=fields,
            description="A statement line (field 61) and the information to account owner (field 86) "
            "that follows it",
        )
        return key


def _header_values(block: Optional[SwiftHeaderBlock]) -> Optional[Dict[str, str]]:
    return {key: value for key, value in block.values} if block is not None else None


def _sequence_description(message: SwiftMtMessage, name: str) -> str:
    if message.name == "MT202COV" and name == "B":
        return "Sequence B — underlying customer credit transfer details"
    return f"Sequence {name}"


class SwiftMtNormalizer(Normalizer, register=True):
    """Normalize a parsed SWIFT MT file into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, SwiftMtFile):
            raise ValueError(
                "SWIFT MT source must be a SwiftMtFile (see app.swift_mt_parser.parse_swift_mt)"
            )
        message = source.messages[0]
        namespace = f"SWIFT-{message.name}"
        builder = _Builder(namespace)
        statement = message.message_type in ("940", "942")

        first = message.sequences[0]
        entries: List[Any] = list(statement_groups(first.fields) if statement else first.fields)
        nested: List[Type] = []
        for sequence in message.sequences[1:]:
            nested.append(
                builder.record(
                    f"{message.name}Sequence{sequence.name}",
                    sequence.fields,
                    _sequence_description(message, sequence.name),
                )
            )
        entries.extend(nested)
        root = builder.record(message.name, entries, f"SWIFT {message.name} message")
        types: List[Type] = [root, *nested, *builder.field_types(), *builder.extra_types.values()]

        title = f"SWIFT {message.name}"
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=title, namespace=namespace),
            title=title,
            types=types,
            raw={"swift-mt": source.raw} if include_raw else None,
            extras={
                "swift_message_type": message.name,
                "swift_headers": {
                    "basic": _header_values(message.basic),
                    "application": _header_values(message.application),
                    "user": _header_values(message.user),
                    "trailer": _header_values(message.trailer),
                },
                "swift_mx_correspondence": mx_correspondence(message),
            },
        )
        return normalize_ordering(api)
