"""OPC UA NodeSet2 native-analysis extractor — FMT-9.1 (#5468).

Describes a nodeset in OPC UA's own vocabulary, including the address-space **instances** the
canonical model deliberately leaves out:

.. code-block:: text

    nodeset          the UANodeSet: model URIs, versions, node counts
      namespaces     namespace → one per NamespaceUris entry, with its index
      models         model (ModelUri · Version · PublicationDate) → requiredModel …
      aliases        alias → its NodeId
      objectTypes · variableTypes · dataTypes · referenceTypes · methods · objects · variables · views
        <node>       nodeId · browseName · nodeClass · dataType · valueRank · role
          field      a data type's Definition fields
          reference  referenceType · target · isForward

Every node carries a ``role``: ``type`` for a type node, ``declaration`` for a type's instance
declaration, ``signature`` for a method's argument variables and ``instance`` for an address-space
node. The reference graph is the bottom level of the tree on purpose — the analyzer's budget is
breadth-first (:func:`app.payload_analyzer.build_analysis_tree`), so when a large plant model
outgrows it, every group and every node is kept and the references are what is dropped, and the
record says so (``partial`` / ``bounds_exceeded``).

No variable *value* is read: a nodeset's values are defaults and sample data, and the record is a
description of structure.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from .opcua_nodeset_normalizer import argument_variable_ids, child_index, instance_declaration_ids
from .opcua_nodeset_parser import NODE_CLASSES, TYPE_NODE_CLASSES, NodeSetDocument, UaNode
from .payload_analysis import (
    MAX_TREE_DEPTH,
    MAX_TREE_NODES,
    AnalyzerCapabilities,
    AnalyzerInfo,
    PayloadAnalysisDocument,
    SourceLocation,
    analyzer_capabilities,
)
from .payload_analyzer import NativeNode, analysis_limits, build_analysis_document

__all__ = [
    "KIND_NODE",
    "KIND_REFERENCE",
    "OPCUA_ANALYZER_KEY",
    "OPCUA_ANALYZER_VERSION",
    "ROLE_DECLARATION",
    "ROLE_INSTANCE",
    "ROLE_SIGNATURE",
    "ROLE_TYPE",
    "analyze_nodeset",
    "opcua_capabilities",
]

OPCUA_ANALYZER_KEY = "opcua-nodeset"
OPCUA_ANALYZER_VERSION = "1.0.0"

KIND_NODESET = "nodeset"
KIND_GROUP = "group"
KIND_NODE = "node"
KIND_FIELD = "field"
KIND_REFERENCE = "reference"

ROLE_TYPE = "type"
ROLE_DECLARATION = "declaration"
ROLE_SIGNATURE = "signature"
ROLE_INSTANCE = "instance"

#: Node class → the group it is listed under.
_GROUPS: Dict[str, str] = {
    "UAObjectType": "objectTypes",
    "UAVariableType": "variableTypes",
    "UADataType": "dataTypes",
    "UAReferenceType": "referenceTypes",
    "UAMethod": "methods",
    "UAObject": "objects",
    "UAVariable": "variables",
    "UAView": "views",
}


def opcua_capabilities(*, max_nodes: int = MAX_TREE_NODES) -> AnalyzerCapabilities:
    """What this extractor models for a nodeset, and what it knowingly does not.

    Args:
        max_nodes: The node budget the record was produced under.

    Returns:
        The capability declaration.
    """
    return analyzer_capabilities(
        supported=[
            "opcua.namespaces",
            "opcua.models",
            "opcua.aliases",
            "opcua.node_classes",
            "opcua.instance_declarations",
            "opcua.address_space_instances",
            "opcua.data_type_definitions",
            "opcua.references",
            "opcua.source_locations",
        ],
        unsupported=[
            "opcua.variable_values",
            "opcua.access_levels",
            "opcua.role_permissions",
            "opcua.extensions",
        ],
        limits=analysis_limits(max_nodes=max_nodes),
    )


def _location(node: UaNode) -> Optional[SourceLocation]:
    """Where the node element opens, addressed by its NodeId."""
    return SourceLocation(line=node.line, path=node.node_id) if node.line else SourceLocation(path=node.node_id)


def _node(document: NodeSetDocument, node: UaNode, *, ordinal: int, role: str) -> NativeNode:
    """One node with its definition fields and (lazily) its references."""
    attributes: Dict[str, object] = {
        "nodeId": node.node_id,
        "browseName": node.browse_name,
        "nodeClass": node.node_class[2:],
        "role": role,
    }
    namespace = document.namespace_uri(node.node_id)
    if namespace:
        attributes["namespaceUri"] = namespace
    if node.data_type:
        attributes["dataType"] = node.data_type
    if node.node_class in ("UAVariable", "UAVariableType"):
        attributes["valueRank"] = node.value_rank
    if node.array_dimensions:
        attributes["arrayDimensions"] = list(node.array_dimensions)
    if node.is_abstract:
        attributes["isAbstract"] = True
    if node.method_declaration_id:
        attributes["methodDeclarationId"] = node.method_declaration_id
    if node.arguments:
        attributes["arguments"] = [argument.name for argument in node.arguments]

    def children() -> List[NativeNode]:
        nodes: List[NativeNode] = []
        if node.definition is not None:
            for index, item in enumerate(node.definition.fields):
                field_attributes: Dict[str, object] = {"valueRank": item.value_rank}
                if item.data_type:
                    field_attributes["dataType"] = item.data_type
                if item.value is not None:
                    field_attributes["value"] = item.value
                if item.is_optional:
                    field_attributes["isOptional"] = True
                nodes.append(NativeNode(kind=KIND_FIELD, name=item.name, ordinal=index, attributes=field_attributes))
        for index, reference in enumerate(node.references):
            target = document.node(reference.target)
            reference_attributes: Dict[str, object] = {
                "referenceType": reference.reference_name,
                "target": reference.target,
                "isForward": reference.is_forward,
            }
            if target is not None:
                reference_attributes["targetBrowseName"] = target.browse_name
            nodes.append(
                NativeNode(
                    kind=KIND_REFERENCE,
                    name=reference.reference_name,
                    ordinal=index,
                    attributes=reference_attributes,
                )
            )
        return nodes

    return NativeNode(
        kind=KIND_NODE,
        name=node.name,
        label=node.display_name,
        ordinal=ordinal,
        attributes=attributes,
        location=_location(node),
        children=children,
    )


def _role(node: UaNode, declarations: Set[str], signatures: Set[str]) -> str:
    """Whether a node is a type, a declaration, a method signature or an instance."""
    if node.node_class in TYPE_NODE_CLASSES:
        return ROLE_TYPE
    if node.node_id in signatures:
        return ROLE_SIGNATURE
    if node.node_id in declarations:
        return ROLE_DECLARATION
    return ROLE_INSTANCE


def _header_groups(document: NodeSetDocument) -> List[NativeNode]:
    """The namespaces, models and aliases groups."""
    namespaces = NativeNode(
        kind=KIND_GROUP,
        name="namespaces",
        attributes={"count": len(document.namespace_uris)},
        children=[
            NativeNode(kind="namespace", name=uri, ordinal=index, attributes={"index": index + 1, "uri": uri})
            for index, uri in enumerate(document.namespace_uris)
        ],
    )
    models = NativeNode(
        kind=KIND_GROUP,
        name="models",
        attributes={"count": len(document.models)},
        children=[
            NativeNode(
                kind="model",
                name=model.model_uri,
                ordinal=index,
                attributes={
                    key: value
                    for key, value in (
                        ("modelUri", model.model_uri),
                        ("version", model.version),
                        ("publicationDate", model.publication_date),
                    )
                    if value
                },
                children=[
                    NativeNode(
                        kind="requiredModel",
                        name=uri,
                        ordinal=position,
                        attributes={
                            key: value
                            for key, value in (("modelUri", uri), ("version", version), ("publicationDate", date))
                            if value
                        },
                    )
                    for position, (uri, version, date) in enumerate(model.required_models)
                ],
            )
            for index, model in enumerate(document.models)
        ],
    )
    aliases = NativeNode(
        kind=KIND_GROUP,
        name="aliases",
        attributes={"count": len(document.aliases)},
        children=[
            NativeNode(kind="alias", name=alias, ordinal=index, attributes={"nodeId": node_id})
            for index, (alias, node_id) in enumerate(document.aliases)
        ],
    )
    return [namespaces, models, aliases]


def analyze_nodeset(
    document: NodeSetDocument,
    *,
    source: Optional[str] = None,
    source_format: str = OPCUA_ANALYZER_KEY,
    max_nodes: int = MAX_TREE_NODES,
    max_depth: int = MAX_TREE_DEPTH,
) -> PayloadAnalysisDocument:
    """Describe a parsed nodeset as a payload analysis.

    Args:
        document: The parsed nodeset (:func:`app.opcua_nodeset_parser.parse_nodeset`).
        source: The exact text analysed; defaults to the document's retained raw text.
        source_format: Adapter key recorded on the record.
        max_nodes: Node budget.
        max_depth: Depth budget.

    Returns:
        The analysis document. Over budget, it is ``partial`` / ``bounds_exceeded``.
    """
    children_by_parent = child_index(document)
    declarations = instance_declaration_ids(document, children_by_parent)
    signatures = argument_variable_ids(document, children_by_parent)
    by_class: Dict[str, List[UaNode]] = {node_class: [] for node_class in NODE_CLASSES}
    for node in document.nodes:
        by_class[node.node_class].append(node)

    groups: List[NativeNode] = _header_groups(document)
    for node_class in NODE_CLASSES:
        members = by_class[node_class]
        if not members:
            continue
        groups.append(
            NativeNode(
                kind=KIND_GROUP,
                name=_GROUPS[node_class],
                attributes={"count": len(members), "nodeClass": node_class[2:]},
                children=lambda members=members: [
                    _node(document, node, ordinal=index, role=_role(node, declarations, signatures))
                    for index, node in enumerate(members)
                ],
            )
        )

    root = NativeNode(
        kind=KIND_NODESET,
        name=document.source_label or (document.models[0].model_uri if document.models else "UANodeSet"),
        attributes={
            "modelUris": [model.model_uri for model in document.models],
            "nodeCount": len(document.nodes),
            **({"lastModified": document.last_modified} if document.last_modified else {}),
        },
        children=groups,
    )
    text = source if source is not None else document.raw
    return build_analysis_document(
        roots=[root],
        analyzer=AnalyzerInfo(key=OPCUA_ANALYZER_KEY, version=OPCUA_ANALYZER_VERSION),
        capabilities=opcua_capabilities(max_nodes=max_nodes),
        source=text,
        source_format=source_format,
        max_nodes=max_nodes,
        max_depth=max_depth,
    )
