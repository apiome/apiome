"""Project activity timeline route — #2594.

``GET /v1/versions/{tenant_slug}/{project_id}/timeline`` — the project's publishes, merges, tag
changes and protection changes as one newest-first stream, each event linked to the revision it
concerns so a client can jump between this timeline and the revision DAG (#2593) both ways.

Rules (see :mod:`app.project_timeline`):

* tenant **and** project scoped — another project's events never appear;
* ``versions:view`` is required; failures and denied attempts are shown to tenant administrators
  only (``restricted: true`` tells everyone else they were left out);
* keyset pagination on ``(occurredAt, id)``, at most
  :data:`~app.project_timeline.MAX_TIMELINE_LIMIT` events per page.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .models import ProjectTimelineEventOut, ProjectTimelineLinksOut, ProjectTimelineResponse
from .permissions import Action, Resource, enforce_permission
from .project_timeline import (
    DEFAULT_TIMELINE_LIMIT,
    MAX_TIMELINE_LIMIT,
    TimelineEvent,
    kind_filter,
    parse_kinds,
    to_events,
    visible_outcomes,
)
from .workflow_audit_routes import (
    _decode_cursor,
    _encode_cursor,
    _optional_uuid_param,
    _parse_iso_datetime,
)

__all__ = ["router"]

router = APIRouter(prefix="/v1/versions", tags=["versions"])


def _event_out(event: TimelineEvent) -> ProjectTimelineEventOut:
    """A :class:`TimelineEvent` as its response model."""
    return ProjectTimelineEventOut(
        id=event.id,
        source=event.source,
        kind=event.kind,
        action=event.action,
        outcome=event.outcome,
        actor_id=event.actor_id,
        occurred_at=event.occurred_at,
        revision_id=event.revision_id,
        version_label=event.version_label,
        merge_from_revision_id=event.merge_from_revision_id,
        merge_from_branch=event.merge_from_branch,
        branch_name=event.branch_name,
        tag_name=event.tag_name,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        detail=event.detail,
        links=ProjectTimelineLinksOut(**event.links) if event.links else None,
    )


@router.get(
    "/{tenant_slug}/{project_id}/timeline",
    response_model=ProjectTimelineResponse,
    response_model_by_alias=True,
)
async def get_project_timeline(
    tenant_slug: str,
    project_id: str,
    revision_id: Optional[str] = Query(
        None, alias="revisionId", description="Only events that concern this revision."
    ),
    kind: Optional[List[str]] = Query(
        None,
        description="publish, merge, tag, protection or other (repeatable or comma-separated).",
    ),
    actor_id: Optional[str] = Query(None, alias="actorId", description="Only events by this user."),
    since: Optional[str] = Query(None, description="Inclusive lower bound on occurredAt (ISO 8601)."),
    until: Optional[str] = Query(None, description="Inclusive upper bound on occurredAt (ISO 8601)."),
    limit: int = Query(DEFAULT_TIMELINE_LIMIT, ge=1, le=MAX_TIMELINE_LIMIT, description="Page size."),
    cursor: Optional[str] = Query(None, description="nextCursor from the previous page."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ProjectTimelineResponse:
    """The project's activity timeline, newest first (#2594).

    Each event that concerns a revision carries ``revisionId`` and ``links`` to that revision, its
    ancestors in the revision DAG and this timeline filtered to it.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    try:
        kinds = parse_kinds(kind)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "INVALID_KIND", "message": str(e)}) from e
    rid = _optional_uuid_param("revisionId", revision_id)
    aid = _optional_uuid_param("actorId", actor_id)
    since_dt = _parse_iso_datetime("since", since)
    until_dt = _parse_iso_datetime("until", until)
    cur_ts = cur_id = None
    if cursor:
        try:
            cur_ts, cur_id = _decode_cursor(cursor)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid cursor: {e}") from e

    uid = get_authenticated_user_id(auth_data)
    is_admin = bool(uid and db.is_user_tenant_admin(tenant_id, uid))
    outcomes = visible_outcomes(is_admin)

    rows = db.list_project_timeline(
        tenant_id,
        project_id,
        revision_id=rid,
        kinds=kind_filter(kinds),
        outcomes=outcomes,
        actor_id=aid,
        since=since_dt,
        until=until_dt,
        limit=limit + 1,
        cursor_created_at=cur_ts,
        cursor_id=cur_id,
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        _encode_cursor(rows[-1].get("created_at"), str(rows[-1]["id"])) if has_more and rows else None
    )
    events = to_events(rows, tenant_slug=tenant_slug, project_id=project_id)
    return ProjectTimelineResponse(
        project_id=project_id,
        items=[_event_out(e) for e in events],
        limit=limit,
        has_more=has_more,
        next_cursor=next_cursor,
        restricted=outcomes is not None,
    )
