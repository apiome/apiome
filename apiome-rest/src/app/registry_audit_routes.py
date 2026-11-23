"""
Registry audit log — paginated list API (#3481, 7.4).

GET /v1/primitives/{tenant_slug}/audit

Reads the append-only ``apiome.registry_audit`` ledger written by the mutating primitives routes
(create / update / delete / import), tenant-scoped and newest first. Part of the advanced Type
Registry surface, so the same ``primitives-registry`` entitlement that gates the import pipeline
and resolver gates this read.

This router is registered **before** the primitives router so its literal ``/audit`` segment is
matched ahead of the primitives ``/{tenant_slug}/{primitive_id}`` catch-all.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from .database import db
from .feature_gating import require_primitives_registry
from .keyset_pagination import (
    MAX_PAGE_LIMIT,
    InvalidCursor,
    cursor_query,
    decode_time_id_cursor,
    encode_time_id_cursor,
    include_total_query,
    limit_query,
    offset_query,
    page_of,
    time_id_key,
)
from .models import (
    RegistryAuditEntryOut,
    RegistryAuditPageResponse,
    RegistryAuditPaginationOut,
)

router = APIRouter(prefix="/v1/primitives", tags=["registry-audit"])

_MAX_LIMIT = MAX_PAGE_LIMIT
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


#: Sibling ledgers import the codec under its old private names; both are the shared
#: ``{"t", "i"}`` token (#7196). ``InvalidCursor`` is a ``ValueError``, as before.
_encode_cursor = encode_time_id_cursor


def _decode_cursor(token: str) -> Tuple[datetime, str]:
    """Read a ``(created_at, id)`` cursor of this ledger.

    The token is the shared ``{"t", "i"}`` form (#7196); this ledger's ids are UUIDs, so anything
    else is refused before it reaches SQL.

    Args:
        token: The ``cursor`` query parameter.

    Returns:
        ``(created_at, id)`` of the last row the caller saw.

    Raises:
        InvalidCursor: The token is malformed or its id is not a UUID.
    """
    stamp, row_id = decode_time_id_cursor(token)
    try:
        uuid.UUID(row_id)
    except ValueError as exc:
        raise InvalidCursor("bad id") from exc
    return stamp, row_id


def _row_to_entry(row: Dict[str, Any]) -> RegistryAuditEntryOut:
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
    return RegistryAuditEntryOut(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        primitive_id=str(row["primitive_id"]) if row.get("primitive_id") is not None else None,
        schema_id=str(row["schema_id"]) if row.get("schema_id") is not None else None,
        namespace=str(row["namespace"]) if row.get("namespace") is not None else None,
        action=str(row["action"]),
        outcome=str(row["outcome"]),
        actor_id=str(row["actor_id"]) if row.get("actor_id") is not None else None,
        detail=detail,
        created_at=ca_s,
    )


@router.get(
    "/{tenant_slug}/audit",
    response_model=RegistryAuditPageResponse,
    response_model_by_alias=True,
    description=(
        "List type-registry audit events for the tenant, newest first.\n\n"
        "Pages by `cursor`: pass `pagination.nextCursor` until `pagination.hasMore` is false. "
        "`offset` is deprecated and cannot be combined with `cursor`. `pagination.total` is "
        "counted (up to 10,000) only when `include_total` is set."
    ),
)
def list_registry_audit(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(require_primitives_registry),
    action: Optional[List[str]] = Query(
        None,
        description="Filter by action (repeat for multiple, e.g. primitive.create).",
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
    primitive_id: Optional[str] = Query(
        None,
        alias="primitiveId",
        description="Filter by affected primitive id (UUID).",
    ),
    schema_id: Optional[str] = Query(
        None,
        alias="schemaId",
        description="Filter by the affected type's derived $id.",
    ),
    since: Optional[str] = Query(
        None,
        description="Inclusive lower bound on createdAt (ISO 8601).",
    ),
    until: Optional[str] = Query(
        None,
        description="Inclusive upper bound on createdAt (ISO 8601).",
    ),
    limit: int = limit_query(_DEFAULT_LIMIT, maximum=_MAX_LIMIT),
    offset: int = offset_query(),
    cursor: Optional[str] = cursor_query(),
    include_total: bool = include_total_query(),
) -> RegistryAuditPageResponse:
    """List type-registry audit events for the tenant, newest first.

    ``hasMore`` comes from reading one row past the page, so nothing is counted unless
    ``include_total`` is set (#7196).

    Args:
        tenant_slug: The tenant in the path.
        auth_data: The authenticated principal.
        action: Only these actions.
        actor_id: Only this actor.
        outcome: Only ``success`` or ``failure``.
        primitive_id: Only this primitive.
        schema_id: Only this derived ``$id``.
        since: Inclusive lower bound on ``created_at``.
        until: Inclusive upper bound on ``created_at``.
        limit: Page size.
        offset: Rows to skip (deprecated).
        cursor: Where the page starts (``nextCursor`` of the previous page).
        include_total: Also count the matches, up to the cap.

    Returns:
        The page and its pagination facts.

    Raises:
        HTTPException: 400 for a malformed filter or cursor, or a cursor combined with a non-zero
            offset.
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
    pid = _optional_uuid_param("primitiveId", primitive_id)
    sid = schema_id.strip() if schema_id and schema_id.strip() else None
    since_dt = _parse_iso_datetime("since", since)
    until_dt = _parse_iso_datetime("until", until)

    cur: Optional[Tuple[datetime, str]] = None
    if cursor:
        try:
            cur = _decode_cursor(cursor)
        except InvalidCursor as e:
            raise HTTPException(status_code=400, detail=f"Invalid cursor: {e}") from e

    filters: Dict[str, Any] = dict(
        primitive_id=pid,
        actions=actions,
        actor_id=aid,
        outcome=out_f,
        schema_id=sid,
        since=since_dt,
        until=until_dt,
    )
    total = db.count_registry_audit_filtered(tid, **filters) if include_total else None
    rows = db.search_registry_audit(
        tid,
        **filters,
        limit=limit + 1,
        offset=0 if cur else offset,
        cursor_created_at=cur[0] if cur else None,
        cursor_id=cur[1] if cur else None,
    )
    page = page_of(rows, limit, time_id_key())
    rows = page.items
    pag = RegistryAuditPaginationOut(
        limit=limit,
        total=total,
        has_more=page.has_more,
        offset=None if cur else offset,
        next_offset=(offset + len(rows)) if page.has_more and not cur else None,
        next_cursor=page.next_cursor,
    )

    items = [_row_to_entry(r) for r in rows]

    return RegistryAuditPageResponse(items=items, pagination=pag)
