"""MCP API key lifecycle — MTG-3.2 (#4776).

Exposes tenant-admin CRUD over ``apiome.mcp_api_keys``:

* ``GET`` / ``POST /v1/tenants/{tenant_slug}/mcp-keys``
* ``GET`` / ``PATCH`` / ``DELETE /v1/tenants/{tenant_slug}/mcp-keys/{key_id}``

Create returns the plaintext secret **once**. List/get/patch never include
``secret`` or ``key_hash``. Capability grant writes live in MTG-3.3 (#4777).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .auth import get_authenticated_user_id, validate_authentication
from .database import db

router = APIRouter(prefix="/v1/tenants", tags=["mcp-keys"])

CapabilityMode = Literal["inherit", "explicit"]


class McpKeyScopeJson(BaseModel):
    """Read scope stored in ``mcp_api_keys.scope_json`` (empty list = unrestricted)."""

    model_config = ConfigDict(extra="forbid")

    tenants: List[str] = Field(
        default_factory=list,
        description="Tenant UUIDs the key may read; empty = any tenant.",
    )
    projects: List[str] = Field(
        default_factory=list,
        description="Project UUIDs the key may read; empty = any project in scope.",
    )

    @field_validator("tenants", "projects")
    @classmethod
    def _string_ids_only(cls, value: List[str]) -> List[str]:
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("scope list entries must be non-empty strings")
        return value


class McpApiKeyMetadata(BaseModel):
    """Public MCP API key metadata (never includes secret or hash)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    prefix: str
    label: str
    scope_json: McpKeyScopeJson
    capability_mode: CapabilityMode
    created_at: datetime
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    created_by: Optional[str] = None


class McpApiKeyListResponse(BaseModel):
    """Tenant MCP API key listing."""

    model_config = ConfigDict(extra="forbid")

    keys: List[McpApiKeyMetadata]


class McpApiKeyCreateRequest(BaseModel):
    """Issue a new MCP API key."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, description="Human label for admin UX.")
    expires_at: Optional[datetime] = Field(
        default=None,
        description="Optional absolute expiry; omit for no expiry.",
    )
    scope_json: McpKeyScopeJson = Field(
        default_factory=McpKeyScopeJson,
        description='Read scope: {"tenants":[...],"projects":[...]}.',
    )


class McpApiKeyCreateResponse(McpApiKeyMetadata):
    """Create response: metadata plus one-time plaintext ``secret``."""

    secret: str = Field(
        description="Plaintext MCP API key; shown only in this response.",
    )


class McpApiKeyPatchRequest(BaseModel):
    """Partial update of label, expiry, and/or scope (active keys only)."""

    model_config = ConfigDict(extra="forbid")

    label: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Replace label when set.",
    )
    expires_at: Optional[datetime] = Field(
        default=None,
        description="Replace expiry when field is present; null clears expiry.",
    )
    scope_json: Optional[McpKeyScopeJson] = Field(
        default=None,
        description="Replace scope_json when set.",
    )


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the authenticated tenant id or fail loudly when the context is missing."""
    tid = auth_data.get("tenant_id")
    if not tid:
        raise HTTPException(status_code=500, detail="Missing tenant context")
    return str(tid)


def _require_tenant_admin(auth_data: Dict[str, Any]) -> str:
    """Gate MCP key lifecycle to tenant administrators; returns the tenant id."""
    tenant_id = _tenant_id(auth_data)
    user_id = get_authenticated_user_id(auth_data)
    if not user_id or not db.is_user_tenant_admin(tenant_id, user_id):
        raise HTTPException(
            status_code=403,
            detail="Only tenant administrators can manage MCP API keys",
        )
    return tenant_id


def _to_metadata(row: Dict[str, Any]) -> McpApiKeyMetadata:
    """Map a Database public row onto the response model."""
    scope = row.get("scope_json") or {}
    return McpApiKeyMetadata(
        id=str(row["id"]),
        prefix=str(row["prefix"]),
        label=str(row["label"]),
        scope_json=McpKeyScopeJson(
            tenants=list(scope.get("tenants") or []),
            projects=list(scope.get("projects") or []),
        ),
        capability_mode=row.get("capability_mode") or "inherit",
        created_at=row["created_at"],
        expires_at=row.get("expires_at"),
        revoked_at=row.get("revoked_at"),
        last_used_at=row.get("last_used_at"),
        created_by=row.get("created_by"),
    )


