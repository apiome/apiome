"""ASN.1 module parser — MFI-21.5 (#3995).

Parses ASN.1 module text into a typed :class:`Asn1Document` AST using
:mod:`asn1tools.parser`. Syntax errors surface as :class:`Asn1ParseError`.

What the AST keeps of an ITU-T X.680 module:

* the module's **tagging default** (``EXPLICIT`` / ``IMPLICIT`` / ``AUTOMATIC TAGS``), whether
  ``EXTENSIBILITY IMPLIED`` is set, and its ``IMPORTS`` (module → names);
* every **type assignment**: ``SEQUENCE`` / ``SET`` / ``CHOICE`` with their components,
  ``ENUMERATED`` with its items, ``SEQUENCE OF`` / ``SET OF`` with their element, a reference to
  another type (``Name ::= Other``) and a built-in type (``Version ::= INTEGER``);
* on each type and component: its **tag** (``[APPLICATION 3] IMPLICIT``), its **constraints**
  (``(0..255)``, ``(SIZE (1..64))``), its ``OPTIONAL`` / ``DEFAULT``, named numbers
  (``INTEGER { v1(0) }``) and named bits;
* the **extension marker** ``...``: a type that has one is *extensible*, and every component,
  alternative or enumeration item after it (an extension addition, ``[[ … ]]`` groups flattened)
  is marked as such;
* an inline ``SEQUENCE`` / ``SET`` / ``CHOICE`` component is kept as its own nested type
  definition.

Value assignments, information object classes and parameterized types are not modelled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Tuple

from asn1tools.parser import parse_string as _parse_asn1_string

__all__ = [
    "Asn1ParseError",
    "Asn1Tag",
    "Asn1EnumValue",
    "Asn1Member",
    "Asn1TypeDef",
    "Asn1Module",
    "Asn1Document",
    "is_asn1",
    "parse_asn1",
]

#: Bound = ``(lower, upper)``; either side is ``None`` for ``MIN`` / ``MAX`` or an open end.
Bound = Tuple[Optional[int], Optional[int]]


class Asn1ParseError(ValueError):
    """Raised when ASN.1 module text cannot be parsed."""


@dataclass(frozen=True)
class Asn1Tag:
    """A tag, ``[CLASS number] KIND``.

    Attributes:
        tag_class: ``CONTEXT`` (no class keyword), ``APPLICATION``, ``PRIVATE`` or ``UNIVERSAL``.
        number: The tag number.
        kind: ``EXPLICIT`` / ``IMPLICIT`` when written, else ``None`` (the module default).
    """

    tag_class: str
    number: int
    kind: Optional[str] = None


@dataclass(frozen=True)
class Asn1EnumValue:
    name: str
    value: Optional[int]
    #: Whether the item comes after the ``...`` extension marker.
    extension: bool = False


@dataclass(frozen=True)
class Asn1Member:
    """A component of a SEQUENCE / SET or an alternative of a CHOICE.

    Attributes:
        name: The component identifier.
        type_name: Its type (``INTEGER``, ``SEQUENCE OF Name``, a type reference).
        optional: ``OPTIONAL``.
        default: The ``DEFAULT`` value (a number, boolean or identifier), when declared.
        enum_values: The items of an inline ``ENUMERATED``.
        element_type: The element type of an inline ``SEQUENCE OF`` / ``SET OF``.
        tag: Its tag, when one is written.
        size: Its ``SIZE`` constraint (of the string, or of the ``SEQUENCE OF``).
        value_range: Its value-range constraint (``INTEGER (0..255)``).
        extension: Whether it comes after the ``...`` extension marker.
        set_of: Whether an inline list is ``SET OF`` (unordered) rather than ``SEQUENCE OF``.
        inline: An inline ``SEQUENCE`` / ``SET`` / ``CHOICE`` body, kept as a nested definition.
        named_numbers: ``INTEGER { a(1) }`` named numbers / ``BIT STRING { b(0) }`` named bits.
    """

    name: str
    type_name: str
    optional: bool = False
    default: Optional[Any] = None
    enum_values: Tuple[Asn1EnumValue, ...] = ()
    element_type: Optional[str] = None
    tag: Optional[Asn1Tag] = None
    size: Optional[Bound] = None
    value_range: Optional[Bound] = None
    extension: bool = False
    set_of: bool = False
    inline: Optional["Asn1TypeDef"] = None
    named_numbers: Tuple[Tuple[str, int], ...] = ()


@dataclass(frozen=True)
class Asn1TypeDef:
    """A type assignment, ``Name ::= …``.

    Attributes:
        name: The type reference.
        kind: ``SEQUENCE`` / ``SET`` / ``CHOICE`` / ``ENUMERATED`` / ``SEQUENCE OF`` / ``SET OF``,
            a built-in type (``INTEGER``), or the name of the type it refers to.
        members: The components / alternatives (a list type has one member, its element).
        enum_values: The ``ENUMERATED`` items.
        tag: The type's own tag (``Name ::= [APPLICATION 1] SEQUENCE { … }``).
        size: Its ``SIZE`` constraint.
        value_range: Its value-range constraint.
        extensible: Whether its body has the ``...`` extension marker (or the module implies it).
        named_numbers: Named numbers / named bits of a built-in type.
    """

    name: str
    kind: str
    members: Tuple[Asn1Member, ...] = ()
    enum_values: Tuple[Asn1EnumValue, ...] = ()
    tag: Optional[Asn1Tag] = None
    size: Optional[Bound] = None
    value_range: Optional[Bound] = None
    extensible: bool = False
    named_numbers: Tuple[Tuple[str, int], ...] = ()


@dataclass(frozen=True)
class Asn1Module:
    name: str
    tags: Optional[str]
    types: Tuple[Asn1TypeDef, ...]
    #: ``IMPORTS``: ``(module, (name, …))`` per ``FROM`` clause.
    imports: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()
    #: ``EXTENSIBILITY IMPLIED`` in the module header.
    extensibility_implied: bool = False


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


#: The type kinds whose components / alternatives are listed in ``members``.
_CONSTRUCTED = frozenset({"SEQUENCE", "SET", "CHOICE"})
#: The list kinds, whose element is in ``element``.
_LISTS = frozenset({"SEQUENCE OF", "SET OF"})


def _int_or_none(value: Any) -> Optional[int]:
    """An integer bound, or ``None`` for ``MIN`` / ``MAX`` / anything not an integer."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _bound(raw: Any) -> Optional[Bound]:
    """A single range or single value of an asn1tools constraint list (``[[1, 64]]``, ``[4]``).

    A constraint with several ranges (``(1..4 | 8)``) or none is not modelled (``None``).
    """
    if not isinstance(raw, list) or len(raw) != 1:
        return None
    entry = raw[0]
    if isinstance(entry, (list, tuple)) and len(entry) == 2:
        return _int_or_none(entry[0]), _int_or_none(entry[1])
    value = _int_or_none(entry)
    return (value, value) if value is not None else None


