"""Sparkplug B normalizer — FMT-9.2 (#5469).

Maps a parsed Sparkplug input (:class:`~app.sparkplug_parser.SparkplugDocument`) onto the
**event** paradigm:

* each topic becomes a :class:`~app.canonical_model.Channel` whose ``address`` is the topic and
  whose ``extras['sparkplug_topic']`` holds its components (namespace, group, message type, edge
  node, device, host); an unknown component is a channel parameter (``{group_id}``);
* each channel gets one operation — ``publish`` for what an edge node sends (BIRTH, DATA, DEATH),
  ``subscribe`` for what it receives (NCMD, DCMD, STATE) — whose event message's payload is a
  record of **metrics**;
* each metric becomes a field: its Sparkplug datatype mapped to a canonical scalar
  (:data:`DATATYPE_TO_CANONICAL`), arrays to lists, a DataSet to a list of a synthesized row
  record, a template instance to its definition's record. The alias, the Sparkplug datatype, the
  property set (engineering units, ranges …), metadata and flags are kept in the field's extras.

**Provenance.** A namespace description *declares* its topics and catalogues. A payload declares
nothing about where it was published, so every construct a payload-only import produces is stamped
``inferred`` (FMT-8.6), with the sentence saying what it was inferred from. An alias-only metric —
a DATA payload names its metrics only by the alias its BIRTH gave them — is named through the
BIRTH when the BIRTH is in the same fileset, and otherwise keeps the placeholder ``alias:<n>``
rather than an invented name.

What is not modelled is listed in ``extras['sparkplug']['capability_limits']`` for the coverage
ledger. Metric *values* are telemetry, not schema: they never enter the canonical model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Server,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from .inference_provenance import INFERRED, SYNTHESIZED, provenance_extras
from .normalizer import Keys, Normalizer, normalize_ordering
from .sparkplug_parser import (
    DEVICE_MESSAGE_TYPES,
    FORMAT_KEY,
    INBOUND_MESSAGE_TYPES,
    SPARKPLUG_NAMESPACE,
    CatalogueMetric,
    NamespaceDescription,
    PayloadMember,
    SparkplugDocument,
    SparkplugTopic,
    raw_record,
    topic_for_message_type,
)
from .sparkplug_payload import SparkplugMetric, SparkplugTemplate, datatype_name
from .typescript_types_normalizer import _limits_payload
from .typescript_types_parser import LimitRecorder

__all__ = [
    "DATATYPE_TO_CANONICAL",
    "LIMIT_DETAILS",
    "PARTIAL_LIMITS",
    "SPARKPLUG_EXTRAS_KEY",
    "SparkplugNormalizer",
    "canonical_scalar",
]

#: Root extras key of the projection record.
SPARKPLUG_EXTRAS_KEY = "sparkplug"

#: Sparkplug scalar datatype → canonical scalar name.
DATATYPE_TO_CANONICAL: Dict[str, str] = {
    "Int8": "int8",
    "Int16": "int16",
    "Int32": "int32",
    "Int64": "int64",
    "UInt8": "uint8",
    "UInt16": "uint16",
    "UInt32": "uint32",
    "UInt64": "uint64",
    "Float": "float",
    "Double": "double",
    "Boolean": "boolean",
    "String": "string",
    "Text": "string",
    "DateTime": "timestamp",
    "UUID": "uuid",
    "Bytes": "bytes",
    "File": "bytes",
}

#: Sparkplug array datatype → its element's Sparkplug datatype.
ARRAY_ELEMENTS: Dict[str, str] = {
    "Int8Array": "Int8",
    "Int16Array": "Int16",
    "Int32Array": "Int32",
    "Int64Array": "Int64",
    "UInt8Array": "UInt8",
    "UInt16Array": "UInt16",
    "UInt32Array": "UInt32",
    "UInt64Array": "UInt64",
    "FloatArray": "Float",
    "DoubleArray": "Double",
    "BooleanArray": "Boolean",
    "StringArray": "String",
    "DateTimeArray": "DateTime",
}

#: The canonical type a metric gets when it sent no datatype, by the value field it used.
_VALUE_FIELD_SCALARS: Dict[str, str] = {
    "int_value": "integer",
    "long_value": "integer",
    "float_value": "float",
    "double_value": "double",
    "boolean_value": "boolean",
    "string_value": "string",
    "bytes_value": "bytes",
}

#: Case-insensitive datatype lookup for namespace descriptions (``"double"`` == ``"Double"``).
_DATATYPE_BY_LOWER: Dict[str, str] = {
    name.lower(): name
    for name in list(DATATYPE_TO_CANONICAL) + list(ARRAY_ELEMENTS) + ["DataSet", "Template", "Unknown"]
}

#: The canonical "any value" scalar.
_ANY = "any"

#: The prefix Sparkplug template definitions are conventionally published under.
_TEMPLATE_DEFINITION_PREFIX = "_types_/"

#: The declared-limit vocabulary (stable keys → reviewed sentence).
LIMIT_DETAILS: Dict[str, str] = {
    "sparkplug.alias_unresolved": (
        "A DATA payload names its metrics only by the alias its BIRTH certificate gave them; "
        "without that BIRTH the name is unknown, so the field keeps the placeholder alias:<n>."
    ),
    "sparkplug.datatype_inferred": (
        "A metric that sent no datatype, with no BIRTH declaring one, is typed from the value "
        "field it used — which cannot tell Int8 from UInt32, or Int64 from DateTime."
    ),
    "sparkplug.datatype_unknown": (
        "A datatype outside the Sparkplug enum, Unknown, or a property-set type on a metric is "
        "typed as any; the declared datatype is kept in extras."
    ),
    "sparkplug.shape_unknown": (
        "A DataSet or Template metric whose value is not in the input has no columns or members "
        "to read, so it is typed as any."
    ),
    "sparkplug.template_unresolved": (
        "A template instance whose definition is not in the input is typed as any; its template_ref is kept in extras."
    ),
    "sparkplug.message_type_unknown": (
        "A payload does not carry its topic. When neither the file name nor the metrics settle "
        "its message type, the channel keeps {message_type} as an address parameter and whether "
        "it is a node or a device message is unknown."
    ),
    "sparkplug.device_without_catalogue": (
        "A device topic whose device has no metric catalogue in the description has no payload schema to bind."
    ),
    "sparkplug.unknown_fields": (
        "Fields outside the Sparkplug B schema (protobuf extensions) were skipped and not read."
    ),
    "sparkplug.payload_body": ("A payload's opaque body bytes have no declared structure and are not read."),
}

#: Limits whose construct is still modelled, with only a detail lost.
PARTIAL_LIMITS = frozenset(LIMIT_DETAILS) - {"sparkplug.unknown_fields", "sparkplug.payload_body"}

_PAYLOAD_TOPIC_EVIDENCE = (
    "A Sparkplug payload does not carry the topic it was published on, so this component of the address is unknown."
)

_PARAMETER_DESCRIPTIONS: Dict[str, str] = {
    "group_id": "The Sparkplug group the edge node belongs to.",
    "message_type": "The Sparkplug message type (NBIRTH, DDATA …).",
    "edge_node_id": "The edge node that published the payload.",
    "device_id": "The device behind the edge node the payload is about.",
    "host_id": "The host application whose state the topic carries.",
}

_MESSAGE_DESCRIPTIONS: Dict[str, str] = {
    "NBIRTH": "Edge node birth certificate: every node metric, with its datatype, alias and properties.",
    "NDEATH": "Edge node death certificate: carries the bdSeq of the session it closes.",
    "NDATA": "Edge node data: changed node metrics, by name or alias.",
    "NCMD": "Command to the edge node: metrics to write.",
    "DBIRTH": "Device birth certificate: every device metric, with its datatype, alias and properties.",
    "DDEATH": "Device death certificate: the device is offline.",
    "DDATA": "Device data: changed device metrics, by name or alias.",
    "DCMD": "Command to the device: metrics to write.",
    "STATE": "The host application's online state (a JSON payload, not protobuf).",
}


def canonical_scalar(datatype: Optional[str]) -> Optional[str]:
    """The canonical scalar a Sparkplug scalar datatype maps to, or ``None`` when it is not one."""
    if datatype is None:
        return None
    return DATATYPE_TO_CANONICAL.get(datatype)


def _canonical_datatype_name(raw: Optional[str]) -> Optional[str]:
    """A namespace description's datatype spelled the Sparkplug way (``"double"`` → ``"Double"``)."""
    if raw is None:
        return None
    return _DATATYPE_BY_LOWER.get(raw.lower(), raw)


