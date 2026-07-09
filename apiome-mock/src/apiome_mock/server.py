"""FastAPI application for the Apiome mock runtime."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from psycopg_pool import AsyncConnectionPool

from apiome_mock.database_pool import create_async_pool, ping_pool
from apiome_mock.handler import handle_mock_request
from apiome_mock.logging_config import configure_logging
from apiome_mock.settings import get_settings
from apiome_mock.spec_cache import SpecCache, run_notify_listener

_log = structlog.get_logger(__name__)

MOCK_DB_POOL_KEY = "db_pool"
MOCK_SPEC_CACHE_KEY = "spec_cache"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[dict[str, object]]:
    settings = get_settings()
    configure_logging(settings)
    pool = create_async_pool(settings, open=False)
    cache = SpecCache(
        max_entries=settings.spec_cache_max_entries,
        ttl_seconds=settings.spec_cache_ttl_seconds,
    )
    stop_event = asyncio.Event()
    listener_task: asyncio.Task[None] | None = None

    _log.info("database_pool_opening")
    await pool.open()
    try:
        await ping_pool(pool)
        _log.info("database_pool_ready")
    except Exception as exc:
        _log.warning("database_pool_probe_failed_at_startup", error=str(exc))

    listener_task = asyncio.create_task(
        run_notify_listener(
            str(settings.database_url),
            settings.spec_notify_channel,
            cache,
            stop_event=stop_event,
        )
    )

    app.state.db_pool = pool
    app.state.spec_cache = cache
    yield {MOCK_DB_POOL_KEY: pool, MOCK_SPEC_CACHE_KEY: cache}

    stop_event.set()
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

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

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
        pool: AsyncConnectionPool = app.state.db_pool
        cache: SpecCache = app.state.spec_cache
        return await handle_mock_request(
            request,
            tenant=tenant,
            project=project,
            version=version,
            path=path,
            pool=pool,
            cache=cache,
        )

    return app
