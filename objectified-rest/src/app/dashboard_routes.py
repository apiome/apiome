"""Dashboard API routes (REPO-10.3 / #2949: tenant-level repository corpus roll-up)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .repositories.attention import attention_detail_query_tab, top_reason_for_chips
from .repositories_routes import (
    _REPOSITORY_SCOPE_READ,
    _require_repository_scope,
    collect_recent_import_attention_rows,
    get_repository_corpus_rollup,
)

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])


class RepositoryCorpusStatsResponse(BaseModel):
    """Cross-repository aggregate spec counts for the scanned report dashboard."""

    repositoriesTracked: int
    importableSpecs: int
    awaitingSelection: int
    parseErrors: int
    manifestErrors: int
    refreshedAt: str


@router.get(
    "/{tenant_slug}/repository_corpus_stats",
    response_model=RepositoryCorpusStatsResponse,
    summary="Tenant corpus stats for scan reports (rolled up server-side).",
)
async def read_repository_corpus_stats(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryCorpusStatsResponse:
    _ = tenant_slug
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_READ)
    tenant_id = str(auth_data["tenant_id"])
    data = get_repository_corpus_rollup(tenant_id)
    return RepositoryCorpusStatsResponse(**data)


class RepositoryAttentionItem(BaseModel):
    """Per-row projection for the dashboard attention widget (REPO-11.2 / #2942)."""

    repositoryId: str
    fullName: str
    reasons: List[str]
    topReason: str
    detailTab: str
    openCount: int
    attentionScore: int
    lastChangeAt: str


class RepositoryAttentionResponse(BaseModel):
    items: List[RepositoryAttentionItem] = Field(default_factory=list)
    repositoriesTracked: int
    needingAttentionCount: int
    otherHealthyCount: int
    refreshedAt: str


class RecentImportAttentionItem(BaseModel):
    """One row for Recent Imports Needing Attention (REPO-11.3 / #2943)."""

    importJobId: str
    repositoryId: str
    repositoryFullName: str
    projectName: str
    versionLabel: str
    state: str
    reasonKind: str
    primaryReason: str
    createdAt: str
    changeReportPath: str


class RecentImportAttentionResponse(BaseModel):
    items: List[RecentImportAttentionItem] = Field(default_factory=list)
    refreshedAt: str


class DismissRecentImportAttentionBody(BaseModel):
    importJobId: str = Field(min_length=1)


@router.get(
    "/{tenant_slug}/repository_attention",
    response_model=RepositoryAttentionResponse,
    summary="Top repositories by attention roll-up (tenant, repository.read).",
)
async def read_repository_attention(
    tenant_slug: str,
    limit: int = Query(default=5, ge=1, le=50),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryAttentionResponse:
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    _ = tenant_slug
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_READ)
    tenant_id = str(auth_data["tenant_id"])
    rows, total_tracked, needing = db.list_repository_attention_for_tenant(tenant_id, limit)
    other_healthy = max(0, int(total_tracked) - int(needing))
    items: List[RepositoryAttentionItem] = []
    for row in rows:
        rid = str(row.get("repository_id", "") or row.get("repositoryId", ""))
        owner = str(row.get("owner", "") or "")
        name = str(row.get("name", "") or "")
        full = f"{owner}/{name}" if (owner and name) else (owner or name or rid)
        raw_reasons = row.get("reasons") or []
        if isinstance(raw_reasons, (list, tuple)):
            reasons = [str(x) for x in raw_reasons]
        else:
            reasons = [str(raw_reasons)]
        top = top_reason_for_chips(reasons)
        tab = attention_detail_query_tab(reasons)
        items.append(
            RepositoryAttentionItem(
                repositoryId=rid,
                fullName=full,
                reasons=reasons,
                topReason=top,
                detailTab=tab,
                openCount=int(row.get("open_count") or row.get("openCount") or 0),
                attentionScore=int(row.get("attention_score") or row.get("attentionScore") or 0),
                lastChangeAt=str(
                    row.get("last_change_at")
                    or row.get("lastChangeAt")
                    or _now_iso()
                ),
            )
        )
    return RepositoryAttentionResponse(
        items=items,
        repositoriesTracked=int(total_tracked),
        needingAttentionCount=int(needing),
        otherHealthyCount=other_healthy,
        refreshedAt=_now_iso(),
    )


@router.get(
    "/{tenant_slug}/recent_imports_attention",
    response_model=RecentImportAttentionResponse,
    summary="Recent repository import jobs needing review (repository.read).",
)
async def read_recent_imports_attention(
    tenant_slug: str,
    limit: int = Query(default=5, ge=1, le=50),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RecentImportAttentionResponse:
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    _ = tenant_slug
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_READ)
    tenant_id = str(auth_data["tenant_id"])
    uid = get_authenticated_user_id(auth_data)
    dismissed: set[str] = set()
    if uid:
        dismissed = set(db.get_dismissed_recent_import_job_ids(str(uid), tenant_id))
    rows = collect_recent_import_attention_rows(
        tenant_id,
        dismissed_import_job_ids=dismissed,
        limit=limit,
    )
    items = [RecentImportAttentionItem(**row) for row in rows]
    return RecentImportAttentionResponse(items=items, refreshedAt=_now_iso())


@router.post(
    "/{tenant_slug}/recent_imports_attention/dismiss",
    summary="Dismiss one recent-import attention row for the current user (user_settings).",
)
async def dismiss_recent_import_attention_row(
    tenant_slug: str,
    body: DismissRecentImportAttentionBody,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, bool]:
    _ = tenant_slug
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_READ)
    tenant_id = str(auth_data["tenant_id"])
    uid = get_authenticated_user_id(auth_data)
    if not uid:
        raise HTTPException(status_code=401, detail="User id required for dismissal")
    jid = body.importJobId.strip()
    db.dismiss_recent_import_attention_job(str(uid), tenant_id, jid)
    db.mark_repository_import_notifications_read_for_job(str(uid), tenant_id, jid)
    return {"ok": True}


