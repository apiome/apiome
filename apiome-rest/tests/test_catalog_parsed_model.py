"""Contract tests for the catalog parsed-model projection — MFI-25.2 (#4087).

These pin the normalized, paradigm-tagged entity list the catalog detail API's ``parsed`` array
carries (:mod:`app.catalog_parsed_model`) — *entity groups → entities (name, tag, meta) → fields
(name, type, description, required)*. They cover:

* one contract per MVP format — **GraphQL** (reconstructed end-to-end through the real import
  adapter), **AsyncAPI** (through the real normalizer on a dereferenced doc), and **gRPC** (a canonical
  model shaped exactly as the proto normalizer emits, so the projection is verified without protoc);
* the stable output shape (every group/entity/field has its documented keys);
* graceful degradation to ``[]`` for an absent/empty model and for an item with no reconstructable
  source (no content / URL-only / unparseable).
"""

from __future__ import annotations

from app.asyncapi_normalizer import AsyncApiNormalizer
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
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
from app.catalog_parsed_model import (
    derive_catalog_parsed_model,
    derive_parsed_model,
    reconstruct_catalog_api,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _groups_by_title(parsed):
    """Index a parsed model by group title for concise assertions."""
    return {group["title"]: group for group in parsed}


def _entities_by_name(group):
    """Index a group's entities by entity name."""
    return {entity["name"]: entity for entity in group["entities"]}


def _fields_by_name(entity):
    """Index an entity's fields by field name."""
    return {field["name"]: field for field in entity["fields"]}


def _assert_stable_shape(parsed):
    """Every group/entity/field carries exactly its documented keys and value types."""
    assert isinstance(parsed, list)
    for group in parsed:
        assert set(group) == {"title", "subtitle", "entities"}
        assert isinstance(group["title"], str) and group["title"]
        assert group["entities"], "empty groups must be dropped, never emitted"
        for entity in group["entities"]:
            assert set(entity) == {"name", "tag", "meta", "fields"}
            assert isinstance(entity["name"], str)
            assert isinstance(entity["tag"], str) and entity["tag"]
            for field in entity["fields"]:
                assert set(field) == {"name", "type", "description", "required"}
                assert isinstance(field["name"], str)
                assert isinstance(field["type"], str)
                assert isinstance(field["required"], bool)


# ---------------------------------------------------------------------------
# GraphQL — reconstructed end-to-end through the real import adapter
# ---------------------------------------------------------------------------
_GRAPHQL_SDL = """
type Query {
  orders(status: OrderStatus, first: Int = 20): [Order!]!
  order(id: ID!): Order
}
type Mutation {
  placeOrder(input: PlaceOrderInput!): Order!
}
type Order {
  id: ID!
  status: OrderStatus!
}
input PlaceOrderInput {
  items: [String!]!
}
enum OrderStatus {
  PENDING
  PAID
}
"""


def _graphql_item():
    return {
        "id": "cat-graphql",
        "source_format": "graphql",
        "protocol": None,
        "tool_versions": {},
        "format_metadata": {"sourceContent": _GRAPHQL_SDL, "sourceLabel": "schema.graphql"},
    }


def test_graphql_projects_operations_and_types():
    """A GraphQL SDL projects an Operations group (QUERY/MUTATION) and a Types group (OBJECT/INPUT/ENUM)."""
    parsed = derive_catalog_parsed_model(_graphql_item())
    _assert_stable_shape(parsed)
    groups = _groups_by_title(parsed)
    assert set(groups) == {"Operations", "Types"}

    ops = _entities_by_name(groups["Operations"])
    assert ops["orders"]["tag"] == "QUERY"
    assert ops["orders"]["meta"] == "→ [Order]"  # list return, nullability carried by required
    assert ops["placeOrder"]["tag"] == "MUTATION"
    # An argument with a default is not required; a bare non-null argument is.
    orders_fields = _fields_by_name(ops["orders"])
    assert orders_fields["first"]["required"] is False
    assert _fields_by_name(ops["placeOrder"])["input"]["required"] is True

    types = _entities_by_name(groups["Types"])
    assert types["Order"]["tag"] == "OBJECT"
    assert types["PlaceOrderInput"]["tag"] == "INPUT"
    assert types["OrderStatus"]["tag"] == "ENUM"
    assert types["OrderStatus"]["meta"] == "2 values"
    assert {f["name"] for f in types["OrderStatus"]["fields"]} == {"PENDING", "PAID"}
    # A non-null object field is required; a list type renders with [...].
    assert _fields_by_name(types["Order"])["id"]["required"] is True
    assert _fields_by_name(types["PlaceOrderInput"])["items"]["type"] == "[String]"


# ---------------------------------------------------------------------------
# AsyncAPI — projected from the real normalizer's output on a dereferenced doc
# ---------------------------------------------------------------------------
def _asyncapi_doc():
    authorized = {
        "address": "payments.authorized",
        "messages": {
            "PaymentAuthorized": {
                "name": "PaymentAuthorized",
                "payload": {
                    "type": "object",
                    "properties": {
                        "payment_id": {"type": "string", "format": "uuid"},
                        "amount": {"type": "integer"},
                    },
                    "required": ["payment_id"],
                },
            }
        },
    }
    captured = {
        "address": "payments.captured",
        "messages": {"PaymentCaptured": {"name": "PaymentCaptured", "payload": {"type": "object"}}},
    }
    return {
        "asyncapi": "3.0.0",
        "info": {"title": "Payments", "version": "1.0.0"},
        "channels": {"paymentsAuthorized": authorized, "paymentsCaptured": captured},
        "operations": {
            "onPaymentAuthorized": {"action": "receive", "channel": dict(authorized)},
            "publishCapture": {"action": "send", "channel": dict(captured)},
        },
    }


def test_asyncapi_projects_channels_operations_messages():
    """An AsyncAPI doc projects Channels, Operations (SEND/RECEIVE) and Messages (payload fields)."""
    api = AsyncApiNormalizer().normalize(_asyncapi_doc())
    parsed = derive_parsed_model(api)
    _assert_stable_shape(parsed)
    groups = _groups_by_title(parsed)
    assert set(groups) == {"Channels", "Operations", "Messages"}

    channels = _entities_by_name(groups["Channels"])
    assert "payments.authorized" in channels
    assert channels["payments.authorized"]["tag"] == "CHANNEL"

    ops = _entities_by_name(groups["Operations"])
    assert ops["onPaymentAuthorized"]["tag"] == "RECEIVE"
    assert ops["onPaymentAuthorized"]["meta"] == "channel: payments.authorized"
    assert ops["publishCapture"]["tag"] == "SEND"

    messages = _entities_by_name(groups["Messages"])
    payment = messages["PaymentAuthorized"]
    assert payment["tag"] == "MESSAGE"
    fields = _fields_by_name(payment)
    assert fields["payment_id"]["type"] == "string (uuid)"
    assert fields["payment_id"]["required"] is True
    assert fields["amount"]["required"] is False


# ---------------------------------------------------------------------------
# gRPC — a canonical model shaped exactly as the proto normalizer emits
# ---------------------------------------------------------------------------
def _proto_field(owner: str, name: str, type_name: str, number: int) -> CanonicalField:
    """A protobuf record field with its positional field number (mirrors the proto normalizer)."""
    return CanonicalField(
        key=f"{owner}.{name}",
        name=name,
        type=TypeRef(name=type_name),
        field_number=number,
    )


def _rpc_method(service: str, name: str, request: str, response: str, streaming: StreamingMode) -> Operation:
    """A gRPC method with its request/response messages and streaming mode."""
    key = f"{service}.{name}"
    return Operation(
        key=key,
        name=name,
        kind=OperationKind.REQUEST_RESPONSE,
        streaming=streaming,
        messages=[
            Message(key=f"{key}#request", role=MessageRole.REQUEST, payload=TypeRef(name=request)),
            Message(key=f"{key}#response", role=MessageRole.RESPONSE, payload=TypeRef(name=response)),
        ],
    )


def _grpc_api() -> CanonicalApi:
    reading = Type(
        key="acme.Reading",
        name="Reading",
        kind=TypeKind.RECORD,
        fields=[
            _proto_field("acme.Reading", "vehicle_id", "string", 1),
            _proto_field("acme.Reading", "speed_kph", "double", 2),
        ],
    )
    ack = Type(
        key="acme.Ack",
        name="Ack",
        kind=TypeKind.RECORD,
        fields=[_proto_field("acme.Ack", "ok", "bool", 1)],
    )
    service = "acme.TelemetryService"
    return CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        identity=ApiIdentity(name="acme.telemetry"),
        services=[
            Service(
                key=service,
                name="TelemetryService",
                operations=[
                    _rpc_method(service, "Report", "acme.Reading", "acme.Ack", StreamingMode.NONE),
                    _rpc_method(service, "StreamReadings", "acme.Reading", "acme.Reading", StreamingMode.SERVER),
                ],
            )
        ],
        types=[reading, ack],
    )


