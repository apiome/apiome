"""ASN.1 module parser — MFI-21.5.

Parses ASN.1 module text into a typed :class:`Asn1Document` AST using
:mod:`asn1tools.parser`. Syntax errors surface as :class:`Asn1ParseError`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from asn1tools.parser import parse_string as _parse_asn1_string

__all__ = [
    "Asn1ParseError",
    "Asn1EnumValue",
    "Asn1Member",
    "Asn1TypeDef",
    "Asn1Module",
    "Asn1Document",
    "is_asn1",
    "parse_asn1",
]


class Asn1ParseError(ValueError):
    """Raised when ASN.1 module text cannot be parsed."""


@dataclass(frozen=True)
class Asn1EnumValue:
    name: str
    value: Optional[int]


@dataclass(frozen=True)
class Asn1Member:
    name: str
    type_name: str
    optional: bool = False
    default: Optional[str] = None
    enum_values: Tuple[Asn1EnumValue, ...] = ()
    element_type: Optional[str] = None


@dataclass(frozen=True)
class Asn1TypeDef:
    name: str
    kind: str
    members: Tuple[Asn1Member, ...] = ()
    enum_values: Tuple[Asn1EnumValue, ...] = ()


@dataclass(frozen=True)
class Asn1Module:
    name: str
    tags: Optional[str]
    types: Tuple[Asn1TypeDef, ...]


@dataclass(frozen=True)
class Asn1Document:
    module: Asn1Module
    raw: str


_ASN1_MODULE_RE = re.compile(
    r"\bDEFINITIONS\b.*::=\s*BEGIN\b",
    re.IGNORECASE | re.DOTALL,
)


def is_asn1(content: str) -> bool:
    """Return ``True`` when ``content`` looks like an ASN.1 module."""
    if not content or not isinstance(content, str):
        return False
    trimmed = content.strip()
    if not trimmed:
        return False
    if _ASN1_MODULE_RE.search(trimmed):
        return True
    if "DEFINITIONS" in trimmed and "::= BEGIN" in trimmed.replace("\n", " "):
        return True
    return False


def _enum_values(raw_values: Any) -> Tuple[Asn1EnumValue, ...]:
    if not isinstance(raw_values, list):
        return ()
    values: List[Asn1EnumValue] = []
    for entry in raw_values:
        if not isinstance(entry, (list, tuple)) or len(entry) < 1:
            continue
        name = entry[0]
        if not isinstance(name, str) or not name:
            continue
        numeric: Optional[int] = None
        if len(entry) > 1 and isinstance(entry[1], int):
            numeric = entry[1]
        values.append(Asn1EnumValue(name=name, value=numeric))
    return tuple(values)


def _member_type_name(raw_type: Mapping[str, Any]) -> str:
    type_name = raw_type.get("type")
    if not isinstance(type_name, str) or not type_name:
        return "ANY"
    if type_name == "SEQUENCE OF":
        element = raw_type.get("element")
        if isinstance(element, Mapping):
            inner = element.get("type")
            if isinstance(inner, str) and inner:
                return f"SEQUENCE OF {inner}"
        return "SEQUENCE OF"
    return type_name


def _members_from_raw(raw_members: Any) -> Tuple[Asn1Member, ...]:
    if not isinstance(raw_members, list):
        return ()
    members: List[Asn1Member] = []
    for raw in raw_members:
        if not isinstance(raw, Mapping):
            continue
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            continue
        type_name = _member_type_name(raw)
        enum_values = _enum_values(raw.get("values"))
        element_type: Optional[str] = None
        if raw.get("type") == "SEQUENCE OF":
            element = raw.get("element")
            if isinstance(element, Mapping):
                inner = element.get("type")
                if isinstance(inner, str):
                    element_type = inner
        members.append(
            Asn1Member(
                name=name,
                type_name=type_name,
                optional=bool(raw.get("optional")),
                default=raw.get("default") if isinstance(raw.get("default"), str) else None,
                enum_values=enum_values,
                element_type=element_type,
            )
        )
    return tuple(members)


def _typedef_from_raw(name: str, raw: Mapping[str, Any]) -> Asn1TypeDef:
    kind = raw.get("type")
    if not isinstance(kind, str) or not kind:
        kind = "ANY"
    if kind == "ENUMERATED":
        return Asn1TypeDef(name=name, kind=kind, enum_values=_enum_values(raw.get("values")))
    if kind in {"SEQUENCE", "CHOICE", "SET"}:
        return Asn1TypeDef(name=name, kind=kind, members=_members_from_raw(raw.get("members")))
    if kind == "SEQUENCE OF":
        element = raw.get("element")
        element_type = element.get("type") if isinstance(element, Mapping) else None
        return Asn1TypeDef(
            name=name,
            kind=kind,
            members=(
                Asn1Member(
                    name=name,
                    type_name=f"SEQUENCE OF {element_type}" if element_type else "SEQUENCE OF",
                    element_type=element_type if isinstance(element_type, str) else None,
                ),
            ),
        )
    return Asn1TypeDef(name=name, kind=kind)


def _module_from_ast(ast: Mapping[str, Any]) -> Asn1Module:
    if not ast:
        raise Asn1ParseError("ASN.1 document contains no modules")
    if len(ast) != 1:
        module_names = ", ".join(sorted(ast))
        raise Asn1ParseError(
            f"ASN.1 import supports a single module per document (found: {module_names})"
        )
    module_name, module_body = next(iter(ast.items()))
    if not isinstance(module_name, str) or not module_name:
        raise Asn1ParseError("ASN.1 module is missing a name")
    if not isinstance(module_body, Mapping):
        raise Asn1ParseError(f"ASN.1 module `{module_name}` is malformed")

    raw_types = module_body.get("types")
    if not isinstance(raw_types, Mapping) or not raw_types:
        raise Asn1ParseError(f"ASN.1 module `{module_name}` defines no types")

    typedefs = tuple(
        _typedef_from_raw(type_name, raw_type)
        for type_name, raw_type in raw_types.items()
        if isinstance(type_name, str) and isinstance(raw_type, Mapping)
    )
    if not typedefs:
        raise Asn1ParseError(f"ASN.1 module `{module_name}` defines no types")

    tags = module_body.get("tags")
    return Asn1Module(
        name=module_name,
        tags=tags if isinstance(tags, str) else None,
        types=typedefs,
    )


def parse_asn1(content: str, *, source_label: Optional[str] = None) -> Asn1Document:
    """Parse ASN.1 module text into an :class:`Asn1Document`."""
    if not content or not content.strip():
        raise Asn1ParseError("Invalid or empty ASN.1 document")
    if not is_asn1(content):
        label = f" ({source_label})" if source_label else ""
        raise Asn1ParseError(f"Content does not appear to be an ASN.1 module{label}")
    try:
        ast = _parse_asn1_string(content)
    except Exception as exc:
        raise Asn1ParseError(f"Malformed ASN.1 module: {exc}") from exc
    if not isinstance(ast, Mapping):
        raise Asn1ParseError("ASN.1 parser returned an unexpected structure")
    return Asn1Document(module=_module_from_ast(ast), raw=content)
