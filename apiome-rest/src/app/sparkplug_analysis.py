"""Sparkplug B native-analysis extractor — FMT-9.2 (#5469).

Describes a Sparkplug import in Sparkplug's own vocabulary:

.. code-block:: text

    payload            one per payload: label · inferred message type · timestamp · seq · uuid
      metric           name · alias · datatype · flags (value: the observed value)
        property       a property-set entry (engUnit, engLow …)
        metadata       the MetaData fields
        column         a DataSet's columns
        member         a Template's member metrics (recursively)

    namespace          a topic-namespace description: group · edge node · host application
      topics           topic → its parsed components
      node / device    a metric catalogue → metric

Metric values are reported as *observed values*, so the stored record keeps or drops them by the
analysis's value-visibility policy (:func:`app.payload_analysis_store.store_analysis`); property
values (units, ranges) are metadata and are attributes. The record hashes the material actually
read — the payload bytes, not the pipeline's lossy text decode of them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

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
from .sparkplug_parser import (
    CatalogueMetric,
    NamespaceDescription,
    PayloadMember,
    SparkplugDocument,
    payload_labels,
)
from .sparkplug_payload import SparkplugMetric, datatype_name

__all__ = [
    "SPARKPLUG_ANALYZER_KEY",
    "SPARKPLUG_ANALYZER_VERSION",
    "analyze_sparkplug",
    "sparkplug_capabilities",
]

SPARKPLUG_ANALYZER_KEY = "sparkplug"
SPARKPLUG_ANALYZER_VERSION = "1.0.0"


def sparkplug_capabilities(*, max_nodes: int = MAX_TREE_NODES) -> AnalyzerCapabilities:
    """What this extractor models for a Sparkplug input, and what it knowingly does not.

    Args:
        max_nodes: The node budget the record was produced under.

    Returns:
        The capability declaration.
    """
    return analyzer_capabilities(
        supported=[
            "sparkplug.payloads",
            "sparkplug.metrics",
            "sparkplug.aliases",
            "sparkplug.datatypes",
            "sparkplug.property_sets",
            "sparkplug.metadata",
            "sparkplug.datasets",
            "sparkplug.templates",
            "sparkplug.metric_values",
            "sparkplug.topic_namespace",
        ],
        unsupported=[
            "sparkplug.payload_body",
            "sparkplug.dataset_rows",
            "sparkplug.extensions",
        ],
        limits=analysis_limits(max_nodes=max_nodes),
    )


def _text(value: Any) -> Optional[str]:
    """An observed value as text (``None`` stays ``None``)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _metric_node(metric: SparkplugMetric, ordinal: int, *, path: str, file: Optional[str]) -> NativeNode:
    """One decoded metric with its properties, metadata, data-set columns and template members."""
    attributes: Dict[str, Any] = {}
    if metric.alias is not None:
        attributes["alias"] = metric.alias
    datatype = datatype_name(metric.datatype)
    if datatype is not None:
        attributes["datatype"] = datatype
    if metric.timestamp is not None:
        attributes["timestamp"] = metric.timestamp
    flags = [
        name
        for name, present in (
            ("historical", metric.is_historical),
            ("transient", metric.is_transient),
            ("null", metric.is_null),
        )
        if present
    ]
    if flags:
        attributes["flags"] = flags
    if metric.value_field:
        attributes["valueField"] = metric.value_field
    name = metric.name or f"alias:{metric.alias}"
    here = f"{path}/{name}"

    def children() -> List[NativeNode]:
        nodes: List[NativeNode] = []
        for index, (key, item) in enumerate(metric.properties):
            property_attributes: Dict[str, Any] = {"type": datatype_name(item.type)}
            if item.is_null:
                property_attributes["isNull"] = True
            elif isinstance(item.value, (str, int, float, bool)):
                property_attributes["value"] = item.value
            nodes.append(NativeNode(kind="property", name=key, ordinal=index, attributes=property_attributes))
        if metric.metadata is not None:
            nodes.append(NativeNode(kind="metadata", name="metadata", attributes=metric.metadata.as_dict()))
        if metric.dataset is not None:
            for index, column in enumerate(metric.dataset.columns):
                nodes.append(
                    NativeNode(
                        kind="column",
                        name=column.name,
                        ordinal=index,
                        attributes={"datatype": datatype_name(column.datatype)},
                    )
                )
        if metric.template is not None:
            for index, member in enumerate(metric.template.metrics):
                nodes.append(_metric_node(member, index, path=here, file=file))
        return nodes

    has_value = metric.value_field is not None and not metric.is_null
    observed = metric.value if metric.value_field not in ("bytes_value", "dataset_value", "template_value") else None
    value_text = _text(observed) if has_value else None
    value_length: Optional[int] = len(value_text) if value_text is not None else None
    if metric.value_field == "bytes_value" and isinstance(metric.value, int):
        value_length = metric.value
    return NativeNode(
        kind="metric",
        name=name,
        ordinal=ordinal,
        attributes=attributes,
        location=SourceLocation(file=file, ordinal=ordinal, path=here),
        value_present=has_value,
        value_length=value_length,
        value=value_text,
        children=children,
    )


