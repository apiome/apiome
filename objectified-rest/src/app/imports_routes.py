"""
Spec import jobs — REST surface for queued orchestrator workers (#3306).

POST inserts a ``queued`` row; T6 worker advances state. Auth and tenant guard match
``validate_authentication`` + path ``tenant_slug`` (JWT or API key).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import psycopg2.errors

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import JSONResponse

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .models import (
    ImportJobCreateRequest,
    ImportJobError,
    ImportJobProgress,
    ImportJobResponse,
    ImportJobResult,
    ImportJobState,
)

router = APIRouter(prefix="/v1/imports", tags=["imports"])

_EVENTS_CAP = 100

_TERMINAL_STATES = frozenset({"completed", "failed", "canceled", "rolled-back"})


def _ts_iso(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[no-any-return]
    return str(value)


def _weak_etag_import_job(updated_at: Any, job_id: str) -> str:
    """Weak ETag from job identity and ``updated_at`` (RFC 9110)."""
    ts = _ts_iso(updated_at)
    return f'W/"import-{job_id}-{ts}"'


def _if_none_match_matches_weak_etag(etag_full: str, if_none_match: Optional[str]) -> bool:
    if not if_none_match or not str(if_none_match).strip():
        return False
    header = str(if_none_match).strip()
    if header == "*":
        return True

    def _strip_weak_quoted(token: str) -> str:
        t = token.strip()
        if t.startswith("W/"):
            t = t[2:].strip()
        if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
            t = t[1:-1]
        return t

    want = _strip_weak_quoted(etag_full)
    for raw in header.split(","):
        token = raw.strip()
        if not token:
            continue
        if token == "*":
            return True
        if _strip_weak_quoted(token) == want:
            return True
    return False


def _workflow_audit_import(
    tenant_id: str,
    project_id: Optional[str],
    action: str,
    outcome: str,
    actor_id: Optional[str],
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    db.insert_workflow_audit(
        tenant_id,
        project_id,
        None,
        action,
        outcome,
        actor_id,
        detail,
    )


def _coerce_progress(raw: Any) -> Optional[ImportJobProgress]:
    if raw is None or not isinstance(raw, dict):
        return None
    try:
        return ImportJobProgress.model_validate(raw)
    except Exception:
        return None


def _coerce_result(raw: Any) -> Optional[ImportJobResult]:
    if raw is None or not isinstance(raw, dict):
        return None
    try:
        return ImportJobResult.model_validate(raw)
    except Exception:
        return None


def _coerce_error(raw: Any) -> Optional[ImportJobError]:
    if raw is None or not isinstance(raw, dict):
        return None
    try:
        return ImportJobError.model_validate(raw)
    except Exception:
        return None


def _events_trim(events: Any) -> List[Dict[str, Any]]:
    if not isinstance(events, list):
        return []
    tail = events[-_EVENTS_CAP:]
    out: List[Dict[str, Any]] = []
    for e in tail:
        if isinstance(e, dict):
            out.append(e)
    return out


def _row_to_response(row: Dict[str, Any]) -> ImportJobResponse:
    pid = row.get("project_id")
    raw_state = str(row["state"])
    try:
        state = ImportJobState(raw_state)
    except ValueError:
        state = ImportJobState.failed
    return ImportJobResponse(
        job_id=str(row["job_id"]),
        tenant_id=str(row["tenant_id"]),
        project_id=str(pid) if pid else None,
        state=state,
        percent=int(row.get("percent") or 0),
        progress=_coerce_progress(row.get("progress")),
        events=_events_trim(row.get("events")),
        summary=row.get("summary") if isinstance(row.get("summary"), dict) else None,
        result=_coerce_result(row.get("result")),
        error=_coerce_error(row.get("error")),
        created_at=_ts_iso(row.get("created_at")),
        updated_at=_ts_iso(row.get("updated_at")),
        finished_at=(None if row.get("finished_at") is None else _ts_iso(row.get("finished_at"))),
    )


def _state_conflict(message: str, *, hint: str, code: str = "IMPORT_JOB_INVALID_STATE") -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": code, "message": message, "hint": hint},
    )


def _normalize_idempotency_key(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if len(s) > 256:
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key must be at most 256 characters",
        )
    return s


@router.post(
    "/{tenant_slug}",
    response_model=ImportJobResponse,
    response_model_by_alias=True,
    status_code=201,
    responses={
        200: {
            "description": "Existing job for Idempotency-Key (replay within 24h)",
            "model": ImportJobResponse,
        },
        201: {"description": "Job created (queued)"},
        400: {"description": "Invalid body or headers"},
        403: {"description": "Tenant access denied"},
    },
)
async def create_import_job(
    tenant_slug: str,
    body: ImportJobCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
    idempotency_key_header: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    Queue a new import job (``queued``). Optional ``Idempotency-Key``: same tenant + key within 24h
    returns the existing job with **200** instead of creating a duplicate.
    """
    tenant_id = str(auth_data["tenant_id"])
    actor_id = get_authenticated_user_id(auth_data)

    idem = _normalize_idempotency_key(idempotency_key_header)
    if idem:
        existing = db.find_import_job_by_idempotency_key(tenant_id, idem)
        if existing:
            r = _row_to_response(existing)
            etag = _weak_etag_import_job(existing.get("updated_at"), str(existing["job_id"]))
            return JSONResponse(
                status_code=200,
                content=r.model_dump(by_alias=True, mode="json"),
                headers={"ETag": etag},
            )

    if body.existing_project_id:
        proj = db.get_project_by_id(str(body.existing_project_id), tenant_id)
        if not proj:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "UNKNOWN_PROJECT_ID",
                    "message": f"No project {body.existing_project_id!r} for this tenant.",
                },
            )

    created_by = db.resolve_import_job_created_by_user_id(
        tenant_id,
        auth_data.get("auth_method"),
        auth_data.get("user_id"),
    )
    if not created_by:
        raise HTTPException(
            status_code=403,
            detail="Cannot resolve a catalog user for this request (tenant membership required).",
        )

    input_payload = body.model_dump(by_alias=True, mode="json")
    repo_row = body.repository_source.model_dump(by_alias=True, mode="json") if body.repository_source else None
    blob_sha = body.repository_source.blob_sha if body.repository_source else None

    events: List[Dict[str, Any]] = [
        {"type": "queued", "at": datetime.now(timezone.utc).isoformat()},
    ]

    try:
        row = db.insert_import_job(
            tenant_id=tenant_id,
            project_id=str(body.existing_project_id) if body.existing_project_id else None,
            state="queued",
            source_kind=str(body.source_kind.value),
            input_payload=input_payload,
            events=events,
            created_by=created_by,
            blob_sha=blob_sha,
            repository_source=repo_row,
            idempotency_key=idem,
            percent=0,
        )
    except psycopg2.errors.UniqueViolation:
        # Concurrent POST with the same Idempotency-Key raced us — re-query and replay.
        if idem:
            existing = db.find_import_job_by_idempotency_key(tenant_id, idem)
            if existing:
                r = _row_to_response(existing)
                etag = _weak_etag_import_job(existing.get("updated_at"), str(existing["job_id"]))
                return JSONResponse(
                    status_code=200,
                    content=r.model_dump(by_alias=True, mode="json"),
                    headers={"ETag": etag},
                )
        raise

    _workflow_audit_import(
        tenant_id,
        row.get("project_id"),
        "import.job.create",
        "success",
        actor_id,
        detail={"jobId": str(row["job_id"]), "state": "queued"},
    )

    r = _row_to_response(row)
    etag = _weak_etag_import_job(row.get("updated_at"), str(row["job_id"]))
    return JSONResponse(
        status_code=201,
        content=r.model_dump(by_alias=True, mode="json"),
        headers={"ETag": etag},
    )


