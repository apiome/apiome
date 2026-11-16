"""Building Kafka records: payload order, encodings, validation, key and headers — XPC-2.2 (#5736)."""

from __future__ import annotations

import io
import json

import pytest
from app.canonical_model import CanonicalField, Message, MessageRole, Type, TypeKind, TypeRef
from fastavro import parse_schema, schemaless_reader

from apiome_mock.event_payloads import (
    ENCODING_AVRO,
    ENCODING_JSON,
    ENCODING_PROTOBUF,
    SOURCE_EXAMPLE,
    SOURCE_FIXTURE,
    SOURCE_REQUEST,
    SOURCE_SCENARIO,
    SOURCE_SYNTHESIS,
    EventRejectedError,
    build_event,
    channel_scenario_key,
    encoding_for,
)
from apiome_mock.scenarios import parse_scenarios
from kafka_fixtures import USER_UPDATED_AVRO, compiled_kafka_spec, kafka_doc, route


def _signedup(doc=None):
    compiled = compiled_kafka_spec(doc)
    channel = route(compiled, "user/signedup")
    return compiled, channel, channel.outbound_messages()[0]


def _scenario(body):
    settings = {
        "scenarios": {
            "vip": {
                "operations": {channel_scenario_key("user/signedup"): {"responses": [{"status": 200, "body": body}]}}
            }
        }
    }
    return parse_scenarios(settings)["vip"]


# ============================================================================
# Payload order: request > scenario > example > fixture > synthesis
# ============================================================================
def test_the_declared_example_is_used_first_when_nothing_overrides_it():
    compiled, channel, message = _signedup()
    event = build_event(compiled.api, channel.key, message)
    assert event.source == SOURCE_EXAMPLE
    assert json.loads(event.value) == {"userId": "u-1", "email": "ada@example.com"}
    assert event.encoding == ENCODING_JSON


def test_a_scenario_override_beats_the_example():
    compiled, channel, message = _signedup()
    body = {"userId": "vip-7", "email": "vip@example.com"}
    event = build_event(compiled.api, channel.key, message, scenario=_scenario(body))
    assert (event.source, json.loads(event.value)) == (SOURCE_SCENARIO, body)


def test_an_explicit_payload_beats_everything():
    compiled, channel, message = _signedup()
    body = {"userId": "req-1", "email": "req@example.com"}
    event = build_event(
        compiled.api, channel.key, message, scenario=_scenario({"userId": "x", "email": "x@x.io"}), payload=body
    )
    assert (event.source, json.loads(event.value)) == (SOURCE_REQUEST, body)


def test_a_wildcard_scenario_override_applies_to_every_channel():
    compiled, channel, message = _signedup()
    settings = {
        "scenarios": {
            "all": {
                "operations": {"*": {"responses": [{"status": 200, "body": {"userId": "w", "email": "w@example.com"}}]}}
            }
        }
    }
    event = build_event(compiled.api, channel.key, message, scenario=parse_scenarios(settings)["all"])
    assert event.source == SOURCE_SCENARIO


def test_a_fixture_is_used_when_there_is_no_example():
    doc = kafka_doc()
    del doc["channels"]["userSignedUp"]["messages"]["UserSignedUp"]["examples"]
    compiled, channel, message = _signedup(doc)
    fixture = {"userId": "fx-1", "email": "fx@example.com"}
    event = build_event(compiled.api, channel.key, message, fixtures={"user/signedup": fixture})
    assert (event.source, json.loads(event.value)) == (SOURCE_FIXTURE, fixture)
    # Keyed by the message name works too.
    event = build_event(compiled.api, channel.key, message, fixtures={"UserSignedUp": fixture})
    assert event.source == SOURCE_FIXTURE


def test_synthesis_is_last_and_seeded():
    doc = kafka_doc()
    del doc["channels"]["userSignedUp"]["messages"]["UserSignedUp"]["examples"]
    compiled, channel, message = _signedup(doc)
    first = build_event(compiled.api, channel.key, message, seed=7)
    again = build_event(compiled.api, channel.key, message, seed=7)
    assert first.source == SOURCE_SYNTHESIS
    assert first.value == again.value
    assert set(json.loads(first.value)) == {"userId", "email"}


# ============================================================================
# Never sent when invalid
# ============================================================================
@pytest.mark.parametrize(
    "payload",
    [{"userId": "u-1"}, {"userId": 5, "email": "a@b.io"}, {"userId": "u", "email": "a@b.io", "extra": 1}, "text"],
)
def test_a_payload_that_fails_the_schema_is_rejected(payload):
    compiled, channel, message = _signedup()
    with pytest.raises(EventRejectedError) as caught:
        build_event(compiled.api, channel.key, message, payload=payload)
    assert caught.value.reason == "invalid-payload"


