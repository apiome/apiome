"""Revision DAG read routes — ancestors, history window and merge-base (#2593).

* ``GET /v1/versions/{tenant_slug}/{project_id}/{revision_id}/ancestors`` — ``ancestors(rev, depth)``:
  the revisions reachable from one revision, each with its distance;
* ``GET /v1/versions/{tenant_slug}/{project_id}/revision-graph/history`` — the same window from
  several tips at once (by default every branch tip), the bulk query behind the history graph;
* ``GET /v1/versions/{tenant_slug}/{project_id}/revision-graph/merge-base`` —
  ``mergeBase(revA, revB)``, ``null`` when the histories are disjoint.

Each request costs one recursive query for the ancestor closure
(:meth:`~app.database.Database.fetch_revision_closure`) plus one lookup per named revision; the
graph work happens in :mod:`app.revision_dag`. A window walks at most
:data:`~app.revision_dag.MAX_HISTORY_DEPTH` parent steps and returns at most
:data:`~app.revision_dag.MAX_HISTORY_LIMIT` revisions, and says when either cut it short.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import validate_authentication
from .database import db
from .models import (
    RevisionGraphNodeOut,
    RevisionHistoryWindowResponse,
    RevisionMergeBaseOut,
    RevisionMergeBaseResponse,
)
from .permissions import Action, Resource, enforce_permission
from .revision_dag import (
    DEFAULT_HISTORY_DEPTH,
    DEFAULT_HISTORY_LIMIT,
    MAX_HISTORY_DEPTH,
    MAX_HISTORY_LIMIT,
    history_window,
    merge_base_candidates,
)

__all__ = ["router"]

router = APIRouter(prefix="/v1/versions", tags=["versions"])

#: The most tips one history request may name.
MAX_HISTORY_TIPS = 50


def _require_project(project_id: str, tenant_id: str) -> Dict[str, Any]:
    """The project, or 404."""
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return project


def _require_revision(revision_id: str, project_id: str, tenant_id: str, *, field: str) -> Dict[str, Any]:
    """The revision, which must exist in the tenant and belong to ``project_id``.

    Raises:
        HTTPException: 404 ``REVISION_NOT_FOUND``; 400 ``REVISION_PROJECT_MISMATCH``.
    """
    row = db.get_version_by_id(revision_id, tenant_id)
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"code": "REVISION_NOT_FOUND", "message": f"No revision {revision_id!r}.", "field": field},
        )
    if str(row.get("project_id")) != str(project_id):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "REVISION_PROJECT_MISMATCH",
                "message": f"Revision {revision_id!r} belongs to a different project.",
                "field": field,
            },
        )
    return row


def _window(tips: List[str], tenant_id: str, *, depth: int, limit: int) -> RevisionHistoryWindowResponse:
    """Load the tips' ancestor closure once and cut the window from it."""
    closure = db.fetch_revision_closure(tips, tenant_id)
    window = history_window(closure, tips, depth=depth, limit=limit)
    return RevisionHistoryWindowResponse(
        tips=tips,
        depth=max(0, min(depth, MAX_HISTORY_DEPTH)),
        limit=max(1, min(limit, MAX_HISTORY_LIMIT)),
        truncated=window.truncated,
        nodes=[
            RevisionGraphNodeOut(
                revision_id=node.revision_id,
                version_label=node.version_label,
                parent_revision_id=node.parent_id,
                merge_parent_revision_id=node.merge_parent_id,
                created_at=node.created_at,
                distance=window.distances[node.revision_id],
            )
            for node in window.nodes
        ],
    )


