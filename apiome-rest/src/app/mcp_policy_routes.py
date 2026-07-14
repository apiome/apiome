"""Tenant MCP policy CRUD — MTG-3.1 (#4775), auth gate — MTG-3.4 (#4778),
policy change history — MTG-5.2 (#4786).

Exposes ``GET`` / ``PUT /v1/tenants/{tenant_slug}/mcp-policy`` so Control Panel
and automation can read and replace the tenant ceiling, default enable-set, and
anonymous flags stored in ``tenant_mcp_policies`` / ``tenant_mcp_policy_tools``.

``GET …/mcp-policy/history`` lists append-only before/after snapshots written on
every non-noop admin PUT (MTG-5.2).

Reads require tenant membership (any authenticated principal for the slug).
Mutations require a **tenant administrator** user session — API keys cannot
escalate into governance writes even when ``created_by`` maps to an admin
(MTG-3.4).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .auth import (
    get_authenticated_user_id,
    require_tenant_admin_session,
    validate_authentication,
)
from .database import db
from .mcp_tool_registry import is_registered_mcp_tool

router = APIRouter(prefix="/v1/tenants", tags=["mcp-policy"])

TenantDefaultMode = Literal["all", "inherit_registry", "explicit"]


class TenantMcpPolicyTool(BaseModel):
    """Per-tool ceiling / default / anonymous flags for a tenant policy."""

    model_config = ConfigDict(extra="forbid")

    tool_id: str = Field(
        description="Stable MTG-1.1 registry id (e.g. ping, spec.list).",
    )
    in_ceiling: bool = Field(
        description="Ceiling membership: keys may enable this tool when true.",
    )
    default_enabled: bool = Field(
        description="Default enable-set for new inherit-mode MCP keys; requires in_ceiling.",
    )
    anonymous_enabled: bool = Field(
        default=True,
        description="Anonymous enable-set membership (independent of ceiling for MVP).",
    )


class TenantMcpPolicyPutRequest(BaseModel):
    """Writable tenant MCP policy body for ``PUT …/mcp-policy``."""

    model_config = ConfigDict(extra="forbid")

    default_mode: TenantDefaultMode = Field(
        description=(
            "How missing tool rows resolve: all, inherit_registry, or explicit."
        ),
    )
    allow_anonymous_mcp: bool = Field(
        default=True,
        description="Kill switch for anonymous tools/call against this tenant policy.",
    )
    tools: List[TenantMcpPolicyTool] = Field(
        default_factory=list,
        description="Full replace-all list of per-tool policy flags.",
    )


class TenantMcpPolicyResponse(BaseModel):
    """Stored (or synthesized unseeded) tenant MCP policy snapshot."""

    model_config = ConfigDict(extra="forbid")

    default_mode: TenantDefaultMode
    allow_anonymous_mcp: bool
    tools: List[TenantMcpPolicyTool]
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Last policy write time; null when no row has been persisted.",
    )
    updated_by: Optional[str] = Field(
        default=None,
        description="User id of the last writer; null until first admin PUT after seed.",
    )


class TenantMcpPolicySnapshot(BaseModel):
    """Policy body stored in audit before/after JSONB (no updated_* metadata)."""

    model_config = ConfigDict(extra="forbid")

    default_mode: TenantDefaultMode
    allow_anonymous_mcp: bool
    tools: List[TenantMcpPolicyTool] = Field(default_factory=list)


class TenantMcpPolicyChangeEntry(BaseModel):
    """One append-only MCP policy change event (MTG-5.2 / #4786)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    actor_user_id: Optional[str] = None
    actor_label: Optional[str] = None
    created_at: datetime
    before_policy: TenantMcpPolicySnapshot
    after_policy: TenantMcpPolicySnapshot


class TenantMcpPolicyHistoryResponse(BaseModel):
    """Newest-first list of tenant MCP policy changes."""

    model_config = ConfigDict(extra="forbid")

    changes: List[TenantMcpPolicyChangeEntry] = Field(default_factory=list)


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the authenticated tenant id or fail loudly when the context is missing."""
    tid = auth_data.get("tenant_id")
    if not tid:
        raise HTTPException(status_code=500, detail="Missing tenant context")
    return str(tid)


def _require_tenant_admin(auth_data: Dict[str, Any]) -> str:
    """Gate a mutation to a JWT tenant-admin session; reject API-key auth."""
    return require_tenant_admin_session(
        db,
        auth_data,
        detail="Only tenant administrators can manage MCP policy",
    )


def _actor_label(auth_data: Dict[str, Any]) -> Optional[str]:
    """Best display label for the acting user in the policy change audit."""
    label = auth_data.get("user_email") or auth_data.get("user_name")
    if label is None:
        return None
    text = str(label).strip()
    return text or None


def _policy_response(row: Optional[Dict[str, Any]]) -> TenantMcpPolicyResponse:
    """Map a DB snapshot (or absence) onto the response model."""
    if row is None:
        return TenantMcpPolicyResponse(
            default_mode="all",
            allow_anonymous_mcp=True,
            tools=[],
            updated_at=None,
            updated_by=None,
        )
    return TenantMcpPolicyResponse(
        default_mode=row["default_mode"],
        allow_anonymous_mcp=bool(row.get("allow_anonymous_mcp", True)),
        tools=[
            TenantMcpPolicyTool(
                tool_id=t["tool_id"],
                in_ceiling=bool(t["in_ceiling"]),
                default_enabled=bool(t["default_enabled"]),
                anonymous_enabled=bool(t.get("anonymous_enabled", True)),
            )
            for t in row.get("tools") or []
        ],
        updated_at=row.get("updated_at"),
        updated_by=row.get("updated_by"),
    )


def _snapshot_from_dict(raw: Dict[str, Any]) -> TenantMcpPolicySnapshot:
    """Coerce a stored JSONB audit snapshot into the response model."""
    tools_raw = raw.get("tools") or []
    return TenantMcpPolicySnapshot(
        default_mode=raw.get("default_mode") or "all",
        allow_anonymous_mcp=bool(raw.get("allow_anonymous_mcp", True)),
        tools=[
            TenantMcpPolicyTool(
                tool_id=str(t.get("tool_id") or ""),
                in_ceiling=bool(t.get("in_ceiling")),
                default_enabled=bool(t.get("default_enabled")),
                anonymous_enabled=bool(t.get("anonymous_enabled", True)),
            )
            for t in tools_raw
            if isinstance(t, dict) and t.get("tool_id")
        ],
    )


def _validate_put_tools(tools: List[TenantMcpPolicyTool]) -> None:
    """Reject unknown, duplicate, or default-not-subset-ceiling tool rows with 422."""
    seen: set[str] = set()
    for tool in tools:
        if not is_registered_mcp_tool(tool.tool_id):
            raise HTTPException(
                status_code=422,
                detail=f"Unknown MCP tool id: {tool.tool_id}",
            )
        if tool.tool_id in seen:
            raise HTTPException(
                status_code=422,
                detail=f"Duplicate MCP tool id in request: {tool.tool_id}",
            )
        seen.add(tool.tool_id)
        if tool.default_enabled and not tool.in_ceiling:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"default_enabled requires in_ceiling for tool id: {tool.tool_id}"
                ),
            )


@router.get(
    "/{tenant_slug}/mcp-policy",
    response_model=TenantMcpPolicyResponse,
    summary="Get tenant MCP policy",
    description=(
        "Return the tenant's MCP tool governance policy (ceiling, default enable-set, "
        "anonymous flags). Tenant members may read; an unseeded tenant synthesizes "
        "default_mode=all with an empty tools list (MTG-3.1, #4775)."
    ),
)
async def get_tenant_mcp_policy(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> TenantMcpPolicyResponse:
    """Read the authenticated tenant's MCP policy snapshot."""
    _ = tenant_slug  # scoping comes from the token, not the URL slug
    tenant_id = _tenant_id(auth_data)
    return _policy_response(db.get_tenant_mcp_policy(tenant_id))


@router.get(
    "/{tenant_slug}/mcp-policy/history",
    response_model=TenantMcpPolicyHistoryResponse,
    summary="List tenant MCP policy change history",
    description=(
        "Return newest-first append-only MCP policy change events with before/after "
        "tool-enablement snapshots (MTG-5.2, #4786). Tenant members may read."
    ),
)
async def list_tenant_mcp_policy_history(
    tenant_slug: str,
    limit: int = Query(50, ge=1, le=200, description="Max change rows to return."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> TenantMcpPolicyHistoryResponse:
    """List MCP policy change audit rows for the authenticated tenant."""
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    rows = db.list_tenant_mcp_policy_changes(tenant_id, limit=limit)
    return TenantMcpPolicyHistoryResponse(
        changes=[
            TenantMcpPolicyChangeEntry(
                id=row["id"],
                actor_user_id=row.get("actor_user_id"),
                actor_label=row.get("actor_label"),
                created_at=row["created_at"],
                before_policy=_snapshot_from_dict(row.get("before_policy") or {}),
                after_policy=_snapshot_from_dict(row.get("after_policy") or {}),
            )
            for row in rows
        ]
    )


@router.put(
    "/{tenant_slug}/mcp-policy",
    response_model=TenantMcpPolicyResponse,
    summary="Replace tenant MCP policy",
    description=(
        "Replace the tenant MCP policy (default_mode, anonymous kill switch, and full "
        "per-tool flag list). Tenant administrators with a signed-in session only; "
        "API keys cannot mutate governance. Unknown tool ids and default_enabled "
        "without in_ceiling yield 422 (MTG-3.1, #4775; MTG-3.4, #4778). Non-noop writes "
        "append a policy change audit row (MTG-5.2, #4786)."
    ),
)
async def put_tenant_mcp_policy(
    tenant_slug: str,
    body: TenantMcpPolicyPutRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> TenantMcpPolicyResponse:
    """Upsert the authenticated tenant's MCP policy; admin-only."""
    _ = tenant_slug
    tenant_id = _require_tenant_admin(auth_data)
    _validate_put_tools(body.tools)
    updated_by = get_authenticated_user_id(auth_data)
    stored = db.replace_tenant_mcp_policy(
        tenant_id,
        default_mode=body.default_mode,
        allow_anonymous_mcp=body.allow_anonymous_mcp,
        tools=[
            {
                "tool_id": t.tool_id,
                "in_ceiling": t.in_ceiling,
                "default_enabled": t.default_enabled,
                "anonymous_enabled": t.anonymous_enabled,
            }
            for t in body.tools
        ],
        updated_by=updated_by,
        actor_label=_actor_label(auth_data),
    )
    return _policy_response(stored)
