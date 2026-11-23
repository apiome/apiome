"""
Project class tags API — labels for organizing classes within a project.
"""

from typing import Any, Dict, List, Optional

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Response

from .auth import validate_authentication
from .authoring_list_orders import PROJECT_TAGS_ORDER
from .database import db
from .keyset_pagination import (
    MAX_REVISION_PAGE_LIMIT,
    cursor_query,
    limit_query,
    set_page_headers,
)
from .models import (
    ClassTagAssignRequest,
    ClassTagSchema,
    TagCreateRequest,
    TagSchema,
    TagUpdateRequest,
)
from .permissions import Action, Resource, enforce_permission

router = APIRouter(prefix="/v1/project-tags", tags=["project-tags"])


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    tid = auth_data.get("tenant_id")
    if not tid:
        raise HTTPException(status_code=500, detail="Missing tenant context")
    return str(tid)


def _assert_project_in_tenant(project_id: str, tenant_id: str) -> Dict[str, Any]:
    project = db.get_project_core(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _assert_tag_in_tenant(tag_id: str, tenant_id: str) -> Dict[str, Any]:
    tag = db.get_tag_by_id(tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    _assert_project_in_tenant(str(tag["project_id"]), tenant_id)
    return tag


def _assert_class_in_tenant(class_id: str, tenant_id: str) -> Dict[str, Any]:
    row = db.get_class_by_id(class_id, tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="Class not found")
    return row


@router.get("/{tenant_slug}/{project_id}", response_model=List[TagSchema])
def list_project_tags(
    tenant_slug: str,
    project_id: str,
    response: Response,
    limit: int = limit_query(MAX_REVISION_PAGE_LIMIT, maximum=MAX_REVISION_PAGE_LIMIT),
    cursor: Optional[str] = cursor_query(),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> List[TagSchema]:
    """List the class tags of a project, by name.

    The body is a JSON array of at most ``limit`` tags (1,000 at most). The ``X-Has-More``
    response header says whether more exist and ``X-Next-Cursor`` carries the ``cursor`` of the
    next page (#7196).

    Args:
        tenant_slug: The tenant in the URL.
        project_id: The project whose tags are listed.
        response: The outgoing response (paging headers are set on it).
        limit: Page size.
        cursor: Where the page starts (the previous page's ``X-Next-Cursor``).
        auth_data: The authenticated principal.

    Returns:
        One page of tags.

    Raises:
        HTTPException: 400 for a malformed cursor; 404 when the project is unknown.
    """
    tenant_id = _tenant_id(auth_data)
    after = PROJECT_TAGS_ORDER.parse(cursor)
    _assert_project_in_tenant(project_id, tenant_id)
    rows = db.get_tags_for_project(project_id, limit=limit + 1, cursor=after)
    page = PROJECT_TAGS_ORDER.page(rows, limit)
    set_page_headers(response, page)
    return [TagSchema(**dict(r)) for r in page.items]


@router.post("/{tenant_slug}/{project_id}", response_model=TagSchema)
def create_project_tag(
    tenant_slug: str,
    project_id: str,
    body: TagCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> TagSchema:
    """Create a class tag in a project."""
    enforce_permission(db, auth_data, Resource.CLASSES, Action.CREATE)
    tenant_id = _tenant_id(auth_data)
    _assert_project_in_tenant(project_id, tenant_id)

    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Tag name is required")

    try:
        row = db.create_tag(project_id, name, body.color or "default", body.description)
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail="A tag with this name already exists in this project",
        ) from None

    return TagSchema(**dict(row))


@router.patch("/{tenant_slug}/{tag_id}", response_model=TagSchema)
def update_project_tag(
    tenant_slug: str,
    tag_id: str,
    body: TagUpdateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> TagSchema:
    """Update a project class tag."""
    enforce_permission(db, auth_data, Resource.CLASSES, Action.EDIT)
    tenant_id = _tenant_id(auth_data)
    _assert_tag_in_tenant(tag_id, tenant_id)

    if body.name is not None and not body.name.strip():
        raise HTTPException(status_code=400, detail="Tag name cannot be empty")

    try:
        row = db.update_tag(
            tag_id,
            body.name.strip() if body.name is not None else None,
            body.color,
            body.description,
        )
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail="A tag with this name already exists in this project",
        ) from None

    if not row:
        raise HTTPException(status_code=404, detail="Tag not found")
    return TagSchema(**dict(row))


@router.delete("/{tenant_slug}/{tag_id}")
def delete_project_tag(
    tenant_slug: str,
    tag_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, bool]:
    """Delete a project class tag."""
    enforce_permission(db, auth_data, Resource.CLASSES, Action.DELETE)
    tenant_id = _tenant_id(auth_data)
    _assert_tag_in_tenant(tag_id, tenant_id)

    if not db.delete_tag(tag_id):
        raise HTTPException(status_code=404, detail="Tag not found")
    return {"success": True}


@router.get("/{tenant_slug}/classes/{class_id}", response_model=List[ClassTagSchema])
def list_class_tags(
    tenant_slug: str,
    class_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> List[ClassTagSchema]:
    """List tags assigned to a class."""
    tenant_id = _tenant_id(auth_data)
    _assert_class_in_tenant(class_id, tenant_id)
    rows = db.get_tags_for_class(class_id)
    return [ClassTagSchema(**dict(r)) for r in rows]


@router.post("/{tenant_slug}/classes/{class_id}", response_model=ClassTagSchema)
def assign_tag_to_class(
    tenant_slug: str,
    class_id: str,
    body: ClassTagAssignRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ClassTagSchema:
    """Assign a project tag to a class."""
    enforce_permission(db, auth_data, Resource.CLASSES, Action.EDIT)
    tenant_id = _tenant_id(auth_data)
    _assert_class_in_tenant(class_id, tenant_id)
    tag = _assert_tag_in_tenant(body.tag_id, tenant_id)

    class_row = db.get_class_by_id(class_id, tenant_id)
    version = db.get_version_core(str(class_row["version_id"]), tenant_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    if str(tag["project_id"]) != str(version["project_id"]):
        raise HTTPException(status_code=400, detail="Tag does not belong to this class project")

    row = db.assign_tag_to_class(class_id, body.tag_id)
    return ClassTagSchema(**dict(row))


@router.delete("/{tenant_slug}/classes/{class_id}/{tag_id}")
def remove_tag_from_class(
    tenant_slug: str,
    class_id: str,
    tag_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, bool]:
    """Remove a tag assignment from a class."""
    enforce_permission(db, auth_data, Resource.CLASSES, Action.EDIT)
    tenant_id = _tenant_id(auth_data)
    _assert_class_in_tenant(class_id, tenant_id)

    if not db.remove_tag_from_class(class_id, tag_id):
        raise HTTPException(status_code=404, detail="Tag assignment not found")
    return {"success": True}
