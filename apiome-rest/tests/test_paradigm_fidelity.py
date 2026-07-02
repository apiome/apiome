"""Cross-paradigm coverage & fidelity contract suite — MFI-2.4 (#3741).

The canonical model (MFI-2.1) is paradigm-agnostic and every format normalizer
(MFI-2.3 + the format epics) maps *into* it. A lossy model would silently make
downstream diff/lint/browse wrong for some paradigm, so this suite is the
**contract test** the format epics are written against: for each paradigm it
pins the *load-bearing* fields — the ones whose loss would change meaning — and
asserts they survive the full normalizer pipeline.

"Survives the pipeline" here means two things every normalizer subjects its model
to, exercised together by :func:`_through_pipeline`:

1. **Ordering normalization** — :func:`app.normalizer.normalize_ordering`, the
   last step every :class:`~app.normalizer.Normalizer` runs, must not perturb a
   load-bearing value (a streaming flag, a default, an enum ordinal, a GraphQL
   wrapper). It is also asserted *idempotent* (re-ordering an ordered model is a
   no-op) and *fingerprint-stabilizing* (two source orderings of the same API
   produce byte-identical JSON).
2. **JSONB persistence round-trip** — ``model_dump()`` → JSON → ``model_validate()``,
   the MFI-2.2 storage contract; the rehydrated model must equal the original.

Where this suite found a paradigm field with no first-class home, it asserts the
documented escape hatch (``extras`` per entity, ``raw`` per artifact) carries it
losslessly — see :func:`test_avro_explicit_null_default_distinguishable_via_extras`.
The gap audit (:func:`test_load_bearing_fields_have_a_canonical_home`) fails if a
future change to MFI-2.1 drops a field a paradigm depends on, tracking the gap
straight back to the model.

This complements ``test_canonical_model.py`` (one happy-path sample per paradigm):
here each paradigm's load-bearing axis is swept *exhaustively* — every streaming
cardinality, every GraphQL wrapper permutation, both event actions, every falsy
default.
"""

import json

import pytest

