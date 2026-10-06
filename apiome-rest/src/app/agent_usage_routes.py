"""Agent usage endpoint — AGX-3.4 (#4540).

```
GET /v1/tenants/{t}/agent-usage?days=30    usage rollups for the Control Panel charts
```

Reads the AGX-3.3 daily rollups (:mod:`app.agent_usage`) for the authenticated tenant: calls,
errors and latency per day, per tool and per agent key over the last ``days`` UTC days (today
included).

**Scoped by the authenticated tenant**, as on every ``/v1/tenants/{t}`` surface: the tenant in the
URL is informational. **Permissions reuse** ``api_keys:view``, like every other agent-access read
(toolsets, agent keys, per-key usage).
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from .agent_usage import DEFAULT_DAYS, MAX_DAYS, AgentUsageOut, get_agent_usage
from .auth import validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["agent-access"])


@router.get(
    "/{tenant_slug}/agent-usage",
    response_model=AgentUsageOut,
    summary="Agent usage rollups",
    description=(
        "The tenant's agent `tools/call` usage over the last `days` UTC days, today included, "
        "from the daily rollups: `daily` (zero-filled, oldest first), `tools` and `agents` (most "
        "calls first) and `totals` with errors broken down by outcome.\n\n"
        "`errors` counts every call that did not succeed, quota rejections included. Latency is "
        "the calls-weighted mean (`latencyAvgMs`) and the worst p95 among the rollup groups "
        "covered (`latencyP95MaxMs`); percentiles cannot be merged exactly.\n\n"
        f"`days` is 1–{MAX_DAYS} (default {DEFAULT_DAYS}). Requires `api_keys:view`."
    ),
)
async def get_agent_usage_route(
    tenant_slug: str,
    days: int = Query(default=DEFAULT_DAYS, ge=1, le=MAX_DAYS),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> AgentUsageOut:
    """Report the tenant's agent usage over a window of days.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is what scopes it).
        days: Window length in UTC days, today included.
        auth_data: The authenticated principal.

    Returns:
        The usage projection.

    Raises:
        HTTPException: 403 without ``api_keys:view`` or without a tenant; 422 when ``days`` is
            out of range.
    """
    enforce_permission(db, auth_data, Resource.API_KEYS, Action.VIEW)
    _ = tenant_slug
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for agent usage.")
    return get_agent_usage(str(tenant_id), days=days)
