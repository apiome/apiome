"""MCP catalog collections — tenant-scoped CRUD + membership routes (V2-MCP-36.4 / MCAT-22.4, #4667).

Exposes the authenticated surface for curated endpoint lists:

* ``GET    /v1/mcp/{tenant_slug}/collections``                         — list collections.
* ``POST   /v1/mcp/{tenant_slug}/collections``                         — create a collection.
* ``GET    /v1/mcp/{tenant_slug}/collections/{id}``                    — fetch one with members.
* ``PATCH  /v1/mcp/{tenant_slug}/collections/{id}``                    — rename / publish / describe.
* ``DELETE /v1/mcp/{tenant_slug}/collections/{id}``                      — delete a collection.
* ``PUT    /v1/mcp/{tenant_slug}/collections/{id}/members``            — replace members.
* ``POST   /v1/mcp/{tenant_slug}/collections/{id}/members``            — add members.
* ``DELETE /v1/mcp/{tenant_slug}/collections/{id}/members/{endpoint}`` — remove one member.

Published collections are browsable on apiome-browse; only endpoints that pass the public
visibility gate are shown there.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from psycopg2 import errors as pg_errors

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .mcp_collections import (
    CollectionValidationError,
    normalize_collection_description,
    normalize_collection_member_ids,
    normalize_collection_name,
    normalize_collection_slug,
    slugify_collection_name,
)
from .models import (
    McpCollectionCreate,
    McpCollectionListResponse,
    McpCollectionMembersAdd,
    McpCollectionMembersReplace,
    McpCollectionOut,
    McpCollectionUpdate,
    mcp_collection_member_out_from_row,
    mcp_collection_out_from_row,
)

router = APIRouter(prefix="/v1/mcp", tags=["mcp-catalog"])


def _require_user_id(auth_data: Dict[str, Any]) -> str:
    """Resolve the authenticated user; collections record a creating author."""
    user_id = get_authenticated_user_id(auth_data)
    if not user_id:
        raise HTTPException(
            status_code=403,
            detail="Collections require an attributable user",
        )
    return user_id


def _members_out(rows: List[Dict[str, Any]]) -> List[Any]:
    return [mcp_collection_member_out_from_row(r) for r in rows]


def _collection_out(
    row: Dict[str, Any],
    *,
    include_members: bool = False,
    member_rows: Optional[List[Dict[str, Any]]] = None,
) -> McpCollectionOut:
    members = _members_out(member_rows) if include_members and member_rows is not None else None
    return mcp_collection_out_from_row(row, members=members)


def _normalize_create(body: McpCollectionCreate) -> Dict[str, Any]:
    try:
        name = normalize_collection_name(body.name)
        slug = normalize_collection_slug(body.slug, fallback_name=name)
        return {
            "name": name,
            "slug": slug,
            "description": normalize_collection_description(body.description),
            "is_published": bool(body.is_published),
            "endpoint_ids": normalize_collection_member_ids(body.endpoint_ids),
        }
    except CollectionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _normalize_update(body: McpCollectionUpdate) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    try:
        if body.name is not None:
            fields["name"] = normalize_collection_name(body.name)
        if body.slug is not None:
            fallback = fields.get("name")
            fields["slug"] = normalize_collection_slug(body.slug, fallback_name=fallback)
        if body.description is not None:
            text = normalize_collection_description(body.description)
            if text is None:
                fields["clear_description"] = True
            else:
                fields["description"] = text
        if body.is_published is not None:
            fields["is_published"] = bool(body.is_published)
    except CollectionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return fields


@router.get("/{tenant_slug}/collections", response_model=McpCollectionListResponse)
async def list_mcp_collections(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpCollectionListResponse:
    """List curated collections for the caller's tenant."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    rows = db.list_mcp_collections(tenant_id)
    return McpCollectionListResponse(
        success=True,
        collections=[_collection_out(r) for r in rows],
    )


