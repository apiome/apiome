"""Cataloger notes — tenant-scoped CRUD on MCP endpoints (V2-MCP-36.3 / MCAT-22.3, #4666).

Exposes authenticated CRUD for human notes on catalog endpoints:

* ``GET    /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/notes``           — list notes.
* ``POST   /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/notes``           — create a note.
* ``GET    /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/notes/{note_id}`` — fetch one note.
* ``PATCH  /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/notes/{note_id}`` — update a note.
* ``DELETE /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/notes/{note_id}`` — delete a note.

Notes are tenant-scoped commentary, never mixed into discovered surface data. Create/update/delete
require an attributable user for the author/time audit trail.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .mcp_endpoint_notes import EndpointNoteValidationError, normalize_endpoint_note_body
from .models import (
    McpEndpointNoteCreate,
    McpEndpointNoteListResponse,
    McpEndpointNoteOut,
    McpEndpointNoteUpdate,
    mcp_endpoint_note_out_from_row,
)

router = APIRouter(prefix="/v1/mcp", tags=["mcp-catalog"])


def _require_user_id(auth_data: Dict[str, Any]) -> str:
    """Resolve the authenticated user; cataloger notes require an attributable author."""
    user_id = get_authenticated_user_id(auth_data)
    if not user_id:
        raise HTTPException(
            status_code=403,
            detail="Cataloger notes require an attributable user",
        )
    return user_id


def _require_tenant_endpoint(tenant_id: str, endpoint_id: uuid.UUID) -> Dict[str, Any]:
    """Load an endpoint scoped to the caller's tenant, or raise ``404``."""
    endpoint = db.get_mcp_endpoint(tenant_id, str(endpoint_id))
    if not endpoint:
        raise HTTPException(status_code=404, detail="MCP endpoint not found")
    return endpoint


@router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/notes",
    response_model=McpEndpointNoteListResponse,
)
async def list_mcp_endpoint_notes(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpEndpointNoteListResponse:
    """List cataloger notes for an endpoint (newest first)."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    _require_tenant_endpoint(tenant_id, endpoint_id)
    rows = db.list_mcp_endpoint_notes(tenant_id, str(endpoint_id))
    return McpEndpointNoteListResponse(
        success=True,
        notes=[mcp_endpoint_note_out_from_row(r) for r in rows],
    )


@router.post(
    "/{tenant_slug}/endpoints/{endpoint_id}/notes",
    response_model=McpEndpointNoteOut,
)
async def create_mcp_endpoint_note(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    body: McpEndpointNoteCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpEndpointNoteOut:
    """Add a cataloger note to an endpoint."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    user_id = _require_user_id(auth_data)
    _require_tenant_endpoint(tenant_id, endpoint_id)
    try:
        note_body = normalize_endpoint_note_body(body.body)
    except EndpointNoteValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = db.create_mcp_endpoint_note(
        tenant_id,
        str(endpoint_id),
        user_id,
        body=note_body,
    )
    return mcp_endpoint_note_out_from_row(row)


@router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/notes/{note_id}",
    response_model=McpEndpointNoteOut,
)
async def get_mcp_endpoint_note(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    note_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpEndpointNoteOut:
    """Fetch one cataloger note on an endpoint."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    _require_tenant_endpoint(tenant_id, endpoint_id)
    row = db.get_mcp_endpoint_note(tenant_id, str(endpoint_id), str(note_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Cataloger note not found")
    return mcp_endpoint_note_out_from_row(row)


@router.patch(
    "/{tenant_slug}/endpoints/{endpoint_id}/notes/{note_id}",
    response_model=McpEndpointNoteOut,
)
async def update_mcp_endpoint_note(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    note_id: uuid.UUID,
    body: McpEndpointNoteUpdate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpEndpointNoteOut:
    """Update a cataloger note on an endpoint."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    user_id = _require_user_id(auth_data)
    _require_tenant_endpoint(tenant_id, endpoint_id)
    if body.body is None:
        row = db.get_mcp_endpoint_note(tenant_id, str(endpoint_id), str(note_id))
        if row is None:
            raise HTTPException(status_code=404, detail="Cataloger note not found")
        return mcp_endpoint_note_out_from_row(row)
    try:
        note_body = normalize_endpoint_note_body(body.body)
    except EndpointNoteValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = db.update_mcp_endpoint_note(
        tenant_id,
        str(endpoint_id),
        str(note_id),
        user_id,
        body=note_body,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Cataloger note not found")
    return mcp_endpoint_note_out_from_row(row)


@router.delete("/{tenant_slug}/endpoints/{endpoint_id}/notes/{note_id}")
async def delete_mcp_endpoint_note(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    note_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, bool]:
    """Delete a cataloger note from an endpoint."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    _require_user_id(auth_data)
    _require_tenant_endpoint(tenant_id, endpoint_id)
    deleted = db.delete_mcp_endpoint_note(tenant_id, str(endpoint_id), str(note_id))
    if not deleted:
        raise HTTPException(status_code=404, detail="Cataloger note not found")
    return {"success": True}


__all__ = ["router"]
