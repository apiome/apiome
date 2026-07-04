"""
Projects API Routes

Provides CRUD endpoints for managing projects.
All endpoints are tenant-scoped and require authentication via JWT token or API key.
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List, Dict, Any

from .database import db
from .api_identity_service import build_related_artifact_refs
from .models import (
    ProjectSchema,
    ProjectCreateRequest,
    ProjectUpdateRequest
)
from .auth import validate_authentication, get_authenticated_user_id
from .permissions import enforce_permission, Resource, Action

router = APIRouter(prefix="/v1/projects", tags=["projects"])

# Ids must stay aligned with apiome-cli `domain-categories.ts` PROJECT_DOMAIN_CHOICES (#3204).
PROJECT_DOMAIN_CATEGORY_IDS: List[str] = [
    "iot",
    "social",
    "gaming",
    "travel",
    "media",
    "ecommerce",
    "healthcare",
    "finance",
    "saas",
    "education",
    "realestate",
    "logistics",
]


@router.get("/domains")
async def list_project_domain_categories_global() -> Dict[str, List[str]]:
    """
    Allowlist of ``domainCategory`` ids for project metadata.

    Public read (CLI prefetch uses no credentials). Register before ``/{tenant_slug}`` so
    ``/v1/projects/domains`` is not captured as a tenant slug.
    """
    return {"domains": list(PROJECT_DOMAIN_CATEGORY_IDS)}


@router.get("/{tenant_slug}/domains")
async def list_project_domain_categories_for_tenant(tenant_slug: str) -> Dict[str, List[str]]:
    """
    Same allowlist under the tenant-scoped URL shape expected by the CLI.

    Must be registered before ``/{tenant_slug}/{project_id}`` so the final segment
    ``domains`` is not interpreted as a project UUID.
    """
    _ = tenant_slug  # reserved for future tenant-specific overrides
    return {"domains": list(PROJECT_DOMAIN_CATEGORY_IDS)}


@router.get("/{tenant_slug}")
async def list_projects(
    tenant_slug: str,
    include_deleted: bool = Query(
        False,
        description="When true, include soft-deleted projects (active projects listed first).",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> List[ProjectSchema]:
    """
    List all projects for a tenant.

    Supports authentication via:
    - JWT token in Authorization header (Bearer token)
    - API key in X-API-Key header

    Args:
        tenant_slug: The tenant slug
        include_deleted: Include rows with deleted_at set (for trash / restore flows).
        auth_data: Authentication data (injected by dependency)

    Returns:
        List of projects for the tenant
    """
    projects = db.get_projects_for_tenant(
        auth_data['tenant_id'], include_deleted=include_deleted
    )

    return [ProjectSchema(**p) for p in projects]


@router.get("/{tenant_slug}/{project_id}")
async def get_project(
    tenant_slug: str,
    project_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> ProjectSchema:
    """
    Get a specific project by ID.

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug
        project_id: The project ID
        auth_data: Authentication data (injected by dependency)

    Returns:
        The project details
    """
    project = db.get_project_by_id(project_id, auth_data['tenant_id'])

    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project not found: {project_id}"
        )

    tenant_id = auth_data["tenant_id"]
    group_id = db.get_identity_group_id_for_project(tenant_id, project_id)
    related = build_related_artifact_refs(
        db.get_related_artifact_rows(tenant_id, project_id)
    )

    return ProjectSchema(
        **project,
        identity_group_id=group_id,
        related_artifacts=related,
    )


@router.get("/{tenant_slug}/by-slug/{project_slug}")
async def get_project_by_slug(
    tenant_slug: str,
    project_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> ProjectSchema:
    """
    Get a specific project by slug.

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug
        project_slug: The project slug
        auth_data: Authentication data (injected by dependency)

    Returns:
        The project details
    """
    project = db.get_project_by_slug(project_slug, auth_data['tenant_id'])

    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project not found with slug: {project_slug}"
        )

    return ProjectSchema(**project)


@router.post("/{tenant_slug}")
async def create_project(
    tenant_slug: str,
    request: ProjectCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> ProjectSchema:
    """
    Create a new project.

    Supports authentication via JWT token or API key.
    When using JWT, the creator_id field will be set to the authenticated user.

    Args:
        tenant_slug: The tenant slug
        request: Project creation data
        auth_data: Authentication data (injected by dependency)

    Returns:
        The created project
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.CREATE)
    # Validate required fields
    if not request.name or not request.name.strip():
        raise HTTPException(
            status_code=400,
            detail="Project name is required"
        )

    if not request.slug or not request.slug.strip():
        raise HTTPException(
            status_code=400,
            detail="Project slug is required"
        )

    # Validate slug format (alphanumeric, hyphens, underscores only)
    slug = request.slug.strip().lower()
    if not all(c.isalnum() or c in '-_' for c in slug):
        raise HTTPException(
            status_code=400,
            detail="Project slug can only contain letters, numbers, hyphens, and underscores"
        )

    if len(slug) < 2:
        raise HTTPException(
            status_code=400,
            detail="Project slug must be at least 2 characters long"
        )

    if len(slug) > 50:
        raise HTTPException(
            status_code=400,
            detail="Project slug must be 50 characters or less"
        )

    try:
        # JWT: token user_id. API key: api_keys.created_by_user_id or tenant admin/member fallback.
        creator_id = get_authenticated_user_id(auth_data)
        if creator_id is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Cannot resolve creator user for this tenant (projects.creator_id is required). "
                    "With API keys: apply DB migration 20260509-220000.sql, create a new key from the UI "
                    "(stores created_by_user_id), or ensure the tenant has at least one member."
                ),
            )

        # Create project
        project = db.create_project(
            tenant_id=auth_data['tenant_id'],
            creator_id=creator_id,
            name=request.name.strip(),
            slug=slug,
            description=request.description.strip() if request.description else None,
            metadata=request.metadata
        )

        return ProjectSchema(**project)
    except Exception as e:
        # Check for unique constraint violation
        if "unique constraint" in str(e).lower() or "23505" in str(e):
            raise HTTPException(
                status_code=409,
                detail=f"A project with slug '{slug}' already exists in this tenant"
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant_slug}/{project_id}")
async def update_project(
    tenant_slug: str,
    project_id: str,
    request: ProjectUpdateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> ProjectSchema:
    """
    Update an existing project.

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug
        project_id: The project ID
        request: Project update data
        auth_data: Authentication data (injected by dependency)

    Returns:
        The updated project
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    # Check if project exists
    existing = db.get_project_by_id(project_id, auth_data['tenant_id'])
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Project not found: {project_id}"
        )

    # Validate slug if provided
    if request.slug is not None:
        slug = request.slug.strip().lower()
        if not all(c.isalnum() or c in '-_' for c in slug):
            raise HTTPException(
                status_code=400,
                detail="Project slug can only contain letters, numbers, hyphens, and underscores"
            )
        if len(slug) < 2:
            raise HTTPException(
                status_code=400,
                detail="Project slug must be at least 2 characters long"
            )
        if len(slug) > 50:
            raise HTTPException(
                status_code=400,
                detail="Project slug must be 50 characters or less"
            )

    # Validate name if provided
    if request.name is not None and not request.name.strip():
        raise HTTPException(
            status_code=400,
            detail="Project name cannot be empty"
        )

    try:
        # Build updates dict from request
        updates = {}
        if request.name is not None:
            updates['name'] = request.name.strip()
        if request.description is not None:
            updates['description'] = request.description.strip() if request.description else None
        if request.slug is not None:
            updates['slug'] = request.slug.strip().lower()
        if request.enabled is not None:
            updates['enabled'] = request.enabled
        if request.metadata is not None:
            updates['metadata'] = request.metadata
        fs = getattr(request, "model_fields_set", set())
        if "change_report_template_version_id" in fs:
            updates["change_report_template_version_id"] = request.change_report_template_version_id

        # Update project
        project = db.update_project(
            project_id,
            auth_data['tenant_id'],
            updates
        )

        if not project:
            raise HTTPException(
                status_code=404,
                detail=f"Project not found: {project_id}"
            )

        return ProjectSchema(**project)
    except HTTPException:
        raise
    except Exception as e:
        # Check for unique constraint violation
        if "unique constraint" in str(e).lower() or "23505" in str(e):
            raise HTTPException(
                status_code=409,
                detail=f"A project with that slug already exists in this tenant"
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tenant_slug}/{project_id}")
async def delete_project(
    tenant_slug: str,
    project_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, str]:
    """
    Delete a project (soft delete).

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug
        project_id: The project ID
        auth_data: Authentication data (injected by dependency)

    Returns:
        Success message
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.DELETE)
    # Check if project exists
    existing = db.get_project_by_id(project_id, auth_data['tenant_id'])
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Project not found: {project_id}"
        )

    # Delete the project
    success = db.delete_project(project_id, auth_data['tenant_id'])

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to delete project"
        )

    return {"message": f"Project '{existing['name']}' deleted successfully"}


@router.post("/{tenant_slug}/{project_id}/restore")
async def restore_project(
    tenant_slug: str,
    project_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> ProjectSchema:
    """Restore a soft-deleted project (clears deleted_at, sets enabled)."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    row = db.get_project_by_id(
        project_id, auth_data['tenant_id'], include_deleted=True
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Project not found: {project_id}",
        )
    if row.get("deleted_at") is None:
        raise HTTPException(
            status_code=400,
            detail="Project is not deleted",
        )

    restored = db.restore_project(project_id, auth_data['tenant_id'])
    if not restored:
        raise HTTPException(
            status_code=409,
            detail="Project could not be restored (it may have already been restored or permanently deleted)",
        )

    project = db.get_project_by_id(project_id, auth_data['tenant_id'])
    if not project:
        raise HTTPException(
            status_code=500,
            detail="Project was restored but could not be reloaded",
        )
    return ProjectSchema(**project)