def test_an_invalid_scenario_body_is_rejected_too():
    compiled, channel, message = _signedup()
    with pytest.raises(EventRejectedError):
        build_event(compiled.api, channel.key, message, scenario=_scenario({"userId": "only"}))


# ============================================================================
# Key and headers
# ============================================================================
def test_the_key_comes_from_the_kafka_key_binding_and_headers_from_the_example():
    compiled, channel, message = _signedup()
    event = build_event(compiled.api, channel.key, message)
    assert event.key == b"user-42"
    headers = dict(event.headers)
    assert headers["traceId"] == b"trace-1"
    assert headers["content-type"] == b"application/json"
    assert headers["x-apiome-encoding"] == b"json"


def test_without_a_key_binding_there_is_no_key():
    compiled = compiled_kafka_spec()
    channel = route(compiled, "user/{region}")
    assert build_event(compiled.api, channel.key, channel.outbound_messages()[0]).key is None


def test_headers_are_synthesized_without_an_example():
    doc = kafka_doc()
    del doc["channels"]["userSignedUp"]["messages"]["UserSignedUp"]["examples"]
    compiled, channel, message = _signedup(doc)
    headers = dict(build_event(compiled.api, channel.key, message, seed=1).headers)
    assert "traceId" in headers and headers["traceId"]


# ============================================================================
# Avro
# ============================================================================
def test_an_avro_message_decodes_with_the_published_schema():
    compiled = compiled_kafka_spec()
    channel = route(compiled, "user/{region}")
    message = channel.outbound_messages()[0]
    assert encoding_for(message) == ENCODING_AVRO
    event = build_event(compiled.api, channel.key, message, seed=3)
    assert event.encoding == ENCODING_AVRO
    decoded = schemaless_reader(io.BytesIO(event.value), parse_schema(USER_UPDATED_AVRO))
    assert set(decoded) == {"userId", "plan", "seats", "nickname"}
    assert decoded["plan"] in {"FREE", "PRO"}
    assert dict(event.headers)["x-apiome-encoding"] == b"avro"


def test_an_avro_payload_that_does_not_match_is_rejected():
    compiled = compiled_kafka_spec()
    channel = route(compiled, "user/{region}")
    with pytest.raises(EventRejectedError) as caught:
        build_event(
            compiled.api,
            channel.key,
            channel.outbound_messages()[0],
            payload={"userId": "u", "plan": "GOLD", "seats": 1, "nickname": None},
        )
    assert caught.value.reason == "invalid-payload"


def test_an_avro_message_with_a_json_schema_payload_is_unsupported():
    doc = kafka_doc()
    doc["channels"]["userUpdated"]["messages"]["UserUpdated"]["payload"] = {"type": "object"}
    compiled = compiled_kafka_spec(doc)
    channel = route(compiled, "user/{region}")
    with pytest.raises(EventRejectedError) as caught:
        build_event(compiled.api, channel.key, channel.outbound_messages()[0])
    assert caught.value.reason == "unsupported-schema"


# ============================================================================
# Protobuf
# ============================================================================
def _protobuf_case():
    compiled = compiled_kafka_spec()
    user = Type(
        key="User",
        name="User",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(key="User.id", name="id", type=TypeRef(name="string", nullable=False), field_number=1),
            CanonicalField(key="User.age", name="age", type=TypeRef(name="int32", nullable=False), field_number=2),
        ],
    )
    api = compiled.api.model_copy(update={"types": [*compiled.api.types, user]})
    message = Message(
        key="onUser#event.User",
        role=MessageRole.EVENT,
        name="User",
        payload=TypeRef(name="User"),
        extras={"schemaFormat": "application/vnd.google.protobuf;version=3"},
    )
    return api, message


def test_a_protobuf_message_is_serialized_from_the_modelled_type():
    from apiome_mock.event_payloads import _protobuf_descriptor

    api, message = _protobuf_case()
    assert encoding_for(message) == ENCODING_PROTOBUF
    event = build_event(api, "user/signedup", message, payload={"id": "u-9", "age": 41})
    assert event.encoding == ENCODING_PROTOBUF
    decoded = _protobuf_descriptor(api, message).FromString(event.value)
    assert (decoded.id, decoded.age) == ("u-9", 41)


def test_a_protobuf_payload_with_unknown_fields_is_rejected():
    api, message = _protobuf_case()
    with pytest.raises(EventRejectedError) as caught:
        build_event(api, "user/signedup", message, payload={"id": "u", "nope": 1})
    assert caught.value.reason == "invalid-payload"


def test_a_raw_proto_payload_is_unsupported():
    compiled = compiled_kafka_spec()
    message = Message(
        key="m", role=MessageRole.EVENT, name="m", extras={"schemaFormat": "application/vnd.google.protobuf;version=3"}
    )
    with pytest.raises(EventRejectedError) as caught:
        build_event(compiled.api, "user/signedup", message)
    assert caught.value.reason == "unsupported-schema"
