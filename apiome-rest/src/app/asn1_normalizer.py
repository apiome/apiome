"""ASN.1 → canonical model normalizer — MFI-21.5.

Maps a parsed :class:`~app.asn1_parser.Asn1Document` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .asn1_parser import Asn1Document, Asn1Member, Asn1TypeDef
from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    EnumValue,
    Type,
    TypeKind,
    TypeRef,
)
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["Asn1Normalizer"]

_FORMAT_KEY = "asn1"

_ASN1_BASE_TO_CANONICAL: Dict[str, str] = {
    "INTEGER": "integer",
    "BOOLEAN": "bool",
    "NULL": "null",
    "REAL": "double",
    "UTF8String": "string",
    "PrintableString": "string",
    "IA5String": "string",
    "VisibleString": "string",
    "GeneralizedTime": "string",
    "UTCTime": "string",
    "OCTET STRING": "bytes",
    "BIT STRING": "bytes",
}


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _qualified_name(name: str, namespace: Optional[str]) -> str:
    return f"{namespace}.{name}" if namespace else name


def _resolve_type_name(name: str, *, namespace: Optional[str], known: frozenset[str]) -> str:
    if name in known:
        return _type_key(name, namespace)
    if "." in name:
        return name
    qualified = _qualified_name(name, namespace)
    if qualified in known:
        return qualified
    return _type_key(name, namespace)


def _constraints_for_scalar(type_name: str) -> Optional[Constraints]:
    if type_name in {"GeneralizedTime", "UTCTime"}:
        return Constraints(format="date-time")
    return None


def _type_ref_from_member(
    member: Asn1Member,
    *,
    namespace: Optional[str],
    known_types: frozenset[str],
    synthetic_enums: Dict[str, Type],
    parent_type_name: Optional[str] = None,
) -> TypeRef:
    if member.enum_values:
        enum_name = (
            f"{parent_type_name}{member.name[0].upper()}{member.name[1:]}"
            if parent_type_name
            else f"{member.name.capitalize()}Enum"
        )
        enum_key = _type_key(enum_name, namespace)
        synthetic_enums.setdefault(
            enum_name,
            Type(
                key=enum_key,
                name=enum_name,
                kind=TypeKind.ENUM,
                enum_values=tuple(
                    EnumValue(
                        key=Keys.enum_value(enum_key, value.name),
                        name=value.name,
                        value=value.value,
                    )
                    for value in member.enum_values
                ),
            ),
        )
        inner = TypeRef(name=_type_key(enum_name, namespace), nullable=False)
    elif member.element_type:
        inner = TypeRef(
            name=_resolve_type_name(member.element_type, namespace=namespace, known=known_types),
            nullable=False,
        )
        return TypeRef(item=inner, nullable=member.optional)
    elif member.type_name.startswith("SEQUENCE OF "):
        element_name = member.type_name.removeprefix("SEQUENCE OF ").strip()
        mapped = _ASN1_BASE_TO_CANONICAL.get(element_name)
        inner_name = mapped or _resolve_type_name(element_name, namespace=namespace, known=known_types)
        return TypeRef(item=TypeRef(name=inner_name, nullable=False), nullable=member.optional)
    else:
        mapped = _ASN1_BASE_TO_CANONICAL.get(member.type_name)
        inner = TypeRef(
            name=mapped or _resolve_type_name(member.type_name, namespace=namespace, known=known_types),
            nullable=False,
        )
    return TypeRef(name=inner.name, item=inner.item, nullable=member.optional)


def _canonical_field(
    member: Asn1Member,
    *,
    parent_key: str,
    parent_type_name: str,
    namespace: Optional[str],
    known_types: frozenset[str],
    synthetic_enums: Dict[str, Type],
    field_number: int,
) -> CanonicalField:
    return CanonicalField(
        key=Keys.field(parent_key, member.name),
        name=member.name,
        type=_type_ref_from_member(
            member,
            namespace=namespace,
            known_types=known_types,
            synthetic_enums=synthetic_enums,
            parent_type_name=parent_type_name,
        ),
        default=member.default,
        field_number=field_number,
        constraints=_constraints_for_scalar(member.type_name),
    )


def _canonical_enum(type_def: Asn1TypeDef, *, namespace: Optional[str]) -> Type:
    type_key = _type_key(type_def.name, namespace)
    return Type(
        key=type_key,
        name=type_def.name,
        kind=TypeKind.ENUM,
        enum_values=tuple(
            EnumValue(
                key=Keys.enum_value(type_key, value.name),
                name=value.name,
                value=value.value,
            )
            for value in type_def.enum_values
        ),
    )


def _canonical_union(
    type_def: Asn1TypeDef,
    *,
    namespace: Optional[str],
    known_types: frozenset[str],
    synthetic_enums: Dict[str, Type],
) -> Type:
    members: List[str] = []
    choice_members: List[Dict[str, str]] = []
    for member in type_def.members:
        ref = _type_ref_from_member(
            member,
            namespace=namespace,
            known_types=known_types,
            synthetic_enums=synthetic_enums,
            parent_type_name=type_def.name,
        )
        members.append(ref.name)
        choice_members.append({"name": member.name, "type": ref.name})
    return Type(
        key=_type_key(type_def.name, namespace),
        name=type_def.name,
        kind=TypeKind.UNION,
        union_members=tuple(members),
        extras={"asn1_choice_members": choice_members},
    )


def _canonical_record(
    type_def: Asn1TypeDef,
    *,
    namespace: Optional[str],
    known_types: frozenset[str],
    synthetic_enums: Dict[str, Type],
) -> Type:
    type_key = _type_key(type_def.name, namespace)
    fields = tuple(
        _canonical_field(
            member,
            parent_key=type_key,
            parent_type_name=type_def.name,
            namespace=namespace,
            known_types=known_types,
            synthetic_enums=synthetic_enums,
            field_number=index,
        )
        for index, member in enumerate(type_def.members, start=1)
    )
    return Type(key=type_key, name=type_def.name, kind=TypeKind.RECORD, fields=fields)


def _collect_types(
    source: Asn1Document,
    *,
    namespace: Optional[str],
) -> List[Type]:
    known = frozenset(type_def.name for type_def in source.module.types)
    synthetic_enums: Dict[str, Type] = {}
    types: List[Type] = []

    for type_def in source.module.types:
        if type_def.kind == "ENUMERATED":
            types.append(_canonical_enum(type_def, namespace=namespace))
        elif type_def.kind == "CHOICE":
            types.append(
                _canonical_union(
                    type_def,
                    namespace=namespace,
                    known_types=known,
                    synthetic_enums=synthetic_enums,
                )
            )
        elif type_def.kind in {"SEQUENCE", "SET"}:
            types.append(
                _canonical_record(
                    type_def,
                    namespace=namespace,
                    known_types=known,
                    synthetic_enums=synthetic_enums,
                )
            )
        elif type_def.kind == "SEQUENCE OF" and type_def.members:
            member = type_def.members[0]
            element = member.element_type or member.type_name.removeprefix("SEQUENCE OF ").strip()
            mapped = _ASN1_BASE_TO_CANONICAL.get(element)
            item_name = mapped or _resolve_type_name(element, namespace=namespace, known=known)
            types.append(
                Type(
                    key=_type_key(type_def.name, namespace),
                    name=type_def.name,
                    kind=TypeKind.ALIAS,
                    alias_of=TypeRef(item=TypeRef(name=item_name), nullable=False),
                )
            )
        else:
            mapped = _ASN1_BASE_TO_CANONICAL.get(type_def.kind)
            if mapped:
                types.append(
                    Type(
                        key=_type_key(type_def.name, namespace),
                        name=type_def.name,
                        kind=TypeKind.SCALAR,
                        scalar=mapped,
                        constraints=_constraints_for_scalar(type_def.kind),
                    )
                )

    types.extend(synthetic_enums.values())
    return types


class Asn1Normalizer(Normalizer, register=True):
    """Normalize a parsed ASN.1 module into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, Asn1Document):
            raise ValueError("ASN.1 source must be an Asn1Document (see app.asn1_parser.parse_asn1)")

        namespace = source.module.name
        types = _collect_types(source, namespace=namespace)
        title = types[0].name if types else source.module.name
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=source.module.name, namespace=namespace),
            title=title,
            types=types,
            raw={"asn1": source.raw} if include_raw else None,
            extras={
                "asn1_module_name": source.module.name,
                "asn1_tags": source.module.tags,
            },
        )
        return normalize_ordering(api)
