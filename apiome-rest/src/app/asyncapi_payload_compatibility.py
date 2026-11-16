"""AsyncAPI message payloads graded by their own format's check — XPC-4.4 (#5748).

An AsyncAPI message names the language of its payload with ``schemaFormat`` (on the message in
AsyncAPI 2, inside a Multi Format Schema Object ``{schemaFormat, schema}`` in AsyncAPI 3). This
module compares two versions of one payload with the check of that language, so an Avro payload
inside an AsyncAPI document gets the Avro rules:

* absent, ``application/vnd.aai.asyncapi`` (``+json`` / ``+yaml``), ``application/schema+json`` or
  ``application/schema+yaml`` → the JSON Schema comparator
  (:func:`app.jsonschema_compatibility.compare_schemas`, XPC-4.2, ``jsonschema.*`` rule ids);
* ``application/vnd.apache.avro`` (``+json`` / ``+yaml``) → Avro schema resolution run both ways
  (:func:`app.avro_compatibility.can_read`, XPC-4.1, ``avro-compatibility.*``);
* ``application/vnd.google.protobuf`` or ``application/x-protobuf`` → the Protobuf classifier over
  the compiled ``.proto`` text (XPC-4.3, ``protobuf.*``);
* anything else (RAML, the OpenAPI Schema Object, …) is not compared, and the caller keeps its grade.

Every finding is graded per **side** (:class:`SideFinding`): the ``consumer`` side is what a
consumer that upgrades first meets (new consumers reading old producers' data — the side
``BACKWARD`` checks), the ``producer`` side what old consumers meet when a producer upgrades first
(the side ``FORWARD`` checks). A JSON Schema or Avro problem found with the *new* schema as the
reader is a consumer-side break; one found with the *old* schema as the reader is a producer-side
break; Protobuf's wire rules are not directional, so they grade both sides alike.

A ``schemaFormat`` that moves to another language is ``asyncapi.both.schema-format-changed``,
breaking both sides: no reader of one language can decode the other. Only the media type counts —
``application/vnd.apache.avro;version=1.9.0`` and ``…;version=1.11.0`` are the same language.

The module is pure for JSON Schema and Avro. The Protobuf check compiles the payload's ``.proto``
text through the ``buf``-backed import source; when ``buf`` is not installed, or the text does not
compile, that payload is not compared (``None``) and the caller's grade stands.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Tuple

from .breaking_change import Severity

__all__ = [
    "AVRO",
    "JSON_SCHEMA",
    "PROTOBUF",
    "SideFinding",
    "compare_payloads",
    "payload_of",
    "schema_family",
    "schema_format_identity",
    "side_rule_id",
]

#: Payload language families this module can compare.
JSON_SCHEMA = "json-schema"
AVRO = "avro"
PROTOBUF = "protobuf"

#: The media type an absent ``schemaFormat`` means: the AsyncAPI Schema Object (a JSON Schema superset).
_DEFAULT_SCHEMA_FORMAT = "application/vnd.aai.asyncapi"

#: Media type (suffix and parameters removed) → family.
_FAMILIES = {
    "application/vnd.aai.asyncapi": JSON_SCHEMA,
    "application/schema": JSON_SCHEMA,
    "application/vnd.apache.avro": AVRO,
    "application/vnd.google.protobuf": PROTOBUF,
    "application/x-protobuf": PROTOBUF,
    "application/protobuf": PROTOBUF,
}

#: Structured-syntax suffixes that do not change the schema language (``+json`` / ``+yaml``).
_SUFFIXES = ("+json", "+yaml")

#: Rule id of a payload pair the payload's own check accepts both ways.
PAYLOAD_COMPATIBLE_RULE = "asyncapi.both.payload-compatible"


@dataclass(frozen=True)
class SideFinding:
    """One compatibility finding, graded for each side of a channel.

    Attributes:
        rule_id: Stable rule id, e.g. ``asyncapi.consumer.message-removed`` or a delegated
            payload rule such as ``avro-compatibility.reader-field-missing-default-value``.
        consumer: The grade for consumers that upgrade first (new consumers, old producers).
        producer: The grade for producers that upgrade first (old consumers, new producers).
        message: One-line human explanation of what changed.
    """

    rule_id: str
    consumer: Severity
    producer: Severity
    message: str


_RANK = {Severity.SAFE: 0, Severity.DANGEROUS: 1, Severity.BREAKING: 2}


def side_rule_id(rule: str, consumer: Severity, producer: Severity) -> str:
    """Build an ``asyncapi.<side>.<rule>`` id, naming the side the change is worst for.

    Args:
        rule: The rule slug, e.g. ``message-removed``.
        consumer: The consumer-side grade.
        producer: The producer-side grade.

    Returns:
        ``asyncapi.consumer.<rule>`` when consumers fare worse, ``asyncapi.producer.<rule>`` when
        producers do, else ``asyncapi.both.<rule>``.
    """
    if _RANK[consumer] > _RANK[producer]:
        side = "consumer"
    elif _RANK[producer] > _RANK[consumer]:
        side = "producer"
    else:
        side = "both"
    return f"asyncapi.{side}.{rule}"


def schema_format_identity(schema_format: Any) -> str:
    """Reduce a ``schemaFormat`` to the schema language it names.

    Args:
        schema_format: The declared ``schemaFormat`` (``None`` when absent).

    Returns:
        The lower-cased media type without parameters or a ``+json`` / ``+yaml`` suffix; the
        AsyncAPI default for an absent or blank value.
    """
    if not isinstance(schema_format, str) or not schema_format.strip():
        return _DEFAULT_SCHEMA_FORMAT
    media = schema_format.split(";", 1)[0].strip().lower()
    for suffix in _SUFFIXES:
        if media.endswith(suffix):
            media = media[: -len(suffix)]
    return media or _DEFAULT_SCHEMA_FORMAT


def schema_family(schema_format: Any) -> Optional[str]:
    """Return the family a ``schemaFormat`` belongs to, or ``None`` when none is supported."""
    return _FAMILIES.get(schema_format_identity(schema_format))


def payload_of(message: Mapping[str, Any]) -> Tuple[Any, Any]:
    """Split an AsyncAPI message into its ``(schemaFormat, payload schema)``.

    Args:
        message: The message object (AsyncAPI 2 or 3, dereferenced).

    Returns:
        For an AsyncAPI 3 Multi Format Schema Object payload, its ``schemaFormat`` and ``schema``;
        otherwise the message's ``schemaFormat`` and its ``payload``.
    """
    payload = message.get("payload")
    if isinstance(payload, Mapping) and "schemaFormat" in payload and "schema" in payload:
        return payload.get("schemaFormat"), payload.get("schema")
    return message.get("schemaFormat"), payload


def compare_payloads(old: Mapping[str, Any], new: Mapping[str, Any]) -> Optional[List[SideFinding]]:
    """Compare the payloads of two versions of one message.

    Args:
        old: The old message object.
        new: The new message object.

    Returns:
        The findings: one ``schema-format-changed`` finding when the language moved, the payload
        check's findings otherwise, or a single ``payload-compatible`` SAFE finding when the check
        accepts the pair both ways. ``[]`` when the payloads are identical. ``None`` when the
        language is not supported or a schema cannot be read, so the caller keeps its own grade.
    """
    old_format, old_schema = payload_of(old)
    new_format, new_schema = payload_of(new)
    old_identity, new_identity = schema_format_identity(old_format), schema_format_identity(new_format)
    if old_identity != new_identity:
        return [
            SideFinding(
                rule_id=side_rule_id("schema-format-changed", Severity.BREAKING, Severity.BREAKING),
                consumer=Severity.BREAKING,
                producer=Severity.BREAKING,
                message=f"payload schemaFormat changed from {old_identity} to {new_identity}",
            )
        ]
    if _canonical(old_schema) == _canonical(new_schema):
        return []
    family = _FAMILIES.get(new_identity)
    if family == JSON_SCHEMA:
        found: Optional[List[SideFinding]] = _json_schema_findings(old_schema, new_schema)
    elif family == AVRO:
        found = _avro_findings(old_schema, new_schema)
    elif family == PROTOBUF:
        found = _protobuf_findings(old_schema, new_schema)
    else:
        return None
    if found is None:
        return None
    if not found:
        return [
            SideFinding(
                rule_id=PAYLOAD_COMPATIBLE_RULE,
                consumer=Severity.SAFE,
                producer=Severity.SAFE,
                message=f"the {family} payload check reads the change both ways",
            )
        ]
    return found


def _canonical(value: Any) -> str:
    """A key-order-independent string of ``value``, for equality."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _directional(direction: str, rule_id: str, message: str) -> SideFinding:
    """A finding from a reader/writer check: ``backward`` breaks consumers, ``forward`` producers."""
    if direction == "backward":
        return SideFinding(rule_id, Severity.BREAKING, Severity.SAFE, message)
    if direction == "forward":
        return SideFinding(rule_id, Severity.SAFE, Severity.BREAKING, message)
    return SideFinding(rule_id, Severity.DANGEROUS, Severity.DANGEROUS, message)


