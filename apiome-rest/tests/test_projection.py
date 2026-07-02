"""Tests for the paradigm projection strategies — MFI-22.2 (#4003).

Exercises the acceptance criterion: each paradigm projection produces a *valid*
OpenAPI 3.1 document on a fixture and reports its ``inferred``/``n/a`` loss set, with
subscriptions/streaming/pub-sub surfaced as losses rather than silently dropped. Both
layers are covered — the projection strategies directly (route resolution + loss
recording) and end-to-end through :class:`~app.openapi_emitter.OpenApiEmitter` with the
emitted document validated against the OpenAPI 3.1 meta-schema.
"""

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
from app.emitter import LossKind, LossTracker
from app.openapi_emitter import OpenApiEmitter
from app.openapi_validator import validate_openapi_document
from app.projection import (
    EVENT_CAVEAT,
    GRAPHQL_ROOT_PATH,
    X_EVENT_ACTION,
    X_FIDELITY,
    X_STREAMING,
    DataSchemaProjection,
    EventProjection,
    GraphProjection,
    ProjectionStrategy,
    RestProjection,
    RouteBinding,
    RpcProjection,
    get_projection,
    register_projection,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _op(key: str, name: str, **kwargs) -> Operation:
    """Build an Operation with a REQUEST_RESPONSE default kind."""
    kwargs.setdefault("kind", OperationKind.REQUEST_RESPONSE)
    return Operation(key=key, name=name, **kwargs)


def _svc(key: str, name: str, operations) -> Service:
    return Service(key=key, name=name, operations=operations)


def _route(strategy: ProjectionStrategy, operation: Operation, service: Service):
    """Run one strategy's ``route`` and return ``(binding, losses)``."""
    tracker = LossTracker()
    binding = strategy.route(operation, service, tracker)
    return binding, tracker.records()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_every_paradigm_resolves_to_its_strategy() -> None:
    assert isinstance(get_projection(ApiParadigm.REST), RestProjection)
    assert isinstance(get_projection(ApiParadigm.RPC), RpcProjection)
    assert isinstance(get_projection(ApiParadigm.GRAPH), GraphProjection)
    assert isinstance(get_projection(ApiParadigm.EVENT), EventProjection)
    assert isinstance(get_projection(ApiParadigm.DATA_SCHEMA), DataSchemaProjection)


def test_register_rejects_a_conflicting_paradigm() -> None:
    with pytest.raises(ValueError, match="already registered"):

        class Clashing(ProjectionStrategy, register=True):
            paradigm = ApiParadigm.REST  # already RestProjection's


def test_register_rejects_a_strategy_without_a_paradigm() -> None:
    class NoParadigm(ProjectionStrategy):
        pass

    with pytest.raises(ValueError, match="must set a `paradigm`"):
        register_projection(NoParadigm)


# ---------------------------------------------------------------------------
# REST projection (the identity / best-effort default)
# ---------------------------------------------------------------------------


def test_rest_uses_the_operations_own_binding_as_source() -> None:
    operation = _op("GET /pets", "list", http_method="GET", http_path="/pets")
    binding, losses = _route(RestProjection(), operation, _svc("s", "s", []))
    assert binding == RouteBinding(method="get", path="/pets", from_source=True)
    assert losses == []  # a source binding is not a loss


def test_rest_synthesizes_a_post_binding_when_absent_and_records_it() -> None:
    operation = _op("acme.Svc.Do", "Do")  # no http_method/http_path
    binding, losses = _route(RestProjection(), operation, _svc("s", "s", []))
    assert binding.method == "post"
    assert binding.path == "/acme.Svc.Do"
    assert binding.from_source is False
    assert [(loss.kind, loss.subject, loss.pointer) for loss in losses] == [
        (LossKind.INFERRED, "synthesized-http-binding", "acme.Svc.Do")
    ]


# ---------------------------------------------------------------------------
# RPC projection
# ---------------------------------------------------------------------------


def test_rpc_synthesizes_service_method_path_when_no_http_annotation() -> None:
    operation = _op("acme.PetService.GetPet", "GetPet")
    service = _svc("acme.PetService", "PetService", [operation])
    binding, losses = _route(RpcProjection(), operation, service)
    # gRPC-transcoding convention: POST /{package.Service}/{Method}.
    assert binding == RouteBinding(
        method="post", path="/acme.PetService/GetPet", from_source=False
    )
    assert any(loss.kind is LossKind.INFERRED and loss.subject == "synthesized-http-binding" for loss in losses)


@pytest.mark.parametrize(
    "http_extra",
    [
        {"method": "get", "path": "/v1/pets/{id}"},  # normalized shape
        {"method": "GET", "uri": "/v1/pets/{id}"},  # Smithy `http` trait (uri, mixed case)
        {"get": "/v1/pets/{id}"},  # google.api.http `{verb: path}` shape
    ],
)
def test_rpc_honors_an_http_annotation_from_extras(http_extra) -> None:
    operation = _op("acme.PetService.GetPet", "GetPet", extras={"http": http_extra})
    service = _svc("acme.PetService", "PetService", [operation])
    binding, losses = _route(RpcProjection(), operation, service)
    assert binding == RouteBinding(method="get", path="/v1/pets/{id}", from_source=True)
    # A source binding is not synthesized, so no inferred-binding loss.
    assert not any(loss.subject == "synthesized-http-binding" for loss in losses)


def test_rpc_flags_streaming_as_extension_and_loss() -> None:
    operation = _op(
        "acme.Chat.Stream", "Stream", streaming=StreamingMode.BIDIRECTIONAL
    )
    service = _svc("acme.Chat", "Chat", [operation])
    binding, losses = _route(RpcProjection(), operation, service)
    assert binding.extensions == {X_STREAMING: "bidirectional"}
    na = [loss for loss in losses if loss.kind is LossKind.NA]
    assert [loss.subject for loss in na] == ["rpc-streaming"]
    assert na[0].pointer == "acme.Chat.Stream"


# ---------------------------------------------------------------------------
# GraphQL projection (SOFA-style)
# ---------------------------------------------------------------------------


def test_graphql_query_projects_to_get_and_mutation_to_post() -> None:
    query = _op("Query.user", "user", kind=OperationKind.QUERY)
    mutation = _op("Mutation.add", "add", kind=OperationKind.MUTATION)
    strategy = GraphProjection()
    q_binding, _ = _route(strategy, query, _svc("Query", "Query", []))
    m_binding, _ = _route(strategy, mutation, _svc("Mutation", "Mutation", []))
    assert q_binding.method == "get"
    assert q_binding.path == f"{GRAPHQL_ROOT_PATH}/user"
    assert m_binding.method == "post"
    assert m_binding.path == f"{GRAPHQL_ROOT_PATH}/add"


def test_graphql_subscription_is_not_emitted_and_is_reported_as_na() -> None:
    subscription = _op(
        "Subscription.onUser",
        "onUser",
        kind=OperationKind.SUBSCRIPTION,
        streaming=StreamingMode.SERVER,
    )
    binding, losses = _route(
        GraphProjection(), subscription, _svc("Subscription", "Subscription", [])
    )
    assert binding is None  # no OpenAPI representation → not emitted
    assert [(loss.kind, loss.subject, loss.pointer) for loss in losses] == [
        (LossKind.NA, "graphql-subscription", "Subscription.onUser")
    ]


# ---------------------------------------------------------------------------
# Event projection (explicitly low-fidelity)
# ---------------------------------------------------------------------------


def test_event_operation_becomes_a_non_normative_path_with_action_and_loss() -> None:
    operation = _op(
        "send user/signedup pub",
        "pub",
        kind=OperationKind.PUBLISH,
        channel_ref="user/signedup",
    )
    binding, losses = _route(EventProjection(), operation, _svc("app", "app", []))
    assert binding.method == "post"
    # Channel address (readable) + operation-name segment (unique per operation, so
    # two operations on one channel do not collide on a single POST /{channel}).
    assert binding.path == "/user/signedup/pub"
    assert binding.extensions == {X_EVENT_ACTION: "publish"}
    assert [(loss.kind, loss.subject) for loss in losses] == [
        (LossKind.NA, "event-pubsub-action")
    ]


def test_event_operations_on_one_channel_do_not_collide() -> None:
    publish = _op(
        "pub op", "onPublish", kind=OperationKind.PUBLISH, channel_ref="orders"
    )
    subscribe = _op(
        "sub op", "onReceive", kind=OperationKind.SUBSCRIBE, channel_ref="orders"
    )
    strategy = EventProjection()
    pub_binding, _ = _route(strategy, publish, _svc("app", "app", []))
    sub_binding, _ = _route(strategy, subscribe, _svc("app", "app", []))
    assert pub_binding.path != sub_binding.path
    assert pub_binding.path == "/orders/onPublish"
    assert sub_binding.path == "/orders/onReceive"


def test_event_document_extensions_caveat_and_channel_binding_loss() -> None:
    api = CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3",
        identity=ApiIdentity(name="E"),
        channels=[
            Channel(key="user/signedup", address="user/signedup", bindings={"kafka": {"partitions": 3}}),
            Channel(key="user/deleted", address="user/deleted"),  # no bindings → no loss
        ],
    )
    tracker = LossTracker()
    extensions = EventProjection().document_extensions(api, tracker)
    fidelity = extensions[X_FIDELITY]
    assert fidelity["fidelity"] == "low"
    assert fidelity["recommended-mode"] == "schemas-only"
    assert fidelity["caveat"] == EVENT_CAVEAT
    binding_losses = [loss for loss in tracker.records() if loss.subject == "event-channel-bindings"]
    assert [loss.pointer for loss in binding_losses] == ["user/signedup"]


