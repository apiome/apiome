"""WebSocket and SSE mock transports for AsyncAPI canonical models (SIM-4.4)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from psycopg_pool import AsyncConnectionPool
from starlette.requests import Request

from apiome_mock.api_key import ValidatedApiKey
from apiome_mock.canonical_compiler import CompiledCanonicalSpec, EventChannelRoute
from apiome_mock.canonical_loader import get_canonical_access_status, load_canonical_spec
from apiome_mock.canonical_spec_cache import CanonicalSpecCache
from apiome_mock.guard import enforce_mock_limits, record_mock_transport_event, resolve_limits_for_tenant
from apiome_mock.message_resolver import encode_message_text, message_schema, resolve_message_body
from apiome_mock.problems import not_found
from apiome_mock.schema_synthesizer import validate_value
from apiome_mock.settings import Settings, get_settings

_log = structlog.get_logger(__name__)


async def _resolve_canonical_spec(
    *,
    pool: AsyncConnectionPool,
    cache: CanonicalSpecCache,
    tenant: str,
    project: str,
    version: str,
    api_key: ValidatedApiKey | None,
) -> CompiledCanonicalSpec | Response:
    cached = cache.get(tenant, project, version)
    if cached is not None:
        return cached

    access = await get_canonical_access_status(
        pool,
        tenant=tenant,
        project=project,
        version=version,
        api_key=api_key,
    )
    if access == "missing":
        return not_found("Mock endpoint not found.", instance=f"/{tenant}/{project}/{version}")
    if access == "disabled":
        return not_found("Mock is disabled for this version.", instance=f"/{tenant}/{project}/{version}")

    loaded = await load_canonical_spec(
        pool,
        tenant=tenant,
        project=project,
        version=version,
        api_key=api_key,
    )
    if loaded is None:
        return not_found("Canonical mock spec not found.", instance=f"/{tenant}/{project}/{version}")

    from apiome_mock.canonical_compiler import compile_canonical_spec

    compiled = compile_canonical_spec(loaded)
    cache.put(compiled)
    return compiled


def _find_channel(compiled: CompiledCanonicalSpec, channel_key: str) -> EventChannelRoute | None:
    normalized = channel_key.strip("/")
    for route in compiled.event_channels:
        if route.key == normalized or route.address == normalized:
            return route
    return None


def _parse_seed(query_params: Any) -> int | None:
    raw = query_params.get("__seed")
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


async def handle_event_websocket(
    websocket: WebSocket,
    *,
    tenant: str,
    project: str,
    version: str,
    channel_key: str,
    pool: AsyncConnectionPool,
    cache: CanonicalSpecCache,
    api_key: ValidatedApiKey | None,
    settings: Settings | None = None,
) -> None:
    """Accept a WebSocket connection and echo/publish schema-valid event messages."""
    cfg = settings or get_settings()
    blocked = await enforce_mock_limits(
        websocket,
        tenant=tenant,
        project=project,
        version=version,
        pool=pool,
        settings=cfg,
        transport="websocket",
    )
    if blocked is not None:
        await websocket.close(code=1013, reason="rate limit exceeded")
        return

    resolved = await _resolve_canonical_spec(
        pool=pool,
        cache=cache,
        tenant=tenant,
        project=project,
        version=version,
        api_key=api_key,
    )
    if isinstance(resolved, Response):
        await websocket.close(code=1008, reason="mock unavailable")
        return

    route = _find_channel(resolved, channel_key)
    if route is None or not route.supports_websocket:
        await websocket.close(code=1008, reason="unknown channel")
        return

    await websocket.accept()
    limits = await resolve_limits_for_tenant(pool, tenant, settings=cfg)
    seed = _parse_seed(websocket.query_params)
    stop_event = asyncio.Event()

    async def _publish_loop() -> None:
        if not route.subscribe_operations:
            return
        while not stop_event.is_set():
            for operation in route.subscribe_operations:
                for message in operation.messages:
                    payload = resolve_message_body(resolved.api, message, seed=seed)
                    text = encode_message_text(payload)
                    await websocket.send_text(text)
                    if limits is not None:
                        record_mock_transport_event(
                            pool=pool,
                            tenant=tenant,
                            project=project,
                            version=version,
                            transport="websocket",
                            channel=route.key,
                            direction="outbound",
                            tenant_id=limits.tenant_id,
                            api_key_id=api_key.id if api_key is not None else None,
                            settings=cfg,
                        )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=route.periodic_interval_seconds)
            except TimeoutError:
                continue

    publisher = asyncio.create_task(_publish_loop())
    try:
        while True:
            raw = await websocket.receive_text()
            if limits is not None:
                record_mock_transport_event(
                    pool=pool,
                    tenant=tenant,
                    project=project,
                    version=version,
                    transport="websocket",
                    channel=route.key,
                    direction="inbound",
                    tenant_id=limits.tenant_id,
                    api_key_id=api_key.id if api_key is not None else None,
                    settings=cfg,
                )
            echoed: str | None = None
            for operation in route.publish_operations:
                for message in operation.messages:
                    schema = message_schema(resolved.api, message)
                    try:
                        body = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if validate_value(body, schema) is None:
                        echoed = raw
                        break
                if echoed is not None:
                    break
            if echoed is None and route.publish_operations:
                operation = route.publish_operations[0]
                if operation.messages:
                    synthesized = resolve_message_body(
                        resolved.api,
                        operation.messages[0],
                        seed=seed,
                    )
                    echoed = encode_message_text(synthesized)
            if echoed is not None:
                await websocket.send_text(echoed)
    except WebSocketDisconnect:
        pass
    finally:
        stop_event.set()
        publisher.cancel()
        try:
            await publisher
        except asyncio.CancelledError:
            pass


async def handle_event_sse(
    request: Request,
    *,
    tenant: str,
    project: str,
    version: str,
    channel_key: str,
    pool: AsyncConnectionPool,
    cache: CanonicalSpecCache,
    api_key: ValidatedApiKey | None,
    settings: Settings | None = None,
) -> Response:
    """Stream schema-valid event messages over Server-Sent Events."""
    cfg = settings or get_settings()
    blocked = await enforce_mock_limits(
        request,
        tenant=tenant,
        project=project,
        version=version,
        pool=pool,
        settings=cfg,
        transport="sse",
    )
    if blocked is not None:
        return blocked

    resolved = await _resolve_canonical_spec(
        pool=pool,
        cache=cache,
        tenant=tenant,
        project=project,
        version=version,
        api_key=api_key,
    )
    if isinstance(resolved, Response):
        return resolved

    route = _find_channel(resolved, channel_key)
    if route is None or not route.supports_sse:
        return not_found("Event channel not found.", instance=request.url.path)

    limits = await resolve_limits_for_tenant(pool, tenant, settings=cfg)
    seed = _parse_seed(request.query_params)

    async def _event_stream() -> Any:
        if not route.subscribe_operations:
            yield "event: ping\ndata: {}\n\n"
            return
        while True:
            for operation in route.subscribe_operations:
                for message in operation.messages:
                    payload = resolve_message_body(resolved.api, message, seed=seed)
                    text = encode_message_text(payload)
                    yield f"event: message\ndata: {text}\n\n"
                    if limits is not None:
                        record_mock_transport_event(
                            pool=pool,
                            tenant=tenant,
                            project=project,
                            version=version,
                            transport="sse",
                            channel=route.key,
                            direction="outbound",
                            tenant_id=limits.tenant_id,
                            api_key_id=api_key.id if api_key is not None else None,
                            settings=cfg,
                        )
            await asyncio.sleep(route.periodic_interval_seconds)

    return StreamingResponse(_event_stream(), media_type="text/event-stream")
