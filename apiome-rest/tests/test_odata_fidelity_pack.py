"""OData fidelity pack — MFX-16.2 (#3898).

:class:`app.odata_emitter.ODataFidelityRulePack` predicts the OData export's losses in the epic's three
classes, each with its kind and reason:

* **keyless types** — an entity without a key gets an inferred one (``APPROX``, made non-nullable when it was
  nullable) or a synthesized ``Id`` (``SYNTH``); a record that is not a resource is a complex type and needs
  none;
* **RPC and event DROP** — unary RPCs become Actions / Functions (``APPROX``); client / bidirectional streams
  and GraphQL subscriptions are not written (critical ``DROP``); a server stream returns a collection
  (``APPROX``); events and channels are ``DROP``;
* **type coercion** — primitives with no CSDL type (``APPROX``), formats and constraints with no CSDL form
  (``DROP``), source field numbers (``DROP`` info).

The prediction agrees with the losses the writer records, and every export stays valid CSDL.
"""

from __future__ import annotations

import json
from typing import Dict, List

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
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import LossKind
from app.fidelity_engine import compute_lossiness_for_emitter
from app.lossiness import LossinessKind, LossinessSeverity, LossItem
from app.odata_emitter import ODataEmitOptions, ODataEmitter, validate_odata_document


def _field(owner: str, name: str, ref: str = "string", **kw) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=TypeRef(name=ref, nullable=kw.pop("nullable", True)),
                          **kw)


def _record(name: str, *fields: CanonicalField) -> Type:
    return Type(key=name, name=name, kind=TypeKind.RECORD, fields=list(fields))


def _api(*, types=(), operations=(), channels=(), paradigm=ApiParadigm.REST, fmt="openapi-3.1") -> CanonicalApi:
    services = [Service(key="svc", name="Svc", operations=list(operations))] if operations else []
    return CanonicalApi(paradigm=paradigm, format=fmt, identity=ApiIdentity(name="Shop"), title="Shop",
                        services=services, types=list(types), channels=list(channels))


def _list_op(type_name: str) -> Operation:
    return Operation(key=f"GET /{type_name.lower()}s", name=f"list{type_name}", kind=OperationKind.REQUEST_RESPONSE,
                     http_method="GET", http_path=f"/{type_name.lower()}s",
                     messages=[Message(key=f"GET /{type_name}#200", role=MessageRole.RESPONSE, status_code="200",
                                       payload=TypeRef(item=TypeRef(name=type_name)))])


def _report(api: CanonicalApi) -> Dict[str, List[LossItem]]:
    items: Dict[str, List[LossItem]] = {}
    for item in compute_lossiness_for_emitter(api, ODataEmitter()).items:
        items.setdefault(item.construct_key, []).append(item)
    return items


def _by_mapping(items: List[LossItem]) -> Dict[str, LossItem]:
    return {item.target_mapping: item for item in items}


def _valid(api: CanonicalApi) -> None:
    for file in ODataEmitter().emit(api, opts=ODataEmitOptions(output="both")).files:
        validate_odata_document(file.content)


# ===========================================================================
# Keyless types
# ===========================================================================


def test_an_inferred_key_is_made_non_nullable_and_reported() -> None:
    api = _api(types=[_record("Pet", _field("Pet", "id"), _field("Pet", "name"))], operations=[_list_op("Pet")])
    (item,) = _report(api)["Pet"]
    assert item.kind is LossinessKind.APPROX and item.target_mapping == "key-inferred"
    assert "non-nullable" in item.message
    doc = json.loads(ODataEmitter().emit(api).files[0].content)
    assert doc["Shop"]["Pet"]["id"] == {} and doc["Shop"]["Pet"]["$Key"] == ["id"]
    _valid(api)


def test_a_keyless_resource_gets_a_synthesized_key_and_a_value_type_needs_none() -> None:
    api = _api(types=[_record("Note", _field("Note", "text"), _field("Note", "tag", "Tag")),
                      _record("Tag", _field("Tag", "label"))], operations=[_list_op("Note")])
    report = _report(api)
    (note,) = report["Note"]
    assert note.kind is LossinessKind.SYNTH and note.target_mapping == "key-synthesized"
    (tag,) = report["Tag"]
    assert tag.kind is LossinessKind.OK and tag.target_mapping == "ComplexType Tag"
    _valid(api)


# ===========================================================================
# RPC and event DROP
# ===========================================================================


def _rpc(key: str, **kw) -> Operation:
    return Operation(key=key, name=key.split(".")[-1], kind=kw.pop("kind", OperationKind.REQUEST_RESPONSE),
                     messages=[Message(key=f"{key}#r", role=MessageRole.RESPONSE, payload=TypeRef(name="string"))],
                     **kw)


