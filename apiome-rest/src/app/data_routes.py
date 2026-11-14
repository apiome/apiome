"""
Data records API routes.

Provides create/update/delete for apiome.data_record and apiome.data_snapshot.
Embedding and insertion into data_snapshot are handled here (distributed compute in REST).
All endpoints are tenant-scoped and require authentication via JWT or API key.
"""

import base64
import binascii
import hashlib
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from .database import db
from .auth import validate_authentication, get_authenticated_user_id
from .permissions import enforce_permission, Resource, Action
from .embedding import embed_record_data, EMBEDDING_MODEL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/data", tags=["data"])


@router.get("/{tenant_slug}")
async def data_api_info(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Verify data API is mounted and tenant is authenticated. Returns 200 with tenant_slug."""
    return {"data_api": True, "tenant_slug": tenant_slug}


@router.get("/{tenant_slug}/classes")
async def list_data_classes(
    tenant_slug: str,
    project: str = Query(..., min_length=1, description="Project slug"),
    version: str = Query(..., min_length=1, description="Version label, e.g. 1.0.0 (a leading v is accepted)"),
    class_name: Optional[str] = Query(
        None, alias="class", min_length=1, description="Only the class with exactly this name"
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """
    Resolve a version's classes to the frozen class schemas data records attach to (#3255).

    Records are created against a ``class_schema_id`` — the JSON Schema 2020-12 captured for
    a class when its version was published. This answers each class's ``class_schema_id`` and
    ``schema``, so a client can address a class as ``<project>/<version>/<Class>`` and
    validate a payload locally before ``POST …/records``.

    A version that was never published has no class schemas: the answer is ``200`` with an
    empty ``classes`` list (and ``published: false``), never an error. An unknown project or
    version is ``404``. Requires ``versions:view``.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]

    found = db.find_data_version(tenant_id, project, version)
    if not found:
        raise HTTPException(status_code=404, detail=f"Version {project}/{version} not found")

    rows = db.list_version_class_schemas(str(found["version_record_id"]), class_name)
    return {
        "success": True,
        "project": found["project_slug"],
        "version": found["version"],
        "published": bool(found.get("published")),
        "classes": [
            {
                "class_schema_id": str(row["class_schema_id"]),
                "class_id": str(row["class_id"]),
                "class_name": row["class_name"],
                "schema": row["schema"] if isinstance(row["schema"], dict) else {},
            }
            for row in rows
        ],
    }


class DataRecordCreateBody(BaseModel):
    class_schema_id: str = Field(..., description="Class schema ID (frozen version class)")
    data: Dict[str, Any] = Field(..., description="Record payload validated against schema")


class DataRecordUpdateBody(BaseModel):
    class_schema_id: str = Field(..., description="Class schema ID")
    data: Dict[str, Any] = Field(..., description="Updated record payload")


def _schedule_embedding_update(record_id: str, data: Dict[str, Any]) -> None:
    """Best-effort: compute embedding and update data_snapshot. Non-blocking."""
    try:
        vector = embed_record_data(data)
        if vector:
            db.update_data_snapshot_embedding(record_id, vector, EMBEDDING_MODEL)
    except Exception as e:
        logger.warning("[data/records] Vectorization failed for record_id=%s: %s", record_id, e)


#: Largest page ``GET …/records`` returns.
MAX_RECORDS_PAGE = 500

#: Most ``filter`` parameters one list request may carry.
MAX_RECORD_FILTERS = 20


def _parse_record_filters(raw: List[str]) -> List[Tuple[str, str]]:
    """Split each ``key=value`` filter; 400 when one has no ``=`` or an empty key, or too many are given."""
    if len(raw) > MAX_RECORD_FILTERS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_RECORD_FILTERS} filters are allowed")
    parsed = []
    for text in raw:
        key, sep, value = text.partition("=")
        if not sep or not key.strip():
            raise HTTPException(status_code=400, detail=f"Filter {text!r} must be key=value")
        parsed.append((key.strip(), value))
    return parsed


def _parse_record_sort(raw: str) -> Tuple[str, bool]:
    """``created_at`` / ``-created_at`` / ``+amount`` → ``(field, descending)``; 400 when the field is empty."""
    text = raw.strip()
    descending = text.startswith("-")
    field = text.lstrip("+-").strip()
    if not field:
        raise HTTPException(status_code=400, detail=f"Sort {raw!r} must name a field, e.g. created_at or -amount")
    return field, descending


