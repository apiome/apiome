"""Request handling: spec resolution, routing, and example-first mock responses."""

from __future__ import annotations

import json
from typing import Any

from app.mock_engine import MockOperation
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from psycopg_pool import AsyncConnectionPool

from apiome_mock.problems import (
    bad_request,
    method_not_allowed,
    not_acceptable,
    not_found,
    undefined_response_status,
    unsupported_media_type,
)
from apiome_mock.request_validator import ValidationFailure, validate_operation_request
from apiome_mock.response_resolver import (
    parse_forced_status,
    resolve_response_body,
    select_default_success_status,
    select_response_by_status,
)
from apiome_mock.routing import match_request
from apiome_mock.schema_synthesizer import parse_mock_seed
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
        media_type = "application/json"
    return Response(content=payload, status_code=status, media_type=media_type)


def _resolve_operation_response(
    *,
    status: int,
    operation: MockOperation,
    spec: dict[str, Any],
    accept: str | None,
    prefer_header: str | None,
    seed: int,
    instance: str,
) -> Response:
    """Resolve and return the mock response for a concrete operation status code."""
    _, response_obj = select_response_by_status(operation.operation, status)
    if response_obj is None:
        return undefined_response_status(
            f"Status {status} is not defined for {operation.key}.",
            instance=instance,
            requested_status=status,
        )

    resolved = resolve_response_body(
        response_obj,
        spec,
        accept=accept,
        prefer_header=prefer_header,
        seed=seed,
        op_key=operation.key,
    )
    if resolved.not_acceptable:
        return not_acceptable(
            "No response content type satisfies the request Accept header.",
            instance=instance,
        )
    return _response_for_body(status=status, body=resolved.body, media_type=resolved.media_type)


def _validation_problem_response(
    failure: ValidationFailure,
    *,
    operation: MockOperation,
    spec: dict[str, Any],
    accept: str | None,
    prefer_header: str | None,
    seed: int,
    instance: str,
) -> Response:
    """Return a spec-true 400/415 body when defined, else problem+json."""
    _, response_obj = select_response_by_status(operation.operation, failure.status)
    if response_obj is not None:
        resolved = resolve_response_body(
            response_obj,
            spec,
            accept=accept,
            prefer_header=prefer_header,
            seed=seed,
            op_key=operation.key,
        )
        if not resolved.not_acceptable:
            return _response_for_body(
                status=failure.status,
                body=resolved.body,
                media_type=resolved.media_type,
            )

    extra = {"violations": list(failure.violations)} if failure.violations else None
    if failure.status == 415:
        return unsupported_media_type(failure.detail, instance=instance, extra=extra)
    return bad_request(failure.detail, instance=instance, extra=extra)


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

    operation, path_params, allowed_methods = match_request(compiled.operations, request.method, relative_path)
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

    prefer_header = request.headers.get("prefer")
    accept = request.headers.get("accept")
    seed = parse_mock_seed(request.query_params.get("__seed"))
    forced_status = parse_forced_status(prefer_header, request.query_params)
    if forced_status is not None:
        return _resolve_operation_response(
            status=forced_status,
            operation=operation,
            spec=compiled.spec,
            accept=accept,
            prefer_header=prefer_header,
            seed=seed,
            instance=instance,
        )

    failure = await validate_operation_request(request, operation, path_params, compiled.spec)
    if failure is not None:
        return _validation_problem_response(
            failure,
            operation=operation,
            spec=compiled.spec,
            accept=accept,
            prefer_header=prefer_header,
            seed=seed,
            instance=instance,
        )

    status, response_obj = select_default_success_status(operation.operation)
    resolved = resolve_response_body(
        response_obj,
        compiled.spec,
        accept=accept,
        prefer_header=prefer_header,
        seed=seed,
        op_key=operation.key,
    )
    if resolved.not_acceptable:
        return not_acceptable(
            "No response content type satisfies the request Accept header.",
            instance=instance,
        )

    return _response_for_body(status=status, body=resolved.body, media_type=resolved.media_type)
