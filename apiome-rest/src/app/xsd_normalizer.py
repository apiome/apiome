"""XSD → canonical model normalizer.

Maps a parsed :class:`~app.xsd_parser.XsdDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

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
from .xsd_parser import XsdComplexType, XsdDocument, XsdField, XsdSimpleType

__all__ = ["XsdNormalizer"]

_FORMAT_KEY = "xsd"

_XSD_BASE_TO_CANONICAL: Dict[str, str] = {
    "string": "string",
    "boolean": "bool",
    "double": "double",
    "float": "float",
    "decimal": "double",
    "int": "i32",
    "integer": "i32",
    "positiveinteger": "i32",
    "nonnegativeinteger": "i32",
    "long": "i64",
    "short": "i16",
    "byte": "int8",
    "unsignedint": "uint32",
    "unsignedlong": "uint64",
    "unsignedshort": "uint16",
    "unsignedbyte": "uint8",
    "date": "string",
    "datetime": "string",
    "time": "string",
    "anytype": "string",
}


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _type_ref_from_expr(
    type_expr: str,
    *,
    namespace: Optional[str],
    type_names: frozenset[str],
    max_occurs: Optional[str] = None,
) -> TypeRef:
    mapped = _XSD_BASE_TO_CANONICAL.get(type_expr.lower())
    inner = (
        TypeRef(name=mapped, nullable=False)
        if mapped
        else TypeRef(
            name=_type_key(type_expr, namespace) if type_expr in type_names else type_expr,
            nullable=False,
        )
    )
    if max_occurs == "unbounded" or (max_occurs and max_occurs.isdigit() and int(max_occurs) > 1):
        return TypeRef(item=inner, nullable=False)
    return inner


def _field_constraints(field: XsdField) -> Optional[Constraints]:
    if field.type_expr.lower() == "date":
        return Constraints(format="date")
    if field.type_expr.lower() in {"datetime", "datetimestamp"}:
        return Constraints(format="date-time")
    return None


def _canonical_field(
    field: XsdField,
    *,
    type_key: str,
    namespace: Optional[str],
    type_names: frozenset[str],
    field_number: int,
) -> CanonicalField:
    return CanonicalField(
        key=Keys.field(type_key, field.name),
        name=field.name,
        type=_type_ref_from_expr(
            field.type_expr,
            namespace=namespace,
            type_names=type_names,
            max_occurs=field.max_occurs,
        ),
        field_number=field_number,
        constraints=_field_constraints(field),
        extras={
            "xsd_type": field.type_expr,
            "xsd_kind": field.kind,
            **({"xsd_max_occurs": field.max_occurs} if field.max_occurs else {}),
            **({"xsd_min_occurs": field.min_occurs} if field.min_occurs else {}),
        },
    )


def _canonical_complex_type(
    complex_type: XsdComplexType,
    *,
    namespace: Optional[str],
    type_names: frozenset[str],
) -> Type:
    type_key = _type_key(complex_type.name, namespace)
    fields = [
        _canonical_field(
            field,
            type_key=type_key,
            namespace=namespace,
            type_names=type_names,
            field_number=index + 1,
        )
        for index, field in enumerate(complex_type.fields)
    ]
    return Type(
        key=type_key,
        name=complex_type.name,
        kind=TypeKind.RECORD,
        namespace=namespace,
        fields=fields,
        extras={"xsd_kind": "complexType"},
    )


def _canonical_simple_type(simple_type: XsdSimpleType, *, namespace: Optional[str]) -> Type:
    type_key = _type_key(simple_type.name, namespace)
    if simple_type.enum_values:
        return Type(
            key=type_key,
            name=simple_type.name,
            kind=TypeKind.ENUM,
            namespace=namespace,
            enum_values=[
                EnumValue(key=Keys.enum_value(type_key, value), name=value, value=index)
                for index, value in enumerate(simple_type.enum_values)
            ],
            extras={
                "xsd_kind": "simpleType",
                "xsd_base": simple_type.base,
            },
        )
    mapped = _XSD_BASE_TO_CANONICAL.get((simple_type.base or "string").lower(), "string")
    return Type(
        key=type_key,
        name=simple_type.name,
        kind=TypeKind.SCALAR,
        namespace=namespace,
        extras={
            "xsd_kind": "simpleType",
            "xsd_base": simple_type.base,
            "xsd_type": mapped,
        },
    )


class XsdNormalizer(Normalizer, register=True):
    """Normalize a parsed XSD document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, XsdDocument):
            raise ValueError("XSD source must be an XsdDocument (see app.xsd_parser.parse_xsd)")

        namespace = source.target_namespace
        type_names = frozenset(
            {t.name for t in source.complex_types}
            | {t.name for t in source.simple_types}
        )
        types: List[Type] = [
            _canonical_complex_type(complex_type, namespace=namespace, type_names=type_names)
            for complex_type in source.complex_types
        ]
        types.extend(
            _canonical_simple_type(simple_type, namespace=namespace)
            for simple_type in source.simple_types
        )

        title = source.root_element or (types[0].name if types else "schema")
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=title, namespace=namespace),
            title=title,
            types=types,
            raw={"xsd": source.raw} if include_raw else None,
            extras={
                "xsd_target_namespace": namespace,
                "xsd_root_element": source.root_element,
                "xsd_elements": [
                    {"name": element.name, "type": element.type_expr}
                    for element in source.elements
                ],
            },
        )
        return normalize_ordering(api)
