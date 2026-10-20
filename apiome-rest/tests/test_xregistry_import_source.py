"""CNCF xRegistry import — MFI-19.2 (#3980).

Covers the ``xregistry`` adapter end to end over the ``apiome-ui/examples/xregistry`` fixtures:
detection, parsing (current and earlier-draft names, every intake-taxonomy failure), the
normalization contract (schemas → types, messages → channels / operations, endpoints → services),
fingerprint stability and the diff between two releases, and lint.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict

import pytest

from app.canonical_model import ApiParadigm, MessageRole, OperationKind, TypeKind
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    detect_import_source,
    get_import_source,
    load_builtin_import_sources,
)
from app.xregistry_import_source import XRegistryImportSource
from app.xregistry_parser import (
    XRegistryParseError,
    group_refs,
    is_xregistry,
    is_xregistry_document,
    parse_xregistry,
)

load_builtin_import_sources()

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui/examples/xregistry"
ADAPTER = XRegistryImportSource()


def _text(name: str) -> str:
    """A fixture's text."""
    return (_EXAMPLES / name).read_text(encoding="utf-8")


def _model(name: str):
    """A fixture parsed and normalized."""
    return ADAPTER.normalize(ADAPTER.parse(_text(name), source_label=name))


def _ops(model) -> Dict[str, Any]:
    """Operations by key."""
    return {op.key: op for op in model.operations()}


# ---------------------------------------------------------------------------
# Registration and detection
# ---------------------------------------------------------------------------


def test_the_adapter_is_registered_as_an_event_source() -> None:
    adapter = get_import_source("xregistry")
    assert isinstance(adapter, XRegistryImportSource)
    descriptor = adapter.descriptor()
    assert descriptor.paradigm == ApiParadigm.EVENT.value or descriptor.paradigm == ApiParadigm.EVENT
    assert descriptor.label == "CNCF xRegistry"
    assert "cloudevents-registry" in descriptor.formats


@pytest.mark.parametrize(
    "name",
    [
        "01-minimal-schema-registry.json",
        "02-typical-order-events.json",
        "03-composition-shared-groups.json",
        "04-stress-edge-cases.json",
        "05-real-world-contoso-erp.json",
        "06-typical-order-events-v2.json",
    ],
)
def test_every_valid_fixture_detects_as_xregistry(name: str) -> None:
    text = _text(name)
    adapter, result = detect_import_source(DetectionInput(text=text, document=json.loads(text), filename=name))
    assert adapter is not None and adapter.key == "xregistry", name
    assert result.confidence >= 0.9


def test_detection_rejects_other_formats_and_single_cloudevents() -> None:
    assert not is_xregistry_document({"specversion": "1.0", "type": "com.x", "source": "/x", "id": "1"})
    assert not is_xregistry_document({"asyncapi": "3.0.0", "endpoints": {}})
    assert not is_xregistry_document({"openapi": "3.1.0", "schemagroups": {}})
    assert not is_xregistry_document([{"schemagroups": {}}])
    assert not is_xregistry("")
    assert not is_xregistry("not json")
    # The xRegistry document schema marker does not stop detection.
    assert is_xregistry_document({"$schema": "https://xregistry.io/schemas/registry", "endpoints": {}})
    result = ADAPTER.detect(DetectionInput(text="{", filename="orders.xreg.json"))
    assert result.matched and result.confidence < 0.9


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, code",
    [
        ("negative/01-syntactic-trailing-comma.json", "INPUT_MALFORMED"),
        ("negative/02-semantic-empty-registry.json", "INPUT_SEMANTIC_INVALID"),
        ("negative/03-truncated-mid-message.json", "INPUT_TRUNCATED"),
        ("negative/04-wrong-format-asyncapi.json", "FORMAT_MISMATCH"),
    ],
)
def test_negative_fixtures_fail_with_their_taxonomy_code(name: str, code: str) -> None:
    with pytest.raises(ImportSourceError) as excinfo:
        ADAPTER.parse(_text(name), source_label=name)
    assert excinfo.value.code == code


def test_utf16_text_is_an_encoding_failure() -> None:
    raw = (_EXAMPLES / "negative/05-encoding-utf16.json").read_bytes().decode("latin-1")
    with pytest.raises(ImportSourceError) as excinfo:
        ADAPTER.parse(raw)
    assert excinfo.value.code == "INPUT_ENCODING_INVALID"


