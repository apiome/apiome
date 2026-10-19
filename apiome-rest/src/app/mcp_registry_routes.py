"""MCP Registry API over the MCP server catalog — read-only routes (AAU-5.3, #5724; CDG-4.1, #5973).

Serves a tenant's cataloged MCP servers in the official registry API shape, so a host, gateway or
registry client can page through them with no Apiome-specific code. Every route is mounted twice
with identical behaviour: under ``/v1/tenants/{tenant_slug}/mcp-registry`` (AAU-5.3) and under the
registry-style base ``/registry/mcp/{tenant_slug}`` (CDG-4.1) that a host or gateway is pointed at:

* ``GET …/v0.1/servers`` — ``ServerList`` (``cursor``, ``limit`` ≤ 100, ``search``,
  ``updated_since``, ``version``).
* ``GET …/v0.1/servers/{serverName}/versions`` — every served version of one server.
* ``GET …/v0.1/servers/{serverName}/versions/{version}`` — one ``ServerResponse`` (``latest`` or
  the exact version), with an ``ETag`` and ``If-None-Match`` support.
* ``GET …/v0.1/schema`` — the registry API and ``server.json`` schema versions served.

Visibility follows the catalog: anonymous callers see only endpoints the public gate admits
(published, public, enabled); a signed-in member, a workspace API key (``X-API-Key``) or an MCP API
key (``Authorization: Bearer``) of the same tenant also sees private and unpublished endpoints.
Bad credentials are refused (``401`` / ``403``) rather than silently downgraded to the public view.

Each entry is built by :mod:`app.mcp_registry`; its trust posture is recomputed offline from the
stored snapshot, with the vulnerability lookup off, so an anonymous read never calls out.
The tenant's own agent-runtime entry is added by AAU-5.1 (#5722) once that builder exists.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from fastapi import APIRouter, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse

from .auth import decode_jwt, resolve_optional_tenant_member_auth
from .database import db
from .mcp_catalog_routes import _build_posture_context
from .mcp_feed_routes import _if_none_match_hit
from .mcp_registry import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    InvalidCursorError,
    body_etag,
    build_server_response,
    decode_cursor,
    encode_cursor,
    endpoint_slug_from_name,
    entry_version,
    schema_info,
    server_list,
    trust_posture_summary,
)
from .mcp_trust_posture import run_trust_posture

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/tenants", tags=["mcp-registry"])

#: The registry-style mount (CDG-4.1): ``/registry/mcp/{tenant_slug}/v0.1/…``, same handlers.
registry_router = APIRouter(prefix="/registry/mcp", tags=["mcp-registry"])

#: ``Cache-Control`` for an anonymous (public-slice) response and for a credentialed one.
_PUBLIC_CACHE = "public, max-age=60"
_PRIVATE_CACHE = "private, no-store"

_BEARER = "bearer "


def _strip_bearer(value: str) -> str:
    """Return the credential after a ``Bearer`` prefix (case-insensitive), else the value."""
    value = value.strip()
    return value[len(_BEARER):].strip() if value.lower().startswith(_BEARER) else value


def _mcp_key_admits(tenant_slug: str, secret: str) -> bool:
    """Return whether ``secret`` is a live MCP API key of ``tenant_slug``.

    Raises:
        HTTPException: ``401`` when the key is unknown, revoked or expired; ``403`` when it belongs
            to another tenant (or the tenant does not exist).
    """
    key_tenant_id = db.resolve_mcp_api_key_tenant_id(secret)
    if not key_tenant_id:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired credential",
            headers={"WWW-Authenticate": "Bearer, API-Key"},
        )
    tenant = db.get_active_tenant_auth_row(tenant_slug)
    if not tenant or str(tenant.get("tenant_id")) != key_tenant_id:
        raise HTTPException(status_code=403, detail="Credential does not have access to this tenant")
    return True


def caller_sees_private(
    tenant_slug: str,
    *,
    authorization: Optional[str],
    x_api_key: Optional[str],
) -> bool:
    """Decide whether the caller may see the tenant's private registry entries.

    Args:
        tenant_slug: The tenant whose registry is being read.
        authorization: The ``Authorization`` header — a session JWT or an MCP API key.
        x_api_key: The ``X-API-Key`` header — a workspace API key or an MCP API key.

    Returns:
        ``False`` when no credential is presented (public slice), ``True`` when one of this
        tenant's credentials is.

    Raises:
        HTTPException: ``401`` / ``403`` for a credential that is invalid or another tenant's.
    """
    auth_header = (authorization or "").strip()
    key_header = (x_api_key or "").strip()
    if not auth_header and not key_header:
        return False
    if auth_header:
        if decode_jwt(auth_header):
            return resolve_optional_tenant_member_auth(
                tenant_slug, authorization=auth_header, x_api_key=None
            )
        return _mcp_key_admits(tenant_slug, _strip_bearer(auth_header))
    if db.validate_api_key(key_header):
        return resolve_optional_tenant_member_auth(
            tenant_slug, authorization=None, x_api_key=key_header
        )
    return _mcp_key_admits(tenant_slug, key_header)


async def _trust_posture(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Recompute the current snapshot's trust-posture summary offline, or ``None`` on failure.

    A posture failure must not take the listing down, so any error is logged and the entry carries
    ``trustPosture: null``.
    """
    try:
        version = db.get_mcp_endpoint_version(str(row["id"]), str(row["current_version_id"]))
        if not version:
            return None
        context = await _build_posture_context(str(row["id"]), version, scan_vulnerabilities=False)
        return trust_posture_summary(run_trust_posture(context).report_dict())
    except Exception:  # noqa: BLE001 — a posture failure degrades one field, not the page
        logger.exception("mcp_registry: trust posture failed for endpoint %s", row.get("id"))
        return None