# ---------------------------------------------------------------------------
# Data-schema projection
# ---------------------------------------------------------------------------


def test_data_schema_with_a_service_gets_a_best_effort_binding() -> None:
    operation = _op("com.acme.Do", "Do")
    binding, losses = _route(
        DataSchemaProjection(), operation, _svc("com.acme", "acme", [operation])
    )
    assert binding.method == "post"
    assert binding.path == "/com.acme.Do"
    assert any(loss.subject == "synthesized-http-binding" for loss in losses)


# ---------------------------------------------------------------------------
# LossTracker determinism
# ---------------------------------------------------------------------------


def test_loss_tracker_sorts_records_deterministically() -> None:
    tracker = LossTracker()
    tracker.record(LossKind.NA, "z-subject", "detail", pointer="p2")
    tracker.record(LossKind.INFERRED, "a-subject", "detail", pointer="p1")
    tracker.record(LossKind.NA, "a-subject", "detail", pointer="p0")
    keys = [(loss.kind.value, loss.subject, loss.pointer) for loss in tracker.records()]
    assert keys == [
        ("inferred", "a-subject", "p1"),
        ("n/a", "a-subject", "p0"),
        ("n/a", "z-subject", "p2"),
    ]


# ---------------------------------------------------------------------------
# End-to-end acceptance: valid doc + reported losses, per paradigm
# ---------------------------------------------------------------------------


