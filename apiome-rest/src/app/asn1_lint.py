"""ASN.1 lint pack — MFI-21.5 (#3995).

Native, deterministic quality rules for ASN.1 (ITU-T X.680) modules, layered on the canonical lint
engine (MFI-4.1 :mod:`app.lint_engine`). The :class:`Asn1RulePack` is registered under the
``asn1`` format key, so it runs with the always-on common pack on every ASN.1 artifact. The rules
read the model :class:`~app.asn1_normalizer.Asn1Normalizer` builds: each component's declared
built-in (``asn1_type``), tag (``asn1_tag``), extension flag and named numbers, each type's kind and
extensibility, and the module's tagging default and ``IMPORTS``.

The tag rules follow X.680: a BER / DER / PER decoder tells components apart by their **tag**, so
it is a compile error for two alternatives of a CHOICE, two components of a SET, or a run of
optional SEQUENCE components and the component after it to share one. A component's tag is the
one written on it, else the UNIVERSAL tag of its type (``INTEGER`` → 2, ``SEQUENCE`` → 16 …); a
type whose components carry no tag in an ``AUTOMATIC TAGS`` module is tagged automatically and is
never ambiguous.

* **asn1.type-resolves** (error) — a reference that is neither a built-in type, a type the module
  assigns, nor a name it ``IMPORTS``.
* **asn1.choice-tags-distinct** (error) — two CHOICE alternatives with the same tag (X.680 §29.3).
* **asn1.set-tags-distinct** (error) — two SET components with the same tag (§27.3).
* **asn1.sequence-tags-unambiguous** (error) — an OPTIONAL / DEFAULT component whose tag equals
  that of a component that may follow it (§25.5): a decoder cannot tell whether it was omitted.
* **asn1.default-valid** (warning) — a DEFAULT outside the component's value range, or naming an
  item / named number its type does not declare.
* **asn1.any-deprecated** (warning) — ``ANY``, removed from ASN.1 in 1994: use an open type or a
  CHOICE.
* **asn1.legacy-string-type** (info) — ``TeletexString`` / ``T61String`` / ``VideotexString`` /
  ``GraphicString`` / ``GeneralString`` / ``UniversalString``: RFC 5280 §4.1.2.4 directs new
  certificates to ``UTF8String`` (or ``PrintableString``).
* **asn1.extension-marker** (info) — a SEQUENCE, SET, CHOICE or ENUMERATED without ``...``: adding a
  component later breaks PER peers and strict decoders, which an extension marker allows for.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Set, Tuple

from .asn1_normalizer import ASN1_BUILTIN_TYPES
from .canonical_model import CanonicalApi, CanonicalField, Type, TypeKind, TypeRef
from .lint_engine import LintRule, RulePack

__all__ = ["Asn1RulePack", "UNIVERSAL_TAGS", "component_tag"]

#: A tag: ``(class, number)``.
Tag = Tuple[str, int]

#: UNIVERSAL tag numbers of the built-in types (X.680 §8.6, table 1).
UNIVERSAL_TAGS: Mapping[str, int] = {
    "BOOLEAN": 1,
    "INTEGER": 2,
    "BIT STRING": 3,
    "OCTET STRING": 4,
    "NULL": 5,
    "OBJECT IDENTIFIER": 6,
    "ObjectDescriptor": 7,
    "EXTERNAL": 8,
    "REAL": 9,
    "ENUMERATED": 10,
    "EMBEDDED PDV": 11,
    "UTF8String": 12,
    "RELATIVE-OID": 13,
    "TIME": 14,
    "SEQUENCE": 16,
    "SET": 17,
    "NumericString": 18,
    "PrintableString": 19,
    "TeletexString": 20,
    "T61String": 20,
    "VideotexString": 21,
    "IA5String": 22,
    "UTCTime": 23,
    "GeneralizedTime": 24,
    "GraphicString": 25,
    "VisibleString": 26,
    "ISO646String": 26,
    "GeneralString": 27,
    "UniversalString": 28,
    "CHARACTER STRING": 29,
    "BMPString": 30,
    "DATE": 31,
    "TIME-OF-DAY": 32,
    "DATE-TIME": 33,
    "DURATION": 34,
}

#: Canonical primitives the normalizer maps built-ins to → the built-in they most often are.
_PRIMITIVE_TAGS: Mapping[str, str] = {
    "integer": "INTEGER",
    "bool": "BOOLEAN",
    "null": "NULL",
    "double": "REAL",
    "string": "UTF8String",
    "bytes": "OCTET STRING",
}

_LEGACY_STRINGS = frozenset(
    {"TeletexString", "T61String", "VideotexString", "GraphicString", "GeneralString", "UniversalString"}
)

#: A finding: ``(path, message)``.
Finding = Tuple[str, str]


class _Module:
    """The model's types by key and the module facts the rules share."""

    def __init__(self, api: CanonicalApi) -> None:
        self.api = api
        self.by_key: Dict[str, Type] = {t.key: t for t in api.types}
        self.automatic = str(api.extras.get("asn1_tags") or "").upper() == "AUTOMATIC"
        imports = api.extras.get("asn1_imports") or {}
        self.imported: Set[str] = (
            {str(n) for names in imports.values() for n in names} if isinstance(imports, Mapping) else set()
        )

    def type_tag(self, type_: Type, seen: Optional[Set[str]] = None) -> Optional[Tag]:
        """The tag values of ``type_`` carry, or ``None`` (an untagged CHOICE, a cycle, unknown)."""
        own = _tag(type_.extras)
        if own is not None:
            return own
        seen = seen or set()
        if type_.key in seen:
            return None
        seen.add(type_.key)
        if type_.kind is TypeKind.RECORD:
            return ("UNIVERSAL", 17 if type_.extras.get("asn1_kind") == "SET" else 16)
        if type_.kind is TypeKind.ENUM:
            return ("UNIVERSAL", 10)
        if type_.kind is TypeKind.ALIAS and type_.aliased is not None:
            declared = type_.extras.get("asn1_type")
            if isinstance(declared, str) and declared in UNIVERSAL_TAGS:
                return ("UNIVERSAL", UNIVERSAL_TAGS[declared])
            if type_.aliased.is_list():
                return ("UNIVERSAL", 17 if type_.extras.get("asn1_set_of") else 16)
            return self.ref_tag(type_.aliased, seen)
        return None

    def ref_tag(self, ref: TypeRef, seen: Optional[Set[str]] = None) -> Optional[Tag]:
        """The tag of a value of type ``ref`` (untagged)."""
        if ref.is_list():
            return ("UNIVERSAL", 16)
        name = ref.name or ""
        target = self.by_key.get(name)
        if target is not None:
            return self.type_tag(target, seen)
        builtin = _builtin(name)
        if builtin in UNIVERSAL_TAGS:
            return ("UNIVERSAL", UNIVERSAL_TAGS[builtin])
        primitive = _PRIMITIVE_TAGS.get(name)
        return ("UNIVERSAL", UNIVERSAL_TAGS[primitive]) if primitive else None


