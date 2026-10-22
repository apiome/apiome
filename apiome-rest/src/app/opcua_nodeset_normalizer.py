"""OPC UA NodeSet2 → canonical model normalizer — FMT-9.1 (#5468).

Maps a parsed :class:`~app.opcua_nodeset_parser.NodeSetDocument` onto a
:class:`~app.canonical_model.CanonicalApi` of paradigm :attr:`~app.canonical_model.ApiParadigm.RPC`:

==========================  ==========================================================================
NodeSet2                    Canonical model
==========================  ==========================================================================
``UAObjectType``            ``RECORD`` whose fields are its **instance declarations** — the variables
                            and objects it reaches by ``HasComponent`` / ``HasProperty`` that carry a
                            modelling rule. ``Mandatory`` → required, ``Optional`` → nullable, the two
                            placeholder rules → a list (``MandatoryPlaceholder``: ``minItems: 1``).
                            A supertype declared in the file contributes its fields first.
``UAVariableType``          ``ALIAS`` of its ``DataType`` at its ``ValueRank``.
``UADataType``              structured → ``RECORD`` with fields; enumeration → ``ENUM``; OptionSet →
                            ``ENUM`` of its bits; union → ``RECORD`` of optional fields; a subtype of
                            a scalar → ``ALIAS``.
``UAMethod``                an RPC ``request_response`` operation on one service per owning type, its
                            ``InputArguments`` / ``OutputArguments`` as request / response records.
``UAReferenceType``         ``extras.opcua.reference_types``.
References                  each type keeps its references in ``extras.opcua_references``.
``UAObject`` · ``UAVariable`` · ``UAView``  address-space *instances*: described by the payload analysis
                            (:mod:`app.opcua_nodeset_analysis`), never promoted to canonical types.
==========================  ==========================================================================

``ValueRank`` ``-1`` is a scalar, ``0`` / ``1`` a list, ``n > 1`` ``n`` nested lists; a positive
``ArrayDimensions`` entry is the dimension's maximum length (``maxItems``). The ns=0 built-in data
types map to canonical scalars with their width as a ``format`` (``Int32`` → ``integer`` /
``int32``).

**Provenance.** The namespace URIs, every ``Model`` (``ModelUri``, ``Version``,
``PublicationDate``, ``RequiredModel``\\s) and the aliases are recorded in ``extras.opcua``; each
type's ``namespace`` is its namespace URI, the first model's URI is the identity namespace and its
version the API version. The request and response records a method's arguments become are named by
Apiome, so they are stamped ``synthesized`` (:mod:`app.inference_provenance`).

**What is declared, not modelled** lands in ``extras.opcua.capability_limits`` (the coverage
ledger): a reference into a namespace the file does not declare (a ``RequiredModel``), a base
structure referenced by NodeId, a data type with no ``Definition``, unions and option sets, nested
arrays, and the count of instances not promoted.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    EnumValue,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from .inference_provenance import SYNTHESIZED, provenance_extras
from .normalizer import Keys, Normalizer, normalize_ordering
from .opcua_nodeset_parser import (
    BASE_REFERENCE_TYPES,
    FORMAT_KEY,
    INSTANCE_NODE_CLASSES,
    NodeSetDocument,
    UaArgument,
    UaNode,
    namespace_index,
)
from .typescript_types_normalizer import _limits_payload
from .typescript_types_parser import LimitRecorder

__all__ = [
    "BUILTIN_DATA_TYPES",
    "LIMIT_DETAILS",
    "OPCUA_EXTRAS_KEY",
    "OpcUaNodeSetNormalizer",
    "PARTIAL_LIMITS",
    "instance_declaration_ids",
]

#: The root extras key holding the NodeSet projection record.
OPCUA_EXTRAS_KEY = "opcua"

#: ns=0 built-in data types → ``(canonical scalar, format)``.
BUILTIN_DATA_TYPES: Dict[str, Tuple[str, Optional[str]]] = {
    "i=1": ("boolean", None),
    "i=2": ("integer", "int8"),
    "i=3": ("integer", "uint8"),
    "i=4": ("integer", "int16"),
    "i=5": ("integer", "uint16"),
    "i=6": ("integer", "int32"),
    "i=7": ("integer", "uint32"),
    "i=8": ("integer", "int64"),
    "i=9": ("integer", "uint64"),
    "i=10": ("number", "float"),
    "i=11": ("number", "double"),
    "i=12": ("string", None),
    "i=13": ("string", "date-time"),
    "i=14": ("string", "uuid"),
    "i=15": ("bytes", None),
    "i=16": ("string", "xml"),
    "i=17": ("string", "opcua-nodeid"),
    "i=18": ("string", "opcua-expanded-nodeid"),
    "i=19": ("integer", "uint32"),
    "i=20": ("string", "opcua-qualified-name"),
    "i=21": ("string", "opcua-localized-text"),
    "i=22": ("object", None),
    "i=23": ("any", None),
    "i=24": ("any", None),
    "i=25": ("object", None),
    "i=26": ("number", None),
    "i=27": ("integer", None),
    "i=28": ("integer", None),
    "i=29": ("integer", None),
    "i=290": ("number", "double"),
    "i=294": ("string", "date-time"),
    "i=295": ("string", None),
}

#: Base-namespace structures a companion model commonly references, by NodeId, for readable extras.
_BASE_STRUCTURE_NAMES: Dict[str, str] = {
    "i=296": "Argument",
    "i=884": "Range",
    "i=887": "EUInformation",
    "i=7594": "EnumValueType",
    "i=8912": "TimeZoneDataType",
    "i=12755": "OptionSet",
    "i=12756": "Union",
    "i=12878": "ComplexNumberType",
    "i=12880": "XVType",
}

#: Readable names for the ns=0 nodes a nodeset most often points at (built-in data types, base
#: object / variable types, modelling rules), so extras say ``Structure`` rather than ``i=22``.
_BASE_NODE_NAMES: Dict[str, str] = {
    **_BASE_STRUCTURE_NAMES,
    **BASE_REFERENCE_TYPES,
    "i=1": "Boolean",
    "i=2": "SByte",
    "i=3": "Byte",
    "i=4": "Int16",
    "i=5": "UInt16",
    "i=6": "Int32",
    "i=7": "UInt32",
    "i=8": "Int64",
    "i=9": "UInt64",
    "i=10": "Float",
    "i=11": "Double",
    "i=12": "String",
    "i=13": "DateTime",
    "i=14": "Guid",
    "i=15": "ByteString",
    "i=16": "XmlElement",
    "i=17": "NodeId",
    "i=18": "ExpandedNodeId",
    "i=19": "StatusCode",
    "i=20": "QualifiedName",
    "i=21": "LocalizedText",
    "i=22": "Structure",
    "i=23": "DataValue",
    "i=24": "BaseDataType",
    "i=25": "DiagnosticInfo",
    "i=26": "Number",
    "i=27": "Integer",
    "i=28": "UInteger",
    "i=29": "Enumeration",
    "i=290": "Duration",
    "i=294": "UtcTime",
    "i=295": "LocaleId",
    "i=58": "BaseObjectType",
    "i=61": "FolderType",
    "i=62": "BaseVariableType",
    "i=63": "BaseDataVariableType",
    "i=68": "PropertyType",
    "i=2041": "BaseEventType",
    "i=2365": "DataItemType",
    "i=2368": "AnalogItemType",
    "i=17570": "AnalogUnitType",
    "i=78": "Mandatory",
    "i=80": "Optional",
    "i=83": "ExposesItsArray",
    "i=11508": "OptionalPlaceholder",
    "i=11510": "MandatoryPlaceholder",
    "i=84": "Root",
    "i=85": "Objects",
    "i=86": "Types",
    "i=87": "Views",
}

_STRUCTURE = "i=22"
_ENUMERATION = "i=29"
_HAS_SUBTYPE = "i=45"
_HAS_MODELLING_RULE = "i=37"
_HAS_TYPE_DEFINITION = "i=40"
_HAS_PROPERTY = "i=46"
_HAS_ENCODING = "i=38"
#: Hierarchical "child" references a type's instance declarations hang from.
_CHILD_REFERENCES = frozenset({"i=46", "i=47", "i=49", "i=17604"})

#: Modelling rules → (name, nullable, list, min_items).
_MODELLING_RULES: Dict[str, Tuple[str, bool, bool, Optional[int]]] = {
    "i=78": ("Mandatory", False, False, None),
    "i=80": ("Optional", True, False, None),
    "i=83": ("ExposesItsArray", False, False, None),
    "i=11508": ("OptionalPlaceholder", True, True, None),
    "i=11510": ("MandatoryPlaceholder", False, True, 1),
}

#: The declared-limit vocabulary (stable keys → reviewed sentence).
LIMIT_DETAILS: Dict[str, str] = {
    "opcua.unresolved_reference": (
        "A reference to a node in a namespace the nodeset does not declare (usually a "
        "RequiredModel such as DI) cannot be resolved: a field or argument of that type keeps the "
        "NodeId and is typed as any, and a supertype there contributes no inherited fields."
    ),
    "opcua.base_type_not_modelled": (
        "A structure from the OPC UA base namespace (Range, EUInformation …) is referenced by "
        "NodeId rather than modelled. The use site is typed as an opaque object."
    ),
    "opcua.definition_missing": (
        "A structured or enumerated data type with no Definition has no fields or values to read, "
        "so it is modelled empty."
    ),
    "opcua.union": (
        "A union data type is modelled as a record whose fields are all optional; that exactly one "
        "is present is recorded in extras."
    ),
    "opcua.option_set": (
        "An OptionSet data type is modelled as an enumeration of its bits; that the bits combine is recorded in extras."
    ),
    "opcua.multi_dimensional_array": (
        "A value rank above 1 is modelled as nested lists; the per-dimension bounds are kept in extras."
    ),
    "opcua.instances_not_promoted": (
        "Address-space instances (UAObject, UAVariable, UAView and UAMethod nodes that are not a "
        "type's instance declarations) are described in the payload analysis and not promoted to "
        "canonical types."
    ),
}

#: Limits whose construct is still modelled, with only a detail lost.
PARTIAL_LIMITS = frozenset(LIMIT_DETAILS) - {"opcua.instances_not_promoted"}


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------


def _supertype_id(node: UaNode) -> Optional[str]:
    """The supertype a type node names with an inverse ``HasSubtype`` reference."""
    for reference in node.references:
        if reference.reference_type == _HAS_SUBTYPE and not reference.is_forward:
            return reference.target
    return None


def _forward_target(node: UaNode, reference_type: str) -> Optional[str]:
    """The target of the node's first forward reference of ``reference_type``."""
    for reference in node.references:
        if reference.reference_type == reference_type and reference.is_forward:
            return reference.target
    return None


