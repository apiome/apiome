"""Build one Kafka record for an event channel: payload, key, headers, encoding — XPC-2.2 (#5736).

**Payload, first source that has one wins** — the same order as the REST and GraphQL mocks:

1. an explicit payload (the on-demand ``publish`` request body);
2. the active scenario's override for the channel (key ``PUBLISH /<channel key>``, or ``*``);
3. the message's first declared example (AsyncAPI ``examples[].payload``);
4. a fixture-pack ``data`` value keyed by the channel key or the message name;
5. a seeded synthesis from the message schema.

**Encoding** follows the message's ``schemaFormat``:

* Avro (``application/vnd.apache.avro…``): the payload schema *is* an Avro schema; it is checked with
  the FMT Avro emitter's validator (:func:`app.avro_emitter.validate_avro_schema`), the value is
  checked against it, and it is written as schemaless Avro binary (``fastavro``). A consumer
  decodes it with the same published schema.
* Protobuf (``application/vnd.google.protobuf…``): the payload must reference a modelled record
  type; its descriptor comes from the FMT descriptor builder
  (:func:`apiome_mock.proto_descriptor_builder.build_descriptor_set`) and the value is serialized
  as protobuf binary.
* Anything else: UTF-8 JSON, checked against the message's JSON Schema.

**Never sent when invalid.** A payload that does not satisfy its schema — whichever source it came
from — raises :class:`EventRejectedError` and is not handed to a broker (the PMR-2.3 callback rule).

**Key and headers.** The partition key comes from the message's Kafka binding ``key`` schema (its
``const`` / first ``enum`` / ``examples`` / ``example`` / ``default``, else a synthesized value); with
no key binding the record has no key and the broker picks the partition. Headers are the first
declared example's ``headers``, else synthesized from the message's header fields, plus
``content-type`` and ``x-apiome-encoding``.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import Any, Mapping

from app.canonical_model import CanonicalApi, Message, TypeKind

from apiome_mock.message_resolver import _type_ref_schema, message_schema
from apiome_mock.scenarios import Scenario
from apiome_mock.schema_synthesizer import generate_example, validate_value

__all__ = [
    "ENCODING_AVRO",
    "ENCODING_JSON",
    "ENCODING_PROTOBUF",
    "SOURCE_EXAMPLE",
    "SOURCE_FIXTURE",
    "SOURCE_REQUEST",
    "SOURCE_SCENARIO",
    "SOURCE_SYNTHESIS",
    "EncodedEvent",
    "EventRejectedError",
    "NO_PAYLOAD",
    "build_event",
    "channel_scenario_key",
    "encoding_for",
]

ENCODING_JSON = "json"
ENCODING_AVRO = "avro"
ENCODING_PROTOBUF = "protobuf"

SOURCE_REQUEST = "request"
SOURCE_SCENARIO = "scenario"
SOURCE_EXAMPLE = "example"
SOURCE_FIXTURE = "fixture"
SOURCE_SYNTHESIS = "synthesis"

_CONTENT_TYPES = {
    ENCODING_JSON: "application/json",
    ENCODING_AVRO: "application/vnd.apache.avro+binary",
    ENCODING_PROTOBUF: "application/x-protobuf",
}

#: "No explicit payload": the default of :func:`build_event`'s ``payload``. Callers that pass a
#: payload through (the publisher, the publish route) default to this same object.
NO_PAYLOAD: Any = object()
_MISSING = NO_PAYLOAD


class EventRejectedError(ValueError):
    """A record was not built, so nothing is sent.

    Attributes:
        reason: ``invalid-payload`` (fails its schema), ``unsupported-schema`` (the schema itself
            can't be used for this encoding) or ``invalid-key``.
        detail: What failed, naming fields, never echoing the whole payload.
    """

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


@dataclass(frozen=True)
class EncodedEvent:
    """One record ready for a broker.

    Attributes:
        value: The encoded payload.
        key: The encoded partition key, or ``None``.
        headers: Record headers.
        encoding: ``json``, ``avro`` or ``protobuf``.
        source: Where the payload came from (``SOURCE_*``).
        message_key: The canonical message it was built for.
    """

    value: bytes
    key: bytes | None
    headers: tuple[tuple[str, bytes], ...]
    encoding: str
    source: str
    message_key: str


def channel_scenario_key(channel_key: str) -> str:
    """The scenario operation key that addresses one channel: ``PUBLISH /<channel key>``."""
    return f"PUBLISH /{channel_key.strip('/')}"


def encoding_for(message: Message) -> str:
    """The encoding a message's ``schemaFormat`` asks for (``json`` when it names none)."""
    schema_format = str((message.extras or {}).get("schemaFormat") or "").lower()
    if "avro" in schema_format:
        return ENCODING_AVRO
    if "protobuf" in schema_format or "proto" in schema_format.split(";")[0].split("/")[-1]:
        return ENCODING_PROTOBUF
    return ENCODING_JSON


# -------------------------------------------------------------------------------------------
# Payload sources
# -------------------------------------------------------------------------------------------


def _first_example(message: Message) -> Mapping[str, Any] | None:
    """The message's first declared AsyncAPI example object, if any."""
    examples = (message.extras or {}).get("examples")
    if isinstance(examples, list):
        for example in examples:
            if isinstance(example, Mapping):
                return example
    return None


def _scenario_body(scenario: Scenario | None, channel_key: str) -> Any:
    """The scenario override body for a channel, or ``_MISSING``."""
    if scenario is None:
        return _MISSING
    override = scenario.override_for(channel_scenario_key(channel_key))
    if override is None:
        return _MISSING
    candidates = list(override.responses)
    for rule in override.rules:
        candidates.extend(rule.responses)
    for response in candidates:
        if response.has_body:
            return response.body
    return _MISSING


def _fixture_body(fixtures: Mapping[str, Any], channel_key: str, message: Message) -> Any:
    """A fixture-pack ``data`` value for the channel or the message, or ``_MISSING``."""
    for key in (channel_key, message.name, message.key):
        if key and key in fixtures:
            return fixtures[key]
    return _MISSING


# -------------------------------------------------------------------------------------------
# Schemas per encoding
# -------------------------------------------------------------------------------------------


_AVRO_PRIMITIVES = {
    "null": {"type": "null"},
    "boolean": {"type": "boolean"},
    "int": {"type": "integer", "minimum": -(2**31), "maximum": 2**31 - 1},
    "long": {"type": "integer"},
    "float": {"type": "number"},
    "double": {"type": "number"},
    "string": {"type": "string"},
}


def avro_to_json_schema(avro: Any, named: dict[str, Any] | None = None) -> dict[str, Any]:
    """Translate an Avro schema into the JSON Schema the synthesizer understands.

    Covers records, enums, arrays, maps, fixed/bytes (as strings), unions (the first non-null
    branch, which is always a valid value of the union) and named references.

    Args:
        avro: The Avro schema (dict, list or primitive name).
        named: Named types seen so far, for references.

    Returns:
        A JSON Schema fragment.
    """
    named = {} if named is None else named
    if isinstance(avro, str):
        if avro in _AVRO_PRIMITIVES:
            return dict(_AVRO_PRIMITIVES[avro])
        return named.get(avro) or named.get(avro.rsplit(".", 1)[-1]) or {"type": "string"}
    if isinstance(avro, list):
        # A union: synthesize its first non-null branch (always a valid value of the union).
        branches = [branch for branch in avro if branch != "null"] or ["null"]
        return avro_to_json_schema(branches[0], named)
    if not isinstance(avro, dict):
        return {}
    kind = avro.get("type")
    if kind == "record":
        properties: dict[str, Any] = {}
        result: dict[str, Any] = {"type": "object", "properties": properties}
        for name_key in (avro.get("name"), avro.get("namespace", "") + "." + str(avro.get("name"))):
            if name_key:
                named[str(name_key)] = result
        required = []
        for field in avro.get("fields") or []:
            if isinstance(field, dict) and field.get("name"):
                properties[field["name"]] = avro_to_json_schema(field.get("type"), named)
                required.append(field["name"])
        result["required"] = required
        result["additionalProperties"] = False
        return result
    if kind == "enum":
        symbols = list(avro.get("symbols") or [])
        result = {"type": "string", "enum": symbols or ["UNKNOWN"]}
        if avro.get("name"):
            named[str(avro["name"])] = result
        return result
    if kind == "array":
        return {"type": "array", "items": avro_to_json_schema(avro.get("items"), named), "minItems": 1}
    if kind == "map":
        return {"type": "object", "additionalProperties": avro_to_json_schema(avro.get("values"), named)}
    if kind in {"fixed", "bytes"}:
        return {"type": "string"}
    return avro_to_json_schema(kind, named)


def _is_avro_schema(schema: Any) -> bool:
    """Whether a payload schema looks like Avro rather than JSON Schema."""
    if isinstance(schema, list):
        return True
    return isinstance(schema, dict) and (
        schema.get("type") in {"record", "enum", "fixed", "map"} or "fields" in schema
    )


def _protobuf_descriptor(api: CanonicalApi, message: Message) -> Any:
    """The protobuf message class for a message's payload type, built by the FMT descriptor builder.

    Raises:
        EventRejectedError: ``unsupported-schema`` when the payload is not a modelled record type
            (an AsyncAPI ``.proto`` text payload is not compiled by the mock).
    """
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

    from apiome_mock.proto_descriptor_builder import (
        _message_name,
        _package_name,
        _resolve_type_key,
        build_descriptor_set,
    )

    type_key = _resolve_type_key(api, message.payload) if message.payload is not None else None
    type_ = api.type_by_key(type_key) if type_key else None
    if type_ is None or type_.kind is not TypeKind.RECORD:
        raise EventRejectedError(
            "unsupported-schema",
            "a Protobuf message must reference a modelled record type; a raw .proto payload is not "
            "compiled by the mock",
        )
    try:
        descriptor_set = descriptor_pb2.FileDescriptorSet.FromString(build_descriptor_set(api))
        pool = descriptor_pool.DescriptorPool()
        for file_proto in descriptor_set.file:
            pool.Add(file_proto)
        full_name = f"{_package_name(api)}.{_message_name(type_.key)}"
        return message_factory.GetMessageClass(pool.FindMessageTypeByName(full_name))
    except (TypeError, KeyError) as exc:
        raise EventRejectedError("unsupported-schema", "the payload type does not build a Protobuf descriptor") from exc


# -------------------------------------------------------------------------------------------
# Encoding
# -------------------------------------------------------------------------------------------


def _encode_avro(value: Any, avro_schema: Any) -> bytes:
    """Validate ``value`` against an Avro schema and write it as schemaless Avro binary."""
    from app.avro_emitter import validate_avro_schema
    from fastavro import schemaless_writer
    from fastavro.validation import validate as validate_avro

    try:
        parsed = validate_avro_schema(avro_schema)
    except ValueError as exc:
        raise EventRejectedError("unsupported-schema", "the message's Avro schema is not valid") from exc
    if not validate_avro(value, parsed, raise_errors=False):
        raise EventRejectedError("invalid-payload", "the payload does not match the message's Avro schema")
    buffer = io.BytesIO()
    schemaless_writer(buffer, parsed, value)
    return buffer.getvalue()


def _encode_protobuf(value: Any, message_class: Any) -> bytes:
    """Serialize ``value`` (a JSON object) as the protobuf message, refusing unknown fields."""
    from google.protobuf import json_format

    if not isinstance(value, Mapping):
        raise EventRejectedError("invalid-payload", "a Protobuf payload must be an object")
    try:
        instance = json_format.ParseDict(dict(value), message_class())
    except json_format.ParseError as exc:
        raise EventRejectedError("invalid-payload", "the payload does not match the Protobuf message") from exc
    return instance.SerializeToString()


def _example_from_schema(schema: Any) -> Any:
    """A declared value on a (key) schema: ``const``, first ``enum``, ``examples``, ``example``, ``default``."""
    if not isinstance(schema, Mapping):
        return _MISSING
    if "const" in schema:
        return schema["const"]
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        return schema["enum"][0]
    if isinstance(schema.get("examples"), list) and schema["examples"]:
        return schema["examples"][0]
    for name in ("example", "default"):
        if name in schema:
            return schema[name]
    return _MISSING


def _to_bytes(value: Any) -> bytes:
    """Encode a key or header value: strings as UTF-8, everything else as compact JSON."""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _kafka_key(message: Message, *, seed: int) -> bytes | None:
    """The partition key from the message's Kafka binding ``key`` schema, or ``None``."""
    bindings = (message.extras or {}).get("bindings")
    kafka = None
    if isinstance(bindings, Mapping):
        kafka = next((v for k, v in bindings.items() if str(k).lower() == "kafka"), None)
    key_schema = kafka.get("key") if isinstance(kafka, Mapping) else None
    if not isinstance(key_schema, Mapping):
        return None
    value = _example_from_schema(key_schema)
    if value is _MISSING:
        value = generate_example(dict(key_schema), seed=seed, field=f"{message.key}#key")
    error = validate_value(value, dict(key_schema))
    if error is not None:
        raise EventRejectedError("invalid-key", "the partition key does not match the Kafka key schema")
    return _to_bytes(value)


def _headers(api: CanonicalApi, message: Message, *, encoding: str, seed: int) -> tuple[tuple[str, bytes], ...]:
    """Record headers: example headers (else synthesized header fields), plus the content type."""
    values: dict[str, Any] = {}
    example = _first_example(message)
    if example is not None and isinstance(example.get("headers"), Mapping):
        values.update(example["headers"])
    else:
        for field in message.headers:
            if field.default is not None:
                values[field.name] = field.default
            else:
                schema = _type_ref_schema(api, field.type)
                values[field.name] = generate_example(schema, seed=seed, field=field.key)
    headers = [(str(name), _to_bytes(value)) for name, value in values.items()]
    headers.append(("content-type", _CONTENT_TYPES[encoding].encode()))
    headers.append(("x-apiome-encoding", encoding.encode()))
    return tuple(headers)


def build_event(
    api: CanonicalApi,
    channel_key: str,
    message: Message,
    *,
    scenario: Scenario | None = None,
    fixtures: Mapping[str, Any] | None = None,
    payload: Any = _MISSING,
    seed: int = 0,
) -> EncodedEvent:
    """Resolve, validate and encode one record for ``message`` on ``channel_key``.

    Args:
        api: The version's canonical model.
        channel_key: The channel's key.
        message: The outbound event message.
        scenario: The active (or ``X-Mock-Scenario``-selected) scenario, if any.
        fixtures: Merged fixture-pack data.
        payload: An explicit payload (on-demand publish body); omit to resolve one.
        seed: Synthesis seed.

    Returns:
        The encoded record.

    Raises:
        EventRejectedError: The payload, key or schema is unusable; nothing must be sent.
    """
    encoding = encoding_for(message)
    raw_schema = message.payload_schema if isinstance(message.payload_schema, (dict, list)) else None
    avro_schema = raw_schema if encoding == ENCODING_AVRO else None
    if encoding == ENCODING_AVRO and not _is_avro_schema(avro_schema):
        raise EventRejectedError("unsupported-schema", "an Avro message needs an inline Avro payload schema")
    json_schema = avro_to_json_schema(avro_schema) if avro_schema is not None else message_schema(api, message)
    protobuf_class = _protobuf_descriptor(api, message) if encoding == ENCODING_PROTOBUF else None

    source = SOURCE_REQUEST
    value = payload
    if value is _MISSING:
        source, value = SOURCE_SCENARIO, _scenario_body(scenario, channel_key)
    if value is _MISSING:
        example = _first_example(message)
        source, value = SOURCE_EXAMPLE, (example.get("payload", _MISSING) if example else _MISSING)
    if value is _MISSING:
        source, value = SOURCE_FIXTURE, _fixture_body(fixtures or {}, channel_key, message)
    if value is _MISSING:
        source, value = SOURCE_SYNTHESIS, generate_example(json_schema, seed=seed, field=message.key)

    if encoding == ENCODING_AVRO:
        encoded = _encode_avro(value, avro_schema)
    elif encoding == ENCODING_PROTOBUF:
        encoded = _encode_protobuf(value, protobuf_class)
    else:
        error = validate_value(value, json_schema)
        if error is not None:
            raise EventRejectedError("invalid-payload", error)
        encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    return EncodedEvent(
        value=encoded,
        key=_kafka_key(message, seed=seed),
        headers=_headers(api, message, encoding=encoding, seed=seed),
        encoding=encoding,
        source=source,
        message_key=message.key,
    )
