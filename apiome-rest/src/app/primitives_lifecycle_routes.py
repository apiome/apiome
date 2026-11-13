"""
Type deprecation lifecycle API routes (#3482, 7.5).

``POST   /v1/primitives/{tenant_slug}/{primitive_id}/deprecate`` deprecates a type (or changes a
deprecated type's details); ``DELETE`` on the same path restores it. Both are tenant-scoped,
authenticated like the rest of the primitives CRUD, and need the same permission as an update.

Deprecation is an advisory marker: it never blocks a binding, a ``$ref`` or an export. System
(``std/*``) types are platform-governed and cannot be deprecated through this API. The rules for
a coherent record are in ``primitives_lifecycle.py``; every write is recorded in the registry
audit log (#3481).
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from .auth import validate_authentication
from .database import db
from .models import PrimitiveDeprecateRequest, PrimitiveSchema
from .permissions import Action, Resource, enforce_permission
from .primitives_lifecycle import (
    audit_detail,
    collect_errors,
    normalize_message,
    replacement_error,
    replacement_summary,
    sunset_date_error,
    today_utc,
)
from .registry_audit import ACTION_DEPRECATE, ACTION_RESTORE, record_registry_audit

router = APIRouter(prefix="/v1/primitives", tags=["primitives"])


def _load_writable_primitive(primitive_id: str, tenant_id: str) -> Dict[str, Any]:
    """Load a primitive the tenant may change the lifecycle of.

    Args:
        primitive_id: The primitive id.
        tenant_id: The caller's tenant id.

    Returns:
        The primitive row.

    Raises:
        HTTPException: 404 when the type is missing or not visible; 403 when it is a system type.
    """
    existing = db.get_primitive_by_id(primitive_id, tenant_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Primitive not found: {primitive_id}")
    if existing.get("is_system"):
        raise HTTPException(status_code=403, detail="Cannot deprecate system primitives")
    return existing


def with_replacement(row: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    """Attach the replacement type's ``{id, name, schema_id}`` to a primitive row.

    Args:
        row: A primitive row carrying ``replacement_id``.
        tenant_id: The caller's tenant id (the replacement must be visible to it).

    Returns:
        A copy of the row with ``replacement`` set (None when there is no visible replacement).
    """
    replacement_id = row.get("replacement_id")
    replacement: Optional[Dict[str, Any]] = (
        db.get_primitive_by_id(str(replacement_id), tenant_id) if replacement_id else None
    )
    return {**row, "replacement": replacement_summary(replacement)}


@router.post("/{tenant_slug}/{primitive_id}/deprecate", response_model=PrimitiveSchema)
async def deprecate_primitive(
    tenant_slug: str,
    primitive_id: str,
    request: PrimitiveDeprecateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PrimitiveSchema:
    """Deprecate a type, optionally with a sunset date, a message and a replacement type.

    Deprecation is advisory: existing and new bindings and ``$ref``s keep working. Calling this
    on an already-deprecated type replaces its sunset date, message and replacement (an omitted
    field is cleared) and keeps the original ``deprecated_at``.

    Args:
        tenant_slug: The tenant slug.
        primitive_id: The primitive id.
        request: The deprecation details (all optional).
        auth_data: Authentication data (injected by dependency).

    Returns:
        The deprecated primitive, with ``replacement`` resolved.

    Raises:
        HTTPException: 404 when the type is not found; 403 for a system type; 422 when the
            sunset date is in the past or the replacement is missing, the type itself, or
            itself deprecated.
    """
    enforce_permission(db, auth_data, Resource.TYPES, Action.EDIT)
    tenant_id = auth_data["tenant_id"]
    existing = _load_writable_primitive(primitive_id, tenant_id)

    replacement_id = (request.replacement_id or "").strip() or None
    replacement = (
        db.get_primitive_by_id(replacement_id, tenant_id)
        if replacement_id and replacement_id != primitive_id
        else None
    )
    errors = collect_errors(
        sunset_date_error(request.sunset_date, today_utc()),
        replacement_error(primitive_id, replacement_id, replacement),
    )
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))

    try:
        row = db.deprecate_primitive(
            primitive_id,
            tenant_id,
            sunset_date=request.sunset_date,
            message=normalize_message(request.message),
            replacement_id=replacement_id,
        )
    except Exception as e:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=str(e))
    if not row:
        raise HTTPException(status_code=404, detail=f"Primitive not found: {primitive_id}")

    record_registry_audit(
        db,
        auth_data,
        ACTION_DEPRECATE,
        primitive_id=str(row["id"]),
        schema_id=row.get("schema_id"),
        namespace=row.get("namespace"),
        detail=audit_detail(row, was_deprecated=existing.get("deprecated_at") is not None),
    )
    return PrimitiveSchema(**{**row, "replacement": replacement_summary(replacement)})


@router.delete("/{tenant_slug}/{primitive_id}/deprecate", response_model=PrimitiveSchema)
async def restore_primitive(
    tenant_slug: str,
    primitive_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PrimitiveSchema:
    """Restore a deprecated type: clear its deprecation, sunset date, message and replacement.

    Restoring a type that is not deprecated is a no-op that returns the type unchanged (and
    writes no audit row), so the call is safe to repeat.

    Args:
        tenant_slug: The tenant slug.
        primitive_id: The primitive id.
        auth_data: Authentication data (injected by dependency).

    Returns:
        The restored primitive.

    Raises:
        HTTPException: 404 when the type is not found; 403 for a system type.
    """
    enforce_permission(db, auth_data, Resource.TYPES, Action.EDIT)
    tenant_id = auth_data["tenant_id"]
    existing = _load_writable_primitive(primitive_id, tenant_id)

    if existing.get("deprecated_at") is None:
        return PrimitiveSchema(**existing)

    try:
        row = db.restore_primitive(primitive_id, tenant_id)
    except Exception as e:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=str(e))
    if not row:
        raise HTTPException(status_code=404, detail=f"Primitive not found: {primitive_id}")

    record_registry_audit(
        db,
        auth_data,
        ACTION_RESTORE,
        primitive_id=str(row["id"]),
        schema_id=row.get("schema_id"),
        namespace=row.get("namespace"),
        detail={"name": row.get("name")},
    )
    return PrimitiveSchema(**row)