def child_index(document: NodeSetDocument) -> Dict[str, List[str]]:
    """Parent NodeId → the nodes it aggregates, from child references in either direction.

    A nodeset may state a parent → child reference on either end (or both), so both are read; each
    list is de-duplicated and keeps source order. Built once per document, because a large
    address space is walked many times.

    Args:
        document: The parsed nodeset.

    Returns:
        The child lists, keyed by parent NodeId.
    """
    index: Dict[str, List[str]] = {}
    for node in document.nodes:
        for reference in node.references:
            if reference.reference_type not in _CHILD_REFERENCES:
                continue
            parent, child = (
                (node.node_id, reference.target) if reference.is_forward else (reference.target, node.node_id)
            )
            children = index.setdefault(parent, [])
            if child not in children:
                children.append(child)
    return index


def _parents(document: NodeSetDocument) -> Dict[str, str]:
    """Child NodeId → parent NodeId, from child references (either direction) and ``ParentNodeId``."""
    parents: Dict[str, str] = {}
    for node in document.nodes:
        for reference in node.references:
            if reference.reference_type not in _CHILD_REFERENCES:
                continue
            if reference.is_forward:
                parents.setdefault(reference.target, node.node_id)
            else:
                parents.setdefault(node.node_id, reference.target)
    for node in document.nodes:
        if node.parent_node_id:
            parents.setdefault(node.node_id, node.parent_node_id)
    return parents


