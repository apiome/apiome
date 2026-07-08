"""Saved catalog searches — tenant-scoped CRUD + run routes (V2-MCP-35.3 / MCAT-21.3, #4662).

Exposes the authenticated, per-user surface for saved catalog searches:

* ``GET    /v1/mcp/{tenant_slug}/saved-searches``           — list the caller's saved searches.
* ``POST   /v1/mcp/{tenant_slug}/saved-searches``           — create a saved search.
* ``GET    /v1/mcp/{tenant_slug}/saved-searches/{id}``      — fetch one saved search.
* ``PATCH  /v1/mcp/{tenant_slug}/saved-searches/{id}``      — update name/filters/pin state.
* ``DELETE /v1/mcp/{tenant_slug}/saved-searches/{id}``      — delete a saved search.
* ``GET    /v1/mcp/{tenant_slug}/saved-searches/{id}/run``  — re-run facet-compatible filters.

Like the rest of the MCP catalog routes, ``tenant_id`` comes from the token and ``user_id`` scopes
ownership — a caller only ever sees and mutates their own saved searches within their tenant.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2 import errors as pg_errors

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .mcp_facets import FacetValidationError
from .mcp_saved_search import (
    SavedSearchValidationError,
    normalize_saved_search_filters,
    normalize_saved_search_name,
    normalize_saved_search_query,
    normalize_saved_search_sort,
    saved_filters_to_facet_kwargs,
)
from .models import (
    McpSavedSearchCreate,
    McpSavedSearchListResponse,
    McpSavedSearchOut,
    McpSavedSearchRunResponse,
    McpSavedSearchUpdate,
    mcp_faceted_search_response_from_bundle,
    mcp_saved_search_out_from_row,
)

router = APIRouter(prefix="/v1/mcp", tags=["mcp-catalog"])


def _require_user_id(auth_data: Dict[str, Any]) -> str:
    """Resolve the authenticated user; saved searches are per-user."""
    user_id = get_authenticated_user_id(auth_data)
    if not user_id:
        raise HTTPException(
            status_code=403,
            detail="Saved searches require an attributable user",
        )
    return user_id


def _normalize_create(body: McpSavedSearchCreate) -> Dict[str, Any]:
    """Validate a create payload into DB-ready primitives."""
    try:
        return {
            "name": normalize_saved_search_name(body.name),
            "filters": normalize_saved_search_filters(body.filters.model_dump()),
            "query": normalize_saved_search_query(body.query),
            "sort": normalize_saved_search_sort(body.sort),
            "is_pinned": bool(body.is_pinned),
        }
    except SavedSearchValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _normalize_update(body: McpSavedSearchUpdate) -> Dict[str, Any]:
    """Validate a patch payload; only supplied fields are returned."""
    fields: Dict[str, Any] = {}
    try:
        if body.name is not None:
            fields["name"] = normalize_saved_search_name(body.name)
        if body.filters is not None:
            fields["filters"] = normalize_saved_search_filters(body.filters.model_dump())
        if body.query is not None:
            fields["query"] = normalize_saved_search_query(body.query)
        if body.sort is not None:
            fields["sort"] = normalize_saved_search_sort(body.sort)
        if body.is_pinned is not None:
            fields["is_pinned"] = bool(body.is_pinned)
    except SavedSearchValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return fields


@router.get("/{tenant_slug}/saved-searches", response_model=McpSavedSearchListResponse)
async def list_mcp_saved_searches(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpSavedSearchListResponse:
    """List the caller's saved catalog searches (pinned first, then newest)."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    user_id = _require_user_id(auth_data)
    rows = db.list_mcp_saved_searches(tenant_id, user_id)
    return McpSavedSearchListResponse(
        success=True,
        searches=[mcp_saved_search_out_from_row(r) for r in rows],
    )