def _tag(extras: Mapping[str, Any]) -> Optional[Tag]:
    tag = extras.get("asn1_tag") if isinstance(extras, Mapping) else None
    if isinstance(tag, Mapping) and isinstance(tag.get("number"), int):
        return (str(tag.get("class") or "CONTEXT"), int(tag["number"]))
    return None


def _builtin(name: str) -> str:
    """The built-in a reference names, ``"Module.OBJECT IDENTIFIER"`` → ``"OBJECT IDENTIFIER"``."""
    return name.split(".", 1)[1] if "." in name and name.split(".", 1)[1] in ASN1_BUILTIN_TYPES else name


def component_tag(module: _Module, field: CanonicalField) -> Optional[Tag]:
    """The tag a component is encoded with: its own, else its declared built-in's, else its type's."""
    own = _tag(field.extras)
    if own is not None:
        return own
    if field.type.is_list():
        return ("UNIVERSAL", 17 if field.extras.get("asn1_set_of") else 16)
    declared = field.extras.get("asn1_type")
    if isinstance(declared, str) and declared in UNIVERSAL_TAGS:
        return ("UNIVERSAL", UNIVERSAL_TAGS[declared])
    return module.ref_tag(field.type)


def _auto_tagged(module: _Module, extras: Iterable[Mapping[str, Any]]) -> bool:
    """Whether a type's components are tagged automatically (AUTOMATIC TAGS and none tagged)."""
    return module.automatic and not any(_tag(e) for e in extras)


