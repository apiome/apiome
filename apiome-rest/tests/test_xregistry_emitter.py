"""xRegistry document emitter — MFX-34.1 (#4306).

Covers :mod:`app.xregistry_emitter`, against the issue's acceptance criteria:

* **event-paradigm sources emit valid xRegistry documents** — every xRegistry corpus document and a
  CloudEvents event export to a document that passes the structural check
  (:func:`app.xregistry_emitter.xregistry_document_problems`), the export gate and a re-import
  through the xRegistry importer;
* **payload schemas resolve; CloudEvents attributes are populated** — every message's
  ``dataschemaxid`` names a schema of the document, every schema is a valid JSON Schema whose
  references resolve inside it, and every message has a ``type``, a ``source`` and a
  ``datacontenttype`` (synthesized, and reported, when the source states none).

Plus the round trip (the same types, CloudEvents types and sources read back), the options, ids,
non-event sources (types only, operations reported dropped), the refusal, and the fidelity pack.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Constraints,
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
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitPreconditionError, EmitResult, EmittedFile, coerce_emit_options, load_builtin_emitters
from app.export_routes import build_target_fidelity_entries
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import get_import_source, load_builtin_import_sources
from app.lossiness import LossinessKind
from app.xregistry_emitter import (
    LOSS_ATTRIBUTE_SYNTHESIZED,
    LOSS_NOT_AN_EVENT,
    SCHEMA_FORMAT,
    XRegistryEmitter,
    check_emitted_xregistry,
    xregistry_document_problems,
)

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
XREGISTRY_CORPUS = sorted(path.name for path in (_EXAMPLES / "xregistry").glob("*.json")) if (
    _EXAMPLES / "xregistry").is_dir() else []


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _corpus(path: str, fmt: str) -> CanonicalApi:
    file = _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": file.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}
    ).api


def _emit(api: CanonicalApi, **options: Any) -> EmitResult:
    return XRegistryEmitter().emit(api, opts=coerce_emit_options(XRegistryEmitter, options))


def _document(api: CanonicalApi, **options: Any) -> Dict[str, Any]:
    return json.loads(str(_emit(api, **options).files[0].content))


def _reimport(content: str) -> CanonicalApi:
    source = get_import_source("xregistry")
    return source.normalize(source.parse(content))


def _messages(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [message for group in (document.get("messagegroups") or {}).values()
            for message in (group.get("messages") or {}).values()]


def _schema_xids(document: Dict[str, Any]) -> set:
    return {f"/schemagroups/{gid}/schemas/{sid}" for gid, group in (document.get("schemagroups") or {}).items()
            for sid in group.get("schemas") or {}}


def _event_api(**overrides: Any) -> CanonicalApi:
    """A small event API: an Order type, one published event with a CloudEvents type, one without."""
    order = Type(key="Order", name="Order", kind=TypeKind.RECORD, description="An order.", fields=[
        CanonicalField(key="Order.id", name="id", type=TypeRef(name="string", nullable=False)),
        CanonicalField(key="Order.total", name="total", type=TypeRef(name="number"),
                       constraints=Constraints(minimum=0)),
        CanonicalField(key="Order.lines", name="lines", type=TypeRef(item=TypeRef(name="Line"))),
    ])
    line = Type(key="Line", name="Line", kind=TypeKind.RECORD, fields=[
        CanonicalField(key="Line.sku", name="sku", type=TypeRef(name="string")),
    ])
    created = Operation(
        key="orders.created", name="orderCreated", kind=OperationKind.PUBLISH, channel_ref="orders/created",
        description="An order was placed.", extras={"cloudevents_type": "com.example.order.created"},
        messages=[Message(key="orders.created#event", role=MessageRole.EVENT, payload=TypeRef(name="Order"),
                          content_types=["application/json"],
                          headers=[CanonicalField(key="h.subject", name="subject", type=TypeRef(name="string",
                                                  nullable=False), description="The order id.")])],
    )
    cancelled = Operation(
        key="orders.cancelled", name="orderCancelled", kind=OperationKind.SUBSCRIBE, channel_ref="orders/cancelled",
        messages=[Message(key="orders.cancelled#event", role=MessageRole.EVENT,
                          payload_schema={"type": "object", "properties": {"reason": {"type": "string"}}})],
    )
    fields: Dict[str, Any] = dict(
        paradigm=ApiParadigm.EVENT, format="asyncapi-3.0", identity=ApiIdentity(name="Order Events"),
        title="Order Events", version="1.0.0",
        services=[Service(key="orders", name="orders", operations=[created, cancelled])],
        channels=[Channel(key="orders/created", address="orders/created"),
                  Channel(key="orders/cancelled", address="orders/cancelled",
                          bindings={"kafka": {"topic": "orders.cancelled"}})],
        types=[order, line],
    )
    fields.update(overrides)
    return CanonicalApi(**fields)


# ===========================================================================
# Valid documents from event sources
# ===========================================================================


@pytest.mark.parametrize("name", XREGISTRY_CORPUS)
def test_every_xregistry_corpus_document_exports_a_valid_document(name: str) -> None:
    api = _corpus(f"xregistry/{name}", "xregistry")
    result = _emit(api)
    assert len(result.files) == 1 and result.files[0].path.endswith(".xregistry.json")
    document = json.loads(str(result.files[0].content))
    assert xregistry_document_problems(document) == []
    assert check_emitted_xregistry(result) == []
    verdict = asyncio.run(validate_emitted_artifact("xregistry", result, api=api))
    assert verdict.valid, [f.message for f in verdict.findings]


@pytest.mark.parametrize("name", XREGISTRY_CORPUS)
def test_an_xregistry_document_reads_back_with_its_types_and_cloudevents_types(name: str) -> None:
    api = _corpus(f"xregistry/{name}", "xregistry")
    back = _reimport(str(_emit(api).files[0].content))
    assert {t.name for t in back.types} >= {t.name for t in api.types if not (t.extras or {}).get("xregistry_opaque")}
    assert {c.address for c in back.channels} == {c.address for c in api.channels}
    assert back.identity.id == api.identity.id  # the registryid is kept


def test_a_cloudevents_event_exports_its_attributes_and_payload_schema() -> None:
    api = _corpus("cloudevents/06-user-signedup.json", "cloudevents")
    document = _document(api)
    [message] = _messages(document)
    assert message["envelope"] == "CloudEvents/1.0"
    assert message["envelopemetadata"]["type"]["value"] == "com.example.user.signedup"
    assert message["envelopemetadata"]["source"]["value"] == "/accounts/service"
    assert message["datacontenttype"] == "application/json"
    assert message["dataschemaformat"] == SCHEMA_FORMAT
    assert message["dataschemaxid"] in _schema_xids(document)


# ===========================================================================
# Payload schemas resolve; CloudEvents attributes populated
# ===========================================================================


def test_each_message_carries_its_cloudevents_attributes() -> None:
    document = _document(_event_api())
    created, cancelled = _messages(document)
    assert created["envelopemetadata"]["type"] == {"value": "com.example.order.created"}
    subject = {"type": "string", "required": True, "description": "The order id."}
    assert created["envelopemetadata"]["subject"] == subject
    # No CloudEvents type stated: the channel's address is the type.
    assert cancelled["envelopemetadata"]["type"]["value"] == "orders/cancelled"
    # No source stated anywhere: `/<registry id>` is written.
    assert {m["envelopemetadata"]["source"]["value"] for m in (created, cancelled)} == {"/order-events"}
    assert created["datacontenttype"] == "application/json"
    assert cancelled["datacontenttype"] == "application/json"


def test_a_named_payload_resolves_to_its_schema_and_an_inline_one_stays_inline() -> None:
    document = _document(_event_api())
    created, cancelled = _messages(document)
    assert created["dataschemaxid"] == "/schemagroups/order-events/schemas/Order"
    assert created["dataschemaxid"] in _schema_xids(document)
    assert cancelled["dataschema"] == {"type": "object", "properties": {"reason": {"type": "string"}}}
    assert "dataschemaxid" not in cancelled


def test_a_schema_carries_the_types_it_reaches_so_it_is_valid_on_its_own() -> None:
    document = _document(_event_api())
    order = document["schemagroups"]["order-events"]["schemas"]["Order"]
    assert order["format"] == SCHEMA_FORMAT and order["defaultversionid"] == "1"
    schema = order["versions"]["1"]["schema"]
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["lines"]["items"] == {"$ref": "#/definitions/Line"}
    assert set(schema["definitions"]) == {"Line"}
    assert schema["properties"]["total"]["minimum"] == 0
    assert "id" in schema["required"]


def test_a_self_referencing_type_carries_itself_under_definitions() -> None:
    node = Type(key="Node", name="Node", kind=TypeKind.RECORD, fields=[
        CanonicalField(key="Node.children", name="children", type=TypeRef(item=TypeRef(name="Node")))])
    api = _event_api(types=[node], services=[])
    schema = _document(api)["schemagroups"]["order-events"]["schemas"]["Node"]["versions"]["1"]["schema"]
    assert schema["definitions"]["Node"]["properties"]["children"]["items"] == {"$ref": "#/definitions/Node"}
    assert xregistry_document_problems(_document(api)) == []


def test_the_round_trip_keeps_payloads_attributes_and_types() -> None:
    api = _event_api()
    back = _reimport(str(_emit(api).files[0].content))
    assert {t.name for t in back.types} >= {"Order", "Line"}
    by_type = {op.extras.get("cloudevents_type"): op for op in back.operations()}
    assert set(by_type) == {"com.example.order.created", "orders/cancelled"}
    event = by_type["com.example.order.created"].messages[0]
    assert event.payload is not None and event.payload.name == "Order"
    assert {h.name for h in event.headers} >= {"type", "source", "subject"}


# ===========================================================================
# Synthesized values, non-events, ids and options
# ===========================================================================


def test_synthesized_attributes_are_losses_and_synth_verdicts() -> None:
    api = _event_api()
    subjects = [(loss.subject, loss.pointer) for loss in _emit(api).losses]
    assert (LOSS_ATTRIBUTE_SYNTHESIZED, "/messagegroups/orders/messages/orderCancelled/envelopemetadata/source") \
        in subjects
    report = compute_lossiness_for_emitter(api, XRegistryEmitter)
    cancelled = [i for i in report.items if i.construct_key == "orders.cancelled"]
    # Re-keyed (it reads back as orders.orderCancelled), and its source synthesized.
    assert [i.kind for i in cancelled] == [LossinessKind.DROP, LossinessKind.SYNTH]
    assert "no CloudEvents source" in cancelled[1].message


def test_a_stated_or_optioned_source_is_not_synthesized() -> None:
    api = _event_api()
    document = _document(api, source="/shop/orders")
    assert {m["envelopemetadata"]["source"]["value"] for m in _messages(document)} == {"/shop/orders"}
    report = compute_lossiness_for_emitter(api, XRegistryEmitter, options={"source": "/shop/orders"})
    # Nothing synthesized: only the re-key (orders.created reads back as orders.orderCreated).
    [item] = [i for i in report.items if i.construct_key == "orders.created"]
    assert item.kind is LossinessKind.DROP and item.severity.value == "info"


def test_a_rest_source_writes_its_types_and_reports_its_operations_dropped() -> None:
    api = _corpus("openapi/30-openapi-3.0-petstore.yaml", "openapi")
    result = _emit(api)
    document = json.loads(str(result.files[0].content))
    assert "messagegroups" not in document and document["schemagroups"]
    assert {loss.subject for loss in result.losses} >= {LOSS_NOT_AN_EVENT}
    report = compute_lossiness_for_emitter(api, XRegistryEmitter)
    dropped = [i for i in report.items if i.construct_key == "GET /pets"]
    assert dropped and dropped[0].kind is LossinessKind.DROP and "not an event" in dropped[0].message


def test_servers_and_bindings_are_reported() -> None:
    api = _event_api(servers=[Server(url="mqtt://broker.example.com")])
    report = compute_lossiness_for_emitter(api, XRegistryEmitter)
    assert any(i.construct_key == "" and i.target_mapping == "servers → dropped (no endpoints)" for i in report.items)
    binding = next(i for i in report.items if i.construct_key == "orders/cancelled")
    assert binding.kind is LossinessKind.APPROX and "bindings" in binding.message


def test_ids_are_made_legal_unique_and_reported() -> None:
    created = Operation(key="a", name="order created!", kind=OperationKind.PUBLISH, channel_ref="x")
    again = Operation(key="b", name="order created!", kind=OperationKind.PUBLISH, channel_ref="x")
    api = _event_api(services=[Service(key="my orders", name="my orders", operations=[created, again])],
                     channels=[Channel(key="x", address="x")])
    document = _document(api)
    assert list(document["messagegroups"]) == ["my_orders"]
    assert list(document["messagegroups"]["my_orders"]["messages"]) == ["order_created_", "order_created__2"]
    assert xregistry_document_problems(document) == []
    report = compute_lossiness_for_emitter(api, XRegistryEmitter)
    assert any(i.kind is LossinessKind.SYNTH and "message group 'my_orders'" in i.message for i in report.items)


def test_the_registry_id_and_indent_options() -> None:
    result = _emit(_event_api(), registry_id="shop", indent=0)
    assert result.files[0].path == "shop.xregistry.json"
    text = str(result.files[0].content)
    assert len(text.splitlines()) == 1
    assert json.loads(text)["registryid"] == "shop"


def test_an_opaque_schema_is_written_back_as_read() -> None:
    api = _corpus("xregistry/04-stress-edge-cases.json", "xregistry")
    opaque = [t for t in api.types if (t.extras or {}).get("xregistry_opaque")]
    if not opaque:
        pytest.skip("the stress document has no opaque schema")
    document = _document(api)
    schemas = next(iter(document["schemagroups"].values()))["schemas"]
    for type_ in opaque:
        entry = next(entry for entry in schemas.values() if entry.get("format") == type_.extras.get("xregistry_format")
                     or "schemauri" in next(iter(entry["versions"].values())))
        assert entry


# ===========================================================================
# Refusal, card and fidelity
# ===========================================================================


def test_a_source_with_neither_types_nor_events_is_refused_and_greyed_out() -> None:
    api = CanonicalApi(paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="x"),
                       services=[Service(key="s", name="s", operations=[
                           Operation(key="GET /x", name="getX", kind=OperationKind.REQUEST_RESPONSE)])])
    with pytest.raises(EmitPreconditionError):
        _emit(api)
    card = next(e for e in build_target_fidelity_entries(api) if e.descriptor.key == "xregistry")
    assert card.descriptor.available is False
    assert "at least one type or event" in (card.descriptor.unavailable_reason or "")


def test_the_card_describes_an_event_target() -> None:
    card = next(e for e in build_target_fidelity_entries(_event_api()) if e.descriptor.key == "xregistry")
    assert card.descriptor.available and card.descriptor.paradigm == "event" and card.descriptor.multi_file is False
    assert {"registry_id", "source", "indent"} <= set(card.options_schema["properties"])


def test_an_imported_schema_only_registry_is_lossless() -> None:
    api = _corpus("xregistry/01-minimal-schema-registry.json", "xregistry")
    report = compute_lossiness_for_emitter(api, XRegistryEmitter)
    assert report.is_lossless, [(i.construct_key, i.message) for i in report.items if i.kind is not LossinessKind.OK]


# ===========================================================================
# The structural check catches broken documents
# ===========================================================================


def _valid() -> Dict[str, Any]:
    return _document(_event_api())


@pytest.mark.parametrize(("break_it", "rule"), [
    (lambda d: d.pop("registryid"), "xregistry-document"),
    (lambda d: d["messagegroups"]["orders"]["messages"]["orderCreated"]["envelopemetadata"]["type"].pop("value"),
     "cloudevents-attribute"),
    (lambda d: d["messagegroups"]["orders"]["messages"]["orderCreated"].pop("datacontenttype"),
     "cloudevents-attribute"),
    (lambda d: d["messagegroups"]["orders"]["messages"]["orderCreated"].update(
        dataschemaxid="/schemagroups/order-events/schemas/Missing"), "xregistry-dataschema"),
    (lambda d: d["messagegroups"]["orders"]["messages"]["orderCreated"].update(envelope="Other/1.0"),
     "cloudevents-envelope"),
    (lambda d: d["schemagroups"]["order-events"]["schemas"]["Order"]["versions"]["1"]["schema"].pop("definitions"),
     "json-schema-ref"),
    (lambda d: d["schemagroups"]["order-events"]["schemas"]["Order"]["versions"]["1"]["schema"].update(type=7),
     "json-schema"),
    (lambda d: d["schemagroups"]["order-events"]["schemas"]["Order"].update(schemaid="Other"), "xregistry-id"),
])
def test_the_check_catches_a_broken_document(break_it: Any, rule: str) -> None:
    document = _valid()
    break_it(document)
    assert rule in {problem["rule"] for problem in xregistry_document_problems(document)}


def test_the_export_gate_rejects_a_broken_artifact() -> None:
    document = _valid()
    document["messagegroups"]["orders"]["messages"]["orderCreated"]["envelopemetadata"].pop("source")
    broken = EmitResult(files=[EmittedFile(path="x.xregistry.json", content=json.dumps(document),
                                           media_type="application/json")], media_type="application/json")
    verdict = asyncio.run(validate_emitted_artifact("xregistry", broken, api=_event_api()))
    assert not verdict.valid and any(f.keyword == "cloudevents-attribute" for f in verdict.findings)


def test_a_repeated_field_name_is_required_once() -> None:
    record = Type(key="Pmt", name="Pmt", kind=TypeKind.RECORD, fields=[
        CanonicalField(key="Pmt.tx1", name="Tx", type=TypeRef(name="string", nullable=False)),
        CanonicalField(key="Pmt.tx2", name="Tx", type=TypeRef(name="string", nullable=False)),
    ])
    document = _document(_event_api(types=[record], services=[]))
    schema = document["schemagroups"]["order-events"]["schemas"]["Pmt"]["versions"]["1"]["schema"]
    assert schema["required"] == ["Tx"]
    assert xregistry_document_problems(document) == []


def test_a_message_that_reads_back_under_another_key_is_reported_re_keyed() -> None:
    api = _event_api()
    back = _reimport(str(_emit(api).files[0].content))
    assert {op.key for op in back.operations()} == {"orders.orderCreated", "orders.orderCancelled"}
    report = compute_lossiness_for_emitter(api, XRegistryEmitter)
    added = [i for i in report.items if i.construct_key == "orders.orderCreated"]
    assert [i.kind for i in added] == [LossinessKind.SYNTH]
    removed = next(i for i in report.items if i.construct_key == "orders.created")
    assert removed.kind is LossinessKind.DROP and "reads back as 'orders.orderCreated'" in removed.message


def test_types_and_channels_of_another_format_are_approximated() -> None:
    report = compute_lossiness_for_emitter(_event_api(), XRegistryEmitter)
    assert next(i for i in report.items if i.construct_key == "Order").kind is LossinessKind.APPROX
    assert next(i for i in report.items if i.construct_key == "orders/created").kind is LossinessKind.APPROX


def test_an_xregistry_source_round_trips_without_unexplained_change() -> None:
    from app.import_source import canonical_diff
    from app.roundtrip_matrix import reconcile

    api = _corpus("xregistry/02-typical-order-events.json", "xregistry")
    back = _reimport(str(_emit(api).files[0].content))
    result = reconcile(canonical_diff(api, back), compute_lossiness_for_emitter(api, XRegistryEmitter))
    assert not result.unexplained and not result.overclaims