from app.canonical_model import (
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
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from app.normalizer import normalize_ordering

# ===========================================================================
# Pipeline helpers — the two transforms every normalized model passes through
# ===========================================================================


def _persist_round_trip(api: CanonicalApi) -> CanonicalApi:
    """Serialize as the JSONB DAO would (MFI-2.2), reload, and assert equality."""
    dumped = api.model_dump()
    rehydrated = CanonicalApi.model_validate(json.loads(json.dumps(dumped)))
    assert rehydrated == api, "model did not survive the JSONB persistence round-trip"
    return rehydrated


def _through_pipeline(api: CanonicalApi) -> CanonicalApi:
    """Run the full normalizer tail (order-normalize, then persist) on ``api``.

    Mirrors what a real :class:`~app.normalizer.Normalizer` does before its model
    is stored, and asserts the two invariants that make the canonical model a
    stable contract:

    * **Idempotence** — ``normalize_ordering`` applied to an already-ordered model
      changes nothing, so the model has a single canonical serialization.
    * **Persistence fidelity** — the ordered model round-trips through JSONB
      unchanged.

    Returns:
        The ordered, round-tripped model, on which callers assert that every
        load-bearing field still holds the value it was built with.
    """
    ordered = normalize_ordering(api)
    assert normalize_ordering(ordered) == ordered, "normalize_ordering is not idempotent"
    return _persist_round_trip(ordered)


def _wrap_type(*types: Type, paradigm: ApiParadigm, fmt: str) -> CanonicalApi:
    """Build a minimal one-artifact :class:`CanonicalApi` carrying ``types``."""
    return CanonicalApi(
        paradigm=paradigm,
        format=fmt,
        identity=ApiIdentity(name="Fixture"),
        types=list(types),
    )


# ===========================================================================
# RPC (gRPC / Protobuf): streaming cardinality + field-number identity
# ===========================================================================


@pytest.mark.parametrize(
    "streaming",
    [
        StreamingMode.NONE,  # unary
        StreamingMode.CLIENT,  # client-streaming
        StreamingMode.SERVER,  # server-streaming
        StreamingMode.BIDIRECTIONAL,  # bidi-streaming
    ],
)
def test_grpc_streaming_mode_survives_pipeline(streaming: StreamingMode) -> None:
    """Every gRPC streaming cardinality is preserved end-to-end.

    The unary/streaming axis is load-bearing: a client cannot call a method with
    the wrong cardinality, so a normalizer that collapses it (or an ordering step
    that perturbs it) would produce an unusable model.
    """
    op = Operation(
        key="acme.EchoService.Echo",
        name="Echo",
        kind=OperationKind.REQUEST_RESPONSE,
        streaming=streaming,
        messages=[
            Message(
                key="acme.EchoService.Echo#request",
                role=MessageRole.REQUEST,
                payload=TypeRef(name="acme.EchoRequest", nullable=False),
            ),
            Message(
                key="acme.EchoService.Echo#response",
                role=MessageRole.RESPONSE,
                payload=TypeRef(name="acme.EchoReply", nullable=False),
            ),
        ],
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="grpc",
        protocol="grpc",
        identity=ApiIdentity(name="Echo", namespace="acme"),
        services=[Service(key="acme.EchoService", name="EchoService", operations=[op])],
    )

    restored = _through_pipeline(api)

    assert restored.operations()[0].streaming is streaming


def test_grpc_field_numbers_survive_and_are_order_independent() -> None:
    """Protobuf field numbers are preserved and pin field identity across ordering.

    A field number is the wire identity of a member; a rename must read as a
    *modify*, not an add+remove, in a diff. ``normalize_ordering`` sorts a record's
    fields by ``key`` (their declaration order is not meaningful), so the field
    *number* — not position — must carry identity, which this asserts by building
    the record with numbers out of positional order.
    """
    msg = Type(
        key="acme.Pet",
        name="Pet",
        kind=TypeKind.RECORD,
        namespace="acme",
        fields=[
            # Declared name-first, then id — but numbered id=1, name=2.
            CanonicalField(
                key="acme.Pet.name",
                name="name",
                type=TypeRef(name="string", nullable=False),
                field_number=2,
            ),
            CanonicalField(
                key="acme.Pet.id",
                name="id",
                type=TypeRef(name="string", nullable=False),
                field_number=1,
            ),
        ],
    )
    restored = _through_pipeline(_wrap_type(msg, paradigm=ApiParadigm.RPC, fmt="grpc"))

    pet = restored.type_by_key("acme.Pet")
    assert pet is not None
    by_name = {f.name: f.field_number for f in pet.fields}
    assert by_name == {"id": 1, "name": 2}


# ===========================================================================
# GraphQL: nullability + list-wrapper fidelity (the [T!]! wrapper stack)
# ===========================================================================


def _ref_str(ref: TypeRef) -> str:
    """Render a :class:`TypeRef` back into GraphQL wrapper syntax (``[T!]!``).

    Inverts :class:`TypeRef`'s wrapper modeling so a round-tripped reference can
    be compared as a string: a list level becomes ``[...]`` and a non-null level
    (``nullable=False``) appends ``!``.
    """
    inner = f"[{_ref_str(ref.item)}]" if ref.is_list() else (ref.name or "?")
    return inner if ref.nullable else inner + "!"


# Each case: the GraphQL type expression and the TypeRef a normalizer must build.
# These are the wrapper permutations a GraphQL field/argument type can take,
# including a doubly-nested list, where every level's nullability is independent
# and load-bearing.
_GRAPHQL_WRAPPERS = [
    ("T", TypeRef(name="T", nullable=True)),
    ("T!", TypeRef(name="T", nullable=False)),
    ("[T]", TypeRef(item=TypeRef(name="T", nullable=True), nullable=True)),
    ("[T!]", TypeRef(item=TypeRef(name="T", nullable=False), nullable=True)),
    ("[T]!", TypeRef(item=TypeRef(name="T", nullable=True), nullable=False)),
    ("[T!]!", TypeRef(item=TypeRef(name="T", nullable=False), nullable=False)),
    (
        "[[T!]!]!",
        TypeRef(
            item=TypeRef(
                item=TypeRef(name="T", nullable=False), nullable=False
            ),
            nullable=False,
        ),
    ),
]


@pytest.mark.parametrize("expr,ref", _GRAPHQL_WRAPPERS, ids=[c[0] for c in _GRAPHQL_WRAPPERS])
def test_graphql_wrapper_nullability_survives_pipeline(expr: str, ref: TypeRef) -> None:
    """Every GraphQL list/non-null wrapper permutation round-trips bit-exact.

    GraphQL nullability is per-wrapper-level (``[T!]`` ≠ ``[T]!`` ≠ ``[T!]!``) and
    each level is a real client contract. The canonical model encodes it as nested
    :class:`TypeRef` with a per-level ``nullable``; this asserts the field both
    survives the pipeline and re-renders to the exact source expression.
    """
    record = Type(
        key="Holder",
        name="Holder",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="Holder.f", name="f", type=ref)],
    )
    restored = _through_pipeline(
        _wrap_type(record, paradigm=ApiParadigm.GRAPH, fmt="graphql")
    )

    field = restored.type_by_key("Holder").fields[0]
    assert field.type == ref
    assert _ref_str(field.type) == expr