@pytest.mark.parametrize(
    "content, code",
    [
        ("", "INPUT_EMPTY"),
        ("[]", "FORMAT_MISMATCH"),
        ('{"name": "x"}', "FORMAT_MISMATCH"),
        ('{"schemagroups": []}', "INPUT_SEMANTIC_INVALID"),
        ('{"endpoints": {"e": "not-an-object"}}', "INPUT_SEMANTIC_INVALID"),
        ('{"messagegroups": {"g": {"messages": ["m"]}}}', "INPUT_SEMANTIC_INVALID"),
        ("info: yaml\n", "FORMAT_MISMATCH"),
    ],
)
def test_parse_failures_carry_a_taxonomy_code(content: str, code: str) -> None:
    with pytest.raises(XRegistryParseError) as excinfo:
        parse_xregistry(content)
    assert excinfo.value.code == code


def test_a_schema_resolves_to_its_default_version() -> None:
    document = parse_xregistry(_text("06-typical-order-events-v2.json"))
    created = next(s for s in document.schemas if s.schema_id == "OrderCreated")
    assert created.version_id == "2"
    assert "currency" in created.document["properties"]


def test_a_schema_without_default_takes_the_last_version() -> None:
    raw = {
        "schemagroups": {
            "g": {"schemas": {"s": {"format": "JsonSchema", "versions": {
                "1": {"versionid": "1", "schema": {"type": "string"}},
                "2": {"versionid": "2", "schema": {"type": "integer"}},
            }}}}
        }
    }
    (schema,) = parse_xregistry(json.dumps(raw)).schemas
    assert schema.version_id == "2" and schema.document == {"type": "integer"}


def test_earlier_draft_names_read_like_current_ones() -> None:
    document = parse_xregistry(_text("04-stress-edge-cases.json"))
    groups = {g.group_id: g for g in document.message_groups}
    issued = next(m for m in groups["billing.events"].messages if m.message_id == "invoice.issued")
    assert issued.event_type == "com.example.billing.invoice.issued"
    assert issued.envelope == "CloudEvents/1.0"  # inherited from the group's `format`
    assert issued.protocol == "HTTP"
    assert issued.data_schema_format == "XSD/1.1"
    webhook = next(e for e in document.endpoints if e.endpoint_id == "webhook")
    assert webhook.usage == ("consumer",)
    assert webhook.uris == ("https://hooks.example.com/billing",)  # de-duplicated
    assert webhook.message_group_refs == ("billing.events", "missing.group")
    assert [m.message_id for m in webhook.messages] == ["webhook.ping"]


def test_base64_and_string_schemas_are_decoded() -> None:
    document = parse_xregistry(_text("04-stress-edge-cases.json"))
    by_xid = {s.xid: s for s in document.schemas}
    assert by_xid["/schemagroups/billing/schemas/Invoice"].document.startswith("<?xml")
    assert by_xid["/schemagroups/billing/schemas/Amount"].document == {"type": "number", "minimum": 0}
    assert by_xid["/schemagroups/billing/schemas/Remote"].document is None
    assert by_xid["/schemagroups/billing/schemas/Remote"].schema_uri == "https://schemas.example.com/remote.json"
    assert by_xid["/schemagroups/shipping/schemas/Amount"].deprecated


def test_invalid_base64_leaves_no_document() -> None:
    raw = {"schemagroups": {"g": {"schemas": {"s": {"format": "Avro", "schemabase64": "%%%"}}}}}
    (schema,) = parse_xregistry(json.dumps(raw)).schemas
    assert schema.document is None


def test_group_refs_accept_xids_urls_and_bare_ids() -> None:
    assert group_refs({"messagegroups": ["/messagegroups/a", "https://r/x/messagegroups/b/", "c", "a", ""]}) == [
        "a", "b", "c",
    ]
    assert group_refs({"definitiongroups": "/definitiongroups/old"}) == ["old"]
    assert group_refs({"messagegroups": {"not": "a list"}}) == []


# ---------------------------------------------------------------------------
# Normalization contract
# ---------------------------------------------------------------------------


def test_a_schema_only_registry_is_types_without_services() -> None:
    model = _model("01-minimal-schema-registry.json")
    assert model.paradigm == ApiParadigm.EVENT and model.format == "xregistry"
    assert model.title == "minimal" and model.identity.id == "minimal"
    assert [t.key for t in model.types] == ["Ping"]
    assert model.types[0].kind == TypeKind.RECORD
    assert model.services == [] and model.channels == []
    assert model.extras["xregistry_specversion"] == "1.0-rc1"