def instance_declaration_ids(document: NodeSetDocument, children: Optional[Dict[str, List[str]]] = None) -> Set[str]:
    """Every node that belongs to a *type* rather than to the address space.

    An instance declaration is a variable, object or method a type node aggregates, directly or
    through another declaration. The specification asks every declaration to carry a modelling
    rule, but many generated nodesets leave it off; a child of a type is part of the type either
    way, and one without a rule is read as optional. Everything else of an instance node class —
    the children of address-space objects — is an instance.

    Args:
        document: The parsed nodeset.
        children: A prebuilt :func:`child_index`, when the caller has one.

    Returns:
        The NodeIds of the instance declarations.
    """
    children = child_index(document) if children is None else children
    declarations: Set[str] = set()
    pending = [node for node in document.nodes if node.node_class in ("UAObjectType", "UAVariableType", "UADataType")]
    while pending:
        owner = pending.pop()
        for child_id in children.get(owner.node_id, ()):
            child = document.node(child_id)
            if child is None or child.node_id in declarations or child.node_class not in INSTANCE_NODE_CLASSES:
                continue
            declarations.add(child.node_id)
            pending.append(child)
    # A data type's encoding objects ("Default Binary", "Default XML") describe how the type is
    # serialized — part of the type, not of the address space.
    for node in document.nodes:
        if node.node_class != "UADataType":
            continue
        for reference in node.references:
            if reference.reference_type == _HAS_ENCODING and reference.is_forward:
                declarations.add(reference.target)
    for node in document.nodes:
        if node.node_class == "UAObject" and any(
            r.reference_type == _HAS_ENCODING and not r.is_forward for r in node.references
        ):
            declarations.add(node.node_id)
    return declarations