@router.post("/{tenant_slug}/collections", response_model=McpCollectionOut)
async def create_mcp_collection(
    tenant_slug: str,
    body: McpCollectionCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpCollectionOut:
    """Create a curated collection, optionally with initial members."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    user_id = _require_user_id(auth_data)
    payload = _normalize_create(body)
    try:
        row = db.create_mcp_collection(
            tenant_id,
            user_id,
            name=payload["name"],
            slug=payload["slug"],
            description=payload["description"],
            is_published=payload["is_published"],
            endpoint_ids=payload["endpoint_ids"],
        )
    except pg_errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=409,
            detail="A collection with that name or slug already exists",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    members = db.list_mcp_collection_members(tenant_id, str(row["id"]))
    return _collection_out(row, include_members=True, member_rows=members)


@router.get("/{tenant_slug}/collections/{collection_id}", response_model=McpCollectionOut)
async def get_mcp_collection(
    tenant_slug: str,
    collection_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpCollectionOut:
    """Fetch one curated collection with its members."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    row = db.get_mcp_collection(tenant_id, str(collection_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    members = db.list_mcp_collection_members(tenant_id, str(collection_id))
    return _collection_out(row, include_members=True, member_rows=members)


@router.patch("/{tenant_slug}/collections/{collection_id}", response_model=McpCollectionOut)
async def update_mcp_collection(
    tenant_slug: str,
    collection_id: uuid.UUID,
    body: McpCollectionUpdate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpCollectionOut:
    """Rename, describe, or publish/unpublish a curated collection."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    fields = _normalize_update(body)
    if not fields:
        row = db.get_mcp_collection(tenant_id, str(collection_id))
        if row is None:
            raise HTTPException(status_code=404, detail="Collection not found")
        members = db.list_mcp_collection_members(tenant_id, str(collection_id))
        return _collection_out(row, include_members=True, member_rows=members)
    clear_description = bool(fields.pop("clear_description", False))
    try:
        row = db.update_mcp_collection(
            tenant_id,
            str(collection_id),
            clear_description=clear_description,
            **fields,
        )
    except pg_errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=409,
            detail="A collection with that name or slug already exists",
        ) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    members = db.list_mcp_collection_members(tenant_id, str(collection_id))
    return _collection_out(row, include_members=True, member_rows=members)


@router.delete("/{tenant_slug}/collections/{collection_id}")
async def delete_mcp_collection(
    tenant_slug: str,
    collection_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, bool]:
    """Delete a curated collection."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    deleted = db.delete_mcp_collection(tenant_id, str(collection_id))
    if not deleted:
        raise HTTPException(status_code=404, detail="Collection not found")
    return {"success": True}


@router.put(
    "/{tenant_slug}/collections/{collection_id}/members",
    response_model=McpCollectionOut,
)
async def replace_mcp_collection_members(
    tenant_slug: str,
    collection_id: uuid.UUID,
    body: McpCollectionMembersReplace,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpCollectionOut:
    """Replace the full membership list for a collection."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    try:
        endpoint_ids = normalize_collection_member_ids(body.endpoint_ids)
    except CollectionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        members = db.replace_mcp_collection_members(
            tenant_id, str(collection_id), endpoint_ids
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not members and not db.get_mcp_collection(tenant_id, str(collection_id)):
        raise HTTPException(status_code=404, detail="Collection not found")
    row = db.get_mcp_collection(tenant_id, str(collection_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return _collection_out(row, include_members=True, member_rows=members)


@router.post(
    "/{tenant_slug}/collections/{collection_id}/members",
    response_model=McpCollectionOut,
)
async def add_mcp_collection_members(
    tenant_slug: str,
    collection_id: uuid.UUID,
    body: McpCollectionMembersAdd,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpCollectionOut:
    """Append endpoints to a collection."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    try:
        endpoint_ids = normalize_collection_member_ids(body.endpoint_ids)
    except CollectionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not endpoint_ids:
        raise HTTPException(status_code=422, detail="endpointIds must not be empty")
    try:
        members = db.add_mcp_collection_members(
            tenant_id, str(collection_id), endpoint_ids
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not members and not db.get_mcp_collection(tenant_id, str(collection_id)):
        raise HTTPException(status_code=404, detail="Collection not found")
    row = db.get_mcp_collection(tenant_id, str(collection_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return _collection_out(row, include_members=True, member_rows=members)


@router.delete("/{tenant_slug}/collections/{collection_id}/members/{endpoint_id}")
async def remove_mcp_collection_member(
    tenant_slug: str,
    collection_id: uuid.UUID,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, bool]:
    """Remove one endpoint from a collection."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    removed = db.remove_mcp_collection_member(
        tenant_id, str(collection_id), str(endpoint_id)
    )
    if not removed:
        raise HTTPException(status_code=404, detail="Collection member not found")
    return {"success": True}


__all__ = ["router", "slugify_collection_name"]
