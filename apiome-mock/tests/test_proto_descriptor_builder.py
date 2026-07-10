"""Tests for protobuf descriptor builder (SIM-4.4)."""

from __future__ import annotations

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
from google.protobuf import descriptor_pb2

from apiome_mock.proto_descriptor_builder import build_descriptor_set, service_full_names


def _echo_api() -> CanonicalApi:
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
    return CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        identity=ApiIdentity(name="echo", namespace="echo.v1"),
        services=[service],
        types=[user],
    )


def test_build_descriptor_set_contains_service_and_messages() -> None:
    raw = build_descriptor_set(_echo_api())
    fds = descriptor_pb2.FileDescriptorSet()
    fds.ParseFromString(raw)
    assert len(fds.file) == 1
    file_proto = fds.file[0]
    assert file_proto.package == "echo.v1"
    assert {service.name for service in file_proto.service} == {"EchoService"}
    assert {message.name for message in file_proto.message_type} == {"User"}
    assert service_full_names(_echo_api()) == ("echo.v1.EchoService",)
