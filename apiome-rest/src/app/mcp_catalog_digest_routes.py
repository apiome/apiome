"""Scheduled catalog digest — tenant-scoped configuration + preview routes (V2-MCP-33.5 / MCAT-19.5, #4654).

Exposes the authenticated, tenant-scoped surface for the scheduled catalog digest feature whose
delivery is driven by :mod:`app.mcp_catalog_digest_sweep`:

* ``GET  /v1/mcp/{tenant_slug}/digest/config`` — read the tenant's digest configuration.
* ``PUT  /v1/mcp/{tenant_slug}/digest/config`` — opt in/out, set the cadence and empty-window policy.
* ``POST /v1/mcp/{tenant_slug}/digest/preview`` — compile the digest for the current window over real
  catalog data and return it, **without** sending or advancing the anchor (so an operator can see
  exactly what the next scheduled digest would contain).

Like the rest of the MCP catalog routes, every route derives ``tenant_id`` from the authenticated
token (never the URL slug — the slug only lets :func:`app.auth.validate_authentication` validate
access), so a caller can only ever read/write/preview its own tenant's digest (tenant scoping, an
acceptance criterion).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .config import settings
from .database import db
from .mcp_catalog_digest import build_digest_payload, compile_digest

router = APIRouter(prefix="/v1/mcp", tags=["mcp-catalog"])

#: Bounds on a per-tenant digest cadence. The lower bound matches the sweep's tick floor (a cadence
#: below it would just be clamped by how often the loop wakes), the upper bound is one year.
_CADENCE_MIN_SECONDS = 300
_CADENCE_MAX_SECONDS = 31_536_000


class McpDigestConfigUpdate(BaseModel):
    """Request body for ``PUT /digest/config`` — the tenant's digest preferences.

    Attributes:
        enabled: Opt-in switch. When False the sweep never selects the tenant.
        cadence_seconds: Per-tenant cadence in seconds, or ``None`` to use the global default.
        send_empty: When True, an empty window still sends an explicit "no changes" digest.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    enabled: bool = Field(..., description="Opt in (True) or out (False) of scheduled digests.")
    cadence_seconds: Optional[int] = Field(
        default=None,
        alias="cadenceSeconds",
        ge=_CADENCE_MIN_SECONDS,
        le=_CADENCE_MAX_SECONDS,
        description="Digest cadence in seconds; null uses the global default.",
    )
    send_empty: bool = Field(
        default=False,
        alias="sendEmpty",
        description="Send an explicit 'no changes' digest when the window is empty.",
    )


class McpDigestConfigResponse(BaseModel):
    """Response model for the tenant's digest configuration."""

    model_config = ConfigDict(populate_by_name=True)

    enabled: bool
    cadence_seconds: Optional[int] = Field(default=None, alias="cadenceSeconds")
    effective_cadence_seconds: int = Field(alias="effectiveCadenceSeconds")
    send_empty: bool = Field(alias="sendEmpty")
    last_digest_at: Optional[datetime] = Field(default=None, alias="lastDigestAt")


def _config_response(row: Optional[Dict[str, Any]]) -> McpDigestConfigResponse:
    """Project a stored config row (or the all-default absence) into the response model.

    A tenant that has never configured a digest has no row; that is surfaced as the default
    disabled configuration rather than a 404, so the client always gets a usable shape. The
    ``effective_cadence_seconds`` resolves the per-tenant override against the global default so the
    caller sees the cadence the sweep will actually apply.
    """
    default_cadence = int(settings.mcp_digest_default_cadence_seconds)
    if row is None:
        return McpDigestConfigResponse(
            enabled=False,
            cadence_seconds=None,
            effective_cadence_seconds=default_cadence,
            send_empty=False,
            last_digest_at=None,
        )
    cadence = row.get("cadence_seconds")
    return McpDigestConfigResponse(
        enabled=bool(row.get("enabled")),
        cadence_seconds=cadence,
        effective_cadence_seconds=int(cadence) if cadence else default_cadence,
        send_empty=bool(row.get("send_empty")),
        last_digest_at=row.get("last_digest_at"),
    )


@router.get("/{tenant_slug}/digest/config", response_model=McpDigestConfigResponse)
async def get_mcp_digest_config(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpDigestConfigResponse:
    """Read the calling tenant's scheduled catalog digest configuration (MCAT-19.5).

    Returns the default disabled configuration when the tenant has never opted in (never a 404).

    Args:
        tenant_slug: The tenant URL slug (validated by the auth dependency; scoping comes from the
            token).
        auth_data: The authenticated principal; ``tenant_id`` scopes the read.

    Returns:
        The tenant's digest configuration.
    """
    _ = tenant_slug  # scoping comes from the token, not the URL slug
    tenant_id = str(auth_data["tenant_id"])
    return _config_response(db.get_mcp_catalog_digest_config(tenant_id))


@router.put("/{tenant_slug}/digest/config", response_model=McpDigestConfigResponse)
async def put_mcp_digest_config(
    tenant_slug: str,
    body: McpDigestConfigUpdate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> McpDigestConfigResponse:
    """Create or update the calling tenant's digest configuration (MCAT-19.5).

    Upserts the tenant's opt-in, cadence and empty-window policy. The window anchor
    (``last_digest_at``) is not reset, so changing cadence mid-stream does not lose the current
    window.

    Args:
        tenant_slug: The tenant URL slug (validated by the auth dependency).
        body: The new digest preferences.
        auth_data: The authenticated principal; ``tenant_id`` scopes the write.

    Returns:
        The stored digest configuration.
    """
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    row = db.upsert_mcp_catalog_digest_config(
        tenant_id,
        enabled=body.enabled,
        cadence_seconds=body.cadence_seconds,
        send_empty=body.send_empty,
    )
    return _config_response(row)


@router.post("/{tenant_slug}/digest/preview")
async def preview_mcp_digest(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Compile and return the tenant's digest for the current window without sending it (MCAT-19.5).

    A dry run over real catalog data: the window ends now and spans one effective cadence back (the
    per-tenant override, or the global default). Nothing is delivered and the anchor is not advanced,
    so an operator can preview exactly what the next scheduled digest would contain. Respects tenant
    scoping — only the caller's own catalog is read.

    Args:
        tenant_slug: The tenant URL slug (validated by the auth dependency; also used as the digest's
            subject slug).
        auth_data: The authenticated principal; ``tenant_id`` scopes the reads.

    Returns:
        The digest payload (same JSON shape the scheduled delivery would carry).
    """
    tenant_id = str(auth_data["tenant_id"])

    config = db.get_mcp_catalog_digest_config(tenant_id)
    cadence = (config or {}).get("cadence_seconds") or settings.mcp_digest_default_cadence_seconds
    window_end = datetime.now(timezone.utc)
    window_start = window_end - timedelta(seconds=int(cadence))

    digest = compile_digest(
        tenant_slug=tenant_slug,
        window_start=window_start,
        window_end=window_end,
        new_endpoint_rows=db.list_mcp_new_endpoints_in_window(
            tenant_id, window_start, window_end
        ),
        change_rows=db.list_mcp_catalog_changes_in_window(
            tenant_id, window_start, window_end
        ),
        grade_movement_rows=db.list_mcp_grade_movements_in_window(
            tenant_id, window_start, window_end
        ),
        health_rows=db.list_mcp_health_problems_in_window(
            tenant_id, window_start, window_end
        ),
    )
    return build_digest_payload(digest)


__all__ = ["router"]
