"""
MCP Catalog — endpoint registration & management (V2-MCP-17.1 / MCAT-3.1, #3663).

Tenants register external MCP servers under a friendly catalog name. This module
exposes tenant-scoped CRUD over ``odb.mcp_endpoints``:

- ``POST   /v1/mcp/{tenant_slug}/endpoints``           — register an endpoint
- ``GET    /v1/mcp/{tenant_slug}/endpoints``           — list a tenant's endpoints
- ``GET    /v1/mcp/{tenant_slug}/endpoints/{id}``      — fetch one endpoint
- ``PATCH  /v1/mcp/{tenant_slug}/endpoints/{id}``      — patch mutable fields

Tenant scoping comes from the existing :func:`validate_authentication` dependency
(JWT Bearer or ``X-API-Key``): the caller's ``tenant_id`` — never the URL slug —
is what scopes every DB query, so a cross-tenant id reads as ``404``. The catalog
slug is derived from the endpoint name and made unique within the tenant.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from psycopg2 import errors as pg_errors

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .mcp_discovery_engine import trigger_discovery
from .models import (
    McpDiscoveryJobListResponse,
    McpDiscoveryJobResponse,
    McpDiscoveryJobStatusListResponse,
    McpDiscoveryJobStatusResponse,
    McpEndpointCreate,
    McpEndpointDeleteResponse,
    McpEndpointListResponse,
    McpEndpointResponse,
    McpEndpointUpdate,
    mcp_discovery_job_out_from_row,
    mcp_discovery_job_status_from_row,
    mcp_endpoint_out_from_row,
)

_logger = logging.getLogger(__name__)

mcp_endpoints_router = APIRouter(prefix="/v1/mcp", tags=["mcp-catalog"])


def _slugify(name: str) -> str:
    """Derive a URL-safe catalog slug from an endpoint name.

    Lowercases, collapses runs of non-alphanumerics to single hyphens, and trims
    leading/trailing hyphens. Falls back to ``"endpoint"`` when the name has no
    slug-able characters (e.g. all punctuation), so a slug is always produced.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "endpoint"


