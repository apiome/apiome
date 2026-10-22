"""OPC UA NodeSet2 parser — FMT-9.1 (#5468).

A NodeSet2 file is the XML serialization of an OPC UA *information model*: the object types,
variable types, data types, methods and reference types a server's address space is built from,
plus (optionally) the address-space instances themselves.

.. code-block:: text

    UANodeSet
      NamespaceUris   Uri …               (namespace index 1, 2, … — index 0 is the OPC UA base)
      Models          Model (ModelUri · Version · PublicationDate) → RequiredModel …
      Aliases         Alias (Boolean = i=1, HasComponent = i=47 …)
      UAObjectType · UAVariableType · UADataType (→ Definition → Field …) · UAReferenceType
      UAMethod · UAObject · UAVariable · UAView
        References    Reference (ReferenceType · IsForward · target NodeId)

This module reads that XML into a small, immutable AST; :mod:`app.opcua_nodeset_normalizer` maps
it onto the canonical model and :mod:`app.opcua_nodeset_analysis` describes it as a payload
analysis. The parser resolves **aliases** and the ``ns=0;`` spelling so every NodeId the rest of
the pipeline sees is in one canonical form (``i=47``, ``ns=1;i=1001``), and it reads a method's
``InputArguments`` / ``OutputArguments`` out of their ``ListOfExtensionObject`` values.

XML goes through :func:`app.secure_xml.parse_xml`: no DTD, no entity expansion, no external
references, a byte and depth ceiling. **Errors** are :class:`NodeSetParseError`:

* ``INPUT_EMPTY`` — the document is empty;
* ``FORMAT_MISMATCH`` — the text is not XML, or its root is not ``UANodeSet``;
* ``INPUT_MALFORMED`` / ``INPUT_TRUNCATED`` — the XML is not well formed (or ends early);
* ``INPUT_SEMANTIC_INVALID`` — a node without a ``NodeId`` or ``BrowseName``, a duplicate
  ``NodeId``, or a nodeset that declares no node at all;
* ``INPUT_REFERENCE_UNRESOLVED`` — a reference to a node in one of the nodeset's **own**
  namespaces (the namespaces its ``Models`` define; the first ``NamespaceUris`` entry when it
  declares none) that no node declares, or a NodeId whose namespace index has no URI. A
  reference into another namespace — a ``RequiredModel`` such as DI — is not an error: the
  normalizer declares it unresolved.

A guard code from :mod:`app.secure_xml` (``INPUT_UNSAFE_CONSTRUCT``, ``INPUT_TOO_LARGE``,
``INPUT_DEPTH_LIMIT``) is kept as is, and an encoding fault is refused code-less so the import
pipeline's encoding rule names it.

**Filesets.** A companion specification usually ships as several NodeSet2 files: the model and
the models it requires. :func:`parse_nodeset_fileset` reads every member and merges them into
one document. Each file numbers its namespaces in its own ``NamespaceUris`` table, so every
member's NodeIds are re-indexed, by URI, into the root's table before the merge.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from typing import Dict, Iterable, List, Mapping, Optional, Set, Tuple

from .secure_xml import SecureXmlError, parse_xml

__all__ = [
    "BASE_REFERENCE_TYPES",
    "FORMAT_KEY",
    "INSTANCE_NODE_CLASSES",
    "NODESET_NAMESPACE",
    "NODE_CLASSES",
    "OPCUA_BASE_NAMESPACE",
    "TYPE_NODE_CLASSES",
    "NodeSetDocument",
    "NodeSetParseError",
    "UaArgument",
    "UaDefinition",
    "UaDefinitionField",
    "UaModel",
    "UaNode",
    "UaReference",
    "canonical_node_id",
    "declares_nodeset_namespace",
    "is_nodeset",
    "local_name",
    "namespace_index",
    "own_namespace_uris",
    "parse_nodeset",
    "parse_nodeset_fileset",
    "split_browse_name",
]

#: The adapter / canonical format key.
FORMAT_KEY = "opcua-nodeset"

#: The NodeSet2 schema namespace (``UANodeSet.xsd``).
NODESET_NAMESPACE = "http://opcfoundation.org/UA/2011/03/UANodeSet.xsd"

#: Namespace index 0 — the OPC UA base information model every nodeset builds on.
OPCUA_BASE_NAMESPACE = "http://opcfoundation.org/UA/"

#: The node elements a NodeSet2 file may carry, in the order the analysis lists them.
NODE_CLASSES: Tuple[str, ...] = (
    "UAObjectType",
    "UAVariableType",
    "UADataType",
    "UAReferenceType",
    "UAMethod",
    "UAObject",
    "UAVariable",
    "UAView",
)

#: Node classes that define types (the canonical model's raw material).
TYPE_NODE_CLASSES = frozenset({"UAObjectType", "UAVariableType", "UADataType", "UAReferenceType"})

#: Node classes that describe the address space (instances, or a type's instance declarations).
INSTANCE_NODE_CLASSES = frozenset({"UAObject", "UAVariable", "UAView", "UAMethod"})

#: Well-known ns=0 reference types, so a reference reads as ``HasComponent`` rather than ``i=47``
#: even in a nodeset that declares no alias for it.
BASE_REFERENCE_TYPES: Mapping[str, str] = {
    "i=31": "References",
    "i=32": "NonHierarchicalReferences",
    "i=33": "HierarchicalReferences",
    "i=34": "HasChild",
    "i=35": "Organizes",
    "i=36": "HasEventSource",
    "i=37": "HasModellingRule",
    "i=38": "HasEncoding",
    "i=39": "HasDescription",
    "i=40": "HasTypeDefinition",
    "i=41": "GeneratesEvent",
    "i=44": "Aggregates",
    "i=45": "HasSubtype",
    "i=46": "HasProperty",
    "i=47": "HasComponent",
    "i=48": "HasNotifier",
    "i=49": "HasOrderedComponent",
    "i=17603": "HasInterface",
    "i=17604": "HasAddIn",
}

#: Well-known ns=0 data types by name, for a nodeset that writes ``DataType="Double"`` without
#: declaring the alias.
_BASE_DATA_TYPES: Mapping[str, str] = {
    "Boolean": "i=1",
    "SByte": "i=2",
    "Byte": "i=3",
    "Int16": "i=4",
    "UInt16": "i=5",
    "Int32": "i=6",
    "UInt32": "i=7",
    "Int64": "i=8",
    "UInt64": "i=9",
    "Float": "i=10",
    "Double": "i=11",
    "String": "i=12",
    "DateTime": "i=13",
    "Guid": "i=14",
    "ByteString": "i=15",
    "XmlElement": "i=16",
    "NodeId": "i=17",
    "ExpandedNodeId": "i=18",
    "StatusCode": "i=19",
    "QualifiedName": "i=20",
    "LocalizedText": "i=21",
    "Structure": "i=22",
    "DataValue": "i=23",
    "BaseDataType": "i=24",
    "DiagnosticInfo": "i=25",
    "Number": "i=26",
    "Integer": "i=27",
    "UInteger": "i=28",
    "Enumeration": "i=29",
    "Duration": "i=290",
    "UtcTime": "i=294",
    "LocaleId": "i=295",
    "Argument": "i=296",
    "Range": "i=884",
    "EUInformation": "i=887",
}

#: Standard names → ns=0 NodeIds, used when a name is not declared as an alias.
_BASE_NAMES: Mapping[str, str] = {
    **{name: node_id for node_id, name in BASE_REFERENCE_TYPES.items()},
    **_BASE_DATA_TYPES,
}

_TRUNCATION_MESSAGES = ("no element found", "unclosed token")
_ENCODING_FAULT_MARKERS = ("\x00", "\ufffd")
_ENCODING_WINDOW = 1024
_SNIFF_WINDOW = 65536
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_FIRST_ELEMENT_RE = re.compile(r"<(?![?!])")
_ROOT_RE = re.compile(r"<(?:[A-Za-z_][\w.-]*:)?UANodeSet[\s>/]")
_NODE_LINE_RE = re.compile(r"<(?:[A-Za-z_][\w.-]*:)?(UA[A-Za-z]+)\b[^>]*?\bNodeId=\"([^\"]+)\"")
_NODE_ID_RE = re.compile(r"^(?:ns=(\d+);)?([isgb])=(.+)$", re.DOTALL)
_BROWSE_NAME_RE = re.compile(r"^(\d+):(.*)$", re.DOTALL)


class NodeSetParseError(ValueError):
    """Raised when text is not a readable NodeSet2 document.

    Attributes:
        code: The intake-taxonomy code.
    """

    def __init__(self, message: str, *, code: Optional[str]) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class UaReference:
    """One ``Reference`` of a node.

    Attributes:
        reference_type: The reference type's canonical NodeId (``i=47``).
        reference_name: Its readable name (``HasComponent``), from the alias, the ns=0 table or
            a ``UAReferenceType`` in the document; the NodeId when none names it.
        target: The target node's canonical NodeId.
        is_forward: ``False`` for an inverse reference (``IsForward="false"``).
    """

    reference_type: str
    reference_name: str
    target: str
    is_forward: bool = True


@dataclass(frozen=True)
class UaDefinitionField:
    """One ``Field`` of a ``UADataType`` ``Definition``.

    Attributes:
        name: The field name.
        data_type: The field's data type NodeId (``None`` for an enumeration value).
        value_rank: ``-1`` scalar, ``1`` one-dimensional array, ``n > 1`` n dimensions, ``0``
            one or more dimensions, ``-2`` any, ``-3`` scalar or one dimension.
        array_dimensions: The declared maximum length per dimension (``0`` = unbounded).
        is_optional: ``IsOptional="true"`` — the field may be absent.
        value: The integer value of an enumeration or option-set member.
        description: The field's description text.
    """

    name: str
    data_type: Optional[str] = None
    value_rank: int = -1
    array_dimensions: Tuple[int, ...] = ()
    is_optional: bool = False
    value: Optional[int] = None
    description: Optional[str] = None


@dataclass(frozen=True)
class UaDefinition:
    """A ``UADataType``'s ``Definition``.

    Attributes:
        name: The definition's ``Name`` (usually the browse name).
        fields: Its fields in source order.
        is_union: ``IsUnion="true"`` — exactly one field is present.
        is_option_set: ``IsOptionSet="true"`` — the fields are bit positions of a flag set.
    """

    name: str
    fields: Tuple[UaDefinitionField, ...] = ()
    is_union: bool = False
    is_option_set: bool = False


@dataclass(frozen=True)
class UaArgument:
    """One method argument read from an ``InputArguments`` / ``OutputArguments`` value.

    Attributes:
        name: The argument name.
        data_type: Its data type NodeId.
        value_rank: As :attr:`UaDefinitionField.value_rank`.
        array_dimensions: As :attr:`UaDefinitionField.array_dimensions`.
        description: Its description text.
    """

    name: str
    data_type: Optional[str] = None
    value_rank: int = -1
    array_dimensions: Tuple[int, ...] = ()
    description: Optional[str] = None


@dataclass(frozen=True)
class UaNode:
    """One node element of the nodeset.

    Attributes:
        node_class: The element name (``UAObjectType``, ``UAVariable`` …).
        node_id: The canonical NodeId.
        browse_name: The ``BrowseName`` as written (``1:PumpType``).
        display_name: The first ``DisplayName`` text.
        description: The first ``Description`` text.
        parent_node_id: ``ParentNodeId``, when declared.
        data_type: ``DataType`` (variables, variable types), as a canonical NodeId.
        value_rank: ``ValueRank`` (default ``-1``).
        array_dimensions: ``ArrayDimensions``.
        is_abstract: ``IsAbstract="true"``.
        symmetric: ``Symmetric="true"`` (reference types).
        inverse_name: ``InverseName`` text (reference types).
        method_declaration_id: ``MethodDeclarationId`` (an instance method's type declaration).
        references: The node's references in source order.
        definition: A data type's ``Definition``.
        arguments: For an ``InputArguments`` / ``OutputArguments`` variable, the arguments its
            value lists.
        line: The 1-based source line of the node element, when it could be located.
        source_file: The fileset member the node was read from (``None`` for a single file).
    """

    node_class: str
    node_id: str
    browse_name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    parent_node_id: Optional[str] = None
    data_type: Optional[str] = None
    value_rank: int = -1
    array_dimensions: Tuple[int, ...] = ()
    is_abstract: bool = False
    symmetric: bool = False
    inverse_name: Optional[str] = None
    method_declaration_id: Optional[str] = None
    references: Tuple[UaReference, ...] = ()
    definition: Optional[UaDefinition] = None
    arguments: Tuple[UaArgument, ...] = ()
    line: Optional[int] = None
    source_file: Optional[str] = None

    @property
    def name(self) -> str:
        """The browse name without its namespace-index prefix (``PumpType``)."""
        return split_browse_name(self.browse_name)[1]


@dataclass(frozen=True)
class UaModel:
    """One ``Model`` the nodeset defines.

    Attributes:
        model_uri: ``ModelUri`` — the namespace the model defines.
        version: ``Version``.
        publication_date: ``PublicationDate``.
        required_models: ``(ModelUri, Version, PublicationDate)`` of each ``RequiredModel``.
    """

    model_uri: str
    version: Optional[str] = None
    publication_date: Optional[str] = None
    required_models: Tuple[Tuple[str, Optional[str], Optional[str]], ...] = ()


@dataclass(frozen=True)
class NodeSetDocument:
    """A parsed NodeSet2 document.

    Attributes:
        namespace_uris: ``NamespaceUris`` in index order; index 1 is the first entry.
        models: The ``Models`` it defines.
        aliases: Alias → canonical NodeId, in source order.
        nodes: Every node element, in source order.
        raw: The source text, kept for the payload analysis's source hash.
        source_label: The filename / paste label, when known.
        last_modified: ``LastModified`` on the root, when declared.
    """

    namespace_uris: Tuple[str, ...]
    models: Tuple[UaModel, ...]
    aliases: Tuple[Tuple[str, str], ...]
    nodes: Tuple[UaNode, ...]
    raw: str = ""
    source_label: Optional[str] = None
    last_modified: Optional[str] = None
    _by_id: Dict[str, UaNode] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        self._by_id.update({node.node_id: node for node in self.nodes})

    def node(self, node_id: Optional[str]) -> Optional[UaNode]:
        """Return the node with ``node_id``, or ``None`` when the document does not declare it."""
        return self._by_id.get(node_id) if node_id else None

    def namespace_uri(self, node_id: Optional[str]) -> Optional[str]:
        """The namespace URI a NodeId lives in (``ns=1;…`` → the first ``NamespaceUris`` entry).

        Returns:
            The URI, :data:`OPCUA_BASE_NAMESPACE` for index 0, or ``None`` for an index the
            document does not declare.
        """
        index = namespace_index(node_id)
        if index == 0:
            return OPCUA_BASE_NAMESPACE
        if 0 < index <= len(self.namespace_uris):
            return self.namespace_uris[index - 1]
        return None


# ---------------------------------------------------------------------------
# NodeIds, browse names and element helpers
# ---------------------------------------------------------------------------


def local_name(tag: str) -> str:
    """An element or attribute name without its ``{namespace}`` prefix."""
    return tag.rsplit("}", 1)[-1]


def canonical_node_id(text: Optional[str]) -> Optional[str]:
    """Normalize a NodeId's spelling: ``ns=0;i=45`` → ``i=45``; whitespace trimmed.

    Args:
        text: The NodeId as written.

    Returns:
        The canonical NodeId, or ``None`` for an empty value. A value that is not a NodeId (an
        unresolved alias) is returned trimmed, unchanged.
    """
    if text is None:
        return None
    value = text.strip()
    if not value:
        return None
    match = _NODE_ID_RE.match(value)
    if not match:
        return value
    ns, kind, ident = match.groups()
    if ns in (None, "0"):
        return f"{kind}={ident}"
    return f"ns={int(ns)};{kind}={ident}"


def namespace_index(node_id: Optional[str]) -> int:
    """The namespace index of a canonical NodeId (``0`` when it has no ``ns=`` prefix)."""
    if not node_id:
        return 0
    match = _NODE_ID_RE.match(node_id)
    if match and match.group(1):
        return int(match.group(1))
    return 0


def split_browse_name(browse_name: str) -> Tuple[int, str]:
    """Split ``1:PumpType`` into ``(1, "PumpType")``; a name with no prefix is index 0."""
    match = _BROWSE_NAME_RE.match(browse_name or "")
    if match:
        return int(match.group(1)), match.group(2)
    return 0, browse_name or ""


def _children(element: ET.Element, name: str) -> List[ET.Element]:
    """Direct children of ``element`` whose local name is ``name``."""
    return [child for child in element if local_name(child.tag) == name]


def _child(element: ET.Element, name: str) -> Optional[ET.Element]:
    """The first direct child of ``element`` whose local name is ``name``."""
    return next(iter(_children(element, name)), None)


def _text(element: Optional[ET.Element]) -> Optional[str]:
    """An element's stripped text, or ``None`` when it is absent or blank."""
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _bool(value: Optional[str]) -> bool:
    """XML boolean (``true`` / ``1``)."""
    return (value or "").strip().lower() in ("true", "1")


def _int(value: Optional[str], default: int) -> int:
    """An integer attribute, ``default`` when absent or unreadable."""
    try:
        return int((value or "").strip())
    except ValueError:
        return default


def _dimensions(value: Optional[str]) -> Tuple[int, ...]:
    """``ArrayDimensions="3,4"`` → ``(3, 4)``; unreadable entries are ``0`` (unbounded)."""
    if not value or not value.strip():
        return ()
    return tuple(_int(part, 0) for part in value.split(","))


def _label(source_label: Optional[str]) -> str:
    return f" {source_label!r}" if source_label else ""


# ---------------------------------------------------------------------------
# Detection and XML intake
# ---------------------------------------------------------------------------


def is_nodeset(text: Optional[str]) -> bool:
    """Whether ``text`` opens with a ``UANodeSet`` root element.

    Only the head is examined (comments removed), so a truncated or malformed nodeset is still
    recognised and the parser can say what is wrong with it.

    Args:
        text: The candidate document.

    Returns:
        ``True`` for a ``UANodeSet`` root (prefixed or not).
    """
    if not text:
        return False
    head = _COMMENT_RE.sub("", text[:_SNIFF_WINDOW])
    start = _FIRST_ELEMENT_RE.search(head)
    return start is not None and bool(_ROOT_RE.match(head, start.start()))


def declares_nodeset_namespace(text: Optional[str]) -> bool:
    """Whether the head of ``text`` names the NodeSet2 schema namespace."""
    return bool(text) and NODESET_NAMESPACE in text[:4096]


def _parse_xml(text: str, source_label: Optional[str]) -> ET.Element:
    """Parse XML safely, mapping faults onto intake codes."""
    head = text[:_ENCODING_WINDOW]
    if any(marker in head for marker in _ENCODING_FAULT_MARKERS):
        raise NodeSetParseError(
            f"Document{_label(source_label)} is not valid text in its declared encoding.", code=None
        )
    if not text.lstrip("﻿ \t\r\n").startswith("<"):
        raise NodeSetParseError(
            f"Document{_label(source_label)} is not XML, so it cannot be an OPC UA NodeSet2 file.",
            code="FORMAT_MISMATCH",
        )
    try:
        return parse_xml(text, source_label=source_label)
    except SecureXmlError as exc:
        message = str(exc)
        if exc.code not in (None, "INPUT_MALFORMED"):
            raise NodeSetParseError(message, code=exc.code) from exc
        truncated = any(marker in message for marker in _TRUNCATION_MESSAGES) and not text.rstrip().endswith(">")
        raise NodeSetParseError(
            message + (" The document was truncated." if truncated else ""),
            code="INPUT_TRUNCATED" if truncated else "INPUT_MALFORMED",
        ) from exc


def _node_lines(text: str) -> Dict[str, int]:
    """Map each node element's NodeId (as written) to the 1-based line it opens on."""
    lines: Dict[str, int] = {}
    line = 1
    position = 0
    for match in _NODE_LINE_RE.finditer(text):
        line += text.count("\n", position, match.start())
        position = match.start()
        lines.setdefault(match.group(2), line)
    return lines


# ---------------------------------------------------------------------------
# Section readers
# ---------------------------------------------------------------------------


def _read_models(root: ET.Element) -> Tuple[UaModel, ...]:
    """Read ``Models/Model`` with their ``RequiredModel`` entries."""
    models: List[UaModel] = []
    section = _child(root, "Models")
    for model in _children(section, "Model") if section is not None else []:
        uri = (model.get("ModelUri") or "").strip()
        if not uri:
            continue
        required = tuple(
            (
                (req.get("ModelUri") or "").strip(),
                req.get("Version"),
                req.get("PublicationDate"),
            )
            for req in _children(model, "RequiredModel")
            if (req.get("ModelUri") or "").strip()
        )
        models.append(
            UaModel(
                model_uri=uri,
                version=model.get("Version"),
                publication_date=model.get("PublicationDate"),
                required_models=required,
            )
        )
    return tuple(models)


def _read_aliases(root: ET.Element) -> Tuple[Tuple[str, str], ...]:
    """Read ``Aliases/Alias`` as ``(alias, canonical NodeId)`` pairs."""
    section = _child(root, "Aliases")
    pairs: List[Tuple[str, str]] = []
    for alias in _children(section, "Alias") if section is not None else []:
        name = (alias.get("Alias") or "").strip()
        target = canonical_node_id(_text(alias))
        if name and target:
            pairs.append((name, target))
    return tuple(pairs)


class _Resolver:
    """Resolves an alias or a NodeId spelling to the canonical NodeId, and names reference types."""

    def __init__(self, aliases: Iterable[Tuple[str, str]]) -> None:
        self.aliases: Dict[str, str] = dict(aliases)
        self._names: Dict[str, str] = dict(BASE_REFERENCE_TYPES)
        for alias, node_id in self.aliases.items():
            self._names.setdefault(node_id, alias)

    def node_id(self, value: Optional[str]) -> Optional[str]:
        """The canonical NodeId for an alias or a NodeId."""
        if value is None:
            return None
        stripped = value.strip()
        if stripped in self.aliases:
            return self.aliases[stripped]
        if stripped in _BASE_NAMES:
            return _BASE_NAMES[stripped]
        return canonical_node_id(stripped)

    def name_reference_type(self, node_id: str, browse_name: str) -> None:
        """Teach the resolver a reference type the document declares."""
        self._names.setdefault(node_id, split_browse_name(browse_name)[1])

    def reference_name(self, written: str, node_id: str) -> str:
        """The readable name of a reference type: the alias as written, else a known name."""
        stripped = written.strip()
        if stripped in self.aliases or not _NODE_ID_RE.match(stripped):
            return stripped
        return self._names.get(node_id, node_id)


def _read_definition(element: Optional[ET.Element], resolver: _Resolver) -> Optional[UaDefinition]:
    """Read a ``UADataType``'s ``Definition``."""
    if element is None:
        return None
    fields = tuple(
        UaDefinitionField(
            name=(item.get("Name") or "").strip(),
            data_type=resolver.node_id(item.get("DataType")),
            value_rank=_int(item.get("ValueRank"), -1),
            array_dimensions=_dimensions(item.get("ArrayDimensions")),
            is_optional=_bool(item.get("IsOptional")),
            value=_int(item.get("Value"), 0) if item.get("Value") is not None else None,
            description=_text(_child(item, "Description")),
        )
        for item in _children(element, "Field")
        if (item.get("Name") or "").strip()
    )
    return UaDefinition(
        name=(element.get("Name") or "").strip(),
        fields=fields,
        is_union=_bool(element.get("IsUnion")),
        is_option_set=_bool(element.get("IsOptionSet")),
    )


def _argument_dimensions(element: Optional[ET.Element]) -> Tuple[int, ...]:
    """An ``Argument``'s ``ArrayDimensions`` (``<UInt32>3</UInt32>`` items) as integers."""
    if element is None:
        return ()
    return tuple(_int(_text(item), 0) for item in element)


def _read_arguments(node: ET.Element, resolver: _Resolver) -> Tuple[UaArgument, ...]:
    """Read the ``Argument`` structures a method's argument variable lists as its value."""
    value = _child(node, "Value")
    if value is None:
        return ()
    arguments: List[UaArgument] = []
    for element in value.iter():
        if local_name(element.tag) != "Argument":
            continue
        name = _text(_child(element, "Name"))
        if not name:
            continue
        data_type = _child(element, "DataType")
        identifier = _text(_child(data_type, "Identifier")) if data_type is not None else None
        description = _child(element, "Description")
        arguments.append(
            UaArgument(
                name=name,
                data_type=resolver.node_id(identifier),
                value_rank=_int(_text(_child(element, "ValueRank")), -1),
                array_dimensions=_argument_dimensions(_child(element, "ArrayDimensions")),
                description=_text(_child(description, "Text")) if description is not None else None,
            )
        )
    return tuple(arguments)


def _read_references(node: ET.Element, resolver: _Resolver) -> Tuple[UaReference, ...]:
    """Read a node's ``References/Reference`` entries."""
    section = _child(node, "References")
    references: List[UaReference] = []
    for reference in _children(section, "Reference") if section is not None else []:
        written = reference.get("ReferenceType") or ""
        type_id = resolver.node_id(written)
        target = resolver.node_id(_text(reference))
        if not type_id or not target:
            continue
        references.append(
            UaReference(
                reference_type=type_id,
                reference_name=resolver.reference_name(written, type_id),
                target=target,
                is_forward=reference.get("IsForward") is None or _bool(reference.get("IsForward")),
            )
        )
    return tuple(references)


def _read_node(
    element: ET.Element,
    node_class: str,
    resolver: _Resolver,
    lines: Mapping[str, int],
    source_label: Optional[str],
    source_file: Optional[str] = None,
) -> UaNode:
    """Read one node element."""
    written_id = element.get("NodeId")
    node_id = canonical_node_id(written_id)
    browse_name = (element.get("BrowseName") or "").strip()
    if not node_id or not browse_name:
        raise NodeSetParseError(
            f"A {node_class} in{_label(source_label) or ' the document'} has no "
            f"{'NodeId' if not node_id else 'BrowseName'}.",
            code="INPUT_SEMANTIC_INVALID",
        )
    _, name = split_browse_name(browse_name)
    arguments: Tuple[UaArgument, ...] = ()
    if node_class == "UAVariable" and name in ("InputArguments", "OutputArguments"):
        arguments = _read_arguments(element, resolver)
    return UaNode(
        node_class=node_class,
        node_id=node_id,
        browse_name=browse_name,
        display_name=_text(_child(element, "DisplayName")),
        description=_text(_child(element, "Description")),
        parent_node_id=resolver.node_id(element.get("ParentNodeId")),
        data_type=resolver.node_id(element.get("DataType")),
        value_rank=_int(element.get("ValueRank"), -1),
        array_dimensions=_dimensions(element.get("ArrayDimensions")),
        is_abstract=_bool(element.get("IsAbstract")),
        symmetric=_bool(element.get("Symmetric")),
        inverse_name=_text(_child(element, "InverseName")),
        method_declaration_id=resolver.node_id(element.get("MethodDeclarationId")),
        references=_read_references(element, resolver),
        definition=_read_definition(_child(element, "Definition"), resolver) if node_class == "UADataType" else None,
        arguments=arguments,
        line=lines.get(written_id or ""),
        source_file=source_file,
    )


# ---------------------------------------------------------------------------
# Reference integrity
# ---------------------------------------------------------------------------


def own_namespace_uris(document: NodeSetDocument) -> Set[str]:
    """The namespaces a nodeset defines: its ``Models``' URIs, else its first namespace URI."""
    if document.models:
        return {model.model_uri for model in document.models}
    return {document.namespace_uris[0]} if document.namespace_uris else set()


def _referenced_ids(node: UaNode) -> List[str]:
    """Every NodeId a node points at: references, data types, parent, method declaration."""
    ids = [reference.target for reference in node.references]
    ids.extend(reference.reference_type for reference in node.references)
    ids.extend(value for value in (node.data_type, node.parent_node_id, node.method_declaration_id) if value)
    if node.definition is not None:
        ids.extend(item.data_type for item in node.definition.fields if item.data_type)
    ids.extend(argument.data_type for argument in node.arguments if argument.data_type)
    return ids


def _check_references(document: NodeSetDocument, source_label: Optional[str]) -> None:
    """Refuse a reference no node can satisfy (see the module docstring).

    Raises:
        NodeSetParseError: ``INPUT_REFERENCE_UNRESOLVED``, naming up to five missing NodeIds.
    """
    own = own_namespace_uris(document)
    missing: List[str] = []
    for node in document.nodes:
        for node_id in _referenced_ids(node):
            if node_id in missing or document.node(node_id) is not None:
                continue
            if namespace_index(node_id) == 0:
                continue
            uri = document.namespace_uri(node_id)
            if uri is None or uri in own:
                missing.append(node_id)
    if missing:
        shown = ", ".join(missing[:5]) + (f" and {len(missing) - 5} more" if len(missing) > 5 else "")
        raise NodeSetParseError(
            f"Document{_label(source_label)} references {shown}, which no node declares and no "
            "required model supplies.",
            code="INPUT_REFERENCE_UNRESOLVED",
        )


# ---------------------------------------------------------------------------
# Filesets
# ---------------------------------------------------------------------------


def _reindex(node_id: Optional[str], mapping: Mapping[int, int]) -> Optional[str]:
    """Re-number a NodeId's namespace index (``ns=1;i=5`` with ``{1: 2}`` → ``ns=2;i=5``)."""
    if not node_id:
        return node_id
    index = namespace_index(node_id)
    if index == 0 or index not in mapping:
        return node_id
    match = _NODE_ID_RE.match(node_id)
    assert match is not None  # namespace_index only returns a non-zero index for a NodeId
    return f"ns={mapping[index]};{match.group(2)}={match.group(3)}"


def _reindex_node(node: UaNode, mapping: Mapping[int, int]) -> UaNode:
    """A node with every NodeId it holds re-numbered into another namespace table."""
    definition = node.definition
    if definition is not None:
        definition = replace(
            definition,
            fields=tuple(replace(item, data_type=_reindex(item.data_type, mapping)) for item in definition.fields),
        )
    return replace(
        node,
        node_id=_reindex(node.node_id, mapping),
        parent_node_id=_reindex(node.parent_node_id, mapping),
        data_type=_reindex(node.data_type, mapping),
        method_declaration_id=_reindex(node.method_declaration_id, mapping),
        references=tuple(
            replace(
                reference,
                reference_type=_reindex(reference.reference_type, mapping),
                target=_reindex(reference.target, mapping),
            )
            for reference in node.references
        ),
        definition=definition,
        arguments=tuple(replace(item, data_type=_reindex(item.data_type, mapping)) for item in node.arguments),
    )


def _merge(root: NodeSetDocument, members: List[NodeSetDocument], source_label: Optional[str]) -> NodeSetDocument:
    """Merge member documents into the root, re-indexing their namespaces into the root's table.

    Raises:
        NodeSetParseError: ``INPUT_SEMANTIC_INVALID`` when two files declare the same node.
    """
    uris = list(root.namespace_uris)
    nodes = list(root.nodes)
    models = list(root.models)
    aliases = list(root.aliases)
    seen = {node.node_id: node for node in nodes}
    for member in members:
        mapping: Dict[int, int] = {}
        for index, uri in enumerate(member.namespace_uris, start=1):
            if uri not in uris:
                uris.append(uri)
            mapping[index] = uris.index(uri) + 1
        for node in member.nodes:
            moved = _reindex_node(node, mapping)
            if moved.node_id in seen:
                raise NodeSetParseError(
                    f"NodeId {moved.node_id} ({moved.browse_name}) is declared in both "
                    f"{seen[moved.node_id].source_file or 'the root'} and {moved.source_file}.",
                    code="INPUT_SEMANTIC_INVALID",
                )
            seen[moved.node_id] = moved
            nodes.append(moved)
        known = {model.model_uri for model in models}
        models.extend(model for model in member.models if model.model_uri not in known)
        names = {alias for alias, _ in aliases}
        aliases.extend(pair for pair in member.aliases if pair[0] not in names)
    return NodeSetDocument(
        namespace_uris=tuple(uris),
        models=tuple(models),
        aliases=tuple(aliases),
        nodes=tuple(nodes),
        raw=root.raw,
        source_label=source_label or root.source_label,
        last_modified=root.last_modified,
    )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def parse_nodeset(text: str, *, source_label: Optional[str] = None) -> NodeSetDocument:
    """Parse a NodeSet2 XML document.

    Args:
        text: The document text.
        source_label: Filename / paste label for messages and provenance.

    Returns:
        The parsed :class:`NodeSetDocument`.

    Raises:
        NodeSetParseError: With an intake-taxonomy code (see the module docstring).
    """
    document = _read_document(text, source_label=source_label)
    _check_references(document, source_label)
    return document


def parse_nodeset_fileset(
    members: Mapping[str, str], root: str, *, source_label: Optional[str] = None
) -> NodeSetDocument:
    """Parse a fileset: the root nodeset plus every other NodeSet2 member, merged.

    Members that are not NodeSet2 documents (a README, an XSD) are skipped. References are
    checked once, against the merged document, so a model's ``RequiredModel`` is satisfied by
    the member that defines it.

    Args:
        members: Member path → text.
        root: The root member's path.
        source_label: The fileset's label.

    Returns:
        The merged :class:`NodeSetDocument`; each node records the member it came from.

    Raises:
        NodeSetParseError: When the root is missing or any member is unreadable, a node is
            declared twice, or a reference cannot be satisfied.
    """
    if root not in members:
        raise NodeSetParseError(f"The fileset has no root member {root!r}.", code="INPUT_MALFORMED")
    root_document = _read_document(members[root], source_label=root, source_file=root)
    others = [
        _read_document(members[path], source_label=path, source_file=path)
        for path in sorted(members)
        if path != root and is_nodeset(members[path])
    ]
    document = _merge(root_document, others, source_label)
    _check_references(document, source_label)
    return document


def _read_document(
    text: str, *, source_label: Optional[str] = None, source_file: Optional[str] = None
) -> NodeSetDocument:
    """Read one NodeSet2 document without checking its references (see :func:`parse_nodeset`)."""
    if not text or not text.strip():
        raise NodeSetParseError(f"Document{_label(source_label)} is empty.", code="INPUT_EMPTY")
    root = _parse_xml(text, source_label)
    if local_name(root.tag) != "UANodeSet":
        raise NodeSetParseError(
            f"Document{_label(source_label)} has a <{local_name(root.tag)}> root, not <UANodeSet>, "
            "so it is not an OPC UA NodeSet2 file.",
            code="FORMAT_MISMATCH",
        )

    namespaces = _child(root, "NamespaceUris")
    namespace_uris = (
        tuple(uri for uri in (_text(item) for item in _children(namespaces, "Uri")) if uri)
        if namespaces is not None
        else ()
    )
    aliases = _read_aliases(root)
    resolver = _Resolver(aliases)
    for element in root:
        if local_name(element.tag) == "UAReferenceType":
            node_id = canonical_node_id(element.get("NodeId"))
            if node_id:
                resolver.name_reference_type(node_id, element.get("BrowseName") or node_id)

    lines = _node_lines(text)
    nodes: List[UaNode] = []
    seen: Dict[str, str] = {}
    for element in root:
        node_class = local_name(element.tag)
        if node_class not in NODE_CLASSES:
            continue
        node = _read_node(element, node_class, resolver, lines, source_label, source_file)
        if node.node_id in seen:
            raise NodeSetParseError(
                f"NodeId {node.node_id} is declared twice in{_label(source_label) or ' the document'} "
                f"({seen[node.node_id]} and {node.browse_name}).",
                code="INPUT_SEMANTIC_INVALID",
            )
        seen[node.node_id] = node.browse_name
        nodes.append(node)

    if not nodes:
        raise NodeSetParseError(
            f"Document{_label(source_label)} is a UANodeSet that declares no node, so there is nothing to import.",
            code="INPUT_SEMANTIC_INVALID",
        )
    return NodeSetDocument(
        namespace_uris=namespace_uris,
        models=_read_models(root),
        aliases=aliases,
        nodes=tuple(nodes),
        raw=text,
        source_label=source_label,
        last_modified=root.get("LastModified"),
    )