def test_schemas_messages_and_endpoints_normalize_into_the_model() -> None:
    model = _model("02-typical-order-events.json")
    assert model.title == "Order events" and model.protocol == "mqtt"
    assert {t.key for t in model.types} >= {"OrderCreated", "OrderShipped"}
    assert [s.key for s in model.services] == ["orders.mqtt"]
    assert [s.url for s in model.servers] == ["mqtts://broker.example.com:8883"]

    channel = next(c for c in model.channels if c.key == "com.example.orders.created")
    # The message names no protocol (the endpoint does), so the channel is a CloudEvents channel.
    assert channel.protocol == "cloudevents" and channel.extras["cloudevents_source"] == "/orders"

    op = _ops(model)["orders.mqtt.com.example.orders.com.example.orders.created"]
    assert op.kind == OperationKind.PUBLISH and op.channel_ref == "com.example.orders.created"
    assert op.extras["cloudevents_type"] == "com.example.orders.created"
    (message,) = op.messages
    assert message.role == MessageRole.EVENT
    assert message.payload is not None and message.payload.name == "OrderCreated"
    assert message.content_types == ["application/json"]
    headers = {h.name: h for h in message.headers}
    assert headers["type"].default == "com.example.orders.created"
    assert headers["subject"].type.nullable is False  # required
    assert headers["source"].type.nullable is True

    service = model.services[0]
    assert service.extras["xregistry_usage"] == ["producer"]
    assert service.extras["xregistry_protocol_options"] == {"options": {"topic": "orders/{subject}", "qos": 1}}


def test_shared_groups_are_operations_of_each_endpoint_and_consumers_subscribe() -> None:
    model = _model("03-composition-shared-groups.json")
    ops = _ops(model)
    breach = "fleet.geofence.breach"
    assert ops[f"vehicles.amqp.alerts.{breach}"].kind == OperationKind.PUBLISH
    assert ops[f"dispatch.nats.alerts.{breach}"].kind == OperationKind.SUBSCRIBE
    # Both endpoints share one channel per CloudEvents type.
    assert len({op.channel_ref for op in ops.values()}) == len(model.channels) == 3
    # Groups carried by an endpoint are not services of their own.
    assert {s.key for s in model.services} == {"vehicles.amqp", "dispatch.nats"}
    assert model.protocol is None  # AMQP and NATS


def test_avro_protobuf_and_json_schema_payloads_resolve_to_types() -> None:
    model = _model("03-composition-shared-groups.json")
    ops = _ops(model)
    payload = lambda key: ops[key].messages[0].payload  # noqa: E731
    assert payload("vehicles.amqp.telemetry.fleet.position").name == "com.example.fleet.Position"
    assert payload("vehicles.amqp.telemetry.fleet.diagnostics").name == "fleet.diag.Diagnostics"
    assert payload("vehicles.amqp.alerts.fleet.geofence.breach").name == "GeofenceBreach"
    types = {t.key: t for t in model.types}
    assert types["Zone"].kind == TypeKind.RECORD  # a JSON Schema `definitions` member
    assert {f.name for f in types["com.example.fleet.Position"].fields} == {"vehicleId", "lat", "lon", "speedKph"}
    headers = {h.name: h for h in ops["vehicles.amqp.alerts.fleet.geofence.breach"].messages[0].headers}
    assert headers["severity"].type.name == "integer" and headers["severity"].type.nullable is False


def test_stress_edge_cases_degrade_without_failing() -> None:
    model = _model("04-stress-edge-cases.json")
    types = {t.key: t for t in model.types}
    # Duplicate schema ids across groups are group-qualified.
    assert {"billing.Amount", "shipping.Amount"} <= set(types)
    assert types["shipping.Amount"].deprecated
    # An unknown format and a document-less schema are opaque, with the reason recorded.
    assert types["Ledger"].kind == TypeKind.SCALAR
    assert types["Ledger"].extras["xregistry_opaque"] == "unsupported-format"
    assert types["Remote"].extras["xregistry_opaque"] == "no-document"
    assert types["Remote"].extras["xregistry_schema_uri"] == "https://schemas.example.com/remote.json"
    # XSD delegated to the XSD adapter (its key is namespace-qualified).
    invoice = "http://example.com/billing.Invoice"
    assert types[invoice].kind == TypeKind.RECORD

    webhook = next(s for s in model.services if s.key == "webhook")
    assert webhook.extras["xregistry_unresolved_groups"] == ["missing.group"]
    ops = _ops(model)
    assert ops["webhook.billing.events.invoice.issued"].kind == OperationKind.SUBSCRIBE
    assert ops["webhook.billing.events.invoice.issued"].messages[0].payload.name == invoice
    voided = ops["webhook.billing.events.invoice.voided"]
    assert voided.deprecated and voided.messages[0].payload_schema == {
        "type": "object", "properties": {"reason": {"type": "string"}},
    }
    # A reference outside the document leaves the payload empty but keeps the reference.
    dup = ops["webhook.billing.events.invoice.issued.dup"].messages[0]
    assert dup.payload is None and dup.extras["xregistry_dataschema"] == "https://schemas.example.com/other.json"
    # producer + consumer publishes; a message with no CloudEvents type is channelled by id.
    assert ops["vendor-x.x.heartbeat"].kind == OperationKind.PUBLISH
    heartbeat = next(c for c in model.channels if c.key == "x.heartbeat")
    assert heartbeat.protocol == "x-acme" and heartbeat.bindings == {"x-acme": {"channel": "hb"}}
    # The empty `orphans` group adds no service.
    assert {s.key for s in model.services} == {"webhook", "vendor-x"}