def test_graphql_operation_kinds_and_nullable_result() -> None:
    """Query/Mutation/Subscription kinds and a nullable result survive the pipeline."""
    ops = [
        Operation(key="Query.user", name="user", kind=OperationKind.QUERY),
        Operation(key="Mutation.addUser", name="addUser", kind=OperationKind.MUTATION),
        Operation(
            key="Subscription.onUser",
            name="onUser",
            kind=OperationKind.SUBSCRIPTION,
            streaming=StreamingMode.SERVER,
            messages=[
                Message(
                    key="Subscription.onUser#response",
                    role=MessageRole.RESPONSE,
                    # GraphQL fields are nullable unless marked `!`.
                    payload=TypeRef(name="User", nullable=True),
                )
            ],
        ),
    ]
    api = CanonicalApi(
        paradigm=ApiParadigm.GRAPH,
        format="graphql",
        identity=ApiIdentity(name="Blog"),
        services=[Service(key="root", name="root", operations=ops)],
    )

    restored = _through_pipeline(api)

    kinds = {op.name: op.kind for op in restored.operations()}
    assert kinds == {
        "user": OperationKind.QUERY,
        "addUser": OperationKind.MUTATION,
        "onUser": OperationKind.SUBSCRIPTION,
    }
    sub = next(op for op in restored.operations() if op.name == "onUser")
    assert sub.streaming is StreamingMode.SERVER
    assert sub.messages[0].payload.nullable is True


# ===========================================================================
# Event-driven (AsyncAPI): operation action + channel binding fidelity
# ===========================================================================


@pytest.mark.parametrize(
    "action",
    [OperationKind.PUBLISH, OperationKind.SUBSCRIBE],
)
def test_asyncapi_operation_action_and_channel_binding(action: OperationKind) -> None:
    """Both AsyncAPI actions bind to a channel and keep its bindings/parameters.

    The action (send vs receive) flips the meaning of an event operation, and the
    channel carries the wire address, protocol bindings (partitions/qos), and
    address parameters — all load-bearing for an event consumer/producer.
    """
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
        bindings={"kafka": {"partitions": 3, "replicas": 2}},
    )
    op = Operation(
        key="onUserSignedUp",
        name="onUserSignedUp",
        kind=action,
        channel_ref=channel.key,
        messages=[
            Message(
                key="onUserSignedUp#event",
                role=MessageRole.EVENT,
                content_types=["application/json"],
                payload=TypeRef(name="UserSignedUp", nullable=False),
            )
        ],
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3",
        protocol="kafka",
        identity=ApiIdentity(name="Accounts"),
        services=[Service(key="accounts", name="accounts", operations=[op])],
        channels=[channel],
    )

    restored = _through_pipeline(api)

    rop = restored.operations()[0]
    assert rop.kind is action
    # The operation's channel_ref resolves to a declared channel.
    rchan = next(c for c in restored.channels if c.key == rop.channel_ref)
    assert rchan.bindings["kafka"] == {"partitions": 3, "replicas": 2}
    assert rchan.parameters[0].name == "userId"
    assert rop.messages[0].role is MessageRole.EVENT


# ===========================================================================
# Data schema (Avro): defaults (incl. falsy), enum ordinal, union order
# ===========================================================================


# Falsy values a naive normalizer is most likely to drop by truthiness-testing
# `if default:` instead of `if "default" in schema:`. Each must survive verbatim.
_FALSY_DEFAULTS = [0, 0.0, False, "", [], {}]


