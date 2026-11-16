"""Usage export, retention and body-sample routes — RDG-5.4 (#5789).

```
GET    /v1/tenants/{t}/usage/retention                         caps, the workspace's values, what applies
PUT    /v1/tenants/{t}/usage/retention                         lower retention (never above the cap)
GET    /v1/tenants/{t}/projects/{p}/usage/export               stream the daily rollups (CSV / JSON)
GET    /v1/tenants/{t}/projects/{p}/usage/sources              sources + agent toolsets, with caps
PATCH  /v1/tenants/{t}/projects/{p}/usage/sources/{id}         sampling, field capture, body samples
PATCH  /v1/tenants/{t}/agent-toolsets/{id}/body-samples        the AGX-3.3 body-capture window
```

Erasing a consumer is ``DELETE …/consumers/{c}/bindings?erase=true`` in
:mod:`app.consumer_binding_routes`, beside the other binding routes.

**Permissions.** Export is ``versions:view`` (it reads what the adoption views read). Reading
retention and sources is ``projects:view``. Changing a source is ``projects:edit``. Changing
retention is ``members:edit`` (Owner and Admin): it decides how long the workspace keeps data. A
toolset's body capture is ``api_keys:edit``, like every other toolset setting.

**Audited**, metadata only: ``usage.export`` (project, format, window, rows),
``usage.retention.update`` (before and after), ``usage.source.update`` (before and after) and
``agent.toolset.body_samples.update`` (before, after, and that the acknowledgement was given).

**Scoped by the authenticated tenant**, as on every ``/v1/tenants/{t}`` surface. The slug in the
URL only names the route.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from .auth import validate_authentication
from .consumer_contract import ConsumerValidationError
from .consumer_contract_routes import _http_error, _tenant_id
from .consumer_contract_store import resolve_project
from .database import db
from .permissions import Action, Resource, enforce_permission
from .usage_controls import (
    AGENT_BODY_CAPTURE_MAX_RATE,
    AUDIT_EXPORT,
    AUDIT_RETENTION_UPDATE,
    AUDIT_SOURCE_UPDATE,
    AUDIT_TOOLSET_BODY_SAMPLES,
    BODY_SAMPLE_MAX_RATE,
    CODE_NOTHING_TO_CHANGE,
    CODE_SOURCE_NOT_FOUND,
    CODE_TOOLSET_NOT_FOUND,
    DEFAULT_EXPORT_DAYS,
    EXPORT_FORMAT,
    MAX_EXPORT_DAYS,
    BodySampleWindow,
    ExportFormat,
    RetentionUpdate,
    ToolsetBodySamplesOut,
    UsageControlsError,
    UsageRetentionResponse,
    UsageSourceList,
    UsageSourceOut,
    UsageSourceUpdate,
    check_body_window,
    check_retention,
    csv_header,
    csv_row,
    export_row,
)
from .usage_controls_store import (
    export_day_rows,
    get_source,
    get_toolset,
    list_sources,
    list_toolsets,
    read_retention,
    update_source,
    update_toolset_body_samples,
    write_retention,
)

__all__ = ["audit", "router"]

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/tenants", tags=["usage"])


def _refusal(exc: UsageControlsError) -> HTTPException:
    """Translate a refusal into its HTTP error (``{code, message}``)."""
    return HTTPException(status_code=exc.status, detail=exc.detail())


def audit(
    *, tenant_id: str, action: str, auth_data: Dict[str, Any], actor_id: Any, target: str, detail: Dict[str, Any]
) -> None:
    """Write one metadata-only access-audit row (best-effort).

    An audit failure is logged and swallowed: a change that succeeded must not be reported as a
    failure because its audit row could not be appended.

    Args:
        tenant_id: The tenant.
        action: One of the ``AUDIT_*`` actions.
        auth_data: The authenticated principal.
        actor_id: The acting user id :func:`enforce_permission` resolved.
        target: What was acted on.
        detail: Action-specific metadata (never a value, a hash or a body).
    """
    try:
        db.write_access_audit(
            tenant_id=tenant_id,
            action=action,
            actor_id=str(actor_id) if actor_id else None,
            actor_label=auth_data.get("user_email") or auth_data.get("user_name"),
            target=target,
            source="api",
            detail=detail,
        )
    except Exception:  # noqa: BLE001 - auditing never fails the governed action
        _logger.warning("Failed to audit %s for tenant %s", action, tenant_id, exc_info=True)


def _project_id(tenant_id: str, project_ref: str) -> str:
    """Resolve a project slug or id within the tenant, or refuse with 404."""
    try:
        return str(resolve_project(tenant_id, project_ref)["id"])
    except ConsumerValidationError as exc:
        raise _http_error(exc) from exc


# ---------------------------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------------------------


@router.get(
    "/{tenant_slug}/usage/retention",
    response_model=UsageRetentionResponse,
    response_model_by_alias=True,
    summary="Read the workspace's usage retention",
    description=(
        "How long the usage index keeps **hourly counters** and **daily rollups**: the tier's caps "
        "(`usage_hourly_retention_days`, `usage_rollup_retention_days`; `-1` keeps rows forever), "
        "the workspace's own values (`null` uses the cap), and what the nightly purge applies (the "
        "smaller of the two). Body samples are purged after 7 days whatever the tier.\n\n"
        "Requires `projects:view`."
    ),
)
async def get_usage_retention(
    tenant_slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> UsageRetentionResponse:
    """Read the retention.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant scopes it).
        auth_data: The authenticated principal.

    Returns:
        Caps, setting and effective values.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    _ = tenant_slug
    return read_retention(db, _tenant_id(auth_data))


