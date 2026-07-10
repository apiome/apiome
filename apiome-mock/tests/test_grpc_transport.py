"""Tests for gRPC mock transport helpers (SIM-4.4)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

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
    Type,
    TypeKind,
    TypeRef,
)

from apiome_mock.canonical_compiler import compile_canonical_spec
from apiome_mock.canonical_loader import LoadedCanonicalSpec
from apiome_mock.message_resolver import resolve_message_body
from apiome_mock.proto_descriptor_builder import build_descriptor_set


def _rpc_loaded() -> LoadedCanonicalSpec:
    user = Type(
        key="echo.v1.User",
        name="User",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(
                key="echo.v1.User.name",
                name="name",
                type=TypeRef(name="string"),
                field_number=1,
            )
        ],
    )
    service = Service(
        key="echo.v1.EchoService",
        name="EchoService",
        operations=[
            Operation(
                key="echo.v1.EchoService.Echo",
                name="Echo",
                kind=OperationKind.REQUEST_RESPONSE,
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
    return LoadedCanonicalSpec(
        revision_id=uuid4(),
        tenant_slug="demo",
        project_slug="echo",
        version_label="1.0.0",
        updated_at=datetime.now(timezone.utc),
        api=api,
        source_format="protobuf",
    )


def test_descriptor_set_and_response_synthesis_round_trip() -> None:
    loaded = _rpc_loaded()
    compiled = compile_canonical_spec(loaded)
    raw = build_descriptor_set(compiled.api)
    assert raw
    route = compiled.grpc_methods[0]
    response_message = route.operation.messages[1]
    resolved = resolve_message_body(compiled.api, response_message, seed=3)
    assert resolved.validation_error is None
    assert isinstance(resolved.body, dict)
