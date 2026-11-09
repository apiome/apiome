"""MCP catalog categories & manual tags — tenant-scoped CRUD (V2-MCP-23.3 / MCAT-9.3, #3693).

Category lookup (built-in vocabulary plus the tenant's own entries):

* ``GET    /v1/mcp/{tenant_slug}/categories``         — list built-in and tenant categories.
* ``POST   /v1/mcp/{tenant_slug}/categories``         — add a tenant category.
* ``GET    /v1/mcp/{tenant_slug}/categories/{slug}``  — fetch one category.
* ``PATCH  /v1/mcp/{tenant_slug}/categories/{slug}``  — change a tenant category's label, description
  or sort order.
* ``DELETE /v1/mcp/{tenant_slug}/categories/{slug}``  — remove a tenant category.

Manual tags on endpoints:

* ``GET    /v1/mcp/{tenant_slug}/tags``                              — the tenant's tag vocabulary.
* ``GET    /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/tags``      — an endpoint's tags.
* ``PUT    /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/tags``      — replace an endpoint's tags.
* ``POST   /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/tags``      — add tags to an endpoint.
* ``DELETE /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/tags/{tag}`` — remove one tag.

An endpoint's category itself is set with ``PATCH /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}``
(see :func:`app.mcp_catalog_routes.update_mcp_endpoint`). Both dimensions are facets on browse and
search. Like every catalog route, scoping comes from the token's ``tenant_id``, never the URL slug.
Built-in categories are read-only: changing or deleting one is a ``403``.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from psycopg2 import errors as pg_errors

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .mcp_categorization import (
    CategorizationValidationError,
    canonical_tag,
    normalize_category_label,
    normalize_category_slug,
    normalize_tags,
    slugify_category,
)
from .models import (
    McpCategoryCreate,
    McpCategoryListResponse,
    McpCategoryResponse,
    McpCategoryUpdate,
    McpEndpointTagsBody,
    McpEndpointTagsResponse,
    McpTagUsageOut,
    McpTagVocabularyResponse,
    mcp_category_out_from_row,
)

router = APIRouter(prefix="/v1/mcp", tags=["mcp-catalog"])


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the caller's token tenant as a string."""
    return str(auth_data["tenant_id"])


def _optional_user_id(auth_data: Dict[str, Any]) -> Optional[str]:
    """Return the authenticated user id for authorship, or ``None`` when not attributable."""
    user_id = get_authenticated_user_id(auth_data)
    return str(user_id) if user_id else None


def _require_tenant_endpoint(tenant_id: str, endpoint_id: uuid.UUID) -> Dict[str, Any]:
    """Load a live endpoint scoped to the caller's tenant, or raise ``404``."""
    endpoint = db.get_mcp_endpoint(tenant_id, str(endpoint_id))
    if not endpoint:
        raise HTTPException(status_code=404, detail="MCP endpoint not found")
    return endpoint


def _require_tenant_category(tenant_id: str, slug: str) -> Dict[str, Any]:
    """Load a category the tenant may change, or raise.

    Raises:
        HTTPException: ``404`` when no visible category has ``slug``; ``403`` when it is built-in.
    """
    row = db.get_mcp_category(tenant_id, slug.strip().lower())
    if row is None:
        raise HTTPException(status_code=404, detail="MCP category not found")
    if row.get("builtin"):
        raise HTTPException(status_code=403, detail="built-in categories are read-only")
    return row


def _label_taken(categories: List[Dict[str, Any]], label: str, *, except_slug: Optional[str] = None) -> bool:
    """True when another visible category already uses ``label`` (case-insensitive).

    Labels resolve to slugs on endpoint writes, so two categories sharing a label would be
    ambiguous.
    """
    folded = label.lower()
    return any(
        str(c.get("label") or "").strip().lower() == folded and c.get("slug") != except_slug
        for c in categories
    )


# --- Categories ---------------------------------------------------------------------------------