@router.get(
    "/{tenant_slug}/{project_id}/{revision_id}/ancestors",
    response_model=RevisionHistoryWindowResponse,
    response_model_by_alias=True,
)
async def get_revision_ancestors(
    tenant_slug: str,
    project_id: str,
    revision_id: str,
    depth: int = Query(DEFAULT_HISTORY_DEPTH, ge=0, le=MAX_HISTORY_DEPTH, description="Parent steps to walk."),
    limit: int = Query(DEFAULT_HISTORY_LIMIT, ge=1, le=MAX_HISTORY_LIMIT, description="Most revisions to return."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RevisionHistoryWindowResponse:
    """``ancestors(revX, depth)``: the revision and its ancestors within ``depth`` parent steps (#2593).

    Follows both parents of a merge. Each revision carries its distance — the fewest parent steps
    from ``revision_id`` (itself 0).
    """
    _ = tenant_slug  # kept for route consistency with the other version endpoints
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_project(project_id, tenant_id)
    _require_revision(revision_id, project_id, tenant_id, field="revisionId")
    return _window([revision_id], tenant_id, depth=depth, limit=limit)


@router.get(
    "/{tenant_slug}/{project_id}/revision-graph/history",
    response_model=RevisionHistoryWindowResponse,
    response_model_by_alias=True,
)
async def get_revision_history_window(
    tenant_slug: str,
    project_id: str,
    tip: Optional[List[str]] = Query(
        None, description="Revision ids to start from (repeatable); every branch tip when omitted."
    ),
    depth: int = Query(DEFAULT_HISTORY_DEPTH, ge=0, le=MAX_HISTORY_DEPTH, description="Parent steps to walk."),
    limit: int = Query(DEFAULT_HISTORY_LIMIT, ge=1, le=MAX_HISTORY_LIMIT, description="Most revisions to return."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RevisionHistoryWindowResponse:
    """The history window behind the revision graph: everything within ``depth`` of the tips (#2593).

    One request returns the whole window — revisions with both parent ids and their distance —
    so the graph needs no request per revision.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_project(project_id, tenant_id)
    tips = list(dict.fromkeys(t.strip() for t in (tip or []) if t and t.strip()))
    if not tips:
        branches = db.list_version_branches_for_project(project_id, tenant_id) or []
        tips = list(dict.fromkeys(str(b["tip_version_id"]) for b in branches if b.get("tip_version_id")))
        if not tips:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "TIPS_REQUIRED",
                    "message": "The project has no branches; name the revisions to start from with ?tip=.",
                },
            )
    if len(tips) > MAX_HISTORY_TIPS:
        raise HTTPException(
            status_code=400,
            detail={"code": "TOO_MANY_TIPS", "message": f"At most {MAX_HISTORY_TIPS} tips per request."},
        )
    for value in tips:
        _require_revision(value, project_id, tenant_id, field="tip")
    return _window(tips, tenant_id, depth=depth, limit=limit)


@router.get(
    "/{tenant_slug}/{project_id}/revision-graph/merge-base",
    response_model=RevisionMergeBaseResponse,
    response_model_by_alias=True,
)
async def get_revision_merge_base(
    tenant_slug: str,
    project_id: str,
    a: str = Query(..., description="One revision id."),
    b: str = Query(..., description="The other revision id."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RevisionMergeBaseResponse:
    """``mergeBase(revA, revB)``: the best common ancestor of two revisions, or null (#2593).

    Of the common ancestors that are an ancestor of no other common ancestor, the most recently
    created is the merge base; all of them are listed as ``candidates`` (more than one only in a
    criss-cross history). Disjoint histories return ``mergeBase: null`` and ``disjoint: true``.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_project(project_id, tenant_id)
    _require_revision(a, project_id, tenant_id, field="a")
    _require_revision(b, project_id, tenant_id, field="b")
    closure = {node.revision_id: node for node in db.fetch_revision_closure([a, b], tenant_id)}
    candidates = merge_base_candidates(closure, a, b)
    base = closure.get(candidates[0]) if candidates else None
    return RevisionMergeBaseResponse(
        a=a,
        b=b,
        merge_base=(
            RevisionMergeBaseOut(
                revision_id=base.revision_id, version_label=base.version_label, created_at=base.created_at
            )
            if base is not None
            else None
        ),
        candidates=candidates,
        disjoint=not candidates,
    )
