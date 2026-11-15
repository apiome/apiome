"""Kafka facts of compiled channels: topic, parameters, support status — XPC-2.2 (#5736)."""

from __future__ import annotations

from app.canonical_model import CanonicalField, Channel, Constraints, TypeRef

from apiome_mock.kafka_channels import (
    SUPPORT_INVALID_TOPIC,
    SUPPORT_NOT_KAFKA,
    SUPPORT_SUPPORTED,
    SUPPORT_UNRESOLVED_PARAMETER,
    parameter_value,
    resolve_address,
)
from kafka_fixtures import compiled_kafka_spec, kafka_doc, route


def test_a_plain_channel_publishes_to_its_dotted_address():
    channel = route(compiled_kafka_spec(), "user/signedup")
    assert (channel.kafka.support, channel.kafka.topic) == (SUPPORT_SUPPORTED, "user.signedup")
    assert channel.kafka.publishable


def test_an_enum_parameter_fills_the_topic():
    channel = route(compiled_kafka_spec(), "user/{region}")
    assert channel.kafka.topic == "user.eu.updated"


def test_a_parameter_without_a_value_is_unsupported_and_names_it():
    channel = route(compiled_kafka_spec(), "orders/")
    assert channel.kafka.support == SUPPORT_UNRESOLVED_PARAMETER
    assert channel.kafka.unresolved == ("orderId",)
    assert channel.kafka.topic is None and not channel.kafka.publishable


def test_an_illegal_topic_is_unsupported():
    channel = route(compiled_kafka_spec(), "audit log!")
    assert channel.kafka.support == SUPPORT_INVALID_TOPIC


def test_a_declared_binding_topic_wins():
    doc = kafka_doc()
    doc["channels"]["userSignedUp"]["bindings"]["kafka"]["topic"] = "users.v1.signedup"
    assert route(compiled_kafka_spec(doc), "user/signedup").kafka.topic == "users.v1.signedup"


def test_a_non_kafka_document_is_served_over_ws_sse_only():
    doc = kafka_doc()
    doc["servers"]["prod"]["protocol"] = "ws"
    for channel in doc["channels"].values():
        channel.pop("bindings", None)
    doc["channels"]["userSignedUp"]["messages"]["UserSignedUp"].pop("bindings")
    channel = route(compiled_kafka_spec(doc), "user/signedup")
    assert channel.kafka.support == SUPPORT_NOT_KAFKA


def test_parameter_values_prefer_enum_then_examples_then_default():
    def field(**kwargs):
        return CanonicalField(key="p", name="p", type=TypeRef(name="string"), **kwargs)

    assert parameter_value(field(constraints=Constraints(enum=["a", "b"]), default="d")) == "a"
    assert parameter_value(field(extras={"examples": ["x"]}, default="d")) == "x"
    assert parameter_value(field(default=7)) == "7"
    assert parameter_value(field()) is None


def test_resolve_address_reports_undeclared_parameters():
    channel = Channel(key="k", address="a/{known}/{unknown}",
                      parameters=[CanonicalField(key="k", name="known", type=TypeRef(name="string"), default="v")])
    assert resolve_address(channel) == ("a/v/{unknown}", ("unknown",))