@pytest.mark.parametrize("default", _FALSY_DEFAULTS, ids=[repr(d) for d in _FALSY_DEFAULTS])
def test_avro_falsy_default_survives_pipeline(default: object) -> None:
    """A field's falsy default (0, False, "", [], {}) is preserved, not dropped.

    Avro defaults are load-bearing for schema-evolution compatibility: a reader
    uses them to fill fields absent from a writer's record. Falsy defaults are the
    classic loss bug (``if default:`` skips them), so each is asserted to survive
    the pipeline with its exact value and type.
    """
    rec = Type(
        key="com.example.Rec",
        name="Rec",
        kind=TypeKind.RECORD,
        namespace="com.example",
        fields=[
            CanonicalField(
                key="com.example.Rec.f",
                name="f",
                type=TypeRef(name="string", nullable=False),
                default=default,
            )
        ],
    )
    restored = _through_pipeline(
        _wrap_type(rec, paradigm=ApiParadigm.DATA_SCHEMA, fmt="avro")
    )

    got = restored.type_by_key("com.example.Rec").fields[0].default
    assert got == default
    assert type(got) is type(default)  # 0 must not become False, etc.


def test_avro_enum_ordinal_order_is_preserved_through_ordering() -> None:
    """Enum value order is preserved — it is the Avro/protobuf ordinal, not noise.

    ``normalize_ordering`` deliberately does *not* sort ``enum_values`` because
    their position is the wire ordinal (and Avro default/compat semantics depend
    on the first symbol). Sorting them would silently break compatibility checks.
    """
    suit = Type(
        key="com.example.Suit",
        name="Suit",
        kind=TypeKind.ENUM,
        namespace="com.example",
        enum_values=[
            EnumValue(key="com.example.Suit.SPADES", name="SPADES", value=0),
            EnumValue(key="com.example.Suit.HEARTS", name="HEARTS", value=1),
            EnumValue(key="com.example.Suit.DIAMONDS", name="DIAMONDS", value=2),
            EnumValue(key="com.example.Suit.CLUBS", name="CLUBS", value=3),
        ],
    )
    restored = _through_pipeline(
        _wrap_type(suit, paradigm=ApiParadigm.DATA_SCHEMA, fmt="avro")
    )

    values = restored.type_by_key("com.example.Suit").enum_values
    assert [v.name for v in values] == ["SPADES", "HEARTS", "DIAMONDS", "CLUBS"]
    assert [v.value for v in values] == [0, 1, 2, 3]


def test_avro_union_member_order_is_preserved_through_ordering() -> None:
    """Union member order is preserved — it is Avro's resolution order.

    For an Avro union the first branch is the default branch and the order drives
    resolution; ``["null", "string"]`` (nullable, defaulting to null) is not the
    same type as ``["string", "null"]``. ``normalize_ordering`` leaves
    ``union_members`` untouched, which this pins.
    """
    union = Type(
        key="com.example.OptString",
        name="OptString",
        kind=TypeKind.UNION,
        namespace="com.example",
        union_members=["null", "string"],
    )
    restored = _through_pipeline(
        _wrap_type(union, paradigm=ApiParadigm.DATA_SCHEMA, fmt="avro")
    )

    assert restored.type_by_key("com.example.OptString").union_members == ["null", "string"]


def test_avro_explicit_null_default_distinguishable_via_extras() -> None:
    """An *explicit* null default is distinguishable from no default via ``extras``.

    ``CanonicalField.default`` is ``Optional[Any]`` defaulting to ``None``, so the
    first-class field cannot by itself tell "default is ``null``" from "no default
    declared". Rather than widen the model, the documented per-entity ``extras``
    escape hatch carries the distinction losslessly — demonstrating the gap named
    by MFI-2.4 ("Avro defaults") is covered without extending MFI-2.1.
    """
    rec = Type(
        key="com.example.Rec",
        name="Rec",
        kind=TypeKind.RECORD,
        namespace="com.example",
        fields=[
            # Explicit `"default": null` on a nullable union field.
            CanonicalField(
                key="com.example.Rec.nick",
                name="nick",
                type=TypeRef(name="string", nullable=True),
                default=None,
                extras={"has_default": True},
            ),
            # No default declared at all.
            CanonicalField(
                key="com.example.Rec.note",
                name="note",
                type=TypeRef(name="string", nullable=True),
                default=None,
            ),
        ],
    )
    restored = _through_pipeline(
        _wrap_type(rec, paradigm=ApiParadigm.DATA_SCHEMA, fmt="avro")
    )

    fields = {f.name: f for f in restored.type_by_key("com.example.Rec").fields}
    assert fields["nick"].default is None and fields["nick"].extras["has_default"] is True
    assert fields["note"].default is None and "has_default" not in fields["note"].extras


# ===========================================================================
# REST (OpenAPI): parameter locations + status/error message fidelity
# ===========================================================================


