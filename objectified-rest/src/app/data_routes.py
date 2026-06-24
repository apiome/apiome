"""
Data records API routes.

Provides create/update/delete for odb.data_record and odb.data_snapshot.
Embedding and insertion into data_snapshot are handled here (distributed compute in REST).
All endpoints are tenant-scoped and require authentication via JWT or API key.
"""

import logging
from typing import Dict, Any

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