def _json_schema_findings(old: Any, new: Any) -> Optional[List[SideFinding]]:
    """JSON Schema payloads, by the XPC-4.2 open/closed content-model comparator."""
    from .jsonschema_compatibility import compare_schemas

    if not isinstance(old, (Mapping, bool)) or not isinstance(new, (Mapping, bool)):
        return None
    return [
        _directional(finding.direction, finding.rule_id, f"payload: {finding.message}")
        for finding in compare_schemas(old, new)
    ]


def _avro_findings(old: Any, new: Any) -> Optional[List[SideFinding]]:
    """Avro payloads, by Avro schema resolution run both ways (XPC-4.1)."""
    from .avro_compatibility import AvroCompatibilityError, can_read, describe, parse_schema_text

    try:
        old_schema = parse_schema_text(old if isinstance(old, str) else json.dumps(old))
        new_schema = parse_schema_text(new if isinstance(new, str) else json.dumps(new))
        problems = [("backward", p) for p in can_read(new_schema, old_schema)]
        problems += [("forward", p) for p in can_read(old_schema, new_schema)]
    except AvroCompatibilityError:
        return None
    return [
        _directional(
            direction,
            f"avro-compatibility.{problem.type.lower().replace('_', '-')}",
            f"payload: {describe(direction, problem)}",
        )
        for direction, problem in problems
    ]


