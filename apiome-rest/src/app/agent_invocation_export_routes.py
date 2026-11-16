"""Agent invocation audit export endpoint — ATQ-4.5 (#5847).

```
GET /v1/tenants/{t}/agent-invocations/export?day=YYYY-MM-DD&format=jsonl|csv
```

Streams one finalized UTC day of the tenant's AGX-3.3 invocation rows for a SIEM. The rules
(finalized days only, tier retention, rows as stored plus ``key_name`` and a hashed
``key_fingerprint``) live in :mod:`app.agent_invocation_export`.

**Permissions reuse** ``api_keys:view``, like every other agent-access read. **Audited** as
``agent.invocations.export`` (day and format; never a row). **Scoped by the authenticated
tenant**: the slug in the URL only names the route.

The streaming half of ATQ-4.5 (the invocation ledger as an event source of the EID-3.4 signed
audit stream) waits for EID-3.4; until then this export is the SIEM path.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from .agent_invocation_export import (
    AUDIT_EXPORT,
    CODE_DAY_NOT_FINAL,
    CODE_DAY_PAST_RETENTION,
    ExportFormat,
    InvocationExportError,
    check_day,
    export_lines,
    read_day_status,
    read_stored_columns,
)
from .auth import validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission
from .usage_controls_routes import audit

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["agent-access"])

#: Response media type per format.
_MEDIA = {"jsonl": "application/x-ndjson; charset=utf-8", "csv": "text/csv; charset=utf-8"}


@router.get(
    "/{tenant_slug}/agent-invocations/export",
    response_class=StreamingResponse,
    summary="Export one day of the agent invocation audit",
    description=(
        "Stream one **finalized** UTC day of the tenant's agent `tools/call` audit rows, for a "
        "SIEM: `jsonl` (one JSON object per line) or `csv` (header line first). Every stored "
        "column is exported as stored, in table order, followed by `key_name` and "
        "`key_fingerprint` (`sha256:` + 32 hex digits over the key id, stable across exports). "
        "The key secret and its stored hash are never exported, and neither are body samples.\n\n"
        f"A day the usage sweep has not finalized yet is `409 {CODE_DAY_NOT_FINAL}` with "
        "`finalizesAfter`. A day older than the plan's raw-row retention is "
        f"`410 {CODE_DAY_PAST_RETENTION}` with `retentionDays` and `oldestExportableDay`.\n\n"
        f"Requires `api_keys:view`. Audited as `{AUDIT_EXPORT}`."
    ),
    responses={
        200: {
            "content": {"application/x-ndjson": {}, "text/csv": {}},
            "description": "The day's rows, streamed as an attachment.",
        },
        409: {"description": f"`{CODE_DAY_NOT_FINAL}`: the day is not finalized yet."},
        410: {"description": f"`{CODE_DAY_PAST_RETENTION}`: the day is past the plan's retention."},
    },
)
async def export_agent_invocations(
    tenant_slug: str,
    day: date = Query(..., description="The UTC day to export, `YYYY-MM-DD`."),
    format: ExportFormat = Query(default="jsonl", description="`jsonl` or `csv`."),  # noqa: A002 - the documented name
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> StreamingResponse:
    """Stream one finalized day of the tenant's agent invocation audit.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is what scopes it).
        day: The UTC day.
        format: ``jsonl`` or ``csv``.
        auth_data: The authenticated principal.

    Returns:
        The streamed document.

    Raises:
        HTTPException: 403 without ``api_keys:view`` or without a tenant; 409 when the day is not
            final; 410 when it is past retention; 422 for a malformed day or format.
    """
    actor_id = enforce_permission(db, auth_data, Resource.API_KEYS, Action.VIEW)
    _ = tenant_slug
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for the agent invocation export.")
    tenant_id = str(tenant_id)
    now = datetime.now(timezone.utc)
    status = read_day_status(db, tenant_id, day, now)
    try:
        check_day(day, finalized_at=status["finalized_at"], raw_cutoff=status["raw_cutoff"], now=now)
    except InvocationExportError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail()) from exc
    stored = read_stored_columns(db)
    audit(
        tenant_id=tenant_id,
        action=AUDIT_EXPORT,
        auth_data=auth_data,
        actor_id=actor_id,
        target=day.isoformat(),
        detail={"day": day.isoformat(), "format": format},
    )
    filename = f"agent-invocations-{day.isoformat()}.{format}"
    return StreamingResponse(
        export_lines(db, tenant_id, day, format, stored=stored),
        media_type=_MEDIA[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )
