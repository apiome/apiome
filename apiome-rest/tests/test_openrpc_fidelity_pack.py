"""OpenRPC fidelity pack — MFX-33.2 (#4302).

JSON-RPC 2.0 has no HTTP semantics, no streams and no channels, so
:class:`app.openrpc_emitter.OpenRpcFidelityRulePack` enumerates what a REST, gRPC or event source loses,
each with its kind and reason:

* HTTP: the method and path (``DROP``, kept as ``x-http``), parameter locations (``APPROX``), a success
  status other than 200 (``DROP``), error statuses as codes (``APPROX``), response headers and errors
  without an integer status (``DROP``);
* streaming: gRPC streams and GraphQL subscriptions (``DROP``);
* events: publish / subscribe operations become notifications (``APPROX``), a channel used by one is an
  ``APPROX`` and an unused channel a ``DROP``;
* field identity: Protobuf / Thrift field numbers (``DROP`` info).

The prediction agrees with the losses the writer records, and the notifications are valid OpenRPC.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import LossKind
from app.fidelity_engine import compute_lossiness_for_emitter
from app.lossiness import LossinessKind, LossinessSeverity, LossItem
from app.openrpc_emitter import OpenRpcEmitter, validate_openrpc_document

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


def _api(*, operations=(), types=(), channels=(), paradigm=ApiParadigm.REST, fmt="openapi-3.1") -> CanonicalApi:
    services = [Service(key="svc", name="Shop", operations=list(operations))] if operations else []
    return CanonicalApi(paradigm=paradigm, format=fmt, identity=ApiIdentity(name="Shop"), title="Shop", version="1",
                        services=services, types=list(types), channels=list(channels))


def _report(api: CanonicalApi) -> Dict[str, List[LossItem]]:
    items: Dict[str, List[LossItem]] = {}
    for item in compute_lossiness_for_emitter(api, OpenRpcEmitter()).items:
        items.setdefault(item.construct_key, []).append(item)
    return items


def _by_mapping(items: List[LossItem]) -> Dict[str, LossItem]:
    return {item.target_mapping: item for item in items}


def _rest_op() -> Operation:
    key = "POST /orders/{id}"
    return Operation(
        key=key, name="createOrder", kind=OperationKind.REQUEST_RESPONSE, http_method="POST",
        http_path="/orders/{id}",
        parameters=[
            Parameter(key=f"{key}#path.id", name="id", location=ParameterLocation.PATH, type=TypeRef(name="string"),
                      required=True),
            Parameter(key=f"{key}#header.X-Tenant", name="X-Tenant", location=ParameterLocation.HEADER,
                      type=TypeRef(name="string")),
            Parameter(key=f"{key}#cookie.session", name="session", location=ParameterLocation.COOKIE,
                      type=TypeRef(name="string")),
        ],
        messages=[
            Message(key=f"{key}#request", role=MessageRole.REQUEST, payload=TypeRef(name="string")),
            Message(key=f"{key}#201", role=MessageRole.RESPONSE, status_code="201", payload=TypeRef(name="string"),
                    headers=[CanonicalField(key=f"{key}#201.Location", name="Location", type=TypeRef(name="string"))]),
            Message(key=f"{key}#409", role=MessageRole.ERROR, status_code="409"),
            Message(key=f"{key}#4XX", role=MessageRole.ERROR, status_code="4XX"),
        ],
    )


# ===========================================================================
# HTTP semantics
# ===========================================================================


def test_rest_losses_are_enumerated_with_kinds_and_reasons() -> None:
    items = _by_mapping(_report(_api(operations=[_rest_op()]))["POST /orders/{id}"])
    expected = {
        "http-binding-dropped": (LossinessKind.DROP, "POST /orders/{id} is the method 'createOrder'"),
        "http-parameters-reframed": (LossinessKind.APPROX, "path id, header X-Tenant, cookie session, the body"),
        "http-status-dropped": (LossinessKind.DROP, "the 201 status"),
        "http-status-as-error-code": (LossinessKind.APPROX, "the 409 error"),
        "error-dropped": (LossinessKind.DROP, "status 4XX"),
        "response-header-dropped": (LossinessKind.DROP, "has no headers"),
    }
    assert set(expected) <= set(items)
    for mapping, (kind, reason) in expected.items():
        assert items[mapping].kind is kind, mapping
        assert reason in items[mapping].message, (mapping, items[mapping].message)
    root = _by_mapping(_report(_api(operations=[_rest_op()]))[""])
    assert root["rest → JSON-RPC"].kind is LossinessKind.APPROX


def test_a_plain_rest_operation_reports_only_its_binding() -> None:
    op = Operation(key="GET /ping", name="ping", kind=OperationKind.REQUEST_RESPONSE, http_method="GET",
                   http_path="/ping", messages=[Message(key="GET /ping#200", role=MessageRole.RESPONSE,
                                                        status_code="200", payload=TypeRef(name="string"))])
    assert [item.target_mapping for item in _report(_api(operations=[op]))["GET /ping"]] == ["http-binding-dropped"]


# ===========================================================================
# Streaming
# ===========================================================================


@pytest.mark.parametrize(("kind", "streaming", "label"), [
    (OperationKind.REQUEST_RESPONSE, StreamingMode.SERVER, "server-streaming"),
    (OperationKind.REQUEST_RESPONSE, StreamingMode.CLIENT, "client-streaming"),
    (OperationKind.REQUEST_RESPONSE, StreamingMode.BIDIRECTIONAL, "bidirectional-streaming"),
    (OperationKind.SUBSCRIPTION, StreamingMode.NONE, "a subscription"),
])
def test_streams_and_subscriptions_are_dropped(kind: OperationKind, streaming: StreamingMode, label: str) -> None:
    op = Operation(key="Svc.Watch", name="Watch", kind=kind, streaming=streaming)
    items = _by_mapping(_report(_api(operations=[op], paradigm=ApiParadigm.RPC, fmt="protobuf"))["Svc.Watch"])
    assert items["streaming-dropped"].kind is LossinessKind.DROP and label in items["streaming-dropped"].message


# ===========================================================================
# Events
# ===========================================================================


def _event_api() -> CanonicalApi:
    signedup = Channel(key="user/{userId}/signedup", address="user/{userId}/signedup",
                       parameters=[CanonicalField(key="user/{userId}/signedup.userId", name="userId",
                                                  type=TypeRef(name="string", nullable=False))])
    unused = Channel(key="audit", address="audit")
    publish = Operation(key="onSignup", name="onSignup", kind=OperationKind.PUBLISH,
                        channel_ref="user/{userId}/signedup",
                        messages=[Message(key="onSignup#event", role=MessageRole.EVENT, payload=TypeRef(name="User"))])
    user = Type(key="User", name="User", kind=TypeKind.RECORD,
                fields=[CanonicalField(key="User.id", name="id", type=TypeRef(name="string"))])
    return _api(operations=[publish], types=[user], channels=[signedup, unused], paradigm=ApiParadigm.EVENT,
                fmt="asyncapi-3")


def test_event_operations_are_notifications_and_channels_are_reported() -> None:
    api = _event_api()
    report = _report(api)
    (op,) = report["onSignup"]
    assert op.kind is LossinessKind.APPROX and op.target_mapping == "event-as-notification"
    assert "notification 'onSignup' the service sends" in op.message
    (used,) = report["user/{userId}/signedup"]
    assert used.kind is LossinessKind.APPROX and "onSignup" in used.message
    (unused,) = report["audit"]
    assert unused.kind is LossinessKind.DROP and unused.target_mapping == "channel-dropped"


def test_the_notification_is_written_and_valid() -> None:
    result = OpenRpcEmitter().emit(_event_api())
    validate_openrpc_document(result.files[0].content)
    (method,) = json.loads(result.files[0].content)["methods"]
    assert method == {
        "name": "onSignup",
        "params": [
            {"name": "userId", "schema": {"type": "string"}, "required": True,
             "description": "(channel parameter)"},
            {"name": "message", "schema": {"$ref": "#/components/schemas/User"}, "required": True},
        ],
        "paramStructure": "by-name",
        "x-channel": "user/{userId}/signedup",
    }


# ===========================================================================
# Field identity
# ===========================================================================


def test_field_numbers_are_dropped_as_info() -> None:
    msg = Type(key="Order", name="Order", kind=TypeKind.RECORD, fields=[
        CanonicalField(key="Order.id", name="id", type=TypeRef(name="string"), field_number=1),
        CanonicalField(key="Order.note", name="note", type=TypeRef(name="string"))])
    report = _report(_api(types=[msg], paradigm=ApiParadigm.RPC, fmt="protobuf"))
    (item,) = report["Order.id"]
    assert item.kind is LossinessKind.DROP and item.severity is LossinessSeverity.INFO
    assert "Order.note" not in report


# ===========================================================================
# Agreement with the writer; corpus sources
# ===========================================================================


def test_every_writer_loss_is_predicted() -> None:
    api = _event_api()
    api = api.model_copy(update={"services": [Service(key="svc", name="Shop",
                                                       operations=[*api.services[0].operations, _rest_op()])]})
    predicted = {(item.target_mapping, item.kind) for items in _report(api).values() for item in items}
    for loss in OpenRpcEmitter().emit(api).losses:
        kind = LossinessKind.DROP if loss.kind is LossKind.NA else LossinessKind.APPROX
        assert (loss.subject, kind) in predicted, loss


@pytest.mark.parametrize(("path", "fmt", "mappings"), [
    ("protobuf/02-grpc-service.proto", "protobuf", set()),
    ("openapi/30-openapi-3.0-petstore.yaml", "openapi", {"http-binding-dropped", "http-parameters-reframed"}),
    ("asyncapi/01-user-events-2.6.yaml", "asyncapi", {"event-as-notification"}),
])
def test_corpus_sources_enumerate_their_losses(path: str, fmt: str, mappings: set) -> None:
    file = _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"corpus file {file} is not checked out")
    api = build_conversion_source({"id": "i", "name": file.stem, "source_format": fmt,
                                   "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}).api
    report = compute_lossiness_for_emitter(api, OpenRpcEmitter())
    found = {item.target_mapping for item in report.items}
    assert mappings <= found
    if fmt == "protobuf":
        assert any(item.kind is LossinessKind.DROP and "field number" in item.message for item in report.items)
    validate_openrpc_document(OpenRpcEmitter().emit(api).files[0].content)