@router.get(
    "/{tenant_slug}/{job_id}",
    response_model=ImportJobResponse,
    response_model_by_alias=True,
    responses={
        304: {"description": "Not modified (If-None-Match)"},
        404: {"description": "Job not found for tenant"},
    },
)
async def get_import_job(
    tenant_slug: str,
    job_id: UUID,
    response: Response,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
):
    """Return job status (events trimmed to the last 100). Supports weak ETag and 304 Not Modified."""
    tenant_id = str(auth_data["tenant_id"])
    row = db.get_import_job_row(tenant_id, str(job_id))
    if not row:
        raise HTTPException(status_code=404, detail=f"Import job not found: {job_id}")

    etag = _weak_etag_import_job(row.get("updated_at"), str(row["job_id"]))
    response.headers["ETag"] = etag
    if _if_none_match_matches_weak_etag(etag, if_none_match):
        return Response(status_code=304, headers={"ETag": etag})

    return _row_to_response(row)


@router.post(
    "/{tenant_slug}/{job_id}/commit",
    response_model=ImportJobResponse,
    response_model_by_alias=True,
    responses={
        409: {"description": "Invalid state for commit (need pending-approval)"},
    },
)
async def commit_import_job(
    tenant_slug: str,
    job_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
):
    """Promote ``pending-approval`` → ``committing`` (orchestrator completes in T6)."""
    tenant_id = str(auth_data["tenant_id"])
    actor_id = get_authenticated_user_id(auth_data)
    row = db.get_import_job_row(tenant_id, str(job_id))
    if not row:
        raise HTTPException(status_code=404, detail=f"Import job not found: {job_id}")

    state = str(row["state"])
    if state != "pending-approval":
        raise _state_conflict(
            f"Cannot commit job in state {state!r}; expected pending-approval.",
            hint="Wait for preview to finish and require approval, or use cancel if abandoning.",
        )

    updated = db.update_import_job_state(tenant_id, str(job_id), "committing", finished_at_now=False, expected_state=state)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Import job not found: {job_id}")

    _workflow_audit_import(
        tenant_id,
        updated.get("project_id"),
        "import.job.commit",
        "success",
        actor_id,
        detail={"jobId": str(job_id), "fromState": state, "toState": "committing"},
    )
    return _row_to_response(updated)


