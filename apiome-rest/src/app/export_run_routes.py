"""Export history & audit routes — MFX-46.1 (#4379).

``GET /v1/export/{tenant_slug}/runs`` lists the tenant's export history from the run ledger
(:mod:`app.export_run_ledger`): who exported what, where, with how much loss — filterable by source,
target, actor, outcome, delivery channel, validation verdict, delivery decision and date, newest first,
each run with its deliveries. ``GET …/runs/{job_id}`` returns one run with its stored reports, read-only,
and ``GET …/runs/actors`` the people who appear in the history (for the actor filter).

Every read is scoped to the caller's tenant (the URL's tenant must be theirs) and needs
``projects:view``, like the per-job delivery listings.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import validate_authentication
from .database import db
from .export_run_ledger import (
    ExportRunActor,
    ExportRunActorsResponse,
    ExportRunDetail,
    ExportRunListResponse,
    deliveries_by_job,
    run_detail,
    run_summary,
)
from .permissions import Action, Resource, enforce_permission
from .sdk_publish_routes import tenant_id_of

router = APIRouter(prefix="/v1/export", tags=["export"])


def _tenant(tenant_slug: str, auth_data: Dict[str, Any]) -> str:
    """The caller's tenant id, once ``projects:view`` is checked and the URL's tenant is theirs (else 404)."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    try:
        row = db.get_tenant_row_by_slug(tenant_slug)
    except Exception:  # noqa: BLE001 - treat an unreadable tenant like an unknown one
        row = None
    if not row or str(row.get("id")) != str(tenant_id):
        raise HTTPException(status_code=404, detail="Tenant not found")
    return str(tenant_id)


@router.get(
    "/{tenant_slug}/runs",
    response_model=ExportRunListResponse,
    summary="List the export history",
    description=(
        "The tenant's export runs, newest first (MFX-46.1): source and revision, target, actor, outcome, "
        "preserved %, validation and lint verdicts, delivery decision and every delivery. Filter by "
        "`artifact`, `target`, `actor`, `state`, `channel` (`git`, `webhook`, `object-storage`, `none`), "
        "`validation`, `decision` and `finished_after` / `finished_before`. Runs are kept for the job "
        "history window (90 days by default). Requires `projects:view`."
    ),
)
async def list_export_runs(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
    artifact: Optional[str] = Query(None, description="Only runs of this artifact (project or catalog item) id."),
    target: Optional[str] = Query(None, description="Only runs that requested this target key."),
    actor: Optional[str] = Query(None, description="Only runs started by this user id."),
    state: Optional[Literal["completed", "failed", "canceled"]] = Query(None, description="Only runs that ended so."),
    channel: Optional[Literal["git", "webhook", "object-storage", "none"]] = Query(
        None, description="Only runs delivered through this channel, or (`none`) never delivered."
    ),
    validation: Optional[Literal["valid", "invalid", "skipped", "not_applicable"]] = Query(
        None, description="Only runs with this validation verdict."
    ),
    decision: Optional[Literal["allow", "allow_with_warning", "block"]] = Query(
        None, description="Only runs with this delivery decision."
    ),
    finished_after: Optional[datetime] = Query(None, description="Inclusive lower bound on when the run ended."),
    finished_before: Optional[datetime] = Query(None, description="Inclusive upper bound on when the run ended."),
    limit: int = Query(50, ge=1, le=200, description="Page size (default 50, max 200)."),
    offset: int = Query(0, ge=0, description="Runs to skip."),
) -> ExportRunListResponse:
    """List the tenant's export history.

    Args:
        tenant_slug: The tenant (must be the caller's).
        auth_data: Authenticated principal.
        artifact: Artifact filter.
        target: Target filter.
        actor: Actor (user id) filter.
        state: Outcome filter.
        channel: Delivery channel filter.
        validation: Validation verdict filter.
        decision: Delivery decision filter.
        finished_after: Lower date bound.
        finished_before: Upper date bound.
        limit: Page size.
        offset: Runs to skip.

    Returns:
        One page of runs with their deliveries, and the total matching.
    """
    tenant_id = _tenant(tenant_slug, auth_data)
    page = await asyncio.to_thread(
        lambda: db.list_export_runs(
            tenant_id,
            artifact_id=artifact,
            target=target,
            actor_id=actor,
            state=state,
            channel=channel,
            validation_verdict=validation,
            delivery_decision=decision,
            finished_after=finished_after,
            finished_before=finished_before,
            limit=limit,
            offset=offset,
        )
    )
    rows = page.get("runs") or []
    deliveries = deliveries_by_job(
        await asyncio.to_thread(db.list_export_run_deliveries, tenant_id, [r["job_id"] for r in rows])
    )
    return ExportRunListResponse(
        runs=[run_summary(row, deliveries.get(row["job_id"], [])) for row in rows],
        total=int(page.get("total") or 0),
        limit=int(page.get("limit") or limit),
        offset=int(page.get("offset") or 0),
    )


@router.get(
    "/{tenant_slug}/runs/actors",
    response_model=ExportRunActorsResponse,
    summary="List the people in the export history",
    description="Everyone who started a recorded export, most recent first (for the actor filter). "
    "Requires `projects:view`.",
)
async def list_export_run_actors(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportRunActorsResponse:
    """List the actors of the tenant's recorded exports.

    Args:
        tenant_slug: The tenant (must be the caller's).
        auth_data: Authenticated principal.

    Returns:
        The actors, most recent first.
    """
    tenant_id = _tenant(tenant_slug, auth_data)
    rows = await asyncio.to_thread(db.list_export_run_actors, tenant_id)
    return ExportRunActorsResponse(
        actors=[ExportRunActor(actor_id=r["actor_id"], actor_label=r["actor_label"]) for r in rows]
    )


@router.get(
    "/{tenant_slug}/runs/{job_id}",
    response_model=ExportRunDetail,
    summary="Get one export run with its stored reports",
    description="One run of the export history with its deliveries and, per target, the fidelity, "
    "validation and delivery-gate reports as they were when it ran (read-only). Requires `projects:view`.",
)
async def get_export_run(
    tenant_slug: str,
    job_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportRunDetail:
    """One run of the tenant's export history.

    Args:
        tenant_slug: The tenant (must be the caller's).
        job_id: The export job.
        auth_data: Authenticated principal.

    Returns:
        The run, its deliveries and its stored reports.

    Raises:
        HTTPException: 404 when the run is not in this tenant's history.
    """
    tenant_id = _tenant(tenant_slug, auth_data)
    row = await asyncio.to_thread(db.get_export_run, tenant_id, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Export run not found")
    deliveries = deliveries_by_job(await asyncio.to_thread(db.list_export_run_deliveries, tenant_id, [job_id]))
    return run_detail(row, deliveries.get(job_id, []))