def _proto_model(text: str) -> Any:
    """Compile ``.proto`` text into a canonical model, or ``None`` when it cannot be compiled.

    Args:
        text: The payload's ``.proto`` source.

    Returns:
        The :class:`~app.canonical_model.CanonicalApi`, or ``None`` when ``buf`` is unavailable or
        the text does not compile.
    """
    from .grpc_import_source import GrpcImportSource
    from .import_source import ImportSourceError

    source = GrpcImportSource()
    try:
        return source.normalize(source.parse(text, source_label="payload.proto"))
    except (ImportSourceError, ValueError):
        return None


def _protobuf_findings(old: Any, new: Any) -> Optional[List[SideFinding]]:
    """Protobuf payloads, by the XPC-4.3 Protobuf classifier at its default category."""
    from .diff import diff
    from .proto_breaking import ProtobufBreakingChangeClassifier

    if not isinstance(old, str) or not isinstance(new, str):
        return None
    old_model, new_model = _proto_model(old), _proto_model(new)
    if old_model is None or new_model is None:
        return None
    result = ProtobufBreakingChangeClassifier().classify(diff(old_model, new_model), old_model, new_model)
    graded = [(c.severity, c.rule_id, f"{c.key}: {c.rationale}") for c in result.classifications]
    graded += [(f.severity, f.rule_id, f.rationale) for f in result.unattributed]
    return [
        SideFinding(rule_id, severity, severity, f"payload: {message}")
        for severity, rule_id, message in graded
        if severity is not Severity.SAFE
    ]