def argument_variable_ids(document: NodeSetDocument, children: Dict[str, List[str]]) -> Set[str]:
    """The ``InputArguments`` / ``OutputArguments`` variables of every method.

    They are a method's signature, read into its operation, never address-space instances.
    """
    ids: Set[str] = set()
    for node in document.nodes:
        if node.node_class != "UAMethod":
            continue
        for child_id in children.get(node.node_id, ()):
            child = document.node(child_id)
            if (
                child is not None
                and child.node_class == "UAVariable"
                and child.name
                in (
                    "InputArguments",
                    "OutputArguments",
                )
            ):
                ids.add(child_id)
    return ids


# ---------------------------------------------------------------------------
# The normalizer
# ---------------------------------------------------------------------------


class _Model:
    """One nodeset's walk to canonical types, operations and declared limits."""

    def __init__(self, document: NodeSetDocument) -> None:
        self.document = document
        self.limits = LimitRecorder(details=LIMIT_DETAILS)
        self.children = child_index(document)
        self.declarations = instance_declaration_ids(document, self.children)
        self.arguments = argument_variable_ids(document, self.children)
        self.parents = _parents(document)
        self.keys: Dict[str, str] = {}
        self.types: Dict[str, Type] = {}
        self._fields_cache: Dict[str, List[CanonicalField]] = {}
        self._claim_type_keys()

    # --- naming ---------------------------------------------------------------------------

    def _claim_type_keys(self) -> None:
        """Give every type node a unique canonical key, declared order first."""
        taken: Set[str] = set()
        for node in self.document.nodes:
            if node.node_class not in ("UAObjectType", "UAVariableType", "UADataType"):
                continue
            key = Keys.type(node.name)
            if key in taken:
                key = Keys.type(f"{node.name}_{node.node_class[2:]}")
            suffix = 2
            base = key
            while key in taken:
                key = f"{base}_{suffix}"
                suffix += 1
            taken.add(key)
            self.keys[node.node_id] = key

    def claim(self, name: str) -> str:
        """A unique key for a type Apiome synthesizes (method argument records)."""
        key = Keys.type(name)
        suffix = 2
        while key in self.types or key in self.keys.values():
            key = Keys.type(f"{name}_{suffix}")
            suffix += 1
        return key

    def display(self, node_id: Optional[str]) -> Optional[str]:
        """A NodeId's browse name when the document declares it, else the NodeId."""
        node = self.document.node(node_id)
        if node is not None:
            return node.name
        if node_id in _BASE_NODE_NAMES:
            return _BASE_NODE_NAMES[node_id]
        return node_id

    # --- type references --------------------------------------------------------------------

    def scalar_ref(self, data_type: Optional[str], *, location: str) -> Tuple[TypeRef, Optional[str]]:
        """Resolve a data type NodeId to a canonical reference plus an optional ``format``.

        Args:
            data_type: The data type's canonical NodeId.
            location: The use site, for declared-limit locations.

        Returns:
            ``(reference, format)``.
        """
        if not data_type:
            return TypeRef(name="any", nullable=False), None
        if data_type in self.keys:
            return TypeRef(name=self.keys[data_type], nullable=False), None
        if data_type in BUILTIN_DATA_TYPES:
            name, fmt = BUILTIN_DATA_TYPES[data_type]
            return TypeRef(name=name, nullable=False), fmt
        if namespace_index(data_type) == 0:
            self.limits.record("opcua.base_type_not_modelled", location=location)
            extras: Dict[str, Any] = {"opcua_data_type": data_type}
            if data_type in _BASE_STRUCTURE_NAMES:
                extras["opcua_base_type"] = _BASE_STRUCTURE_NAMES[data_type]
            return TypeRef(name="object", nullable=False, extras=extras), None
        self.limits.record("opcua.unresolved_reference", location=location)
        unresolved: Dict[str, Any] = {"opcua_unresolved": data_type}
        uri = self.document.namespace_uri(data_type)
        if uri:
            unresolved["opcua_namespace"] = uri
        return TypeRef(name="any", nullable=False, extras=unresolved), None

    def ranked(
        self,
        data_type: Optional[str],
        value_rank: int,
        dimensions: Sequence[int],
        *,
        location: str,
        nullable: bool = False,
    ) -> Tuple[TypeRef, Optional[Constraints], Dict[str, Any]]:
        """A data type at a value rank: the reference, its constraints and rank extras.

        Args:
            data_type: The element data type NodeId.
            value_rank: The OPC UA ``ValueRank``.
            dimensions: ``ArrayDimensions`` (``0`` = unbounded).
            location: The use site.
            nullable: Whether the use site may be absent.

        Returns:
            ``(reference, constraints, extras)``.
        """
        ref, fmt = self.scalar_ref(data_type, location=location)
        extras: Dict[str, Any] = {}
        max_items: Optional[int] = None
        if value_rank in (0, 1):
            ref = TypeRef(item=ref, nullable=False)
            if dimensions and dimensions[0] > 0:
                max_items = dimensions[0]
        elif value_rank > 1:
            self.limits.record("opcua.multi_dimensional_array", location=location)
            for _ in range(value_rank):
                ref = TypeRef(item=ref, nullable=False)
            if dimensions:
                extras["opcua_array_dimensions"] = list(dimensions)
        elif value_rank in (-2, -3):
            extras["opcua_value_rank"] = value_rank
        constraints = None
        if fmt or max_items is not None:
            constraints = Constraints(format=fmt, max_items=max_items)
        return ref.model_copy(update={"nullable": nullable}), constraints, extras

    # --- object types ------------------------------------------------------------------------

    def declaration_field(self, owner_key: str, child: UaNode) -> Optional[CanonicalField]:
        """One instance declaration of a type as a field of its record."""
        rule_id = _forward_target(child, _HAS_MODELLING_RULE)
        # No modelling rule: part of the type, but not promised on every instance — optional.
        rule_name, nullable, as_list, min_items = _MODELLING_RULES.get(
            rule_id or "", (self.display(rule_id) or "None", True, False, None)
        )
        location = f"{owner_key}.{child.name}"
        constraints: Optional[Constraints] = None
        extras: Dict[str, Any] = {
            "native_id": child.node_id,
            "opcua_node_class": child.node_class[2:],
            "opcua_modelling_rule": rule_name,
        }
        type_definition = _forward_target(child, _HAS_TYPE_DEFINITION)
        if type_definition:
            extras["opcua_type_definition"] = self.display(type_definition)
        if child.line:
            extras["source_location"] = f"{child.line}:1"
        if child.node_class == "UAVariable":
            ref, constraints, rank_extras = self.ranked(
                child.data_type, child.value_rank, child.array_dimensions, location=location
            )
            extras.update(rank_extras)
            if self._is_property(child):
                extras["opcua_property"] = True
        else:
            if type_definition and type_definition in self.keys:
                ref = TypeRef(name=self.keys[type_definition], nullable=False)
            else:
                ref = TypeRef(name="object", nullable=False)
        if as_list:
            ref = TypeRef(item=ref.model_copy(update={"nullable": False}), nullable=False)
            if min_items is not None:
                constraints = (constraints or Constraints()).model_copy(update={"min_items": min_items})
        return CanonicalField(
            key=Keys.field(owner_key, child.name),
            name=child.name,
            type=ref.model_copy(update={"nullable": nullable}),
            constraints=constraints,
            description=child.description,
            extras=extras,
        )

    def note_unresolved_supertype(self, node: UaNode, key: str) -> None:
        """Declare a supertype that lives in a namespace the file does not declare (a RequiredModel).

        Its fields cannot be inherited, so the type is modelled with its own declarations only.
        """
        supertype = _supertype_id(node)
        if supertype and namespace_index(supertype) != 0 and self.document.node(supertype) is None:
            self.limits.record("opcua.unresolved_reference", location=key)

    def _is_property(self, child: UaNode) -> bool:
        """Whether ``child`` hangs from its parent by ``HasProperty`` (stated on either end)."""
        parent_id = self.parents.get(child.node_id)
        if any(
            r.reference_type == _HAS_PROPERTY and not r.is_forward and r.target == parent_id for r in child.references
        ):
            return True
        parent = self.document.node(parent_id)
        return parent is not None and any(
            r.reference_type == _HAS_PROPERTY and r.is_forward and r.target == child.node_id for r in parent.references
        )

    def object_type_fields(self, node: UaNode, chain: Tuple[str, ...] = ()) -> List[CanonicalField]:
        """An object type's fields: its supertype's (when declared here), then its own declarations."""
        if node.node_id in self._fields_cache:
            return self._fields_cache[node.node_id]
        key = self.keys[node.node_id]
        fields: Dict[str, CanonicalField] = {}
        self.note_unresolved_supertype(node, key)
        supertype = self.document.node(_supertype_id(node))
        if supertype is not None and supertype.node_class == "UAObjectType" and supertype.node_id not in chain:
            for inherited in self.object_type_fields(supertype, chain + (node.node_id,)):
                fields[inherited.name] = inherited.model_copy(
                    update={
                        "key": Keys.field(key, inherited.name),
                        # The type that declares the field, however many levels up it is.
                        "extras": {"opcua_inherited_from": supertype.name, **inherited.extras},
                    }
                )
        for child_id in self.children.get(node.node_id, ()):
            child = self.document.node(child_id)
            if child is None or child.node_id not in self.declarations:
                continue
            if child.node_class not in ("UAVariable", "UAObject"):
                continue
            field = self.declaration_field(key, child)
            if field is not None:
                fields[field.name] = field
        result = list(fields.values())
        self._fields_cache[node.node_id] = result
        return result

    # --- types -------------------------------------------------------------------------------

    def type_extras(self, node: UaNode) -> Dict[str, Any]:
        """The extras every type carries: identity, abstractness, supertype and references."""
        extras: Dict[str, Any] = {
            "native_id": node.node_id,
            "opcua_node_class": node.node_class[2:],
            "opcua_browse_name": node.browse_name,
        }
        if node.is_abstract:
            extras["opcua_abstract"] = True
        supertype = _supertype_id(node)
        if supertype:
            extras["opcua_supertype"] = self.display(supertype)
        if node.references:
            extras["opcua_references"] = [
                {
                    "referenceType": reference.reference_name,
                    "target": reference.target,
                    **(
                        {"targetName": self.display(reference.target)}
                        if self.display(reference.target) != reference.target
                        else {}
                    ),
                    "isForward": reference.is_forward,
                }
                for reference in node.references
            ]
        if node.line:
            extras["source_location"] = f"{node.line}:1"
        if node.source_file:
            extras["source_file"] = node.source_file
        return extras

    def object_type(self, node: UaNode) -> Type:
        """A ``UAObjectType`` as a record of its instance declarations."""
        return Type(
            key=self.keys[node.node_id],
            name=node.name,
            kind=TypeKind.RECORD,
            namespace=self.document.namespace_uri(node.node_id),
            description=node.description,
            fields=self.object_type_fields(node),
            extras=self.type_extras(node),
        )

    def variable_type(self, node: UaNode) -> Type:
        """A ``UAVariableType`` as an alias of its data type at its value rank."""
        key = self.keys[node.node_id]
        ref, constraints, rank_extras = self.ranked(
            node.data_type, node.value_rank, node.array_dimensions, location=key
        )
        extras = {**self.type_extras(node), **rank_extras}
        declared = [
            child.name
            for child in (self.document.node(c) for c in self.children.get(node.node_id, ()))
            if child is not None and child.node_id in self.declarations
        ]
        if declared:
            extras["opcua_declarations"] = declared
        return Type(
            key=key,
            name=node.name,
            kind=TypeKind.ALIAS,
            namespace=self.document.namespace_uri(node.node_id),
            description=node.description,
            aliased=ref,
            constraints=constraints,
            extras=extras,
        )

    def _inherits(self, node: UaNode, ancestor: str) -> bool:
        """Whether a data type's supertype chain reaches ``ancestor`` (a NodeId)."""
        seen: Set[str] = set()
        current: Optional[str] = _supertype_id(node)
        while current and current not in seen:
            if current == ancestor:
                return True
            seen.add(current)
            parent = self.document.node(current)
            current = _supertype_id(parent) if parent is not None else None
        return False

    def _base_scalar(self, node: UaNode) -> Optional[str]:
        """The first supertype that is a built-in scalar or another declared data type."""
        current = _supertype_id(node)
        if current and (current in BUILTIN_DATA_TYPES or current in self.keys or namespace_index(current) != 0):
            return current
        return None

    def data_type(self, node: UaNode) -> Type:
        """A ``UADataType`` as a record, enumeration or alias."""
        key = self.keys[node.node_id]
        extras = self.type_extras(node)
        common: Dict[str, Any] = {
            "key": key,
            "name": node.name,
            "namespace": self.document.namespace_uri(node.node_id),
            "description": node.description,
        }
        definition = node.definition
        is_enum = self._inherits(node, _ENUMERATION) or (
            definition is not None and definition.fields and all(f.value is not None for f in definition.fields)
        )
        if definition is not None and (is_enum or definition.is_option_set):
            if definition.is_option_set:
                self.limits.record("opcua.option_set", location=key)
                extras["opcua_option_set"] = True
            values = [
                EnumValue(key=f"{key}.{item.name}", name=item.name, value=item.value, description=item.description)
                for item in definition.fields
            ]
            return Type(kind=TypeKind.ENUM, enum_values=values, extras=extras, **common)
        if definition is not None:
            if definition.is_union:
                self.limits.record("opcua.union", location=key)
                extras["opcua_union"] = True
            fields = []
            for item in definition.fields:
                ref, constraints, rank_extras = self.ranked(
                    item.data_type,
                    item.value_rank,
                    item.array_dimensions,
                    location=f"{key}.{item.name}",
                    nullable=item.is_optional or definition.is_union,
                )
                fields.append(
                    CanonicalField(
                        key=Keys.field(key, item.name),
                        name=item.name,
                        type=ref,
                        constraints=constraints,
                        description=item.description,
                        extras=rank_extras,
                    )
                )
            return Type(kind=TypeKind.RECORD, fields=fields, extras=extras, **common)
        if is_enum or self._inherits(node, _STRUCTURE) or _supertype_id(node) == _STRUCTURE:
            self.limits.record("opcua.definition_missing", location=key)
            if is_enum:
                return Type(kind=TypeKind.ENUM, extras=extras, **common)
            return Type(kind=TypeKind.RECORD, extras=extras, **common)
        ref, constraints, _ = self.ranked(self._base_scalar(node), -1, (), location=key)
        return Type(kind=TypeKind.ALIAS, aliased=ref, constraints=constraints, extras=extras, **common)

    # --- methods -----------------------------------------------------------------------------

    def method_arguments(self, method: UaNode) -> Tuple[Tuple[UaArgument, ...], Tuple[UaArgument, ...]]:
        """A method's input and output arguments, read from its argument variables."""
        inputs: Tuple[UaArgument, ...] = ()
        outputs: Tuple[UaArgument, ...] = ()
        for child_id in self.children.get(method.node_id, ()):
            child = self.document.node(child_id)
            if child is None or child.node_class != "UAVariable":
                continue
            if child.name == "InputArguments":
                inputs = child.arguments
            elif child.name == "OutputArguments":
                outputs = child.arguments
        return inputs, outputs

    def argument_record(self, owner: str, method: UaNode, role: str, arguments: Sequence[UaArgument]) -> str:
        """Build the synthesized request or response record of a method's arguments."""
        key = self.claim(f"{owner}_{method.name}_{role}")
        fields = []
        for argument in arguments:
            ref, constraints, rank_extras = self.ranked(
                argument.data_type,
                argument.value_rank,
                argument.array_dimensions,
                location=f"{owner}.{method.name}",
            )
            fields.append(
                CanonicalField(
                    key=Keys.field(key, argument.name),
                    name=argument.name,
                    type=ref,
                    constraints=constraints,
                    description=argument.description,
                    extras=rank_extras,
                )
            )
        which = "input" if role == "Request" else "output"
        self.types[key] = Type(
            key=key,
            name=key,
            kind=TypeKind.RECORD,
            fields=fields,
            extras={
                "opcua_method": method.node_id,
                **provenance_extras(
                    SYNTHESIZED,
                    f"Named by Apiome for the {which} arguments of method {owner}.{method.name}.",
                ),
            },
        )
        return key

    def operation(self, owner: str, service_key: str, method: UaNode) -> Operation:
        """A ``UAMethod`` as an RPC operation with request / response records."""
        op_key = Keys.operation_rpc(service_key, method.name)
        inputs, outputs = self.method_arguments(method)
        messages: List[Message] = []
        if inputs:
            messages.append(
                Message(
                    key=Keys.request_message(op_key),
                    role=MessageRole.REQUEST,
                    payload=TypeRef(name=self.argument_record(owner, method, "Request", inputs), nullable=False),
                    required=True,
                )
            )
        if outputs:
            messages.append(
                Message(
                    key=f"{op_key}#response",
                    role=MessageRole.RESPONSE,
                    payload=TypeRef(name=self.argument_record(owner, method, "Response", outputs), nullable=False),
                )
            )
        extras: Dict[str, Any] = {"native_id": method.node_id}
        rule = _forward_target(method, _HAS_MODELLING_RULE)
        if rule:
            extras["opcua_modelling_rule"] = _MODELLING_RULES.get(rule, (self.display(rule),))[0]
        if method.line:
            extras["source_location"] = f"{method.line}:1"
        return Operation(
            key=op_key,
            name=method.name,
            kind=OperationKind.REQUEST_RESPONSE,
            streaming=StreamingMode.NONE,
            description=method.description,
            messages=messages,
            extras=extras,
        )

    def services(self, fallback_name: str) -> List[Service]:
        """One service per node that owns methods: a type's methods, or an instance's own ones.

        An instance method that copies a type's declaration (``MethodDeclarationId``) is the type's
        method again and is not repeated.
        """
        services: Dict[str, Service] = {}
        for method in self.document.nodes:
            if method.node_class != "UAMethod" or method.method_declaration_id:
                continue
            owner_node = self.document.node(self.parents.get(method.node_id))
            if owner_node is not None and owner_node.node_class == "UAObjectType":
                owner = owner_node.name
                service_key = self.keys.get(owner_node.node_id, Keys.type(owner))
            elif owner_node is not None and owner_node.node_id not in self.declarations:
                owner = owner_node.name
                service_key = Keys.type(owner)
            elif owner_node is None:
                owner = fallback_name
                service_key = Keys.type(fallback_name)
            else:
                continue  # a method declared under another declaration, read with its type
            if service_key not in services:
                services[service_key] = Service(
                    key=service_key,
                    name=owner,
                    extras={
                        "native_id": owner_node.node_id if owner_node else None,
                        "opcua_node_class": owner_node.node_class[2:] if owner_node else None,
                    },
                )
            service = services[service_key]
            services[service_key] = service.model_copy(
                update={"operations": [*service.operations, self.operation(owner, service_key, method)]}
            )
        return list(services.values())

    # --- instances ------------------------------------------------------------------------------

    def record_instances(self) -> int:
        """Record the address-space instances the model does not promote; return their count."""
        count = 0
        for node in self.document.nodes:
            if node.node_id in self.declarations or node.node_id in self.arguments:
                continue
            if node.node_class in ("UAObject", "UAVariable", "UAView"):
                self.limits.record("opcua.instances_not_promoted")
                count += 1
            elif node.node_class == "UAMethod" and node.method_declaration_id:
                self.limits.record("opcua.instances_not_promoted")
                count += 1
        return count