def _records_query_signature(
    class_schema_id: str, filters: List[Tuple[str, str]], sort: str, include_deleted: bool
) -> str:
    """A short hash of what a records cursor was issued for, so it is not reused for another query."""
    material = json.dumps([class_schema_id, filters, sort, include_deleted], separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _encode_records_cursor(offset: int, signature: str) -> str:
    """The opaque ``next_cursor``: base64url of ``{"o": offset, "q": signature}``."""
    raw = json.dumps({"o": offset, "q": signature}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_records_cursor(cursor: str, signature: str) -> int:
    """The offset a cursor carries; 400 when it is malformed or was issued for a different query."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        offset = int(payload["o"])
        issued_for = str(payload["q"])
    except (binascii.Error, ValueError, KeyError, TypeError, UnicodeError):
        raise HTTPException(status_code=400, detail="Invalid cursor")
    if offset < 0 or issued_for != signature:
        raise HTTPException(
            status_code=400,
            detail="Cursor does not belong to this query (class, filters, sort or include_deleted changed)",
        )
    return offset


def _iso(value: Any) -> Optional[str]:
    """A timestamp as ISO 8601 (``None`` stays ``None``)."""
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)


@router.get("/{tenant_slug}/records")
async def list_data_records(
    tenant_slug: str,
    class_schema_id: str = Query(..., min_length=1, description="Class schema ID (from GET …/classes)"),
    limit: int = Query(50, ge=1, le=MAX_RECORDS_PAGE, description="Records per page"),
    cursor: Optional[str] = Query(None, description="The next_cursor of the previous page"),
    filter: List[str] = Query(
        default=[], description="key=value on a top-level data field; repeat to require several"
    ),
    sort: str = Query(
        "created_at",
        description="created_at, updated_at, deleted_at, record_id or a data field; prefix - for descending",
    ),
    include_deleted: bool = Query(False, description="Include soft-deleted records (they carry deleted_at)"),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """
    List a class schema's records, a page at a time (#3253).

    ``filter`` compares a top-level data field as text (``status=succeeded``,
    ``amount=19.99``); several filters must all match. ``sort`` takes a system field or a
    data field (compared as JSON; records without it sort last). A soft-deleted record is
    left out unless ``include_deleted`` — then it carries the data it had and ``deleted_at``.

    Pages are cursor-driven: pass the answer's ``next_cursor`` to get the next page
    (``null`` on the last page). A cursor only fits the query it came from; changing the
    class, filters, sort or ``include_deleted`` is a 400. Records added while paging can
    shift later pages. Unknown class schema → 404. Requires ``versions:view``.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]

    filters = _parse_record_filters(filter)
    sort_field, descending = _parse_record_sort(sort)
    signature = _records_query_signature(class_schema_id, filters, sort.strip(), include_deleted)
    offset = _decode_records_cursor(cursor, signature) if cursor else 0

    try:
        uuid.UUID(class_schema_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Class schema not found")
    if not db.assert_class_schema_tenant_access(class_schema_id, tenant_id):
        raise HTTPException(status_code=404, detail="Class schema not found")

    rows, total = db.list_data_records(
        class_schema_id,
        tenant_id,
        filters=filters,
        sort_field=sort_field,
        descending=descending,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
    next_offset = offset + len(rows)
    return {
        "success": True,
        "class_schema_id": class_schema_id,
        "total": total,
        "limit": limit,
        "sort": sort.strip(),
        "next_cursor": _encode_records_cursor(next_offset, signature) if rows and next_offset < total else None,
        "items": [
            {
                "record_id": str(row["record_id"]),
                "created_at": _iso(row.get("created_at")),
                "updated_at": _iso(row.get("updated_at")),
                "deleted_at": _iso(row.get("deleted_at")),
                "data": row["data"] if isinstance(row.get("data"), dict) else {},
            }
            for row in rows
        ],
    }


@router.get("/{tenant_slug}/records/{record_id}")
async def get_data_record(
    tenant_slug: str,
    record_id: str,
    class_schema_id: str = Query(..., description="Class schema ID"),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """
    Get the current snapshot data for a record (for edit form).
    Returns 404 if record not found or deleted.
    """
    tenant_id = auth_data["tenant_id"]

    if not db.assert_class_schema_tenant_access(class_schema_id, tenant_id):
        raise HTTPException(status_code=404, detail="Class schema not found")

    snapshot = db.get_data_snapshot(record_id, class_schema_id, tenant_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Record not found")

    return {"success": True, "record_id": record_id, "data": snapshot.get("data", {})}


@router.post("/{tenant_slug}/records")
async def create_data_record(
    tenant_slug: str,
    body: DataRecordCreateBody,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """
    Create a new data record and data_snapshot row.
    Embedding is computed asynchronously and stored in data_snapshot.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.CREATE)
    tenant_id = auth_data["tenant_id"]
    user_id = get_authenticated_user_id(auth_data)

    row = db.get_class_schema_by_id(body.class_schema_id, tenant_id)
    if not row:
        # Help debug: check if class_schema exists and which tenant owns it
        info = db.get_class_schema_tenant_info(body.class_schema_id)
        if not info:
            logger.warning(
                "[data/records] POST 404: class_schema_id=%s not found in database (version not published?)",
                body.class_schema_id,
            )
            raise HTTPException(
                status_code=404,
                detail=(
                    "Class schema not found. Ensure the version is published (so class_schema rows exist) "
                    "and that the REST API uses the same database as the UI."
                ),
            )
        # Exists but different tenant
        logger.warning(
            "[data/records] POST 404: class_schema_id=%s belongs to tenant=%s, requested tenant=%s",
            body.class_schema_id,
            info.get("project_tenant_id"),
            tenant_id,
        )
        raise HTTPException(
            status_code=404,
            detail=(
                "Class schema belongs to a different tenant. "
                "Ensure the REST API and UI use the same database and tenant."
            ),
        )

    try:
        record_id = db.insert_data_record(
            class_schema_id=body.class_schema_id,
            tenant_id=tenant_id,
            data=body.data,
            created_by=user_id,
        )
    except ValueError as e:
        if "Access denied" in str(e):
            raise HTTPException(status_code=403, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    # Best-effort embedding (non-blocking)
    _schedule_embedding_update(record_id, body.data)

    return {"success": True, "record_id": record_id}


@router.patch("/{tenant_slug}/records/{record_id}")
async def update_data_record(
    tenant_slug: str,
    record_id: str,
    body: DataRecordUpdateBody,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """
    Update an existing data record and data_snapshot.
    Embedding is recomputed asynchronously and stored in data_snapshot.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    tenant_id = auth_data["tenant_id"]
    user_id = get_authenticated_user_id(auth_data)

    row = db.get_class_schema_by_id(body.class_schema_id, tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="Class schema not found")

    try:
        updated = db.update_data_record(
            record_id=record_id,
            class_schema_id=body.class_schema_id,
            tenant_id=tenant_id,
            data=body.data,
            updated_by=user_id,
        )
    except ValueError as e:
        if "Access denied" in str(e):
            raise HTTPException(status_code=403, detail=str(e))
        if "Record not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    if not updated:
        return {"success": True, "record_id": record_id, "updated": False}

    _schedule_embedding_update(record_id, body.data)

    return {"success": True, "record_id": record_id, "updated": True}


@router.delete("/{tenant_slug}/records/{record_id}")
async def delete_data_record(
    tenant_slug: str,
    record_id: str,
    class_schema_id: str = Query(..., description="Class schema ID"),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Delete a data record (append deleted event, remove data_snapshot row)."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.DELETE)
    tenant_id = auth_data["tenant_id"]
    user_id = get_authenticated_user_id(auth_data)

    if not db.assert_class_schema_tenant_access(class_schema_id, tenant_id):
        raise HTTPException(status_code=404, detail="Class schema not found")

    try:
        db.delete_data_record(
            record_id=record_id,
            class_schema_id=class_schema_id,
            tenant_id=tenant_id,
            deleted_by=user_id,
        )
    except ValueError as e:
        if "Access denied" in str(e):
            raise HTTPException(status_code=403, detail=str(e))
        if "Record not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    return {"success": True, "record_id": record_id}


@router.post("/{tenant_slug}/records/{record_id}/restore")
async def restore_data_record(
    tenant_slug: str,
    record_id: str,
    class_schema_id: str = Query(..., description="Class schema ID"),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Restore a deleted data record (recreate data_snapshot from deleted event, append restored event)."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    tenant_id = auth_data["tenant_id"]
    user_id = get_authenticated_user_id(auth_data)

    if not db.assert_class_schema_tenant_access(class_schema_id, tenant_id):
        raise HTTPException(status_code=404, detail="Class schema not found")

    try:
        db.restore_data_record(
            record_id=record_id,
            class_schema_id=class_schema_id,
            tenant_id=tenant_id,
            restored_by=user_id,
        )
    except ValueError as e:
        if "Access denied" in str(e):
            raise HTTPException(status_code=403, detail=str(e))
        if "Record not found" in str(e) or "not deleted" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    return {"success": True, "record_id": record_id}