class RepositoryImportNotificationItem(BaseModel):
    """In-app notification row for repository import outcomes (REPO-12.5 / #2954)."""

    id: str
    importJobId: str
    repositoryId: str
    title: str
    body: str
    primaryLink: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    readAt: str | None = None
    createdAt: str


class RepositoryImportNotificationsResponse(BaseModel):
    items: List[RepositoryImportNotificationItem]
    unreadCount: int


def _iso_or_none(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc).isoformat()
        return v.isoformat()
    return str(v)


def _iso_required(v: Any) -> str:
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc).isoformat()
        return v.isoformat()
    return str(v)


@router.get(
    "/{tenant_slug}/repository_import_notifications",
    response_model=RepositoryImportNotificationsResponse,
    summary="In-app notifications for repository import jobs (REPO-12.5).",
)
async def list_repository_import_notifications(
    tenant_slug: str,
    limit: int = Query(default=20, ge=1, le=100),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryImportNotificationsResponse:
    _ = tenant_slug
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_READ)
    tenant_id = str(auth_data["tenant_id"])
    uid = get_authenticated_user_id(auth_data)
    if not uid:
        raise HTTPException(status_code=401, detail="User id required")
    rows = db.list_repository_import_notifications(str(uid), tenant_id, limit=limit)
    unread = db.count_unread_repository_import_notifications(str(uid), tenant_id)
    items = [
        RepositoryImportNotificationItem(
            id=str(r.get("id", "")),
            importJobId=str(r.get("importJobId", "")),
            repositoryId=str(r.get("repositoryId", "")),
            title=str(r.get("title", "")),
            body=str(r.get("body", "")),
            primaryLink=str(r.get("primaryLink", "")),
            payload=dict(r.get("payload") or {}) if isinstance(r.get("payload"), dict) else {},
            readAt=_iso_or_none(r.get("readAt")),
            createdAt=_iso_required(r.get("createdAt")),
        )
        for r in rows
    ]
    return RepositoryImportNotificationsResponse(items=items, unreadCount=unread)


@router.get(
    "/{tenant_slug}/repository_import_notifications/unread_count",
    summary="Unread count for repository import in-app notifications.",
)
async def repository_import_notifications_unread_count(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, int]:
    _ = tenant_slug
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_READ)
    tenant_id = str(auth_data["tenant_id"])
    uid = get_authenticated_user_id(auth_data)
    if not uid:
        raise HTTPException(status_code=401, detail="User id required")
    n = db.count_unread_repository_import_notifications(str(uid), tenant_id)
    return {"unreadCount": n}