def test_a_message_group_no_endpoint_carries_is_its_own_service() -> None:
    raw = {
        "name": "Loose",
        "messagegroups": {
            "g": {"envelope": "CloudEvents/1.0", "messages": {"m": {"envelopemetadata": {"type": {"value": "t.m"}}}}}
        },
    }
    model = ADAPTER.normalize(ADAPTER.parse(json.dumps(raw)))
    (service,) = model.services
    assert service.key == "g" and service.extras["xregistry_kind"] == "messagegroup"
    assert [op.key for op in service.operations] == ["g.m"]
    assert model.channels[0].protocol == "cloudevents"


def test_raw_is_kept_only_when_asked() -> None:
    document = ADAPTER.parse(_text("01-minimal-schema-registry.json"))
    assert ADAPTER.normalize(document).raw == {"xregistry": document.raw}
    assert ADAPTER.normalize(document, include_raw=False).raw is None


def test_normalize_rejects_a_foreign_ast() -> None:
    with pytest.raises(ImportSourceError):
        ADAPTER.normalize({"schemagroups": {}})


# ---------------------------------------------------------------------------
# Fingerprint, diff, lint
# ---------------------------------------------------------------------------


def test_registry_bookkeeping_and_order_do_not_move_the_fingerprint() -> None:
    raw = json.loads(_text("02-typical-order-events.json"))
    base = ADAPTER.fingerprint(ADAPTER.normalize(ADAPTER.parse(json.dumps(raw))))
    raw["epoch"] = 9
    raw["modifiedat"] = "2027-01-01T00:00:00Z"
    group = raw["messagegroups"]["com.example.orders"]
    group["messages"] = dict(reversed(list(group["messages"].items())))
    moved = ADAPTER.fingerprint(ADAPTER.normalize(ADAPTER.parse(json.dumps(raw))))
    assert moved == base


def test_the_v2_release_diffs_as_added_messages_endpoint_and_changed_schemas() -> None:
    old, new = _model("02-typical-order-events.json"), _model("06-typical-order-events-v2.json")
    assert ADAPTER.fingerprint(old) != ADAPTER.fingerprint(new)
    diff = ADAPTER.diff(old, new)
    changes = {(e.change.value, e.entity, e.key) for e in diff.entries}
    assert ("added", "service", "orders.kafka") in changes
    assert ("added", "channel", "com.example.orders.cancelled") in changes
    assert ("added", "operation", "orders.mqtt.com.example.orders.com.example.orders.cancelled") in changes
    assert ("changed", "type", "OrderCreated") in changes
    assert ("changed", "type", "OrderShipped") in changes
    assert not [e for e in diff.entries if e.change.value == "removed"]


def test_lint_runs_over_the_event_model() -> None:
    report = ADAPTER.lint(_model("02-typical-order-events.json"))
    assert 0 <= report.score <= 100
    assert any(f.rule.startswith("common.") for f in report.findings)


def test_the_schema_description_documents_its_type() -> None:
    raw = {"schemagroups": {"g": {"schemas": {"S": {"format": "JsonSchema/draft-07", "description": "Docs.",
                                                     "schema": {"type": "object", "properties": {}}}}}}}
    model = ADAPTER.normalize(ADAPTER.parse(json.dumps(raw)))
    assert model.types[0].description == "Docs."


def test_a_delegated_schema_that_does_not_parse_is_opaque() -> None:
    raw = {"schemagroups": {"g": {"schemas": {"Bad": {"format": "Avro/1.11.0", "schema": "not avro"}}}}}
    model = ADAPTER.normalize(ADAPTER.parse(json.dumps(raw)))
    (bad,) = model.types
    assert bad.kind == TypeKind.SCALAR and bad.extras["xregistry_document"] == "not avro"


def test_fileset_parses_its_root_member() -> None:
    from app.fileset import IntakeFileset

    text = _text("01-minimal-schema-registry.json")
    fileset = IntakeFileset(root="reg.json", members={"reg.json": text})
    assert ADAPTER.parse_fileset(fileset).registry_id == "minimal"
    with pytest.raises(ImportSourceError):
        ADAPTER.parse_fileset(IntakeFileset(root="missing.json", members={"reg.json": text}))


def test_base64_fixture_round_trips() -> None:
    raw = json.loads(_text("04-stress-edge-cases.json"))
    encoded = raw["schemagroups"]["billing"]["schemas"]["Invoice"]["schemabase64"]
    assert base64.b64decode(encoded).decode("utf-8").startswith("<?xml")
