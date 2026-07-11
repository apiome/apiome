"""Tests for CloudEvents catalog import/export adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, MessageRole, OperationKind, TypeKind
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError
from app.cloudevents_import_source import CloudEventsImportSource
from app.cloudevents_normalizer import CloudEventsNormalizer
from app.cloudevents_parser import is_cloudevents, parse_cloudevents

_ORDER_CREATED = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/cloudevents/01-order-created.json"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> CloudEventsImportSource:
    return CloudEventsImportSource()


def test_is_cloudevents_recognizes_order_created():
    assert is_cloudevents(_ORDER_CREATED) is True
    assert is_cloudevents('{"openapi":"3.0.0"}') is False


def test_parse_collects_envelope_and_data():
    doc = parse_cloudevents(_ORDER_CREATED)
    assert len(doc.events) == 1
    event = doc.events[0]
    assert event.specversion == "1.0"
    assert event.type == "com.example.order.created"
    assert event.source == "/orders/service"
    assert event.subject == "order/9f2c"
    assert isinstance(event.data, dict)
    assert event.data["orderId"] == "9f2c-aa01"


def test_normalizer_maps_event_paradigm():
    doc = parse_cloudevents(_ORDER_CREATED)
    api = CloudEventsNormalizer().normalize(doc)
    assert api.format == "cloudevents"
    assert api.paradigm is ApiParadigm.EVENT
    assert api.protocol == "cloudevents"
    assert api.title == "com.example.order.created"
    assert len(api.channels) == 1
    assert api.channels[0].address == "com.example.order.created"
    order_created = next(t for t in api.types if t.name == "OrderCreated")
    assert order_created.kind is TypeKind.RECORD
    assert {field.name for field in order_created.fields} >= {
        "orderId",
        "customerId",
        "total",
        "currency",
        "items",
        "placedAt",
    }
    service = api.services[0]
    operation = service.operations[0]
    assert operation.kind is OperationKind.PUBLISH
    assert operation.channel_ref == api.channels[0].key
    assert operation.messages[0].role is MessageRole.EVENT


def test_adapter_detect_parse_normalize(adapter: CloudEventsImportSource):
    detected = adapter.detect(
        DetectionInput(
            text=_ORDER_CREATED,
            filename="01-order-created.json",
        )
    )
    assert detected.matched
    assert detected.format == "cloudevents"
    doc = adapter.parse(_ORDER_CREATED, source_label="01-order-created.json")
    api = adapter.normalize(doc)
    assert len(api.services) == 1
    assert len(api.services[0].operations) == 1
    assert len(api.types) >= 1


def test_adapter_invalid_source_raises(adapter: CloudEventsImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse('{"title":"nope"}')


def test_emitter_round_trips_core_constructs():
    doc = parse_cloudevents(_ORDER_CREATED)
    api = CloudEventsNormalizer().normalize(doc)
    emitter = get_emitter("cloudevents")
    assert emitter is not None
    result = emitter().emit(api)
    text = result.files[0].content
    assert '"specversion": "1.0"' in text
    assert "com.example.order.created" in text
    assert "/orders/service" in text
    assert "9f2c-aa01" in text
    assert "order/9f2c" in text


def test_catalog_conversion_resolves_cloudevents_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("cloudevents", _ORDER_CREATED).key == "cloudevents"
