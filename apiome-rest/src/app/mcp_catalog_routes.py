"""
MCP Catalog — endpoint registration & management (V2-MCP-17.1 / MCAT-3.1, #3663).

Tenants register external MCP servers under a friendly catalog name. This module
exposes tenant-scoped CRUD over ``apiome.mcp_endpoints``:

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
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import jsonschema
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2 import errors as pg_errors

from .auth import get_authenticated_user_id, validate_authentication
from .config import settings
from .database import db
from .mcp_auth import (
    CredentialPayloadError,
    build_auth_headers,
    validate_credential_payload,
)
from .mcp_capability_graph import compute_capability_graph
from .mcp_client.normalize import (
    ITEM_TYPE_PROMPT,
    ITEM_TYPE_RESOURCE,
    ITEM_TYPE_TOOL,
)
from .mcp_credential_crypto import CredentialEncryptionError, seal_credential_payload
from .mcp_credentials import load_endpoint_auth_headers
from .mcp_discovery_engine import (
    compare_endpoint_versions,
    reconstruct_surface,
    trigger_discovery,
)
from .mcp_insight_aggregation import (
    DISCOVERY_TIMELINE_WINDOW,
    compute_discovery_reliability,
    compute_discovery_timeline,
    compute_invocation_reliability,
)
from .mcp_invoke import get_prompt, invoke_tool, read_resource
from .mcp_score import score_mcp_surface
from .mcp_surface_metrics import compute_surface_metrics
from .models import (
    McpBrowseResponse,
    McpCredentialDeleteResponse,
    McpCredentialStatusResponse,
    McpCredentialUpsert,
    McpDiscoveryJobListResponse,
    McpDiscoveryJobResponse,
    McpDiscoveryJobStatusListResponse,
    McpDiscoveryJobStatusResponse,
    McpDiscoveryReliabilityOut,
    McpEndpointCreate,
    McpEndpointDeleteResponse,
    McpEndpointDigestResponse,
    McpEndpointListResponse,
    McpEndpointResponse,
    McpEndpointTestRequest,
    McpEndpointTestResponse,
    McpEndpointUpdate,
    McpEndpointVersionListResponse,
    McpEndpointVersionResponse,
    McpEndpointViewMarkRequest,
    McpEndpointViewResponse,
    McpInsightCatalogResponse,
    McpInsightEvolutionResponse,
    McpInsightGraphResponse,
    McpInsightReliabilityResponse,
    McpInsightSurfaceResponse,
    McpInvocationReliabilityOut,
    McpLintReportResponse,
    McpSearchResponse,
    McpSearchScope,
    McpSearchVisibility,
    McpTypeCountsOut,
    McpVersionChangesResponse,
    McpVersionCompareResponse,
    McpVersionRef,
    group_mcp_browse_endpoints,
    mcp_capability_graph_out,
    mcp_catalog_insight_from_row,
    mcp_change_counts,
    mcp_credential_status_from_row,
    mcp_discovery_health_out,
    mcp_discovery_job_out_from_row,
    mcp_discovery_job_status_from_row,
    mcp_endpoint_digest_response,
    mcp_endpoint_out_from_row,
    mcp_endpoint_test_response_from_result,
    mcp_endpoint_view_response,
    mcp_evolution_point_from_row,
    mcp_lint_report_from_report,
    mcp_search_hit_from_row,
    mcp_surface_metrics_out,
    mcp_version_change_out_from_row,
    mcp_version_detail_from_row,
    mcp_version_summary_from_row,
    redact_sensitive_args,
)
from .rate_limit import FixedWindowRateLimiter

_logger = logging.getLogger(__name__)

mcp_endpoints_router = APIRouter(prefix="/v1/mcp", tags=["mcp-catalog"])

# Per-endpoint fixed-window rate limiter for the live test harness (V2-MCP-22.3 / MCAT-8.3, #3689).
# Each accepted test call hits a real external MCP server, so test traffic is throttled per endpoint
# — in addition to the global per-tenant middleware — to keep one tenant from flooding a server it
# is cataloging. In-process (per replica), matching the global limiter's semantics.
_test_invocation_limiter = FixedWindowRateLimiter()


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
    "/{tenant_slug}/browse",
    response_model=McpBrowseResponse,
)
async def browse_mcp_endpoints(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpBrowseResponse:
    """Private browse: the caller's cataloged endpoints grouped by host (V2-MCP-23.1 / MCAT-9.1).

    The browse-list half of the private catalog view (the detail half reuses the existing
    endpoint and version-detail reads). Returns every live endpoint the caller's tenant owns,
    bucketed by the host its URL points at, each carrying its current snapshot's capability
    counts (tools/resources/resource templates/prompts), quality score/grade, and
    last-discovered time. Like every catalog route, scoping comes from the token's
    ``tenant_id`` — never the URL slug — so a tenant only ever browses its own catalog.
    """
    _ = tenant_slug  # scoping comes from the token, not the URL slug
    tenant_id = str(auth_data["tenant_id"])
    rows = db.browse_mcp_endpoints(tenant_id)
    return group_mcp_browse_endpoints(rows)


@mcp_endpoints_router.get(
    "/{tenant_slug}/search",
    response_model=McpSearchResponse,
)
async def search_mcp_catalog(
    tenant_slug: str,
    q: str = Query(
        ...,
        min_length=1,
        description="Free-text query (websearch syntax: quotes for phrases, OR, leading - to exclude).",
    ),
    scope: Optional[McpSearchScope] = Query(
        None,
        description=(
            "What to search: a single capability kind (tool/resource/resource_template/prompt), "
            "or 'endpoint' to search endpoints by name/description/category. Omit to search across "
            "all capability kinds."
        ),
    ),
    host: Optional[str] = Query(None, description="Filter to endpoints on this host (case-insensitive)."),
    category: Optional[str] = Query(
        None, description="Filter to endpoints in this category (case-insensitive)."
    ),
    grade: Optional[str] = Query(
        None, description="Filter to endpoints whose current snapshot earned this A-F grade."
    ),
    visibility: Optional[McpSearchVisibility] = Query(
        None,
        description="Filter to 'private' or 'public' endpoints within the caller's own catalog.",
    ),
    limit: int = Query(50, ge=1, le=200, description="Maximum hits to return."),
    offset: int = Query(0, ge=0, description="Hits to skip (pagination)."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpSearchResponse:
    """Free-text search over the caller's MCP catalog, relevance-then-score ranked (V2-MCP-23.2 / MCAT-9.2).

    Backed by the V127 capability-item ``tsvector`` GIN index. ``scope`` selects what is searched: a
    single capability kind, every capability kind (the default), or the endpoints themselves
    (``scope=endpoint``). Each hit carries its owning endpoint's browse context (host, category,
    score/grade, visibility) so the result is renderable without a second read. The ``host`` /
    ``category`` / ``grade`` / ``visibility`` filters compose (each supplied filter is ANDed in).

    Like every catalog route, scoping comes from the token's ``tenant_id`` — never the URL slug — so a
    search only ever returns the caller's own catalog (the public-directory variant waits on the
    MCAT-1.6 public read view). ``visibility`` therefore narrows the caller's *own* private/public
    endpoints rather than exposing another tenant's. A query that reduces to nothing under full-text
    parsing (e.g. only stop-words) is a valid request that simply returns no hits.
    """
    _ = tenant_slug  # scoping comes from the token, not the URL slug
    tenant_id = str(auth_data["tenant_id"])

    query = q.strip()
    host_filter = host.strip() if host and host.strip() else None
    category_filter = category.strip() if category and category.strip() else None
    grade_filter = grade.strip() if grade and grade.strip() else None

    if not query:
        # An empty/whitespace-only query has nothing to match; return an empty result rather than 422.
        return McpSearchResponse(
            success=True, query=q, scope=scope, limit=limit, offset=offset, count=0, hits=[]
        )

    if scope == "endpoint":
        rows = db.search_mcp_endpoints_fts(
            tenant_id,
            query,
            host=host_filter,
            category=category_filter,
            grade=grade_filter,
            visibility=visibility,
            limit=limit,
            offset=offset,
        )
    else:
        rows = db.search_mcp_capability_items(
            tenant_id,
            query,
            item_type=scope,  # None searches every capability kind
            host=host_filter,
            category=category_filter,
            grade=grade_filter,
            visibility=visibility,
            limit=limit,
            offset=offset,
        )

    hits = [mcp_search_hit_from_row(r) for r in rows]
    return McpSearchResponse(
        success=True,
        query=q,
        scope=scope,
        limit=limit,
        offset=offset,
        count=len(hits),
        hits=hits,
    )


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


# ===========================================================================
# Version history, change report & compare (V2-MCP-18.5 / MCAT-4.5, #3672)
# ===========================================================================
#
# Read surfaces a UI/CLI uses to render an endpoint's version timeline, one version's full
# surface, the stored ``previous → this`` diff a version introduced, and an on-demand diff
# between any two versions. Every route first re-validates the endpoint against the caller's
# token tenant (``db.get_mcp_endpoint``), so a cross-tenant id reads as ``404`` before any
# version is touched; the version reads are then scoped to that endpoint, so a version id
# belonging to a different endpoint also reads as ``404``.
#
# Route ordering note: the literal ``…/versions/compare`` route is declared *before* the
# parametrized ``…/versions/{version_id}`` route so "compare" is never captured as a version
# id (which would 422 against the ``uuid.UUID`` path type).


def _require_tenant_endpoint(
    auth_data: Dict[str, Any], endpoint_id: uuid.UUID
) -> Dict[str, Any]:
    """Load an endpoint scoped to the caller's token tenant, or raise ``404``.

    Shared guard for the version routes: the URL ``tenant_slug`` is informational; the
    caller's ``tenant_id`` from the validated token is what scopes the lookup.
    """
    tenant_id = str(auth_data["tenant_id"])
    endpoint = db.get_mcp_endpoint(tenant_id, str(endpoint_id))
    if not endpoint:
        raise HTTPException(status_code=404, detail="MCP endpoint not found")
    return endpoint


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/versions",
    response_model=McpEndpointVersionListResponse,
)
async def list_mcp_endpoint_versions(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpEndpointVersionListResponse:
    """List an endpoint's version history newest-first (seq, date tag, score, change counts).

    Each entry carries the snapshot's sequence and human-readable ``version_tag``, its server
    identity and fingerprint, the quality score/grade (when scored), and the per-direction
    tally of changes it introduced. ``is_current`` marks the snapshot the endpoint currently
    points at. 404 when the endpoint is not the caller's tenant's.
    """
    _ = tenant_slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)
    current_version_id = endpoint.get("current_version_id")
    rows = db.list_mcp_endpoint_versions(str(endpoint_id))
    return McpEndpointVersionListResponse(
        success=True,
        versions=[mcp_version_summary_from_row(r, current_version_id) for r in rows],
    )


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/versions/compare",
    response_model=McpVersionCompareResponse,
)
async def compare_mcp_endpoint_versions(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    base: uuid.UUID = Query(..., description="The base (from) version id."),
    target: uuid.UUID = Query(..., description="The target (to) version id."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpVersionCompareResponse:
    """Compute an on-demand structured diff between any two of an endpoint's versions.

    Works for *any* base/target pair — adjacent or arbitrarily distant — because the surfaces
    are diffed directly (MCAT-4.2), not by chaining adjacent step-diffs. The order is
    normalized to older→newer (by ``version_seq``) regardless of which id was passed as
    ``base``, so ``added``/``removed`` always read relative to the older surface. The same
    version on both sides yields an empty diff with ``fingerprint_changed = False``. 404 when
    the endpoint — or either version under it — is not the caller's tenant's.
    """
    _ = tenant_slug
    _require_tenant_endpoint(auth_data, endpoint_id)

    base_version = db.get_mcp_endpoint_version(str(endpoint_id), str(base))
    target_version = db.get_mcp_endpoint_version(str(endpoint_id), str(target))
    if base_version is None or target_version is None:
        raise HTTPException(status_code=404, detail="MCP endpoint version not found")

    # Normalize to chronological order so "added"/"removed" read older→newer.
    if int(base_version["version_seq"]) > int(target_version["version_seq"]):
        base_version, target_version = target_version, base_version

    base_ref = McpVersionRef(
        id=str(base_version["id"]),
        version_seq=int(base_version["version_seq"]),
        version_tag=base_version.get("version_tag"),
        surface_fingerprint=base_version.get("surface_fingerprint"),
    )
    target_ref = McpVersionRef(
        id=str(target_version["id"]),
        version_seq=int(target_version["version_seq"]),
        version_tag=target_version.get("version_tag"),
        surface_fingerprint=target_version.get("surface_fingerprint"),
    )

    if str(base_version["id"]) == str(target_version["id"]):
        # Same version on both sides — nothing to diff (avoids needless surface reads).
        return McpVersionCompareResponse(
            success=True,
            base=base_ref,
            target=target_ref,
            fingerprint_changed=False,
            counts=mcp_change_counts(0, 0, 0),
            changes=[],
        )

    diff = compare_endpoint_versions(base_version, target_version)
    counts = diff.counts
    return McpVersionCompareResponse(
        success=True,
        base=base_ref,
        target=target_ref,
        fingerprint_changed=not diff.fingerprint_unchanged,
        counts=mcp_change_counts(counts["added"], counts["removed"], counts["modified"]),
        changes=[mcp_version_change_out_from_row(r) for r in diff.to_change_rows(None)],
    )


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}",
    response_model=McpEndpointVersionResponse,
)
async def get_mcp_endpoint_version(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    version_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpEndpointVersionResponse:
    """Fetch one version snapshot's full surface (identity, capabilities, and items).

    Returns the server identity, declared capabilities, instructions, score/grade, change
    counts, and every normalized capability item of the snapshot. 404 when the endpoint — or
    the version under it — is not the caller's tenant's.
    """
    _ = tenant_slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)
    version = db.get_mcp_endpoint_version(str(endpoint_id), str(version_id))
    if version is None:
        raise HTTPException(status_code=404, detail="MCP endpoint version not found")
    items = db.get_mcp_capability_items(str(version_id))
    return McpEndpointVersionResponse(
        success=True,
        version=mcp_version_detail_from_row(
            version, items, endpoint.get("current_version_id")
        ),
    )


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}/changes",
    response_model=McpVersionChangesResponse,
)
async def get_mcp_endpoint_version_changes(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    version_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpVersionChangesResponse:
    """Return a version's stored ``previous → this`` change report (the diff it introduced).

    Empty for the first version (which introduces no diff). The changes are in the same stable
    order an on-demand compare of the same pair produces. 404 when the endpoint — or the
    version under it — is not the caller's tenant's.
    """
    _ = tenant_slug
    _require_tenant_endpoint(auth_data, endpoint_id)
    version = db.get_mcp_endpoint_version(str(endpoint_id), str(version_id))
    if version is None:
        raise HTTPException(status_code=404, detail="MCP endpoint version not found")
    change_rows = db.get_mcp_version_changes(str(version_id))
    return McpVersionChangesResponse(
        success=True,
        version_id=str(version_id),
        version_seq=int(version["version_seq"]),
        counts=mcp_change_counts(
            version.get("added_count") or 0,
            version.get("removed_count") or 0,
            version.get("modified_count") or 0,
        ),
        changes=[mcp_version_change_out_from_row(r) for r in change_rows],
    )


# ===========================================================================
# Quality lint — fetch stored / recompute a version's lint report (V2-MCP-21.5 / MCAT-7.5, #3686)
# ===========================================================================
#
# The MCP catalog analogue of the per-revision OpenAPI lint API (``lint_routes.py``). A version
# snapshot's lint score/grade/findings are captured best-effort at discovery time (MCAT-7.4) and
# persisted to ``mcp_version_scores``; these two routes let a UI/CLI read that stored report and
# force a fresh recompute. Both reconstruct the snapshot's normalized surface from its persisted
# rows and run the same deterministic scorer (:func:`app.mcp_score.score_mcp_surface`) the
# discovery path uses, so a recompute of an unchanged surface reproduces the same score, grade,
# and fingerprint. Each route first re-validates the endpoint against the caller's token tenant
# via :func:`_require_tenant_endpoint`, so a cross-tenant id reads as ``404``.


def _recompute_mcp_version_lint(version: Dict[str, Any]):
    """Reconstruct a version's surface from its persisted rows and lint+score it.

    Loads the snapshot's ``mcp_capability_items`` children, rebuilds the normalized
    :class:`~app.mcp_client.normalize.DiscoverySurface` (the same reconstruction the diff/compare
    path uses), and runs the deterministic scorer over it. Pure aside from the capability-item
    read — the same stored surface always yields the same :class:`~app.mcp_score.MCPScoreResult`.

    Args:
        version: The ``mcp_endpoint_versions`` row to score.

    Returns:
        The rolled-up :class:`~app.mcp_score.MCPScoreResult` for the snapshot's surface.
    """
    items = db.get_mcp_capability_items(str(version["id"]))
    surface = reconstruct_surface(version, items)
    return score_mcp_surface(surface)


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}/lint",
    response_model=McpLintReportResponse,
)
async def get_mcp_endpoint_version_lint(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    version_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpLintReportResponse:
    """Return a version snapshot's lint report — the stored score, or a live recompute.

    Serves the report persisted at discovery time (``source="stored"``) when one exists; when the
    snapshot has never been scored (or only an empty placeholder row exists), the surface is
    reconstructed and scored on the fly (``source="computed"``) without writing it back — a GET
    stays read-only. Either way the response carries the deterministic score, A-F grade, per-rule
    and per-severity tallies, the stable fingerprint, and every itemized finding. 404 when the
    endpoint — or the version under it — is not the caller's tenant's.
    """
    _ = tenant_slug
    _require_tenant_endpoint(auth_data, endpoint_id)
    version = db.get_mcp_endpoint_version(str(endpoint_id), str(version_id))
    if version is None:
        raise HTTPException(status_code=404, detail="MCP endpoint version not found")

    stored = db.get_mcp_version_score(str(version_id))
    if stored and (stored.get("report") or {}).get("report_fingerprint"):
        return mcp_lint_report_from_report(
            str(endpoint_id),
            version,
            dict(stored["report"]),
            source="stored",
            scored_at=stored.get("scored_at"),
        )

    result = _recompute_mcp_version_lint(version)
    return mcp_lint_report_from_report(
        str(endpoint_id),
        version,
        result.report_dict(),
        source="computed",
    )


@mcp_endpoints_router.post(
    "/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}/lint",
    response_model=McpLintReportResponse,
)
async def recompute_mcp_endpoint_version_lint(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    version_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpLintReportResponse:
    """Recompute a version snapshot's lint report and persist the refreshed score.

    Always reconstructs the snapshot's surface from its stored rows, re-runs the deterministic
    scorer, and upserts the result into ``mcp_version_scores`` (overwriting any prior score and
    moving ``scored_at`` to now). Returns the freshly computed report with ``source="computed"``
    and the persisted ``scored_at``. 404 when the endpoint — or the version under it — is not the
    caller's tenant's.
    """
    _ = tenant_slug
    _require_tenant_endpoint(auth_data, endpoint_id)
    version = db.get_mcp_endpoint_version(str(endpoint_id), str(version_id))
    if version is None:
        raise HTTPException(status_code=404, detail="MCP endpoint version not found")

    result = _recompute_mcp_version_lint(version)
    db.set_mcp_version_score(
        str(version_id),
        score=result.score,
        grade=result.grade,
        report=result.report_dict(),
        report_fingerprint=result.report_fingerprint,
    )
    # Re-read so the response carries the authoritative persisted ``scored_at``.
    stored = db.get_mcp_version_score(str(version_id))
    return mcp_lint_report_from_report(
        str(endpoint_id),
        version,
        result.report_dict(),
        source="computed",
        scored_at=stored.get("scored_at") if stored else None,
    )


# ===========================================================================
# Outbound credentials — set / clear / redacted status (V2-MCP-20.5 / MCAT-6.5, #3681)
# ===========================================================================
#
# A protected MCP server is reached by holding a secret (bearer token, custom header, OAuth2 token
# set, or env bundle). These routes let a tenant set/replace, inspect, and clear that secret for one
# of their endpoints. The secret only ever travels INBOUND: the plaintext arrives on a PUT, is sealed
# by the encryption-at-rest layer (MCAT-6.2) and stored as ciphertext, and is never returned by any
# response — every read projects through the redacted status model (the ciphertext and the decrypted
# secret have no field to escape through). Each route first re-validates the endpoint against the
# caller's token tenant via :func:`_require_tenant_endpoint`, so a cross-tenant id reads as ``404``
# before any credential is touched.


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/credentials",
    response_model=McpCredentialStatusResponse,
)
async def get_mcp_endpoint_credentials(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpCredentialStatusResponse:
    """Return an endpoint's **redacted** credential status (never the secret itself).

    Reports which ``auth_type`` is configured, whether a sealed secret is present (with a fixed
    mask placeholder when it is), the sealing ``key_version``, non-secret ``oauth_metadata`` and
    timestamps. An endpoint with no credential reads as the anonymous ``none`` status. 404 when the
    endpoint is not the caller's tenant's.
    """
    _ = tenant_slug
    _require_tenant_endpoint(auth_data, endpoint_id)
    row = db.get_mcp_endpoint_credentials(str(endpoint_id))
    return McpCredentialStatusResponse(
        success=True,
        credential=mcp_credential_status_from_row(str(endpoint_id), row),
    )


@mcp_endpoints_router.put(
    "/{tenant_slug}/endpoints/{endpoint_id}/credentials",
    response_model=McpCredentialStatusResponse,
)
async def set_mcp_endpoint_credentials(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    body: McpCredentialUpsert,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpCredentialStatusResponse:
    """Set or replace an endpoint's outbound credential, sealing the secret before storage.

    The plaintext ``payload`` is validated against its ``auth_type`` (the same auth-type model used
    to build request headers, so a malformed or injection-bearing secret is rejected here), sealed
    via envelope encryption (MCAT-6.2), and upserted as ciphertext. The response is the **redacted**
    status — the secret is never echoed back. Returns ``404`` when the endpoint is not the caller's
    tenant's, ``422`` when the payload does not match its ``auth_type``, and ``503`` when credential
    encryption is not configured (a secret cannot be stored safely without it).
    """
    _ = tenant_slug
    _require_tenant_endpoint(auth_data, endpoint_id)

    # Validate the plaintext payload against its auth_type before sealing — the write-time gate is
    # the same model that gates use, so an unusable/hostile secret never reaches the vault.
    try:
        validate_credential_payload(body.auth_type, body.payload)
    except CredentialPayloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Seal the secret (ciphertext only ever leaves this call). Fail closed when encryption is
    # unconfigured rather than storing a secret we could not protect.
    try:
        encrypted_payload, key_version = seal_credential_payload(body.payload)
    except CredentialEncryptionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    row = db.upsert_mcp_endpoint_credentials(
        endpoint_id=str(endpoint_id),
        auth_type=body.auth_type,
        encrypted_payload=encrypted_payload,
        key_version=key_version,
        oauth_metadata=body.oauth_metadata,
    )
    return McpCredentialStatusResponse(
        success=True,
        credential=mcp_credential_status_from_row(str(endpoint_id), row),
    )


@mcp_endpoints_router.delete(
    "/{tenant_slug}/endpoints/{endpoint_id}/credentials",
    response_model=McpCredentialDeleteResponse,
)
async def clear_mcp_endpoint_credentials(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpCredentialDeleteResponse:
    """Clear an endpoint's stored credential, removing the row (idempotent).

    Returns ``removed=True`` when a credential was deleted and ``removed=False`` when the endpoint
    had none — both are ``200``. 404 when the endpoint is not the caller's tenant's.
    """
    _ = tenant_slug
    _require_tenant_endpoint(auth_data, endpoint_id)
    removed = db.delete_mcp_endpoint_credentials(str(endpoint_id))
    return McpCredentialDeleteResponse(
        success=True, endpoint_id=str(endpoint_id), removed=removed
    )


# ===========================================================================
# Test harness — invoke one cataloged capability live (V2-MCP-22.2 / MCAT-8.2, #3688)
# ===========================================================================
#
# Exposes the in-process invocation service (:mod:`app.mcp_invoke`, MCAT-8.1) to the UI/CLI as a
# single tenant-scoped route. The route names the capability to exercise on the endpoint's *current*
# discovered surface, validates the supplied ``arguments`` against the stored schema BEFORE the call
# leaves the server, attaches the endpoint's stored credentials (or an ephemeral, never-persisted
# auth override), invokes the one method under a per-call timeout, and returns the content / tool
# error / classified transport failure with its latency. As everywhere in this module, the endpoint
# is first re-validated against the caller's token tenant, so a cross-tenant id reads as ``404``.


def _resolve_test_capability(
    version_id: str, item_type: str, item_name: str
) -> Dict[str, Any]:
    """Find the capability item to invoke on a version's surface, or raise ``404``.

    Scans the snapshot's ``mcp_capability_items`` for the row whose ``item_type`` and ``name`` match
    the request, so a tool, resource, or prompt that is not part of the endpoint's current surface is
    rejected rather than blindly forwarded to the remote server.

    Args:
        version_id: The endpoint's ``current_version_id`` (the surface to invoke against).
        item_type: The requested capability kind (``tool``/``resource``/``prompt``).
        item_name: The requested capability name.

    Returns:
        The matching ``mcp_capability_items`` row.

    Raises:
        HTTPException: ``404`` when no capability of that type and name exists on the surface.
    """
    for row in db.get_mcp_capability_items(version_id):
        if str(row.get("item_type")) == item_type and str(row.get("name")) == item_name:
            return dict(row)
    raise HTTPException(
        status_code=404,
        detail=f"no {item_type} named {item_name!r} on this endpoint's current surface",
    )


def _validate_test_arguments(
    item_type: str, item: Dict[str, Any], arguments: Dict[str, Any]
) -> None:
    """Validate call ``arguments`` against the capability's stored schema before invoking.

    A tool's ``arguments`` are validated against its stored JSON Schema ``inputSchema`` (the ticket's
    central acceptance criterion); a prompt's against its declared required-argument list. A resource
    read takes no arguments, so nothing is checked. A *malformed* stored schema (the remote server's
    fault, not the caller's) is not treated as a client error: local validation is skipped and the
    remote server is left to reject the call, so a bad schema never turns a test into a spurious 422.

    Args:
        item_type: The capability kind being invoked.
        item: The matched ``mcp_capability_items`` row.
        arguments: The caller-supplied arguments object.

    Raises:
        HTTPException: ``422`` when the arguments do not satisfy the tool input schema, or a required
            prompt argument is missing.
    """
    if item_type == ITEM_TYPE_TOOL:
        schema = item.get("input_schema")
        if isinstance(schema, dict) and schema:
            try:
                jsonschema.validate(instance=arguments, schema=schema)
            except jsonschema.ValidationError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"arguments do not match the tool's input schema: {exc.message}",
                ) from exc
            except jsonschema.SchemaError:
                # The server published an invalid inputSchema; don't punish the caller for it —
                # skip local validation and let the remote server reject the call if it must.
                _logger.warning(
                    "MCP tool %r has an invalid stored inputSchema; skipping local "
                    "argument validation",
                    item.get("name"),
                )
    elif item_type == ITEM_TYPE_PROMPT:
        raw = item.get("raw")
        declared = (raw or {}).get("arguments") if isinstance(raw, dict) else None
        for arg in declared or []:
            if (
                isinstance(arg, dict)
                and arg.get("required")
                and arg.get("name") not in arguments
            ):
                raise HTTPException(
                    status_code=422,
                    detail=f"missing required prompt argument {arg.get('name')!r}",
                )


def _resolve_test_headers(
    endpoint_id: str, body: McpEndpointTestRequest
) -> Tuple[Dict[str, str], bool]:
    """Resolve the auth headers for a test call — an ephemeral override, or the stored credential.

    When ``body.auth_override`` is present its plaintext payload is validated against the same
    auth-type model that gates stored credentials and turned into request headers *for this one call
    only* — it is never written to ``mcp_endpoint_credentials``. When absent, the endpoint's stored
    credential is loaded and decrypted exactly as a discovery run would.

    Args:
        endpoint_id: The endpoint whose stored credential to fall back on.
        body: The validated test request (its optional ``auth_override``).

    Returns:
        A ``(headers, override_applied)`` pair: the headers to attach, and whether they came from an
        ephemeral override (``True``) rather than the stored credential (``False``).

    Raises:
        HTTPException: ``422`` when an override payload does not match its ``auth_type``.
    """
    override = body.auth_override
    if override is None:
        return load_endpoint_auth_headers(endpoint_id), False
    try:
        validate_credential_payload(override.auth_type, override.payload)
        headers = build_auth_headers(override.auth_type, override.payload)
    except CredentialPayloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return headers, True


async def _invoke_test_capability(
    url: str,
    item_type: str,
    item_name: str,
    item: Dict[str, Any],
    arguments: Dict[str, Any],
    headers: Dict[str, str],
    timeout: float,
) -> Dict[str, Any]:
    """Dispatch the matched capability to its invocation method and return the result dict.

    Maps the capability kind onto the right :mod:`app.mcp_invoke` helper — a tool to ``tools/call``,
    a resource to ``resources/read`` against its stored concrete ``uri``, a prompt to ``prompts/get``
    — each under the per-call ``timeout``. The invocation service never raises for a remote failure;
    it returns a latency-bearing result whose ``completed``/``is_error``/``error`` describe the
    outcome, which is serialized via :meth:`InvocationResult.as_dict`.

    Args:
        url: The endpoint's MCP URL.
        item_type: The capability kind to invoke.
        item_name: The capability name (tool/prompt target).
        item: The matched capability row (supplies a resource's ``uri``).
        arguments: The validated call arguments (ignored for a resource read).
        headers: The resolved auth headers.
        timeout: Per-request timeout in seconds.

    Returns:
        The ``InvocationResult.as_dict()`` payload for the call.

    Raises:
        HTTPException: ``422`` when a resource has no concrete ``uri`` to read.
    """
    if item_type == ITEM_TYPE_TOOL:
        result = await invoke_tool(
            url, item_name, arguments, headers=headers, timeout=timeout
        )
    elif item_type == ITEM_TYPE_RESOURCE:
        uri = item.get("uri")
        if not uri:
            raise HTTPException(
                status_code=422,
                detail="resource has no concrete uri to read (a template needs expansion)",
            )
        result = await read_resource(url, str(uri), headers=headers, timeout=timeout)
    else:  # ITEM_TYPE_PROMPT (the request model restricts item_type to the testable set)
        result = await get_prompt(
            url, item_name, arguments, headers=headers, timeout=timeout
        )
    return result.as_dict()


# --- Safety guards: destructive confirm, per-endpoint rate limit, redacted logging (MCAT-8.3) ---
#: Tool annotation hints whose presence (as a JSON ``true``) makes a tool dangerous enough to require
#: an explicit caller confirmation before the test harness will invoke it. ``destructiveHint`` marks a
#: tool that may perform irreversible updates; ``openWorldHint`` marks one that reaches out to an
#: open/unbounded external world. Both are advisory hints the server itself published.
_CONFIRMATION_HINTS = ("destructiveHint", "openWorldHint")


def _confirmation_required_hints(item: Dict[str, Any]) -> List[str]:
    """Return the danger hints (``destructiveHint``/``openWorldHint``) a capability asserts as true.

    Reads the item's normalized ``annotations`` object and collects the safety hints that are present
    *and* a JSON boolean ``true`` — a missing key, a non-mapping annotations blob, or a non-boolean
    value (e.g. the string ``"true"``) is treated as unset, so a server never has a confirmation read
    into a value it did not actually assert. Only tools carry these hints; resources/prompts yield an
    empty list.

    Args:
        item: The matched ``mcp_capability_items`` row.

    Returns:
        The names of the asserted danger hints (empty when the call needs no confirmation).
    """
    annotations = item.get("annotations")
    if not isinstance(annotations, dict):
        return []
    return [hint for hint in _CONFIRMATION_HINTS if annotations.get(hint) is True]


def _enforce_test_rate_limit(endpoint_id: str) -> None:
    """Throttle live test invocations per endpoint, raising ``429`` when the window is exhausted.

    A fixed-window counter keyed by endpoint id bounds how many test calls leave the server for one
    cataloged endpoint per window, so a tenant cannot flood an external MCP server through the test
    console. Honours the global ``rate_limit_enabled`` kill switch and reuses its window length; the
    per-endpoint ceiling is ``mcp_test_rate_limit_per_minute``. A no-op when rate limiting is off.

    Args:
        endpoint_id: The endpoint the call targets (the rate-limit bucket).

    Raises:
        HTTPException: ``429`` with ``Retry-After`` / ``X-RateLimit-*`` headers when the per-endpoint
            limit for the current window has been reached.
    """
    if not settings.rate_limit_enabled:
        return
    limit = max(1, settings.mcp_test_rate_limit_per_minute)
    window_seconds = max(1, settings.rate_limit_window_seconds)
    allowed, remaining, reset_after, retry_after = _test_invocation_limiter.check(
        f"mcptest:{endpoint_id}", limit, window_seconds, time.monotonic()
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="test invocation rate limit exceeded for this endpoint; slow down and retry later",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(reset_after),
            },
        )


def _log_test_invocation(
    *,
    endpoint_id: str,
    version_id: Optional[str],
    body: McpEndpointTestRequest,
    result: Dict[str, Any],
    invoked_by: Optional[str],
) -> Optional[str]:
    """Persist a redacted audit row for a dispatched test call; never raises (best-effort).

    Writes one ``mcp_test_invocations`` row recording what was tested and how it turned out. Secrets
    never reach the log: the request's auth headers are not part of the row at all, and both the
    ``arguments`` and the response payload are passed through :func:`app.models.redact_sensitive_args`
    so any secret-named field is masked before storage. ``is_error`` is true for either a tool-level
    error or a transport/JSON-RPC failure (``completed`` false). Because the live call has already
    happened by the time this runs, a logging failure must not fail the request — it is swallowed with
    a warning and a ``None`` id is returned.

    Args:
        endpoint_id: The endpoint the call was made against.
        version_id: The current surface version the item came from (may be ``None``).
        body: The validated test request (source of the arguments to redact + log).
        result: The ``InvocationResult.as_dict()`` payload that came back.
        invoked_by: The acting user id, or ``None`` when unresolved.

    Returns:
        The new log row id, or ``None`` if the best-effort write failed.
    """
    completed = bool(result.get("completed"))
    is_error = bool(result.get("is_error")) or not completed
    latency = result.get("latency_ms")
    latency_ms = int(round(latency)) if isinstance(latency, (int, float)) else None
    # Log the outcome — redacted — so a secret echoed back in content/error is masked too. A failed
    # call (never returned) logs its classified error rather than a NULL response, which is more
    # useful for triage and still carries no secret.
    response_log = redact_sensitive_args(
        {
            "completed": completed,
            "is_error": bool(result.get("is_error")),
            "content": result.get("content") or [],
            "structured_content": result.get("structured_content"),
            "error": result.get("error"),
        }
    )
    try:
        row = db.insert_mcp_test_invocation(
            endpoint_id=endpoint_id,
            version_id=version_id,
            item_type=body.item_type,
            item_name=body.item_name,
            arguments=redact_sensitive_args(body.arguments),
            response=response_log,
            is_error=is_error,
            latency_ms=latency_ms,
            invoked_by=invoked_by,
        )
    except Exception:  # noqa: BLE001 — the call already happened; logging must not fail the response.
        _logger.warning(
            "failed to record MCP test invocation for endpoint %s (%s %r)",
            endpoint_id,
            body.item_type,
            body.item_name,
            exc_info=True,
        )
        return None
    invocation_id = row.get("id") if row else None
    return str(invocation_id) if invocation_id is not None else None


@mcp_endpoints_router.post(
    "/{tenant_slug}/endpoints/{endpoint_id}/test",
    response_model=McpEndpointTestResponse,
)
async def test_mcp_endpoint_capability(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    body: McpEndpointTestRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpEndpointTestResponse:
    """Invoke one cataloged capability against its live MCP server and report the outcome.

    The test-harness surface for the UI/CLI: it names a ``tool``/``resource``/``prompt`` on the
    endpoint's *current* discovered surface, validates the supplied ``arguments`` against the stored
    schema (a tool's ``inputSchema``; a prompt's required arguments), attaches the endpoint's stored
    credential — or an ephemeral ``auth_override`` that is **never persisted** — and invokes the one
    method under ``timeout_seconds``. The response carries the three outcomes the invocation service
    distinguishes: a successful result (``completed`` / not ``is_error``), a tool-level error
    (``completed`` + ``is_error``, with the error content), or a transport/JSON-RPC failure
    (``completed=False`` with a classified ``error``) — each with its ``latency_ms``.

    Safety guards (V2-MCP-22.3 / MCAT-8.3):

    * **Confirm gate** — a tool whose annotations assert ``destructiveHint`` or ``openWorldHint``
      is refused with ``428`` unless the request sets ``confirm=true``, so an irreversible or
      open-world tool is never fired by accident.
    * **Per-endpoint rate limit** — accepted calls are throttled per endpoint (``429`` when the
      window is exhausted) so the console cannot flood the external server.
    * **Redacted audit log** — every *dispatched* call is recorded in ``mcp_test_invocations`` with
      secret-named arguments/response fields masked; auth headers are never logged. The new row's id
      is returned as ``invocation_id``. Logging is best-effort and never fails the call.

    Status codes:

    * ``404`` — the endpoint is not the caller's tenant's, or the named capability is not on its
      current surface.
    * ``409`` — the endpoint has never been discovered (no current surface to test).
    * ``422`` — the arguments fail the stored schema, the override payload is malformed, or a
      resource has no concrete uri.
    * ``428`` — the tool is flagged destructive/open-world and the request did not set ``confirm``.
    * ``429`` — the per-endpoint test rate limit for the current window has been reached.

    A remote-server failure is **not** an HTTP error here: it is reported in-band as
    ``completed=False`` with the classified ``error``, so "the tool is down" is data, not a 5xx.
    """
    _ = tenant_slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)

    version_id = endpoint.get("current_version_id")
    if not version_id:
        raise HTTPException(
            status_code=409,
            detail="endpoint has no discovered surface yet; run discovery before testing",
        )

    item = _resolve_test_capability(str(version_id), body.item_type, body.item_name)

    # Safety gate: a destructive / open-world tool must be explicitly confirmed before it fires.
    danger_hints = _confirmation_required_hints(item)
    if danger_hints and not body.confirm:
        raise HTTPException(
            status_code=428,
            detail=(
                f"{body.item_name!r} is flagged {', '.join(danger_hints)}; "
                "resend with confirm=true to invoke it"
            ),
        )

    _validate_test_arguments(body.item_type, item, body.arguments)

    # Throttle live traffic to the external server before the call goes out (only accepted,
    # fully-validated calls count against the per-endpoint budget).
    _enforce_test_rate_limit(str(endpoint_id))

    headers, override_applied = _resolve_test_headers(str(endpoint_id), body)

    result = await _invoke_test_capability(
        url=str(endpoint["endpoint_url"]),
        item_type=body.item_type,
        item_name=body.item_name,
        item=item,
        arguments=body.arguments,
        headers=headers,
        timeout=body.timeout_seconds,
    )

    # Record the dispatched call (redacted) — best-effort, so a log failure never fails the response.
    invocation_id = _log_test_invocation(
        endpoint_id=str(endpoint_id),
        version_id=str(version_id),
        body=body,
        result=result,
        invoked_by=get_authenticated_user_id(auth_data),
    )

    return mcp_endpoint_test_response_from_result(
        str(endpoint_id),
        body.item_type,
        body.item_name,
        result,
        auth_override_applied=override_applied,
        invocation_id=invocation_id,
    )


# ===========================================================================
# Insight aggregation — pre-aggregated read APIs (V2-MCP-28.2 / MCAT-14.2, #4628)
# ===========================================================================
#
# Read-only, cache-friendly aggregates the Insight tab (14.4) and the 15–22 visualization panels
# render, so the browser never runs N queries per panel nor holds raw item rows. Three endpoint-
# scoped surfaces — capability-surface metrics for any version, the per-version evolution series,
# and discovery/invocation reliability — plus one tenant-scoped catalog roll-up (18.1). Each
# endpoint route first re-validates the endpoint against the caller's token tenant via
# :func:`_require_tenant_endpoint`, so a cross-tenant id reads as ``404``; the catalog route scopes
# on the token tenant directly. The roll-up math is the pure :mod:`app.mcp_surface_metrics` /
# :mod:`app.mcp_insight_aggregation` layer; these routes only fetch and shape.


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/insight/surface",
    response_model=McpInsightSurfaceResponse,
)
async def get_mcp_endpoint_insight_surface(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    version_id: Optional[uuid.UUID] = Query(
        None,
        description="Which snapshot to summarize; omit to summarize the endpoint's current surface.",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpInsightSurfaceResponse:
    """Return the capability-surface metrics for a version snapshot (defaults to the current one).

    Resolves the target snapshot — the supplied ``version_id`` or, when omitted, the endpoint's
    ``current_version_id`` — reconstructs its normalized surface from the persisted rows, and runs
    the deterministic :func:`app.mcp_surface_metrics.compute_surface_metrics` roll-up (per-type
    counts, per-tool schema complexity, annotation and documentation coverage) the 15.x panels
    render. A GET stays read-only: nothing is written. Returns ``404`` when the endpoint — or the
    named version under it — is not the caller's tenant's, or when no ``version_id`` was given and
    the endpoint has never been discovered (no current surface to summarize).
    """
    _ = tenant_slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)

    target_version_id = (
        str(version_id) if version_id is not None else endpoint.get("current_version_id")
    )
    if not target_version_id:
        raise HTTPException(
            status_code=404,
            detail="endpoint has no discovered surface yet; run discovery before requesting insight",
        )

    version = db.get_mcp_endpoint_version(str(endpoint_id), str(target_version_id))
    if version is None:
        raise HTTPException(status_code=404, detail="MCP endpoint version not found")

    items = db.get_mcp_capability_items(str(version["id"]))
    surface = reconstruct_surface(version, items)
    metrics = compute_surface_metrics(surface)
    return McpInsightSurfaceResponse(
        endpoint_id=str(endpoint_id),
        version_id=str(version["id"]),
        version_seq=int(version["version_seq"]),
        version_tag=version.get("version_tag"),
        is_current=str(version["id"]) == str(endpoint.get("current_version_id")),
        metrics=mcp_surface_metrics_out(metrics.as_dict()),
    )


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/insight/graph",
    response_model=McpInsightGraphResponse,
)
async def get_mcp_endpoint_insight_graph(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    version_id: Optional[uuid.UUID] = Query(
        None,
        description="Which snapshot to map; omit to map the endpoint's current surface.",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpInsightGraphResponse:
    """Return the capability relationship graph for a version snapshot (defaults to the current one).

    Resolves the target snapshot — the supplied ``version_id`` or, when omitted, the endpoint's
    ``current_version_id`` — reconstructs its normalized surface from the persisted rows, and runs
    the deterministic :func:`app.mcp_capability_graph.compute_capability_graph` inference (one node
    per capability plus edges for prompts that name a tool, tools that reference a resource URI, and
    items that share a schema type) the 15.2 "Capability relationship graph" panel renders. Edges are
    emitted only on concrete signals (precision over recall); isolated nodes are still returned. A GET
    stays read-only. Returns ``404`` when the endpoint — or the named version under it — is not the
    caller's tenant's, or when no ``version_id`` was given and the endpoint has never been discovered.
    """
    _ = tenant_slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)

    target_version_id = (
        str(version_id) if version_id is not None else endpoint.get("current_version_id")
    )
    if not target_version_id:
        raise HTTPException(
            status_code=404,
            detail="endpoint has no discovered surface yet; run discovery before requesting insight",
        )

    version = db.get_mcp_endpoint_version(str(endpoint_id), str(target_version_id))
    if version is None:
        raise HTTPException(status_code=404, detail="MCP endpoint version not found")

    items = db.get_mcp_capability_items(str(version["id"]))
    surface = reconstruct_surface(version, items)
    graph = compute_capability_graph(surface)
    return McpInsightGraphResponse(
        endpoint_id=str(endpoint_id),
        version_id=str(version["id"]),
        version_seq=int(version["version_seq"]),
        version_tag=version.get("version_tag"),
        is_current=str(version["id"]) == str(endpoint.get("current_version_id")),
        graph=mcp_capability_graph_out(graph.as_dict()),
    )


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/insight/evolution",
    response_model=McpInsightEvolutionResponse,
)
async def get_mcp_endpoint_insight_evolution(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpInsightEvolutionResponse:
    """Return the endpoint's per-version evolution series (oldest snapshot first).

    One point per discovery snapshot carrying its capability ``type_counts``, quality
    ``score`` / ``grade``, the ``change_counts`` (churn by direction) it introduced, and the
    ``severity_counts`` (V2-MCP-30.3) classifying that churn as breaking / additive / review —
    the time series a "how has this server evolved" chart plots, with breaking-change markers.
    An endpoint that was never discovered returns an empty ``series`` (a ``200`` with ``[]``,
    never a ``500``). Returns ``404`` when the endpoint is not the caller's tenant's.
    """
    _ = tenant_slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)
    current_version_id = endpoint.get("current_version_id")
    rows = db.get_mcp_evolution_series(str(endpoint_id))

    # Bucket every snapshot's change rows by version so each point can classify its own
    # churn severity — one query for the whole endpoint rather than one per snapshot.
    changes_by_version: Dict[str, List[Dict[str, Any]]] = {}
    for change in db.get_mcp_version_changes_for_endpoint(str(endpoint_id)):
        changes_by_version.setdefault(str(change["version_id"]), []).append(change)

    return McpInsightEvolutionResponse(
        endpoint_id=str(endpoint_id),
        series=[
            mcp_evolution_point_from_row(
                r, current_version_id, changes_by_version.get(str(r["id"]), [])
            )
            for r in rows
        ],
    )


# ---------------------------------------------------------------------------------------------------
# "Changed since last view" digest — per-user seen-marker (V2-MCP-30.5 / MCAT-16.5, #4640).
#
# A lightweight per-user, per-endpoint marker (``mcp_endpoint_views``) remembers which version a
# user last saw; the digest diffs that snapshot against the endpoint's current version and classifies
# the delta's breaking severity (reusing the compare engine + MCAT-16.3 classifier). The read
# (``GET …/insight/digest``) is pure and never advances the marker; the acknowledge
# (``POST …/views``) advances it — so the digest always reflects the pre-advance state on load.
# ---------------------------------------------------------------------------------------------------


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/insight/digest",
    response_model=McpEndpointDigestResponse,
)
async def get_mcp_endpoint_digest(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpEndpointDigestResponse:
    """Return the caller's "changed since last view" digest for the endpoint (MCAT-16.5).

    Compares the version the caller last saw (their per-user ``mcp_endpoint_views`` seen-marker)
    against the endpoint's current version and summarizes the delta and its breaking severity:
    ``new_to_you`` on a first visit (or when the last-seen snapshot has been pruned),
    ``has_changes`` with the classified diff when the surface moved on since, or neither flag when
    the caller is already up to date. A GET stays read-only — it does **not** advance the marker
    (``POST …/views`` does), so the digest reflects the pre-advance state. An endpoint that was
    never discovered yields a digest with no changes (a ``200``). Returns ``404`` when the endpoint
    is not the caller's tenant's.
    """
    _ = tenant_slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)
    user_id = get_authenticated_user_id(auth_data)

    # The caller's marker — only when a user can be attributed. An unresolvable (legacy API-key)
    # caller has no personal seen-state, so the whole surface reads as "new to you".
    view_row = db.get_mcp_endpoint_view(user_id, str(endpoint_id)) if user_id else None

    current_version_id = endpoint.get("current_version_id")
    current_version = (
        db.get_mcp_endpoint_version(str(endpoint_id), str(current_version_id))
        if current_version_id
        else None
    )

    # Per-kind counts of the current surface (for the "new to you" summary) and the change delta
    # since the last-seen snapshot. Both derive from the current surface, reconstructed once.
    current_type_counts = McpTypeCountsOut()
    change_rows: List[Dict[str, Any]] = []
    if current_version is not None:
        current_items = db.get_mcp_capability_items(str(current_version["id"]))
        current_surface = reconstruct_surface(current_version, current_items)
        current_type_counts = McpTypeCountsOut(
            **compute_surface_metrics(current_surface).type_counts.as_dict()
        )

        last_seen_version_id = view_row.get("last_seen_version_id") if view_row else None
        if last_seen_version_id and str(last_seen_version_id) != str(current_version["id"]):
            last_seen_version = db.get_mcp_endpoint_version(
                str(endpoint_id), str(last_seen_version_id)
            )
            if last_seen_version is not None:
                # Normalize older→newer so "added"/"removed" read from the last-seen surface toward
                # current (the marker is normally the older side; normalize defensively regardless).
                base, target = last_seen_version, current_version
                if int(base["version_seq"]) > int(target["version_seq"]):
                    base, target = target, base
                change_rows = compare_endpoint_versions(base, target).to_change_rows(None)

    return mcp_endpoint_digest_response(
        endpoint_id=str(endpoint_id),
        current_version=current_version,
        current_type_counts=current_type_counts,
        view_row=view_row,
        change_rows=change_rows,
    )


@mcp_endpoints_router.post(
    "/{tenant_slug}/endpoints/{endpoint_id}/views",
    response_model=McpEndpointViewResponse,
)
async def record_mcp_endpoint_view(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    body: Optional[McpEndpointViewMarkRequest] = None,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpEndpointViewResponse:
    """Record that the caller viewed the endpoint, advancing their seen-marker (MCAT-16.5).

    Upserts the caller's per-user ``mcp_endpoint_views`` marker to the snapshot they saw — the
    ``version_id`` they acknowledge in the body, or the endpoint's current version when omitted —
    so the next "changed since last view" digest reads relative to it ("the marker advances on
    view"). Requires a resolvable user (``403`` otherwise, as the marker is per-user). Returns
    ``404`` when the endpoint — or an explicitly named version under it — is not the caller's
    tenant's, and ``400`` when the endpoint has no discovered version to mark.
    """
    _ = tenant_slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)

    user_id = get_authenticated_user_id(auth_data)
    if not user_id:
        raise HTTPException(
            status_code=403,
            detail="a resolvable user is required to record a view",
        )

    # The version the caller acknowledges seeing: an explicit, endpoint-validated body value or,
    # by default, the endpoint's current snapshot.
    requested = body.version_id if body else None
    if requested:
        version = db.get_mcp_endpoint_version(str(endpoint_id), str(requested))
        if version is None:
            raise HTTPException(status_code=404, detail="MCP endpoint version not found")
        target_version_id = str(version["id"])
    else:
        target_version_id = endpoint.get("current_version_id")
        if not target_version_id:
            raise HTTPException(
                status_code=400,
                detail="endpoint has no discovered version to mark as seen",
            )

    row = db.record_mcp_endpoint_view(user_id, str(endpoint_id), str(target_version_id))
    return mcp_endpoint_view_response(str(endpoint_id), row)


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/insight/reliability",
    response_model=McpInsightReliabilityResponse,
)
async def get_mcp_endpoint_insight_reliability(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpInsightReliabilityResponse:
    """Return the endpoint's discovery and test-invocation reliability aggregates + health timeline.

    ``discovery`` folds ``mcp_discovery_jobs`` into per-state tallies, a success rate over terminal
    jobs, and run-latency statistics; ``invocation`` folds ``mcp_test_invocations`` into call/error
    tallies, an error rate, and latency percentiles (p50/p95/p99). ``health`` (MCAT-17.1) adds the
    recent per-job outcome timeline (newest-first, capped at the timeline window), a windowed
    availability percentage, and the endpoint's live quarantine / backoff state. An endpoint with no
    discovery or test history returns zero counts, an empty timeline, and empty (``None``) statistics
    — a ``200``, never a ``500``. Returns ``404`` when the endpoint is not the caller's tenant's.
    """
    _ = tenant_slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)

    discovery = compute_discovery_reliability(db.list_mcp_discovery_job_stats(str(endpoint_id)))
    invocation = compute_invocation_reliability(db.list_mcp_invocation_stats(str(endpoint_id)))
    timeline = compute_discovery_timeline(
        db.list_mcp_discovery_job_timeline(str(endpoint_id), DISCOVERY_TIMELINE_WINDOW),
        window=DISCOVERY_TIMELINE_WINDOW,
    )
    return McpInsightReliabilityResponse(
        endpoint_id=str(endpoint_id),
        discovery=McpDiscoveryReliabilityOut.model_validate(discovery.as_dict()),
        invocation=McpInvocationReliabilityOut.model_validate(invocation.as_dict()),
        health=mcp_discovery_health_out(timeline.as_dict(), endpoint),
    )


@mcp_endpoints_router.get(
    "/{tenant_slug}/insight/catalog",
    response_model=McpInsightCatalogResponse,
)
async def get_mcp_catalog_insight(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpInsightCatalogResponse:
    """Return a tenant-wide roll-up of the caller's live MCP catalog (feeds 18.1).

    Aggregates every live endpoint the caller's tenant owns: total / published / discovered counts,
    the per-kind capability ``type_counts`` summed across each endpoint's current surface, the
    average quality score, and the A-F ``grade_distribution``. Like every catalog route, scoping
    comes from the token's ``tenant_id`` — never the URL slug — so the aggregate only ever spans the
    caller's own catalog (an empty catalog returns zeroes, not a ``404``).
    """
    _ = tenant_slug  # scoping comes from the token, not the URL slug
    tenant_id = str(auth_data["tenant_id"])
    row = db.get_mcp_catalog_insight(tenant_id)
    return mcp_catalog_insight_from_row(row)