def _graphql_model() -> CanonicalApi:
    return CanonicalApi(
        paradigm=ApiParadigm.GRAPH,
        format="graphql",
        identity=ApiIdentity(name="Graph"),
        version="1",
        services=[
            _svc(
                "Query",
                "Query",
                [
                    _op(
                        "Query.user",
                        "user",
                        kind=OperationKind.QUERY,
                        parameters=[
                            Parameter(
                                key="Query.user#arg.id",
                                name="id",
                                location=ParameterLocation.QUERY,
                                type=TypeRef(name="string", nullable=False),
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
                ],
            ),
            _svc(
                "Subscription",
                "Subscription",
                [
                    _op(
                        "Subscription.onUser",
                        "onUser",
                        kind=OperationKind.SUBSCRIPTION,
                        streaming=StreamingMode.SERVER,
                    )
                ],
            ),
        ],
        types=[
            Type(
                key="User",
                name="User",
                kind=TypeKind.RECORD,
                fields=[
                    CanonicalField(
                        key="User.id",
                        name="id",
                        type=TypeRef(name="string", nullable=False),
                    )
                ],
            )
        ],
    )


def _event_model() -> CanonicalApi:
    return CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3",
        identity=ApiIdentity(name="Event"),
        version="1",
        channels=[
            Channel(
                key="user/signedup",
                address="user/signedup",
                bindings={"kafka": {"partitions": 3}},
            )
        ],
        services=[
            _svc(
                "app",
                "app",
                [
                    _op(
                        "receive user/signedup onUp",
                        "onUp",
                        kind=OperationKind.SUBSCRIBE,
                        channel_ref="user/signedup",
                        messages=[
                            Message(
                                key="m",
                                role=MessageRole.EVENT,
                                payload=TypeRef(name="UserSignedUp", nullable=False),
                            )
                        ],
                    )
                ],
            )
        ],
        types=[
            Type(
                key="UserSignedUp",
                name="UserSignedUp",
                kind=TypeKind.RECORD,
                fields=[
                    CanonicalField(
                        key="UserSignedUp.id",
                        name="id",
                        type=TypeRef(name="string", nullable=False),
                    )
                ],
            )
        ],
    )


def test_graphql_end_to_end_valid_document_and_losses() -> None:
    result = OpenApiEmitter().emit(_graphql_model())
    assert validate_openapi_document(result.document) == []
    # Query is a GET under the SOFA root; the subscription is absent from paths.
    assert set(result.document["paths"]) == {f"{GRAPHQL_ROOT_PATH}/user"}
    assert "get" in result.document["paths"][f"{GRAPHQL_ROOT_PATH}/user"]
    # The subscription loss is surfaced (n/a), not silently dropped.
    assert any(
        loss.kind is LossKind.NA and loss.subject == "graphql-subscription"
        for loss in result.losses
    )


def test_event_end_to_end_valid_document_and_low_fidelity_note() -> None:
    result = OpenApiEmitter().emit(_event_model())
    assert validate_openapi_document(result.document) == []
    # Payloads are faithful in components even though the paths are non-normative.
    assert "UserSignedUp" in result.document["components"]["schemas"]
    assert result.document[X_FIDELITY]["recommended-mode"] == "schemas-only"
    op = result.document["paths"]["/user/signedup/onUp"]["post"]
    assert op[X_EVENT_ACTION] == "subscribe"
    subjects = {loss.subject for loss in result.losses}
    assert {"event-pubsub-action", "event-channel-bindings"} <= subjects


def test_emitted_losses_are_deterministic() -> None:
    model = _event_model()
    first = OpenApiEmitter().emit(model)
    second = OpenApiEmitter().emit(model)
    assert first.model_dump() == second.model_dump()  # document + provenance + losses


def test_rest_projection_incurs_no_losses_on_a_clean_rest_model() -> None:
    model = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="R"),
        version="1",
        services=[
            _svc(
                "default",
                "default",
                [_op("GET /ping", "ping", http_method="GET", http_path="/ping")],
            )
        ],
    )
    result = OpenApiEmitter().emit(model)
    assert validate_openapi_document(result.document) == []
    assert result.losses == []  # a native REST model converts losslessly
