"""
Properties API Routes

Provides CRUD endpoints for managing project properties (library properties).
All endpoints are tenant-scoped and require authentication via JWT token or API key.
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Dict, Any

from .database import PropertyUpdateConflict, PropertyUsedInPublishedVersion, db
from .models import (
    ProjectPropertySchema,
    ProjectPropertyCreateRequest,
    ProjectPropertyUpdateRequest
)
from .auth import validate_authentication, get_authenticated_user_id
from .permissions import enforce_permission, Resource, Action

router = APIRouter(prefix="/v1/properties", tags=["properties"])


@router.get("/{tenant_slug}/{project_id}")
async def list_properties(
    tenant_slug: str,
    project_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> List[ProjectPropertySchema]:
    """
    List all properties for a project, each with ``used_by`` (the class names that use it, across the
    project's live versions) and ``used_by_count`` (#3223).

    Supports authentication via:
    - JWT token in Authorization header (Bearer token)
    - API key in X-API-Key header

    Args:
        tenant_slug: The tenant slug
        project_id: The project ID
        auth_data: Authentication data (injected by dependency)

    Returns:
        List of properties for the project
    """
    # Validate project belongs to tenant
    project = db.get_project_by_id(project_id, auth_data['tenant_id'])
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project not found: {project_id}"
        )

    properties = db.get_properties_for_project(project_id, with_usage=True)

    # Parse JSON data if it's a string
    for prop in properties:
        if isinstance(prop.get('data'), str):
            import json
            try:
                prop['data'] = json.loads(prop['data'])
            except:
                prop['data'] = {}

    return [ProjectPropertySchema(**p) for p in properties]


@router.get("/{tenant_slug}/{project_id}/{property_id}")
async def get_property(
    tenant_slug: str,
    project_id: str,
    property_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> ProjectPropertySchema:
    """
    Get a specific property by ID, with ``usage`` — every class attribute that uses it, across the
    project's live versions (#3224).

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug
        project_id: The project ID
        property_id: The property ID
        auth_data: Authentication data (injected by dependency)

    Returns:
        The property details
    """
    # Validate project belongs to tenant
    project = db.get_project_by_id(project_id, auth_data['tenant_id'])
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project not found: {project_id}"
        )

    property_data = db.get_property_by_id(property_id, project_id)

    if not property_data:
        raise HTTPException(
            status_code=404,
            detail=f"Property not found: {property_id}"
        )

    # Parse JSON data if it's a string
    if isinstance(property_data.get('data'), str):
        import json
        try:
            property_data['data'] = json.loads(property_data['data'])
        except:
            property_data['data'] = {}

    property_data['usage'] = db.get_property_usage(property_id)
    return ProjectPropertySchema(**property_data)


@router.post("/{tenant_slug}/{project_id}")
async def create_property(
    tenant_slug: str,
    project_id: str,
    request: ProjectPropertyCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> ProjectPropertySchema:
    """
    Create a new property.

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug
        project_id: The project ID
        request: Property creation data
        auth_data: Authentication data (injected by dependency)

    Returns:
        The created property
    """
    enforce_permission(db, auth_data, Resource.PROPERTIES, Action.CREATE)
    # Validate required fields
    if not request.name or not request.name.strip():
        raise HTTPException(
            status_code=400,
            detail="Property name is required"
        )

    if not request.data:
        raise HTTPException(
            status_code=400,
            detail="Property data is required"
        )

    # Validate project belongs to tenant
    project = db.get_project_by_id(project_id, auth_data['tenant_id'])
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project not found: {project_id}"
        )

    try:
        # Create property
        property_data = db.create_property(
            project_id=project_id,
            name=request.name.strip(),
            description=request.description.strip() if request.description else None,
            data=request.data
        )

        return ProjectPropertySchema(**property_data)
    except Exception as e:
        # Check for unique constraint violation
        if "unique constraint" in str(e).lower() or "23505" in str(e):
            raise HTTPException(
                status_code=409,
                detail=f"A property with name '{request.name.strip()}' already exists in this project"
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant_slug}/{project_id}/{property_id}")
async def update_property(
    tenant_slug: str,
    project_id: str,
    property_id: str,
    request: ProjectPropertyUpdateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> ProjectPropertySchema:
    """
    Update an existing property. ``expectedUpdatedAt`` makes it conditional (409 ``update_conflict``
    when the property changed since); ``requiredEverywhere`` also sets ``required`` on every class
    attribute using it in an unpublished version, reported in ``required_everywhere_result`` (#3226).

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug
        project_id: The project ID
        property_id: The property ID
        request: Property update data
        auth_data: Authentication data (injected by dependency)

    Returns:
        The updated property
    """
    enforce_permission(db, auth_data, Resource.PROPERTIES, Action.EDIT)
    # Validate project belongs to tenant
    project = db.get_project_by_id(project_id, auth_data['tenant_id'])
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project not found: {project_id}"
        )

    # Check if property exists
    existing = db.get_property_by_id(property_id, project_id)
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Property not found: {property_id}"
        )

    # Validate name if provided
    if request.name is not None and not request.name.strip():
        raise HTTPException(
            status_code=400,
            detail="Property name cannot be empty"
        )

    try:
        # Build updates dict from request
        updates = {}
        if request.name is not None:
            updates['name'] = request.name.strip()
        if request.description is not None:
            updates['description'] = request.description.strip() if request.description else None
        if request.data is not None:
            updates['data'] = request.data
        if request.enabled is not None:
            updates['enabled'] = request.enabled

        # Update property — guarded by the caller's last-read updated_at when given, and setting
        # `required` on the class attributes that use it when asked (#3226).
        try:
            property_data = db.update_property(
                property_id,
                project_id,
                updates,
                expected_updated_at=request.expected_updated_at,
                required_everywhere=request.required_everywhere,
            )
        except PropertyUpdateConflict as conflict:
            current = conflict.current_updated_at
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "update_conflict",
                    "message": "The property changed since it was read; re-fetch it and retry.",
                    "current_updated_at": current.isoformat() if hasattr(current, "isoformat") else current,
                },
            )

        if not property_data:
            raise HTTPException(
                status_code=404,
                detail=f"Property not found: {property_id}"
            )

        return ProjectPropertySchema(**property_data)
    except HTTPException:
        raise
    except Exception as e:
        # Check for unique constraint violation
        if "unique constraint" in str(e).lower() or "23505" in str(e):
            raise HTTPException(
                status_code=409,
                detail=f"A property with that name already exists in this project"
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tenant_slug}/{project_id}/{property_id}")
async def delete_property(
    tenant_slug: str,
    project_id: str,
    property_id: str,
    force: bool = Query(
        False,
        description="Also remove every class attribute that uses the property, in the same transaction (#3227). "
        "Refused with 409 `property_in_published_version` when any use is in a published version.",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, Any]:
    """
    Delete a property (soft delete). With ``force=true``, first remove the class attributes that use
    it in unpublished versions — all in one transaction — and report how many as ``detached``; any use
    in a published version refuses the whole delete with 409 (#3227).

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug
        project_id: The project ID
        property_id: The property ID
        auth_data: Authentication data (injected by dependency)

    Returns:
        Success message
    """
    enforce_permission(db, auth_data, Resource.PROPERTIES, Action.DELETE)
    # Validate project belongs to tenant
    project = db.get_project_by_id(project_id, auth_data['tenant_id'])
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project not found: {project_id}"
        )

    # Check if property exists
    existing = db.get_property_by_id(property_id, project_id)
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Property not found: {property_id}"
        )

    if force:
        try:
            detached = db.force_delete_property(property_id, project_id)
        except PropertyUsedInPublishedVersion as refused:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "property_in_published_version",
                    "message": "The property is used in published versions, which cannot change; nothing was deleted.",
                    "uses": refused.uses,
                },
            )
        if detached is None:
            raise HTTPException(status_code=404, detail=f"Property not found: {property_id}")
        return {"message": f"Property '{existing['name']}' deleted successfully", "detached": detached}

    # Delete the property
    success = db.delete_property(property_id, project_id)

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to delete property"
        )

    return {"message": f"Property '{existing['name']}' deleted successfully"}