def _template_type_name(metric_name: str) -> str:
    """The type name of a template definition (its metric name, without ``_types_/``)."""
    if metric_name.startswith(_TEMPLATE_DEFINITION_PREFIX):
        return metric_name[len(_TEMPLATE_DEFINITION_PREFIX) :] or metric_name
    return metric_name


@dataclass
class _MetricSpec:
    """One metric as the normalizer needs it, whichever input it came from."""

    name: str
    alias: Optional[int]
    datatype: Optional[str]
    description: Optional[str] = None
    properties: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    flags: List[str] = field(default_factory=list)
    value_field: Optional[str] = None
    columns: Optional[List[Tuple[str, Optional[str]]]] = None
    template: Optional[SparkplugTemplate] = None
    template_ref: Optional[str] = None
    evidence: Optional[str] = None
    unresolved_alias: bool = False


class _Builder:
    """Accumulates types, limits and provenance while one document is normalized."""

    def __init__(self, *, inferred: bool) -> None:
        self.inferred = inferred
        self.types: Dict[str, Type] = {}
        self.templates: Dict[str, str] = {}
        self.limits = LimitRecorder(details=LIMIT_DETAILS)

    def stamp(self, evidence: Optional[str], *, provenance: str = INFERRED) -> Dict[str, Any]:
        """The provenance stamp for a construct — empty for a declared (namespace) construct."""
        if not self.inferred and provenance == INFERRED:
            return {}
        return provenance_extras(provenance, evidence)

    # --- metric → field ----------------------------------------------------

    def type_ref(self, spec: _MetricSpec, owner_key: str) -> Tuple[TypeRef, bool]:
        """The canonical type of one metric, and whether the datatype was inferred from its value."""
        location = Keys.field(owner_key, spec.name)
        datatype = spec.datatype
        if datatype is None:
            if spec.template is not None or spec.template_ref is not None:
                datatype = "Template"
            elif spec.columns is not None:
                datatype = "DataSet"
            elif spec.value_field in _VALUE_FIELD_SCALARS:
                self.limits.record("sparkplug.datatype_inferred", location=location)
                return TypeRef(name=_VALUE_FIELD_SCALARS[spec.value_field]), True
            else:
                self.limits.record("sparkplug.datatype_unknown", location=location)
                return TypeRef(name=_ANY), False
        scalar = canonical_scalar(datatype)
        if scalar is not None:
            return TypeRef(name=scalar), False
        if datatype in ARRAY_ELEMENTS:
            return TypeRef(item=TypeRef(name=DATATYPE_TO_CANONICAL[ARRAY_ELEMENTS[datatype]])), False
        if datatype == "DataSet":
            if spec.columns is None:
                self.limits.record("sparkplug.shape_unknown", location=location)
                return TypeRef(name=_ANY), False
            row_key = self.dataset_row(spec, owner_key)
            return TypeRef(item=TypeRef(name=row_key, nullable=False)), False
        if datatype == "Template":
            return self.template_ref(spec, owner_key, location), False
        self.limits.record("sparkplug.datatype_unknown", location=location)
        return TypeRef(name=_ANY), False

    def template_ref(self, spec: _MetricSpec, owner_key: str, location: str) -> TypeRef:
        """A template instance's type: its definition's record, when the definition is known."""
        reference = spec.template_ref or (spec.template.template_ref if spec.template else None)
        if reference is None:
            self.limits.record("sparkplug.shape_unknown", location=location)
            return TypeRef(name=_ANY)
        key = self.templates.get(reference) or self.templates.get(_template_type_name(reference))
        if key is None:
            self.limits.record("sparkplug.template_unresolved", location=location)
            return TypeRef(name=_ANY)
        return TypeRef(name=key)

    def dataset_row(self, spec: _MetricSpec, owner_key: str) -> str:
        """Synthesize the record one row of a DataSet metric holds; returns its key."""
        name = f"{spec.name} row"
        key = Keys.type(name, namespace=owner_key)
        fields: List[CanonicalField] = []
        for column, datatype in spec.columns or []:
            column_spec = _MetricSpec(name=column, alias=None, datatype=datatype)
            ref, _ = self.type_ref(column_spec, key)
            fields.append(
                CanonicalField(
                    key=Keys.field(key, column),
                    name=column,
                    type=ref,
                    extras={"sparkplug_datatype": datatype} if datatype else {},
                )
            )
        self.types[key] = Type(
            key=key,
            name=name,
            kind=TypeKind.RECORD,
            namespace=owner_key,
            description=f"One row of the {spec.name} data set.",
            fields=fields,
            extras=provenance_extras(SYNTHESIZED, f"Named by Apiome for the rows of the {spec.name} DataSet metric."),
        )
        return key

    def field(self, spec: _MetricSpec, owner_key: str) -> CanonicalField:
        """One metric as a canonical field."""
        ref, from_value = self.type_ref(spec, owner_key)
        extras: Dict[str, Any] = {}
        if spec.alias is not None:
            extras["sparkplug_alias"] = spec.alias
        if spec.datatype is not None:
            extras["sparkplug_datatype"] = spec.datatype
        elif from_value and spec.value_field:
            extras["sparkplug_value_field"] = spec.value_field
        if spec.properties:
            extras["sparkplug_properties"] = dict(spec.properties)
        if spec.metadata:
            extras["sparkplug_metadata"] = dict(spec.metadata)
        if spec.flags:
            extras["sparkplug_flags"] = list(spec.flags)
        template_ref = spec.template_ref or (spec.template.template_ref if spec.template else None)
        if template_ref:
            extras["sparkplug_template_ref"] = template_ref
        extras.update(self.stamp(spec.evidence))
        return CanonicalField(
            key=Keys.field(owner_key, spec.name),
            name=spec.name,
            type=ref,
            description=spec.description,
            extras=extras,
        )

    def record(
        self,
        key: str,
        name: str,
        specs: Sequence[_MetricSpec],
        *,
        namespace: Optional[str],
        description: Optional[str],
        extras: Dict[str, Any],
    ) -> None:
        """Add one record type of metrics (first occurrence of a metric name wins)."""
        fields: Dict[str, CanonicalField] = {}
        for spec in specs:
            if spec.name not in fields:
                fields[spec.name] = self.field(spec, key)
        self.types[key] = Type(
            key=key,
            name=name,
            kind=TypeKind.RECORD,
            namespace=namespace,
            description=description,
            fields=list(fields.values()),
            extras=extras,
        )

    def define_templates(self, metrics: Sequence[SparkplugMetric], evidence: str) -> None:
        """Turn every template *definition* among ``metrics`` into a record type."""
        definitions = [m for m in metrics if m.template is not None and m.template.is_definition and m.name]
        # Register every key first, so a definition may refer to another one.
        for metric in definitions:
            assert metric.name is not None
            name = _template_type_name(metric.name)
            self.templates[metric.name] = Keys.type(name)
            self.templates[name] = Keys.type(name)
        for metric in definitions:
            assert metric.template is not None and metric.name is not None
            name = _template_type_name(metric.name)
            template = metric.template
            members = [_spec_from_metric(member, evidence) for member in template.metrics if member.name]
            extras: Dict[str, Any] = {
                "sparkplug_template": {
                    "version": template.version,
                    "definition": metric.name,
                    "parameters": [
                        {"name": parameter.name, "datatype": datatype_name(parameter.datatype)}
                        for parameter in template.parameters
                    ],
                }
            }
            extras.update(self.stamp(evidence))
            self.record(
                Keys.type(name),
                name,
                members,
                namespace=None,
                description=f"Sparkplug template {name}.",
                extras=extras,
            )


