"""
Cross-protocol search route (MFI-6.2, #3754).

``GET /v1/search/{tenant_slug}/model?q=createOrder`` finds every operation, type and message whose
name, key, path or description matches, across every format the tenant has imported — gRPC
services, GraphQL fields, AsyncAPI operations, Avro records, OpenAPI Projects — with repeatable
``kind`` / ``protocol`` / ``format`` / ``grade`` facets that compose. The query, the two stores it
reads and the facet rule live in :mod:`app.model_search`.

Tenant-scoped; authentication via JWT bearer token or API key, like the catalog list.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import validate_authentication
from .browse_facets import format_label, protocol_label
from .database import db
from .model_search import (
    MAX_QUERY_LENGTH,
    SEARCH_HIT_CAP,
    UNGRADED,
    ModelSearchFilters,
    facet_counts,
    filter_hits,
    ordered_buckets,
)
from .models import CatalogFacetBucket, ModelSearchFacets, ModelSearchHit, ModelSearchResponse

router = APIRouter(prefix="/v1/search", tags=["search"])

#: Display labels for the kind facet.
_KIND_LABELS = {"operation": "Operations", "type": "Types", "message": "Messages"}


def _bucket_label(facet: str, value: str) -> str:
    """The display label of one facet value."""
    if facet == "kind":
        return _KIND_LABELS.get(value, value)
    if facet == "protocol":
        return protocol_label(value) or value
    if facet == "format":
        return format_label(value)
    return "Ungraded" if value == UNGRADED else value


def _buckets(
    facet: str, counts: Mapping[str, int], filters: ModelSearchFilters
) -> List[CatalogFacetBucket]:
    """Turn one facet's counts into ordered, labelled buckets marking the selected values."""
    selected = set(filters.selected(facet))
    return [
        CatalogFacetBucket(
            value=value,
            label=_bucket_label(facet, value),
            count=count,
            selected=value in selected,
        )
        for value, count in ordered_buckets(facet, counts)
    ]


def _hit(row: Mapping[str, Any]) -> ModelSearchHit:
    """Project one search row onto the response shape."""
    fmt = row.get("format")
    return ModelSearchHit(
        kind=str(row["kind"]),
        element_id=str(row["element_id"]),
        name=str(row.get("name") or row.get("element_key") or ""),
        key=row.get("element_key"),
        detail=row.get("detail"),
        method=row.get("method"),
        path=row.get("path"),
        parent=row.get("parent"),
        snippet=row.get("snippet"),
        paradigm=row.get("paradigm"),
        format=fmt,
        format_label=format_label(fmt) if fmt else None,
        quality_grade=row.get("quality_grade"),
        store=str(row.get("store") or "canonical"),
        rank=float(row.get("rank") or 0.0),
        project_id=str(row["project_id"]),
        project_slug=row.get("project_slug"),
        project_name=row.get("project_name"),
        publishable=bool(row.get("publishable")),
        version_record_id=str(row["version_record_id"]),
        version_label=row.get("version_label"),
    )


@router.get("/{tenant_slug}/model", response_model=ModelSearchResponse)
async def search_normalized_model(
    tenant_slug: str,
    q: str = Query(
        ...,
        description="Search text: words AND together, \"quoted phrases\" match in order, 'or' "
        "alternates and -word excludes (Postgres websearch syntax, English stemming).",
    ),
    kind: Optional[List[str]] = Query(
        None, description="Element kind, repeatable: operation, type, message."
    ),
    protocol: Optional[List[str]] = Query(
        None,
        description="Paradigm, repeatable: rest, rpc, event, graph, data_schema, agent "
        "(aliases such as grpc and graphql work).",
    ),
    format_: Optional[List[str]] = Query(
        None, alias="format", description="Source-format key, repeatable (openapi-3.1, protobuf, …)."
    ),
    grade: Optional[List[str]] = Query(
        None, description="Captured quality grade, repeatable: A, B, C, D, F or ungraded."
    ),
    all_versions: bool = Query(
        False, description="Search every live revision instead of each project's latest."
    ),
    limit: int = Query(25, ge=1, le=100, description="Page size."),
    offset: int = Query(0, ge=0, description="Matches to skip."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ModelSearchResponse:
    """
    Search the tenant's normalized model across every format (MFI-6.2, #3754).

    Matches operations, types and messages of catalog items and Projects alike. Values within one
    facet OR together and facets AND; each facet's counts are computed over the matches every
    *other* facet keeps, so ticking a value shows exactly that many. An unknown facet value narrows
    to nothing rather than failing. Matches are ranked by full-text relevance; at most 2 000 are
    considered, and ``truncated`` says when that cap was reached.

    Args:
        tenant_slug: The tenant slug.
        q: The search text (1–200 characters after trimming).
        kind: Element kinds to keep.
        protocol: Paradigms to keep.
        format_: Source formats to keep.
        grade: Grades to keep.
        all_versions: Search every live revision.
        limit: Page size.
        offset: Matches to skip.
        auth_data: Authentication data (injected by dependency).

    Returns:
        The page of matches, the totals and the four facets.

    Raises:
        HTTPException: 422 when ``q`` is blank or longer than 200 characters.
    """
    query = (q or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail="Enter something to search for.")
    if len(query) > MAX_QUERY_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Search text is limited to {MAX_QUERY_LENGTH} characters.",
        )

    filters = ModelSearchFilters.from_query(
        kinds=kind, protocols=protocol, formats=format_, grades=grade
    )
    rows = db.search_normalized_model(
        tenant_id=auth_data["tenant_id"], query=query, all_versions=all_versions
    )
    kept = filter_hits(rows, filters)
    counts = facet_counts(rows, filters)
    return ModelSearchResponse(
        query=query,
        total=len(rows),
        matched=len(kept),
        truncated=len(rows) >= SEARCH_HIT_CAP,
        offset=offset,
        limit=limit,
        hits=[_hit(row) for row in kept[offset : offset + limit]],
        facets=ModelSearchFacets(
            kinds=_buckets("kind", counts["kind"], filters),
            protocols=_buckets("protocol", counts["protocol"], filters),
            formats=_buckets("format", counts["format"], filters),
            grades=_buckets("grade", counts["grade"], filters),
        ),
    )
