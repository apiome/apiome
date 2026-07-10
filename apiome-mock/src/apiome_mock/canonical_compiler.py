"""Compile canonical API models into multi-protocol mock routing tables (SIM-4.4)."""

from __future__ import annotations

from dataclasses import dataclass

from app.canonical_model import (
    ApiParadigm,
    CanonicalApi,
    Channel,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    StreamingMode,
)

from apiome_mock.canonical_loader import LoadedCanonicalSpec

_WS_PROTOCOLS = frozenset({"ws", "websocket", "wss"})
_SSE_PROTOCOLS = frozenset({"sse", "http", "https"})


@dataclass(frozen=True)
class EventChannelRoute:
    """One event channel exposed over WebSocket and/or SSE."""

    key: str
    address: str
    subscribe_operations: tuple[Operation, ...]
    publish_operations: tuple[Operation, ...]
    supports_websocket: bool
    supports_sse: bool
    periodic_interval_seconds: float


@dataclass(frozen=True)
class GrpcMethodRoute:
    """One gRPC method the mock server can answer."""

    service_key: str
    service_name: str
    method_name: str
    operation: Operation
    request_message_key: str | None
    response_message_key: str | None
    streaming: StreamingMode


@dataclass(frozen=True)
class CompiledCanonicalSpec:
    """Routing tables compiled from a canonical API model."""

    loaded: LoadedCanonicalSpec
    event_channels: tuple[EventChannelRoute, ...]
    grpc_methods: tuple[GrpcMethodRoute, ...]

    @property
    def cache_key(self) -> tuple[str, str, str]:
        return self.loaded.cache_key

    @property
    def api(self) -> CanonicalApi:
        return self.loaded.api

    @property
    def paradigm(self) -> ApiParadigm:
        return self.loaded.paradigm


def _channel_transport_flags(channel: Channel, api: CanonicalApi) -> tuple[bool, bool]:
    bindings = channel.bindings or {}
    binding_keys = {key.lower() for key in bindings}
    protocol = (channel.protocol or api.protocol or "").lower()

    ws = bool(binding_keys & _WS_PROTOCOLS) or protocol in _WS_PROTOCOLS
    sse = bool(binding_keys & _SSE_PROTOCOLS) or protocol in _SSE_PROTOCOLS

    if not ws and not sse:
        # Event mocks over HTTP-family transports when bindings are absent (kafka/mqtt specs).
        ws = True
        sse = True
    return ws, sse


def _event_messages(operation: Operation) -> tuple[Message, ...]:
    return tuple(msg for msg in operation.messages if msg.role is MessageRole.EVENT)


def _grpc_message_key(operation: Operation, role: MessageRole) -> str | None:
    for message in operation.messages:
        if message.role is role:
            if message.payload is not None and message.payload.name:
                return message.payload.name
            return message.key
    return None


def _compile_event_channels(api: CanonicalApi) -> tuple[EventChannelRoute, ...]:
    channel_map = {channel.key: channel for channel in api.channels}
    subscribe_by_channel: dict[str, list[Operation]] = {}
    publish_by_channel: dict[str, list[Operation]] = {}

    for operation in api.operations():
        channel_ref = operation.channel_ref
        if not channel_ref:
            continue
        if operation.kind is OperationKind.SUBSCRIBE:
            subscribe_by_channel.setdefault(channel_ref, []).append(operation)
        elif operation.kind is OperationKind.PUBLISH:
            publish_by_channel.setdefault(channel_ref, []).append(operation)

    routes: list[EventChannelRoute] = []
    for channel in api.channels:
        ws, sse = _channel_transport_flags(channel, api)
        routes.append(
            EventChannelRoute(
                key=channel.key,
                address=channel.address,
                subscribe_operations=tuple(subscribe_by_channel.get(channel.key, ())),
                publish_operations=tuple(publish_by_channel.get(channel.key, ())),
                supports_websocket=ws,
                supports_sse=sse,
                periodic_interval_seconds=2.0,
            )
        )

    for channel_key in set(subscribe_by_channel) | set(publish_by_channel):
        if channel_key in channel_map:
            continue
        routes.append(
            EventChannelRoute(
                key=channel_key,
                address=channel_key,
                subscribe_operations=tuple(subscribe_by_channel.get(channel_key, ())),
                publish_operations=tuple(publish_by_channel.get(channel_key, ())),
                supports_websocket=True,
                supports_sse=True,
                periodic_interval_seconds=2.0,
            )
        )

    return tuple(sorted(routes, key=lambda route: route.key))


def _compile_grpc_methods(api: CanonicalApi) -> tuple[GrpcMethodRoute, ...]:
    routes: list[GrpcMethodRoute] = []
    for service in api.services:
        for operation in service.operations:
            if operation.kind is not OperationKind.REQUEST_RESPONSE and operation.kind is not OperationKind.ONE_WAY:
                continue
            method_name = operation.name.rsplit(".", 1)[-1]
            routes.append(
                GrpcMethodRoute(
                    service_key=service.key,
                    service_name=service.name,
                    method_name=method_name,
                    operation=operation,
                    request_message_key=_grpc_message_key(operation, MessageRole.REQUEST),
                    response_message_key=_grpc_message_key(operation, MessageRole.RESPONSE),
                    streaming=operation.streaming,
                )
            )
    return tuple(routes)


def compile_canonical_spec(loaded: LoadedCanonicalSpec) -> CompiledCanonicalSpec:
    """Build transport routing tables from a loaded canonical model."""
    event_channels: tuple[EventChannelRoute, ...] = ()
    grpc_methods: tuple[GrpcMethodRoute, ...] = ()

    if loaded.paradigm is ApiParadigm.EVENT:
        event_channels = _compile_event_channels(loaded.api)
    elif loaded.paradigm is ApiParadigm.RPC:
        grpc_methods = _compile_grpc_methods(loaded.api)

    return CompiledCanonicalSpec(
        loaded=loaded,
        event_channels=event_channels,
        grpc_methods=grpc_methods,
    )
