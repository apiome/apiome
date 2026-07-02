"""
Version tags API — named pointers to schema revisions (git tag analog).
"""

import re
from typing import Any, Dict, List

import psycopg2
from fastapi import APIRouter, Depends, HTTPException

from .auth import validate_authentication, get_authenticated_user_id
from .database import db
from .permissions import enforce_permission, Resource, Action
from .models import VersionTagSchema, VersionTagCreateRequest, VersionTagUpdateRequest

router = APIRouter(prefix="/v1/version-tags", tags=["version-tags"])

_TAG_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._\-/]{0,254}$")


def _valid_tag_name(name: str) -> bool:
    return bool(name and _TAG_NAME_RE.match(name.strip()))


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    tid = auth_data.get("tenant_id")
    if not tid:
        raise HTTPException(status_code=500, detail="Missing tenant context")
    return str(tid)


@router.get("/{tenant_slug}/{project_id}", response_model=List[VersionTagSchema])
async def list_version_tags(
    tenant_slug: str,
    project_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> List[VersionTagSchema]:
    """List all tags for a project."""
    tenant_id = _tenant_id(auth_data)
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = db.list_version_tags_for_project(project_id, tenant_id)
    return [VersionTagSchema(**dict(r)) for r in rows]


@router.post("/{tenant_slug}/{project_id}", response_model=VersionTagSchema)
async def create_version_tag(
    tenant_slug: str,
    project_id: str,
    body: VersionTagCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionTagSchema:
    """Create a tag pointing at an existing schema revision."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.CREATE)
    tenant_id = _tenant_id(auth_data)
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not _valid_tag_name(body.name):
        raise HTTPException(
            status_code=400,
            detail="Invalid tag name: use 1–255 chars, start with letter or digit, [a-zA-Z0-9._\\-/]",
        )
    uid = get_authenticated_user_id(auth_data)
    ch = (body.channel or "").strip()[:64] if body.channel else None
    msg = body.message.strip() if body.message else None
    if msg == "":
        msg = None
    want_protected = bool(body.protected)
    if want_protected:
        if not uid:
            raise HTTPException(
                status_code=403,
                detail="Protected tags can only be created from an authenticated user session",
            )
        if not db.is_user_tenant_admin(tenant_id, uid):
            raise HTTPException(
                status_code=403,
                detail="Only tenant administrators can create protected tags",
            )
    try:
        row = db.create_version_tag(
            project_id,
            tenant_id,
            body.version_id.strip(),
            body.name,
            msg,
            ch,
            bool(body.immutable),
            want_protected,
            uid,
        )
        return VersionTagSchema(**dict(row))
    except psycopg2.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail={"code": "TAG_NAME_CONFLICT", "message": "A tag with this name already exists for this project"},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{tenant_slug}/{project_id}/{tag_id}", response_model=VersionTagSchema)
async def patch_version_tag(
    tenant_slug: str,
    project_id: str,
    tag_id: str,
    body: VersionTagUpdateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionTagSchema:
    """Move a tag to another revision and/or set immutable lock / protection policy."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    tenant_id = _tenant_id(auth_data)
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    uid = get_authenticated_user_id(auth_data)
    if not uid:
        raise HTTPException(
            status_code=403,
            detail="Tag modification requires an authenticated user session (API keys are not supported for this operation)",
        )

    new_vid = body.version_id.strip() if body.version_id else None
    set_immutable = body.immutable is True
    set_protected: Any = None
    if "protected" in body.model_fields_set:
        set_protected = body.protected

    is_admin = bool(uid and db.is_user_tenant_admin(tenant_id, uid))
    try:
        row = db.update_version_tag(
            tag_id,
            project_id,
            tenant_id,
            uid,
            is_admin,
            new_vid,
            set_immutable,
            set_protected,
        )
    except PermissionError as e:
        code = str(e)
        if code == "TAG_IMMUTABLE":
            raise HTTPException(
                status_code=409,
                detail={"code": "TAG_IMMUTABLE", "message": "This tag is immutable and cannot be changed"},
            )
        if code == "TAG_PROTECTED":
            raise HTTPException(
                status_code=403,
                detail={"code": "TAG_PROTECTED", "message": "This tag is protected; only tenant admins may change it"},
            )
        if code == "TAG_PROTECT_POLICY_ADMIN_ONLY":
            raise HTTPException(
                status_code=403,
                detail={"code": "TAG_PROTECT_POLICY_ADMIN_ONLY", "message": "Only tenant admins can change protection policy"},
            )
        if code == "TAG_FORBIDDEN":
            raise HTTPException(status_code=403, detail="Not allowed to modify this tag")
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not row:
        raise HTTPException(status_code=404, detail="Tag not found")
    return VersionTagSchema(**dict(row))


@router.delete("/{tenant_slug}/{project_id}/{tag_id}")
async def delete_version_tag(
    tenant_slug: str,
    project_id: str,
    tag_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, str]:
    """Delete a tag (not allowed when immutable; protected tags require admin)."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.DELETE)
    tenant_id = _tenant_id(auth_data)
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    uid = get_authenticated_user_id(auth_data)
    if not uid:
        raise HTTPException(
            status_code=403,
            detail="Tag deletion requires an authenticated user session (API keys are not supported for this operation)",
        )

    is_admin = bool(uid and db.is_user_tenant_admin(tenant_id, uid))
    try:
        ok = db.delete_version_tag(tag_id, project_id, tenant_id, uid, is_admin)
    except PermissionError as e:
        code = str(e)
        if code == "TAG_IMMUTABLE":
            raise HTTPException(
                status_code=409,
                detail={"code": "TAG_IMMUTABLE", "message": "This tag is immutable and cannot be deleted"},
            )
        if code == "TAG_PROTECTED":
            raise HTTPException(
                status_code=403,
                detail={"code": "TAG_PROTECTED", "message": "This tag is protected and cannot be deleted"},
            )
        if code == "TAG_FORBIDDEN":
            raise HTTPException(status_code=403, detail="Not allowed to delete this tag")
        raise
    if not ok:
        raise HTTPException(status_code=404, detail="Tag not found")
    return {"status": "deleted", "id": tag_id}
