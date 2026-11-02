"""ASN.1 → canonical model normalizer — MFI-21.5 (#3995).

Maps a parsed :class:`~app.asn1_parser.Asn1Document` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA`:

* ``SEQUENCE`` / ``SET`` → a RECORD (``extras["asn1_kind"]`` says which), its components fields
  numbered in declaration order; ``OPTIONAL`` / ``DEFAULT`` make a field nullable / defaulted;
* ``CHOICE`` → a UNION of its alternatives' types, the alternatives (name, type, tag,
  extension) in ``extras["asn1_choice_members"]``;
* ``ENUMERATED`` → an ENUM, an inline one lifted to a synthetic ``<Type><Component>`` enum;
* an inline ``SEQUENCE`` / ``SET`` / ``CHOICE`` component → a synthetic ``<Type><Component>``
  type the field references;
* ``Name ::= INTEGER (0..255)``, ``Name ::= SEQUENCE OF X`` and ``Name ::= Other`` → an ALIAS
  of the primitive, list or type (the import used to fail on these);
* constraints → canonical constraints: a value range → ``minimum`` / ``maximum``, ``SIZE`` →
  ``min_length`` / ``max_length`` (strings) or ``min_items`` / ``max_items`` (lists);
* each field keeps its declared ASN.1 type (``asn1_type``), its tag (``asn1_tag``: class,
  number and the kind it resolves to — written, else the module's tagging default, and always
  explicit on a CHOICE), whether it is an extension addition (``asn1_extension``) and its named
  numbers; each type whether it is extensible (``asn1_extensible``) and its own tag.

The module's tagging default, ``EXTENSIBILITY IMPLIED`` and ``IMPORTS`` are kept in the model's
extras. The lint pack (:mod:`app.asn1_lint`), breaking-change classifier
(:mod:`app.asn1_breaking`) and ASN.1 emitter read them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .asn1_parser import Asn1Document, Asn1Member, Asn1Tag, Asn1TypeDef, Bound
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

__all__ = ["ASN1_BUILTIN_TYPES", "Asn1Normalizer", "resolved_tag"]

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

#: Every ASN.1 built-in type name a reference can carry: those mapped to a primitive above and
#: those kept as themselves (``OBJECT IDENTIFIER``, the legacy character strings, ``ANY``).
ASN1_BUILTIN_TYPES = frozenset(
    {
        *_ASN1_BASE_TO_CANONICAL,
        "OBJECT IDENTIFIER", "RELATIVE-OID", "NumericString", "BMPString", "UniversalString",
        "GeneralString", "GraphicString", "TeletexString", "T61String", "VideotexString", "ISO646String",
        "ObjectDescriptor", "EXTERNAL", "EMBEDDED PDV", "CHARACTER STRING", "ANY", "DATE", "TIME-OF-DAY",
        "DATE-TIME", "DURATION", "TIME",
    }
)

_STRING_KINDS = frozenset(
    name for name, mapped in _ASN1_BASE_TO_CANONICAL.items() if mapped in ("string", "bytes")
) | {"NumericString", "BMPString", "UniversalString", "GeneralString", "GraphicString", "TeletexString",
     "T61String", "VideotexString", "ISO646String"}


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


def _constraints_for(
    type_name: str, *, size: Optional[Bound], value_range: Optional[Bound], is_list: bool = False
) -> Optional[Constraints]:
    """The canonical constraints of a declared type and its subtype constraints.

    Args:
        type_name: The declared ASN.1 type (``IA5String``, ``INTEGER``).
        size: Its ``SIZE`` bound.
        value_range: Its value-range bound.
        is_list: The value is a ``SEQUENCE OF`` / ``SET OF``: ``SIZE`` bounds its items.

    Returns:
        The constraints, or ``None`` when there are none.
    """
    rules: Dict[str, Any] = {}
    if type_name in {"GeneralizedTime", "UTCTime"}:
        rules["format"] = "date-time"
    if size is not None:
        low, high = size
        if is_list:
            rules.update(min_items=low, max_items=high)
        elif type_name in _STRING_KINDS:
            rules.update(min_length=low, max_length=high)
    if value_range is not None and not is_list:
        low, high = value_range
        rules.update(minimum=low, maximum=high)
    rules = {key: value for key, value in rules.items() if value is not None}
    return Constraints(**rules) if rules else None


def resolved_tag(tag: Optional[Asn1Tag], *, module_tags: Optional[str], choice: bool) -> Optional[Dict[str, Any]]:
    """A tag as the encodings see it: class, number and the kind it resolves to.

    An unwritten kind takes the module default (``EXPLICIT TAGS`` → explicit, ``IMPLICIT`` /
    ``AUTOMATIC TAGS`` → implicit); a tag on a CHOICE is always explicit (X.680 §31.2.7).

    Args:
        tag: The parsed tag, or ``None``.
        module_tags: The module's tagging default.
        choice: The tagged type is a CHOICE.

    Returns:
        ``{"class", "number", "kind"}``, or ``None`` when no tag is written.
    """
    if tag is None:
        return None
    kind = tag.kind or ("EXPLICIT" if (module_tags or "EXPLICIT").upper() == "EXPLICIT" else "IMPLICIT")
    if choice:
        kind = "EXPLICIT"
    return {"class": tag.tag_class, "number": tag.number, "kind": kind}


def _capitalized(name: str) -> str:
    return f"{name[0].upper()}{name[1:]}" if name else name


class _Builder:
    """Builds the canonical types of one module (the module's names, tagging and synthetic types).

    Args:
        source: The parsed document.
    """

    def __init__(self, source: Asn1Document) -> None:
        module = source.module
        self.namespace: str = module.name
        self.module_tags = module.tags
        self.known: set[str] = {type_def.name for type_def in module.types}
        self.choices: set[str] = {t.name for t in module.types if t.kind == "CHOICE"}
        self.synthetic: Dict[str, Type] = {}

    # --- references -----------------------------------------------------------------------------

    def _named(self, name: str) -> str:
        """A primitive for a mapped built-in, else the referenced type's key."""
        return _ASN1_BASE_TO_CANONICAL.get(name) or _resolve_type_name(
            name, namespace=self.namespace, known=frozenset(self.known)
        )

    def _list_element(self, type_name: str, element_type: Optional[str]) -> str:
        if element_type:
            return element_type
        for prefix in ("SEQUENCE OF ", "SET OF "):
            if type_name.startswith(prefix):
                return type_name[len(prefix):].strip()
        return "ANY"

    def member_ref(self, member: Asn1Member, parent: str) -> TypeRef:
        """The type of one component / alternative, nullable when it is OPTIONAL."""
        if member.enum_values:
            inner = TypeRef(name=self._synthetic_enum(member, parent), nullable=False)
        elif member.inline is not None:
            inner = TypeRef(name=self._synthetic_type(member, parent), nullable=False)
        elif member.element_type or member.type_name.startswith(("SEQUENCE OF", "SET OF")):
            element = self._list_element(member.type_name, member.element_type)
            item = TypeRef(name=self._named(element), nullable=False)
            return TypeRef(item=item, nullable=member.optional)
        else:
            inner = TypeRef(name=self._named(member.type_name), nullable=False)
        return TypeRef(name=inner.name, nullable=member.optional)

    def _synthetic_enum(self, member: Asn1Member, parent: str) -> str:
        enum_name = f"{parent}{_capitalized(member.name)}" if parent else f"{member.name.capitalize()}Enum"
        enum_key = _type_key(enum_name, self.namespace)
        self.synthetic.setdefault(enum_name, self.enum(enum_name, member.enum_values, extensible=False))
        return enum_key

    def _synthetic_type(self, member: Asn1Member, parent: str) -> str:
        """An inline SEQUENCE / SET / CHOICE, declared as ``<Parent><Component>``."""
        assert member.inline is not None
        name = f"{parent}{_capitalized(member.name)}"
        self.known.add(name)
        if member.inline.kind == "CHOICE":
            self.choices.add(name)
        if name not in self.synthetic:
            inline = Asn1TypeDef(
                name=name,
                kind=member.inline.kind,
                members=member.inline.members,
                extensible=member.inline.extensible,
            )
            self.synthetic[name] = self.build(inline)  # type: ignore[assignment]
        return _type_key(name, self.namespace)

    def _is_choice(self, member: Asn1Member) -> bool:
        if member.inline is not None:
            return member.inline.kind == "CHOICE"
        return member.type_name in self.choices

    # --- components -----------------------------------------------------------------------------

    def field_extras(self, member: Asn1Member) -> Dict[str, Any]:
        extras: Dict[str, Any] = {}
        if member.type_name in ASN1_BUILTIN_TYPES:
            extras["asn1_type"] = member.type_name
        tag = resolved_tag(member.tag, module_tags=self.module_tags, choice=self._is_choice(member))
        if tag is not None:
            extras["asn1_tag"] = tag
        if member.extension:
            extras["asn1_extension"] = True
        if member.named_numbers:
            extras["asn1_named_numbers"] = dict(member.named_numbers)
        if member.set_of:
            extras["asn1_set_of"] = True
        return extras

    def field(self, member: Asn1Member, *, parent_key: str, parent: str, number: int) -> CanonicalField:
        is_list = bool(member.element_type) or member.type_name.startswith(("SEQUENCE OF", "SET OF"))
        return CanonicalField(
            key=Keys.field(parent_key, member.name),
            name=member.name,
            type=self.member_ref(member, parent),
            default=member.default,
            field_number=number,
            constraints=_constraints_for(
                member.type_name, size=member.size, value_range=member.value_range, is_list=is_list
            ),
            extras=self.field_extras(member),
        )

    # --- types ----------------------------------------------------------------------------------

    def enum(self, name: str, values: Any, *, extensible: bool) -> Type:
        type_key = _type_key(name, self.namespace)
        return Type(
            key=type_key,
            name=name,
            kind=TypeKind.ENUM,
            enum_values=[
                EnumValue(
                    key=Keys.enum_value(type_key, value.name),
                    name=value.name,
                    value=value.value,
                    extras={"asn1_extension": True} if value.extension else {},
                )
                for value in values
            ],
            extras={"asn1_extensible": True} if extensible else {},
        )

    def _type_extras(self, type_def: Asn1TypeDef, **more: Any) -> Dict[str, Any]:
        extras: Dict[str, Any] = dict(more)
        if type_def.extensible:
            extras["asn1_extensible"] = True
        tag = resolved_tag(type_def.tag, module_tags=self.module_tags, choice=type_def.kind == "CHOICE")
        if tag is not None:
            extras["asn1_tag"] = tag
        if type_def.named_numbers:
            extras["asn1_named_numbers"] = dict(type_def.named_numbers)
        return extras

    def build(self, type_def: Asn1TypeDef) -> Optional[Type]:
        """The canonical type of one assignment (``None`` for one with nothing to model)."""
        type_key = _type_key(type_def.name, self.namespace)
        if type_def.kind == "ENUMERATED":
            enum = self.enum(type_def.name, type_def.enum_values, extensible=type_def.extensible)
            extras = self._type_extras(type_def)
            return enum.model_copy(update={"extras": {**enum.extras, **extras}})
        if type_def.kind == "CHOICE":
            alternatives = []
            for member in type_def.members:
                ref = self.member_ref(member, type_def.name)
                entry: Dict[str, Any] = {"name": member.name, "type": ref.name or (ref.item.name if ref.item else None)}
                entry.update(
                    {
                        k: v
                        for k, v in self.field_extras(member).items()
                        if k in ("asn1_tag", "asn1_extension", "asn1_type")
                    }
                )
                constraints = _constraints_for(
                    member.type_name, size=member.size, value_range=member.value_range, is_list=ref.item is not None
                )
                if constraints is not None:
                    # A union holds member types only; an alternative's own constraints live here.
                    entry["constraints"] = constraints.model_dump(exclude_none=True, exclude={"extras"})
                alternatives.append(entry)
            return Type(
                key=type_key,
                name=type_def.name,
                kind=TypeKind.UNION,
                union_members=[str(entry["type"]) for entry in alternatives],
                extras=self._type_extras(type_def, asn1_choice_members=alternatives),
            )
        if type_def.kind in {"SEQUENCE", "SET"}:
            fields = [
                self.field(member, parent_key=type_key, parent=type_def.name, number=index)
                for index, member in enumerate(type_def.members, start=1)
            ]
            extras = self._type_extras(type_def, **({"asn1_kind": "SET"} if type_def.kind == "SET" else {}))
            return Type(key=type_key, name=type_def.name, kind=TypeKind.RECORD, fields=fields, extras=extras)
        if type_def.kind in {"SEQUENCE OF", "SET OF"}:
            member = type_def.members[0] if type_def.members else None
            element = self._list_element(member.type_name if member else type_def.kind, member and member.element_type)
            extras = self._type_extras(type_def, **({"asn1_set_of": True} if type_def.kind == "SET OF" else {}))
            return Type(
                key=type_key,
                name=type_def.name,
                kind=TypeKind.ALIAS,
                aliased=TypeRef(item=TypeRef(name=self._named(element), nullable=False), nullable=False),
                constraints=_constraints_for(type_def.kind, size=type_def.size, value_range=None, is_list=True),
                extras=extras,
            )
        # A built-in type or a reference to another type: an alias of it.
        extras = self._type_extras(type_def)
        if type_def.kind in ASN1_BUILTIN_TYPES:
            extras["asn1_type"] = type_def.kind
        return Type(
            key=type_key,
            name=type_def.name,
            kind=TypeKind.ALIAS,
            aliased=TypeRef(name=self._named(type_def.kind), nullable=False),
            constraints=_constraints_for(type_def.kind, size=type_def.size, value_range=type_def.value_range),
            extras=extras,
        )


def _collect_types(source: Asn1Document) -> List[Type]:
    builder = _Builder(source)
    types = [built for built in (builder.build(type_def) for type_def in source.module.types) if built is not None]
    declared = {t.key for t in types}
    types.extend(t for t in builder.synthetic.values() if t.key not in declared)
    return types


class Asn1Normalizer(Normalizer, register=True):
    """Normalize a parsed ASN.1 module into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, Asn1Document):
            raise ValueError("ASN.1 source must be an Asn1Document (see app.asn1_parser.parse_asn1)")

        module = source.module
        types = _collect_types(source)
        title = types[0].name if types else module.name
        extras: Dict[str, Any] = {"asn1_module_name": module.name, "asn1_tags": module.tags}
        if module.imports:
            extras["asn1_imports"] = {name: list(names) for name, names in module.imports}
        if module.extensibility_implied:
            extras["asn1_extensibility_implied"] = True
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=module.name, namespace=module.name),
            title=title,
            types=types,
            raw={"asn1": source.raw} if include_raw else None,
            extras=extras,
        )
        return normalize_ordering(api)