def _tag(raw: Any) -> Optional[Asn1Tag]:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("number"), int):
        return None
    kind = raw.get("kind")
    return Asn1Tag(
        tag_class=str(raw.get("class") or "CONTEXT"),
        number=int(raw["number"]),
        kind=kind if kind in ("EXPLICIT", "IMPLICIT") else None,
    )


def _named_numbers(raw: Mapping[str, Any]) -> Tuple[Tuple[str, int], ...]:
    """``named-numbers`` (INTEGER) or ``named-bits`` (BIT STRING), in declaration order."""
    named = raw.get("named-numbers")
    if isinstance(named, Mapping):
        return tuple((str(k), int(v)) for k, v in named.items() if isinstance(v, int))
    bits = raw.get("named-bits")
    if isinstance(bits, list):
        return tuple(
            (str(entry[0]), int(entry[1]))
            for entry in bits
            if isinstance(entry, (list, tuple)) and len(entry) == 2 and str(entry[1]).lstrip("-").isdigit()
        )
    return ()


def _enum_values(raw_values: Any) -> Tuple[Asn1EnumValue, ...]:
    """ENUMERATED items; a ``None`` entry is the ``...`` marker, after which items are extensions."""
    if not isinstance(raw_values, list):
        return ()
    values: List[Asn1EnumValue] = []
    extension = False
    for entry in raw_values:
        if entry is None:
            extension = True
            continue
        if not isinstance(entry, (list, tuple)) or len(entry) < 1:
            continue
        name = entry[0]
        if not isinstance(name, str) or not name:
            continue
        numeric = entry[1] if len(entry) > 1 and isinstance(entry[1], int) else None
        values.append(Asn1EnumValue(name=name, value=numeric, extension=extension))
    return tuple(values)


def _is_extensible(raw_entries: Any) -> bool:
    """Whether a members / values list holds the ``...`` marker (asn1tools writes it as ``None``)."""
    return isinstance(raw_entries, list) and any(entry is None for entry in raw_entries)


def _element_type(raw: Mapping[str, Any]) -> Optional[str]:
    element = raw.get("element")
    inner = element.get("type") if isinstance(element, Mapping) else None
    return inner if isinstance(inner, str) and inner else None