@router.get("/{tenant_slug}/categories", response_model=McpCategoryListResponse)
async def list_mcp_categories(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpCategoryListResponse:
    """List the category lookup: built-in categories plus the tenant's own, with endpoint counts."""
    _ = tenant_slug
    rows = db.list_mcp_categories(_tenant_id(auth_data))
    return McpCategoryListResponse(
        success=True, categories=[mcp_category_out_from_row(r) for r in rows]
    )


@router.post("/{tenant_slug}/categories", response_model=McpCategoryResponse, status_code=201)
async def create_mcp_category(
    tenant_slug: str,
    body: McpCategoryCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpCategoryResponse:
    """Add a tenant-defined category.

    The slug defaults to one derived from the label. A slug or label already used by a visible
    category (built-in or the tenant's) is a ``409``; an invalid slug or label is a ``422``.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        label = normalize_category_label(body.label)
        raw_slug = body.slug if body.slug and body.slug.strip() else slugify_category(label)
        slug = normalize_category_slug(raw_slug)
    except CategorizationValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    existing = db.list_mcp_categories(tenant_id)
    if any(c.get("slug") == slug for c in existing):
        raise HTTPException(status_code=409, detail=f"a category with slug {slug!r} already exists")
    if _label_taken(existing, label):
        raise HTTPException(status_code=409, detail=f"a category labelled {label!r} already exists")

    description = (body.description or "").strip() or None
    try:
        row = db.create_mcp_category(
            tenant_id,
            _optional_user_id(auth_data),
            slug=slug,
            label=label,
            description=description,
            sort_order=body.sort_order,
        )
    except pg_errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=409, detail=f"a category with slug {slug!r} already exists"
        ) from exc
    return McpCategoryResponse(success=True, category=mcp_category_out_from_row(row))


@router.get("/{tenant_slug}/categories/{slug}", response_model=McpCategoryResponse)
async def get_mcp_category(
    tenant_slug: str,
    slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpCategoryResponse:
    """Fetch one visible category (built-in or the tenant's) by slug; ``404`` when unknown."""
    _ = tenant_slug
    row = db.get_mcp_category(_tenant_id(auth_data), slug.strip().lower())
    if row is None:
        raise HTTPException(status_code=404, detail="MCP category not found")
    return McpCategoryResponse(success=True, category=mcp_category_out_from_row(row))


@router.patch("/{tenant_slug}/categories/{slug}", response_model=McpCategoryResponse)
async def update_mcp_category(
    tenant_slug: str,
    slug: str,
    body: McpCategoryUpdate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpCategoryResponse:
    """Change a tenant category's label, description or sort order (the slug never changes).

    Only keys present in the body are applied; an empty body returns the category unchanged.
    ``403`` for a built-in category, ``404`` when unknown, ``409`` when the new label is taken.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    current = _require_tenant_category(tenant_id, slug)
    current_slug = str(current["slug"])

    fields: Dict[str, Any] = {}
    if body.label is not None:
        try:
            fields["label"] = normalize_category_label(body.label)
        except CategorizationValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if _label_taken(db.list_mcp_categories(tenant_id), fields["label"], except_slug=current_slug):
            raise HTTPException(
                status_code=409, detail=f"a category labelled {fields['label']!r} already exists"
            )
    if "description" in body.model_fields_set:
        fields["description"] = (body.description or "").strip() or None
    if body.sort_order is not None:
        fields["sort_order"] = body.sort_order
    if not fields:
        return McpCategoryResponse(success=True, category=mcp_category_out_from_row(current))

    row = db.update_mcp_category(tenant_id, current_slug, fields)
    if row is None:
        raise HTTPException(status_code=404, detail="MCP category not found")
    return McpCategoryResponse(success=True, category=mcp_category_out_from_row(row))


@router.delete("/{tenant_slug}/categories/{slug}")
async def delete_mcp_category(
    tenant_slug: str,
    slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, bool]:
    """Remove a tenant category. Endpoints filed under it keep the slug as an unlisted category.

    ``403`` for a built-in category, ``404`` when unknown.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    current = _require_tenant_category(tenant_id, slug)
    if not db.delete_mcp_category(tenant_id, str(current["slug"])):
        raise HTTPException(status_code=404, detail="MCP category not found")
    return {"success": True}


# --- Tags ---------------------------------------------------------------------------------------


@router.get("/{tenant_slug}/tags", response_model=McpTagVocabularyResponse)
async def list_mcp_tag_vocabulary(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpTagVocabularyResponse:
    """List every tag in use across the tenant's live endpoints, busiest first."""
    _ = tenant_slug
    rows = db.list_mcp_tag_vocabulary(_tenant_id(auth_data))
    return McpTagVocabularyResponse(
        success=True,
        tags=[
            McpTagUsageOut(tag=str(r["tag"]), endpoint_count=int(r.get("endpoint_count") or 0))
            for r in rows
        ],
    )


@router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/tags", response_model=McpEndpointTagsResponse
)
async def list_mcp_endpoint_tags(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpEndpointTagsResponse:
    """Return an endpoint's tags, alphabetical; ``404`` when the endpoint is not the tenant's."""
    _ = tenant_slug
    _require_tenant_endpoint(_tenant_id(auth_data), endpoint_id)
    return McpEndpointTagsResponse(
        success=True,
        endpoint_id=str(endpoint_id),
        tags=db.list_mcp_endpoint_tags(str(endpoint_id)),
    )


@router.put(
    "/{tenant_slug}/endpoints/{endpoint_id}/tags", response_model=McpEndpointTagsResponse
)
async def replace_mcp_endpoint_tags(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    body: McpEndpointTagsBody,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpEndpointTagsResponse:
    """Replace an endpoint's tags with ``body.tags`` (an empty list clears them).

    ``422`` when a tag is invalid or there are more than 32 distinct tags.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    _require_tenant_endpoint(tenant_id, endpoint_id)
    try:
        tags = normalize_tags(body.tags)
    except CategorizationValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    stored = db.replace_mcp_endpoint_tags(
        tenant_id, str(endpoint_id), tags, _optional_user_id(auth_data)
    )
    return McpEndpointTagsResponse(success=True, endpoint_id=str(endpoint_id), tags=stored)


@router.post(
    "/{tenant_slug}/endpoints/{endpoint_id}/tags", response_model=McpEndpointTagsResponse
)
async def add_mcp_endpoint_tags(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    body: McpEndpointTagsBody,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpEndpointTagsResponse:
    """Add ``body.tags`` to an endpoint's existing tags; tags it already has are ignored.

    ``422`` when a tag is invalid or the result would exceed 32 tags.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    _require_tenant_endpoint(tenant_id, endpoint_id)
    existing = db.list_mcp_endpoint_tags(str(endpoint_id))
    try:
        added = normalize_tags(body.tags)
        tags = normalize_tags([*existing, *added])
    except CategorizationValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    stored = db.replace_mcp_endpoint_tags(
        tenant_id, str(endpoint_id), tags, _optional_user_id(auth_data)
    )
    return McpEndpointTagsResponse(success=True, endpoint_id=str(endpoint_id), tags=stored)


@router.delete(
    "/{tenant_slug}/endpoints/{endpoint_id}/tags/{tag}", response_model=McpEndpointTagsResponse
)
async def remove_mcp_endpoint_tag(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    tag: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpEndpointTagsResponse:
    """Remove one tag from an endpoint; ``404`` when the endpoint does not carry it."""
    _ = tenant_slug
    _require_tenant_endpoint(_tenant_id(auth_data), endpoint_id)
    if not db.remove_mcp_endpoint_tag(str(endpoint_id), canonical_tag(tag)):
        raise HTTPException(status_code=404, detail="tag not found on this endpoint")
    return McpEndpointTagsResponse(
        success=True,
        endpoint_id=str(endpoint_id),
        tags=db.list_mcp_endpoint_tags(str(endpoint_id)),
    )


__all__ = ["router"]
