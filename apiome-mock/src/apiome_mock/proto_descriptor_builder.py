"""Build protobuf FileDescriptorSets from canonical RPC models (SIM-4.4)."""

from __future__ import annotations

from typing import Dict, Tuple

from app.canonical_model import (
    CanonicalApi,
    CanonicalField,
    MessageRole,
    OperationKind,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from google.protobuf import descriptor_pb2

_FD = descriptor_pb2.FieldDescriptorProto

_SCALAR_MAP: Dict[str, int] = {
    "double": _FD.TYPE_DOUBLE,
    "float": _FD.TYPE_FLOAT,
    "int32": _FD.TYPE_INT32,
    "int64": _FD.TYPE_INT64,
    "uint32": _FD.TYPE_UINT32,
    "uint64": _FD.TYPE_UINT64,
    "sint32": _FD.TYPE_SINT32,
    "sint64": _FD.TYPE_SINT64,
    "fixed32": _FD.TYPE_FIXED32,
    "fixed64": _FD.TYPE_FIXED64,
    "sfixed32": _FD.TYPE_SFIXED32,
    "sfixed64": _FD.TYPE_SFIXED64,
    "bool": _FD.TYPE_BOOL,
    "boolean": _FD.TYPE_BOOL,
    "string": _FD.TYPE_STRING,
    "bytes": _FD.TYPE_BYTES,
}


def _package_name(api: CanonicalApi) -> str:
    namespace = api.identity.namespace or api.identity.name
    return namespace.replace("/", ".").strip(".") or "apiome.mock"


def _message_name(type_key: str) -> str:
    return type_key.rsplit(".", 1)[-1]


def _type_name(type_key: str, package: str) -> str:
    if type_key.startswith(f"{package}."):
        return f".{type_key}"
    return f".{package}.{_message_name(type_key)}"


def _resolve_type_key(api: CanonicalApi, type_ref: TypeRef) -> str | None:
    if type_ref.name is None:
        return None
    if api.type_by_key(type_ref.name) is not None:
        return type_ref.name
    for candidate in api.types:
        if candidate.name == type_ref.name or candidate.key.endswith(f".{type_ref.name}"):
            return candidate.key
    return None


def _add_field(
    message: descriptor_pb2.DescriptorProto,
    field: CanonicalField,
    *,
    package: str,
    api: CanonicalApi,
) -> None:
    proto_field = message.field.add()
    proto_field.name = field.name
    proto_field.number = field.field_number or (len(message.field) + 1)
    proto_field.label = _FD.LABEL_OPTIONAL

    type_ref = field.type
    if type_ref.is_list():
        proto_field.label = _FD.LABEL_REPEATED
        assert type_ref.item is not None
        type_ref = type_ref.item

    scalar = _SCALAR_MAP.get((type_ref.name or "").lower())
    if scalar is not None:
        proto_field.type = scalar
        return

    type_key = _resolve_type_key(api, type_ref)
    if type_key is not None:
        named = api.type_by_key(type_key)
        if named is not None and named.kind is TypeKind.ENUM:
            proto_field.type = _FD.TYPE_ENUM
            proto_field.type_name = _type_name(type_key, package)
            return
        proto_field.type = _FD.TYPE_MESSAGE
        proto_field.type_name = _type_name(type_key, package)
        return

    proto_field.type = _FD.TYPE_STRING


def _add_enum(file_proto: descriptor_pb2.FileDescriptorProto, type_: Type) -> None:
    enum_proto = file_proto.enum_type.add()
    enum_proto.name = _message_name(type_.key)
    for index, value in enumerate(type_.enum_values):
        enum_value = enum_proto.value.add()
        enum_value.name = value.name
        enum_value.number = int(value.value) if value.value is not None else index


def _add_message(
    file_proto: descriptor_pb2.FileDescriptorProto,
    type_: Type,
    *,
    package: str,
    api: CanonicalApi,
) -> None:
    message = file_proto.message_type.add()
    message.name = _message_name(type_.key)
    for field in type_.fields:
        _add_field(message, field, package=package, api=api)



def build_descriptor_set(api: CanonicalApi) -> bytes:
    """Compile a canonical RPC model into a protobuf FileDescriptorSet."""
    package = _package_name(api)
    fds = descriptor_pb2.FileDescriptorSet()
    file_proto = fds.file.add()
    file_proto.name = f"{package.replace('.', '/')}.proto"
    file_proto.package = package
    file_proto.syntax = "proto3"

    for type_ in api.types:
        if type_.kind is TypeKind.ENUM:
            _add_enum(file_proto, type_)
        elif type_.kind is TypeKind.RECORD:
            _add_message(file_proto, type_, package=package, api=api)

    for service in api.services:
        service_proto = file_proto.service.add()
        service_proto.name = service.name
        for operation in service.operations:
            if operation.kind not in {OperationKind.REQUEST_RESPONSE, OperationKind.ONE_WAY}:
                continue
            method = service_proto.method.add()
            method.name = operation.name.rsplit(".", 1)[-1]

            request_key = next(
                (
                    message.payload.name if message.payload else None
                    for message in operation.messages
                    if message.role is MessageRole.REQUEST
                ),
                None,
            )
            response_key = next(
                (
                    message.payload.name if message.payload else None
                    for message in operation.messages
                    if message.role is MessageRole.RESPONSE
                ),
                None,
            )

            if request_key:
                resolved = _resolve_type_key(api, TypeRef(name=request_key)) or request_key
                method.input_type = _type_name(resolved, package)
            else:
                method.input_type = ".google.protobuf.Empty"

            if response_key:
                resolved = _resolve_type_key(api, TypeRef(name=response_key)) or response_key
                method.output_type = _type_name(resolved, package)
            else:
                method.output_type = ".google.protobuf.Empty"

            if operation.streaming is StreamingMode.CLIENT:
                method.client_streaming = True
            elif operation.streaming is StreamingMode.SERVER:
                method.server_streaming = True
            elif operation.streaming is StreamingMode.BIDIRECTIONAL:
                method.client_streaming = True
                method.server_streaming = True

    return fds.SerializeToString()


def service_full_names(api: CanonicalApi) -> Tuple[str, ...]:
    """Return fully-qualified gRPC service names for reflection registration."""
    package = _package_name(api)
    return tuple(f"{package}.{service.name}" for service in api.services)
