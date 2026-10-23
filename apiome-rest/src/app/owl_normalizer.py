"""OWL / RDFS ontology → canonical model — FMT-9.4 (#5471).

Reads an OWL or RDFS ontology (Turtle, RDF/XML or JSON-LD, one file or an ``owl:imports`` fileset,
loaded by :mod:`app.rdf_graph`) onto the **data_schema** paradigm:

.. code-block:: text

    ex:Customer a owl:Class ; rdfs:subClassOf ex:Agent   → RECORD Customer (Agent's fields inherited)
    ex:orderId a owl:DatatypeProperty ; rdfs:domain ex:Order ; rdfs:range xsd:string
                                                         → field  Order.orderId : string
    ex:placedBy a owl:ObjectProperty ; rdfs:range ex:Customer
                                                         → field  Order.placedBy : Customer
    ex:Colour owl:oneOf ( ex:Red ex:Green )              → ENUM   Colour
    ex:Sellable owl:unionOf ( ex:Widget ex:Gadget )      → UNION  Sellable
    ex:Percentage a rdfs:Datatype ; owl:withRestrictions → ALIAS  Percentage (decimal, 0–100)

A property becomes a field of every class in its ``rdfs:domain`` (a sub-property inherits its
super-property's domain and range) and of every class that restricts it. Cardinality follows OWL:
a property is multi-valued (a list) unless it is ``owl:FunctionalProperty`` or a restriction caps it
at one; ``owl:cardinality`` / ``owl:minCardinality`` / ``owl:maxCardinality`` (qualified or not) set
``min_items`` / ``max_items`` and a minimum of one makes the field required. Named superclasses are
inheritance: a subclass carries its superclasses' fields (``extras['owl_inherited_from']``).

**OWL is open-world; Apiome's model is closed-world.** An ontology's inferred consequences are not
imported, and every import declares that (``owl.open_world``). The axioms that only drive
inference — class expressions, quantified restrictions, property characteristics and chains,
equivalence, disjointness, individual identity — are kept in ``extras`` under ``owl_*`` keys and
declared in ``extras['owl']['capability_limits']``, never approximated as structure.

Refusals (raised while reading): an ontology with no classes, properties, datatypes or individuals
(``INPUT_SEMANTIC_INVALID``, or ``FORMAT_MISMATCH`` for a SHACL shapes graph) and, from the loader,
an ``owl:imports`` the upload does not contain (``INPUT_REFERENCE_UNRESOLVED``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Set, Tuple

from rdflib import BNode, Literal, URIRef

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
from .fileset import IntakeFileset
from .inference_provenance import INFERRED, provenance_extras
from .normalizer import Keys, Normalizer, normalize_ordering
from .rdf_graph import (
    DCT,
    OWL,
    RDF,
    RDFS,
    SKOS,
    XSD,
    RdfDocument,
    RdfParseError,
    assign_type_keys,
    datatype_ref_name,
    literal_text,
    literal_value,
    load_rdf_document,
    local_name,
    read_list,
)
from .shacl_normalizer import has_shacl_vocabulary
from .typescript_types_normalizer import _limits_payload
from .typescript_types_parser import LimitRecorder

__all__ = [
    "FORMAT_KEY",
    "LIMIT_DETAILS",
    "OWL_EXTRAS_KEY",
    "OwlDocument",
    "OwlNormalizer",
    "PARTIAL_LIMITS",
    "read_owl",
]

#: Adapter and canonical format key.
FORMAT_KEY = "owl"

#: Root extras key of the projection record.
OWL_EXTRAS_KEY = "owl"

#: The declared-limit vocabulary (stable keys → reviewed sentence).
LIMIT_DETAILS: Dict[str, str] = {
    "owl.open_world": (
        "OWL is open-world and inference-driven; Apiome's model is closed-world. The ontology's "
        "asserted classes and properties are imported as types and fields; its inferred "
        "consequences (entailed subclasses, types and property values) are not."
    ),
    "owl.class_expression": (
        "A class defined by owl:unionOf / owl:intersectionOf / owl:complementOf is kept as a named "
        "type (a union of the named members, or a record of the intersected members' fields); the "
        "class expression's logical meaning is kept in extras['owl_class_expression']."
    ),
    "owl.quantified_restriction": (
        "owl:someValuesFrom / owl:allValuesFrom / owl:hasValue restrictions quantify over an "
        "open world; the restricted property is a field and the restriction is kept in "
        "extras['owl_restrictions']."
    ),
    "owl.property_characteristic": (
        "Transitive, symmetric, asymmetric, reflexive, irreflexive and inverse-functional "
        "properties license inferences, not structure; the characteristic is kept in "
        "extras['owl_characteristics']."
    ),
    "owl.property_chain": (
        "owl:propertyChainAxiom defines a property by composition for a reasoner; it is kept in "
        "extras['owl_property_chain'] and not modelled."
    ),
    "owl.inverse_property": (
        "owl:inverseOf pairs two properties for inference; both are fields and the pairing is kept "
        "in extras['owl_inverse_of']."
    ),
    "owl.class_equivalence": (
        "owl:equivalentClass states that two classes have the same members, an inference axiom; it "
        "is kept in extras['owl_equivalent_class']."
    ),
    "owl.disjointness": (
        "owl:disjointWith states that no individual is in both classes; the canonical model has no "
        "such constraint, so it is kept in extras['owl_disjoint_with']."
    ),
    "owl.individual_identity": (
        "owl:sameAs / owl:differentFrom assert identity between individuals in an open world; they "
        "are kept in extras['owl']['individual_identity'] and not modelled."
    ),
    "owl.individual_enumeration": (
        "The class lists named individuals but is not closed with owl:oneOf; under OWL more members "
        "may exist. Apiome lists the asserted individuals as the members of an enum."
    ),
    "owl.external_reference": (
        "A superclass, domain or range names a class this import does not define (a vocabulary "
        "outside the upload). A range keeps an IRI-valued string; the class is named in extras."
    ),
    "owl.property_without_domain": (
        "A property has no rdfs:domain and no class restricts it, so it is attached to no type; it "
        "is listed in extras['owl']['unattached_properties']."
    ),
    "owl.external_import": (
        "owl:imports names a well-known vocabulary that is not part of the upload; its terms are "
        "referenced by IRI, not imported."
    ),
}

#: Limits whose construct is still modelled, with only a detail lost.
PARTIAL_LIMITS = frozenset(
    {
        "owl.class_expression",
        "owl.quantified_restriction",
        "owl.inverse_property",
        "owl.individual_enumeration",
        "owl.external_reference",
        "owl.external_import",
    }
)

#: Built-in vocabularies whose classes are never imported as types.
_BUILTIN_NAMESPACES = (str(OWL), str(RDF), str(RDFS), str(XSD))

_CLASS_TYPES = (OWL.Class, RDFS.Class)
_PROPERTY_TYPES = (OWL.ObjectProperty, OWL.DatatypeProperty, RDF.Property, OWL.FunctionalProperty)
_CHARACTERISTICS = (
    OWL.TransitiveProperty,
    OWL.SymmetricProperty,
    OWL.AsymmetricProperty,
    OWL.ReflexiveProperty,
    OWL.IrreflexiveProperty,
    OWL.InverseFunctionalProperty,
)
_EXACT = (OWL.cardinality, OWL.qualifiedCardinality)
_MINIMUM = (OWL.minCardinality, OWL.minQualifiedCardinality)
_MAXIMUM = (OWL.maxCardinality, OWL.maxQualifiedCardinality)
_FACETS = (
    (XSD.minInclusive, "minimum"),
    (XSD.maxInclusive, "maximum"),
    (XSD.minExclusive, "exclusive_minimum"),
    (XSD.maxExclusive, "exclusive_maximum"),
    (XSD.minLength, "min_length"),
    (XSD.maxLength, "max_length"),
    (XSD.pattern, "pattern"),
)

_ENUMERATION_EVIDENCE = (
    "OWL does not close a class over the individuals asserted in it; the enum lists the ones this ontology names."
)


@dataclass
class OwlDocument:
    """A validated OWL / RDFS ontology.

    Attributes:
        rdf: The loaded graph and its sources.
        classes: Named classes, sorted by IRI.
        datatypes: Named ``rdfs:Datatype`` s, sorted by IRI.
        properties: Object, datatype and RDF properties, sorted by IRI.
    """

    rdf: RdfDocument
    classes: Tuple[URIRef, ...]
    datatypes: Tuple[URIRef, ...]
    properties: Tuple[URIRef, ...]


def _is_builtin(node: Any) -> bool:
    """Whether ``node`` is in the OWL, RDF, RDFS or XSD namespace."""
    return str(node).startswith(_BUILTIN_NAMESPACES)


def _iri_subjects(graph: Any, types: Any) -> Set[URIRef]:
    """Every IRI subject typed with one of ``types``, built-in vocabulary excluded."""
    return {s for t in types for s in graph.subjects(RDF.type, t) if isinstance(s, URIRef) and not _is_builtin(s)}


def read_owl(text: Optional[str] = None, *, label: str, fileset: Optional[IntakeFileset] = None) -> OwlDocument:
    """Load and validate an OWL / RDFS ontology (one file or an ``owl:imports`` fileset).

    Raises:
        RdfParseError: With the taxonomy code of the failure — a syntax, encoding or import fault,
            or no vocabulary to import (``INPUT_SEMANTIC_INVALID`` / ``FORMAT_MISMATCH``).
    """
    rdf = load_rdf_document(text, label=label, fileset=fileset)
    graph = rdf.graph
    datatypes = _iri_subjects(graph, (RDFS.Datatype,))
    classes = (
        _iri_subjects(graph, _CLASS_TYPES)
        | {s for s in graph.subjects(RDFS.subClassOf, None) if isinstance(s, URIRef) and not _is_builtin(s)}
    ) - datatypes
    properties = _iri_subjects(graph, _PROPERTY_TYPES)
    if not classes and not properties and not datatypes:
        if has_shacl_vocabulary(graph):
            raise RdfParseError(
                f"{label} is a SHACL shapes graph, not an OWL / RDFS ontology: it declares "
                "sh:NodeShape constraints but no owl:Class or property. Import it as SHACL shapes.",
                code="FORMAT_MISMATCH",
            )
        raise RdfParseError(
            f"{label} declares no classes, properties or datatypes (an ontology header alone has no "
            "vocabulary to import).",
            code="INPUT_SEMANTIC_INVALID",
        )
    return OwlDocument(
        rdf=rdf,
        classes=tuple(sorted(classes, key=str)),
        datatypes=tuple(sorted(datatypes, key=str)),
        properties=tuple(sorted(properties, key=str)),
    )


def _count(node: Any) -> Optional[int]:
    """A cardinality literal as ``int``, or ``None``."""
    if isinstance(node, Literal):
        value = node.toPython()
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        try:
            return int(str(node))
        except ValueError:
            return None
    return None


def _facet_value(node: Any) -> Any:
    """A datatype facet value as a JSON-safe number or string."""
    value = node.toPython() if isinstance(node, Literal) else node
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return str(node)


@dataclass
class _Restriction:
    """One ``owl:Restriction`` a class carries on a property."""

    on_property: Any
    min_count: Optional[int] = None
    max_count: Optional[int] = None
    filler: Any = None
    quantified: Optional[Dict[str, Any]] = None


def _merge_restrictions(found: List[_Restriction]) -> List[_Restriction]:
    """One restriction per property: cardinalities, filler and quantifiers of every restriction on it.

    A class may restrict one property several times (``someValuesFrom`` beside ``allValuesFrom``);
    the field it becomes carries all of them, so they are merged — in a stable order, independent of
    the graph's iteration order.
    """
    merged: Dict[str, _Restriction] = {}
    for restriction in found:
        key = str(restriction.on_property)
        current = merged.setdefault(key, _Restriction(on_property=restriction.on_property))
        if restriction.min_count is not None:
            current.min_count = max(current.min_count or 0, restriction.min_count)
        if restriction.max_count is not None:
            current.max_count = (
                restriction.max_count if current.max_count is None else min(current.max_count, restriction.max_count)
            )
        if restriction.filler is not None and (current.filler is None or str(restriction.filler) < str(current.filler)):
            current.filler = restriction.filler
        if restriction.quantified:
            current.quantified = dict(sorted({**(current.quantified or {}), **restriction.quantified}.items()))
    return [merged[key] for key in sorted(merged)]


class _Builder:
    """Accumulates types and limits while one ontology is normalized."""

    def __init__(self, document: OwlDocument) -> None:
        """Assign type keys and index the ontology's classes, datatypes and properties."""
        self.document = document
        self.rdf = document.rdf
        self.graph = document.rdf.graph
        self.types: Dict[str, Type] = {}
        self.limits = LimitRecorder(details=LIMIT_DETAILS)
        self.keys: Dict[Any, str] = assign_type_keys(self.rdf, list(document.classes) + list(document.datatypes))
        self.classes = set(document.classes)
        self.datatypes = set(document.datatypes)
        self.properties = set(document.properties)
        self._fields: Dict[Any, List[CanonicalField]] = {}
        self._unattached: List[str] = []
        self._attached: Set[Any] = set()

    # --- property facts --------------------------------------------------------------------

    def _super_properties(self, prop: Any) -> List[Any]:
        """``prop``'s super-properties, nearest first, cycle-safe."""
        chain: List[Any] = []
        pending = sorted(self.graph.objects(prop, RDFS.subPropertyOf), key=str)
        while pending:
            parent = pending.pop(0)
            if parent in chain or parent == prop:
                continue
            chain.append(parent)
            pending.extend(sorted(self.graph.objects(parent, RDFS.subPropertyOf), key=str))
        return chain

    def _inherited_value(self, prop: Any, predicate: Any) -> List[Any]:
        """``prop``'s own values of ``predicate``, else the nearest super-property's."""
        for holder in [prop] + self._super_properties(prop):
            values = sorted(self.graph.objects(holder, predicate), key=lambda n: (isinstance(n, BNode), str(n)))
            if values:
                return values
        return []

    def domains(self, prop: Any) -> List[Any]:
        """The named classes in ``prop``'s domain (a union domain contributes its named members)."""
        named: List[Any] = []
        for domain in self._inherited_value(prop, RDFS.domain):
            members = (
                read_list(self.graph, self.graph.value(domain, OWL.unionOf)) if isinstance(domain, BNode) else [domain]
            )
            named.extend(m for m in members if isinstance(m, URIRef))
        return named

    def is_object_property(self, prop: Any) -> bool:
        """Whether ``prop`` relates individuals.

        True for an ``owl:ObjectProperty`` (or a sub-property of one), or a property whose range is
        a class of the import.
        """
        graph = self.graph
        if (prop, RDF.type, OWL.ObjectProperty) in graph:
            return True
        if any((parent, RDF.type, OWL.ObjectProperty) in graph for parent in self._super_properties(prop)):
            return True
        # An RDFS ``rdf:Property`` says neither; a range that is one of the import's classes does.
        return any(r in self.classes for r in self._inherited_value(prop, RDFS.range))

    def is_functional(self, prop: Any) -> bool:
        """Whether ``prop`` is declared ``owl:FunctionalProperty``."""
        return (prop, RDF.type, OWL.FunctionalProperty) in self.graph

    # --- restrictions ----------------------------------------------------------------------

    def restrictions(self, cls: Any) -> List[_Restriction]:
        """The restrictions ``cls`` declares through ``rdfs:subClassOf`` (or an intersection)."""
        graph = self.graph
        nodes = [n for n in graph.objects(cls, RDFS.subClassOf) if isinstance(n, BNode)]
        for holder in graph.objects(cls, OWL.intersectionOf):
            nodes.extend(n for n in read_list(graph, holder) if isinstance(n, BNode))
        found: List[_Restriction] = []
        for node in nodes:
            on_property = graph.value(node, OWL.onProperty)
            if on_property is None:
                continue
            restriction = _Restriction(on_property=on_property)
            for predicate in _EXACT:
                value = _count(graph.value(node, predicate))
                if value is not None:
                    restriction.min_count = restriction.max_count = value
            for predicate in _MINIMUM:
                value = _count(graph.value(node, predicate))
                if value is not None:
                    restriction.min_count = value
            for predicate in _MAXIMUM:
                value = _count(graph.value(node, predicate))
                if value is not None:
                    restriction.max_count = value
            restriction.filler = graph.value(node, OWL.onClass) or graph.value(node, OWL.onDataRange)
            for predicate, name in (
                (OWL.someValuesFrom, "someValuesFrom"),
                (OWL.allValuesFrom, "allValuesFrom"),
                (OWL.hasValue, "hasValue"),
            ):
                value = graph.value(node, predicate)
                if value is not None:
                    restriction.quantified = {
                        name: literal_value(value) if isinstance(value, Literal) else self.rdf.compact(value)
                    }
            found.append(restriction)
        return _merge_restrictions(found)

    # --- value types -----------------------------------------------------------------------

    def range_ref(self, prop: Any, filler: Any, location: str) -> Tuple[str, Optional[str], Dict[str, Any]]:
        """The canonical type of ``prop``'s values: ``(name, format, extras)``."""
        ranges = [filler] if filler is not None else self._inherited_value(prop, RDFS.range)
        target = next((r for r in ranges if isinstance(r, URIRef)), None)
        extras: Dict[str, Any] = {}
        if target is None:
            if self.is_object_property(prop):
                return "string", "iri", extras
            return "any", None, extras
        extras["owl_range"] = self.rdf.compact(target)
        if target in self.keys:
            return self.keys[target], None, extras
        scalar, fmt = datatype_ref_name(target)
        if scalar is not None:
            return scalar, fmt, extras
        if target == OWL.Thing:
            return "string", "iri", extras
        self.limits.record("owl.external_reference", location=location)
        return "string", "iri", extras

    # --- fields ----------------------------------------------------------------------------

    def field(self, cls_key: str, prop: Any, restriction: Optional[_Restriction]) -> CanonicalField:
        """``prop`` as a field of the class keyed ``cls_key``."""
        graph = self.graph
        name = local_name(prop)
        key = Keys.field(cls_key, name)
        type_name, fmt, extras = self.range_ref(prop, restriction.filler if restriction else None, key)
        min_count = restriction.min_count if restriction and restriction.min_count is not None else 0
        max_count = restriction.max_count if restriction and restriction.max_count is not None else None
        if max_count is None and self.is_functional(prop):
            max_count = 1
        required = min_count >= 1
        many = max_count != 1
        element = TypeRef(name=type_name, nullable=False)
        type_ref = (
            TypeRef(item=element, nullable=not required) if many else TypeRef(name=type_name, nullable=not required)
        )
        values: Dict[str, Any] = {}
        if many and min_count:
            values["min_items"] = min_count
        if many and max_count is not None:
            values["max_items"] = max_count
        if fmt:
            values["format"] = fmt
        extras.update(
            {"native_id": str(prop), "owl_property_kind": "object" if self.is_object_property(prop) else "datatype"}
        )
        if self.is_functional(prop):
            extras["owl_functional"] = True
        if restriction is not None:
            extras["owl_restriction"] = {
                **({"minCount": restriction.min_count} if restriction.min_count is not None else {}),
                **({"maxCount": restriction.max_count} if restriction.max_count is not None else {}),
                **({"on": self.rdf.compact(restriction.filler)} if restriction.filler is not None else {}),
            }
            if restriction.quantified:
                extras["owl_restrictions"] = restriction.quantified
                self.limits.record("owl.quantified_restriction", location=key)
        self._property_axioms(prop, key, extras)
        label = literal_text(graph, prop, RDFS.label)
        if label:
            extras["rdfs_label"] = label
        return CanonicalField(
            key=key,
            name=name,
            type=type_ref,
            constraints=Constraints(**values) if values else None,
            description=literal_text(graph, prop, RDFS.comment) or literal_text(graph, prop, SKOS.definition),
            extras=extras,
        )

    def _property_axioms(self, prop: Any, location: str, extras: Dict[str, Any]) -> None:
        """The inference-only property axioms, kept in ``extras`` and declared."""
        graph = self.graph
        characteristics = [local_name(c) for c in _CHARACTERISTICS if (prop, RDF.type, c) in graph]
        if characteristics:
            extras["owl_characteristics"] = characteristics
            self.limits.record("owl.property_characteristic", location=location)
        inverse = sorted(
            {self.rdf.compact(o) for o in graph.objects(prop, OWL.inverseOf)}
            | {self.rdf.compact(s) for s in graph.subjects(OWL.inverseOf, prop)}
        )
        if inverse:
            extras["owl_inverse_of"] = inverse
            self.limits.record("owl.inverse_property", location=location)
        chains = [
            [self.rdf.compact(step) for step in read_list(graph, c)]
            for c in graph.objects(prop, OWL.propertyChainAxiom)
        ]
        if chains:
            extras["owl_property_chain"] = sorted(chains)
            self.limits.record("owl.property_chain", location=location)
        supers = [self.rdf.compact(p) for p in sorted(graph.objects(prop, RDFS.subPropertyOf), key=str)]
        if supers:
            extras["owl_sub_property_of"] = supers

    def own_fields(self, cls: Any, key: str) -> Dict[str, CanonicalField]:
        """The fields ``cls`` declares itself: properties whose domain it is, then its restrictions."""
        fields: Dict[str, CanonicalField] = {}
        restrictions = {r.on_property: r for r in self.restrictions(cls)}
        for prop in sorted(self.properties, key=str):
            if cls in self.domains(prop) or prop in restrictions:
                fields[local_name(prop)] = self.field(key, prop, restrictions.get(prop))
                self._attached.add(prop)
        for prop, restriction in restrictions.items():
            if prop not in self.properties and isinstance(prop, URIRef):
                fields[local_name(prop)] = self.field(key, prop, restriction)
        return fields

    def superclasses(self, cls: Any) -> List[Any]:
        """The named superclasses (``rdfs:subClassOf`` and the named members of an intersection)."""
        graph = self.graph
        named = [p for p in graph.objects(cls, RDFS.subClassOf) if isinstance(p, URIRef)]
        for holder in graph.objects(cls, OWL.intersectionOf):
            named.extend(m for m in read_list(graph, holder) if isinstance(m, URIRef))
        return sorted({p for p in named if p != OWL.Thing and p != cls}, key=str)

    def class_fields(self, cls: Any, chain: Tuple[Any, ...] = ()) -> List[CanonicalField]:
        """A class's fields: every superclass's (flattened, nearest last), then its own."""
        if cls in self._fields:
            return self._fields[cls]
        key = self.keys[cls]
        fields: Dict[str, CanonicalField] = {}
        for parent in self.superclasses(cls):
            if parent not in self.keys or parent in chain:
                continue
            for inherited in self.class_fields(parent, chain + (cls,)):
                extras = dict(inherited.extras)
                extras.setdefault("owl_inherited_from", self.keys[parent])
                fields[inherited.name] = inherited.model_copy(
                    update={"key": Keys.field(key, inherited.name), "extras": extras}
                )
        fields.update(self.own_fields(cls, key))
        result = list(fields.values())
        self._fields[cls] = result
        return result

    # --- types -----------------------------------------------------------------------------

    def individuals(self, cls: Any) -> List[Any]:
        """Named individuals asserted in ``cls`` (``ex:Paid a ex:OrderStatus``)."""
        graph = self.graph
        return sorted(
            (
                s
                for s in graph.subjects(RDF.type, cls)
                if isinstance(s, URIRef) and s not in self.classes and s not in self.properties
            ),
            key=str,
        )

    def _enum_values(self, key: str, members: List[Any]) -> List[EnumValue]:
        """Enum members for named individuals: local name, IRI value and preferred label."""
        graph = self.graph
        return [
            EnumValue(
                key=Keys.enum_value(key, local_name(member)),
                name=local_name(member),
                value=str(member),
                description=literal_text(graph, member, SKOS.prefLabel) or literal_text(graph, member, RDFS.label),
            )
            for member in members
        ]

    def class_extras(self, cls: Any, key: str) -> Dict[str, Any]:
        """Identity, hierarchy and the inference-only class axioms of one class."""
        graph = self.graph
        extras: Dict[str, Any] = {"native_id": str(cls)}
        source_file = self.rdf.file_of(cls)
        if source_file:
            extras["rdf_file"] = source_file
        label = literal_text(graph, cls, RDFS.label) or literal_text(graph, cls, SKOS.prefLabel)
        if label:
            extras["rdfs_label"] = label
        supers = self.superclasses(cls)
        if supers:
            extras["owl_superclasses"] = [self.keys.get(p) or self.rdf.compact(p) for p in supers]
            for parent in supers:
                if parent not in self.keys:
                    self.limits.record("owl.external_reference", location=key)
        disjoint = sorted(
            {self.rdf.compact(o) for o in graph.objects(cls, OWL.disjointWith)}
            | {self.rdf.compact(s) for s in graph.subjects(OWL.disjointWith, cls)}
        )
        if disjoint:
            extras["owl_disjoint_with"] = disjoint
            self.limits.record("owl.disjointness", location=key)
        equivalent = [o for o in graph.objects(cls, OWL.equivalentClass) if isinstance(o, URIRef)]
        if equivalent:
            extras["owl_equivalent_class"] = sorted(self.rdf.compact(o) for o in equivalent)
            self.limits.record("owl.class_equivalence", location=key)
        expression = {}
        for predicate, name in ((OWL.unionOf, "unionOf"), (OWL.intersectionOf, "intersectionOf")):
            for holder in graph.objects(cls, predicate):
                expression[name] = [
                    self.rdf.compact(m) if isinstance(m, URIRef) else "restriction" for m in read_list(graph, holder)
                ]
        complement = graph.value(cls, OWL.complementOf)
        if complement is not None:
            expression["complementOf"] = (
                self.rdf.compact(complement) if isinstance(complement, URIRef) else "expression"
            )
        if expression:
            extras["owl_class_expression"] = expression
            self.limits.record("owl.class_expression", location=key)
        restrictions = [
            {"onProperty": self.rdf.compact(r.on_property), **r.quantified}
            for r in self.restrictions(cls)
            if r.quantified
        ]
        if restrictions:
            extras["owl_restrictions"] = restrictions
        return extras

    def class_type(self, cls: Any) -> None:
        """Define the type of one named class."""
        graph = self.graph
        key = self.keys[cls]
        extras = self.class_extras(cls, key)
        description = literal_text(graph, cls, RDFS.comment) or literal_text(graph, cls, SKOS.definition)
        one_of = [m for holder in graph.objects(cls, OWL.oneOf) for m in read_list(graph, holder)]
        union = [m for holder in graph.objects(cls, OWL.unionOf) for m in read_list(graph, holder)]
        if one_of:
            self.types[key] = Type(
                key=key,
                name=local_name(cls),
                kind=TypeKind.ENUM,
                description=description,
                enum_values=self._enum_values(key, one_of),
                extras=extras,
            )
            return
        if union:
            members = [self.keys.get(m) or self.rdf.compact(m) for m in union if isinstance(m, URIRef)]
            self.types[key] = Type(
                key=key,
                name=local_name(cls),
                kind=TypeKind.UNION,
                description=description,
                union_members=members,
                extras=extras,
            )
            return
        fields = self.class_fields(cls)
        individuals = self.individuals(cls)
        if individuals and not fields:
            self.limits.record("owl.individual_enumeration", location=key)
            self.types[key] = Type(
                key=key,
                name=local_name(cls),
                kind=TypeKind.ENUM,
                description=description,
                enum_values=self._enum_values(key, individuals),
                extras={**extras, **provenance_extras(INFERRED, _ENUMERATION_EVIDENCE)},
            )
            return
        if individuals:
            extras["owl_individuals"] = [self.rdf.compact(i) for i in individuals]
        self.types[key] = Type(
            key=key, name=local_name(cls), kind=TypeKind.RECORD, description=description, fields=fields, extras=extras
        )

    def datatype_type(self, datatype: Any) -> None:
        """Define a named ``rdfs:Datatype`` as an alias of its base type with its facets."""
        graph = self.graph
        key = self.keys[datatype]
        definitions = [datatype] + [n for n in graph.objects(datatype, OWL.equivalentClass)]
        base: Any = None
        values: Dict[str, Any] = {}
        for node in definitions:
            base = base or graph.value(node, OWL.onDatatype)
            for holder in graph.objects(node, OWL.withRestrictions):
                for facet in read_list(graph, holder):
                    for predicate, name in _FACETS:
                        value = graph.value(facet, predicate)
                        if value is not None:
                            values[name] = _facet_value(value) if name != "pattern" else str(value)
        if base is None:
            base = next((n for n in graph.objects(datatype, OWL.equivalentClass) if isinstance(n, URIRef)), None)
        scalar, fmt = datatype_ref_name(base) if base is not None else (None, None)
        if fmt:
            values["format"] = fmt
        extras: Dict[str, Any] = {"native_id": str(datatype)}
        if base is not None:
            extras["owl_on_datatype"] = self.rdf.compact(base)
        self.types[key] = Type(
            key=key,
            name=local_name(datatype),
            kind=TypeKind.ALIAS,
            description=literal_text(graph, datatype, RDFS.comment) or literal_text(graph, datatype, RDFS.label),
            aliased=TypeRef(name=scalar or "string", nullable=False),
            constraints=Constraints(**values) if values else None,
            extras=extras,
        )


