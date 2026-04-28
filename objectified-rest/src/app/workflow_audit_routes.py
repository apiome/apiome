"""
Workflow audit ledger — paginated list API (#2578, P1-06).

GET /v1/versions/{tenant_slug}/workflow-audit
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import validate_authentication
from .database import db
from .models import (
    WorkflowAuditChangeReportJoinOut,
    WorkflowAuditEntryOut,
    WorkflowAuditPageResponse,
    WorkflowAuditPaginationOut,
)
from .repositories.spec_detail import derive_change_report_summary_kind

router = APIRouter(prefix="/v1/versions", tags=["workflow-audit"])

_MAX_LIMIT = 500
_DEFAULT_LIMIT = 50


def _parse_iso_datetime(label: str, raw: Optional[str]) -> Optional[datetime]:
    if raw is None or str(raw).strip() == "":
        return None
    s = str(raw).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {label}: expected ISO 8601 datetime ({e})",
        ) from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _optional_uuid_param(label: str, raw: Optional[str]) -> Optional[str]:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return str(uuid.UUID(str(raw).strip()))
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {label}: expected UUID",
        ) from e


def _normalize_actions(raw: Optional[List[str]]) -> Optional[List[str]]:
    if not raw:
        return None
    out = [str(x).strip() for x in raw if x is not None and str(x).strip() != ""]
    return out or None


def _normalize_outcome(raw: Optional[str]) -> Optional[str]:
    if raw is None or str(raw).strip() == "":
        return None
    o = str(raw).strip().lower()
    if o not in ("success", "failure"):
        raise HTTPException(
            status_code=400,
            detail="Invalid outcome: expected success or failure",
        )
    return o


def _encode_cursor(created_at: Any, row_id: str) -> str:
    if hasattr(created_at, "isoformat"):
        ts = created_at.isoformat()
    else:
        ts = str(created_at)
    payload = json.dumps({"t": ts, "i": str(row_id)}, separators=(",", ":"))
    raw = base64.urlsafe_b64encode(payload.encode()).decode("ascii")
    return raw.rstrip("=")


def _decode_cursor(token: str) -> Tuple[datetime, str]:
    s = str(token).strip()
    if not s:
        raise ValueError("empty cursor")
    pad = "=" * (-len(s) % 4)
    try:
        data = base64.urlsafe_b64decode(s + pad)
    except (binascii.Error, ValueError) as e:
        raise ValueError("invalid base64") from e
    try:
        obj = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError("invalid json") from e
    if not isinstance(obj, dict):
        raise ValueError("cursor must be a JSON object")
    ts = obj.get("t")
    rid = obj.get("i")
    if not isinstance(ts, str) or not isinstance(rid, str):
        raise ValueError("cursor missing t or i")
    ts_norm = ts.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(ts_norm)
    except ValueError as e:
        raise ValueError("bad timestamp") from e
    if dt.tzinfo is None:
        raise ValueError("cursor timestamp missing timezone info")
    try:
        uuid.UUID(rid)
    except ValueError as e:
        raise ValueError("bad id") from e
    return dt, rid


def _auto_import_change_report_projection(detail: Dict[str, Any]) -> WorkflowAuditChangeReportJoinOut | None:
    cr_id = detail.get("changeReportId") or detail.get("change_report_id")
    if not cr_id:
        return None
    sk = detail.get("changeReportSummaryKind") or detail.get("change_report_summary_kind")
    bc_raw = detail.get("changeReportBreakingChangeCount")
    if bc_raw is None:
        bc_raw = detail.get("breaking_change_count")
    ad_raw = detail.get("changeReportAdditiveChangeCount")
    if ad_raw is None:
        ad_raw = detail.get("additive_change_count")
    bc_i: int
    ad_i: int
    try:
        bc_i = int(bc_raw) if bc_raw is not None else 0
    except (TypeError, ValueError):
        bc_i = 0
    try:
        ad_i = int(ad_raw) if ad_raw is not None else 0
    except (TypeError, ValueError):
        ad_i = 0
    if not isinstance(sk, str) or not sk.strip():
        sk = derive_change_report_summary_kind(bc_i, ad_i)
    else:
        sk = sk.strip()
    return WorkflowAuditChangeReportJoinOut(
        id=str(cr_id),
        summary_kind=sk,
        breaking_change_count=bc_i,
    )


def _row_to_entry(row: Dict[str, Any]) -> WorkflowAuditEntryOut:
    ca = row.get("created_at")
    if hasattr(ca, "isoformat"):
        ca_s = ca.isoformat()
    elif ca is None:
        ca_s = ""
    else:
        ca_s = str(ca)
    detail = row.get("detail")
    if detail is not None and not isinstance(detail, dict):
        detail = None
    change_report: WorkflowAuditChangeReportJoinOut | None = None
    if str(row.get("action")) == "repository.auto_imported" and isinstance(detail, dict):
        change_report = _auto_import_change_report_projection(detail)
    return WorkflowAuditEntryOut(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        project_id=str(row["project_id"]) if row.get("project_id") is not None else None,
        version_id=str(row["version_id"]) if row.get("version_id") is not None else None,
        action=str(row["action"]),
        outcome=str(row["outcome"]),
        actor_id=str(row["actor_id"]) if row.get("actor_id") is not None else None,
        detail=detail,
        created_at=ca_s,
        change_report=change_report,
    )


@router.get(
    "/{tenant_slug}/workflow-audit",
    response_model=WorkflowAuditPageResponse,
    response_model_by_alias=True,
)
async def list_workflow_audit(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
    action: Optional[List[str]] = Query(
        None,
        description="Filter by action (repeat for multiple, e.g. version.push).",
    ),
    actor_id: Optional[str] = Query(
        None,
        alias="actorId",
        description="Filter by actor user id (UUID).",
    ),
    outcome: Optional[str] = Query(
        None,
        description="Filter by outcome: success or failure.",
    ),
    version_id: Optional[str] = Query(
        None,
        alias="versionId",
        description="Filter by revision id (versions.id) stored on the audit row.",
    ),
    project_id: Optional[str] = Query(
        None,
        alias="projectId",
        description="Restrict to a project id (UUID); must belong to the tenant.",
    ),
    since: Optional[str] = Query(
        None,
        description="Inclusive lower bound on createdAt (ISO 8601).",
    ),
    until: Optional[str] = Query(
        None,
        description="Inclusive upper bound on createdAt (ISO 8601).",
    ),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    cursor: Optional[str] = Query(
        None,
        description="Opaque next-page token from pagination.nextCursor (cursor mode).",
    ),
) -> WorkflowAuditPageResponse:
    """
    List workflow audit events for the tenant (newest first).

    Pagination: use **offset** + **limit**, or **cursor** + **limit**. Do not combine
    **cursor** with a non-zero **offset**.
    """
    tid = auth_data["tenant_id"]

    if cursor and offset != 0:
        raise HTTPException(
            status_code=400,
            detail="Do not pass both cursor and a non-zero offset",
        )

    actions = _normalize_actions(action)
    out_f = _normalize_outcome(outcome)
    aid = _optional_uuid_param("actorId", actor_id)
    vid = _optional_uuid_param("versionId", version_id)
    pid = _optional_uuid_param("projectId", project_id)
    since_dt = _parse_iso_datetime("since", since)
    until_dt = _parse_iso_datetime("until", until)

    if pid is not None:
        proj = db.get_project_by_id(pid, tid)
        if not proj:
            raise HTTPException(status_code=404, detail=f"Project not found: {pid}")

    cur_ts: Optional[datetime] = None
    cur_id: Optional[str] = None
    if cursor:
        try:
            cur_ts, cur_id = _decode_cursor(cursor)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid cursor: {e}") from e

    total = db.count_workflow_audit_filtered(
        tid,
        project_id=pid,
        actions=actions,
        actor_id=aid,
        outcome=out_f,
        version_id=vid,
        since=since_dt,
        until=until_dt,
    )

    if cur_ts is not None:
        rows = db.search_workflow_audit(
            tid,
            project_id=pid,
            actions=actions,
            actor_id=aid,
            outcome=out_f,
            version_id=vid,
            since=since_dt,
            until=until_dt,
            limit=limit + 1,
            offset=0,
            cursor_created_at=cur_ts,
            cursor_id=cur_id,
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cur = None
        if has_more and rows:
            last = rows[-1]
            next_cur = _encode_cursor(last.get("created_at"), str(last["id"]))
        pag = WorkflowAuditPaginationOut(
            limit=limit,
            total=total,
            has_more=has_more,
            offset=None,
            next_offset=None,
            next_cursor=next_cur,
        )
    else:
        rows = db.search_workflow_audit(
            tid,
            project_id=pid,
            actions=actions,
            actor_id=aid,
            outcome=out_f,
            version_id=vid,
            since=since_dt,
            until=until_dt,
            limit=limit,
            offset=offset,
            cursor_created_at=None,
            cursor_id=None,
        )
        has_more = offset + len(rows) < total
        next_off = (offset + len(rows)) if has_more else None
        next_cur_off = None
        if has_more and rows:
            last = rows[-1]
            next_cur_off = _encode_cursor(last.get("created_at"), str(last["id"]))
        pag = WorkflowAuditPaginationOut(
            limit=limit,
            total=total,
            has_more=has_more,
            offset=offset,
            next_offset=next_off,
            next_cursor=next_cur_off,
        )

    items = [_row_to_entry(r) for r in rows]

    return WorkflowAuditPageResponse(items=items, pagination=pag)

