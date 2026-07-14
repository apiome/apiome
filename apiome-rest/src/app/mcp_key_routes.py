"""MCP API key lifecycle — MTG-3.2 (#4776) and capability grants — MTG-3.3 (#4777).

Exposes tenant-admin CRUD over ``apiome.mcp_api_keys``:

* ``GET`` / ``POST /v1/tenants/{tenant_slug}/mcp-keys``
* ``GET`` / ``PATCH`` / ``DELETE /v1/tenants/{tenant_slug}/mcp-keys/{key_id}``
* ``PUT /v1/tenants/{tenant_slug}/mcp-keys/{key_id}/capabilities``
* ``POST /v1/tenants/{tenant_slug}/mcp-keys/{key_id}/capabilities/preview``

Create returns the plaintext secret **once**. List/get/patch never include
``secret`` or ``key_hash``. Capability PUT enforces enable-set ⊆ tenant
ceiling; preview uses the shared MTG-1.4 resolver.

All operations require a **tenant administrator** user session; API keys
cannot mutate this governance surface (MTG-3.4, #4778).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .auth import (
    get_authenticated_user_id,
    require_tenant_admin_session,
    validate_authentication,
)
from .database import db
from .mcp_effective_policy import (
    KeyCapabilitySnapshot,
    TenantMcpPolicySnapshot,
    TenantToolFlags,
    preview_effective_tools,
    tool_in_ceiling,
)
from .mcp_tool_registry import is_registered_mcp_tool

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
    enabled_tools: List[str] = Field(
        default_factory=list,
        description="Explicit enable-set when capability_mode=explicit; empty under inherit.",
    )
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


class McpKeyCapabilitiesRequest(BaseModel):
    """Writable per-key capability grants (MTG-3.3)."""

    model_config = ConfigDict(extra="forbid")

    mode: CapabilityMode = Field(
        description=(
            "inherit = clear enabled_tools and follow tenant defaults; "
            "explicit = enabled_tools is authoritative (must be ⊆ ceiling)."
        ),
    )
    enabled_tools: Optional[List[str]] = Field(
        default=None,
        description=(
            "Tool ids when mode=explicit. Ignored (cleared) when mode=inherit."
        ),
    )


class McpKeyCapabilitiesResponse(BaseModel):
    """Stored per-key capability grants."""

    model_config = ConfigDict(extra="forbid")

    mode: CapabilityMode
    enabled_tools: List[str]


class McpKeyEffectiveToolRow(BaseModel):
    """One registry tool's effective enablement for a key (MTG-1.4 preview)."""

    model_config = ConfigDict(extra="forbid")

    tool_id: str
    enabled: bool
    deny_reason: Optional[str] = Field(
        default=None,
        description="First failing check when enabled is false; null when enabled.",
    )