def _ontology_record(document: OwlDocument) -> Tuple[str, Optional[str], Optional[str], Dict[str, Any]]:
    """The API's name, version, description and the ontology header record."""
    graph = document.rdf.graph
    root = document.rdf.root
    for iri in root.ontologies:
        subject = URIRef(iri)
        if (subject, RDF.type, OWL.Ontology) not in graph:
            continue
        name = (
            literal_text(graph, subject, RDFS.label) or literal_text(graph, subject, DCT.title) or local_name(subject)
        )
        header: Dict[str, Any] = {"iri": iri}
        version_iri = graph.value(subject, OWL.versionIRI)
        if version_iri is not None:
            header["version_iri"] = str(version_iri)
        licence = graph.value(subject, DCT.license)
        if licence is not None:
            header["license"] = str(licence)
        imports = sorted(str(o) for o in graph.objects(subject, OWL.imports))
        if imports:
            header["imports"] = imports
        return (
            name,
            literal_text(graph, subject, OWL.versionInfo),
            literal_text(graph, subject, RDFS.comment) or literal_text(graph, subject, DCT.description),
            header,
        )
    return PurePosixPath(root.path).stem or "Ontology", None, None, {}


class OwlNormalizer(Normalizer, register=True):
    """Normalize an :class:`OwlDocument` into a data_schema :class:`CanonicalApi`."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map a validated ontology onto the canonical model.

        Args:
            source: The :class:`OwlDocument` from :func:`read_owl`.
            include_raw: Whether to keep every file's text on ``raw``.

        Returns:
            The canonical model.

        Raises:
            ValueError: When ``source`` is not an :class:`OwlDocument`.
        """
        if not isinstance(source, OwlDocument):
            raise ValueError("OWL source must be an OwlDocument (see app.owl_normalizer.read_owl)")
        builder = _Builder(source)
        name, version, description, header = _ontology_record(source)
        builder.limits.record("owl.open_world", location=name)
        for datatype in source.datatypes:
            builder.datatype_type(datatype)
        for cls in source.classes:
            builder.class_type(cls)
        graph = source.rdf.graph
        unattached = sorted(source.rdf.compact(p) for p in source.properties if p not in builder._attached)
        for prop in unattached:
            builder.limits.record("owl.property_without_domain", location=prop)
        identity = sorted(
            {
                f"{source.rdf.compact(s)} {local_name(p)} {source.rdf.compact(o)}"
                for p in (OWL.sameAs, OWL.differentFrom)
                for s, o in graph.subject_objects(p)
            }
        )
        for statement in identity:
            builder.limits.record("owl.individual_identity", location=statement.split(" ", 1)[0])
        for iri in source.rdf.external_imports:
            builder.limits.record("owl.external_import", location=iri)
        record: Dict[str, Any] = {
            "input": "fileset" if source.rdf.is_fileset else "file",
            "files": [{"path": s.path, "syntax": s.syntax} for s in source.rdf.sources],
            "ontologies": list(source.rdf.ontologies),
            **({"ontology": header} if header else {}),
            **({"unattached_properties": unattached} if unattached else {}),
            **({"individual_identity": identity} if identity else {}),
            **({"external_imports": list(source.rdf.external_imports)} if source.rdf.external_imports else {}),
            "capability_limits": _limits_payload(builder.limits.limits()),
        }
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=name),
            version=version,
            title=name,
            description=description,
            types=list(builder.types.values()),
            raw=source.rdf.raw_record() if include_raw else None,
            extras={OWL_EXTRAS_KEY: record},
        )
        return normalize_ordering(api)
