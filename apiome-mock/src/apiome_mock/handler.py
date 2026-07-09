"""Request handling: spec resolution, routing, and example-first mock responses."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from psycopg_pool import AsyncConnectionPool

from apiome_mock.problems import method_not_allowed, not_acceptable, not_found
from apiome_mock.response_resolver import (
    resolve_response_body,
    select_default_success_status,
)
from apiome_mock.routing import match_request
from apiome_mock.spec_cache import SpecCache
from apiome_mock.spec_loader import load_compiled_spec


def _instance_path(tenant: str, project: str, version: str, path: str) -> str:
    suffix = path.strip("/")
    base = f"/{tenant}/{project}/{version}"
    return f"{base}/{suffix}" if suffix else base


def _response_for_body(
    *,
    status: int,
    body: Any,
    media_type: str,
) -> Response:
    if body is None:
        return Response(status_code=status, media_type=media_type)
    if media_type.endswith("json") or media_type.endswith("+json"):
        return JSONResponse(status_code=status, content=body, media_type=media_type)
    if isinstance(body, (bytes, bytearray)):
        payload: bytes | str = bytes(body)
    elif isinstance(body, str):
        payload = body
    else:
        payload = json.dumps(body)
        if media_type.endswith("json") or "+json" in media_type:
            media_type = "application/json"
    return Response(content=payload, status_code=status, media_type=media_type)


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

    status, response_obj = select_default_success_status(operation.operation)
    resolved = resolve_response_body(
        response_obj,
        compiled.spec,
        accept=request.headers.get("accept"),
        prefer_header=request.headers.get("prefer"),
        seed=0,
        op_key=operation.key,
    )
    if resolved.not_acceptable:
        return not_acceptable(
            "No response content type satisfies the request Accept header.",
            instance=instance,
        )

    return _response_for_body(status=status, body=resolved.body, media_type=resolved.media_type)
