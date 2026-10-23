"""MQTT Sparkplug B reader — FMT-9.2 (#5469).

Sparkplug B defines both the **payload** an industrial edge node publishes (protobuf metrics,
:mod:`app.sparkplug_payload`) and the **topic namespace** those payloads travel on::

    spBv1.0/<group_id>/<message_type>/<edge_node_id>[/<device_id>]
    spBv1.0/STATE/<host_application_id>

This module reads the two inputs an import can carry:

* **payloads** — one binary payload, or a fileset of them (a DBIRTH beside the DDATA payloads
  that refer to its metrics by alias). A payload does not carry its topic, so the message type is
  *inferred*: from a message-type token in the file name (``…-dbirth.bin``) and, failing that,
  from the content (a lone ``bdSeq`` is an NDEATH; ``bdSeq`` among named metrics is an NBIRTH).
  The group, edge node and device are unknowable and stay address parameters.
* **a topic-namespace description** — a JSON document naming the group, the edge node, its
  topics, and the metric catalogue of the node and of each device. Every topic is checked
  against the declared identity: a topic in another namespace, another group or for another edge
  node is a contradiction, and the import is refused (``INPUT_SEMANTIC_INVALID``) rather than
  guessed at.

:func:`parse_topic` is the topic grammar both inputs share.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .fileset import IntakeFileset
from .proxy_route_common import load_json_document
from .sparkplug_payload import SparkplugPayload, SparkplugWireError, decode_payload, sniff_payload

__all__ = [
    "DEVICE_MESSAGE_TYPES",
    "FORMAT_KEY",
    "INBOUND_MESSAGE_TYPES",
    "MESSAGE_TYPES",
    "NODE_MESSAGE_TYPES",
    "PAYLOAD_SUFFIXES",
    "SPARKPLUG_NAMESPACE",
    "CatalogueMetric",
    "NamespaceDescription",
    "NamespaceDevice",
    "NamespaceTopic",
    "PayloadMember",
    "SparkplugDocument",
    "SparkplugParseError",
    "SparkplugTopic",
    "declares_namespace",
    "has_namespace_marker",
    "infer_message_type",
    "is_namespace_document",
    "parse_sparkplug_bytes",
    "parse_sparkplug_fileset",
    "parse_sparkplug_text",
    "parse_topic",
]

FORMAT_KEY = "sparkplug"

#: The topic namespace element of Sparkplug B (``spBv1.0``).
SPARKPLUG_NAMESPACE = "spBv1.0"

#: Message types an edge node publishes or receives about itself.
NODE_MESSAGE_TYPES: Tuple[str, ...] = ("NBIRTH", "NDEATH", "NDATA", "NCMD")
#: Message types about a device behind an edge node (the topic names the device).
DEVICE_MESSAGE_TYPES: Tuple[str, ...] = ("DBIRTH", "DDEATH", "DDATA", "DCMD")
#: Every message type, ``STATE`` (a host application's online state) included.
MESSAGE_TYPES: Tuple[str, ...] = NODE_MESSAGE_TYPES + DEVICE_MESSAGE_TYPES + ("STATE",)
#: Message types an edge node *receives*: commands to it and the host application's state.
INBOUND_MESSAGE_TYPES = frozenset({"NCMD", "DCMD", "STATE"})

#: File suffixes claimed as binary Sparkplug payloads, even when the bytes are broken.
PAYLOAD_SUFFIXES: Tuple[str, ...] = (".bin",)

#: Characters a Sparkplug identifier must not contain (topic separator and MQTT wildcards).
_ID_FORBIDDEN = re.compile(r"[/+#]")

#: A message-type token in a file name, bounded by anything that is not a letter.
_MESSAGE_TYPE_TOKEN = re.compile(
    r"(?<![a-z])(" + "|".join(t.lower() for t in MESSAGE_TYPES if t != "STATE") + r")(?![a-z])"
)

#: The metric every NBIRTH and NDEATH carries: the birth/death sequence number.
BDSEQ_METRIC = "bdSeq"


class SparkplugParseError(ValueError):
    """A Sparkplug input could not be read.

    Attributes:
        code: Intake-taxonomy code, or ``None`` to let the pipeline classify the failure
            (a document that is not Sparkplug at all is the pipeline's call to make).
    """

    def __init__(self, message: str, *, code: Optional[str] = "INPUT_MALFORMED") -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Topic grammar
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SparkplugTopic:
    """A Sparkplug topic, parsed into its components.

    A component that is not known — every identifier of a payload imported without its topic —
    is ``None`` and becomes an address parameter (``{group_id}``).

    Attributes:
        namespace: The namespace element (``spBv1.0``).
        message_type: The message type, or ``None`` when it could not be determined.
        group_id: The group, or ``None`` when unknown.
        edge_node_id: The edge node, or ``None`` when unknown.
        device_id: The device, or ``None`` (unknown, or a node-level message).
        host_id: The host application of a ``STATE`` topic.
        device_level: ``True`` for a device message, ``False`` for a node message, ``None`` when
            the message type is unknown.
    """

    namespace: str = SPARKPLUG_NAMESPACE
    message_type: Optional[str] = None
    group_id: Optional[str] = None
    edge_node_id: Optional[str] = None
    device_id: Optional[str] = None
    host_id: Optional[str] = None
    device_level: Optional[bool] = None

    def segments(self) -> List[Tuple[str, Optional[str]]]:
        """The address as ``(component, value)`` pairs; a ``None`` value is a parameter."""
        if self.message_type == "STATE":
            return [("namespace", self.namespace), ("message_type", "STATE"), ("host_id", self.host_id)]
        pairs: List[Tuple[str, Optional[str]]] = [
            ("namespace", self.namespace),
            ("group_id", self.group_id),
            ("message_type", self.message_type),
            ("edge_node_id", self.edge_node_id),
        ]
        if self.device_level:
            pairs.append(("device_id", self.device_id))
        return pairs

    def address(self) -> str:
        """The wire address, with ``{component}`` placeholders for unknown components."""
        return "/".join(value if value is not None else "{" + name + "}" for name, value in self.segments())

    def parameters(self) -> List[str]:
        """The components that are address parameters, in address order."""
        return [name for name, value in self.segments() if value is None]

    def components(self) -> Dict[str, Optional[str]]:
        """Every component by name — ``None`` for a parameter — for the channel's provenance."""
        return {name: value for name, value in self.segments()}


def _check_identifier(value: str, what: str, topic: str) -> None:
    """Reject an empty identifier or one carrying ``/``, ``+`` or ``#``."""
    if not value:
        raise SparkplugParseError(f"Topic {topic!r} has an empty {what}", code="INPUT_SEMANTIC_INVALID")
    if _ID_FORBIDDEN.search(value):
        raise SparkplugParseError(
            f"Topic {topic!r}: the {what} {value!r} contains '/', '+' or '#'", code="INPUT_SEMANTIC_INVALID"
        )


def parse_topic(topic: str) -> SparkplugTopic:
    """Parse one Sparkplug B topic.

    Accepts ``spBv1.0/<group>/<type>/<edge node>[/<device>]``, ``spBv1.0/STATE/<host>`` and the
    Sparkplug 2.2 host form ``STATE/<host>``.

    Args:
        topic: The topic string.

    Returns:
        The parsed topic (its ``namespace`` is whatever the first segment says — the caller decides
        whether a foreign namespace is acceptable).

    Raises:
        SparkplugParseError: ``INPUT_SEMANTIC_INVALID`` when the topic does not have the
            Sparkplug shape — an unknown message type, a node message naming a device, a device
            message without one, or a missing segment.
    """
    parts = topic.split("/")
    if len(parts) == 2 and parts[0] == "STATE":
        _check_identifier(parts[1], "host application id", topic)
        return SparkplugTopic(message_type="STATE", host_id=parts[1], device_level=False)
    if len(parts) == 3 and parts[1] == "STATE":
        _check_identifier(parts[2], "host application id", topic)
        return SparkplugTopic(namespace=parts[0], message_type="STATE", host_id=parts[2], device_level=False)
    if len(parts) < 4:
        raise SparkplugParseError(
            f"Topic {topic!r} has {len(parts)} segment(s); a Sparkplug topic is "
            "namespace/group_id/message_type/edge_node_id[/device_id]",
            code="INPUT_SEMANTIC_INVALID",
        )
    if len(parts) > 5:
        raise SparkplugParseError(
            f"Topic {topic!r} has {len(parts)} segments; a Sparkplug topic has at most five",
            code="INPUT_SEMANTIC_INVALID",
        )
    namespace, group_id, message_type, edge_node_id = parts[:4]
    device_id = parts[4] if len(parts) == 5 else None
    if message_type not in MESSAGE_TYPES or message_type == "STATE":
        raise SparkplugParseError(
            f"Topic {topic!r}: {message_type!r} is not a Sparkplug message type", code="INPUT_SEMANTIC_INVALID"
        )
    _check_identifier(group_id, "group id", topic)
    _check_identifier(edge_node_id, "edge node id", topic)
    device_level = message_type in DEVICE_MESSAGE_TYPES
    if device_level and device_id is None:
        raise SparkplugParseError(
            f"Topic {topic!r}: a {message_type} topic names the device after the edge node",
            code="INPUT_SEMANTIC_INVALID",
        )
    if not device_level and device_id is not None:
        raise SparkplugParseError(
            f"Topic {topic!r}: a {message_type} topic is about the edge node and names no device",
            code="INPUT_SEMANTIC_INVALID",
        )
    if device_id is not None:
        _check_identifier(device_id, "device id", topic)
    return SparkplugTopic(
        namespace=namespace,
        message_type=message_type,
        group_id=group_id,
        edge_node_id=edge_node_id,
        device_id=device_id,
        device_level=device_level,
    )


def topic_for_message_type(message_type: Optional[str]) -> SparkplugTopic:
    """The topic of a payload imported without one: identifiers unknown, level from the type."""
    if message_type is None:
        return SparkplugTopic()
    return SparkplugTopic(message_type=message_type, device_level=message_type in DEVICE_MESSAGE_TYPES)


# ---------------------------------------------------------------------------
# Payload inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PayloadMember:
    """One payload of a payload import.

    Attributes:
        label: The file the payload came from (or ``None`` for an unnamed upload).
        payload: The decoded payload.
        data: The raw bytes (hashed by the analysis).
        message_type: The inferred message type, or ``None`` when neither the file name nor the
            content settles it.
        evidence: One sentence saying how the message type was inferred.
    """

    label: Optional[str]
    payload: SparkplugPayload
    data: bytes
    message_type: Optional[str]
    evidence: str

    @property
    def topic(self) -> SparkplugTopic:
        """The (parameterised) topic the payload was published on."""
        return topic_for_message_type(self.message_type)


def infer_message_type(payload: SparkplugPayload, label: Optional[str]) -> Tuple[Optional[str], str]:
    """Infer which Sparkplug message a payload is, since the payload does not say.

    The file name is consulted first — a message-type token bounded by non-letters
    (``06-typical-ddata.bin``, ``dbirth.bin``) is what the person who saved the payload knew. The
    content decides otherwise, on the two signatures the specification fixes: an NDEATH carries
    only ``bdSeq``, and an NBIRTH carries ``bdSeq`` among its named metrics. Anything else is left
    undetermined rather than guessed.

    Args:
        payload: The decoded payload.
        label: The file name or path, when known.

    Returns:
        ``(message type or None, evidence sentence)``.
    """
    name = PurePosixPath(label).name.lower() if label else ""
    match = _MESSAGE_TYPE_TOKEN.search(name)
    if match:
        found = match.group(1).upper()
        return found, f"Message type {found} inferred from the file name {PurePosixPath(label or '').name!r}."
    names = [metric.name for metric in payload.metrics]
    if names == [BDSEQ_METRIC]:
        return "NDEATH", "Message type NDEATH inferred: the payload carries only the bdSeq metric."
    if BDSEQ_METRIC in names and all(names):
        return "NBIRTH", "Message type NBIRTH inferred: the payload names every metric and carries bdSeq."
    return None, (
        "The message type could not be inferred: a payload does not carry its topic, and neither "
        "the file name nor the metrics settle it."
    )


def _payload_member(data: bytes, label: Optional[str]) -> PayloadMember:
    """Decode and classify one payload, refusing one with nothing to describe."""
    try:
        payload = decode_payload(data)
    except SparkplugWireError as exc:
        where = f" ({label})" if label else ""
        raise SparkplugParseError(f"{exc}{where}", code=exc.code) from None
    if not payload.metrics:
        raise SparkplugParseError(
            "The Sparkplug payload carries no metrics, so it describes no message schema"
            + (f" ({label})" if label else ""),
            code="INPUT_SEMANTIC_INVALID",
        )
    for index, metric in enumerate(payload.metrics, start=1):
        if metric.name is None and metric.alias is None:
            raise SparkplugParseError(
                f"Metric {index} has neither a name nor an alias, so nothing can refer to it",
                code="INPUT_SEMANTIC_INVALID",
            )
    message_type, evidence = infer_message_type(payload, label)
    return PayloadMember(label=label, payload=payload, data=data, message_type=message_type, evidence=evidence)


# ---------------------------------------------------------------------------
# Topic-namespace description
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CatalogueMetric:
    """One metric of a namespace description's catalogue.

    Attributes:
        name: The metric name.
        alias: Its alias, when declared.
        datatype: The Sparkplug datatype name as written (``"Double"``), when declared.
        description: Its description.
        properties: Every other key of the metric object (``engUnit``, ``writable`` …), in order.
    """

    name: str
    alias: Optional[int]
    datatype: Optional[str]
    description: Optional[str]
    properties: Tuple[Tuple[str, Any], ...]


@dataclass(frozen=True)
class NamespaceDevice:
    """A device behind the edge node and its metric catalogue."""

    device_id: str
    description: Optional[str]
    metrics: Tuple[CatalogueMetric, ...]


@dataclass(frozen=True)
class NamespaceTopic:
    """One declared topic.

    Attributes:
        topic: The parsed topic.
        address: The topic as written.
        retained: The declared MQTT retain flag, when stated.
        direction: ``"inbound"`` / ``"outbound"`` as declared, else ``None``.
    """

    topic: SparkplugTopic
    address: str
    retained: Optional[bool]
    direction: Optional[str]


@dataclass(frozen=True)
class NamespaceDescription:
    """A parsed topic-namespace description."""

    group_id: str
    edge_node_id: str
    host_application_id: Optional[str]
    description: Optional[str]
    broker: Dict[str, Any]
    topics: Tuple[NamespaceTopic, ...]
    devices: Tuple[NamespaceDevice, ...]
    node_metrics: Tuple[CatalogueMetric, ...]


#: Keys of a catalogue metric that are read into its own attributes; the rest are properties.
_METRIC_KEYS = frozenset({"name", "alias", "datatype", "description"})


def is_namespace_document(document: Any) -> bool:
    """Whether a parsed JSON value is a Sparkplug topic-namespace description."""
    return isinstance(document, dict) and document.get("namespace") == SPARKPLUG_NAMESPACE


#: The declaration a namespace description opens with, as text.
_NAMESPACE_DECLARATION = re.compile(r'"namespace"\s*:\s*"spBv1\.0"')


def declares_namespace(text: Optional[str]) -> bool:
    """Whether text declares ``"namespace": "spBv1.0"`` — the mark of a namespace description."""
    return bool(text) and bool(_NAMESPACE_DECLARATION.search(text or ""))


def has_namespace_marker(text: Optional[str]) -> bool:
    """Whether text declares the Sparkplug namespace or quotes an ``spBv1.0/`` topic."""
    if not text:
        return False
    return declares_namespace(text) or f'"{SPARKPLUG_NAMESPACE}/' in text


def _optional_text(document: Mapping[str, Any], key: str, where: str) -> Optional[str]:
    value = document.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SparkplugParseError(f"{where}: {key!r} must be a string", code="INPUT_SEMANTIC_INVALID")
    return value


def _catalogue(raw: Any, where: str) -> Tuple[CatalogueMetric, ...]:
    """Read a metric catalogue (a list of metric objects)."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise SparkplugParseError(f"{where} must be a list of metrics", code="INPUT_SEMANTIC_INVALID")
    metrics: List[CatalogueMetric] = []
    seen: Dict[str, int] = {}
    aliases: Dict[int, str] = {}
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"]:
            raise SparkplugParseError(f"{where}, metric {index}: a metric needs a name", code="INPUT_SEMANTIC_INVALID")
        name = item["name"]
        if name in seen:
            raise SparkplugParseError(f"{where}: metric {name!r} is listed twice", code="INPUT_SEMANTIC_INVALID")
        seen[name] = index
        alias = item.get("alias")
        if alias is not None and (not isinstance(alias, int) or isinstance(alias, bool) or alias < 0):
            raise SparkplugParseError(
                f"{where}, metric {name!r}: an alias is a non-negative integer", code="INPUT_SEMANTIC_INVALID"
            )
        if alias is not None and alias in aliases:
            raise SparkplugParseError(
                f"{where}: alias {alias} is given to both {aliases[alias]!r} and {name!r}",
                code="INPUT_SEMANTIC_INVALID",
            )
        if alias is not None:
            aliases[alias] = name
        datatype = item.get("datatype")
        if datatype is not None and not isinstance(datatype, str):
            raise SparkplugParseError(
                f"{where}, metric {name!r}: datatype must be a Sparkplug datatype name", code="INPUT_SEMANTIC_INVALID"
            )
        metrics.append(
            CatalogueMetric(
                name=name,
                alias=alias,
                datatype=datatype,
                description=_optional_text(item, "description", f"{where}, metric {name!r}"),
                properties=tuple((key, value) for key, value in item.items() if key not in _METRIC_KEYS),
            )
        )
    return tuple(metrics)


def _identifier(document: Mapping[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value or _ID_FORBIDDEN.search(value):
        raise SparkplugParseError(
            f"The namespace description needs a {key!r}: a non-empty identifier without '/', '+' or '#'",
            code="INPUT_SEMANTIC_INVALID",
        )
    return value


def _identity_problems(address: str, document: Mapping[str, Any]) -> List[str]:
    """Contradictions between a topic's segments and the description's declared identity.

    Read from the raw segments, before the topic grammar is applied, so a topic that is both
    misshapen and in the wrong group reports both faults.
    """
    parts = address.split("/")
    problems: List[str] = []
    if parts[0] != SPARKPLUG_NAMESPACE and not (len(parts) == 2 and parts[0] == "STATE"):
        problems.append(f"Topic {address!r} is in namespace {parts[0]!r}, not {SPARKPLUG_NAMESPACE!r}")
    is_state = (len(parts) == 2 and parts[0] == "STATE") or (len(parts) == 3 and parts[1] == "STATE")
    if is_state:
        host = document.get("hostApplicationId")
        if isinstance(host, str) and host and parts[-1] != host:
            problems.append(f"Topic {address!r} names host application {parts[-1]!r}, not {host!r}")
        return problems
    if len(parts) > 1 and parts[1] != document.get("groupId"):
        problems.append(f"Topic {address!r} is in group {parts[1]!r}, not {document.get('groupId')!r}")
    if len(parts) > 3 and parts[3] != document.get("edgeNodeId"):
        problems.append(f"Topic {address!r} is for edge node {parts[3]!r}, not {document.get('edgeNodeId')!r}")
    return problems


def _namespace_topic(
    item: Any, index: int, document: Mapping[str, Any], problems: List[str]
) -> Optional[NamespaceTopic]:
    """Read one declared topic, adding every contradiction with the declared identity to ``problems``."""
    if not isinstance(item, dict) or not isinstance(item.get("topic"), str):
        problems.append(f"topic {index}: a topic entry needs a 'topic' string")
        return None
    address = item["topic"]
    problems.extend(_identity_problems(address, document))
    try:
        topic = parse_topic(address)
    except SparkplugParseError as exc:
        problems.append(str(exc))
        return None
    declared_type = item.get("messageType")
    if declared_type is not None and declared_type != topic.message_type:
        problems.append(f"Topic {address!r} is a {topic.message_type} topic but is listed as {declared_type!r}")
    retained = item.get("retained")
    direction = item.get("direction")
    if retained is not None and not isinstance(retained, bool):
        problems.append(f"Topic {address!r}: 'retained' must be true or false")
        retained = None
    if direction is not None and direction not in ("inbound", "outbound"):
        problems.append(f"Topic {address!r}: 'direction' must be 'inbound' or 'outbound'")
        direction = None
    return NamespaceTopic(topic=topic, address=address, retained=retained, direction=direction)


def _namespace_description(document: Mapping[str, Any]) -> NamespaceDescription:
    """Validate a namespace description against its own declared identity.

    Raises:
        SparkplugParseError: ``INPUT_SEMANTIC_INVALID`` listing every contradiction found.
    """
    group_id = _identifier(document, "groupId")
    edge_node_id = _identifier(document, "edgeNodeId")
    host = document.get("hostApplicationId")
    if host is not None and (not isinstance(host, str) or not host):
        raise SparkplugParseError("'hostApplicationId' must be a non-empty string", code="INPUT_SEMANTIC_INVALID")
    raw_topics = document.get("topics")
    if not isinstance(raw_topics, list) or not raw_topics:
        raise SparkplugParseError(
            "The namespace description lists no topics, so it describes no channel", code="INPUT_SEMANTIC_INVALID"
        )
    problems: List[str] = []
    topics: List[NamespaceTopic] = []
    seen: Dict[str, int] = {}
    for index, item in enumerate(raw_topics, start=1):
        topic = _namespace_topic(item, index, document, problems)
        if topic is None:
            continue
        if topic.address in seen:
            problems.append(f"Topic {topic.address!r} is listed twice")
            continue
        seen[topic.address] = index
        topics.append(topic)
    if problems:
        raise SparkplugParseError(
            "The topic namespace contradicts its declared identity: " + "; ".join(problems),
            code="INPUT_SEMANTIC_INVALID",
        )
    raw_devices = document.get("devices") or []
    if not isinstance(raw_devices, list):
        raise SparkplugParseError("'devices' must be a list", code="INPUT_SEMANTIC_INVALID")
    devices: List[NamespaceDevice] = []
    device_ids: Dict[str, int] = {}
    for index, item in enumerate(raw_devices, start=1):
        if not isinstance(item, dict):
            raise SparkplugParseError(f"device {index} must be an object", code="INPUT_SEMANTIC_INVALID")
        device_id = _identifier(item, "deviceId")
        if device_id in device_ids:
            raise SparkplugParseError(f"Device {device_id!r} is listed twice", code="INPUT_SEMANTIC_INVALID")
        device_ids[device_id] = index
        devices.append(
            NamespaceDevice(
                device_id=device_id,
                description=_optional_text(item, "description", f"Device {device_id!r}"),
                metrics=_catalogue(item.get("metrics"), f"Device {device_id!r} metrics"),
            )
        )
    broker = document.get("broker")
    if broker is not None and not isinstance(broker, dict):
        raise SparkplugParseError("'broker' must be an object", code="INPUT_SEMANTIC_INVALID")
    return NamespaceDescription(
        group_id=group_id,
        edge_node_id=edge_node_id,
        host_application_id=host,
        description=_optional_text(document, "description", "The namespace description"),
        broker=dict(broker or {}),
        topics=tuple(topics),
        devices=tuple(devices),
        node_metrics=_catalogue(document.get("nodeMetrics"), "nodeMetrics"),
    )


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SparkplugDocument:
    """A parsed Sparkplug import: payloads, or a topic-namespace description.

    Attributes:
        label: The upload's file name or path.
        payloads: The payloads, root first (empty for a namespace description).
        namespace: The namespace description (``None`` for payloads).
        source: The exact material read — the namespace text, or the payload bytes (a fileset's
            payloads concatenated in member order) — hashed by the analysis.
    """

    label: Optional[str]
    payloads: Tuple[PayloadMember, ...] = ()
    namespace: Optional[NamespaceDescription] = None
    source: Any = None

    @property
    def is_namespace(self) -> bool:
        """Whether the document is a topic-namespace description."""
        return self.namespace is not None


def parse_sparkplug_bytes(data: bytes, *, label: Optional[str] = None) -> SparkplugDocument:
    """Parse one binary Sparkplug payload.

    Raises:
        SparkplugParseError: The payload is empty, truncated, malformed or describes nothing.
    """
    member = _payload_member(data, label)
    return SparkplugDocument(label=label, payloads=(member,), source=data)


def parse_sparkplug_text(text: str, *, label: Optional[str] = None) -> SparkplugDocument:
    """Parse a topic-namespace description.

    Raises:
        SparkplugParseError: ``INPUT_ENCODING_INVALID`` for text that did not decode as UTF-8;
            ``INPUT_TRUNCATED`` / ``INPUT_MALFORMED`` for broken JSON; ``INPUT_SEMANTIC_INVALID``
            for a description that contradicts itself; and no code for JSON that is not a
            Sparkplug namespace description at all (the pipeline decides what it is instead).
    """
    if "\ufffd" in text or "\x00" in text:
        raise SparkplugParseError(
            "The document is not UTF-8 text (it may be UTF-16, or a binary payload sent as text)",
            code="INPUT_ENCODING_INVALID",
        )
    try:
        document = load_json_document(text.lstrip("\ufeff"), format_label="Sparkplug namespace description")
    except ValueError as exc:
        code = getattr(exc, "code", "INPUT_MALFORMED")
        if has_namespace_marker(text):
            raise SparkplugParseError(str(exc), code=code) from None
        raise SparkplugParseError(
            "The document is neither a Sparkplug payload nor a JSON topic-namespace description", code=None
        ) from None
    if not isinstance(document, dict):
        raise SparkplugParseError("A Sparkplug namespace description is a JSON object", code=None)
    if not is_namespace_document(document):
        if "namespace" in document and ("groupId" in document or "topics" in document):
            raise SparkplugParseError(
                f"The namespace is {document.get('namespace')!r}; this reader understands {SPARKPLUG_NAMESPACE!r}",
                code="INPUT_SEMANTIC_INVALID",
            )
        raise SparkplugParseError(f'The JSON document does not declare "namespace": "{SPARKPLUG_NAMESPACE}"', code=None)
    return SparkplugDocument(label=label, namespace=_namespace_description(document), source=text)


def parse_sparkplug_fileset(fileset: IntakeFileset, *, label: Optional[str] = None) -> SparkplugDocument:
    """Parse a set of payloads (a session: a BIRTH and the DATA / DEATH payloads after it).

    The root and every member with a payload suffix (``.bin``) — or whose bytes are a payload —
    are read from their exact bytes (:meth:`~app.fileset.IntakeFileset.member_bytes`), root first
    and then in path order; other files (a README) are ignored. A JSON root is read as a namespace
    description on its own.

    Args:
        fileset: The set, its binary members' bytes included.
        label: The upload's label.

    Raises:
        SparkplugParseError: Any payload read fails.
    """
    root = fileset.root
    if root.lower().endswith(".json"):
        return parse_sparkplug_text(fileset.members[root], label=root)
    order = [root] + sorted(path for path in fileset.members if path != root)
    payloads: List[PayloadMember] = []
    material: List[bytes] = []
    for path in order:
        data = fileset.member_bytes(path)
        if path != root and not path.lower().endswith(PAYLOAD_SUFFIXES) and not sniff_payload(data):
            continue
        payloads.append(_payload_member(data, path))
        material.append(data)
    return SparkplugDocument(label=label or root, payloads=tuple(payloads), source=b"".join(material))


def raw_record(document: SparkplugDocument) -> Dict[str, Any]:
    """The lossless native record kept on ``CanonicalApi.raw``.

    Payload bytes are kept as hexadecimal (one string per payload), a namespace description as
    its parsed JSON.
    """
    if document.is_namespace:
        assert isinstance(document.source, str)
        return {"namespace": json.loads(document.source.lstrip("\ufeff"))}
    return {
        "payloads": [
            {"label": member.label, "hex": member.data.hex(), "messageType": member.message_type}
            for member in document.payloads
        ]
    }


def payload_labels(payloads: Sequence[PayloadMember]) -> List[str]:
    """Display labels of a payload set (file names, or ``payload <n>``)."""
    return [
        PurePosixPath(member.label).name if member.label else f"payload {index}"
        for index, member in enumerate(payloads, start=1)
    ]