def _spec_from_metric(metric: SparkplugMetric, evidence: Optional[str], *, name: Optional[str] = None) -> _MetricSpec:
    """A decoded payload metric as a :class:`_MetricSpec` (``name`` overrides an alias-only metric's)."""
    metadata = metric.metadata.as_dict() if metric.metadata else {}
    description = metadata.pop("description", None)
    flags = [
        flag
        for flag, present in (
            ("historical", metric.is_historical),
            ("transient", metric.is_transient),
            ("null", metric.is_null),
        )
        if present
    ]
    return _MetricSpec(
        name=name or metric.name or f"alias:{metric.alias}",
        alias=metric.alias,
        datatype=datatype_name(metric.datatype),
        description=description if isinstance(description, str) else None,
        properties={key: (None if value.is_null else value.value) for key, value in metric.properties},
        metadata=metadata,
        flags=flags,
        value_field=metric.value_field,
        columns=[(column.name, datatype_name(column.datatype)) for column in metric.dataset.columns]
        if metric.dataset is not None
        else None,
        template=metric.template,
        evidence=evidence,
    )


def _spec_from_catalogue(metric: CatalogueMetric) -> _MetricSpec:
    """A namespace description's catalogue metric as a :class:`_MetricSpec`."""
    return _MetricSpec(
        name=metric.name,
        alias=metric.alias,
        datatype=_canonical_datatype_name(metric.datatype),
        description=metric.description,
        properties=dict(metric.properties),
    )


