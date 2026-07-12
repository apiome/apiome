"""ISO 20022 → canonical model normalizer — MFI-22.5.

Maps a parsed :class:`~app.iso20022_parser.Iso20022Document` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA`.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Set

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Type,
    TypeKind,
    TypeRef,
)
from .iso20022_parser import Iso20022Document, Iso20022Element, element_template
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["Iso20022Normalizer"]

_FORMAT_KEY = "iso20022"


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _collect_elements(element: Iso20022Element) -> List[Iso20022Element]:
    collected = [element]
    for child in element.children:
        collected.extend(_collect_elements(child))
    return collected


def _child_tags(element: Iso20022Element) -> Counter[str]:
    return Counter(child.tag for child in element.children)


def _is_complex(element: Iso20022Element) -> bool:
    return bool(element.children)


def _record_type(
    prototype: Iso20022Element,
    *,
    namespace: Optional[str],
    repeating_tags: Set[str],
) -> Type:
    type_key = _type_key(prototype.tag, namespace)
    fields: List[CanonicalField] = []
    field_number = 1
    seen_tags: Set[str] = set()
    for child in prototype.children:
        if child.tag in seen_tags and child.tag not in repeating_tags:
            continue
        seen_tags.add(child.tag)
        if _is_complex(child):
            child_type = _type_key(child.tag, namespace)
            if child.tag in repeating_tags:
                type_ref = TypeRef(item=TypeRef(name=child_type, nullable=False), nullable=False)
            else:
                type_ref = TypeRef(name=child_type, nullable=False)
            fields.append(
                CanonicalField(
                    key=Keys.field(type_key, child.tag),
                    name=child.tag,
                    type=type_ref,
                    field_number=field_number,
                    extras={"iso20022_kind": "element"},
                )
            )
        else:
            fields.append(
                CanonicalField(
                    key=Keys.field(type_key, child.tag),
                    name=child.tag,
                    type=TypeRef(name="string", nullable=False),
                    field_number=field_number,
                    default=child.text,
                    extras={
                        "iso20022_kind": "leaf",
                        "iso20022_attributes": [[key, value] for key, value in child.attributes],
                    },
                )
            )
        field_number += 1
    return Type(
        key=type_key,
        name=prototype.tag,
        kind=TypeKind.RECORD,
        fields=tuple(fields),
        extras={"iso20022_kind": "complex"},
    )


class Iso20022Normalizer(Normalizer, register=True):
    """Normalize a parsed ISO 20022 document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, Iso20022Document):
            raise ValueError(
                "ISO 20022 source must be an Iso20022Document (see app.iso20022_parser.parse_iso20022)"
            )

        namespace = source.message_id
        elements = _collect_elements(source.root)
        prototypes: Dict[str, Iso20022Element] = {}
        repeating_tags: Set[str] = set()
        for element in elements:
            if _is_complex(element):
                prototypes.setdefault(element.tag, element)
                for tag, count in _child_tags(element).items():
                    if count > 1:
                        repeating_tags.add(tag)

        types: List[Type] = []
        created: Set[str] = set()
        for element in elements:
            if not _is_complex(element) or element.tag in created:
                continue
            created.add(element.tag)
            types.append(
                _record_type(
                    prototypes.get(element.tag, element),
                    namespace=namespace,
                    repeating_tags=repeating_tags,
                )
            )

        business_child = source.root.children[0]
        title = f"{business_child.tag} ({source.message_id})"
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=title, namespace=namespace),
            title=title,
            types=types,
            raw={"iso20022": source.raw} if include_raw else None,
            extras={
                "iso20022_message_id": source.message_id,
                "iso20022_namespace": source.namespace,
                "iso20022_business_element": business_child.tag,
                "iso20022_tree": element_template(source.root),
            },
        )
        return normalize_ordering(api)