@router.get(
    "/{tenant_slug}/mcp-keys",
    response_model=McpApiKeyListResponse,
    summary="List MCP API keys",
    description=(
        "List MCP API key metadata for the tenant (prefix, label, scope, "
        "capability_mode, timestamps). Includes revoked keys for audit. Never "
        "returns secret or hash. Tenant administrators only (MTG-3.2, #4776)."
    ),
)
async def list_mcp_api_keys(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpApiKeyListResponse:
    """List MCP API keys for the authenticated tenant."""
    _ = tenant_slug
    tenant_id = _require_tenant_admin(auth_data)
    rows = db.list_mcp_api_keys(tenant_id)
    return McpApiKeyListResponse(keys=[_to_metadata(r) for r in rows])


@router.post(
    "/{tenant_slug}/mcp-keys",
    response_model=McpApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create MCP API key",
    description=(
        "Issue a new MCP API key. Returns plaintext ``secret`` once; subsequent "
        "reads never include it. Defaults to capability_mode=inherit. Tenant "
        "administrators only (MTG-3.2, #4776)."
    ),
)
async def create_mcp_api_key(
    tenant_slug: str,
    body: McpApiKeyCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpApiKeyCreateResponse:
    """Create an MCP API key and return metadata plus one-time secret."""
    _ = tenant_slug
    tenant_id = _require_tenant_admin(auth_data)
    created_by = get_authenticated_user_id(auth_data)
    try:
        row, secret = db.create_mcp_api_key(
            tenant_id,
            label=body.label,
            scope_json=body.scope_json.model_dump(),
            expires_at=body.expires_at,
            created_by=created_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    meta = _to_metadata(row)
    return McpApiKeyCreateResponse(**meta.model_dump(), secret=secret)


@router.get(
    "/{tenant_slug}/mcp-keys/{key_id}",
    response_model=McpApiKeyMetadata,
    summary="Get MCP API key",
    description=(
        "Return one MCP API key's public metadata. Never returns secret or hash. "
        "Tenant administrators only (MTG-3.2, #4776)."
    ),
)
async def get_mcp_api_key(
    tenant_slug: str,
    key_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpApiKeyMetadata:
    """Get one MCP API key by id for the authenticated tenant."""
    _ = tenant_slug
    tenant_id = _require_tenant_admin(auth_data)
    row = db.get_mcp_api_key(tenant_id, str(key_id))
    if row is None:
        raise HTTPException(status_code=404, detail="MCP API key not found")
    return _to_metadata(row)


@router.patch(
    "/{tenant_slug}/mcp-keys/{key_id}",
    response_model=McpApiKeyMetadata,
    summary="Update MCP API key",
    description=(
        "Update label, expires_at, and/or scope_json on an active (non-revoked) "
        "MCP API key. Capability grants are MTG-3.3. Tenant administrators only "
        "(MTG-3.2, #4776)."
    ),
)
async def patch_mcp_api_key(
    tenant_slug: str,
    key_id: UUID,
    body: McpApiKeyPatchRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpApiKeyMetadata:
    """Patch an active MCP API key's mutable fields."""
    _ = tenant_slug
    tenant_id = _require_tenant_admin(auth_data)
    fields_set = body.model_fields_set
    if not fields_set:
        raise HTTPException(
            status_code=422,
            detail="At least one of label, expires_at, or scope_json is required",
        )
    try:
        row = db.update_mcp_api_key(
            tenant_id,
            str(key_id),
            label=body.label,
            update_label="label" in fields_set,
            expires_at=body.expires_at,
            update_expires_at="expires_at" in fields_set,
            scope_json=body.scope_json.model_dump() if body.scope_json is not None else None,
            update_scope_json="scope_json" in fields_set,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="MCP API key not found or already revoked",
        )
    return _to_metadata(row)


@router.delete(
    "/{tenant_slug}/mcp-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke MCP API key",
    description=(
        "Soft-revoke an MCP API key (sets revoked_at). Idempotent for already-"
        "revoked keys. MCP auth rejects the key immediately. Tenant administrators "
        "only (MTG-3.2, #4776)."
    ),
    response_class=Response,
)
async def revoke_mcp_api_key(
    tenant_slug: str,
    key_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Revoke an MCP API key; unknown ids are 404."""
    _ = tenant_slug
    tenant_id = _require_tenant_admin(auth_data)
    row = db.revoke_mcp_api_key(tenant_id, str(key_id))
    if row is None:
        raise HTTPException(status_code=404, detail="MCP API key not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