def test_grpc_projects_services_and_messages():
    """A gRPC model projects a Services & methods group (streaming signatures) and a Messages group."""
    parsed = derive_parsed_model(_grpc_api())
    _assert_stable_shape(parsed)
    groups = _groups_by_title(parsed)
    assert set(groups) == {"Services & methods", "Messages"}

    services = _entities_by_name(groups["Services & methods"])
    telemetry = services["TelemetryService"]
    assert telemetry["tag"] == "SERVICE"
    assert telemetry["meta"] == "2 methods"
    methods = _fields_by_name(telemetry)
    assert methods["Report"]["type"] == "(acme.Reading) → acme.Ack"
    assert methods["StreamReadings"]["type"] == "(acme.Reading) → stream acme.Reading"

    messages = _entities_by_name(groups["Messages"])
    assert messages["Reading"]["tag"] == "MESSAGE"
    reading_fields = _fields_by_name(messages["Reading"])
    assert reading_fields["vehicle_id"]["type"] == "string #1"
    assert reading_fields["speed_kph"]["type"] == "double #2"


# ---------------------------------------------------------------------------
# Streaming variants of the gRPC signature
# ---------------------------------------------------------------------------
def _one_method_service(streaming: StreamingMode) -> CanonicalApi:
    op = _rpc_method("p.S", "M", "Req", "Resp", streaming)
    return CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        identity=ApiIdentity(name="p"),
        services=[Service(key="p.S", name="S", operations=[op])],
    )