def _require_actor(auth_data: Dict[str, Any]) -> str:
    """Resolve the acting user id for ``creator_id`` (NOT NULL on the table).

    JWT callers carry their own ``user_id``; API-key callers resolve to the key's
    creator (or a tenant fallback). When neither yields a user, the endpoint
    cannot be attributed, so creation is rejected with ``403``.
    """
    actor = get_authenticated_user_id(auth_data)
    if not actor:
        raise HTTPException(
            status_code=403,
            detail="a resolvable user is required to register an MCP endpoint",
        )
    return str(actor)


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints",
    response_model=McpEndpointListResponse,
)
async def list_mcp_endpoints(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpEndpointListResponse:
    """List every catalog endpoint owned by the caller's tenant (newest first)."""
    _ = tenant_slug  # scoping comes from the token, not the URL slug
    tenant_id = str(auth_data["tenant_id"])
    rows = db.list_mcp_endpoints(tenant_id)
    return McpEndpointListResponse(
        success=True,
        endpoints=[mcp_endpoint_out_from_row(r) for r in rows],
    )


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}",
    response_model=McpEndpointResponse,
)
async def get_mcp_endpoint(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpEndpointResponse:
    """Fetch a single catalog endpoint by id; 404 when it is not the tenant's."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    row = db.get_mcp_endpoint(tenant_id, str(endpoint_id))
    if not row:
        raise HTTPException(status_code=404, detail="MCP endpoint not found")
    return McpEndpointResponse(success=True, endpoint=mcp_endpoint_out_from_row(row))


@mcp_endpoints_router.post(
    "/{tenant_slug}/endpoints",
    response_model=McpEndpointResponse,
    status_code=201,
)
async def create_mcp_endpoint(
    tenant_slug: str,
    body: McpEndpointCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpEndpointResponse:
    """Register a new MCP endpoint in the tenant's catalog.

    The slug is taken from ``body.slug`` when supplied, otherwise derived from the
    name; either way it is uniquified within the tenant by the DB layer. Returns
    the created endpoint with ``201``.
    """
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    actor_id = _require_actor(auth_data)

    name = body.name.strip()
    base_slug = _slugify(body.slug) if body.slug and body.slug.strip() else _slugify(name)

    description = body.description.strip() if body.description else None
    if description == "":
        description = None
    category = body.category.strip() if body.category else None
    if category == "":
        category = None

    try:
        inserted = db.insert_mcp_endpoint(
            tenant_id=tenant_id,
            creator_id=actor_id,
            name=name,
            base_slug=base_slug,
            endpoint_url=body.endpoint_url.strip(),
            transport=body.transport,
            description=description,
            category=category,
            visibility=body.visibility,
            discovery_cadence_seconds=body.discovery_cadence_seconds,
        )
    except pg_errors.UniqueViolation as exc:
        # Belt-and-braces: the slug resolver already avoids collisions, but a
        # concurrent insert racing on the same base slug could still trip the
        # (tenant_id, slug) unique constraint.
        raise HTTPException(
            status_code=409,
            detail="an MCP endpoint with this slug already exists for this tenant",
        ) from exc

    return McpEndpointResponse(success=True, endpoint=mcp_endpoint_out_from_row(inserted))


@mcp_endpoints_router.patch(
    "/{tenant_slug}/endpoints/{endpoint_id}",
    response_model=McpEndpointResponse,
)
async def update_mcp_endpoint(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    body: McpEndpointUpdate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpEndpointResponse:
    """Patch mutable fields on a catalog endpoint; 404 when not the tenant's.

    Only the fields present in the request body are applied (the slug is not
    patchable). An empty body is a no-op that returns the current record.
    """
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    eid = str(endpoint_id)

    fields: Dict[str, Any] = {}
    if body.name is not None:
        fields["name"] = body.name.strip()
    if body.endpoint_url is not None:
        fields["endpoint_url"] = body.endpoint_url.strip()
    if body.transport is not None:
        fields["transport"] = body.transport
    if body.description is not None:
        stripped = body.description.strip()
        fields["description"] = stripped or None
    if body.category is not None:
        stripped = body.category.strip()
        fields["category"] = stripped or None
    if body.visibility is not None:
        fields["visibility"] = body.visibility
    if body.published is not None:
        fields["published"] = body.published
    if body.enabled is not None:
        fields["enabled"] = body.enabled
    if body.discovery_cadence_seconds is not None:
        fields["discovery_cadence_seconds"] = body.discovery_cadence_seconds

    updated = db.update_mcp_endpoint(tenant_id, eid, fields)
    if not updated:
        raise HTTPException(status_code=404, detail="MCP endpoint not found")
    return McpEndpointResponse(success=True, endpoint=mcp_endpoint_out_from_row(updated))


@mcp_endpoints_router.delete(
    "/{tenant_slug}/endpoints/{endpoint_id}",
    response_model=McpEndpointDeleteResponse,
)
async def delete_mcp_endpoint(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpEndpointDeleteResponse:
    """Retire a catalog endpoint and purge its child data (V2-MCP-17.5 / MCAT-3.5).

    The endpoint is soft-deleted (stamped ``deleted_at``, disabled) so it vanishes
    from browse/list/get and is skipped by the discovery sweep, while its slug stays
    reserved. Its children are hard-deleted: the stored credentials (the security-
    critical purge), every discovery job, and every version snapshot — whose
    capability items, change logs and scores cascade away with it. Returns a
    teardown summary, or ``404`` when the endpoint is not the caller's tenant's
    (or was already deleted).
    """
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    summary = db.soft_delete_mcp_endpoint(tenant_id, str(endpoint_id))
    if not summary:
        raise HTTPException(status_code=404, detail="MCP endpoint not found")
    return McpEndpointDeleteResponse(
        success=True,
        endpoint_id=str(endpoint_id),
        credentials_purged=bool(summary.get("credentials_purged")),
        versions_deleted=int(summary.get("versions_deleted", 0)),
        jobs_deleted=int(summary.get("jobs_deleted", 0)),
    )


# ===========================================================================
# Manual discovery trigger & async jobs (V2-MCP-17.2 / MCAT-3.2, #3664)
# ===========================================================================


@mcp_endpoints_router.post(
    "/{tenant_slug}/endpoints/{endpoint_id}/discover",
    response_model=McpDiscoveryJobResponse,
    status_code=202,
)
async def discover_mcp_endpoint(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpDiscoveryJobResponse:
    """Kick off a discovery run for an endpoint and return its job (submit→poll).

    Creates a ``manual`` discovery job and starts the run out of band: the MCP client
    connects, handshakes, paginates the capability listings, normalizes them, and persists a
    new version when the surface changed (version 1 on first run). Poll the returned job's
    ``GET .../discover/{job_id}`` for the terminal state and the produced ``version_id``.

    Concurrent discover requests on the same endpoint are de-duplicated: when a run is already
    queued/running, that existing job is returned (with ``deduplicated=True``) and no second
    run starts. Returns ``404`` when the endpoint is not the caller's tenant's.
    """
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    endpoint = db.get_mcp_endpoint(tenant_id, str(endpoint_id))
    if not endpoint:
        raise HTTPException(status_code=404, detail="MCP endpoint not found")

    job, deduplicated = await trigger_discovery(tenant_id, endpoint)
    return McpDiscoveryJobResponse(
        success=True,
        deduplicated=deduplicated,
        job=mcp_discovery_job_out_from_row(job),
    )


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/discover",
    response_model=McpDiscoveryJobListResponse,
)
async def list_mcp_discovery_jobs(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpDiscoveryJobListResponse:
    """List an endpoint's discovery jobs, newest first; 404 when not the tenant's endpoint."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    endpoint = db.get_mcp_endpoint(tenant_id, str(endpoint_id))
    if not endpoint:
        raise HTTPException(status_code=404, detail="MCP endpoint not found")
    rows = db.list_mcp_discovery_jobs(tenant_id, str(endpoint_id))
    return McpDiscoveryJobListResponse(
        success=True,
        jobs=[mcp_discovery_job_out_from_row(r) for r in rows],
    )


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/discover/{job_id}",
    response_model=McpDiscoveryJobResponse,
)
async def get_mcp_discovery_job(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    job_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpDiscoveryJobResponse:
    """Poll one discovery job's state/result; 404 when it is not this tenant+endpoint's job."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    job = db.get_mcp_discovery_job(tenant_id, str(job_id))
    if not job or str(job.get("endpoint_id")) != str(endpoint_id):
        raise HTTPException(status_code=404, detail="discovery job not found")
    return McpDiscoveryJobResponse(success=True, job=mcp_discovery_job_out_from_row(job))


# ===========================================================================
# Discovery job status/polling API (V2-MCP-17.4 / MCAT-3.4, #3666)
# ===========================================================================
#
# The canonical "follow a discovery job to completion" surface for the CLI poller
# (Epic-11) and the UI. These mirror the ``…/discover`` reads above but return the
# ergonomic :class:`McpDiscoveryJobStatus` snapshot — ``state``, timings, the lifted
# ``version_id`` / ``changed`` (success) or structured ``error_detail`` (failure),
# and a ``status_path`` to re-poll — rather than the raw job row. Both are scoped to
# the caller's token tenant, so a cross-tenant id reads as ``404``.


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/jobs",
    response_model=McpDiscoveryJobStatusListResponse,
)
async def list_mcp_endpoint_jobs(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpDiscoveryJobStatusListResponse:
    """List an endpoint's discovery-job status snapshots, newest first.

    404 when the endpoint is not the caller's tenant's (so an unknown id never
    discloses another tenant's jobs as an empty list).
    """
    tenant_id = str(auth_data["tenant_id"])
    endpoint = db.get_mcp_endpoint(tenant_id, str(endpoint_id))
    if not endpoint:
        raise HTTPException(status_code=404, detail="MCP endpoint not found")
    rows = db.list_mcp_discovery_jobs(tenant_id, str(endpoint_id))
    return McpDiscoveryJobStatusListResponse(
        success=True,
        jobs=[mcp_discovery_job_status_from_row(r, tenant_slug) for r in rows],
    )


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/jobs/{job_id}",
    response_model=McpDiscoveryJobStatusResponse,
)
async def get_mcp_endpoint_job(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    job_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpDiscoveryJobStatusResponse:
    """Poll one discovery job's status snapshot (state, timings, version_id/error).

    A terminal snapshot carries ``version_id`` (completed) or ``error`` /
    ``error_detail`` (failed). 404 when the job is not this tenant+endpoint's.
    """
    tenant_id = str(auth_data["tenant_id"])
    job = db.get_mcp_discovery_job(tenant_id, str(job_id))
    if not job or str(job.get("endpoint_id")) != str(endpoint_id):
        raise HTTPException(status_code=404, detail="discovery job not found")
    return McpDiscoveryJobStatusResponse(
        success=True,
        job=mcp_discovery_job_status_from_row(job, tenant_slug),
    )
