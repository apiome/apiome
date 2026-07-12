"""COBOL copybook → canonical model normalizer — MFI-22.7.

Maps a parsed :class:`~app.cobolcopybook_parser.CobolCopybookDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA`.
"""

from __future__ import annotations

import re
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
from .cobolcopybook_parser import CobolCopybookDocument, CobolField, field_template
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["CobolCopybookNormalizer"]

_FORMAT_KEY = "cobolcopybook"


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _pic_to_type_ref(picture: Optional[str]) -> TypeRef:
    if not picture:
        return TypeRef(name="string", nullable=False)
    normalized = picture.upper().replace(" ", "")
    if "X" in normalized:
        return TypeRef(name="string", nullable=False)
    if "V" in normalized or "COMP-3" in normalized:
        return TypeRef(name="double", nullable=False)
    if normalized.startswith("S9") or normalized.startswith("9"):
        return TypeRef(name="i64", nullable=False)
    return TypeRef(name="string", nullable=False)


def _field_type_ref(field: CobolField, *, namespace: Optional[str]) -> TypeRef:
    if field.children:
        inner = TypeRef(name=_type_key(field.name, namespace), nullable=False)
    else:
        inner = _pic_to_type_ref(field.picture)
    if field.occurs_max is not None:
        return TypeRef(item=inner, nullable=False)
    return inner


def _record_type(
    field: CobolField,
    *,
    namespace: Optional[str],
    created: Dict[str, Type],
) -> Type:
    type_key = _type_key(field.name, namespace)
    if type_key in created:
        return created[type_key]

    fields: List[CanonicalField] = []
    field_number = 1
    for child in field.children:
        child_type = _record_type(child, namespace=namespace, created=created) if child.children else None
        type_ref = _field_type_ref(child, namespace=namespace)
        if child_type is not None and child_type.key not in created:
            created[child_type.key] = child_type
        fields.append(
            CanonicalField(
                key=Keys.field(type_key, child.name),
                name=child.name,
                type=type_ref,
                field_number=field_number,
                description=child.picture,
                extras={
                    "cobol_level": child.level,
                    "cobol_picture": child.picture,
                    "cobol_usage": child.usage,
                    "cobol_occurs_min": child.occurs_min,
                    "cobol_occurs_max": child.occurs_max,
                    "cobol_depending_on": child.depending_on,
                    "cobol_conditions": [
                        {"name": condition.name, "value": condition.value}
                        for condition in child.conditions
                    ],
                },
            )
        )
        field_number += 1

    record = Type(
        key=type_key,
        name=field.name,
        kind=TypeKind.RECORD,
        fields=tuple(fields),
        extras={"cobol_level": field.level, "cobol_kind": "group"},
    )
    created[type_key] = record
    return record


def _collect_group_types(root: CobolField, *, namespace: Optional[str]) -> List[Type]:
    created: Dict[str, Type] = {}
    types: List[Type] = []

    def walk(field: CobolField) -> None:
        if field.children:
            type_key = _type_key(field.name, namespace)
            if type_key not in created:
                types.append(_record_type(field, namespace=namespace, created=created))
            for child in field.children:
                walk(child)

    walk(root)
    return types


class CobolCopybookNormalizer(Normalizer, register=True):
    """Normalize a parsed COBOL copybook into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, CobolCopybookDocument):
            raise ValueError(
                "COBOL copybook source must be a CobolCopybookDocument "
                "(see app.cobolcopybook_parser.parse_cobolcopybook)"
            )

        root = source.root
        namespace = re.sub(r"[^A-Za-z0-9_-]+", "-", root.name).strip("-") or "copybook"
        types = _collect_group_types(root, namespace=namespace)
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=root.name, namespace=namespace),
            title=root.name,
            types=types,
            raw={"cobolcopybook": source.raw} if include_raw else None,
            extras={
                "cobolcopybook_root": root.name,
                "cobolcopybook_tree": field_template(root),
            },
        )
        return normalize_ordering(api)