async def _entries(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build a ``ServerResponse`` for each row, in order."""
    return [build_server_response(row, trust_posture=await _trust_posture(row)) for row in rows]


def _json(body: Any, *, private: bool, etag: Optional[str] = None) -> JSONResponse:
    """Return ``body`` as JSON with the caching headers for the caller's visibility."""
    headers = {
        "Cache-Control": _PRIVATE_CACHE if private else _PUBLIC_CACHE,
        "Vary": "Authorization, X-API-Key",
    }
    if etag:
        headers["ETag"] = etag
    return JSONResponse(content=body, headers=headers)


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    """Treat a naive ``updated_since`` as UTC so it compares against ``timestamptz`` columns."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _server_row(tenant_slug: str, server_name_param: str, *, private: bool) -> Dict[str, Any]:
    """Resolve a server name to its registry row, or raise ``404``.

    The router decodes ``%2F`` before matching, so the name arrives through a ``path`` converter
    with its ``/``; :func:`urllib.parse.unquote` also accepts a client that double-encoded it.
    """
    slug = endpoint_slug_from_name(unquote(server_name_param), tenant_slug)
    rows = (
        db.list_mcp_registry_endpoints(tenant_slug, include_private=private, limit=1, slug=slug)
        if slug
        else []
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Server not found")
    return rows[0]


@registry_router.get("/{tenant_slug}/v0.1/servers")
@router.get("/{tenant_slug}/mcp-registry/v0.1/servers")
async def list_registry_servers(
    tenant_slug: str,
    cursor: Optional[str] = Query(None, description="Opaque cursor from `metadata.nextCursor`."),
    limit: int = Query(
        DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT, description="Page size (1–100, default 30)."
    ),
    search: Optional[str] = Query(None, description="Substring matched against server name and slug."),
    updated_since: Optional[datetime] = Query(
        None, description="Only servers whose entry changed at or after this RFC 3339 instant."
    ),
    version: Optional[str] = Query(
        None, description="`latest` (every served entry) or an exact version string."
    ),
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> JSONResponse:
    """List a tenant's cataloged MCP servers in the MCP Registry API v0.1 ``ServerList`` shape (AAU-5.3).

    Pages are keyset-ordered by endpoint slug, so a cursor stays valid while servers are added.
    Anonymous callers see only published, public endpoints; a credential of the tenant (session,
    workspace API key, or MCP API key) also lists private and unpublished ones. An unknown tenant
    is an empty list, so the route never confirms whether a tenant exists.

    Args:
        tenant_slug: The tenant whose catalog to list.
        cursor: The previous page's ``metadata.nextCursor``.
        limit: Page size, 1–100.
        search: Case-insensitive substring of the server's name or slug.
        updated_since: Lower bound on each entry's ``updatedAt``.
        version: ``latest`` or an exact version; only current versions are served.
        authorization: Optional session JWT or MCP API key (``Bearer``).
        x_api_key: Optional workspace or MCP API key.

    Returns:
        A ``ServerList`` (``servers`` + ``metadata.count`` / ``metadata.nextCursor``).
    """
    private = caller_sees_private(tenant_slug, authorization=authorization, x_api_key=x_api_key)
    try:
        after_slug = decode_cursor(cursor) if cursor else None
    except InvalidCursorError as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc

    rows = db.list_mcp_registry_endpoints(
        tenant_slug,
        include_private=private,
        limit=limit + 1,
        after_slug=after_slug,
        search=(search or "").strip() or None,
        updated_since=_utc(updated_since),
    )
    page = rows[:limit]
    next_cursor = encode_cursor(str(page[-1]["slug"])) if len(rows) > limit else None
    wanted = (version or "").strip()
    if wanted and wanted != "latest":
        page = [row for row in page if entry_version(row) == wanted]
    body = server_list(await _entries(page), next_cursor)
    return _json(body, private=private, etag=body_etag(body))


@registry_router.get("/{tenant_slug}/v0.1/servers/{server_name:path}/versions")
@router.get("/{tenant_slug}/mcp-registry/v0.1/servers/{server_name:path}/versions")
async def list_registry_server_versions(
    tenant_slug: str,
    server_name: str,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> JSONResponse:
    """List the served versions of one server — a ``ServerList`` holding its current version (AAU-5.3).

    Args:
        tenant_slug: The tenant whose catalog to read.
        server_name: The URL-encoded server name (``apiome.<tenant>%2F<endpoint>``).
        authorization: Optional session JWT or MCP API key (``Bearer``).
        x_api_key: Optional workspace or MCP API key.

    Returns:
        A ``ServerList`` with the server's current version; ``404`` when the caller cannot see it.
    """
    private = caller_sees_private(tenant_slug, authorization=authorization, x_api_key=x_api_key)
    row = _server_row(tenant_slug, server_name, private=private)
    body = server_list(await _entries([row]), None)
    return _json(body, private=private, etag=body_etag(body))


@registry_router.get(
    "/{tenant_slug}/v0.1/servers/{server_name:path}/versions/{version}",
    responses={304: {"description": "Not modified (the `If-None-Match` ETag still matches)."}},
)
@router.get(
    "/{tenant_slug}/mcp-registry/v0.1/servers/{server_name:path}/versions/{version}",
    responses={304: {"description": "Not modified (the `If-None-Match` ETag still matches)."}},
)
async def get_registry_server_version(
    tenant_slug: str,
    server_name: str,
    version: str,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
) -> Response:
    """Return one server version as a registry ``ServerResponse``, with an ``ETag`` (AAU-5.3).

    Args:
        tenant_slug: The tenant whose catalog to read.
        server_name: The URL-encoded server name (``apiome.<tenant>%2F<endpoint>``).
        version: ``latest`` or the exact (URL-encoded) version string.
        authorization: Optional session JWT or MCP API key (``Bearer``).
        x_api_key: Optional workspace or MCP API key.
        if_none_match: Conditional-request header; a match answers ``304``.

    Returns:
        The ``ServerResponse``; ``304`` when unchanged; ``404`` for an unknown or hidden server
        or a version that is not the one served.
    """
    private = caller_sees_private(tenant_slug, authorization=authorization, x_api_key=x_api_key)
    row = _server_row(tenant_slug, server_name, private=private)
    wanted = unquote(version)
    if wanted != "latest" and wanted != entry_version(row):
        raise HTTPException(status_code=404, detail="Server version not found")
    entry = (await _entries([row]))[0]
    etag = body_etag(entry)
    if _if_none_match_hit(if_none_match, etag):
        return Response(
            status_code=304,
            headers={
                "ETag": etag,
                "Cache-Control": _PRIVATE_CACHE if private else _PUBLIC_CACHE,
                "Vary": "Authorization, X-API-Key",
            },
        )
    return _json(entry, private=private, etag=etag)


@registry_router.get("/{tenant_slug}/v0.1/schema")
@router.get("/{tenant_slug}/mcp-registry/v0.1/schema")
async def get_registry_schema_version(tenant_slug: str) -> JSONResponse:
    """Return the registry API and ``server.json`` schema versions this registry serves (CDG-4.1).

    Anonymous and tenant-independent in content (the tenant segment only mirrors the other routes'
    base URL), so a client can check compatibility before paging.

    Args:
        tenant_slug: The tenant whose registry base URL was called (not looked up).

    Returns:
        ``{"registryApiVersion", "serverSchema", "apiSpec": {"version", "commit"}}``.
    """
    _ = tenant_slug
    return _json(schema_info(), private=False)