def _label(tag: Tag) -> str:
    cls, number = tag
    return f"[{number}]" if cls == "CONTEXT" else f"[{cls} {number}]"


def _records(api: CanonicalApi) -> Iterator[Type]:
    yield from (t for t in api.types if t.kind is TypeKind.RECORD)


def _refs(api: CanonicalApi) -> Iterator[Tuple[str, TypeRef]]:
    """Every ``(path, reference)`` a field, alias or CHOICE alternative makes."""
    for type_ in api.types:
        for field in type_.fields:
            yield field.key, field.type
        if type_.kind is TypeKind.ALIAS and type_.aliased is not None:
            yield type_.key, type_.aliased
        for member in type_.union_members:
            yield type_.key, TypeRef(name=member)


def _check_type_resolves(api: CanonicalApi) -> Iterable[Finding]:
    """Every referenced type must be a built-in, assigned in the module, or imported."""
    module = _Module(api)
    reported: Set[Tuple[str, str]] = set()
    for path, ref in _refs(api):
        while ref.item is not None:
            ref = ref.item
        name = ref.name or ""
        if not name or name in module.by_key or name in _PRIMITIVE_TAGS:
            continue
        local = name.rsplit(".", 1)[-1] if name.startswith(f"{api.identity.namespace}.") else name
        if _builtin(name) in ASN1_BUILTIN_TYPES or local in ASN1_BUILTIN_TYPES or local in module.imported:
            continue
        if (path, local) in reported:
            continue
        reported.add((path, local))
        yield (
            path,
            f"Type {local!r} is not a built-in type, not assigned in this module and not imported; an "
            "ASN.1 compiler rejects the module. Add it to IMPORTS or define it.",
        )


def _duplicate_tags(module: _Module, entries: List[Tuple[str, Optional[Tag]]]) -> Iterator[Tuple[str, Tag, str]]:
    """``(path, tag, earlier path)`` for every entry whose known tag an earlier entry already has."""
    first: Dict[Tag, str] = {}
    for path, tag in entries:
        if tag is None:
            continue
        if tag in first:
            yield path, tag, first[tag]
        else:
            first[tag] = path


def _check_choice_tags_distinct(api: CanonicalApi) -> Iterable[Finding]:
    """CHOICE alternatives must have distinct tags."""
    module = _Module(api)
    for type_ in api.types:
        alternatives = type_.extras.get("asn1_choice_members") if type_.kind is TypeKind.UNION else None
        if not isinstance(alternatives, list):
            continue
        extras = [a if isinstance(a, Mapping) else {} for a in alternatives]
        if _auto_tagged(module, extras):
            continue
        entries = [(f"{type_.key}.{a.get('name')}", _alternative_tag(module, a)) for a in extras]
        for path, tag, earlier in _duplicate_tags(module, entries):
            yield (
                path,
                f"Alternative {path.rsplit('.', 1)[-1]!r} has tag {_label(tag)}, as {earlier.rsplit('.', 1)[-1]!r} "
                "does; a decoder cannot tell which was sent. Tag the alternatives distinctly.",
            )