def _member_type_name(raw_type: Mapping[str, Any]) -> str:
    type_name = raw_type.get("type")
    if not isinstance(type_name, str) or not type_name:
        return "ANY"
    if type_name in _LISTS:
        inner = _element_type(raw_type)
        return f"{type_name} {inner}" if inner else type_name
    return type_name


def _default(raw: Any) -> Optional[Any]:
    """A DEFAULT value asn1tools reports as a scalar (number, boolean or identifier)."""
    return raw if isinstance(raw, (str, int, float, bool)) else None


def _member(raw: Mapping[str, Any], *, extension: bool) -> Optional[Asn1Member]:
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        return None
    kind = raw.get("type")
    inline: Optional[Asn1TypeDef] = None
    if kind in _CONSTRUCTED:
        inline = _typedef_from_raw(name, raw)
    is_list = kind in _LISTS
    return Asn1Member(
        name=name,
        type_name=_member_type_name(raw),
        optional=bool(raw.get("optional")),
        default=_default(raw.get("default")),
        enum_values=_enum_values(raw.get("values")),
        element_type=_element_type(raw) if is_list else None,
        tag=_tag(raw.get("tag")),
        size=_bound(raw.get("size")),
        value_range=_bound(raw.get("restricted-to")),
        extension=extension,
        set_of=kind == "SET OF",
        inline=inline,
        named_numbers=_named_numbers(raw),
    )


def _members_from_raw(raw_members: Any) -> Tuple[Asn1Member, ...]:
    """Components in order; ``None`` is the ``...`` marker and a list an ``[[ … ]]`` group."""
    if not isinstance(raw_members, list):
        return ()
    members: List[Asn1Member] = []
    extension = False
    for raw in raw_members:
        if raw is None:
            extension = True
            continue
        group = raw if isinstance(raw, list) else [raw]
        for item in group:
            member = _member(item, extension=extension) if isinstance(item, Mapping) else None
            if member is not None:
                members.append(member)
    return tuple(members)


def _typedef_from_raw(name: str, raw: Mapping[str, Any], *, implied: bool = False) -> Asn1TypeDef:
    """One type assignment (or inline constructed type) from its asn1tools dict.

    Args:
        name: The type reference (or, for an inline type, the component name).
        raw: The asn1tools dict.
        implied: The module declares ``EXTENSIBILITY IMPLIED``.

    Returns:
        The type definition.
    """
    kind = raw.get("type")
    if not isinstance(kind, str) or not kind:
        kind = "ANY"
    common = dict(
        tag=_tag(raw.get("tag")),
        size=_bound(raw.get("size")),
        value_range=_bound(raw.get("restricted-to")),
        named_numbers=_named_numbers(raw),
    )
    if kind == "ENUMERATED":
        values = raw.get("values")
        return Asn1TypeDef(
            name=name,
            kind=kind,
            enum_values=_enum_values(values),
            extensible=implied or _is_extensible(values),
            **common,
        )
    if kind in _CONSTRUCTED:
        members = raw.get("members")
        return Asn1TypeDef(
            name=name,
            kind=kind,
            members=_members_from_raw(members),
            extensible=implied or _is_extensible(members),
            **common,
        )
    if kind in _LISTS:
        element_type = _element_type(raw)
        return Asn1TypeDef(
            name=name,
            kind=kind,
            members=(
                Asn1Member(
                    name=name,
                    type_name=f"{kind} {element_type}" if element_type else kind,
                    element_type=element_type,
                    set_of=kind == "SET OF",
                ),
            ),
            **common,
        )
    return Asn1TypeDef(name=name, kind=kind, **common)


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

    implied = bool(module_body.get("extensibility-implied"))
    typedefs = tuple(
        _typedef_from_raw(type_name, raw_type, implied=implied)
        for type_name, raw_type in raw_types.items()
        if isinstance(type_name, str) and isinstance(raw_type, Mapping)
    )
    if not typedefs:
        raise Asn1ParseError(f"ASN.1 module `{module_name}` defines no types")

    tags = module_body.get("tags")
    raw_imports = module_body.get("imports")
    imports = tuple(
        (str(module), tuple(str(name) for name in names))
        for module, names in (raw_imports.items() if isinstance(raw_imports, Mapping) else ())
        if isinstance(names, list)
    )
    return Asn1Module(
        name=module_name,
        tags=tags if isinstance(tags, str) else None,
        types=typedefs,
        imports=imports,
        extensibility_implied=implied,
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
