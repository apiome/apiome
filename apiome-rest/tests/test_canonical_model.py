"""Paradigm coverage + round-trip tests for the canonical model (MFI-2.1, #3738).

The acceptance criterion is that the documented model maps cleanly from at least
one REST, one RPC, one event-driven, one graph, and one data-schema sample, and
round-trips to/from persistence. Persistence (MFI-2.2) stores the model as JSONB,
so the lossless guarantee lives in the Pydantic serialization layer exercised
here: every sample is built, asserted on its load-bearing fields, then
``model_dump()`` -> ``json`` -> ``model_validate()`` and compared for equality.
"""

import json

from app.canonical_model import (
    CANONICAL_API_SCHEMA_VERSION,
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Constraints,
    EnumValue,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Server,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)


def _round_trip(api: CanonicalApi) -> CanonicalApi:
    """Serialize as the JSONB DAO would, then reload — the persistence contract."""
    dumped = api.model_dump()
    rehydrated = CanonicalApi.model_validate(json.loads(json.dumps(dumped)))
    assert rehydrated == api
    return rehydrated


# --- REST (OpenAPI) ---------------------------------------------------------


def _rest_sample() -> CanonicalApi:
    """A REST GET with a path param and a 200 response referencing a record."""
    pet = Type(
        key="Pet",
        name="Pet",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(
                key="Pet.id",
                name="id",
                type=TypeRef(name="string", nullable=False),
                constraints=Constraints(format="uuid"),
            ),
            CanonicalField(
                key="Pet.name", name="name", type=TypeRef(name="string", nullable=False)
            ),
        ],
    )
    get_pet = Operation(
        key="GET /pets/{id}",
        name="getPet",
        kind=OperationKind.REQUEST_RESPONSE,
        http_method="GET",
        http_path="/pets/{id}",
        parameters=[
            Parameter(
                key="GET /pets/{id}#path.id",
                name="id",
                location=ParameterLocation.PATH,
                type=TypeRef(name="string", nullable=False),
                required=True,
            )
        ],
        messages=[
            Message(
                key="GET /pets/{id}#response.200",
                role=MessageRole.RESPONSE,
                status_code="200",
                content_types=["application/json"],
                payload=TypeRef(name="Pet", nullable=False),
            )
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        protocol="http",
        identity=ApiIdentity(name="Pet Store"),
        version="1.0.0",
        servers=[Server(url="https://api.example.com/v1", protocol="https")],
        services=[Service(key="pets", name="pets", operations=[get_pet])],
        types=[pet],
    )


def test_rest_sample_maps_and_round_trips() -> None:
    api = _rest_sample()
    op = api.operations()[0]

    assert api.paradigm is ApiParadigm.REST
    assert (op.http_method, op.http_path) == ("GET", "/pets/{id}")
    assert op.parameters[0].location is ParameterLocation.PATH
    response = op.messages[0]
    assert response.status_code == "200"
    assert response.payload is not None and response.payload.name == "Pet"
    assert api.type_by_key("Pet") is not None

    _round_trip(api)


# --- RPC (gRPC / Protobuf) --------------------------------------------------


def _rpc_sample() -> CanonicalApi:
    """A gRPC service with a bidirectional-streaming method and numbered fields."""
    point = Type(
        key="route.Point",
        name="Point",
        kind=TypeKind.RECORD,
        namespace="route",
        fields=[
            CanonicalField(
                key="route.Point.latitude",
                name="latitude",
                type=TypeRef(name="int32", nullable=False),
                field_number=1,
            ),
            CanonicalField(
                key="route.Point.longitude",
                name="longitude",
                type=TypeRef(name="int32", nullable=False),
                field_number=2,
            ),
        ],
    )
    route_chat = Operation(
        key="route.RouteGuide.RouteChat",
        name="RouteChat",
        kind=OperationKind.REQUEST_RESPONSE,
        streaming=StreamingMode.BIDIRECTIONAL,
        messages=[
            Message(
                key="route.RouteGuide.RouteChat#request",
                role=MessageRole.REQUEST,
                payload=TypeRef(name="route.Point", nullable=False),
            ),
            Message(
                key="route.RouteGuide.RouteChat#response",
                role=MessageRole.RESPONSE,
                payload=TypeRef(name="route.Point", nullable=False),
            ),
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="grpc",
        protocol="grpc",
        identity=ApiIdentity(name="RouteGuide", namespace="route"),
        services=[
            Service(key="route.RouteGuide", name="RouteGuide", operations=[route_chat])
        ],
        types=[point],
    )


def test_rpc_sample_preserves_streaming_and_field_numbers() -> None:
    api = _rpc_sample()
    op = api.operations()[0]

    assert op.streaming is StreamingMode.BIDIRECTIONAL
    point = api.type_by_key("route.Point")
    assert point is not None
    assert [f.field_number for f in point.fields] == [1, 2]

    _round_trip(api)


# --- Event-driven (AsyncAPI) ------------------------------------------------


def _event_sample() -> CanonicalApi:
    """An AsyncAPI publish operation bound to a parameterized channel."""
    signup = Type(
        key="UserSignedUp",
        name="UserSignedUp",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(
                key="UserSignedUp.userId",
                name="userId",
                type=TypeRef(name="string", nullable=False),
            )
        ],
    )
    channel = Channel(
        key="user/{userId}/signedup",
        address="user/{userId}/signedup",
        protocol="kafka",
        parameters=[
            CanonicalField(
                key="user/{userId}/signedup#param.userId",
                name="userId",
                type=TypeRef(name="string", nullable=False),
            )
        ],
        bindings={"kafka": {"partitions": 3}},
    )
    publish = Operation(
        key="onUserSignedUp",
        name="onUserSignedUp",
        kind=OperationKind.PUBLISH,
        channel_ref="user/{userId}/signedup",
        messages=[
            Message(
                key="onUserSignedUp#event",
                role=MessageRole.EVENT,
                content_types=["application/json"],
                payload=TypeRef(name="UserSignedUp", nullable=False),
            )
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3",
        protocol="kafka",
        identity=ApiIdentity(name="Accounts Service"),
        services=[Service(key="accounts", name="accounts", operations=[publish])],
        channels=[channel],
        types=[signup],
    )


def test_event_sample_binds_operation_to_channel() -> None:
    api = _event_sample()
    op = api.operations()[0]

    assert op.kind is OperationKind.PUBLISH
    assert op.channel_ref == "user/{userId}/signedup"
    # The operation's channel_ref resolves to a declared channel.
    assert any(c.key == op.channel_ref for c in api.channels)
    channel = api.channels[0]
    assert channel.bindings["kafka"]["partitions"] == 3
    assert channel.parameters[0].name == "userId"
    assert op.messages[0].role is MessageRole.EVENT

    _round_trip(api)


# --- Graph (GraphQL) --------------------------------------------------------


def _graph_sample() -> CanonicalApi:
    """A GraphQL query whose return type exercises ``[Post!]!`` wrapper fidelity."""
    role_enum = Type(
        key="Role",
        name="Role",
        kind=TypeKind.ENUM,
        enum_values=[
            EnumValue(key="Role.ADMIN", name="ADMIN"),
            EnumValue(key="Role.USER", name="USER"),
        ],
    )
    user = Type(
        key="User",
        name="User",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(
                key="User.id", name="id", type=TypeRef(name="ID", nullable=False)
            ),
            # posts: [Post!]!  — non-null list of non-null Post.
            CanonicalField(
                key="User.posts",
                name="posts",
                type=TypeRef(
                    item=TypeRef(name="Post", nullable=False), nullable=False
                ),
            ),
        ],
    )
    user_query = Operation(
        key="Query.user",
        name="user",
        kind=OperationKind.QUERY,
        parameters=[
            Parameter(
                key="Query.user#arg.id",
                name="id",
                location=ParameterLocation.QUERY,
                type=TypeRef(name="ID", nullable=False),
                required=True,
            )
        ],
        messages=[
            Message(
                key="Query.user#response",
                role=MessageRole.RESPONSE,
                payload=TypeRef(name="User", nullable=True),
            )
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.GRAPH,
        format="graphql",
        protocol="graphql-over-http",
        identity=ApiIdentity(name="Blog API"),
        services=[Service(key="Query", name="Query", operations=[user_query])],
        types=[role_enum, user],
    )


def test_graph_sample_preserves_nullability_and_list_wrappers() -> None:
    api = _graph_sample()

    user = api.type_by_key("User")
    assert user is not None
    posts = next(f for f in user.fields if f.name == "posts")
    # [Post!]!  -> outer non-null list, inner non-null element.
    assert posts.type.is_list()
    assert posts.type.nullable is False
    assert posts.type.item is not None
    assert posts.type.item.name == "Post"
    assert posts.type.item.nullable is False

    role = api.type_by_key("Role")
    assert role is not None and role.kind is TypeKind.ENUM
    assert [v.name for v in role.enum_values] == ["ADMIN", "USER"]

    op = api.operations()[0]
    assert op.kind is OperationKind.QUERY
    # Nullable return: Query.user can resolve to null.
    assert op.messages[0].payload is not None
    assert op.messages[0].payload.nullable is True

    _round_trip(api)


# --- Data schema (Avro) -----------------------------------------------------


def _data_schema_sample() -> CanonicalApi:
    """An Avro record with a defaulted field, an enum, and a union (nullable)."""
    suit_enum = Type(
        key="com.example.Suit",
        name="Suit",
        kind=TypeKind.ENUM,
        namespace="com.example",
        enum_values=[
            EnumValue(key="com.example.Suit.SPADES", name="SPADES"),
            EnumValue(key="com.example.Suit.HEARTS", name="HEARTS"),
        ],
    )
    # A union ["null", "string"] is the canonical "optional string".
    nickname_union = Type(
        key="com.example.Card.nickname_union",
        name="nickname_union",
        kind=TypeKind.UNION,
        namespace="com.example",
        union_members=["null", "string"],
    )
    card = Type(
        key="com.example.Card",
        name="Card",
        kind=TypeKind.RECORD,
        namespace="com.example",
        fields=[
            CanonicalField(
                key="com.example.Card.rank",
                name="rank",
                type=TypeRef(name="int", nullable=False),
                default=1,
            ),
            CanonicalField(
                key="com.example.Card.suit",
                name="suit",
                type=TypeRef(name="com.example.Suit", nullable=False),
            ),
            CanonicalField(
                key="com.example.Card.nickname",
                name="nickname",
                type=TypeRef(name="com.example.Card.nickname_union", nullable=True),
                default=None,
            ),
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="avro",
        identity=ApiIdentity(name="Card", namespace="com.example"),
        types=[suit_enum, nickname_union, card],
        raw={"type": "record", "name": "Card", "namespace": "com.example"},
    )


def test_data_schema_sample_preserves_defaults_unions_and_raw() -> None:
    api = _data_schema_sample()

    card = api.type_by_key("com.example.Card")
    assert card is not None
    rank = next(f for f in card.fields if f.name == "rank")
    # Avro default survives normalization (load-bearing for compatibility checks).
    assert rank.default == 1

    union = api.type_by_key("com.example.Card.nickname_union")
    assert union is not None and union.kind is TypeKind.UNION
    assert union.union_members == ["null", "string"]

    # The native AST is retained verbatim for full-fidelity round-tripping.
    assert api.raw == {"type": "record", "name": "Card", "namespace": "com.example"}

    _round_trip(api)


# --- Cross-cutting invariants ----------------------------------------------


def test_schema_version_defaults_and_round_trips() -> None:
    api = _rest_sample()
    assert api.schema_version == CANONICAL_API_SCHEMA_VERSION
    rehydrated = _round_trip(api)
    assert rehydrated.schema_version == CANONICAL_API_SCHEMA_VERSION


def test_extras_bag_is_lossless_for_format_specific_fidelity() -> None:
    api = _rest_sample()
    api.operations()[0].extras["x-internal"] = {"team": "payments", "sla_ms": 250}
    api.types[0].extras["x-table"] = "pets"
    rehydrated = _round_trip(api)
    assert rehydrated.operations()[0].extras["x-internal"]["sla_ms"] == 250
    assert rehydrated.types[0].extras["x-table"] == "pets"


def test_all_five_paradigms_round_trip() -> None:
    """Every paradigm sample survives the JSONB persistence round-trip."""
    for builder in (
        _rest_sample,
        _rpc_sample,
        _event_sample,
        _graph_sample,
        _data_schema_sample,
    ):
        _round_trip(builder())