class McpKeyCapabilitiesPreviewResponse(BaseModel):
    """Effective enable-set table for a key (matches MCP call gate)."""

    model_config = ConfigDict(extra="forbid")

    tools: List[McpKeyEffectiveToolRow]


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the authenticated tenant id or fail loudly when the context is missing."""
    tid = auth_data.get("tenant_id")
    if not tid:
        raise HTTPException(status_code=500, detail="Missing tenant context")
    return str(tid)


def _require_tenant_admin(auth_data: Dict[str, Any]) -> str:
    """Gate MCP key lifecycle to a JWT tenant-admin session; reject API-key auth."""
    return require_tenant_admin_session(
        db,
        auth_data,
        detail="Only tenant administrators can manage MCP API keys",
    )


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
        enabled_tools=list(row.get("enabled_tools") or []),
        created_at=row["created_at"],
        expires_at=row.get("expires_at"),
        revoked_at=row.get("revoked_at"),
        last_used_at=row.get("last_used_at"),
        created_by=row.get("created_by"),
    )


def _normalized_enabled_tools(
    mode: CapabilityMode, enabled_tools: Optional[List[str]]
) -> List[str]:
    """Apply inherit-clears-list and dedupe explicit tool ids (order preserved)."""
    if mode == "inherit":
        return []
    seen: set[str] = set()
    out: List[str] = []
    for raw in enabled_tools or []:
        tid = (raw or "").strip()
        if not tid or tid in seen:
            continue
        seen.add(tid)
        out.append(tid)
    return out


def _policy_snapshot(
    row: Optional[Dict[str, Any]],
) -> Optional[TenantMcpPolicySnapshot]:
    """Map a ``get_tenant_mcp_policy`` row onto the resolver snapshot."""
    if row is None:
        return None
    return TenantMcpPolicySnapshot(
        default_mode=row["default_mode"],
        allow_anonymous_mcp=bool(row.get("allow_anonymous_mcp", True)),
        tools={
            str(t["tool_id"]): TenantToolFlags(
                in_ceiling=bool(t["in_ceiling"]),
                default_enabled=bool(t["default_enabled"]),
                anonymous_enabled=bool(t.get("anonymous_enabled", True)),
            )
            for t in row.get("tools") or []
        },
    )


def _reject_outside_ceiling(tenant_id: str, tool_ids: List[str]) -> None:
    """Raise 422 listing tool ids that are unknown or outside the tenant ceiling."""
    if not tool_ids:
        return
    snap = _policy_snapshot(db.get_tenant_mcp_policy(tenant_id))
    offending: List[str] = []
    for tid in tool_ids:
        if not is_registered_mcp_tool(tid) or not tool_in_ceiling(tid, snap):
            offending.append(tid)
    if offending:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "MCP key enable-set exceeds tenant ceiling",
                "offending_tool_ids": offending,
            },
        )


def _capabilities_response(row: Dict[str, Any]) -> McpKeyCapabilitiesResponse:
    """Project stored capability columns onto the capabilities response model."""
    return McpKeyCapabilitiesResponse(
        mode=row.get("capability_mode") or "inherit",
        enabled_tools=list(row.get("enabled_tools") or []),
    )


def _preview_for(
    tenant_id: str, mode: CapabilityMode, enabled_tools: List[str]
) -> McpKeyCapabilitiesPreviewResponse:
    """Build an effective enable-set table via the shared MTG-1.4 resolver."""
    snap = _policy_snapshot(db.get_tenant_mcp_policy(tenant_id))
    key = KeyCapabilitySnapshot(
        capability_mode=mode,
        enabled_tools=frozenset(enabled_tools),
    )
    rows = preview_effective_tools(key=key, tenant=snap)
    return McpKeyCapabilitiesPreviewResponse(
        tools=[
            McpKeyEffectiveToolRow(
                tool_id=r.tool_id,
                enabled=r.enabled,
                deny_reason=r.deny_reason.value if r.deny_reason else None,
            )
            for r in rows
        ]
    )


@router.get(
    "/{tenant_slug}/mcp-keys",
    response_model=McpApiKeyListResponse,
    summary="List MCP API keys",
    description=(
        "List MCP API key metadata for the tenant (prefix, label, scope, "
        "capability_mode, enabled_tools, timestamps). Includes revoked keys for "
        "audit. Never returns secret or hash. Tenant administrators only "
        "(MTG-3.2, #4776)."
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
        "MCP API key. Capability grants use PUT …/capabilities (MTG-3.3). Tenant "
        "administrators only (MTG-3.2, #4776)."
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


@router.put(
    "/{tenant_slug}/mcp-keys/{key_id}/capabilities",
    response_model=McpKeyCapabilitiesResponse,
    summary="Update MCP API key capabilities",
    description=(
        "Set per-key capability grants: mode inherit|explicit and optional "
        "enabled_tools. inherit clears the explicit list; explicit lists must be "
        "⊆ the tenant ceiling (422 with offending_tool_ids otherwise). Tenant "
        "administrators only (MTG-3.3, #4777)."
    ),
)
async def put_mcp_api_key_capabilities(
    tenant_slug: str,
    key_id: UUID,
    body: McpKeyCapabilitiesRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpKeyCapabilitiesResponse:
    """Replace capability_mode / enabled_tools on an active MCP API key."""
    _ = tenant_slug
    tenant_id = _require_tenant_admin(auth_data)
    tools = _normalized_enabled_tools(body.mode, body.enabled_tools)
    _reject_outside_ceiling(tenant_id, tools)
    try:
        row = db.update_mcp_api_key_capabilities(
            tenant_id,
            str(key_id),
            capability_mode=body.mode,
            enabled_tools=tools,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="MCP API key not found or already revoked",
        )
    return _capabilities_response(row)


@router.post(
    "/{tenant_slug}/mcp-keys/{key_id}/capabilities/preview",
    response_model=McpKeyCapabilitiesPreviewResponse,
    summary="Preview MCP API key effective capabilities",
    description=(
        "Dry-run effective enable-set for the given mode/enabled_tools against the "
        "tenant policy, using the same MTG-1.4 resolver as MCP tools/call. Does not "
        "persist. Ceiling violations yield 422 with offending_tool_ids. Tenant "
        "administrators only (MTG-3.3, #4777)."
    ),
)
async def preview_mcp_api_key_capabilities(
    tenant_slug: str,
    key_id: UUID,
    body: McpKeyCapabilitiesRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpKeyCapabilitiesPreviewResponse:
    """Preview effective tools for proposed grants without writing the key."""
    _ = tenant_slug
    tenant_id = _require_tenant_admin(auth_data)
    existing = db.get_mcp_api_key(tenant_id, str(key_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="MCP API key not found")
    tools = _normalized_enabled_tools(body.mode, body.enabled_tools)
    _reject_outside_ceiling(tenant_id, tools)
    return _preview_for(tenant_id, body.mode, tools)