@pytest.mark.parametrize(("operation", "label"), [
    (_rpc("Svc.Upload", streaming=StreamingMode.CLIENT), "client-streaming call"),
    (_rpc("Svc.Chat", streaming=StreamingMode.BIDIRECTIONAL), "bidirectional-streaming call"),
    (_rpc("Subscription.onPet", kind=OperationKind.SUBSCRIPTION), "GraphQL subscription"),
])
def test_client_and_bidirectional_streams_and_subscriptions_are_dropped(operation: Operation, label: str) -> None:
    api = _api(operations=[operation, _rpc("Svc.Get")], paradigm=ApiParadigm.RPC, fmt="protobuf")
    (item,) = _report(api)[operation.key]
    assert item.kind is LossinessKind.DROP and item.severity is LossinessSeverity.CRITICAL
    assert item.target_mapping == "stream-dropped" and label in item.message
    schema = json.loads(ODataEmitter().emit(api).files[0].content)["Shop"]
    assert operation.name not in schema and "Get" in schema
    _valid(api)


def test_a_server_stream_returns_a_collection() -> None:
    api = _api(operations=[_rpc("Svc.Watch", kind=OperationKind.QUERY, streaming=StreamingMode.SERVER)],
               paradigm=ApiParadigm.RPC, fmt="protobuf")
    items = _by_mapping(_report(api)["Svc.Watch"])
    assert items["stream-as-collection"].kind is LossinessKind.APPROX
    schema = json.loads(ODataEmitter().emit(api).files[0].content)["Shop"]
    assert schema["Watch"][0]["$ReturnType"] == {"$Type": "Edm.String", "$Collection": True}
    _valid(api)


def test_unary_rpcs_are_actions_and_events_and_channels_are_dropped() -> None:
    publish = Operation(key="onOrder", name="onOrder", kind=OperationKind.PUBLISH, channel_ref="orders")
    api = _api(operations=[_rpc("Svc.Get"), publish], channels=[Channel(key="orders", address="orders")],
               types=[_record("Order", _field("Order", "id", nullable=False))], paradigm=ApiParadigm.RPC,
               fmt="protobuf")
    report = _report(api)
    assert _by_mapping(report["Svc.Get"])["operation-as-action"].kind is LossinessKind.APPROX
    (event,) = report["onOrder"]
    assert event.kind is LossinessKind.DROP and event.target_mapping == "event-operation-dropped"
    (channel,) = report["orders"]
    assert channel.kind is LossinessKind.DROP and channel.target_mapping == "channel-dropped"
    _valid(api)


# ===========================================================================
# Type coercion
# ===========================================================================


def test_coercions_formats_and_field_numbers() -> None:
    item = _record("Item",
                   _field("Item", "count", "uint64", field_number=1),
                   _field("Item", "mail", constraints=Constraints(format="email"), field_number=2),
                   _field("Item", "at", constraints=Constraints(format="date-time"), field_number=3),
                   _field("Item", "odd", "Snowflake", field_number=4))
    report = _report(_api(types=[item], paradigm=ApiParadigm.DATA_SCHEMA, fmt="protobuf"))
    count = _by_mapping(report["Item.count"])
    assert count["primitive-coerced"].kind is LossinessKind.APPROX and "Edm.Decimal" in count[
        "primitive-coerced"].message
    mail = [i for i in report["Item.mail"] if i.target_mapping == "constraint-dropped"]
    assert mail and "format 'email'" in mail[0].message
    assert all(i.target_mapping != "constraint-dropped" for i in report["Item.at"])
    assert _by_mapping(report["Item.odd"])["primitive-coerced"].kind is LossinessKind.APPROX
    numbers = [i for i in report["Item.at"] if i.kind is LossinessKind.DROP]
    assert numbers and numbers[0].severity is LossinessSeverity.INFO


# ===========================================================================
# Agreement with the writer
# ===========================================================================


def test_every_writer_loss_is_predicted() -> None:
    api = _api(types=[_record("Note", _field("Note", "text", constraints=Constraints(format="email")))],
               operations=[_list_op("Note"), _rpc("Svc.Chat", streaming=StreamingMode.BIDIRECTIONAL),
                           _rpc("Svc.Watch", streaming=StreamingMode.SERVER)])
    predicted = {(item.target_mapping, item.kind) for items in _report(api).values() for item in items}
    for loss in ODataEmitter().emit(api).losses:
        kind = LossinessKind.DROP if loss.kind is LossKind.NA else (
            LossinessKind.SYNTH if loss.subject == "key-synthesized" else LossinessKind.APPROX)
        assert (loss.subject, kind) in predicted, loss