def _alternative_tag(module: _Module, alternative: Mapping[str, Any]) -> Optional[Tag]:
    """A CHOICE alternative's tag: its own, else its declared built-in's, else its type's."""
    own = _tag(alternative)
    if own is not None:
        return own
    declared = alternative.get("asn1_type")
    if isinstance(declared, str) and declared in UNIVERSAL_TAGS:
        return ("UNIVERSAL", UNIVERSAL_TAGS[declared])
    return module.ref_tag(TypeRef(name=str(alternative.get("type") or "")))


def _ordered_fields(type_: Type) -> List[CanonicalField]:
    return sorted(type_.fields, key=lambda f: f.field_number or 0)


def _check_set_tags_distinct(api: CanonicalApi) -> Iterable[Finding]:
    """SET components must have distinct tags."""
    module = _Module(api)
    for type_ in _records(api):
        if type_.extras.get("asn1_kind") != "SET":
            continue
        fields = _ordered_fields(type_)
        if _auto_tagged(module, [f.extras for f in fields]):
            continue
        for path, tag, earlier in _duplicate_tags(module, [(f.key, component_tag(module, f)) for f in fields]):
            yield (
                path,
                f"SET component {path.rsplit('.', 1)[-1]!r} has tag {_label(tag)}, as "
                f"{earlier.rsplit('.', 1)[-1]!r} does; a SET is decoded by tag, so they cannot be told apart.",
            )


def _optional(field: CanonicalField) -> bool:
    return field.type.nullable or field.default is not None


def _check_sequence_tags_unambiguous(api: CanonicalApi) -> Iterable[Finding]:
    """An optional SEQUENCE component's tag must differ from every component that may follow it."""
    module = _Module(api)
    for type_ in _records(api):
        if type_.extras.get("asn1_kind") == "SET":
            continue
        fields = _ordered_fields(type_)
        if _auto_tagged(module, [f.extras for f in fields]):
            continue
        tags = [component_tag(module, f) for f in fields]
        for index, field in enumerate(fields):
            if not _optional(field) or tags[index] is None:
                continue
            # The components a decoder may meet instead: the following optional ones and the first
            # required one after them.
            for later in range(index + 1, len(fields)):
                if tags[later] == tags[index]:
                    yield (
                        field.key,
                        f"Optional component {field.name!r} has tag {_label(tags[index])}, as the following "
                        f"{fields[later].name!r} does; when it is omitted a decoder reads {fields[later].name!r} "
                        "as it. Tag them distinctly.",
                    )
                    break
                if not _optional(fields[later]):
                    break


def _named_values(module: _Module, field: CanonicalField) -> Optional[Set[str]]:
    """The identifiers a DEFAULT of ``field`` may name (enum items, named numbers), or ``None``."""
    names: Set[str] = set((field.extras.get("asn1_named_numbers") or {}).keys())
    target = module.by_key.get(field.type.name or "")
    if target is not None:
        if target.kind is TypeKind.ENUM:
            names |= {v.name for v in target.enum_values}
        names |= set((target.extras.get("asn1_named_numbers") or {}).keys())
    return names or None


def _check_default_valid(api: CanonicalApi) -> Iterable[Finding]:
    """A DEFAULT must be inside the value range and name only declared items."""
    module = _Module(api)
    for type_ in _records(api):
        for field in type_.fields:
            default = field.default
            if default is None or isinstance(default, bool):
                continue
            if isinstance(default, (int, float)):
                c = field.constraints
                if c is not None and (
                    (c.minimum is not None and default < c.minimum) or (c.maximum is not None and default > c.maximum)
                ):
                    yield (field.key, f"DEFAULT {default} is outside the component's range {c.minimum}..{c.maximum}.")
            elif isinstance(default, str):
                names = _named_values(module, field)
                if names is not None and default not in names:
                    yield (
                        field.key,
                        f"DEFAULT {default!r} is not an item or named number of the component's type "
                        f"({', '.join(sorted(names))}).",
                    )


