"""SHACL shapes graph → canonical model — FMT-9.4 (#5471).

Reads a SHACL shapes graph (Turtle, RDF/XML or JSON-LD, one file or an ``owl:imports`` fileset,
loaded by :mod:`app.rdf_graph`) onto the **data_schema** paradigm:

.. code-block:: text

    ex:PersonShape a sh:NodeShape           → RECORD   PersonShape
      sh:property [ sh:path ex:email ; … ]  → field    PersonShape.email
      sh:node ex:IdentifiedShape            → the referenced shape's fields, inherited
      sh:or / sh:xone ( [ … ] [ … ] )       → the alternatives' fields, optional
    ex:AShape sh:or ( ex:B [ sh:datatype ] ) → UNION   AShape (B | string)

A property shape becomes a field named after its path's local name. ``sh:datatype`` maps XSD types
to canonical scalars; ``sh:node`` names the referenced shape's type; ``sh:class`` names the type of
the shape that targets that class, else an IRI-valued string. Cardinality follows SHACL: a property
with ``sh:maxCount 1`` is single-valued, any other is a list (``min_items`` / ``max_items`` from
``sh:minCount`` / ``sh:maxCount``); ``sh:minCount`` ≥ 1 makes it required. Value-range, string and
enumeration constraints (``sh:minInclusive`` … ``sh:pattern``, ``sh:in``, ``sh:hasValue``) map to the
canonical constraints. Everything SHACL states that the canonical model cannot (severity, messages,
targets, property pairs, qualified shapes, language constraints) is kept in ``extras`` under
``shacl_*`` keys, and every shape and property keeps its IRI as ``native_id`` provenance.

Declared limits (``extras['shacl']['capability_limits']``): SPARQL constraints, open-world targets
(``sh:targetSubjectsOf`` / ``sh:targetObjectsOf``), complex and unbounded property paths, logical
alternatives, property-pair, qualified, negated and language constraints, and **recursive shapes**
— SHACL leaves validation through a shape cycle undefined, so a cycle is kept as recursive type
references and declared.

Refusals (raised while reading, before normalization): a graph with no shapes
(``INPUT_SEMANTIC_INVALID``, or ``FORMAT_MISMATCH`` for an OWL ontology document) and a shape
reference (``sh:node``, ``sh:and`` …) to a shape the import does not define
(``INPUT_REFERENCE_UNRESOLVED``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

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
from .inference_provenance import SYNTHESIZED, provenance_extras
from .normalizer import Keys, Normalizer, normalize_ordering
from .rdf_graph import (
    DCT,
    OWL,
    RDF,
    RDFS,
    SH,
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
from .typescript_types_normalizer import _limits_payload
from .typescript_types_parser import LimitRecorder

__all__ = [
    "FORMAT_KEY",
    "LIMIT_DETAILS",
    "PARTIAL_LIMITS",
    "SHACL_EXTRAS_KEY",
    "ShaclDocument",
    "ShaclNormalizer",
    "has_shacl_vocabulary",
    "read_shacl",
]

#: Adapter and canonical format key.
FORMAT_KEY = "shacl"

#: Root extras key of the projection record.
SHACL_EXTRAS_KEY = "shacl"

#: The declared-limit vocabulary (stable keys → reviewed sentence).
LIMIT_DETAILS: Dict[str, str] = {
    "shacl.sparql_constraint": (
        "A SPARQL-based constraint (sh:sparql) is arbitrary query logic, not a structural "
        "constraint; it is not modelled. Its message and query are kept in extras['shacl_sparql']."
    ),
    "shacl.open_world_target": (
        "sh:targetSubjectsOf / sh:targetObjectsOf select focus nodes by the shape of the data graph, "
        "not by declaration; Apiome's model is closed-world, so the shape is imported as a type and "
        "the target is kept in extras only."
    ),
    "shacl.complex_path": (
        "A sequence, inverse, alternative or zero-or-one property path is projected to one field named "
        "after its steps; the path itself is kept in extras['shacl_path']."
    ),
    "shacl.unbounded_path": (
        "A zero-or-more / one-or-more property path recurses over the graph without bound; it is "
        "projected to one field and the path is kept in extras['shacl_path']."
    ),
    "shacl.logical_alternatives": (
        "sh:or / sh:xone alternatives are projected as optional fields (or a union of the "
        "alternative types); the exclusive-choice semantics are kept in extras['shacl_alternative']."
    ),
    "shacl.property_pair": (
        "A property-pair constraint (sh:equals, sh:disjoint, sh:lessThan, sh:lessThanOrEquals) "
        "compares two properties' values; it has no canonical analogue and is kept in extras."
    ),
    "shacl.qualified_value_shape": (
        "A qualified value shape counts only the values that conform to another shape; the field is "
        "kept and the qualified cardinality is in extras['shacl_qualified']."
    ),
    "shacl.negation": (
        "sh:not requires values *not* to conform to a shape; the field is kept and the negated shape "
        "is in extras['shacl_not']."
    ),
    "shacl.language_constraint": (
        "sh:languageIn / sh:uniqueLang constrain language tags, which the canonical string does not "
        "carry; they are kept in extras."
    ),
    "shacl.recursive_shape": (
        "The shape is part of a reference cycle. SHACL leaves validation through recursive shapes "
        "undefined; Apiome keeps the cycle as recursive type references and stops there."
    ),
    "shacl.property_without_path": (
        "A property shape without sh:path constrains nothing addressable and is not modelled."
    ),
    "shacl.external_import": (
        "owl:imports names a well-known vocabulary that is not part of the upload; its terms are "
        "referenced by IRI, not imported."
    ),
}

#: Limits whose construct is still modelled, with only a detail lost.
PARTIAL_LIMITS = frozenset(LIMIT_DETAILS) - {
    "shacl.sparql_constraint",
    "shacl.property_without_path",
}

_SYNTHESIZED_EVIDENCE = "SHACL lets a shape be anonymous (a blank node); the type name is Apiome's."

#: Shape-reference predicates whose IRI targets must be shapes the import defines.
_SHAPE_LIST_PREDICATES = (SH["and"], SH["or"], SH.xone)
_SHAPE_PREDICATES = (SH.node, SH["not"], SH.qualifiedValueShape, SH.property)

_PROPERTY_PAIR_PREDICATES = (SH.equals, SH.disjoint, SH.lessThan, SH.lessThanOrEquals)

_NUMERIC_CONSTRAINTS = (
    (SH.minInclusive, "minimum"),
    (SH.maxInclusive, "maximum"),
    (SH.minExclusive, "exclusive_minimum"),
    (SH.maxExclusive, "exclusive_maximum"),
)

#: Predicates in the SHACL namespace that make an IRI subject a shape.
_SHAPE_MARKERS = (SH.property, SH.targetClass, SH.targetNode, SH.targetSubjectsOf, SH.targetObjectsOf, SH.path)

#: OWL / RDFS vocabulary that makes a document an ontology rather than a shapes graph.
_ONTOLOGY_TYPES = (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, RDFS.Class)


@dataclass
class ShaclDocument:
    """A validated SHACL shapes graph.

    Attributes:
        rdf: The loaded graph and its sources.
        shapes: The named node shapes, sorted by IRI.
        property_shapes: Named (IRI) property shapes, sorted by IRI.
    """

    rdf: RdfDocument
    shapes: Tuple[URIRef, ...]
    property_shapes: Tuple[URIRef, ...]


# ===========================================================================
# Reading and validation
# ===========================================================================


def has_shacl_vocabulary(graph: Any) -> bool:
    """Whether a graph declares at least one SHACL node or property shape."""
    for marker in (SH.NodeShape, SH.PropertyShape):
        if next(iter(graph.subjects(RDF.type, marker)), None) is not None:
            return True
    return next(iter(graph.subjects(SH.property, None)), None) is not None


def _named_shapes(rdf: RdfDocument) -> Tuple[Tuple[URIRef, ...], Tuple[URIRef, ...]]:
    """The named node shapes and named property shapes of the graph, each sorted by IRI."""
    graph = rdf.graph
    property_shapes = {s for s in graph.subjects(RDF.type, SH.PropertyShape) if isinstance(s, URIRef)}
    property_shapes |= {
        s for s in graph.subjects(SH.path, None) if isinstance(s, URIRef) and (s, RDF.type, SH.NodeShape) not in graph
    }
    node_shapes = {s for s in graph.subjects(RDF.type, SH.NodeShape) if isinstance(s, URIRef)}
    for marker in _SHAPE_MARKERS:
        if marker == SH.path:
            continue
        node_shapes |= {s for s in graph.subjects(marker, None) if isinstance(s, URIRef)}
    # Shapes referenced by name from a logical list or sh:node are node shapes too.
    for predicate in _SHAPE_LIST_PREDICATES:
        for holder in graph.objects(None, predicate):
            node_shapes |= {m for m in read_list(graph, holder) if isinstance(m, URIRef) and _is_defined(graph, m)}
    node_shapes -= property_shapes
    return tuple(sorted(node_shapes, key=str)), tuple(sorted(property_shapes, key=str))


def _is_defined(graph: Any, node: Any) -> bool:
    """Whether the graph says anything about ``node`` as a subject."""
    return next(iter(graph.predicate_objects(node)), None) is not None


def _referenced_shapes(graph: Any) -> Set[URIRef]:
    """Every IRI used where a shape is expected."""
    found: Set[URIRef] = set()
    for predicate in _SHAPE_PREDICATES:
        found |= {o for o in graph.objects(None, predicate) if isinstance(o, URIRef)}
    for predicate in _SHAPE_LIST_PREDICATES:
        for holder in graph.objects(None, predicate):
            found |= {m for m in read_list(graph, holder) if isinstance(m, URIRef)}
    return found


def read_shacl(text: Optional[str] = None, *, label: str, fileset: Optional[IntakeFileset] = None) -> ShaclDocument:
    """Load and validate a SHACL shapes graph (one file or a fileset).

    Raises:
        RdfParseError: With the taxonomy code of the failure — a syntax, encoding or import fault,
            no shapes (``INPUT_SEMANTIC_INVALID`` / ``FORMAT_MISMATCH``), or a shape reference the
            import does not define (``INPUT_REFERENCE_UNRESOLVED``).
    """
    rdf = load_rdf_document(text, label=label, fileset=fileset)
    graph = rdf.graph
    if not has_shacl_vocabulary(graph):
        is_ontology = rdf.ontologies and any(
            next(iter(graph.subjects(RDF.type, t)), None) is not None for t in _ONTOLOGY_TYPES
        )
        if is_ontology:
            raise RdfParseError(
                f"{label} is an OWL / RDFS ontology, not a SHACL shapes graph: it declares an "
                "owl:Ontology with classes and properties but no sh:NodeShape. Import it as OWL / RDFS.",
                code="FORMAT_MISMATCH",
            )
        raise RdfParseError(
            f"{label} is valid RDF but not a shapes graph: it declares no sh:NodeShape or "
            "sh:PropertyShape, so there are no constraints to import.",
            code="INPUT_SEMANTIC_INVALID",
        )
    missing = sorted(str(ref) for ref in _referenced_shapes(graph) if not _is_defined(graph, ref))
    if missing:
        names = ", ".join(rdf.compact(URIRef(iri)) for iri in missing)
        raise RdfParseError(
            f"Shape reference(s) {names} name a shape this import does not define. Add the file that "
            "defines it (with an owl:imports of its shapes graph) to the upload and import it again.",
            code="INPUT_REFERENCE_UNRESOLVED",
        )
    shapes, property_shapes = _named_shapes(rdf)
    return ShaclDocument(rdf=rdf, shapes=shapes, property_shapes=property_shapes)


# ===========================================================================
# Normalization
# ===========================================================================


def _number(node: Any) -> Optional[float]:
    """A numeric literal as ``int`` / ``float`` (``None`` for anything else, booleans included)."""
    if isinstance(node, Literal):
        value = node.toPython()
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float, Decimal)):
            return float(value) if not isinstance(value, int) else value
    return None


def _integer(node: Any) -> Optional[int]:
    """A numeric literal truncated to ``int``, or ``None``."""
    value = _number(node)
    return int(value) if value is not None else None


def _bool(node: Any) -> bool:
    """Whether ``node`` is the literal ``true``."""
    return isinstance(node, Literal) and node.toPython() is True


def _worst(parts: Sequence[Tuple[Any, ...]], limit: str) -> str:
    """The limit a composite path falls under: unbounded if any step is, else ``limit``."""
    if limit == "shacl.unbounded_path" or any(p[3] == "shacl.unbounded_path" for p in parts):
        return "shacl.unbounded_path"
    return limit


def _sorted_nodes(nodes: Any) -> List[Any]:
    """Graph objects in a stable order: IRIs and literals by text, blank nodes by their content."""
    return sorted(nodes, key=lambda n: (isinstance(n, BNode), str(n) if not isinstance(n, BNode) else ""))


class _Builder:
    """Accumulates types and limits while one shapes graph is normalized."""

    def __init__(self, document: ShaclDocument) -> None:
        """Assign type keys, index class-targeting shapes and find the shapes on a reference cycle."""
        self.document = document
        self.rdf = document.rdf
        self.graph = document.rdf.graph
        self.types: Dict[str, Type] = {}
        self.limits = LimitRecorder(details=LIMIT_DETAILS)
        self.keys: Dict[Any, str] = assign_type_keys(self.rdf, document.shapes)
        self.class_shapes: Dict[Any, str] = {}
        for shape in document.shapes:
            for target in _sorted_nodes(self.graph.objects(shape, SH.targetClass)):
                self.class_shapes.setdefault(target, self.keys[shape])
        self.cyclic: Set[Any] = self._cyclic_shapes()
        self._synthesized: Dict[Any, str] = {}
        self._building: Set[Any] = set()
        #: Record key → the named shapes it inherits from (sh:node / sh:and).
        self._inherits: Dict[str, List[str]] = {}

    # --- keys ------------------------------------------------------------------------------

    def _unique_key(self, base: str) -> str:
        """``base``, or ``base2``, ``base3`` … — the first key no type or shape uses yet."""
        key = base
        counter = 2
        while key in self.types or key in self.keys.values():
            key = f"{base}{counter}"
            counter += 1
        return key

    # --- cycles ----------------------------------------------------------------------------

    def _shape_edges(self, shape: Any) -> Set[Any]:
        """Named shapes ``shape`` refers to, through its properties and logical constraints."""
        edges: Set[Any] = set()
        pending = [shape]
        seen: Set[Any] = set()
        while pending:
            node = pending.pop()
            if node in seen:
                continue
            seen.add(node)
            for predicate in (SH.node, SH.qualifiedValueShape, SH["not"], SH.property):
                for target in self.graph.objects(node, predicate):
                    (edges.add(target) if target in self.keys else pending.append(target))
            for target in self.graph.objects(node, SH["class"]):
                if target in self.class_shapes:
                    edges.add(next(s for s, k in self.keys.items() if k == self.class_shapes[target]))
            for predicate in _SHAPE_LIST_PREDICATES:
                for holder in self.graph.objects(node, predicate):
                    for member in read_list(self.graph, holder):
                        (edges.add(member) if member in self.keys else pending.append(member))
        return edges

    def _cyclic_shapes(self) -> Set[Any]:
        """The named shapes that sit on a reference cycle (Tarjan's strongly connected components)."""
        edges = {shape: self._shape_edges(shape) for shape in self.keys}
        index: Dict[Any, int] = {}
        low: Dict[Any, int] = {}
        stack: List[Any] = []
        on_stack: Set[Any] = set()
        cyclic: Set[Any] = set()
        counter = [0]

        def visit(root: Any) -> None:
            # Iterative Tarjan: (node, iterator over successors).
            """Run Tarjan's algorithm from ``root`` without recursion."""
            work: List[Tuple[Any, Any]] = [(root, iter(sorted(edges.get(root, ()), key=str)))]
            index[root] = low[root] = counter[0]
            counter[0] += 1
            stack.append(root)
            on_stack.add(root)
            while work:
                node, successors = work[-1]
                advanced = False
                for successor in successors:
                    if successor not in index:
                        index[successor] = low[successor] = counter[0]
                        counter[0] += 1
                        stack.append(successor)
                        on_stack.add(successor)
                        work.append((successor, iter(sorted(edges.get(successor, ()), key=str))))
                        advanced = True
                        break
                    if successor in on_stack:
                        low[node] = min(low[node], index[successor])
                if advanced:
                    continue
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == index[node]:
                    component = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        component.append(member)
                        if member == node:
                            break
                    if len(component) > 1 or node in edges.get(node, ()):
                        cyclic.update(component)

        for shape in sorted(self.keys, key=str):
            if shape not in index:
                visit(shape)
        return cyclic

    # --- paths -----------------------------------------------------------------------------

    def path(self, node: Any) -> Tuple[str, str, Optional[str], Optional[str]]:
        """Describe a property path.

        Returns:
            ``(field name, path text, native IRI or None, limit key or None)`` — a plain predicate
            path has an IRI and no limit; a composite path names the limit it falls under.
        """
        graph = self.graph
        if isinstance(node, URIRef):
            return local_name(node), self.rdf.compact(node), str(node), None
        steps = read_list(graph, node)
        if steps:
            parts = [self.path(step) for step in steps]
            return (
                "_".join(p[0] for p in parts),
                " / ".join(p[1] for p in parts),
                None,
                _worst(parts, "shacl.complex_path"),
            )
        for predicate, suffix, limit, sign in (
            (SH.inversePath, "_inverse", "shacl.complex_path", "^"),
            (SH.zeroOrMorePath, "_zeroOrMore", "shacl.unbounded_path", "*"),
            (SH.oneOrMorePath, "_oneOrMore", "shacl.unbounded_path", "+"),
            (SH.zeroOrOnePath, "_zeroOrOne", "shacl.complex_path", "?"),
        ):
            target = graph.value(node, predicate)
            if target is not None:
                name, text, _, inner = self.path(target)
                rendered = f"^{text}" if sign == "^" else f"({text}){sign}"
                return f"{name}{suffix}", rendered, None, _worst([("", "", None, inner)], limit)
        alternatives = read_list(graph, graph.value(node, SH.alternativePath))
        if alternatives:
            parts = [self.path(step) for step in alternatives]
            return (
                "_or_".join(p[0] for p in parts),
                " | ".join(p[1] for p in parts),
                None,
                _worst(parts, "shacl.complex_path"),
            )
        return "value", "?", None, "shacl.complex_path"

    # --- value types -----------------------------------------------------------------------

    def _member_type(self, node: Any, owner: str, hint: str) -> Tuple[str, Optional[str]]:
        """The canonical type name (and format) a shape-valued node stands for."""
        if node in self.keys:
            return self.keys[node], None
        name, fmt = self._value_type(node, owner, hint)
        return name, fmt

    def _value_type(self, shape: Any, owner: str, hint: str) -> Tuple[str, Optional[str]]:
        """The canonical type of the values a (property or inline) shape constrains."""
        graph = self.graph
        datatype = graph.value(shape, SH.datatype)
        if datatype is not None:
            scalar, fmt = datatype_ref_name(datatype)
            return scalar or "string", fmt
        node = graph.value(shape, SH.node)
        if node is not None:
            if node in self.keys:
                return self.keys[node], None
            return self._synthesized_record(node, owner, hint), None
        cls = graph.value(shape, SH["class"])
        if cls is not None:
            if cls in self.class_shapes:
                return self.class_shapes[cls], None
            return "string", "iri"
        alternatives = self._alternative_members(shape)
        if alternatives:
            names = {self._member_type(member, owner, hint) for member in alternatives}
            if len(names) == 1:
                return next(iter(names))
            return "any", None
        enumerated = read_list(graph, graph.value(shape, SH["in"]))
        has_value = list(graph.objects(shape, SH.hasValue))
        values = enumerated or has_value
        if values:
            if all(isinstance(v, URIRef) for v in values):
                return "string", "iri"
            if all(isinstance(v, Literal) for v in values):
                kinds = {datatype_ref_name(v.datatype)[0] if v.datatype else "string" for v in values}
                if len(kinds) == 1:
                    return kinds.pop() or "string", None
            return "any", None
        kind = graph.value(shape, SH.nodeKind)
        if kind in (SH.IRI, SH.BlankNodeOrIRI):
            return "string", "iri"
        if kind == SH.Literal:
            return "string", None
        if graph.value(shape, SH.property) is not None:
            return self._synthesized_record(shape, owner, hint), None
        return "any", None

    def _alternative_members(self, shape: Any) -> List[Any]:
        """The members of every ``sh:or`` / ``sh:xone`` list on ``shape``."""
        members: List[Any] = []
        for predicate in (SH["or"], SH.xone):
            for holder in self.graph.objects(shape, predicate):
                members.extend(read_list(self.graph, holder))
        return members

    def _synthesized_record(self, shape: Any, owner: str, hint: str) -> str:
        """Name and build the record of an anonymous (blank-node) shape."""
        if shape in self._synthesized:
            return self._synthesized[shape]
        key = self._unique_key(f"{owner}_{hint[:1].upper()}{hint[1:]}")
        self._synthesized[shape] = key
        self.shape_type(shape, key, synthesized=True)
        return key

    # --- fields ----------------------------------------------------------------------------

    def _constraints(
        self, shape: Any, many: bool, min_count: int, max_count: Optional[int], fmt: Optional[str]
    ) -> Tuple[Optional[Constraints], Dict[str, Any]]:
        """The canonical constraints of a property shape, plus the ``shacl_*`` extras they leave behind."""
        graph = self.graph
        values: Dict[str, Any] = {}
        extras: Dict[str, Any] = {}
        if many:
            if min_count > 0:
                values["min_items"] = min_count
            if max_count is not None:
                values["max_items"] = max_count
        for predicate, name in _NUMERIC_CONSTRAINTS:
            number = _number(graph.value(shape, predicate))
            if number is not None:
                values[name] = number
        for predicate, name in ((SH.minLength, "min_length"), (SH.maxLength, "max_length")):
            number = _integer(graph.value(shape, predicate))
            if number is not None:
                values[name] = number
        pattern = graph.value(shape, SH.pattern)
        if pattern is not None:
            values["pattern"] = str(pattern)
            flags = graph.value(shape, SH.flags)
            if flags is not None:
                extras["shacl_flags"] = str(flags)
        enumerated = read_list(graph, graph.value(shape, SH["in"]))
        if enumerated:
            values["enum"] = [literal_value(v) for v in enumerated]
        has_value = _sorted_nodes(graph.objects(shape, SH.hasValue))
        if has_value:
            values["enum"] = [literal_value(v) for v in has_value]
            extras["shacl_has_value"] = [literal_value(v) for v in has_value]
        if fmt:
            values["format"] = fmt
        if not values:
            return None, extras
        return Constraints(**values), extras

    def property_field(self, prop: Any, owner_key: str, alternative: Optional[str] = None) -> Optional[CanonicalField]:
        """One property shape as a field of ``owner_key`` (``None`` for a path-less shape)."""
        graph = self.graph
        path_node = graph.value(prop, SH.path)
        if path_node is None:
            self.limits.record("shacl.property_without_path", location=owner_key)
            return None
        name, path_text, native, path_limit = self.path(path_node)
        key = Keys.field(owner_key, name)
        if path_limit:
            self.limits.record(path_limit, location=key)
        min_count = _integer(graph.value(prop, SH.minCount)) or 0
        max_count = _integer(graph.value(prop, SH.maxCount))
        required = min_count >= 1 and alternative is None
        many = max_count != 1
        type_name, fmt = self._value_type(prop, owner_key, name)
        element = TypeRef(name=type_name, nullable=False)
        type_ref = (
            TypeRef(item=element, nullable=not required) if many else TypeRef(name=type_name, nullable=not required)
        )
        constraints, constraint_extras = self._constraints(prop, many, min_count, max_count, fmt)
        extras: Dict[str, Any] = {"shacl_path": path_text, **constraint_extras}
        if native:
            extras["native_id"] = native
        if isinstance(prop, URIRef):
            extras["shacl_property_shape"] = str(prop)
        if min_count:
            extras["shacl_min_count"] = min_count
        if max_count is not None:
            extras["shacl_max_count"] = max_count
        self._annotations(prop, extras)
        self._field_constraints(prop, key, extras)
        if alternative:
            extras["shacl_alternative"] = alternative
        default = graph.value(prop, SH.defaultValue)
        return CanonicalField(
            key=key,
            name=name,
            type=type_ref,
            default=literal_value(default) if default is not None else None,
            constraints=constraints,
            description=literal_text(graph, prop, SH.description) or literal_text(graph, prop, RDFS.comment),
            extras=extras,
        )

    def _annotations(self, node: Any, extras: Dict[str, Any]) -> None:
        """Copy the non-validating SHACL annotations of a shape into ``extras``."""
        graph = self.graph
        label = literal_text(graph, node, SH.name)
        if label:
            extras["shacl_name"] = label
        order = _number(graph.value(node, SH.order))
        if order is not None:
            extras["shacl_order"] = order
        group = graph.value(node, SH.group)
        if group is not None:
            extras["shacl_group"] = self.rdf.compact(group)
        severity = graph.value(node, SH.severity)
        if severity is not None:
            extras["shacl_severity"] = local_name(severity)
        message = literal_text(graph, node, SH.message)
        if message:
            extras["shacl_message"] = message
        datatype = graph.value(node, SH.datatype)
        if datatype is not None:
            extras["shacl_datatype"] = self.rdf.compact(datatype)
        cls = graph.value(node, SH["class"])
        if cls is not None:
            extras["shacl_class"] = self.rdf.compact(cls)
        kind = graph.value(node, SH.nodeKind)
        if kind is not None:
            extras["shacl_node_kind"] = local_name(kind)
        if _bool(graph.value(node, SH.deactivated)):
            extras["shacl_deactivated"] = True

    def _field_constraints(self, prop: Any, location: str, extras: Dict[str, Any]) -> None:
        """Record the constraints with no canonical analogue (and their declared limits)."""
        graph = self.graph
        pairs = {
            local_name(predicate): self.rdf.compact(target)
            for predicate in _PROPERTY_PAIR_PREDICATES
            for target in [graph.value(prop, predicate)]
            if target is not None
        }
        if pairs:
            extras["shacl_property_pair"] = pairs
            self.limits.record("shacl.property_pair", location=location)
        qualified = graph.value(prop, SH.qualifiedValueShape)
        if qualified is not None:
            extras["shacl_qualified"] = {
                "shape": self._describe_shape(qualified),
                **{
                    name: _integer(graph.value(prop, predicate))
                    for predicate, name in ((SH.qualifiedMinCount, "minCount"), (SH.qualifiedMaxCount, "maxCount"))
                    if graph.value(prop, predicate) is not None
                },
                **({"disjoint": True} if _bool(graph.value(prop, SH.qualifiedValueShapesDisjoint)) else {}),
            }
            self.limits.record("shacl.qualified_value_shape", location=location)
        negated = graph.value(prop, SH["not"])
        if negated is not None:
            extras["shacl_not"] = self._describe_shape(negated)
            self.limits.record("shacl.negation", location=location)
        languages = read_list(graph, graph.value(prop, SH.languageIn))
        if languages:
            extras["shacl_language_in"] = [str(v) for v in languages]
        if _bool(graph.value(prop, SH.uniqueLang)):
            extras["shacl_unique_lang"] = True
        if languages or extras.get("shacl_unique_lang"):
            self.limits.record("shacl.language_constraint", location=location)
        if self._alternative_members(prop):
            extras["shacl_alternatives"] = [self._describe_shape(m) for m in self._alternative_members(prop)]
            self.limits.record("shacl.logical_alternatives", location=location)

    def _describe_shape(self, node: Any) -> Any:
        """A small JSON description of an inline shape (or the key of a named one)."""
        if node in self.keys:
            return self.keys[node]
        if isinstance(node, URIRef):
            return self.rdf.compact(node)
        described: Dict[str, Any] = {}
        paths = [
            self.path(path)[1]
            for prop in self._property_nodes(node)
            for path in [self.graph.value(prop, SH.path)]
            if path is not None
        ]
        if paths:
            described["properties"] = sorted(paths)
        for predicate, obj in sorted(self.graph.predicate_objects(node), key=lambda po: str(po[0])):
            if isinstance(obj, BNode):
                continue
            described[self.rdf.compact(predicate)] = (
                literal_value(obj) if isinstance(obj, Literal) else self.rdf.compact(obj)
            )
        return described

    # --- shapes ----------------------------------------------------------------------------

    def _property_nodes(self, shape: Any) -> List[Any]:
        """The property shapes of ``shape`` in a stable order."""
        return _sorted_nodes(self.graph.objects(shape, SH.property))

    def collect_fields(self, shape: Any, key: str, chain: Tuple[Any, ...] = ()) -> List[CanonicalField]:
        """A shape's fields: inherited (sh:node / sh:and), then alternatives, then its own."""
        graph = self.graph
        fields: Dict[str, CanonicalField] = {}
        inherited_from: List[str] = []
        conjuncts = list(_sorted_nodes(graph.objects(shape, SH.node)))
        for holder in graph.objects(shape, SH["and"]):
            conjuncts.extend(read_list(graph, holder))
        for parent in conjuncts:
            if parent in chain or parent == shape:
                continue
            parent_name = self.keys.get(parent)
            for inherited in self.collect_fields(parent, parent_name or key, chain + (shape,)):
                extras = dict(inherited.extras)
                if parent_name:
                    extras.setdefault("shacl_inherited_from", parent_name)
                fields[inherited.name] = inherited.model_copy(
                    update={"key": Keys.field(key, inherited.name), "extras": extras}
                )
            if parent_name:
                inherited_from.append(parent_name)
        for predicate, label in ((SH["or"], "or"), (SH.xone, "xone")):
            for holder in graph.objects(shape, predicate):
                for member in read_list(graph, holder):
                    if member in self.keys or graph.value(member, SH.property) is None:
                        continue
                    self.limits.record("shacl.logical_alternatives", location=key)
                    for prop in self._property_nodes(member):
                        built = self.property_field(prop, key, alternative=label)
                        if built is None:
                            continue
                        if built.name in fields:
                            previous = fields[built.name]
                            others = list(previous.extras.get("shacl_alternative_types", []))
                            others.append(built.type.item.name if built.type.item else built.type.name)
                            fields[built.name] = previous.model_copy(
                                update={"extras": {**previous.extras, "shacl_alternative_types": others}}
                            )
                            continue
                        fields[built.name] = built
        for prop in self._property_nodes(shape):
            built = self.property_field(prop, key)
            if built is None:
                continue
            name = built.name
            if (
                name in fields
                and "shacl_inherited_from" not in fields[name].extras
                and "shacl_alternative" not in fields[name].extras
            ):
                counter = 2
                while f"{name}_{counter}" in fields:
                    counter += 1
                name = f"{name}_{counter}"
                built = built.model_copy(update={"name": name, "key": Keys.field(key, name)})
            fields[name] = built
        if inherited_from and shape in self.keys:
            self._inherits[key] = inherited_from
        return list(fields.values())

    def shape_type(self, shape: Any, key: str, *, synthesized: bool = False) -> None:
        """Define the type of one node shape (named or anonymous)."""
        if key in self.types or shape in self._building:
            return
        self._building.add(shape)
        graph = self.graph
        extras: Dict[str, Any] = {}
        if isinstance(shape, URIRef):
            extras["native_id"] = str(shape)
        source_file = self.rdf.file_of(shape)
        if source_file:
            extras["rdf_file"] = source_file
        self._shape_extras(shape, key, extras)
        if synthesized:
            extras.update(provenance_extras(SYNTHESIZED, _SYNTHESIZED_EVIDENCE))
        if shape in self.cyclic:
            self.limits.record("shacl.recursive_shape", location=key)
            extras["shacl_recursive"] = True
        description = (
            literal_text(graph, shape, RDFS.comment)
            or literal_text(graph, shape, SH.description)
            or literal_text(graph, shape, RDFS.label)
        )
        alternatives = self._alternative_members(shape)
        has_properties = graph.value(shape, SH.property) is not None or graph.value(shape, SH.node) is not None
        record_alternatives = any(m not in self.keys and graph.value(m, SH.property) is not None for m in alternatives)
        enumerated = read_list(graph, graph.value(shape, SH["in"]))
        if alternatives and not has_properties and not record_alternatives:
            self.limits.record("shacl.logical_alternatives", location=key)
            members: List[str] = []
            for index, member in enumerate(alternatives, start=1):
                name, _ = self._member_type(member, key, f"option{index}")
                if name not in members:
                    members.append(name)
            self.types[key] = Type(
                key=key,
                name=key.rsplit(".", 1)[-1],
                kind=TypeKind.UNION,
                description=description,
                union_members=members,
                extras=extras,
            )
        elif enumerated and not has_properties:
            self.types[key] = Type(
                key=key,
                name=key.rsplit(".", 1)[-1],
                kind=TypeKind.ENUM,
                description=description,
                enum_values=[
                    EnumValue(key=Keys.enum_value(key, local_name(v)), name=local_name(v), value=literal_value(v))
                    for v in enumerated
                ],
                extras=extras,
            )
        else:
            # Reserve the key first so a self-referential shape resolves to itself.
            self.types[key] = Type(key=key, name=key.rsplit(".", 1)[-1], kind=TypeKind.RECORD, extras=extras)
            fields = self.collect_fields(shape, key)
            if key in self._inherits:
                extras["shacl_node"] = self._inherits[key]
            self.types[key] = Type(
                key=key,
                name=key.rsplit(".", 1)[-1],
                kind=TypeKind.RECORD,
                description=description,
                fields=fields,
                extras=extras,
            )
        self._building.discard(shape)

    def _shape_extras(self, shape: Any, key: str, extras: Dict[str, Any]) -> None:
        """Targets, closedness, severity and the node-level limits of one shape."""
        graph = self.graph
        for predicate, name in (
            (SH.targetClass, "shacl_target_class"),
            (SH.targetNode, "shacl_target_node"),
            (SH.targetSubjectsOf, "shacl_target_subjects_of"),
            (SH.targetObjectsOf, "shacl_target_objects_of"),
        ):
            targets = [
                self.rdf.compact(t) if not isinstance(t, Literal) else str(t)
                for t in _sorted_nodes(graph.objects(shape, predicate))
            ]
            if targets:
                extras[name] = targets
        if "shacl_target_subjects_of" in extras or "shacl_target_objects_of" in extras:
            self.limits.record("shacl.open_world_target", location=key)
        if _bool(graph.value(shape, SH.closed)):
            extras["shacl_closed"] = True
            ignored = read_list(graph, graph.value(shape, SH.ignoredProperties))
            if ignored:
                extras["shacl_ignored_properties"] = [self.rdf.compact(p) for p in ignored]
        label = literal_text(graph, shape, RDFS.label)
        if label:
            extras["rdfs_label"] = label
        for predicate, label_key in ((SH["or"], "shacl_or"), (SH.xone, "shacl_xone"), (SH["and"], "shacl_and")):
            members = [m for holder in graph.objects(shape, predicate) for m in read_list(graph, holder)]
            if members:
                extras[label_key] = [self._describe_shape(m) for m in members]
        self._annotations(shape, extras)
        sparql = []
        for constraint in graph.objects(shape, SH.sparql):
            sparql.append(
                {
                    **(
                        {"message": literal_text(graph, constraint, SH.message)}
                        if graph.value(constraint, SH.message)
                        else {}
                    ),
                    **(
                        {"select": str(graph.value(constraint, SH.select)).strip()}
                        if graph.value(constraint, SH.select)
                        else {}
                    ),
                }
            )
            self.limits.record("shacl.sparql_constraint", location=key)
        if sparql:
            extras["shacl_sparql"] = sorted(
                sparql, key=lambda item: (item.get("message") or "", item.get("select") or "")
            )


def _identity(document: ShaclDocument) -> Tuple[str, Optional[str], Optional[str]]:
    """The API's name, version and description."""
    graph = document.rdf.graph
    root = document.rdf.root
    for iri in root.ontologies:
        subject = URIRef(iri)
        name = literal_text(graph, subject, RDFS.label) or literal_text(graph, subject, DCT.title)
        if name or (subject, RDF.type, OWL.Ontology) in graph:
            return (
                name or local_name(subject),
                literal_text(graph, subject, OWL.versionInfo),
                literal_text(graph, subject, RDFS.comment) or literal_text(graph, subject, DCT.description),
            )
    stem = PurePosixPath(root.path).stem
    return stem or "SHACL shapes", None, None


class ShaclNormalizer(Normalizer, register=True):
    """Normalize a :class:`ShaclDocument` into a data_schema :class:`CanonicalApi`."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map a validated shapes graph onto the canonical model.

        Args:
            source: The :class:`ShaclDocument` from :func:`read_shacl`.
            include_raw: Whether to keep every file's text on ``raw``.

        Returns:
            The canonical model.

        Raises:
            ValueError: When ``source`` is not a :class:`ShaclDocument`.
        """
        if not isinstance(source, ShaclDocument):
            raise ValueError("SHACL source must be a ShaclDocument (see app.shacl_normalizer.read_shacl)")
        builder = _Builder(source)
        for shape in source.shapes:
            builder.shape_type(shape, builder.keys[shape])
        for iri in source.rdf.external_imports:
            builder.limits.record("shacl.external_import", location=iri)
        graph = source.rdf.graph
        groups = [
            {
                "iri": source.rdf.compact(group),
                **({"label": literal_text(graph, group, RDFS.label)} if literal_text(graph, group, RDFS.label) else {}),
                **(
                    {"order": _number(graph.value(group, SH.order))} if graph.value(group, SH.order) is not None else {}
                ),
            }
            for group in sorted(graph.subjects(RDF.type, SH.PropertyGroup), key=str)
        ]
        name, version, description = _identity(source)
        record: Dict[str, Any] = {
            "input": "fileset" if source.rdf.is_fileset else "file",
            "files": [{"path": s.path, "syntax": s.syntax} for s in source.rdf.sources],
            "ontologies": list(source.rdf.ontologies),
            "shapes": [builder.keys[s] for s in source.shapes],
            **({"property_groups": groups} if groups else {}),
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
            extras={SHACL_EXTRAS_KEY: record},
        )
        return normalize_ordering(api)