def test_rest_parameter_locations_and_error_message_survive_pipeline() -> None:
    """REST parameter locations and a declared error response survive the pipeline.

    Where a value is carried (path/query/header/cookie) and which responses are
    errors vs success are load-bearing for REST request shaping and error handling.
    """
    op = Operation(
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
                constraints=Constraints(format="uuid"),
            ),
            Parameter(
                key="GET /pets/{id}#query.verbose",
                name="verbose",
                location=ParameterLocation.QUERY,
                type=TypeRef(name="boolean", nullable=True),
            ),
        ],
        messages=[
            Message(
                key="GET /pets/{id}#response.200",
                role=MessageRole.RESPONSE,
                status_code="200",
                content_types=["application/json"],
                payload=TypeRef(name="Pet", nullable=False),
            ),
            Message(
                key="GET /pets/{id}#response.404",
                role=MessageRole.ERROR,
                status_code="404",
                content_types=["application/problem+json"],
                payload=TypeRef(name="Problem", nullable=False),
            ),
        ],
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        protocol="http",
        identity=ApiIdentity(name="Pet Store"),
        services=[Service(key="pets", name="pets", operations=[op])],
    )

    restored = _through_pipeline(api)

    rop = restored.operations()[0]
    locations = {p.name: p.location for p in rop.parameters}
    assert locations == {
        "id": ParameterLocation.PATH,
        "verbose": ParameterLocation.QUERY,
    }
    roles = {m.status_code: m.role for m in rop.messages}
    assert roles == {"200": MessageRole.RESPONSE, "404": MessageRole.ERROR}


# ===========================================================================
# Cross-cutting: ordering is a stable fingerprint regardless of source order
# ===========================================================================


def _shuffled_pair() -> tuple[CanonicalApi, CanonicalApi]:
    """Two models with identical entities declared in opposite source orders."""
    a = Type(key="A", name="A", kind=TypeKind.SCALAR)
    b = Type(key="B", name="B", kind=TypeKind.SCALAR)
    op1 = Operation(key="GET /a", name="a", kind=OperationKind.REQUEST_RESPONSE)
    op2 = Operation(key="GET /b", name="b", kind=OperationKind.REQUEST_RESPONSE)

    def build(types: list[Type], ops: list[Operation]) -> CanonicalApi:
        return CanonicalApi(
            paradigm=ApiParadigm.REST,
            format="openapi-3.1",
            identity=ApiIdentity(name="Svc"),
            services=[Service(key="s", name="s", operations=ops)],
            types=types,
        )

    return build([a, b], [op1, op2]), build([b, a], [op2, op1])


def test_ordering_yields_identical_fingerprint_regardless_of_source_order() -> None:
    """Two source orderings of the same API normalize to byte-identical JSON.

    This is the property that makes a fingerprint/diff stable: re-importing the
    same document — however the source happens to order its paths and schemas —
    must not look like a change.
    """
    first, second = _shuffled_pair()

    assert first != second  # the inputs really do differ in order
    a_json = normalize_ordering(first).model_dump_json()
    b_json = normalize_ordering(second).model_dump_json()
    assert a_json == b_json


# ===========================================================================
# Gap audit: every named load-bearing field has a first-class canonical home
# ===========================================================================


def test_load_bearing_fields_have_a_canonical_home() -> None:
    """Assert MFI-2.1 still exposes each paradigm's load-bearing field.

    This is the guardrail behind "gaps tracked back into 2.1": each entry names a
    paradigm field the AC calls load-bearing and the canonical attribute that must
    hold it. If a future change to the model drops or renames one of these, this
    test fails and points straight at the gap to file against MFI-2.1.
    """
    required = {
        Operation: ["streaming", "kind", "channel_ref", "http_method", "http_path"],
        CanonicalField: ["field_number", "default", "type", "constraints"],
        TypeRef: ["name", "item", "nullable"],  # GraphQL wrapper stack
        Type: ["enum_values", "union_members", "kind", "namespace"],
        Channel: ["address", "protocol", "parameters", "bindings"],
        Message: ["role", "status_code", "content_types", "payload"],
        Parameter: ["location", "required"],
    }
    for model, fields in required.items():
        for field in fields:
            assert field in model.model_fields, (
                f"MFI-2.1 gap: {model.__name__}.{field} is load-bearing for a "
                f"paradigm but is no longer on the canonical model"
            )
