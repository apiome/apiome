"""gRPC reflection mock transport for canonical RPC models (SIM-4.4)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import grpc
import structlog
from app.canonical_model import MessageRole, StreamingMode
from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory
from google.protobuf.message import Message
from grpc_reflection.v1alpha import reflection
from psycopg_pool import AsyncConnectionPool

from apiome_mock.api_key import ValidatedApiKey, validate_api_key_for_tenant
from apiome_mock.canonical_compiler import CompiledCanonicalSpec, GrpcMethodRoute, compile_canonical_spec
from apiome_mock.canonical_loader import get_canonical_access_status, load_canonical_spec
from apiome_mock.canonical_spec_cache import CanonicalSpecCache
from apiome_mock.guard import enforce_mock_limits_for_context, record_mock_transport_event, resolve_limits_for_tenant
from apiome_mock.message_resolver import resolve_message_body
from apiome_mock.proto_descriptor_builder import build_descriptor_set
from apiome_mock.settings import Settings

_log = structlog.get_logger(__name__)

_METADATA_TENANT = "x-apiome-tenant"
_METADATA_PROJECT = "x-apiome-project"
_METADATA_VERSION = "x-apiome-version"
_METADATA_API_KEY = "x-api-key"
_STREAM_BOUND = 3


@dataclass(frozen=True)
class _GrpcRouteKey:
    tenant: str
    project: str
    version: str


class GrpcMockRuntime:
    """Multi-tenant gRPC mock runtime with reflection and metadata routing."""

    def __init__(self, *, pool: AsyncConnectionPool, cache: CanonicalSpecCache, settings: Settings) -> None:
        self._pool = pool
        self._cache = cache
        self._settings = settings
        self._server: grpc.aio.Server | None = None
        self._registered_services: set[str] = set()

    async def start(self) -> None:
        if not self._settings.grpc_enabled:
            return
        self._server = grpc.aio.server()
        self._server.add_generic_rpc_handlers((self._build_generic_handler(),))
        reflection.enable_server_reflection((reflection.SERVICE_NAME,), self._server)
        listen = f"{self._settings.grpc_host}:{self._settings.grpc_port}"
        self._server.add_insecure_port(listen)
        await self._server.start()
        _log.info("grpc_mock_server_started", listen=listen)

    async def stop(self) -> None:
        if self._server is None:
            return
        await self._server.stop(grace=1.0)
        self._server = None

    def _build_generic_handler(self) -> grpc.GenericRpcHandler:
        runtime = self

        class _Handler(grpc.GenericRpcHandler):
            def service(self, handler_call_details: grpc.HandlerCallDetails) -> grpc.RpcMethodHandler | None:
                method_path = handler_call_details.method or ""
                if method_path.startswith("/grpc.reflection."):
                    return None
                parts = method_path.strip("/").split("/")
                if len(parts) != 2:
                    return None
                service_name, method_name = parts
                route = runtime._lookup_route(handler_call_details, service_name=service_name, method_name=method_name)
                if route is None:
                    return None
                if route.operation.streaming is StreamingMode.SERVER:
                    return grpc.unary_stream_rpc_method_handler(
                        runtime._unary_stream_handler(service_name, method_name),
                    )
                if route.operation.streaming is StreamingMode.CLIENT:
                    return grpc.stream_unary_rpc_method_handler(
                        runtime._stream_unary_handler(service_name, method_name),
                    )
                if route.operation.streaming is StreamingMode.BIDIRECTIONAL:
                    return grpc.stream_stream_rpc_method_handler(
                        runtime._stream_stream_handler(service_name, method_name),
                    )
                return grpc.unary_unary_rpc_method_handler(
                    runtime._unary_unary_handler(service_name, method_name),
                )

        return _Handler()

    def _metadata(self, handler_call_details: grpc.HandlerCallDetails) -> dict[str, str]:
        return {key.lower(): value for key, value in handler_call_details.invocation_metadata or ()}

    def _lookup_route(
        self,
        handler_call_details: grpc.HandlerCallDetails,
        *,
        service_name: str,
        method_name: str,
    ) -> GrpcMethodRoute | None:
        metadata = self._metadata(handler_call_details)
        tenant = metadata.get(_METADATA_TENANT)
        project = metadata.get(_METADATA_PROJECT)
        version = metadata.get(_METADATA_VERSION)
        if not tenant or not project or not version:
            return None
        compiled = self._cache.get(tenant, project, version)
        if compiled is None:
            return None
        for route in compiled.grpc_methods:
            if route.method_name == method_name:
                return route
        return None

    def _unary_unary_handler(self, service_name: str, method_name: str):
        async def _handler(request: bytes, context: grpc.aio.ServicerContext) -> bytes:
            return await self._serve_unary(request, context, service_name=service_name, method_name=method_name)

        return _handler

    def _unary_stream_handler(self, service_name: str, method_name: str):
        async def _handler(request: bytes, context: grpc.aio.ServicerContext):
            async for item in self._serve_server_stream(
                request,
                context,
                service_name=service_name,
                method_name=method_name,
            ):
                yield item

        return _handler

    def _stream_unary_handler(self, service_name: str, method_name: str):
        async def _handler(request_iterator, context: grpc.aio.ServicerContext) -> bytes:
            last = b""
            async for item in request_iterator:
                last = item
            return await self._serve_unary(last, context, service_name=service_name, method_name=method_name)

        return _handler

    def _stream_stream_handler(self, service_name: str, method_name: str):
        async def _handler(request_iterator, context: grpc.aio.ServicerContext):
            count = 0
            async for _ in request_iterator:
                if count >= _STREAM_BOUND:
                    break
                yield await self._serve_unary(b"", context, service_name=service_name, method_name=method_name)
                count += 1

        return _handler

    async def _resolve_compiled(
        self,
        context: grpc.aio.ServicerContext,
        *,
        method_name: str,
    ) -> tuple[CompiledCanonicalSpec, GrpcMethodRoute, ValidatedApiKey | None] | None:
        metadata = {key.lower(): value for key, value in context.invocation_metadata() or ()}
        tenant = metadata.get(_METADATA_TENANT)
        project = metadata.get(_METADATA_PROJECT)
        version = metadata.get(_METADATA_VERSION)
        if not tenant or not project or not version:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "missing x-apiome-tenant/project/version metadata")
            return None

        api_key = await validate_api_key_for_tenant(
            self._pool,
            api_key=metadata.get(_METADATA_API_KEY),
            tenant_slug=tenant,
        )

        blocked = await enforce_mock_limits_for_context(
            client_host=self._peer_host(context),
            tenant=tenant,
            project=project,
            version=version,
            pool=self._pool,
            settings=self._settings,
            transport="grpc",
        )
        if blocked is not None:
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "rate limit exceeded")
            return None

        access = await get_canonical_access_status(
            self._pool,
            tenant=tenant,
            project=project,
            version=version,
            api_key=api_key,
        )
        if access != "ok":
            await context.abort(grpc.StatusCode.NOT_FOUND, "mock unavailable")
            return None

        compiled = self._cache.get(tenant, project, version)
        if compiled is None:
            loaded = await load_canonical_spec(
                self._pool,
                tenant=tenant,
                project=project,
                version=version,
                api_key=api_key,
            )
            if loaded is None:
                await context.abort(grpc.StatusCode.NOT_FOUND, "canonical spec not found")
                return None
            compiled = compile_canonical_spec(loaded)
            self._cache.put(compiled)
            self._register_reflection(compiled)

        route = next((item for item in compiled.grpc_methods if item.method_name == method_name), None)
        if route is None:
            await context.abort(grpc.StatusCode.UNIMPLEMENTED, "method not found")
            return None
        return compiled, route, api_key

    def _register_reflection(self, compiled: CompiledCanonicalSpec) -> None:
        if self._server is None:
            return
        from apiome_mock.proto_descriptor_builder import service_full_names

        for service_name in service_full_names(compiled.api):
            if service_name in self._registered_services:
                continue
            self._registered_services.add(service_name)
            reflection.enable_server_reflection(
                (reflection.SERVICE_NAME, service_name),
                self._server,
            )

    def _peer_host(self, context: grpc.aio.ServicerContext) -> str:
        peer = context.peer()
        if peer.startswith("ipv4:"):
            return peer.split(":", 2)[1]
        if peer.startswith("ipv6:"):
            return peer.split("[", 1)[1].split("]", 1)[0]
        return "unknown"

    def _descriptor_pool(self, compiled: CompiledCanonicalSpec) -> descriptor_pool.DescriptorPool:
        fds = descriptor_pb2.FileDescriptorSet()
        fds.ParseFromString(build_descriptor_set(compiled.api))
        pool = descriptor_pool.DescriptorPool()
        for file_proto in fds.file:
            pool.Add(file_proto)
        return pool

    def _response_message_type(self, pool: descriptor_pool.DescriptorPool, route: GrpcMethodRoute) -> type[Message]:
        type_name = route.response_message_key or "google.protobuf.Empty"
        short_name = type_name.rsplit(".", 1)[-1]
        descriptor = pool.FindMessageTypeByName(short_name)
        factory = message_factory.MessageFactory(pool=pool)
        return factory.GetPrototype(descriptor)

    async def _serve_unary(
        self,
        request: bytes,
        context: grpc.aio.ServicerContext,
        *,
        service_name: str,
        method_name: str,
    ) -> bytes:
        resolved = await self._resolve_compiled(context, method_name=method_name)
        if resolved is None:
            return b""
        compiled, route, api_key = resolved
        response_message = next(
            (message for message in route.operation.messages if message.role is MessageRole.RESPONSE),
            None,
        )
        if response_message is None:
            await context.abort(grpc.StatusCode.INTERNAL, "response message missing")
            return b""

        synthesized = resolve_message_body(compiled.api, response_message)
        limits = await resolve_limits_for_tenant(self._pool, compiled.loaded.tenant_slug, settings=self._settings)
        if limits is not None:
            record_mock_transport_event(
                pool=self._pool,
                tenant=compiled.loaded.tenant_slug,
                project=compiled.loaded.project_slug,
                version=compiled.loaded.version_label,
                transport="grpc",
                channel=f"{service_name}/{method_name}",
                direction="outbound",
                tenant_id=limits.tenant_id,
                api_key_id=api_key.id if api_key is not None else None,
                settings=self._settings,
            )

        pool = self._descriptor_pool(compiled)
        try:
            message_cls = self._response_message_type(pool, route)
            message = message_cls()
            json_format.ParseDict(synthesized.body, message, ignore_unknown_fields=True)
            return message.SerializeToString()
        except Exception:
            return b""

    async def _serve_server_stream(
        self,
        request: bytes,
        context: grpc.aio.ServicerContext,
        *,
        service_name: str,
        method_name: str,
    ):
        for _ in range(_STREAM_BOUND):
            payload = await self._serve_unary(request, context, service_name=service_name, method_name=method_name)
            yield payload
            await asyncio.sleep(0)