@router.post("/{tenant_slug}/saved-searches", response_model=McpSavedSearchOut)
async def create_mcp_saved_search(
    tenant_slug: str,
    body: McpSavedSearchCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpSavedSearchOut:
    """Save the current catalog filter bundle under a name."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    user_id = _require_user_id(auth_data)
    payload = _normalize_create(body)
    try:
        row = db.create_mcp_saved_search(
            tenant_id,
            user_id,
            name=payload["name"],
            filters=payload["filters"],
            query=payload["query"],
            sort=payload["sort"],
            is_pinned=payload["is_pinned"],
        )
    except pg_errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=409,
            detail="A saved search with that name already exists",
        ) from exc
    return mcp_saved_search_out_from_row(row)


@router.get("/{tenant_slug}/saved-searches/{search_id}", response_model=McpSavedSearchOut)
async def get_mcp_saved_search(
    tenant_slug: str,
    search_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpSavedSearchOut:
    """Fetch one saved search owned by the caller."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    user_id = _require_user_id(auth_data)
    row = db.get_mcp_saved_search(tenant_id, user_id, str(search_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Saved search not found")
    return mcp_saved_search_out_from_row(row)


@router.patch("/{tenant_slug}/saved-searches/{search_id}", response_model=McpSavedSearchOut)
async def update_mcp_saved_search(
    tenant_slug: str,
    search_id: uuid.UUID,
    body: McpSavedSearchUpdate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpSavedSearchOut:
    """Update a saved search owned by the caller."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    user_id = _require_user_id(auth_data)
    fields = _normalize_update(body)
    if not fields:
        row = db.get_mcp_saved_search(tenant_id, user_id, str(search_id))
        if row is None:
            raise HTTPException(status_code=404, detail="Saved search not found")
        return mcp_saved_search_out_from_row(row)
    try:
        row = db.update_mcp_saved_search(
            tenant_id, user_id, str(search_id), **fields
        )
    except pg_errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=409,
            detail="A saved search with that name already exists",
        ) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Saved search not found")
    return mcp_saved_search_out_from_row(row)


@router.delete("/{tenant_slug}/saved-searches/{search_id}")
async def delete_mcp_saved_search(
    tenant_slug: str,
    search_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, bool]:
    """Delete a saved search owned by the caller."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    user_id = _require_user_id(auth_data)
    deleted = db.delete_mcp_saved_search(tenant_id, user_id, str(search_id))
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved search not found")
    return {"success": True}


@router.get(
    "/{tenant_slug}/saved-searches/{search_id}/run",
    response_model=McpSavedSearchRunResponse,
)
async def run_mcp_saved_search(
    tenant_slug: str,
    search_id: uuid.UUID,
    limit: int = Query(500, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpSavedSearchRunResponse:
    """Re-run a saved search's facet-compatible filters and return matching endpoints.

    Host/auth dimensions are applied client-side on the browse page; the server runs the facet
    subset via the same faceted-search path as ``GET /facets``, so results match the equivalent
    live facet filter for those dimensions.
    """
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    user_id = _require_user_id(auth_data)
    row = db.get_mcp_saved_search(tenant_id, user_id, str(search_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Saved search not found")

    search = mcp_saved_search_out_from_row(row)
    try:
        facet_kwargs, visibility = saved_filters_to_facet_kwargs(search.filters.model_dump())
    except FacetValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    bundle = db.search_mcp_catalog_faceted(
        tenant_id,
        grades=facet_kwargs.get("grades"),
        transports=facet_kwargs.get("transports"),
        categories=facet_kwargs.get("categories"),
        safety=facet_kwargs.get("safety"),
        complexity=facet_kwargs.get("complexity"),
        protocols=facet_kwargs.get("protocols"),
        health=facet_kwargs.get("health"),
        visibility=visibility,
        limit=limit,
        offset=offset,
    )
    result = mcp_faceted_search_response_from_bundle(bundle, limit=limit, offset=offset)
    return McpSavedSearchRunResponse(success=True, search=search, result=result)


__all__ = ["router"]