# ---------------------------------------------------------------------------
# Channels and operations (shared by both inputs)
# ---------------------------------------------------------------------------


def _action(message_type: Optional[str], declared_direction: Optional[str] = None) -> Tuple[str, OperationKind]:
    """``publish`` for what the edge node sends, ``subscribe`` for what it receives."""
    if declared_direction == "inbound" or (declared_direction is None and message_type in INBOUND_MESSAGE_TYPES):
        return "subscribe", OperationKind.SUBSCRIBE
    return "publish", OperationKind.PUBLISH


def _channel(builder: _Builder, topic: SparkplugTopic, address: str, *, name: str, evidence: Optional[str]) -> Channel:
    """One topic as a channel; unknown components become address parameters."""
    key = Keys.channel(address)
    parameters = [
        CanonicalField(
            key=Keys.channel_parameter(key, parameter),
            name=parameter,
            type=TypeRef(name="string", nullable=False),
            description=_PARAMETER_DESCRIPTIONS.get(parameter),
            extras=builder.stamp(_PAYLOAD_TOPIC_EVIDENCE),
        )
        for parameter in topic.parameters()
    ]
    extras: Dict[str, Any] = {"sparkplug_topic": topic.components()}
    extras.update(builder.stamp(evidence))
    return Channel(
        key=key,
        address=address,
        name=name,
        description=_MESSAGE_DESCRIPTIONS.get(topic.message_type or ""),
        protocol="mqtt",
        parameters=parameters,
        extras=extras,
    )