def _payload_node(member: PayloadMember, label: str, ordinal: int, *, fileset: bool) -> NativeNode:
    """One payload and its metrics."""
    payload = member.payload
    attributes: Dict[str, Any] = {
        "messageType": member.message_type or "unknown",
        "messageTypeEvidence": member.evidence,
        "metricCount": len(payload.metrics),
        "size": payload.size,
    }
    for key, value in (("timestamp", payload.timestamp), ("seq", payload.seq), ("uuid", payload.uuid)):
        if value is not None:
            attributes[key] = value
    if payload.body_length is not None:
        attributes["bodyLength"] = payload.body_length
    file = member.label if fileset else None
    return NativeNode(
        kind="payload",
        name=label,
        ordinal=ordinal,
        attributes=attributes,
        location=SourceLocation(file=file, ordinal=ordinal),
        children=lambda: [
            _metric_node(metric, index, path=label, file=file) for index, metric in enumerate(payload.metrics)
        ],
    )


def _catalogue_node(kind: str, name: str, metrics: Sequence[CatalogueMetric], ordinal: int) -> NativeNode:
    """A metric catalogue (the edge node's or a device's)."""
    return NativeNode(
        kind=kind,
        name=name,
        ordinal=ordinal,
        attributes={"metricCount": len(metrics)},
        children=lambda: [
            NativeNode(
                kind="metric",
                name=metric.name,
                ordinal=index,
                attributes={
                    key: value
                    for key, value in (
                        ("alias", metric.alias),
                        ("datatype", metric.datatype),
                        ("description", metric.description),
                        *metric.properties,
                    )
                    if value is not None and isinstance(value, (str, int, float, bool))
                },
                location=SourceLocation(path=f"{name}/{metric.name}"),
            )
            for index, metric in enumerate(metrics)
        ],
    )


def _namespace_node(namespace: NamespaceDescription, label: Optional[str]) -> NativeNode:
    """A topic-namespace description: its topics and catalogues."""
    attributes: Dict[str, Any] = {
        "groupId": namespace.group_id,
        "edgeNodeId": namespace.edge_node_id,
        "topicCount": len(namespace.topics),
        "deviceCount": len(namespace.devices),
    }
    if namespace.host_application_id:
        attributes["hostApplicationId"] = namespace.host_application_id
    topics = NativeNode(
        kind="group",
        name="topics",
        attributes={"count": len(namespace.topics)},
        children=lambda: [
            NativeNode(
                kind="topic",
                name=entry.address,
                ordinal=index,
                attributes={
                    **{key: value for key, value in entry.topic.components().items() if value is not None},
                    **({"retained": entry.retained} if entry.retained is not None else {}),
                    **({"direction": entry.direction} if entry.direction else {}),
                },
            )
            for index, entry in enumerate(namespace.topics)
        ],
    )
    catalogues = [_catalogue_node("node", namespace.edge_node_id, namespace.node_metrics, 0)] + [
        _catalogue_node("device", device.device_id, device.metrics, index)
        for index, device in enumerate(namespace.devices, start=1)
    ]
    return NativeNode(
        kind="namespace",
        name=label or f"{namespace.group_id}/{namespace.edge_node_id}",
        attributes=attributes,
        children=[topics, *catalogues],
    )


def analyze_sparkplug(
    document: SparkplugDocument,
    *,
    source: Optional[Any] = None,
    source_format: str = SPARKPLUG_ANALYZER_KEY,
    max_nodes: int = MAX_TREE_NODES,
    max_depth: int = MAX_TREE_DEPTH,
) -> PayloadAnalysisDocument:
    """Describe a parsed Sparkplug input as a payload analysis.

    Args:
        document: The parsed input (:mod:`app.sparkplug_parser`).
        source: The material to hash; ignored for payloads, whose own bytes are hashed (the
            pipeline's text decode of a binary payload is not what was read).
        source_format: Adapter key recorded on the record.
        max_nodes: Node budget.
        max_depth: Depth budget.

    Returns:
        The analysis document, observed metric values still on it.
    """
    if document.namespace is not None:
        roots = [_namespace_node(document.namespace, document.label)]
        material = source if source is not None else document.source
    else:
        fileset = len(document.payloads) > 1
        roots = [
            _payload_node(member, label, index, fileset=fileset)
            for index, (member, label) in enumerate(zip(document.payloads, payload_labels(document.payloads)))
        ]
        material = document.source
    return build_analysis_document(
        roots=roots,
        analyzer=AnalyzerInfo(key=SPARKPLUG_ANALYZER_KEY, version=SPARKPLUG_ANALYZER_VERSION),
        capabilities=sparkplug_capabilities(max_nodes=max_nodes),
        source=material,
        source_format=source_format,
        max_nodes=max_nodes,
        max_depth=max_depth,
    )
