"""Request handling: spec resolution, routing, and minimal response synthesis."""

from __future__ import annotations

from typing import Any

from app.mock_engine import resolve_response
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from psycopg_pool import AsyncConnectionPool

from apiome_mock.problems import method_not_allowed, not_found
from apiome_mock.routing import match_request
from apiome_mock.spec_cache import SpecCache
from apiome_mock.spec_loader import load_compiled_spec

_HAPPY_PATH_CONFIG: dict[str, Any] = {
    "scenarios": [],
    "active_scenario": "happy-path",
    "seed": 0,
}


def _instance_path(tenant: str, project: str, version: str, path: str) -> str:
    suffix = path.strip("/")
    base = f"/{tenant}/{project}/{version}"
    return f"{base}/{suffix}" if suffix else base


async def resolve_compiled_spec(
    pool: AsyncConnectionPool,
    cache: SpecCache,
    *,
    tenant: str,
    project: str,
    version: str,
) -> Any:
    """Return a compiled spec from cache or Postgres."""
    cached = cache.get(tenant, project, version)
    if cached is not None:
        return cached
    compiled = await load_compiled_spec(pool, tenant=tenant, project=project, version=version)
    if compiled is not None:
        cache.put(compiled)
    return compiled


async def handle_mock_request(
    request: Request,
    *,
    tenant: str,
    project: str,
    version: str,
    path: str,
    pool: AsyncConnectionPool,
    cache: SpecCache,
) -> Response:
    """Serve a mock response for ``/{tenant}/{project}/{version}/{path}``."""
    instance = _instance_path(tenant, project, version, path)
    relative_path = "/" + path.strip("/") if path.strip("/") else "/"

    compiled = await resolve_compiled_spec(pool, cache, tenant=tenant, project=project, version=version)
    if compiled is None:
        return not_found(
            f"No published spec for {tenant}/{project}/{version}.",
            instance=instance,
        )

    operation, _params, allowed_methods = match_request(compiled.operations, request.method, relative_path)
    if operation is None:
        if allowed_methods:
            return method_not_allowed(
                f"Method {request.method.upper()} is not allowed for {relative_path}.",
                instance=instance,
                allow=allowed_methods,
            )
        return not_found(
            f"No operation matches {request.method.upper()} {relative_path}.",
            instance=instance,
        )

    result = resolve_response(
        compiled.spec,
        _HAPPY_PATH_CONFIG,
        list(compiled.operations),
        request.method,
        relative_path,
        seed=0,
    )

    if result.body is None:
        return Response(status_code=result.status, media_type=result.media_type)
    return JSONResponse(status_code=result.status, content=result.body, media_type=result.media_type)