@router.post(
    "/{tenant_slug}/{job_id}/cancel",
    response_model=ImportJobResponse,
    response_model_by_alias=True,
)
async def cancel_import_job(
    tenant_slug: str,
    job_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
):
    """Cancel a job that is not yet terminal."""
    tenant_id = str(auth_data["tenant_id"])
    actor_id = get_authenticated_user_id(auth_data)
    row = db.get_import_job_row(tenant_id, str(job_id))
    if not row:
        raise HTTPException(status_code=404, detail=f"Import job not found: {job_id}")

    state = str(row["state"])
    if state in _TERMINAL_STATES:
        raise _state_conflict(
            f"Cannot cancel job in terminal state {state!r}.",
            hint="Terminal jobs cannot be canceled.",
        )

    updated = db.update_import_job_state(tenant_id, str(job_id), "canceled", finished_at_now=True, expected_state=state)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Import job not found: {job_id}")

    _workflow_audit_import(
        tenant_id,
        updated.get("project_id"),
        "import.job.cancel",
        "success",
        actor_id,
        detail={"jobId": str(job_id), "fromState": state, "toState": "canceled"},
    )
    return _row_to_response(updated)


@router.post(
    "/{tenant_slug}/{job_id}/rollback",
    response_model=ImportJobResponse,
    response_model_by_alias=True,
)
async def rollback_import_job(
    tenant_slug: str,
    job_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
):
    """Roll back a **completed** job to ``rolled-back``."""
    tenant_id = str(auth_data["tenant_id"])
    actor_id = get_authenticated_user_id(auth_data)
    row = db.get_import_job_row(tenant_id, str(job_id))
    if not row:
        raise HTTPException(status_code=404, detail=f"Import job not found: {job_id}")

    state = str(row["state"])
    if state != "completed":
        raise _state_conflict(
            f"Cannot roll back job in state {state!r}; expected completed.",
            hint="Only successfully completed imports can be rolled back.",
        )

    updated = db.update_import_job_state(tenant_id, str(job_id), "rolled-back", finished_at_now=True, expected_state=state)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Import job not found: {job_id}")

    _workflow_audit_import(
        tenant_id,
        updated.get("project_id"),
        "import.job.rollback",
        "success",
        actor_id,
        detail={"jobId": str(job_id), "fromState": state, "toState": "rolled-back"},
    )
    return _row_to_response(updated)
