"""Shared XML Schema (XSD 1.0) writer for the XML-family emitters — MFX-14.1 (#3889), MFX-29.1 (#4173).

Builds the ``xsd:schema`` that WSDL (``wsdl:types``) and WADL (``wadl:grammars``) export, so both
write the same, valid types for the same model:

* records → ``complexType`` + ``sequence`` and a global element of the same name;
* lists → ``maxOccurs`` (from ``minItems``/``maxItems``); nullable → ``minOccurs="0" nillable="true"``;
* constraints → length / range / pattern / enumeration facets (patterns via
  :func:`app.xsd_types.xsd_pattern`);
* enums → ``simpleType``; unions → ``xs:choice``; maps → a list of ``entry`` elements; aliases and
  named scalars → derived types; descriptions → ``xs:annotation``;
* scalars keep their precision (:func:`app.xsd_types.xsd_builtin`);
* a field imported from XSD (``extras["xsd_type"]`` …) is written back with the occurrence, facets
  and type it was read with.

Names are made legal ``NCName`` s and de-duplicated; every change, and every construct XSD cannot
carry, is recorded on the caller's :class:`~app.emitter.LossTracker`. The matching predicted
verdicts for a fidelity rule pack are :func:`schema_type_verdict`, :func:`schema_field_verdicts`
and :func:`target_namespace_verdicts`.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from .canonical_model import CanonicalApi, CanonicalField, Constraints, Type, TypeKind, TypeRef
from .emitter import LossKind, LossTracker, Provenance, ProvenanceTracker
from .fidelity_rulepack import FidelityVerdict, rename_verdict
from .lossiness import LossinessSeverity
from .xsd_types import ncname, xsd_builtin, xsd_pattern

__all__ = [
    "TNS_PREFIX",
    "XSD_NS",
    "XSD_PREFIX",
    "NameScope",
    "XsdSchemaWriter",
    "anonymous_sequence",
    "comment_safe",
    "schema_field_verdicts",
    "schema_type_verdict",
    "target_namespace_verdicts",
    "unsupported_facets",
]

XSD_NS = "http://www.w3.org/2001/XMLSchema"
XSD_PREFIX = "xsd"
TNS_PREFIX = "tns"

#: XSD built-ins that take length facets, and those that take range facets.
_LENGTH_BASES = frozenset({"string", "normalizedString", "token", "anyURI", "base64Binary", "hexBinary"})
_RANGE_BASES = frozenset(
    {
        "decimal", "integer", "long", "int", "short", "byte", "unsignedLong", "unsignedInt",
        "unsignedShort", "unsignedByte", "float", "double", "dateTime", "date", "time",
        "nonNegativeInteger", "positiveInteger", "nonPositiveInteger", "negativeInteger",
    }
)


class NameScope:
    """Names already used in one XML symbol space; later claimants get a numeric suffix."""

    def __init__(self) -> None:
        self._taken: Set[str] = set()

    def claim(self, name: str) -> str:
        """Reserve ``name`` (or ``name2``, ``name3`` … when taken) and return what was reserved."""
        candidate, suffix = name, 2
        while candidate in self._taken:
            candidate, suffix = f"{name}{suffix}", suffix + 1
        self._taken.add(candidate)
        return candidate


class XsdSchemaWriter:
    """Writes one model's types into an ``xsd:schema`` (single use per export).

    Args:
        api: The model being exported.
        target_namespace: The schema's ``targetNamespace`` (``tns:``).
        target_label: The export target's label, used in loss messages (``"WSDL"``, ``"WADL"``).
        losses: Where renames and constructs XSD cannot carry are recorded.
        tracker: Provenance for the types and fields written.
        skip_types: Type keys the caller writes itself (a WSDL source's multi-part messages).
    """

    def __init__(
        self,
        api: CanonicalApi,
        *,
        target_namespace: str,
        target_label: str,
        losses: LossTracker,
        tracker: ProvenanceTracker,
        skip_types: FrozenSet[str] = frozenset(),
    ) -> None:
        self._api = api
        self.target_namespace = target_namespace
        self._label = target_label
        self.losses = losses
        self.tracker = tracker
        self._skip = skip_types
        self._types_by_key = {t.key: t for t in api.types}
        #: Global element names (one symbol space for every element the export declares).
        self.element_scope = NameScope()
        #: Type key → the legal name the type is written under.
        self.type_names: Dict[str, str] = {}
        #: Type key → the global element declared for it (complex types only).
        self.type_elements: Dict[str, str] = {}
        self._schema_el: Optional[ET.Element] = None
        self._simple_types_written: Set[str] = set()
        type_scope = NameScope()
        for type_ in api.types:
            if type_.key in skip_types:
                continue
            name = type_scope.claim(ncname(type_.name, pascal=True, fallback="Type"))
            self.type_names[type_.key] = self.rename(type_.name, name, type_.key, "type")

    # ------------------------------------------------------------------
    # Names
    # ------------------------------------------------------------------

    def rename(self, source: Optional[str], emitted: str, pointer: str, noun: str) -> str:
        """Report ``source`` → ``emitted`` when they differ, and return ``emitted``."""
        if source != emitted:
            self.losses.record(
                LossKind.INFERRED,
                "renamed-identifier",
                f"{self._label} {noun} names must be XML NCNames; {source!r} is written as {emitted!r}.",
                pointer=pointer,
            )
        return emitted

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def new_schema(self) -> ET.Element:
        """The empty ``xsd:schema`` element, with ``targetNamespace`` and ``xmlns:tns`` declared."""
        schema_el = ET.Element(
            ET.QName(XSD_NS, "schema"),
            # `tns:` appears only in attribute values, which ElementTree never declares itself.
            {"targetNamespace": self.target_namespace, f"xmlns:{TNS_PREFIX}": self.target_namespace},
        )
        self._schema_el = schema_el
        return schema_el

    def append_types(self, schema_el: ET.Element) -> None:
        """Write every type (and a global element for each complex one) into ``schema_el``."""
        self._schema_el = schema_el
        for type_ in self._api.types:
            if type_.key in self._skip:
                continue
            if self.append_type(schema_el, type_):
                name = self.type_names[type_.key]
                element = self.element_scope.claim(name)
                ET.SubElement(
                    schema_el, ET.QName(XSD_NS, "element"), {"name": element, "type": f"{TNS_PREFIX}:{name}"}
                )
                self.type_elements[type_.key] = element

    def append_type(self, schema_el: ET.Element, type_: Type) -> bool:
        """Write one named type; return whether it is a complex type (and so gets an element)."""
        name = self.type_names[type_.key]
        self.tracker.record(type_.key, Provenance.SOURCE)
        if type_.kind is TypeKind.ENUM:
            self._append_enum(schema_el, type_, name)
            return False
        if type_.kind is TypeKind.SCALAR:
            fmt = type_.constraints.format if type_.constraints is not None else None
            base = xsd_builtin(type_.name, fmt) or "string"
            simple = ET.SubElement(schema_el, ET.QName(XSD_NS, "simpleType"), {"name": name})
            annotate(simple, type_.description)
            _append_facets(
                ET.SubElement(simple, ET.QName(XSD_NS, "restriction"), {"base": f"{XSD_PREFIX}:{base}"}),
                type_.constraints,
                base,
            )
            return False
        if type_.kind is TypeKind.ALIAS and type_.aliased is not None:
            return self._append_alias(schema_el, type_, name)
        complex_el = ET.SubElement(schema_el, ET.QName(XSD_NS, "complexType"), {"name": name})
        annotate(complex_el, type_.description)
        if type_.kind is TypeKind.UNION:
            choice = ET.SubElement(complex_el, ET.QName(XSD_NS, "choice"))
            self._append_union_members(choice, type_)
        elif type_.kind is TypeKind.MAP:
            self._append_map_body(complex_el, type_)
        else:
            sequence_el = ET.SubElement(complex_el, ET.QName(XSD_NS, "sequence"))
            scope = NameScope()
            for field in sorted(type_.fields, key=lambda f: f.field_number or 0):
                self.append_field(sequence_el, field, scope)
        return True

    def _append_enum(self, schema_el: ET.Element, type_: Type, name: str) -> None:
        """An enum: a ``simpleType`` restricting ``xs:int`` (all-integer values) or ``xs:string``."""
        values = [v.value if v.value is not None else v.name for v in type_.enum_values]
        integral = bool(values) and all(isinstance(v, int) and not isinstance(v, bool) for v in values)
        simple = ET.SubElement(schema_el, ET.QName(XSD_NS, "simpleType"), {"name": name})
        annotate(simple, type_.description)
        restriction = ET.SubElement(
            simple, ET.QName(XSD_NS, "restriction"), {"base": f"{XSD_PREFIX}:{'int' if integral else 'string'}"}
        )
        for value in values:
            ET.SubElement(restriction, ET.QName(XSD_NS, "enumeration"), {"value": _literal(value)})

    def _append_alias(self, schema_el: ET.Element, type_: Type, name: str) -> bool:
        """An alias: a derived simple type, a list wrapper, or an extension of a complex type."""
        aliased = type_.aliased
        target = self._types_by_key.get(aliased.name or "") if aliased.item is None else None
        builtin = None if target is not None or aliased.item is not None else xsd_builtin(aliased.name)
        if builtin is not None or (target is not None and self.is_simple(target)):
            simple = ET.SubElement(schema_el, ET.QName(XSD_NS, "simpleType"), {"name": name})
            annotate(simple, type_.description)
            base = f"{XSD_PREFIX}:{builtin}" if builtin else f"{TNS_PREFIX}:{self.type_names[target.key]}"
            ET.SubElement(simple, ET.QName(XSD_NS, "restriction"), {"base": base})
            return False
        complex_el = ET.SubElement(schema_el, ET.QName(XSD_NS, "complexType"), {"name": name})
        annotate(complex_el, type_.description)
        if target is not None:
            content = ET.SubElement(complex_el, ET.QName(XSD_NS, "complexContent"))
            ET.SubElement(
                content, ET.QName(XSD_NS, "extension"), {"base": f"{TNS_PREFIX}:{self.type_names[target.key]}"}
            )
        else:
            sequence_el = ET.SubElement(complex_el, ET.QName(XSD_NS, "sequence"))
            self.append_value(sequence_el, "item", aliased, pointer=type_.key, optional=False)
        return True

    def _append_union_members(self, choice: ET.Element, type_: Type) -> None:
        """A union's ``xs:choice``: its fields (a oneof), else one element per member type."""
        scope = NameScope()
        if type_.fields:
            for field in type_.fields:
                self.append_field(choice, field, scope, in_choice=True)
            return
        for member in type_.union_members:
            target = self._types_by_key.get(member)
            local = target.name if target is not None else member.split(".")[-1]
            element = scope.claim(ncname(local[:1].lower() + local[1:], fallback="variant"))
            self.append_value(choice, element, TypeRef(name=member), pointer=type_.key, optional=False)

    def _append_map_body(self, complex_el: ET.Element, type_: Type) -> None:
        """A map: a sequence of ``entry`` elements, each a ``key`` and a ``value``."""
        self.losses.record(
            LossKind.INFERRED,
            "map-as-entry-list",
            f"Map {type_.key!r} is written as a list of key/value entry elements.",
            pointer=type_.key,
        )
        sequence_el = ET.SubElement(complex_el, ET.QName(XSD_NS, "sequence"))
        entry = ET.SubElement(
            sequence_el, ET.QName(XSD_NS, "element"), {"name": "entry", "minOccurs": "0", "maxOccurs": "unbounded"}
        )
        entry_sequence = anonymous_sequence(entry)
        self.append_value(
            entry_sequence, "key", type_.key_type or TypeRef(name="string"), pointer=type_.key, optional=False
        )
        self.append_value(
            entry_sequence, "value", type_.value_type or TypeRef(name="string"), pointer=type_.key, optional=False
        )

    # ------------------------------------------------------------------
    # Fields and values
    # ------------------------------------------------------------------

    def append_field(
        self, parent: ET.Element, field: CanonicalField, scope: NameScope, *, in_choice: bool = False
    ) -> None:
        """Write one record (or union) field as an element."""
        extras = field.extras or {}
        name = scope.claim(ncname(field.name, fallback="field"))
        self.rename(field.name, name, field.key, "element")
        if field.deprecated:
            self.losses.record(
                LossKind.NA, "deprecated-dropped",
                f"XSD has no deprecation marker; {field.key!r} is written without one.", pointer=field.key,
            )
        unsupported = unsupported_facets(field.constraints)
        if unsupported:
            self.losses.record(
                LossKind.NA, "unsupported-facet",
                f"XSD has no facet for {', '.join(unsupported)}; the rule on {field.key!r} is not written.",
                pointer=field.key,
            )
        self.tracker.record(field.key, Provenance.SOURCE)
        if "xsd_type" in extras:
            self._append_xsd_source_field(parent, field, name)
            return
        fmt = field.constraints.format if field.constraints is not None else None
        self.append_value(
            parent,
            name,
            field.type,
            fmt=fmt,
            # A WADL import records the grammar's original XSD type (`dateTime`, `decimal`).
            hint=extras.get("wadl_type"),
            constraints=field.constraints,
            default=field.default,
            description=field.description,
            optional=field.type.nullable and not in_choice,
            pointer=field.key,
        )

    def _append_xsd_source_field(self, parent: ET.Element, field: CanonicalField, name: str) -> None:
        """A field imported from XSD: written back with the occurrence and facets it was read with."""
        extras = field.extras
        attributes = {"name": name}
        facets = extras.get("xsd_facets")
        simple_type = extras.get("xsd_simple_type")
        base = extras.get("xsd_base")
        if base and simple_type:
            # A named simple type: written once at schema level, referenced by name.
            attributes["type"] = f"{TNS_PREFIX}:{simple_type}"
            if simple_type not in self._simple_types_written and self._schema_el is not None:
                self._simple_types_written.add(simple_type)
                named = ET.SubElement(self._schema_el, ET.QName(XSD_NS, "simpleType"), {"name": simple_type})
                _append_restriction(named, base, facets)
        elif not base:
            attributes["type"] = self.source_type_qname(field.type, hint=extras.get("xsd_type"))
        # MFI-13.5: the element's occurrence, nillability and default, as the source stated them.
        for key, attribute in (
            ("xsd_min_occurs", "minOccurs"),
            ("xsd_max_occurs", "maxOccurs"),
            ("xsd_nillable", "nillable"),
            ("xsd_default", "default"),
        ):
            if extras.get(key) is not None:
                attributes[attribute] = str(extras[key])
        element_el = ET.SubElement(parent, ET.QName(XSD_NS, "element"), attributes)
        if base and not simple_type:
            # An inline restriction of a built-in type.
            inline = ET.SubElement(element_el, ET.QName(XSD_NS, "simpleType"))
            _append_restriction(inline, base, facets)

    def append_value(
        self,
        parent: ET.Element,
        name: str,
        ref: TypeRef,
        *,
        pointer: str,
        optional: bool,
        fmt: Optional[str] = None,
        constraints: Optional[Constraints] = None,
        default: Any = None,
        description: Optional[str] = None,
        hint: Optional[str] = None,
    ) -> ET.Element:
        """Write ``ref`` as an element named ``name``: lists repeat, scalars keep facets.

        Args:
            parent: The ``sequence`` / ``choice`` the element joins.
            name: The element's (legal) name.
            ref: Its type.
            pointer: The construct key, for loss records.
            optional: Write ``minOccurs="0" nillable="true"`` (a nullable value).
            fmt: The ``format`` that picks a scalar's XSD type.
            constraints: Facets to write (and, for lists, ``minItems``/``maxItems``).
            default: A scalar default (``default`` attribute).
            description: Written as ``xs:annotation``.
            hint: An XSD type an XML import recorded for the value; wins when it is a built-in.

        Returns:
            The element written.
        """
        attributes: Dict[str, str] = {"name": name}
        if ref.item is not None:
            attributes["minOccurs"] = str(constraints.min_items) if constraints and constraints.min_items else "0"
            attributes["maxOccurs"] = (
                str(constraints.max_items) if constraints and constraints.max_items else "unbounded"
            )
            if ref.item.item is not None:
                # A list of lists: XSD has no nested occurrence, so the inner list gets a wrapper.
                element = ET.SubElement(parent, ET.QName(XSD_NS, "element"), attributes)
                annotate(element, description)
                inner = anonymous_sequence(element)
                self.append_value(inner, "item", ref.item, pointer=pointer, optional=False, fmt=fmt, hint=hint)
                return element
            attributes["type"] = self.type_qname(ref.item, fmt, pointer, hint=hint)
            element = ET.SubElement(parent, ET.QName(XSD_NS, "element"), attributes)
            annotate(element, description)
            return element
        if optional:
            attributes["minOccurs"] = "0"
            attributes["nillable"] = "true"
        builtin = self.builtin(ref, fmt, hint=hint)
        if default is not None and builtin is not None and not isinstance(default, (dict, list)):
            attributes["default"] = _literal(default)
        if builtin is not None and _has_facets(constraints, builtin):
            element = ET.SubElement(parent, ET.QName(XSD_NS, "element"), attributes)
            annotate(element, description)
            restriction = ET.SubElement(
                ET.SubElement(element, ET.QName(XSD_NS, "simpleType")),
                ET.QName(XSD_NS, "restriction"),
                {"base": f"{XSD_PREFIX}:{builtin}"},
            )
            _append_facets(restriction, constraints, builtin)
            return element
        attributes["type"] = self.type_qname(ref, fmt, pointer, hint=hint)
        element = ET.SubElement(parent, ET.QName(XSD_NS, "element"), attributes)
        annotate(element, description)
        return element

    def wrapper(self, schema_el: ET.Element, name: str) -> ET.Element:
        """A global element with an anonymous ``complexType``; returns its ``sequence``."""
        return anonymous_sequence(ET.SubElement(schema_el, ET.QName(XSD_NS, "element"), {"name": name}))

    # ------------------------------------------------------------------
    # Type references
    # ------------------------------------------------------------------

    def is_simple(self, type_: Type) -> bool:
        """Whether a named type is written as an XSD ``simpleType``."""
        if type_.kind in (TypeKind.ENUM, TypeKind.SCALAR):
            return True
        if type_.kind is TypeKind.ALIAS and type_.aliased is not None and type_.aliased.item is None:
            target = self._types_by_key.get(type_.aliased.name or "")
            if target is None:
                return xsd_builtin(type_.aliased.name) is not None
            return target is not type_ and self.is_simple(target)
        return False

    def builtin(self, ref: TypeRef, fmt: Optional[str], *, hint: Optional[str] = None) -> Optional[str]:
        """The XSD built-in ``ref`` maps to (an imported ``hint`` wins), or ``None`` for a named type."""
        if not ref.name or ref.name in self.type_names:
            return None
        return xsd_builtin(ref.name, fmt, xsd_hint=hint)

    def type_qname(self, ref: TypeRef, fmt: Optional[str], pointer: str, *, hint: Optional[str] = None) -> str:
        """The ``type=`` value for ``ref``: ``tns:<Type>``, ``xsd:<builtin>`` or a fallback."""
        if ref.item is not None:
            # Only reached for a list nested where XSD has no slot; carried as any content.
            return f"{XSD_PREFIX}:anyType"
        if not ref.name:
            self.losses.record(
                LossKind.INFERRED, "untyped-value",
                f"{pointer!r} has no declared type; it is written as xs:anyType.", pointer=pointer,
            )
            return f"{XSD_PREFIX}:anyType"
        if ref.name in self.type_names:
            return f"{TNS_PREFIX}:{self.type_names[ref.name]}"
        builtin = xsd_builtin(ref.name, fmt, xsd_hint=hint)
        if builtin is not None:
            return f"{XSD_PREFIX}:{builtin}"
        self.losses.record(
            LossKind.INFERRED, "unmapped-type",
            f"{ref.name!r} is not an XSD type or a type in this model; it is written as xs:string.",
            pointer=pointer,
        )
        return f"{XSD_PREFIX}:string"

    def source_type_qname(self, ref: TypeRef, *, hint: Optional[str] = None) -> str:
        """The ``type=`` value for a field or part imported from XML (keeps imported names)."""
        if ref.name:
            mapped = xsd_builtin(ref.name, xsd_hint=hint) if hint else None
            if mapped:
                return f"{XSD_PREFIX}:{mapped}"
            if ref.name in self.type_names:
                return f"{TNS_PREFIX}:{self.type_names[ref.name]}"
            mapped = xsd_builtin(ref.name)
            if mapped:
                return f"{XSD_PREFIX}:{mapped}"
            return f"{TNS_PREFIX}:{ref.name.split('.')[-1]}"
        return f"{XSD_PREFIX}:string"


# ---------------------------------------------------------------------------
# Predicted verdicts (for the XML targets' fidelity rule packs)
# ---------------------------------------------------------------------------


def target_namespace_verdicts(
    api: CanonicalApi, *, target_label: str, namespace: str, source_has_own: bool
) -> List[FidelityVerdict]:
    """The root verdict naming the target namespace every type and element is qualified by.

    Args:
        api: The model being exported.
        target_label: ``"WSDL"`` / ``"WADL"``.
        namespace: The namespace the export uses.
        source_has_own: The source is the same format and carries its own namespace — nothing
            changes, so there is no verdict.

    Returns:
        ``[]``, an info ``APPROX`` (the source's namespace is used) or an info ``SYNTH`` (invented).
    """
    if source_has_own:
        return []
    if api.identity.namespace:
        return [
            FidelityVerdict.approx(
                message=f"{target_label} qualifies every type, element and operation by a target namespace; "
                f"the source namespace {namespace!r} is used",
                severity=LossinessSeverity.INFO,
                target_mapping=f"names → {namespace}",
            )
        ]
    return [
        FidelityVerdict.synth(
            message=f"{target_label} requires a target namespace and the source has none; {namespace!r} is used, "
            "and every type, element and operation is qualified by it",
            severity=LossinessSeverity.INFO,
            target_mapping=f"targetNamespace → {namespace}",
        )
    ]


def schema_type_verdict(type_: Type, *, target_label: str) -> Optional[FidelityVerdict]:
    """A map written as an entry list, or a type renamed to a legal name; ``None`` otherwise."""
    if type_.kind is TypeKind.MAP:
        return FidelityVerdict.approx(
            message="XSD has no map type; the map is written as a list of key/value entry elements",
            severity=LossinessSeverity.INFO,
            target_mapping="map → sequence of entry",
        )
    return rename_verdict(
        type_.name, ncname(type_.name, pascal=True, fallback="Type"), target_label=target_label, noun="type"
    )


def schema_field_verdicts(field: CanonicalField, *, target_label: str) -> List[FidelityVerdict]:
    """Everything XSD changes or cannot carry about one field (rename, untyped, facets, deprecated)."""
    verdicts: List[FidelityVerdict] = []
    renamed = rename_verdict(
        field.name, ncname(field.name, fallback="field"), target_label=target_label, noun="element"
    )
    if renamed:
        verdicts.append(renamed)
    if field.type.name is None and field.type.item is None:
        verdicts.append(
            FidelityVerdict.approx(
                message="The field has no declared type; it is written as xs:anyType",
                severity=LossinessSeverity.INFO,
                target_mapping="untyped → xs:anyType",
            )
        )
    unsupported = unsupported_facets(field.constraints)
    if unsupported:
        verdicts.append(
            FidelityVerdict.approx(
                message=f"XSD has no facet for {', '.join(unsupported)}; the rule is not written",
                target_mapping=f"{', '.join(unsupported)} → dropped",
            )
        )
    if field.deprecated:
        verdicts.append(
            FidelityVerdict.drop(
                message="XSD has no deprecation marker; the field's deprecated flag is dropped",
                severity=LossinessSeverity.INFO,
            )
        )
    return verdicts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def unsupported_facets(constraints: Optional[Constraints]) -> List[str]:
    """Constraint keywords XSD has no facet for (and patterns it cannot express)."""
    if constraints is None:
        return []
    names = []
    if constraints.multiple_of is not None:
        names.append("multipleOf")
    if constraints.unique_items:
        names.append("uniqueItems")
    if constraints.pattern and xsd_pattern(constraints.pattern) is None:
        names.append(f"the pattern {constraints.pattern!r}")
    return names


def _facets(constraints: Constraints, base: str) -> List[Tuple[str, Any]]:
    """The ``(facet, value)`` pairs ``constraints`` maps to on a restriction of ``base``."""
    pairs: List[Tuple[str, Any]] = []
    if base in _LENGTH_BASES:
        if constraints.min_length is not None:
            pairs.append(("minLength", constraints.min_length))
        if constraints.max_length is not None:
            pairs.append(("maxLength", constraints.max_length))
    if base in _RANGE_BASES:
        for facet, value in (
            ("minInclusive", constraints.minimum),
            ("maxInclusive", constraints.maximum),
            ("minExclusive", constraints.exclusive_minimum),
            ("maxExclusive", constraints.exclusive_maximum),
        ):
            if value is not None:
                pairs.append((facet, value))
    if constraints.pattern and xsd_pattern(constraints.pattern) is not None:
        pairs.append(("pattern", xsd_pattern(constraints.pattern)))
    for value in constraints.enum or []:
        if value is not None and not isinstance(value, (dict, list)):
            pairs.append(("enumeration", value))
    return pairs


def _has_facets(constraints: Optional[Constraints], base: str) -> bool:
    return constraints is not None and bool(_facets(constraints, base))


def _append_facets(restriction: ET.Element, constraints: Optional[Constraints], base: str) -> None:
    """Write the restriction facets ``base`` accepts; the order is free in XSD 1.0."""
    if constraints is None:
        return
    for facet, value in _facets(constraints, base):
        ET.SubElement(restriction, ET.QName(XSD_NS, facet), {"value": _literal(value)})


def _append_restriction(simple_type_el: ET.Element, base: str, facets: Any) -> None:
    """Write ``<xs:restriction base="xs:<base>">`` with its facets under a ``simpleType``."""
    restriction = ET.SubElement(simple_type_el, ET.QName(XSD_NS, "restriction"), {"base": f"{XSD_PREFIX}:{base}"})
    for facet, value in (facets or {}).items():
        for item in value if isinstance(value, list) else [value]:
            ET.SubElement(restriction, ET.QName(XSD_NS, facet), {"value": str(item)})


def _literal(value: Any) -> str:
    """A facet, enumeration or default value as XSD writes it (``true``, ``5``, ``2.5``)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    return str(value)


def anonymous_sequence(element: ET.Element) -> ET.Element:
    """Give ``element`` an anonymous ``complexType`` and return that type's ``sequence``."""
    return ET.SubElement(ET.SubElement(element, ET.QName(XSD_NS, "complexType")), ET.QName(XSD_NS, "sequence"))


def annotate(element: ET.Element, description: Optional[str]) -> None:
    """Add ``<xs:annotation><xs:documentation>`` (it must be the element's first child)."""
    if description:
        annotation = ET.SubElement(element, ET.QName(XSD_NS, "annotation"))
        ET.SubElement(annotation, ET.QName(XSD_NS, "documentation")).text = description


def comment_safe(text: str) -> str:
    """Text that cannot end an XML comment early (``--`` is not allowed inside one)."""
    return text.replace("--", "- -")
