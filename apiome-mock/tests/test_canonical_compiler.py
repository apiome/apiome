"""Tests for canonical mock compiler (SIM-4.4)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.asyncapi_normalizer import AsyncApiNormalizer
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
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

from apiome_mock.canonical_compiler import compile_canonical_spec
from apiome_mock.canonical_loader import LoadedCanonicalSpec


def _loaded(api: CanonicalApi) -> LoadedCanonicalSpec:
    return LoadedCanonicalSpec(
        revision_id=uuid4(),
        tenant_slug="demo",
        project_slug="events",
        version_label="1.0.0",
        updated_at=datetime.now(timezone.utc),
        api=api,
        source_format=api.format,
    )


def test_event_channels_compile_from_asyncapi_fixture() -> None:
    doc = {
        "asyncapi": "3.0.0",
        "info": {"title": "User Service", "version": "1.2.3"},
        "channels": {
            "userSignedUp": {
                "address": "user/signedup",
                "messages": {
                    "UserSignedUp": {
                        "payload": {
                            "type": "object",
                            "properties": {"userId": {"type": "string"}},
                        }
                    }
                },
            }
        },
        "operations": {
            "onUserSignedUp": {
                "action": "receive",
                "channel": {"$ref": "#/channels/userSignedUp"},
                "messages": [{"$ref": "#/channels/userSignedUp/messages/UserSignedUp"}],
            }
        },
    }
    api = AsyncApiNormalizer().normalize(doc)
    compiled = compile_canonical_spec(_loaded(api))
    assert len(compiled.event_channels) == 1
    route = compiled.event_channels[0]
    assert route.key == "user/signedup"
    assert len(route.subscribe_operations) == 1
    assert route.supports_websocket is True
    assert route.supports_sse is True


def test_grpc_methods_compile_from_rpc_model() -> None:
    user = Type(
        key="echo.v1.User",
        name="User",
        kind=TypeKind.RECORD,
        fields=[],
    )
    service = Service(
        key="echo.v1.EchoService",
        name="EchoService",
        operations=[
            Operation(
                key="echo.v1.EchoService.Echo",
                name="Echo",
                kind=OperationKind.REQUEST_RESPONSE,
                streaming=StreamingMode.SERVER,
                messages=[
                    Message(
                        key="echo.v1.EchoService.Echo#request",
                        role=MessageRole.REQUEST,
                        payload=TypeRef(name="echo.v1.User"),
                    ),
                    Message(
                        key="echo.v1.EchoService.Echo#response",
                        role=MessageRole.RESPONSE,
                        payload=TypeRef(name="echo.v1.User"),
                    ),
                ],
            )
        ],
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        identity=ApiIdentity(name="echo", namespace="echo.v1"),
        services=[service],
        types=[user],
    )
    compiled = compile_canonical_spec(_loaded(api))
    assert len(compiled.grpc_methods) == 1
    assert compiled.grpc_methods[0].method_name == "Echo"
    assert compiled.grpc_methods[0].streaming is StreamingMode.SERVER