def _model_record(document: NodeSetDocument) -> List[Dict[str, Any]]:
    """The ``Models`` section as provenance."""
    return [
        {
            "model_uri": model.model_uri,
            "version": model.version,
            "publication_date": model.publication_date,
            "required_models": [
                {"model_uri": uri, "version": version, "publication_date": date}
                for uri, version, date in model.required_models
            ],
        }
        for model in document.models
    ]


def _identity_name(document: NodeSetDocument) -> str:
    """A readable API name: the last path segment of the first model URI (else of the first
    namespace URI), else the source label."""
    uri = document.models[0].model_uri if document.models else next(iter(document.namespace_uris), "")
    if uri:
        trimmed = uri.rstrip("/")
        tail = trimmed.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        return tail or trimmed
    return document.source_label or "OPC UA NodeSet"


class OpcUaNodeSetNormalizer(Normalizer, register=True):
    """Normalize a parsed NodeSet2 document into a :class:`CanonicalApi`."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.RPC

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map a :class:`~app.opcua_nodeset_parser.NodeSetDocument` to the canonical model.

        Args:
            source: The parsed nodeset.
            include_raw: Whether to keep the source text on ``raw``.

        Returns:
            The canonical model.

        Raises:
            ValueError: When ``source`` is not a parsed nodeset.
        """
        if not isinstance(source, NodeSetDocument):
            raise ValueError("OPC UA source must be a NodeSetDocument (see app.opcua_nodeset_parser.parse_nodeset)")
        model = _Model(source)
        for node in source.nodes:
            if node.node_class == "UAObjectType":
                model.types[model.keys[node.node_id]] = model.object_type(node)
            elif node.node_class == "UAVariableType":
                model.types[model.keys[node.node_id]] = model.variable_type(node)
            elif node.node_class == "UADataType":
                model.types[model.keys[node.node_id]] = model.data_type(node)
        name = _identity_name(source)
        services = model.services(name)
        instance_count = model.record_instances()

        counts: Dict[str, int] = {}
        for node in source.nodes:
            counts[node.node_class] = counts.get(node.node_class, 0) + 1
        record: Dict[str, Any] = {
            "namespace_uris": list(source.namespace_uris),
            "models": _model_record(source),
            "aliases": dict(source.aliases),
            "reference_types": [
                {
                    "name": node.name,
                    "native_id": node.node_id,
                    "inverse_name": node.inverse_name,
                    "symmetric": node.symmetric,
                    "abstract": node.is_abstract,
                    "supertype": model.display(_supertype_id(node)),
                }
                for node in source.nodes
                if node.node_class == "UAReferenceType"
            ],
            "node_counts": dict(sorted(counts.items())),
            "instance_count": instance_count,
            "capability_limits": _limits_payload(model.limits.limits()),
        }
        first_model = source.models[0] if source.models else None
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol="opcua",
            identity=ApiIdentity(
                name=name,
                namespace=first_model.model_uri
                if first_model
                else (source.namespace_uris[0] if source.namespace_uris else None),
            ),
            version=first_model.version if first_model else None,
            title=name,
            services=services,
            types=list(model.types.values()),
            raw={"nodeset": source.raw} if include_raw else None,
            extras={OPCUA_EXTRAS_KEY: record},
        )
        return normalize_ordering(api)
