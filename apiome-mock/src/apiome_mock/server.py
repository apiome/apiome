"""FastAPI application for the Apiome mock runtime."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, Response
from psycopg_pool import AsyncConnectionPool

from apiome_mock.api_key import validate_api_key_for_tenant
from apiome_mock.broker_health import DevBrokerHealth
from apiome_mock.broker_producer import BrokerPublisher, PeriodicBrokerProducer
from apiome_mock.callback_dispatch import build_dispatcher
from apiome_mock.canonical_spec_cache import CanonicalSpecCache
from apiome_mock.capture import build_capture_proxy
from apiome_mock.channel_routes import CHANNELS_SEGMENT, handle_channel_publish, handle_list_channels
from apiome_mock.database_pool import create_async_pool, ping_pool
from apiome_mock.event_transport import handle_event_sse, handle_event_websocket
from apiome_mock.graphql_transport import handle_graphql_request
from apiome_mock.grpc_transport import GrpcMockRuntime
from apiome_mock.guard import (
    enforce_mock_limits,
    record_mock_request,
    resolve_limits_for_tenant,
)
from apiome_mock.handler import handle_mock_request
from apiome_mock.logging_config import configure_logging
from apiome_mock.preview_routes import create_preview_router
from apiome_mock.sandbox_routes import create_sandbox_router
from apiome_mock.session_store_factory import create_session_store
from apiome_mock.settings import get_settings
from apiome_mock.spec_cache import SpecCache, run_notify_listener

_log = structlog.get_logger(__name__)

MOCK_DB_POOL_KEY = "db_pool"
MOCK_SPEC_CACHE_KEY = "spec_cache"
MOCK_CANONICAL_CACHE_KEY = "canonical_spec_cache"
MOCK_SESSION_STORE_KEY = "session_store"
MOCK_CALLBACK_DISPATCHER_KEY = "callback_dispatcher"
MOCK_CAPTURE_PROXY_KEY = "capture_proxy"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[dict[str, object]]:
    settings = get_settings()
    configure_logging(settings)
    pool = create_async_pool(settings, open=False)
    cache = SpecCache(
        max_entries=settings.spec_cache_max_entries,
        ttl_seconds=settings.spec_cache_ttl_seconds,
    )
    canonical_cache = CanonicalSpecCache(
        max_entries=settings.spec_cache_max_entries,
        ttl_seconds=settings.spec_cache_ttl_seconds,
    )
    stop_event = asyncio.Event()
    listener_task: asyncio.Task[None] | None = None
    grpc_runtime = GrpcMockRuntime(pool=pool, cache=canonical_cache, settings=settings)

    _log.info("database_pool_opening")
    await pool.open()
    try:
        await ping_pool(pool)
        _log.info("database_pool_ready")
    except Exception as exc:
        _log.warning("database_pool_probe_failed_at_startup", error=str(exc))

    def _invalidate_both(tenant: str, project: str, version: str) -> None:
        cache.invalidate(tenant, project, version)
        canonical_cache.invalidate(tenant, project, version)

    listener_task = asyncio.create_task(
        run_notify_listener(
            str(settings.database_url),
            settings.spec_notify_channel,
            cache,
            stop_event=stop_event,
            on_invalidate=_invalidate_both,
        )
    )
    await grpc_runtime.start()

    session_store = create_session_store(settings, pool)
    callback_dispatcher = build_dispatcher(
        enabled=settings.callbacks_enabled,
        allow_private_destinations=settings.callback_allow_private,
        timeout_seconds=settings.callback_timeout_seconds,
    )
    capture_proxy = build_capture_proxy(
        enabled=settings.capture_enabled,
        allow_private_upstreams=settings.capture_allow_private_upstreams,
        timeout_seconds=settings.capture_timeout_seconds,
        max_body_bytes=settings.capture_max_body_bytes,
        retention_hours=settings.capture_retention_hours,
    )

    # Kafka broker producer (#5736, XPC-2.2): on-demand publishes always go through the publisher;
    # the periodic producer runs only when enabled (turn it off on all but one replica).
    broker_publisher = BrokerPublisher(pool=pool, settings=settings)
    periodic_producer: PeriodicBrokerProducer | None = None
    producer_task: asyncio.Task[None] | None = None
    if settings.broker_producer_enabled:

        async def _load_spec(tenant: str, project: str, version: str) -> object:
            from apiome_mock.event_transport import _resolve_canonical_spec

            resolved = await _resolve_canonical_spec(
                pool=pool, cache=canonical_cache, tenant=tenant, project=project, version=version, api_key=None
            )
            return None if isinstance(resolved, Response) else resolved

        periodic_producer = PeriodicBrokerProducer(publisher=broker_publisher, load_spec=_load_spec, settings=settings)
        producer_task = asyncio.create_task(periodic_producer.run())

    app.state.db_pool = pool
    app.state.spec_cache = cache
    app.state.broker_publisher = broker_publisher
    app.state.canonical_spec_cache = canonical_cache
    app.state.session_store = session_store
    app.state.callback_dispatcher = callback_dispatcher
    app.state.capture_proxy = capture_proxy
    app.state.grpc_runtime = grpc_runtime
    yield {
        MOCK_DB_POOL_KEY: pool,
        MOCK_SPEC_CACHE_KEY: cache,
        MOCK_CANONICAL_CACHE_KEY: canonical_cache,
        MOCK_SESSION_STORE_KEY: session_store,
        MOCK_CALLBACK_DISPATCHER_KEY: callback_dispatcher,
        MOCK_CAPTURE_PROXY_KEY: capture_proxy,
    }

    stop_event.set()
    if periodic_producer is not None:
        await periodic_producer.stop()
    if producer_task is not None:
        producer_task.cancel()
        try:
            await producer_task
        except asyncio.CancelledError:
            pass
    await broker_publisher.close()
    await grpc_runtime.stop()
    if callback_dispatcher is not None:
        await callback_dispatcher.aclose()
    if capture_proxy is not None:
        await capture_proxy.aclose()
    if listener_task is not None:
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass
    _log.info("database_pool_closing")
    await pool.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Apiome Mock", lifespan=lifespan)

    # The opt-in dev broker (#5735, XPC-2.1): reported only while its host resolves, so a stack
    # started without `--profile broker` answers exactly as before.
    dev_broker = DevBrokerHealth(get_settings().dev_broker_bootstrap)

    @app.get("/health")
    async def health() -> JSONResponse:
        body = {"status": "ok"}
        broker = await dev_broker.state()
        if broker is not None:
            body["broker"] = broker
        return JSONResponse(body)

    # Internal dry-run preview (#5528, MSC-1.2). Registered before the data-plane catch-alls: its
    # path is a single reserved segment, so it could not be shadowed by the three-segment mock
    # routes anyway, but declaring it first keeps the reserved surface visible in one place.
    app.include_router(create_preview_router())

    # Internal sandbox serving (#5532, MSC-2.2). apiome-rest's ``/v1/mock/{id}/…`` data plane no
    # longer resolves anything itself; it forwards here, so the ephemeral instances it provisions
    # are answered by the same engine as every other mock request.
    app.include_router(create_sandbox_router())

    @app.websocket("/{tenant}/{project}/{version}/events/ws/{channel_key:path}")
    async def event_websocket(
        websocket: WebSocket,
        tenant: str,
        project: str,
        version: str,
        channel_key: str,
    ) -> None:
        pool: AsyncConnectionPool = app.state.db_pool
        cache: CanonicalSpecCache = app.state.canonical_spec_cache
        settings = get_settings()
        raw_api_key = websocket.headers.get("X-Api-Key") or websocket.headers.get("x-api-key")
        validated_key = await validate_api_key_for_tenant(
            pool,
            api_key=raw_api_key,
            tenant_slug=tenant,
        )
        await handle_event_websocket(
            websocket,
            tenant=tenant,
            project=project,
            version=version,
            channel_key=channel_key,
            pool=pool,
            cache=cache,
            api_key=validated_key,
            settings=settings,
        )

    @app.get("/{tenant}/{project}/{version}/events/sse/{channel_key:path}")
    async def event_sse(
        request: Request,
        tenant: str,
        project: str,
        version: str,
        channel_key: str,
    ) -> Response:
        pool: AsyncConnectionPool = app.state.db_pool
        cache: CanonicalSpecCache = app.state.canonical_spec_cache
        settings = get_settings()
        raw_api_key = request.headers.get("X-Api-Key") or request.headers.get("x-api-key")
        validated_key = await validate_api_key_for_tenant(
            pool,
            api_key=raw_api_key,
            tenant_slug=tenant,
        )
        return await handle_event_sse(
            request,
            tenant=tenant,
            project=project,
            version=version,
            channel_key=channel_key,
            pool=pool,
            cache=cache,
            api_key=validated_key,
            settings=settings,
        )

    async def serve_rest(request: Request, tenant: str, project: str, version: str, path: str) -> Response:
        """Serve one request through the REST (OpenAPI) mock path: limits, resolution, usage."""
        pool: AsyncConnectionPool = app.state.db_pool
        cache: SpecCache = app.state.spec_cache
        session_store = getattr(app.state, "session_store", None)
        callback_dispatcher = getattr(app.state, "callback_dispatcher", None)
        capture_proxy = getattr(app.state, "capture_proxy", None)
        settings = get_settings()
        raw_api_key = request.headers.get("X-Api-Key") or request.headers.get("x-api-key")
        validated_key = await validate_api_key_for_tenant(
            pool,
            api_key=raw_api_key,
            tenant_slug=tenant,
        )

        blocked = await enforce_mock_limits(
            request,
            tenant=tenant,
            project=project,
            version=version,
            pool=pool,
            settings=settings,
        )
        if blocked is not None:
            return blocked

        limits = await resolve_limits_for_tenant(pool, tenant, settings=settings)
        response = await handle_mock_request(
            request,
            tenant=tenant,
            project=project,
            version=version,
            path=path,
            pool=pool,
            cache=cache,
            api_key=validated_key,
            session_store=session_store,
            callback_dispatcher=callback_dispatcher,
            capture_proxy=capture_proxy,
        )
        if limits is not None:
            record_mock_request(
                pool=pool,
                request=request,
                tenant=tenant,
                project=project,
                version=version,
                path=path,
                status_code=response.status_code,
                tenant_id=limits.tenant_id,
                api_key_id=validated_key.id if validated_key is not None else None,
                settings=settings,
            )
        return response

    # Event channel control routes (#5736, XPC-2.2): the channel listing and on-demand Kafka
    # publish. Declared before the REST catch-all; `__channels__` is a reserved segment.
    @app.get(f"/{{tenant}}/{{project}}/{{version}}/{CHANNELS_SEGMENT}")
    async def list_channels_route(request: Request, tenant: str, project: str, version: str) -> Response:
        pool: AsyncConnectionPool = app.state.db_pool
        raw_api_key = request.headers.get("X-Api-Key") or request.headers.get("x-api-key")
        validated_key = await validate_api_key_for_tenant(pool, api_key=raw_api_key, tenant_slug=tenant)
        return await handle_list_channels(
            tenant=tenant, project=project, version=version, pool=pool,
            cache=app.state.canonical_spec_cache, api_key=validated_key,
        )

    @app.post(f"/{{tenant}}/{{project}}/{{version}}/{CHANNELS_SEGMENT}/{{channel_key:path}}/publish")
    async def publish_channel_route(
        request: Request, tenant: str, project: str, version: str, channel_key: str
    ) -> Response:
        pool: AsyncConnectionPool = app.state.db_pool
        raw_api_key = request.headers.get("X-Api-Key") or request.headers.get("x-api-key")
        validated_key = await validate_api_key_for_tenant(pool, api_key=raw_api_key, tenant_slug=tenant)
        return await handle_channel_publish(
            request, tenant=tenant, project=project, version=version, channel_key=channel_key,
            pool=pool, cache=app.state.canonical_spec_cache, publisher=app.state.broker_publisher,
            api_key=validated_key,
        )

    # GraphQL mock route (#5729, XPC-1.1). Declared before the REST catch-all so it wins for
    # GraphQL versions; any other version falls through to the REST path, so a REST API with its
    # own ``/graphql`` operation is served exactly as before.
    @app.api_route("/{tenant}/{project}/{version}/graphql", methods=["GET", "POST"])
    async def graphql_route(request: Request, tenant: str, project: str, version: str) -> Response:
        pool: AsyncConnectionPool = app.state.db_pool
        cache: CanonicalSpecCache = app.state.canonical_spec_cache
        raw_api_key = request.headers.get("X-Api-Key") or request.headers.get("x-api-key")
        validated_key = await validate_api_key_for_tenant(
            pool,
            api_key=raw_api_key,
            tenant_slug=tenant,
        )
        response = await handle_graphql_request(
            request,
            tenant=tenant,
            project=project,
            version=version,
            pool=pool,
            cache=cache,
            api_key=validated_key,
            settings=get_settings(),
        )
        if response is not None:
            return response
        return await serve_rest(request, tenant, project, version, "graphql")

    @app.api_route(
        "/{tenant}/{project}/{version}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    @app.api_route(
        "/{tenant}/{project}/{version}/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def mock_route(
        request: Request,
        tenant: str,
        project: str,
        version: str,
        path: str = "",
    ) -> Response:
        return await serve_rest(request, tenant, project, version, path)

    return app