def test_grpc_streaming_signatures():
    """Client/server/bidi streaming each mark the correct side of the signature with ``stream``."""
    def signature(mode):
        parsed = derive_parsed_model(_one_method_service(mode))
        service = parsed[0]["entities"][0]
        return service["fields"][0]["type"]

    assert signature(StreamingMode.NONE) == "(Req) → Resp"
    assert signature(StreamingMode.CLIENT) == "(stream Req) → Resp"
    assert signature(StreamingMode.SERVER) == "(Req) → stream Resp"
    assert signature(StreamingMode.BIDIRECTIONAL) == "(stream Req) → stream Resp"


# ---------------------------------------------------------------------------
# Generic fallback (data-schema paradigm) + graceful degradation
# ---------------------------------------------------------------------------
def test_data_schema_falls_back_to_types_group():
    """A paradigm with no bespoke builder (Avro/JSON Schema) still yields a Types group."""
    api = CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="avro",
        identity=ApiIdentity(name="record-lib"),
        types=[
            Type(
                key="Person",
                name="Person",
                kind=TypeKind.RECORD,
                fields=[CanonicalField(key="Person.name", name="name", type=TypeRef(name="string", nullable=False))],
            )
        ],
    )
    parsed = derive_parsed_model(api)
    _assert_stable_shape(parsed)
    groups = _groups_by_title(parsed)
    assert set(groups) == {"Types"}
    person = _entities_by_name(groups["Types"])["Person"]
    assert person["tag"] == "OBJECT"
    assert _fields_by_name(person)["name"]["required"] is True


def test_none_model_degrades_to_empty():
    """A missing canonical model degrades to an empty list, never an error."""
    assert derive_parsed_model(None) == []


def test_empty_model_degrades_to_empty():
    """A model with no services/types/channels emits no groups (all would be empty)."""
    api = CanonicalApi(paradigm=ApiParadigm.RPC, format="protobuf", identity=ApiIdentity(name="empty"))
    assert derive_parsed_model(api) == []


def test_item_without_captured_content_degrades_to_empty():
    """An item with only provenance (no captured source text) yields ``[]`` (nothing to reconstruct)."""
    item = {"id": "cat-x", "source_format": "graphql", "format_metadata": {"package": "acme"}}
    assert derive_catalog_parsed_model(item) == []
    assert reconstruct_catalog_api(item) is None


def test_item_url_only_degrades_to_empty():
    """A URL-only source (no inline content) cannot be reconstructed inline → ``[]``."""
    item = {"id": "cat-x", "source_format": "graphql", "format_metadata": {"sourceUrl": "https://x/schema.graphql"}}
    assert derive_catalog_parsed_model(item) == []


def test_item_unparseable_content_degrades_to_empty():
    """Captured content the adapter cannot parse degrades to ``[]`` (a read never 500s on a bad model)."""
    item = {"id": "cat-x", "source_format": "graphql", "format_metadata": {"sourceContent": "@@@ not graphql @@@"}}
    assert derive_catalog_parsed_model(item) == []


def test_reconstruct_returns_model_for_valid_source():
    """A valid captured source reconstructs a real canonical model (proves derivability, not just [])."""
    api = reconstruct_catalog_api(_graphql_item())
    assert api is not None
    assert api.paradigm is ApiParadigm.GRAPH
    assert api.services