def _operation(
    builder: _Builder,
    channel: Channel,
    message_type: Optional[str],
    *,
    payload_key: Optional[str],
    name: str,
    direction: Optional[str] = None,
    bindings: Optional[Dict[str, Any]] = None,
    evidence: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Operation:
    """The single operation bound to a channel, carrying one event message."""
    action, kind = _action(message_type, direction)
    key = Keys.operation_event(action, channel.address)
    message_name = message_type or "payload"
    message_extras: Dict[str, Any] = {"sparkplug_encoding": "json" if message_type == "STATE" else "protobuf"}
    message_extras.update(builder.stamp(evidence))
    extras: Dict[str, Any] = {"action": action}
    if message_type:
        extras["sparkplug_message_type"] = message_type
    if bindings:
        extras["bindings"] = bindings
    if extra:
        extras.update(extra)
    extras.update(builder.stamp(evidence))
    return Operation(
        key=key,
        name=name,
        kind=kind,
        channel_ref=channel.key,
        description=_MESSAGE_DESCRIPTIONS.get(message_type or ""),
        messages=[
            Message(
                key=Keys.event_message(key, message_name),
                role=MessageRole.EVENT,
                name=message_name,
                payload=TypeRef(name=payload_key, nullable=False) if payload_key else None,
                description=_MESSAGE_DESCRIPTIONS.get(message_type or ""),
                extras=message_extras,
            )
        ],
        extras=extras,
    )


# ---------------------------------------------------------------------------
# Payload input
# ---------------------------------------------------------------------------


def _level(message_type: Optional[str]) -> Optional[str]:
    """``"device"`` / ``"node"`` for a known message type, ``None`` when unknown."""
    if message_type is None:
        return None
    return "device" if message_type in DEVICE_MESSAGE_TYPES else "node"


def _member_name(member: PayloadMember) -> str:
    return PurePosixPath(member.label).name if member.label else "the payload"


def _alias_tables(members: Sequence[PayloadMember]) -> Dict[Optional[str], Dict[int, Tuple[str, Optional[str], str]]]:
    """Alias → (name, datatype, source) declared by the payloads that name aliased metrics.

    A BIRTH defines its level's aliases (an NBIRTH the node's, a DBIRTH the device's); a payload
    whose message type is unknown contributes to the level-less table every payload may consult.
    """
    tables: Dict[Optional[str], Dict[int, Tuple[str, Optional[str], str]]] = {}
    for member in members:
        for metric in member.payload.metrics:
            if metric.name is None or metric.alias is None:
                continue
            table = tables.setdefault(_level(member.message_type), {})
            table.setdefault(metric.alias, (metric.name, datatype_name(metric.datatype), _member_name(member)))
    return tables


def _payload_specs(
    builder: _Builder,
    member: PayloadMember,
    tables: Mapping[Optional[str], Mapping[int, Tuple[str, Optional[str], str]]],
    type_key: str,
) -> List[_MetricSpec]:
    """The metric specs of one payload, alias-only metrics named through a BIRTH when possible."""
    label = _member_name(member)
    own = tables.get(_level(member.message_type), {})
    fallback = tables.get(None, {})
    specs: List[_MetricSpec] = []
    for metric in member.payload.metrics:
        if metric.template is not None and metric.template.is_definition:
            continue
        if metric.name is not None:
            specs.append(_spec_from_metric(metric, f"Observed in the payload {label}."))
            continue
        assert metric.alias is not None
        resolved = own.get(metric.alias) or fallback.get(metric.alias)
        if resolved is None:
            spec = _spec_from_metric(
                metric,
                f"Alias-only metric {metric.alias} in {label}: its name is declared by the BIRTH "
                "certificate, which was not supplied.",
            )
            spec.unresolved_alias = True
            builder.limits.record("sparkplug.alias_unresolved", location=Keys.field(type_key, spec.name))
        else:
            name, datatype, source = resolved
            spec = _spec_from_metric(
                metric, f"Alias {metric.alias} in {label}, named through the BIRTH {source}.", name=name
            )
            if spec.datatype is None:
                spec.datatype = datatype
        specs.append(spec)
    return specs


def _record_payload_limits(builder: _Builder, member: PayloadMember) -> None:
    """Note the parts of a payload the reader skipped."""
    label = _member_name(member)
    unknown = member.payload.unknown_fields + sum(metric.unknown_fields for metric in member.payload.metrics)
    for _ in range(unknown):
        builder.limits.record("sparkplug.unknown_fields", location=label)
    if member.payload.body_length is not None:
        builder.limits.record("sparkplug.payload_body", location=label)


def _normalize_payloads(document: SparkplugDocument, builder: _Builder) -> Dict[str, Any]:
    """Channels, operations and types for a payload (or a fileset of payloads)."""
    members = list(document.payloads)
    for member in members:
        builder.define_templates(member.payload.metrics, f"Template definition in the payload {_member_name(member)}.")
    tables = _alias_tables(members)

    groups: Dict[Optional[str], List[PayloadMember]] = {}
    for member in members:
        groups.setdefault(member.message_type, []).append(member)
        _record_payload_limits(builder, member)

    channels: List[Channel] = []
    operations: List[Operation] = []
    for message_type, group in groups.items():
        type_name = message_type or "SparkplugPayload"
        type_key = Keys.type(type_name)
        labels = [_member_name(member) for member in group]
        evidence = " ".join(dict.fromkeys(member.evidence for member in group))
        specs: List[_MetricSpec] = []
        for member in group:
            specs.extend(_payload_specs(builder, member, tables, type_key))
        type_extras: Dict[str, Any] = {"sparkplug_sources": labels}
        if message_type:
            type_extras["sparkplug_message_type"] = message_type
        type_extras.update(builder.stamp(f"Metrics observed in {', '.join(labels)}."))
        builder.record(
            type_key,
            type_name,
            specs,
            namespace=None,
            description=f"Metrics carried by the {message_type or 'Sparkplug'} payload ({', '.join(labels)}).",
            extras=type_extras,
        )
        topic = topic_for_message_type(message_type)
        if message_type is None:
            builder.limits.record("sparkplug.message_type_unknown", location=", ".join(labels))
        channel = _channel(builder, topic, topic.address(), name=message_type or "Sparkplug payload", evidence=evidence)
        channels.append(channel)
        operations.append(
            _operation(
                builder,
                channel,
                message_type,
                payload_key=type_key,
                name=message_type or "Sparkplug payload",
                evidence=evidence,
                extra={"sparkplug_sources": labels},
            )
        )
    return {
        "channels": channels,
        "services": [
            Service(
                key="Sparkplug",
                name="Sparkplug",
                operations=operations,
                extras=builder.stamp("A payload names no edge node; the operations are grouped under one service."),
            )
        ],
        "servers": [],
        "record": {
            "input": "payload",
            "payloads": [
                {
                    key: value
                    for key, value in (
                        ("label", _member_name(member)),
                        ("messageType", member.message_type),
                        ("messageTypeEvidence", member.evidence),
                        ("timestamp", member.payload.timestamp),
                        ("seq", member.payload.seq),
                        ("uuid", member.payload.uuid),
                        ("metricCount", len(member.payload.metrics)),
                    )
                    if value is not None
                }
                for member in members
            ],
        },
    }


# ---------------------------------------------------------------------------
# Namespace description input
# ---------------------------------------------------------------------------


def _bindings(namespace: NamespaceDescription, retained: Optional[bool]) -> Optional[Dict[str, Any]]:
    """The declared MQTT operation binding (AsyncAPI's ``mqtt`` binding shape): QoS and retain."""
    binding: Dict[str, Any] = {}
    qos = namespace.broker.get("qos")
    if isinstance(qos, int) and not isinstance(qos, bool):
        binding["qos"] = qos
    if retained is not None:
        binding["retain"] = retained
    return {"mqtt": binding} if binding else None


def _normalize_namespace(namespace: NamespaceDescription, builder: _Builder) -> Dict[str, Any]:
    """Channels, operations, types and the broker for a topic-namespace description."""
    node_key = Keys.type(namespace.edge_node_id, namespace=namespace.group_id)
    if namespace.node_metrics:
        builder.record(
            node_key,
            namespace.edge_node_id,
            [_spec_from_catalogue(metric) for metric in namespace.node_metrics],
            namespace=namespace.group_id,
            description=f"Metrics of the edge node {namespace.edge_node_id}.",
            extras={"sparkplug_endpoint": "node"},
        )
    device_keys: Dict[str, str] = {}
    for device in namespace.devices:
        key = Keys.type(device.device_id, namespace=node_key)
        device_keys[device.device_id] = key
        builder.record(
            key,
            device.device_id,
            [_spec_from_catalogue(metric) for metric in device.metrics],
            namespace=node_key,
            description=device.description or f"Metrics of the device {device.device_id}.",
            extras={"sparkplug_endpoint": "device"},
        )

    channels: List[Channel] = []
    operations: List[Operation] = []
    for entry in namespace.topics:
        topic = entry.topic
        message_type = topic.message_type
        payload_key: Optional[str] = None
        if message_type in ("NBIRTH", "NDATA", "NCMD") and node_key in builder.types:
            payload_key = node_key
        elif message_type in ("DBIRTH", "DDATA", "DCMD"):
            payload_key = device_keys.get(topic.device_id or "")
            if payload_key is None:
                builder.limits.record("sparkplug.device_without_catalogue", location=entry.address)
        target = topic.device_id or topic.edge_node_id or topic.host_id or ""
        name = f"{message_type} {target}".strip()
        channel = _channel(builder, topic, entry.address, name=name, evidence=None)
        channels.append(channel)
        operations.append(
            _operation(
                builder,
                channel,
                message_type,
                payload_key=payload_key,
                name=name,
                direction=entry.direction,
                bindings=_bindings(namespace, entry.retained),
            )
        )
    servers: List[Server] = []
    url = namespace.broker.get("url")
    if isinstance(url, str) and url:
        settings = {key: value for key, value in namespace.broker.items() if key != "url"}
        servers.append(
            Server(
                url=url,
                name="broker",
                protocol="mqtt",
                extras={"sparkplug_broker": settings} if settings else {},
            )
        )
    service_key = f"{namespace.group_id}/{namespace.edge_node_id}"
    return {
        "channels": channels,
        "services": [Service(key=service_key, name=namespace.edge_node_id, operations=operations)],
        "servers": servers,
        "record": {
            "input": "namespace",
            "groupId": namespace.group_id,
            "edgeNodeId": namespace.edge_node_id,
            **({"hostApplicationId": namespace.host_application_id} if namespace.host_application_id else {}),
            "deviceIds": [device.device_id for device in namespace.devices],
            "topicCount": len(namespace.topics),
        },
    }


class SparkplugNormalizer(Normalizer, register=True):
    """Normalize a parsed Sparkplug input into an event-paradigm :class:`CanonicalApi`."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.EVENT

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map a :class:`~app.sparkplug_parser.SparkplugDocument` to the canonical model.

        Args:
            source: The parsed document.
            include_raw: Whether to keep the native record on ``raw``.

        Returns:
            The canonical model.

        Raises:
            ValueError: When ``source`` is not a parsed Sparkplug document.
        """
        if not isinstance(source, SparkplugDocument):
            raise ValueError("Sparkplug source must be a SparkplugDocument (see app.sparkplug_parser)")
        builder = _Builder(inferred=not source.is_namespace)
        if source.namespace is not None:
            parts = _normalize_namespace(source.namespace, builder)
            name = f"{source.namespace.group_id}/{source.namespace.edge_node_id}"
            description = source.namespace.description
        else:
            parts = _normalize_payloads(source, builder)
            label = source.label or (source.payloads[0].label if source.payloads else None)
            name = PurePosixPath(label).stem if label else "Sparkplug B payload"
            description = (
                "Inferred from Sparkplug B payloads alone: the topics they were published on were "
                "not supplied, so the group, edge node and device are address parameters."
            )
        record = dict(parts["record"])
        record["capability_limits"] = _limits_payload(builder.limits.limits())
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol="mqtt",
            identity=ApiIdentity(name=name, namespace=SPARKPLUG_NAMESPACE),
            title=name,
            description=description,
            servers=parts["servers"],
            services=parts["services"],
            channels=parts["channels"],
            types=list(builder.types.values()),
            raw=raw_record(source) if include_raw else None,
            extras={SPARKPLUG_EXTRAS_KEY: record},
        )
        return normalize_ordering(api)