@router.put(
    "/{tenant_slug}/usage/retention",
    response_model=UsageRetentionResponse,
    response_model_by_alias=True,
    summary="Lower the workspace's usage retention",
    description=(
        "Keep usage counters for **fewer** days than the tier allows. A value above the cap is "
        "refused (`422 usage-retention-above-cap`, the message names the cap). `null` goes back "
        "to the cap. The next nightly purge deletes what is now past retention.\n\n"
        "Requires `members:edit` (Owner and Admin). Audited as `usage.retention.update`."
    ),
    responses={422: {"description": "`usage-retention-above-cap`, or a value below 1."}},
)
async def put_usage_retention(
    tenant_slug: str, body: RetentionUpdate, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> UsageRetentionResponse:
    """Store the workspace's own retention.

    Args:
        tenant_slug: The tenant in the URL.
        body: The values (``null`` = the cap).
        auth_data: The authenticated principal.

    Returns:
        The retention after the change.

    Raises:
        HTTPException: 422 above a cap, 403 without ``members:edit``.
    """
    actor_id = enforce_permission(db, auth_data, Resource.MEMBERS, Action.EDIT, target="usage-retention")
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    before = read_retention(db, tenant_id)
    try:
        check_retention(body, before.caps)
    except UsageControlsError as exc:
        raise _refusal(exc) from exc
    write_retention(db, tenant_id, hourly_days=body.hourly_days, rollup_days=body.rollup_days, user_id=actor_id)
    after = read_retention(db, tenant_id)
    audit(
        tenant_id=tenant_id,
        action=AUDIT_RETENTION_UPDATE,
        auth_data=auth_data,
        actor_id=actor_id,
        target="usage-retention",
        detail={
            "before": before.setting.model_dump(by_alias=True),
            "after": after.setting.model_dump(by_alias=True),
            "caps": after.caps.model_dump(by_alias=True),
        },
    )
    return after


# ---------------------------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------------------------


def _export_stream(tenant_id: str, project_id: str, *, since: Any, until: Any, fmt: str) -> Iterator[str]:
    """Yield the export one UTC day at a time, so memory stays bounded by one day's rows.

    Args:
        tenant_id: The tenant.
        project_id: The project.
        since: First UTC day (inclusive).
        until: Last UTC day (inclusive).
        fmt: ``csv`` or ``json``.

    Yields:
        Text chunks of the document.
    """
    calls = errors = count = 0
    if fmt == "csv":
        yield csv_header()
    else:
        head = {
            "format": EXPORT_FORMAT,
            "projectId": project_id,
            "since": since.isoformat(),
            "until": until.isoformat(),
        }
        yield json.dumps(head)[:-1] + ', "rows": ['
    day = since
    while day <= until:
        for raw in export_day_rows(db, tenant_id, project_id, day):
            row = export_row(raw)
            calls += row["calls"]
            errors += row["errors"]
            if fmt == "csv":
                yield csv_row(row)
            else:
                yield ("," if count else "") + json.dumps(row)
            count += 1
        day += timedelta(days=1)
    if fmt == "json":
        yield '], "totals": ' + json.dumps({"rows": count, "calls": calls, "errors": errors}) + "}"


@router.get(
    "/{tenant_slug}/projects/{project_ref}/usage/export",
    summary="Export the project's usage rollups",
    description=(
        "Stream the project's **daily usage rollups** for the last `days` UTC days (ending today) "
        "as `csv` or `json`: one row per day, environment, source, version, operation, status and "
        "consumer, with calls, errors, latency and bytes. The consumer is its slug, or `anonymous` "
        "for traffic no binding attributes. A binding's name, value or hash is never exported.\n\n"
        "The JSON document ends with `totals` (`rows`, `calls`, `errors`), the same sums the "
        "adoption views show for the window.\n\n"
        "Requires `versions:view`. Audited as `usage.export`."
    ),
    responses={
        200: {
            "content": {"text/csv": {}, "application/json": {}},
            "description": "The export, streamed as an attachment.",
        }
    },
)
async def export_usage(
    tenant_slug: str,
    project_ref: str,
    format: ExportFormat = Query(default="csv", description="`csv` or `json`."),  # noqa: A002 - the documented name
    days: int = Query(
        default=DEFAULT_EXPORT_DAYS, ge=1, le=MAX_EXPORT_DAYS, description="Window in UTC days, ending today."
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> StreamingResponse:
    """Stream the export.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        format: ``csv`` or ``json``.
        days: The window.
        auth_data: The authenticated principal.

    Returns:
        The streamed document.

    Raises:
        HTTPException: 404 for an unknown project, 403 without ``versions:view``.
    """
    actor_id = enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    project_id = _project_id(tenant_id, project_ref)
    until = datetime.now(timezone.utc).date()
    since = until - timedelta(days=days - 1)
    audit(
        tenant_id=tenant_id,
        action=AUDIT_EXPORT,
        auth_data=auth_data,
        actor_id=actor_id,
        target=project_id,
        detail={
            "projectId": project_id,
            "format": format,
            "days": days,
            "since": since.isoformat(),
            "until": until.isoformat(),
        },
    )
    media = "text/csv; charset=utf-8" if format == "csv" else "application/json"
    filename = f"usage-{project_id}-{since.isoformat()}-{until.isoformat()}.{format}"
    return StreamingResponse(
        _export_stream(tenant_id, project_id, since=since, until=until, fmt=format),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------------------------
# Sources and toolsets
# ---------------------------------------------------------------------------------------------


def _source_settings(source: UsageSourceOut) -> Dict[str, Any]:
    """The source settings an audit row quotes."""
    return {
        "samplingRate": source.sampling_rate,
        "fieldCapture": source.field_capture,
        "bodySampleRate": source.body_samples.rate,
        "bodySampleUntil": source.body_samples.until.isoformat() if source.body_samples.until else None,
    }


@router.get(
    "/{tenant_slug}/projects/{project_ref}/usage/sources",
    response_model=UsageSourceList,
    response_model_by_alias=True,
    summary="List the project's usage sources and agent toolsets",
    description=(
        "Everything that can keep this project's traffic: each **usage source** with its head "
        "sampling, field capture and body samples (at most 5 %, at most 7 days ahead), and each "
        "**agent toolset** with its AGX-3.3 body capture (at most 7 days ahead). Both opt-ins use "
        "one shape, `bodySamples`, and the sentence that opens a window is `acknowledgement`.\n\n"
        "Requires `projects:view`."
    ),
)
async def list_usage_sources(
    tenant_slug: str, project_ref: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> UsageSourceList:
    """List sources and toolsets.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        auth_data: The authenticated principal.

    Returns:
        The sources and toolsets.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    project_id = _project_id(tenant_id, project_ref)
    return UsageSourceList(
        sources=list_sources(db, tenant_id, project_id), agent_toolsets=list_toolsets(db, tenant_id, project_id)
    )


@router.patch(
    "/{tenant_slug}/projects/{project_ref}/usage/sources/{source_id}",
    response_model=UsageSourceOut,
    response_model_by_alias=True,
    summary="Change what a usage source captures",
    description=(
        "Set head sampling (`samplingRate`, in (0, 1]), field capture (`fieldCapture`: field "
        "names, never values) and/or body samples (`bodySamples`). A body-sample window takes a "
        "`rate` of at most 0.05 and an `until` at most 7 days ahead, and opening one requires the "
        "exact `acknowledgement` sentence (`422 usage-body-samples-acknowledgement-required`). "
        "`rate: 0` closes it.\n\n"
        "Requires `projects:edit`. Audited as `usage.source.update`, before and after."
    ),
    responses={
        404: {"description": "`usage-source-not-found`."},
        422: {
            "description": (
                "`usage-body-samples-invalid`, `usage-body-samples-acknowledgement-required` or "
                "`usage-settings-unchanged`."
            )
        },
    },
)
async def patch_usage_source(
    tenant_slug: str,
    project_ref: str,
    source_id: str,
    body: UsageSourceUpdate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> UsageSourceOut:
    """Change a source's capture settings.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        source_id: The source.
        body: The settings to change.
        auth_data: The authenticated principal.

    Returns:
        The source after the change.

    Raises:
        HTTPException: 404 / 422 as documented, 403 without ``projects:edit``.
    """
    actor_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT, target=source_id)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    project_id = _project_id(tenant_id, project_ref)
    try:
        if body.sampling_rate is None and body.field_capture is None and body.body_samples is None:
            raise UsageControlsError(
                CODE_NOTHING_TO_CHANGE, "set at least one of samplingRate, fieldCapture, bodySamples"
            )
        before = get_source(db, tenant_id, project_id, source_id)
        if before is None:
            raise UsageControlsError(CODE_SOURCE_NOT_FOUND, "this project has no such usage source", status=404)
        window: Dict[str, Any] = {}
        if body.body_samples is not None:
            until = check_body_window(body.body_samples, max_rate=BODY_SAMPLE_MAX_RATE)
            window = {"body_sample_rate": body.body_samples.rate, "body_sample_until": until}
    except UsageControlsError as exc:
        raise _refusal(exc) from exc
    after = update_source(
        db,
        tenant_id,
        project_id,
        source_id,
        sampling_rate=body.sampling_rate,
        field_capture=body.field_capture,
        **window,
    )
    if after is None:
        raise _refusal(UsageControlsError(CODE_SOURCE_NOT_FOUND, "this project has no such usage source", status=404))
    audit(
        tenant_id=tenant_id,
        action=AUDIT_SOURCE_UPDATE,
        auth_data=auth_data,
        actor_id=actor_id,
        target=source_id,
        detail={
            "projectId": project_id,
            "kind": after.kind,
            "before": _source_settings(before),
            "after": _source_settings(after),
            "acknowledged": bool(window and window["body_sample_rate"] > 0),
        },
    )
    return after


@router.patch(
    "/{tenant_slug}/agent-toolsets/{toolset_id}/body-samples",
    response_model=ToolsetBodySamplesOut,
    response_model_by_alias=True,
    summary="Open or close an agent toolset's body capture",
    description=(
        "The AGX-3.3 opt-in that keeps the bodies of a fraction of an agent toolset's `tools/call` "
        "invocations for debugging, in the same shape as a usage source's `bodySamples`: a "
        "`rate` (at most 1) and an `until` at most 7 days ahead. Opening a window requires the "
        "exact `acknowledgement` sentence. `rate: 0` closes it.\n\n"
        "Requires `api_keys:edit`, like every toolset setting. Audited as "
        "`agent.toolset.body_samples.update`, before and after."
    ),
    responses={
        404: {"description": "`agent-toolset-not-found`."},
        422: {"description": "`usage-body-samples-invalid` or `usage-body-samples-acknowledgement-required`."},
    },
)
async def patch_toolset_body_samples(
    tenant_slug: str,
    toolset_id: UUID,
    body: BodySampleWindow,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ToolsetBodySamplesOut:
    """Change a toolset's body-capture window.

    Args:
        tenant_slug: The tenant in the URL.
        toolset_id: The toolset.
        body: The window.
        auth_data: The authenticated principal.

    Returns:
        The toolset after the change.

    Raises:
        HTTPException: 404 / 422 as documented, 403 without ``api_keys:edit``.
    """
    actor_id = enforce_permission(db, auth_data, Resource.API_KEYS, Action.EDIT)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        before = get_toolset(db, tenant_id, str(toolset_id))
        if before is None:
            raise UsageControlsError(CODE_TOOLSET_NOT_FOUND, "no such agent toolset", status=404)
        until = check_body_window(body, max_rate=AGENT_BODY_CAPTURE_MAX_RATE)
    except UsageControlsError as exc:
        raise _refusal(exc) from exc
    after = update_toolset_body_samples(
        db, tenant_id, str(toolset_id), rate=body.rate, until=until, user_id=str(actor_id) if actor_id else None
    )
    if after is None:
        raise _refusal(UsageControlsError(CODE_TOOLSET_NOT_FOUND, "no such agent toolset", status=404))
    audit(
        tenant_id=tenant_id,
        action=AUDIT_TOOLSET_BODY_SAMPLES,
        auth_data=auth_data,
        actor_id=actor_id,
        target=after.id,
        detail={
            "versionId": after.version_id,
            "before": _window(before),
            "after": _window(after),
            "acknowledged": body.rate > 0,
        },
    )
    return after


def _window(toolset: ToolsetBodySamplesOut) -> Dict[str, Optional[Any]]:
    """The body-capture window an audit row quotes."""
    until = toolset.body_samples.until
    return {"rate": toolset.body_samples.rate, "until": until.isoformat() if until else None}
