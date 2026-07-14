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
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

import jsonschema
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from psycopg2 import errors as pg_errors

from .auth import get_authenticated_user_id, validate_authentication
from .config import settings
from .database import db
from .embedding import get_embedding
from .mcp_auth import (
    CredentialPayloadError,
    build_auth_headers,
    validate_credential_payload,
)
from .mcp_capability_graph import compute_capability_graph
from .mcp_catalog_inventory import inventory_record, stream_csv, stream_json
from .mcp_change_severity import severity_counts
from .mcp_client.normalize import (
    ITEM_TYPE_PROMPT,
    ITEM_TYPE_RESOURCE,
    ITEM_TYPE_TOOL,
)
from .mcp_credential_crypto import CredentialEncryptionError, seal_credential_payload
from .mcp_credentials import load_endpoint_auth_headers
from .mcp_digest_service import generate_server_digest
from .mcp_discovery_engine import (
    compare_endpoint_versions,
    reconstruct_surface,
    trigger_discovery,
)
from .mcp_duplicate_detection import mcp_duplicate_report_from_rows
from .mcp_freshness_report import mcp_freshness_report_from_rows
from .mcp_facets import FacetValidationError, normalize_catalog_facet_filters
from .mcp_insight_aggregation import (
    DISCOVERY_TIMELINE_WINDOW,
    TOOL_LATENCY_WINDOW_DAYS,
    build_capability_embedding_text,
    build_tool_examples,
    capability_name_set,
    compute_capability_overlap,
    compute_discovery_reliability,
    compute_discovery_timeline,
    compute_endpoint_percentile_axes,
    compute_invocation_reliability,
    compute_peer_percentiles,
    compute_tool_reliability,
    compute_trust_profile,
    group_cross_server_capability_hits,
    mcp_auth_posture,
    merge_cross_server_capability_hits,
    rank_embedding_neighbors,
)
from .mcp_invoke import get_prompt, invoke_tool, read_resource
from .mcp_license_signals import detect_license_signals
from .mcp_lifecycle_signals import detect_lifecycle_signals
from .mcp_provenance import build_endpoint_provenance
from .mcp_report_card import (
    build_report_card,
    render_report_html,
    render_report_markdown,
)
from .lint_evidence import SUBJECT_MCP_ENDPOINT_VERSION
from .mcp_score import score_mcp_surface
from .mcp_surface_metrics import compute_surface_metrics
from .models import (
    LintEvidenceResponse,
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
    McpFacetedSearchResponse,
    McpInsightCatalogResponse,
    McpInsightEvolutionResponse,
    McpInsightGraphResponse,
    McpInsightPercentileResponse,
    McpInsightReliabilityResponse,
    McpInsightSurfaceResponse,
    McpInsightTrustResponse,
    McpInvocationReliabilityOut,
    McpLintReportResponse,
    McpPeerPercentileOut,
    McpCrossServerCapabilitySearchResponse,
    McpCapabilityDirectoryResponse,
    McpCapabilityDirectorySort,
    McpCapabilityDirectoryDirection,
    McpCapabilityDirectoryType,
    McpDuplicateReportResponse,
    McpFreshnessReportResponse,
    McpSearchResponse,
    McpSearchScope,
    McpSearchVisibility,
    McpServerDigestGenerateResponse,
    McpServerDigestResponse,
    McpSimilarEmbeddingNeighborOut,
    McpSimilarOverlapNeighborOut,
    McpSimilarReindexResponse,
    McpSimilarServersResponse,
    McpToolExampleOut,
    McpToolInvocationReliabilityOut,
    McpTrustProfileOut,
    McpTypeCountsOut,
    McpVersionChangesResponse,
    McpVersionCompareResponse,
    McpVersionRef,
    group_mcp_browse_endpoints,
    mcp_capability_graph_out,
    mcp_catalog_insight_from_row,
    mcp_change_counts,
    mcp_cross_server_capability_search_response_from_groups,
    mcp_capability_directory_response_from_rows,
    mcp_credential_status_from_row,
    mcp_discovery_health_out,
    mcp_discovery_job_out_from_row,
    mcp_discovery_job_status_from_row,
    mcp_endpoint_digest_response,
    mcp_endpoint_out_from_row,
    mcp_endpoint_test_response_from_result,
    mcp_endpoint_view_response,
    mcp_evolution_point_from_row,
    mcp_faceted_search_response_from_bundle,
    lint_evidence_response_from_rows,
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
    "/{tenant_slug}/data-quality/duplicates",
    response_model=McpDuplicateReportResponse,
)
async def list_mcp_duplicate_report(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpDuplicateReportResponse:
    """Advisory duplicate review list for the caller's catalog (V2-MCP-36.1 / MCAT-22.1).

    Flags endpoints that share a normalized ``endpoint_url``, the same network host (when
    fingerprints do not prove they are distinct), or an identical current ``surface_fingerprint``.
    Published endpoints in other tenants that match the same keys are returned as cross-tenant hints.
    The report is advisory only — nothing is merged automatically.
    """
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    candidates = db.list_mcp_duplicate_candidates(tenant_id)
    foreign = db.list_published_mcp_duplicate_hints(tenant_id)
    return mcp_duplicate_report_from_rows(
        tenant_id=tenant_id,
        candidates=candidates,
        foreign_published=foreign,
    )


@mcp_endpoints_router.get(
    "/{tenant_slug}/data-quality/freshness",
    response_model=McpFreshnessReportResponse,
)
async def list_mcp_freshness_report(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpFreshnessReportResponse:
    """Freshness report for the caller's catalog (V2-MCP-36.2 / MCAT-22.2).

    Flags endpoints that are overdue for re-discovery, in failure backoff/quarantine, or on a
    failing streak. Each flagged row carries a ``last_known_good_at`` anchor from the current
    snapshot (when one exists) plus the live cadence/backoff fields from ``mcp_endpoints``.
    Healthy, in-cadence endpoints are omitted.
    """
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    candidates = db.list_mcp_freshness_candidates(tenant_id)
    return mcp_freshness_report_from_rows(
        default_cadence_seconds=int(settings.mcp_discovery_default_cadence_seconds),
        candidates=candidates,
    )


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


#: Raw capability hits to gather from each search channel before grouping. Large enough that
#: server-level pagination still finds matches when many capabilities share one endpoint.
_CROSS_SERVER_CAPABILITY_RAW_LIMIT = 200

_MCP_CAPABILITY_DIRECTORY_SORTS = frozenset({"server", "name", "type"})
_MCP_CAPABILITY_DIRECTORY_DIRECTIONS = frozenset({"asc", "desc"})


@mcp_endpoints_router.get(
    "/{tenant_slug}/capabilities",
    response_model=McpCapabilityDirectoryResponse,
)
async def list_mcp_capability_directory(
    tenant_slug: str,
    name: Optional[str] = Query(
        None,
        description="Case-insensitive substring match on capability name or title.",
    ),
    capability_type: Optional[McpCapabilityDirectoryType] = Query(
        None,
        alias="type",
        description="Restrict to one capability kind (tool/resource/resource_template/prompt).",
    ),
    endpoint_id: Optional[str] = Query(
        None, description="Restrict to capabilities from one cataloged server."
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
    sort: McpCapabilityDirectorySort = Query(
        "server",
        description="Sort column: server (default), name, or type.",
    ),
    direction: McpCapabilityDirectoryDirection = Query(
        "asc",
        description="Sort direction: asc (default) or desc.",
    ),
    limit: int = Query(50, ge=1, le=200, description="Maximum items to return."),
    offset: int = Query(0, ge=0, description="Items to skip (pagination)."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpCapabilityDirectoryResponse:
    """Capability directory — paginated index of every live tool/resource/prompt (MCAT-21.4).

    A browsable "what can be done" index across the caller's catalog: every capability item from
    each endpoint's *current* snapshot, with enough owning-server context to link back without a
    second read. ``name`` matches item name or title case-insensitively (substring); ``type``,
    ``endpoint_id``, and the usual host/category/grade/visibility filters compose (ANDed). Like
    every catalog route, scoping comes from the token's ``tenant_id`` — never the URL slug.
    """
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])

    if sort not in _MCP_CAPABILITY_DIRECTORY_SORTS:
        raise HTTPException(status_code=422, detail=f"invalid sort: {sort}")
    if direction not in _MCP_CAPABILITY_DIRECTORY_DIRECTIONS:
        raise HTTPException(status_code=422, detail=f"invalid direction: {direction}")

    name_pattern = name.strip() if name and name.strip() else None
    host_filter = host.strip() if host and host.strip() else None
    category_filter = category.strip() if category and category.strip() else None
    grade_filter = grade.strip() if grade and grade.strip() else None

    rows, total = db.list_mcp_capability_directory(
        tenant_id,
        name_pattern=name_pattern,
        item_type=capability_type,
        endpoint_id=endpoint_id,
        host=host_filter,
        category=category_filter,
        grade=grade_filter,
        visibility=visibility,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    return mcp_capability_directory_response_from_rows(
        rows=rows, total=total, limit=limit, offset=offset
    )


@mcp_endpoints_router.get(
    "/{tenant_slug}/capabilities/search",
    response_model=McpCrossServerCapabilitySearchResponse,
)
async def cross_server_capability_search(
    tenant_slug: str,
    q: str = Query(
        ...,
        min_length=1,
        description="Free-text query (websearch syntax for keyword matches; also embedded for semantic).",
    ),
    scope: Optional[McpSearchScope] = Query(
        None,
        description=(
            "Restrict to one capability kind (tool/resource/resource_template/prompt). "
            "Omit to search all capability kinds."
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
    limit: int = Query(20, ge=1, le=100, description="Maximum server groups to return."),
    offset: int = Query(0, ge=0, description="Server groups to skip (pagination)."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpCrossServerCapabilitySearchResponse:
    """Cross-server capability search — keyword + semantic, grouped by owning server (MCAT-21.2).

    Answers "which servers offer a capability like X?" across the caller's catalog. **Keyword**
    matches use the V127 capability-item ``tsvector`` GIN index (``websearch_to_tsquery``). When
    ``APIOME_MCP_SIMILARITY_EMBEDDINGS_ENABLED`` is on and the Ollama embedding service is
    reachable, **semantic** matches also rank stored per-item embeddings (V149) by cosine
    similarity. Each distinct capability appears once with ``match_source`` ``keyword``,
    ``semantic``, or ``both``.

    **Ranking** (MCAT-9.7 / MCAT-21.2): per-item ``relevance`` is ``max(fts_rank,
    cosine_similarity)``; server groups sort by their best item relevance, then letter grade (A
    first, ungraded last), then score, then endpoint name; capabilities within a group sort by
    relevance desc, then ordinal. ``visibility`` and tenant scoping are enforced like the flat
    search route — only the caller's own catalog is searched. An empty or whitespace-only query, or
    a query that matches nothing, returns ``groups: []`` (not an error).
    """
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])

    if scope == "endpoint":
        raise HTTPException(
            status_code=422,
            detail="scope=endpoint is not supported for cross-server capability search",
        )

    query = q.strip()
    host_filter = host.strip() if host and host.strip() else None
    category_filter = category.strip() if category and category.strip() else None
    grade_filter = grade.strip() if grade and grade.strip() else None

    if not query:
        return mcp_cross_server_capability_search_response_from_groups(
            query=q,
            scope=scope,
            semantic_enabled=settings.mcp_similarity_embeddings_enabled,
            limit=limit,
            offset=offset,
            total=0,
            groups=[],
        )

    item_type = scope  # None → all capability kinds
    keyword_rows = db.search_mcp_capability_items(
        tenant_id,
        query,
        item_type=item_type,
        host=host_filter,
        category=category_filter,
        grade=grade_filter,
        visibility=visibility,
        limit=_CROSS_SERVER_CAPABILITY_RAW_LIMIT,
        offset=0,
    )

    semantic_rows: List[Dict[str, Any]] = []
    semantic_enabled = settings.mcp_similarity_embeddings_enabled
    if semantic_enabled:
        query_embedding = get_embedding(query)
        if query_embedding:
            semantic_rows = db.search_mcp_capability_items_semantic(
                tenant_id,
                query_embedding,
                item_type=item_type,
                host=host_filter,
                category=category_filter,
                grade=grade_filter,
                visibility=visibility,
                limit=_CROSS_SERVER_CAPABILITY_RAW_LIMIT,
            )

    merged = merge_cross_server_capability_hits(keyword_rows, semantic_rows)
    page_groups, total = group_cross_server_capability_hits(
        merged, limit=limit, offset=offset
    )
    return mcp_cross_server_capability_search_response_from_groups(
        query=q,
        scope=scope,
        semantic_enabled=semantic_enabled,
        limit=limit,
        offset=offset,
        total=total,
        groups=page_groups,
    )


@mcp_endpoints_router.get(
    "/{tenant_slug}/facets",
    response_model=McpFacetedSearchResponse,
)
async def faceted_mcp_catalog_search(
    tenant_slug: str,
    grade: Optional[List[str]] = Query(
        None, description="Grade facet: A-F letters (any case) and/or 'ungraded'. Repeatable."
    ),
    transport: Optional[List[str]] = Query(
        None, description="Transport facet: streamable_http / sse / stdio. Repeatable."
    ),
    category: Optional[List[str]] = Query(
        None,
        description=(
            "Category facet: category names (case-insensitive) and/or 'uncategorized'. Repeatable."
        ),
    ),
    safety: Optional[List[str]] = Query(
        None,
        description=(
            "Safety-posture facet: 'has_destructive' (a tool asserts destructiveHint) and/or "
            "'read_only_only' (every tool asserts readOnlyHint). Repeatable."
        ),
    ),
    complexity: Optional[List[str]] = Query(
        None,
        description="Complexity-band facet: simple / moderate / complex / unknown. Repeatable.",
    ),
    protocol: Optional[List[str]] = Query(
        None,
        description=(
            "Protocol-version facet: exact reported versions (e.g. 2025-06-18) and/or 'unknown'. "
            "Repeatable."
        ),
    ),
    health: Optional[List[str]] = Query(
        None,
        description=(
            "Discovery-health facet: healthy / failing / undiscovered / disabled / quarantined. "
            "Repeatable."
        ),
    ),
    visibility: Optional[McpSearchVisibility] = Query(
        None,
        description="Filter to 'private' or 'public' endpoints within the caller's own catalog.",
    ),
    limit: int = Query(100, ge=1, le=500, description="Maximum endpoints to return."),
    offset: int = Query(0, ge=0, description="Endpoints to skip (pagination)."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpFacetedSearchResponse:
    """Faceted search over the caller's MCP catalog with live facet counts (V2-MCP-35.1 / MCAT-21.1).

    The catalog's rich metrics as queryable facets: filter by grade band, transport, category,
    safety posture, complexity band, protocol version, and discovery health. Filters **AND across
    facets** and **OR within a facet**; the response carries the matching endpoint page (browse-
    shaped rows, each with its facet fields) plus per-dimension bucket counts aggregated over the
    same filtered set, so the counts are live. Every bucket label — including the NULL-bucket
    sentinels ``ungraded`` / ``uncategorized`` / ``unknown`` — is itself a valid filter value.

    Like every catalog route, scoping comes from the token's ``tenant_id`` — never the URL slug —
    so the search only ever spans the caller's own catalog, and ``visibility`` narrows the
    caller's *own* private/public endpoints. A filter combination matching nothing returns an
    empty page with zeroed counts, not an error; an invalid facet value is a ``422``.
    """
    _ = tenant_slug  # scoping comes from the token, not the URL slug
    tenant_id = str(auth_data["tenant_id"])

    try:
        filters = normalize_catalog_facet_filters(
            grade=grade,
            transport=transport,
            category=category,
            safety=safety,
            complexity=complexity,
            protocol=protocol,
            health=health,
        )
    except FacetValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    bundle = db.search_mcp_catalog_faceted(
        tenant_id,
        grades=filters.grades,
        transports=filters.transports,
        categories=filters.categories,
        safety=filters.safety,
        complexity=filters.complexity,
        protocols=filters.protocols,
        health=filters.health,
        visibility=visibility,
        limit=limit,
        offset=offset,
    )
    return mcp_faceted_search_response_from_bundle(bundle, limit=limit, offset=offset)


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
    if "discovery_cadence_seconds" in body.model_fields_set:
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


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}/lint/evidence",
    response_model=LintEvidenceResponse,
)
async def get_mcp_endpoint_version_lint_evidence(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    version_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> LintEvidenceResponse:
    """Return the immutable lint evidence recorded for a version snapshot (CLX-1.1, #4848).

    Lists every evidence run captured for the snapshot — provenance (scanner, adapter,
    profile, fingerprints), outcome, normalized findings, and coverage — plus a per-scanner
    coverage summary in which a scanner that never ran reads as ``not_run`` (never as clean).
    Raw output artifacts are access-controlled: responses expose only their availability,
    never the storage reference or command metadata. 404 when the endpoint — or the version
    under it — is not the caller's tenant's.
    """
    _ = tenant_slug
    _require_tenant_endpoint(auth_data, endpoint_id)
    version = db.get_mcp_endpoint_version(str(endpoint_id), str(version_id))
    if version is None:
        raise HTTPException(status_code=404, detail="MCP endpoint version not found")

    rows = db.list_lint_evidence_runs_for_mcp_version(str(version_id))
    return lint_evidence_response_from_rows(
        SUBJECT_MCP_ENDPOINT_VERSION, str(version_id), rows
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
    availability percentage, and the endpoint's live quarantine / backoff state. ``tools``
    (MCAT-17.2) adds a per-tool latency & error-rate breakdown over the recent
    :data:`TOOL_LATENCY_WINDOW_DAYS`-day window — p50/p95/p99 and error rate per tool, a latency
    distribution, and the endpoint-wide totals. An endpoint with no discovery or test history returns
    zero counts, an empty timeline, an empty tool list, and empty (``None``) statistics — a ``200``,
    never a ``500``. Returns ``404`` when the endpoint is not the caller's tenant's.
    """
    _ = tenant_slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)

    discovery = compute_discovery_reliability(db.list_mcp_discovery_job_stats(str(endpoint_id)))
    invocation = compute_invocation_reliability(db.list_mcp_invocation_stats(str(endpoint_id)))
    timeline = compute_discovery_timeline(
        db.list_mcp_discovery_job_timeline(str(endpoint_id), DISCOVERY_TIMELINE_WINDOW),
        window=DISCOVERY_TIMELINE_WINDOW,
    )
    tools = compute_tool_reliability(
        db.list_mcp_tool_invocation_stats(str(endpoint_id), TOOL_LATENCY_WINDOW_DAYS),
        window_days=TOOL_LATENCY_WINDOW_DAYS,
    )
    return McpInsightReliabilityResponse(
        endpoint_id=str(endpoint_id),
        discovery=McpDiscoveryReliabilityOut.model_validate(discovery.as_dict()),
        invocation=McpInvocationReliabilityOut.model_validate(invocation.as_dict()),
        health=mcp_discovery_health_out(timeline.as_dict(), endpoint),
        tools=McpToolInvocationReliabilityOut.model_validate(tools.as_dict()),
    )


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/insight/trust",
    response_model=McpInsightTrustResponse,
)
async def get_mcp_endpoint_insight_trust(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpInsightTrustResponse:
    """Return the endpoint's composite trust profile — five normalized 0-100 axes (MCAT-17.4).

    The capstone of the single-server insight view: a synthesized "trust glance" across five axes,
    each reading one already-computed metric layer —

    * **quality** — the current snapshot's stored lint score;
    * **safety** — behavioural-annotation coverage crossed with the endpoint's auth posture and its
      destructive-tool count;
    * **documentation** — the snapshot's documentation coverage;
    * **stability** — the breaking-change rate across the evolution series' snapshot transitions;
    * **responsiveness** — the test-invocation error rate and p95 latency.

    Every axis whose input is missing (a never-scored, never-changed, or never-tested server) is
    returned as an explicit *gap* — ``value: null`` with ``available: false`` — never a zero, and the
    ``overall`` composite averages only the available axes. This is deliberately a **heuristic**
    composite the panel labels as such, not an official rating. A never-discovered endpoint yields an
    all-gap profile (a ``200``), never a ``500``. Returns ``404`` when the endpoint is not the
    caller's tenant's. A GET stays read-only.
    """
    _ = tenant_slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)

    # Quality / safety / documentation all read the current snapshot's surface. A never-discovered
    # endpoint simply leaves these inputs empty, so those axes come back as gaps (a 200), not a 500.
    current_version_id = endpoint.get("current_version_id")
    quality_score: Optional[int] = None
    quality_grade: Optional[str] = None
    annotation_coverage: Dict[str, Any] = {}
    documentation_coverage: Dict[str, Any] = {}
    destructive_tool_count = 0
    version_id: Optional[str] = None
    if current_version_id:
        version = db.get_mcp_endpoint_version(str(endpoint_id), str(current_version_id))
        if version is not None:
            version_id = str(version["id"])
            quality_score = version.get("score")
            quality_grade = version.get("grade")
            items = db.get_mcp_capability_items(version_id)
            surface = reconstruct_surface(version, items)
            metrics = compute_surface_metrics(surface)
            annotation_coverage = metrics.annotation_coverage.as_dict()
            documentation_coverage = metrics.documentation_coverage.as_dict()
            # A tool is "destructive" when it asserts ``destructiveHint: true`` as a JSON boolean —
            # the same strict definition the surface metrics / UI safety matrix use.
            destructive_tool_count = sum(
                1
                for tool in surface.tools
                if isinstance(tool.annotations, Mapping)
                and tool.annotations.get("destructiveHint") is True
            )

    # Safety cross-references the endpoint's auth posture (anonymous when it has no credential, i.e.
    # is reachable with no secret). The redacted credential read never exposes the secret itself.
    credential = db.get_mcp_endpoint_credentials(str(endpoint_id))
    auth_type = credential.get("auth_type") if credential else None
    auth_posture = mcp_auth_posture(auth_type)

    # Stability reads the per-snapshot breaking-change classification across the evolution series;
    # one classification per *transition* (every snapshot after the first). The change rows are
    # bucketed by version in a single query, mirroring the evolution route.
    series = db.get_mcp_evolution_series(str(endpoint_id))
    changes_by_version: Dict[str, List[Dict[str, Any]]] = {}
    for change in db.get_mcp_version_changes_for_endpoint(str(endpoint_id)):
        changes_by_version.setdefault(str(change["version_id"]), []).append(change)
    change_severities = [
        severity_counts(changes_by_version.get(str(row["id"]), [])) for row in series[1:]
    ]

    # Responsiveness reads the test-invocation reliability (error rate + latency percentiles).
    invocation = compute_invocation_reliability(db.list_mcp_invocation_stats(str(endpoint_id)))

    profile = compute_trust_profile(
        quality_score=quality_score,
        quality_grade=quality_grade,
        annotation_coverage=annotation_coverage,
        documentation_coverage=documentation_coverage,
        destructive_tool_count=destructive_tool_count,
        auth_posture=auth_posture,
        change_severities=change_severities,
        invocation=invocation.as_dict(),
    )
    return McpInsightTrustResponse(
        endpoint_id=str(endpoint_id),
        version_id=version_id,
        auth_type=auth_type,
        profile=McpTrustProfileOut.model_validate(profile.as_dict()),
    )


# ---------------------------------------------------------------------------------------------------
# Server report-card export (V2-MCP-33.1 / MCAT-19.1, #4650).
#
# Serializes the single-server Insight assessment — identity (15.1), grade + score breakdown (17.3),
# capability surface + safety posture (15.3/15.4), documentation coverage (15.5), the composite trust
# radar (17.4), and the change-since-previous summary — into a self-contained Markdown or HTML
# document the caller can share outside the app. It reuses the exact metrics the Insight endpoints
# already compute (:mod:`app.mcp_surface_metrics`, :mod:`app.mcp_insight_aggregation`, the persisted
# ``mcp_version_scores.report`` and change rows); the pure :mod:`app.mcp_report_card` layer only
# shapes and renders. Visibility is honoured by the same token-tenant scoping as every other endpoint
# route (a private endpoint's report is 404 to a non-tenant caller), and no secret ever reaches the
# report — only the auth *posture* and ``auth_type`` label. "PDF" is the browser's print-to-PDF of
# the HTML variant, whose embedded ``@media print`` stylesheet makes it a one-page document.
# ---------------------------------------------------------------------------------------------------

#: MIME type + file extension per supported report format (the query ``format`` selects one).
_REPORT_FORMATS = {
    "markdown": ("text/markdown; charset=utf-8", "md"),
    "md": ("text/markdown; charset=utf-8", "md"),
    "html": ("text/html; charset=utf-8", "html"),
}


def _report_trust_profile(
    endpoint_id: str,
    version: Optional[Dict[str, Any]],
    surface_metrics_obj: Optional[Any],
    auth_posture: str,
) -> Optional[Dict[str, Any]]:
    """Compute the endpoint's composite trust profile for the reported version (MCAT-17.4).

    Mirrors the ``…/insight/trust`` route's assembly, but keyed on the *reported* snapshot rather
    than always the current one: quality/safety/documentation read that snapshot's surface, while
    stability (breaking-change rate across the evolution series) and responsiveness (test-invocation
    error rate + latency) are endpoint-level. Returns the profile ``as_dict()``, or ``None`` when
    there is no discovered version to anchor it.

    Args:
        endpoint_id: The owning endpoint.
        version: The reported version row, or ``None`` (never discovered → no profile).
        surface_metrics_obj: The already-computed :class:`SurfaceMetrics` for that version (reused
            so the surface is reconstructed once), or ``None``.
        auth_posture: The endpoint's ``anonymous`` / ``authenticated`` posture.

    Returns:
        The trust-profile dict, or ``None`` when undiscovered.
    """
    if version is None or surface_metrics_obj is None:
        return None

    annotation_coverage = surface_metrics_obj.annotation_coverage.as_dict()
    documentation_coverage = surface_metrics_obj.documentation_coverage.as_dict()
    destructive_tool_count = int(annotation_coverage.get("destructive_hint") or 0)

    # Stability: one breaking-change classification per snapshot transition across the series.
    series = db.get_mcp_evolution_series(endpoint_id)
    changes_by_version: Dict[str, List[Dict[str, Any]]] = {}
    for change in db.get_mcp_version_changes_for_endpoint(endpoint_id):
        changes_by_version.setdefault(str(change["version_id"]), []).append(change)
    change_severities = [
        severity_counts(changes_by_version.get(str(row["id"]), [])) for row in series[1:]
    ]

    invocation = compute_invocation_reliability(db.list_mcp_invocation_stats(endpoint_id))

    profile = compute_trust_profile(
        quality_score=version.get("score"),
        quality_grade=version.get("grade"),
        annotation_coverage=annotation_coverage,
        documentation_coverage=documentation_coverage,
        destructive_tool_count=destructive_tool_count,
        auth_posture=auth_posture,
        change_severities=change_severities,
        invocation=invocation.as_dict(),
    )
    return profile.as_dict()


@mcp_endpoints_router.get("/{tenant_slug}/endpoints/{endpoint_id}/report")
async def export_mcp_endpoint_report(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    format: str = Query(
        "markdown",
        description="Report format: 'markdown' (alias 'md') or 'html'.",
    ),
    version_id: Optional[uuid.UUID] = Query(
        None,
        description="Which snapshot to report; omit to report the endpoint's current surface.",
    ),
    include_cataloger_notes: bool = Query(
        False,
        description="When true, include tenant cataloger commentary (not server-reported data).",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Export a self-contained one-page report card for an endpoint version (MCAT-19.1).

    Serializes the same panels the in-app Insight view shows — identity, grade + score breakdown,
    capability surface, safety posture, documentation coverage, license & terms signals,
    deprecation & lifecycle signals, the composite trust radar, and the change-since-previous
    summary — into a shareable **Markdown**
    or **HTML** document (the HTML
    carries a print stylesheet, so "PDF" is the browser's print-to-PDF of the same file). No new
    metric is computed: the route fetches the values the Insight endpoints already produce and the
    pure :mod:`app.mcp_report_card` layer renders them.

    Visibility is honoured by the standard token-tenant scoping — a cross-tenant (or private,
    non-tenant) endpoint id reads as ``404``. A **never-discovered or never-scored** endpoint yields
    a graceful *partial* report (identity present; the unavailable sections say so) rather than an
    error. No credential secret ever reaches the report — only the auth posture and ``auth_type``.

    Args:
        tenant_slug: Informational; scoping comes from the validated token's tenant.
        endpoint_id: The endpoint to report on.
        format: ``markdown`` / ``md`` / ``html`` (``400`` on anything else).
        version_id: The snapshot to report; defaults to the endpoint's current surface.
        auth_data: The validated caller identity (also what enforces visibility).

    Returns:
        A ``Response`` carrying the rendered document with the right ``Content-Type`` and an
        ``attachment`` ``Content-Disposition`` filename.
    """
    _ = tenant_slug
    fmt = (format or "markdown").strip().lower()
    if fmt not in _REPORT_FORMATS:
        raise HTTPException(
            status_code=400,
            detail="unsupported report format; use 'markdown' or 'html'",
        )
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)

    # Resolve the reported snapshot. An explicit version_id that is not this endpoint's is a 404;
    # an omitted one with no current version simply yields a partial (never-discovered) report.
    target_version_id = (
        str(version_id) if version_id is not None else endpoint.get("current_version_id")
    )
    version: Optional[Dict[str, Any]] = None
    if target_version_id:
        version = db.get_mcp_endpoint_version(str(endpoint_id), str(target_version_id))
        if version is None:
            raise HTTPException(status_code=404, detail="MCP endpoint version not found")

    # Surface-derived sections (surface / safety / documentation / trust) — reconstructed once.
    surface_metrics_obj = None
    surface_metrics_dict: Optional[Dict[str, Any]] = None
    items: List[Dict[str, Any]] = []
    if version is not None:
        items = db.get_mcp_capability_items(str(version["id"]))
        surface = reconstruct_surface(version, items)
        surface_metrics_obj = compute_surface_metrics(surface)
        surface_metrics_dict = surface_metrics_obj.as_dict()

    # Score breakdown — the persisted lint report (None until the snapshot is scored).
    score_report: Optional[Dict[str, Any]] = None
    if version is not None:
        score_row = db.get_mcp_version_score(str(version["id"]))
        if score_row is not None:
            score_report = score_row.get("report")

    # Auth posture (never the secret) — anonymous when the endpoint has no stored credential.
    credential = db.get_mcp_endpoint_credentials(str(endpoint_id))
    auth_type = credential.get("auth_type") if credential else None
    auth_posture = mcp_auth_posture(auth_type)

    trust_profile = _report_trust_profile(
        str(endpoint_id), version, surface_metrics_obj, auth_posture
    )

    # License & terms signals (V2-MCP-34.3) — the pure detector over the snapshot's advertised
    # text. Runs whenever a snapshot exists: a "nothing found" result is a real section (status
    # "not stated"), not a missing one; only a never-discovered endpoint has no report.
    license_signals: Optional[Dict[str, Any]] = None
    if version is not None:
        branding = version.get("server_branding") or {}
        license_signals = detect_license_signals(
            instructions=version.get("instructions"),
            server_title=version.get("server_title"),
            website_url=branding.get("website_url") if isinstance(branding, dict) else None,
        ).as_dict()

    # Deprecation & lifecycle signals (V2-MCP-34.4) — the pure detector over the snapshot's
    # capability items (already fetched above for the surface metrics). Same asymmetry as the
    # license section: "no signals" is a real section whose wording is never a "stable" claim;
    # only a never-discovered endpoint has no report.
    lifecycle_signals: Optional[Dict[str, Any]] = None
    if version is not None:
        lifecycle_signals = detect_lifecycle_signals(items).as_dict()

    # Provenance (V2-MCP-34.5) — how the endpoint was added and which run produced each
    # snapshot, assembled by the pure layer from the stored version history and the
    # per-trigger job tallies. Always present: added_via is a fact from registration,
    # so even a never-discovered endpoint has a provenance section.
    provenance = build_endpoint_provenance(
        endpoint,
        db.list_mcp_endpoint_versions(str(endpoint_id)),
        db.list_mcp_discovery_trigger_stats(str(endpoint_id)),
    ).as_dict()

    # Change-since-previous — the stored previous → this diff rows and their severity roll-up.
    change_rows: List[Dict[str, Any]] = (
        db.get_mcp_version_changes(str(version["id"])) if version is not None else []
    )
    change_severity = severity_counts(change_rows) if change_rows else None

    cataloger_note_rows: Optional[List[Dict[str, Any]]] = None
    if include_cataloger_notes:
        cataloger_note_rows = db.list_mcp_endpoint_notes(
            str(auth_data["tenant_id"]), str(endpoint_id)
        )

    card = build_report_card(
        endpoint=endpoint,
        version=version,
        is_current=bool(version)
        and str(version["id"]) == str(endpoint.get("current_version_id")),
        score_report=score_report,
        surface_metrics=surface_metrics_dict,
        license_signals=license_signals,
        lifecycle_signals=lifecycle_signals,
        provenance=provenance,
        trust_profile=trust_profile,
        change_rows=change_rows,
        change_severity=change_severity,
        auth_posture=auth_posture,
        auth_type=auth_type,
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        cataloger_notes=cataloger_note_rows,
    )

    body = render_report_html(card) if fmt == "html" else render_report_markdown(card)
    media_type, ext = _REPORT_FORMATS[fmt]
    slug = endpoint.get("slug") or "endpoint"
    seq = version.get("version_seq") if version else None
    filename = f"report-card-{slug}" + (f"-v{seq}" if seq is not None else "") + f".{ext}"
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------------------------------
# Catalog inventory export (V2-MCP-33.2 / MCAT-19.2, #4651).
#
# Analysts want the whole catalog as data (a spreadsheet, a notebook), not the browse UI. This route
# streams a tenant-scoped CSV or JSON of every cataloged endpoint with the key columns — name, host,
# transport, category, visibility, current grade/score, per-kind capability counts, last discovery
# status/time, and a derived health label. The catalog is walked one bounded keyset page at a time
# (:meth:`Database.list_mcp_endpoints_export_page`) and serialized incrementally by the pure
# :mod:`app.mcp_catalog_inventory` layer, so a large catalog streams without ever loading every row
# into memory. Visibility is honoured the same way every catalog route honours it — scoping comes
# from the validated token's tenant, never the URL slug — and only the endpoint *host* is exported
# (never the stored URL, which may embed a credential). ``scope=public`` is the published-only
# variant (what a public directory would show).
# ---------------------------------------------------------------------------------------------------

#: MIME type + file extension per supported inventory format (the query ``format`` selects one).
_INVENTORY_FORMATS = {
    "csv": ("text/csv; charset=utf-8", "csv"),
    "json": ("application/json; charset=utf-8", "json"),
}

#: Keyset page size for the streaming export — how many endpoints each DB round-trip fetches. Bounds
#: the export's peak memory to one page regardless of catalog size; a middle-of-the-road value that
#: keeps the round-trip count low without buffering a large catalog.
_INVENTORY_PAGE_SIZE = 500


def _iter_inventory_records(tenant_id: str, published_only: bool):
    """Yield every endpoint's inventory record for a tenant, one keyset page at a time (MCAT-19.2).

    Walks :meth:`Database.list_mcp_endpoints_export_page` by primary-key keyset: each page starts
    after the previous page's last ``id``, so the whole catalog is traversed without an OFFSET (which
    degrades on large tables) and without ever holding more than one page in memory. Iteration stops
    on the first short page (fewer rows than the page size), which can only be the last one.

    Args:
        tenant_id: The caller's token tenant; the sole cross-tenant scoping predicate.
        published_only: Restrict to published endpoints (the ``scope=public`` variant).

    Yields:
        One :func:`inventory_record` dict per endpoint, in ``id`` order.
    """
    after_id: Optional[str] = None
    while True:
        page = db.list_mcp_endpoints_export_page(
            tenant_id,
            published_only=published_only,
            after_id=after_id,
            limit=_INVENTORY_PAGE_SIZE,
        )
        for row in page:
            yield inventory_record(row)
        if len(page) < _INVENTORY_PAGE_SIZE:
            return
        after_id = str(page[-1]["id"])


@mcp_endpoints_router.get("/{tenant_slug}/endpoints:export")
async def export_mcp_catalog_inventory(
    tenant_slug: str,
    format: str = Query(
        "csv",
        description="Inventory format: 'csv' or 'json'.",
    ),
    scope: str = Query(
        "all",
        description=(
            "'all' exports the tenant's full catalog; 'public' exports only published endpoints "
            "(the public-directory variant)."
        ),
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> StreamingResponse:
    """Export the tenant's whole MCP catalog as streamed CSV or JSON data (MCAT-19.2).

    Serializes every cataloged endpoint into a flat inventory row — id, name, host, transport,
    category, visibility, published flag, current grade/score, per-kind capability counts (and their
    total), last discovery status/time, and a derived health label — as **CSV** (RFC-4180 escaped)
    or a **JSON** wrapper whose ``endpoints`` array carries the same fields. The catalog is walked one
    bounded keyset page at a time and the body is streamed, so a large catalog exports without
    loading every row into memory.

    Like every catalog route, scoping comes from the validated token's ``tenant_id`` — never the URL
    slug — so the export only ever contains the caller's own catalog. ``scope=public`` restricts the
    export to published endpoints (the published-only variant a public directory would show). Only
    each endpoint's *host* is exported; the stored URL, which may embed a credential, never appears.

    Args:
        tenant_slug: Informational; scoping comes from the validated token's tenant.
        format: ``csv`` or ``json`` (``400`` on anything else).
        scope: ``all`` (full catalog) or ``public`` (published-only); ``400`` on anything else.
        auth_data: The validated caller identity (also what enforces tenant scoping).

    Returns:
        A ``StreamingResponse`` carrying the rendered inventory with the right ``Content-Type`` and
        an ``attachment`` ``Content-Disposition`` filename.
    """
    _ = tenant_slug  # scoping comes from the token, not the URL slug
    fmt = (format or "csv").strip().lower()
    if fmt not in _INVENTORY_FORMATS:
        raise HTTPException(
            status_code=400,
            detail="unsupported inventory format; use 'csv' or 'json'",
        )
    scope_value = (scope or "all").strip().lower()
    if scope_value not in ("all", "public"):
        raise HTTPException(
            status_code=400,
            detail="unsupported scope; use 'all' or 'public'",
        )
    tenant_id = str(auth_data["tenant_id"])
    published_only = scope_value == "public"

    records = _iter_inventory_records(tenant_id, published_only)
    if fmt == "json":
        generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        body_iter = stream_json(
            records,
            tenant_slug=str(tenant_slug),
            scope=scope_value,
            generated_at=generated_at,
        )
    else:
        body_iter = stream_csv(records)

    media_type, ext = _INVENTORY_FORMATS[fmt]
    filename = f"catalog-inventory-{_slugify(str(tenant_slug))}" + (
        "-public" if published_only else ""
    ) + f".{ext}"
    return StreamingResponse(
        body_iter,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _cohort_member_axis_values(member: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Compute one cohort member's four ranked axis values (grade / safety / documentation / latency).

    Reuses the exact surface-metric and invocation derivations the trust route uses — the safety and
    documentation axes read a reconstructed surface's annotation & documentation coverage, and the
    latency axis reads the test-invocation p95 — then folds them through the pure
    :func:`compute_endpoint_percentile_axes`. A member with no current version (never discovered)
    simply yields gaps on the surface-derived axes rather than raising.

    Args:
        member: One entry from :meth:`Database.get_mcp_category_cohort` (its ``version`` / ``items`` /
            ``invocation_stats`` / ``score`` / ``grade`` / ``auth_type`` fields).

    Returns:
        A ``{axis_key: value_or_None}`` map over the four ranked axes for this member.
    """
    auth_posture = mcp_auth_posture(member.get("auth_type"))
    annotation_coverage: Dict[str, Any] = {}
    documentation_coverage: Dict[str, Any] = {}
    destructive_tool_count = 0
    version = member.get("version")
    if version:
        surface = reconstruct_surface(version, member.get("items") or [])
        metrics = compute_surface_metrics(surface)
        annotation_coverage = metrics.annotation_coverage.as_dict()
        documentation_coverage = metrics.documentation_coverage.as_dict()
        destructive_tool_count = sum(
            1
            for tool in surface.tools
            if isinstance(tool.annotations, Mapping)
            and tool.annotations.get("destructiveHint") is True
        )
    invocation = compute_invocation_reliability(member.get("invocation_stats") or [])
    return compute_endpoint_percentile_axes(
        score=member.get("score"),
        grade=member.get("grade"),
        annotation_coverage=annotation_coverage,
        documentation_coverage=documentation_coverage,
        destructive_tool_count=destructive_tool_count,
        auth_posture=auth_posture,
        invocation=invocation.as_dict(),
    )


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/insight/percentile",
    response_model=McpInsightPercentileResponse,
)
async def get_mcp_endpoint_insight_percentile(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpInsightPercentileResponse:
    """Return the endpoint's peer percentile & category ranking across four axes (MCAT-18.3).

    "Is this a good weather server?" needs a *peer baseline*, not an absolute grade. This ranks the
    endpoint against the other live endpoints in its catalog **category** — the *cohort* — on four
    axes: **grade** (the stored lint score), **safety** (annotation coverage crossed with the
    destructive/auth posture), **documentation** (documentation coverage), and **latency** (p95
    responsiveness). Each axis reuses the same derivation the endpoint's own trust profile shows, so a
    rank never disagrees with the numbers on its Insight tab, and each carries the server's percentile
    (share of the cohort at or below it), its rank, and the "top N%" the UI badges render.

    A blank/uncategorized endpoint is ranked within the uncategorized cohort. A **single-member**
    category is handled — the sole server is trivially the category leader. Any axis the endpoint has
    not measured (never scored, no tools, never tested) is an explicit *gap*, never a zero, so an
    undiscovered endpoint yields a coherent all-gap profile (a ``200``, never a ``500``). Scoping comes
    from the token's tenant, so the cohort never spans another tenant's catalog; returns ``404`` when
    the endpoint is not the caller's tenant's. A GET stays read-only, recomputed live as the catalog
    grows.
    """
    _ = tenant_slug  # scoping comes from the token, not the URL slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)
    category = endpoint.get("category")
    tenant_id = str(auth_data["tenant_id"])

    cohort = db.get_mcp_category_cohort(tenant_id, category)

    # Compute every cohort member's four axis values once, then rank the target within them. The
    # target is always a member of its own category cohort; the fallback keeps the response coherent
    # (all gaps) in the unlikely event the cohort read returns without it.
    axis_values_by_endpoint: Dict[str, Dict[str, Optional[float]]] = {
        str(member["endpoint_id"]): _cohort_member_axis_values(member) for member in cohort
    }
    target_axis_values = axis_values_by_endpoint.get(str(endpoint_id), {})
    cohort_axis_values: Dict[str, List[float]] = {}
    for values in axis_values_by_endpoint.values():
        for key, value in values.items():
            if value is not None:
                cohort_axis_values.setdefault(key, []).append(value)

    profile = compute_peer_percentiles(
        category=category,
        cohort_size=len(cohort),
        target_axis_values=target_axis_values,
        cohort_axis_values=cohort_axis_values,
    )
    return McpInsightPercentileResponse(
        endpoint_id=str(endpoint_id),
        profile=McpPeerPercentileOut.model_validate(profile.as_dict()),
    )


# ---------------------------------------------------------------------------------------------------
# "Similar servers" — capability overlap + semantic embeddings (V2-MCP-32.4 / MCAT-18.4, #4648).
#
# "Servers like this one" from two independent signals ranked against the caller's own live catalog:
# capability-name Jaccard *overlap* (always available — it reads the normalized capability items) and a
# *semantic* cosine nearest-neighbour over an optional per-snapshot capability embedding. The overlap
# math and the NN ranking live in the pure :mod:`app.mcp_insight_aggregation` layer; this route only
# fetches the candidate pool and shapes the result. When embeddings are disabled/unbackfilled the
# semantic list is simply empty and the feature falls back to overlap-only (never a 500).
# ---------------------------------------------------------------------------------------------------

#: How many similar servers each signal returns at most — the "similar servers" rail's top-N.
SIMILAR_SERVERS_LIMIT = 10


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/insight/similar",
    response_model=McpSimilarServersResponse,
)
async def get_mcp_endpoint_similar(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpSimilarServersResponse:
    """Return "servers like this one" from capability overlap + optional semantic embeddings (MCAT-18.4).

    Ranks the caller's other live endpoints against this one by two independent signals. **overlap** —
    always present — is the capability-name Jaccard overlap: peers sharing this server's tool / resource /
    prompt names, ranked by set-overlap, with the shared names surfaced (a server with nothing in common
    is not returned). **semantic** is a cosine nearest-neighbour over a per-snapshot capability embedding
    and is populated only when ``embeddings_enabled`` — the feature flag is on *and* both this endpoint
    and at least one peer carry a backfilled embedding. When embeddings are disabled or unbackfilled,
    ``semantic`` is empty and the endpoint page falls back to overlap-only (the "gracefully no-ops if
    embeddings are disabled" acceptance criterion). A never-discovered endpoint has no capabilities, so
    both lists are empty (a ``200``, never a ``500``). Scoping comes from the token's tenant, so neighbours
    never span another tenant's catalog; returns ``404`` when the endpoint is not the caller's tenant's. A
    GET stays read-only, recomputed live as the catalog grows.
    """
    _ = tenant_slug  # scoping comes from the token, not the URL slug
    _require_tenant_endpoint(auth_data, endpoint_id)
    tenant_id = str(auth_data["tenant_id"])

    candidates = db.get_mcp_similar_candidates(tenant_id)
    target_id = str(endpoint_id)
    target = next((c for c in candidates if c["endpoint_id"] == target_id), None)
    peers = [c for c in candidates if c["endpoint_id"] != target_id]

    target_names = (target or {}).get("capability_names") or []
    target_embedding = (target or {}).get("embedding")
    target_capability_count = len(capability_name_set(target_names))

    overlap = compute_capability_overlap(target_names, peers, limit=SIMILAR_SERVERS_LIMIT)

    # The semantic signal is active only when the flag is on and there are vectors on both sides to
    # compare — otherwise it is an explicit no-op (empty, embeddings_enabled=False), never an error.
    peer_has_embedding = any(c.get("embedding") for c in peers)
    embeddings_enabled = bool(
        settings.mcp_similarity_embeddings_enabled and target_embedding and peer_has_embedding
    )
    semantic = (
        rank_embedding_neighbors(target_embedding, peers, limit=SIMILAR_SERVERS_LIMIT)
        if embeddings_enabled
        else []
    )

    return McpSimilarServersResponse(
        endpoint_id=target_id,
        embeddings_enabled=embeddings_enabled,
        target_capability_count=target_capability_count,
        overlap=[McpSimilarOverlapNeighborOut.model_validate(n.as_dict()) for n in overlap],
        semantic=[McpSimilarEmbeddingNeighborOut.model_validate(n.as_dict()) for n in semantic],
    )


@mcp_endpoints_router.post(
    "/{tenant_slug}/endpoints/{endpoint_id}/insight/similar/reindex",
    response_model=McpSimilarReindexResponse,
)
async def reindex_mcp_endpoint_similar(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpSimilarReindexResponse:
    """(Re)compute and store this endpoint's current-snapshot capability embedding (MCAT-18.4).

    The backfill step behind the semantic similarity signal: it derives the deterministic capability text
    of the endpoint's current surface (its tool/resource/prompt names + descriptions), embeds it via the
    Ollama embedding service, and stores the vector on the snapshot (V143) so the ``insight/similar``
    semantic list can find it. Every non-success is a labelled no-op, not an error (always a ``200``): the
    feature flag being off, the endpoint having no discovered surface or no capabilities to embed, the
    embedding service being unreachable, or pgvector being unavailable each return ``reindexed=false`` with
    a ``detail`` explaining why. Returns ``404`` when the endpoint is not the caller's tenant's.
    """
    _ = tenant_slug  # scoping comes from the token, not the URL slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)

    if not settings.mcp_similarity_embeddings_enabled:
        return McpSimilarReindexResponse(
            endpoint_id=str(endpoint_id),
            embeddings_enabled=False,
            reindexed=False,
            detail="semantic embeddings are disabled (APIOME_MCP_SIMILARITY_EMBEDDINGS_ENABLED is off)",
        )

    current_version_id = endpoint.get("current_version_id")
    if not current_version_id:
        return McpSimilarReindexResponse(
            endpoint_id=str(endpoint_id),
            embeddings_enabled=True,
            reindexed=False,
            detail="endpoint has no discovered surface to embed; run discovery first",
        )

    version = db.get_mcp_endpoint_version(str(endpoint_id), str(current_version_id))
    if version is None:
        return McpSimilarReindexResponse(
            endpoint_id=str(endpoint_id),
            embeddings_enabled=True,
            reindexed=False,
            detail="endpoint has no current version to embed",
        )

    version_id = str(version["id"])
    items = db.get_mcp_capability_items(version_id)
    text = build_capability_embedding_text(
        (item.get("name"), item.get("description")) for item in items
    )
    if not text:
        return McpSimilarReindexResponse(
            endpoint_id=str(endpoint_id),
            embeddings_enabled=True,
            reindexed=False,
            version_id=version_id,
            detail="endpoint's current surface has no capabilities to embed",
        )

    embedding = get_embedding(text)
    if not embedding:
        return McpSimilarReindexResponse(
            endpoint_id=str(endpoint_id),
            embeddings_enabled=True,
            reindexed=False,
            version_id=version_id,
            detail="embedding service unavailable; try again once Ollama is reachable",
        )

    stored = db.store_mcp_capability_embedding(version_id, embedding)
    return McpSimilarReindexResponse(
        endpoint_id=str(endpoint_id),
        embeddings_enabled=True,
        reindexed=bool(stored),
        version_id=version_id,
        detail=(
            "capability embedding stored"
            if stored
            else "pgvector unavailable; embedding computed but not stored"
        ),
    )


# ---------------------------------------------------------------------------------------------------
# Natural-language server digest + usage examples (V2-MCP-32.5 / MCAT-18.5, #4649).
#
# Pairs an opt-in, AI-written "this server lets you …" summary of a cataloged server with one
# deterministic, schema-derived example call per tool. The examples are pure offline synthesis
# (:func:`build_tool_examples`) — no tool is ever executed to build them — and are always returned. The
# digest is a gated Claude API step (:func:`generate_server_digest`) cached per ``surface_fingerprint``
# so it is computed once per surface and regenerated only when the surface (and thus the fingerprint)
# changes. GET reads (examples always, digest if cached); POST generates behind the feature flag.
# ---------------------------------------------------------------------------------------------------


def _mcp_digest_current_surface(
    endpoint: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], List[Any]]:
    """Load the endpoint's current version snapshot and its tool example calls.

    Returns ``(version_row, tool_examples)`` for the endpoint's ``current_version_id``. When the endpoint
    was never discovered (no current version, or the version read comes back empty) both are the empty
    case — ``(None, [])`` — so the digest routes yield a coherent "nothing to summarize yet" response
    rather than a 500. The examples are synthesized deterministically from the surface's tool schemas.
    """
    current_version_id = endpoint.get("current_version_id")
    if not current_version_id:
        return None, []
    version = db.get_mcp_endpoint_version(str(endpoint["id"]), str(current_version_id))
    if version is None:
        return None, []
    items = db.get_mcp_capability_items(str(version["id"]))
    return version, build_tool_examples(items)


def _mcp_digest_response(
    response_cls,
    endpoint_id: uuid.UUID,
    version: Optional[Dict[str, Any]],
    tool_examples: List[Any],
    cached: Optional[Dict[str, Any]],
    **extra: Any,
):
    """Shape a digest response envelope from the current surface + any cached digest row.

    Shared by the GET and POST routes: ``examples`` and ``tool_count`` come from the (always-present)
    schema-derived examples; the digest text / model / timestamp come from the cached row when one exists
    for the current surface. ``response_cls`` selects the read vs generate envelope; ``extra`` carries the
    generate-only fields (``generated`` / ``from_cache`` / ``detail``).
    """
    examples_out = [McpToolExampleOut.model_validate(e.as_dict()) for e in tool_examples]
    generated_at = cached.get("generated_at") if cached else None
    return response_cls(
        endpoint_id=str(endpoint_id),
        version_id=str(version["id"]) if version else None,
        surface_fingerprint=version.get("surface_fingerprint") if version else None,
        ai_digest_enabled=bool(settings.mcp_ai_digest_enabled),
        digest=cached.get("digest") if cached else None,
        model=cached.get("model") if cached else None,
        generated_at=generated_at.isoformat() if generated_at is not None else None,
        tool_count=len(examples_out),
        examples=examples_out,
        **extra,
    )


@mcp_endpoints_router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/insight/summary",
    response_model=McpServerDigestResponse,
)
async def get_mcp_endpoint_summary(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpServerDigestResponse:
    """Return the endpoint's usage examples and its cached AI digest, if any (MCAT-18.5).

    Two things in one read. ``examples`` — one **schema-derived example call per tool** of the current
    surface — is always present: it is synthesized deterministically from each tool's ``input_schema``
    with no model call and no tool execution, so it needs neither the feature flag nor an API key. The
    AI-written ``digest`` ("this server lets you …") is returned only when one has already been generated
    and cached for the current ``surface_fingerprint`` (``null`` otherwise); ``ai_digest_enabled`` tells
    the UI whether the gated ``…/insight/summary/generate`` action is available. Because the cache is keyed
    on the fingerprint, a surface change automatically presents as "no digest yet" until regenerated. A
    never-discovered endpoint yields empty ``examples`` and a ``null`` digest (a ``200``, never a ``500``).
    Scoping comes from the token's tenant; ``404`` when the endpoint is not the caller's tenant's. Read-only.
    """
    _ = tenant_slug  # scoping comes from the token, not the URL slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)
    version, tool_examples = _mcp_digest_current_surface(endpoint)

    fingerprint = version.get("surface_fingerprint") if version else None
    cached = db.get_mcp_server_digest(fingerprint) if fingerprint else None
    return _mcp_digest_response(
        McpServerDigestResponse, endpoint_id, version, tool_examples, cached
    )


@mcp_endpoints_router.post(
    "/{tenant_slug}/endpoints/{endpoint_id}/insight/summary/generate",
    response_model=McpServerDigestGenerateResponse,
)
async def generate_mcp_endpoint_summary(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpServerDigestGenerateResponse:
    """(Re)generate and cache the endpoint's AI digest for its current surface (MCAT-18.5).

    The gated AI step. It (re)computes the schema-derived example calls (always), and — when
    ``APIOME_MCP_AI_DIGEST_ENABLED`` is on and an API key is configured — writes a short natural-language
    digest of the server via the Claude API and caches it under the current ``surface_fingerprint`` so it
    is computed once per surface. If a digest is already cached for this exact surface, it is returned as
    is without calling the model (``from_cache=true``). Every non-success is a labelled no-op, not an
    error (always a ``200``): the feature flag being off, no API key, the endpoint having no discovered
    surface, or the model being unreachable / declining each return ``generated=false`` with a ``detail``.
    No tool is executed — the examples are pure schema synthesis and the model is told the surface is
    descriptive only. ``404`` when the endpoint is not the caller's tenant's.
    """
    _ = tenant_slug  # scoping comes from the token, not the URL slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)
    version, tool_examples = _mcp_digest_current_surface(endpoint)

    def result(cached, *, generated, from_cache, detail):
        return _mcp_digest_response(
            McpServerDigestGenerateResponse,
            endpoint_id,
            version,
            tool_examples,
            cached,
            generated=generated,
            from_cache=from_cache,
            detail=detail,
        )

    if version is None:
        return result(
            None,
            generated=False,
            from_cache=False,
            detail="endpoint has no discovered surface to summarize; run discovery first",
        )

    fingerprint = version.get("surface_fingerprint")

    if not settings.mcp_ai_digest_enabled:
        cached = db.get_mcp_server_digest(fingerprint) if fingerprint else None
        return result(
            cached,
            generated=False,
            from_cache=cached is not None,
            detail="AI digest is disabled (APIOME_MCP_AI_DIGEST_ENABLED is off)",
        )

    # Computed once per surface: a digest already cached for this fingerprint is reused, never re-billed.
    cached = db.get_mcp_server_digest(fingerprint) if fingerprint else None
    if cached is not None:
        return result(
            cached,
            generated=False,
            from_cache=True,
            detail="digest already generated for this surface",
        )

    digest = generate_server_digest(version, tool_examples)
    if not digest:
        return result(
            None,
            generated=False,
            from_cache=False,
            detail="digest model unavailable or declined; try again later",
        )

    stored = db.store_mcp_server_digest(
        fingerprint,
        digest,
        [e.as_dict() for e in tool_examples],
        settings.mcp_ai_digest_model,
    )
    return result(
        stored,
        generated=True,
        from_cache=False,
        detail="digest generated",
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