def _declared_types(api: CanonicalApi) -> Iterator[Tuple[str, str]]:
    """Every ``(path, built-in)`` a field or alias declares."""
    for type_ in api.types:
        declared = type_.extras.get("asn1_type")
        if isinstance(declared, str):
            yield type_.key, declared
        for field in type_.fields:
            declared = field.extras.get("asn1_type")
            if isinstance(declared, str):
                yield field.key, declared
            elif field.type.name and _builtin(field.type.name) in ASN1_BUILTIN_TYPES:
                yield field.key, _builtin(field.type.name)


def _check_any_deprecated(api: CanonicalApi) -> Iterable[Finding]:
    """``ANY`` was removed from ASN.1 in 1994."""
    for path, declared in _declared_types(api):
        if declared == "ANY":
            yield (path, "ANY was removed from ASN.1 in 1994; use an open type (CLASS.&Type) or a CHOICE.")


def _check_legacy_string_type(api: CanonicalApi) -> Iterable[Finding]:
    """Legacy character-string types should be UTF8String."""
    for path, declared in _declared_types(api):
        if declared in _LEGACY_STRINGS:
            yield (
                path,
                f"{declared} is a legacy character-string type; RFC 5280 §4.1.2.4 directs new data to UTF8String "
                "(or PrintableString).",
            )


def _check_extension_marker(api: CanonicalApi) -> Iterable[Finding]:
    """A SEQUENCE, SET, CHOICE or ENUMERATED should be extensible."""
    if api.extras.get("asn1_extensibility_implied"):
        return
    for type_ in api.types:
        if type_.kind not in (TypeKind.RECORD, TypeKind.UNION, TypeKind.ENUM):
            continue
        if type_.extras.get("asn1_extensible"):
            continue
        kind = {TypeKind.UNION: "CHOICE", TypeKind.ENUM: "ENUMERATED"}.get(
            type_.kind, str(type_.extras.get("asn1_kind") or "SEQUENCE")
        )
        yield (
            type_.key,
            f"{kind} {type_.name!r} has no extension marker (...); adding to it later breaks PER peers and strict "
            "decoders. Add ... where new components may go.",
        )


class Asn1RulePack(RulePack, register=True):
    """Native rules for ASN.1 modules (see the module docstring)."""

    format = "asn1"
    pack_id = "asn1"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="asn1.type-resolves",
            category="structure",
            severity="error",
            description="Every referenced type must be built in, assigned in the module or imported.",
            check=_check_type_resolves,
        ),
        LintRule(
            rule_id="asn1.choice-tags-distinct",
            category="structure",
            severity="error",
            description="CHOICE alternatives must have distinct tags.",
            check=_check_choice_tags_distinct,
        ),
        LintRule(
            rule_id="asn1.set-tags-distinct",
            category="structure",
            severity="error",
            description="SET components must have distinct tags.",
            check=_check_set_tags_distinct,
        ),
        LintRule(
            rule_id="asn1.sequence-tags-unambiguous",
            category="structure",
            severity="error",
            description="An optional SEQUENCE component's tag must differ from the components that may follow it.",
            check=_check_sequence_tags_unambiguous,
        ),
        LintRule(
            rule_id="asn1.default-valid",
            category="structure",
            severity="warning",
            description="A DEFAULT must be in range and name only declared items.",
            check=_check_default_valid,
        ),
        LintRule(
            rule_id="asn1.any-deprecated",
            category="compatibility",
            severity="warning",
            description="ANY was removed from ASN.1 in 1994.",
            check=_check_any_deprecated,
        ),
        LintRule(
            rule_id="asn1.legacy-string-type",
            category="compatibility",
            severity="info",
            description="Legacy character-string types should be UTF8String.",
            check=_check_legacy_string_type,
        ),
        LintRule(
            rule_id="asn1.extension-marker",
            category="compatibility",
            severity="info",
            description="A SEQUENCE, SET, CHOICE or ENUMERATED should carry an extension marker.",
            check=_check_extension_marker,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the ASN.1 native rules in deterministic execution order."""
        return list(self._RULES)
