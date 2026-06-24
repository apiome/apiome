"""
Properties API Routes

Provides CRUD endpoints for managing project properties (library properties).
All endpoints are tenant-scoped and require authentication via JWT token or API key.
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any

from .database import db
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
    List all properties for a project.

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

    properties = db.get_properties_for_project(project_id)

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
    Get a specific property by ID.

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
    Update an existing property.

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

        # Update property
        property_data = db.update_property(
            property_id,
            project_id,
            updates
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
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, str]:
    """
    Delete a property (soft delete).

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

    # Delete the property
    success = db.delete_property(property_id, project_id)

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to delete property"
        )

    return {"message": f"Property '{existing['name']}' deleted successfully"}
