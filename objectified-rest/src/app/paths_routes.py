"""
Paths API Routes

Provides CRUD endpoints for managing OpenAPI paths and operations.
All endpoints are tenant-scoped and require authentication via JWT token or API key.
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any

from .database import db
from .models import (
    PathSchema,
    PathCreateRequest,
    PathUpdateRequest,
    PathsCanvasPayload,
    OperationSchema,
    OperationCreateRequest,
    OperationUpdateRequest,
    OperationDescriptionRequest,
    SharedParameterSchema,
    SharedParameterCreateRequest,
    SharedRequestBodySchema,
    SharedRequestBodyCreateRequest,
    RequestBodyContentTypeRequest,
    SharedResponseSchema,
    SharedResponseCreateRequest,
    ResponseContentTypeRequest,
    LinkOperationRequest,
    CopyClassToInlineSchemaRequest,
)
from .auth import validate_authentication
from .path_template_validation import validate_openapi_path_template
from .permissions import enforce_permission, Resource, Action

router = APIRouter(prefix="/v1/paths", tags=["paths"])


# ==================== Path CRUD ====================

@router.get("/{tenant_slug}/{version_id}")
async def list_paths(
    tenant_slug: str,
    version_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> List[PathSchema]:
    """
    List all paths for a version.

    Args:
        tenant_slug: The tenant slug
        version_id: The version ID (UUID)
        auth_data: Authentication data (injected by dependency)

    Returns:
        List of paths for the version
    """
    # Verify version belongs to tenant
    version = db.get_version_for_tenant(auth_data['tenant_id'], version_id)
    if not version:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {version_id}"
        )

    paths = db.get_paths_for_version_with_tenant(version_id, auth_data['tenant_id'])
    return [PathSchema(**p) for p in paths]


@router.get("/{tenant_slug}/{version_id}/{path_id}")
async def get_path(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, Any]:
    """
    Get a specific path with its operations.

    Args:
        tenant_slug: The tenant slug
        version_id: The version ID
        path_id: The path ID
        auth_data: Authentication data (injected by dependency)

    Returns:
        Path details with operations
    """
    path = db.get_path_by_id(path_id, auth_data['tenant_id'])
    if not path:
        raise HTTPException(
            status_code=404,
            detail=f"Path not found: {path_id}"
        )

    # Get operations for this path
    operations = db.get_operations_for_path(path_id)

    return {
        **path,
        "operations": operations
    }


@router.get("/{tenant_slug}/{version_id}/{path_id}/canvas")
async def get_path_canvas(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """
    Load persisted React Flow canvas (nodes, edges, viewport) for a path (#2642).
    Tenant-safe; returns defaults when no row exists.
    """
    version = db.get_version_for_tenant(auth_data["tenant_id"], version_id)
    if not version:
        raise HTTPException(status_code=404, detail=f"Version not found: {version_id}")

    canvas = db.get_path_canvas(version_id, path_id, auth_data["tenant_id"])
    if canvas is None:
        raise HTTPException(status_code=404, detail=f"Path not found: {path_id}")

    return {
        "nodes": canvas["nodes"],
        "edges": canvas["edges"],
        "viewport": canvas["viewport"],
        "updated_at": canvas.get("updated_at"),
    }


@router.put("/{tenant_slug}/{version_id}/{path_id}/canvas")
async def put_path_canvas(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    request: PathsCanvasPayload,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Replace Paths canvas JSON for this path (last-write-wins, #2642)."""
    enforce_permission(db, auth_data, Resource.PATHS, Action.EDIT)
    version = db.get_version_for_tenant(auth_data["tenant_id"], version_id)
    if not version:
        raise HTTPException(status_code=404, detail=f"Version not found: {version_id}")

    body = request.model_dump()
    updated = db.upsert_path_canvas(version_id, path_id, auth_data["tenant_id"], body)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Path not found: {path_id}")

    return {
        "nodes": updated["nodes"],
        "edges": updated["edges"],
        "viewport": updated["viewport"],
        "updated_at": updated.get("updated_at"),
    }


@router.post("/{tenant_slug}/{version_id}")
async def create_path(
    tenant_slug: str,
    version_id: str,
    request: PathCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> PathSchema:
    """
    Create a new path.

    Args:
        tenant_slug: The tenant slug
        version_id: The version ID
        request: Path creation data
        auth_data: Authentication data (injected by dependency)

    Returns:
        The created path
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.CREATE)
    # Verify version belongs to tenant
    version = db.get_version_for_tenant(auth_data['tenant_id'], version_id)
    if not version:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {version_id}"
        )

    try:
        validate_openapi_path_template(request.pathname)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    try:
        path = db.create_path(
            version_id=version_id,
            pathname=request.pathname,
            metadata=request.metadata
        )
        return PathSchema(**path)
    except Exception as e:
        if "unique constraint" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail=f"Path '{request.pathname}' already exists in this version"
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant_slug}/{version_id}/{path_id}")
async def update_path(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    request: PathUpdateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> PathSchema:
    """
    Update an existing path.

    Args:
        tenant_slug: The tenant slug
        version_id: The version ID
        path_id: The path ID
        request: Path update data
        auth_data: Authentication data (injected by dependency)

    Returns:
        The updated path
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.EDIT)
    updates = request.model_dump(exclude_unset=True)
    if updates.get("pathname") is not None:
        try:
            validate_openapi_path_template(updates["pathname"])
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    path = db.update_path(path_id, auth_data['tenant_id'], updates)

    if not path:
        raise HTTPException(
            status_code=404,
            detail=f"Path not found: {path_id}"
        )

    return PathSchema(**path)


@router.delete("/{tenant_slug}/{version_id}/{path_id}")
async def delete_path(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, bool]:
    """
    Delete a path.

    Args:
        tenant_slug: The tenant slug
        version_id: The version ID
        path_id: The path ID
        auth_data: Authentication data (injected by dependency)

    Returns:
        Success status
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.DELETE)
    deleted = db.delete_path(path_id, auth_data['tenant_id'])
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Path not found: {path_id}"
        )

    return {"success": True}


# ==================== Operation CRUD ====================

@router.get("/{tenant_slug}/{version_id}/{path_id}/operations")
async def list_operations(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> List[OperationSchema]:
    """
    List all operations for a path.
    """
    # Verify path belongs to tenant
    path = db.get_path_by_id(path_id, auth_data['tenant_id'])
    if not path:
        raise HTTPException(status_code=404, detail=f"Path not found: {path_id}")

    operations = db.get_operations_for_path(path_id)
    return [OperationSchema(**op) for op in operations]


@router.post("/{tenant_slug}/{version_id}/{path_id}/operations")
async def create_operation(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    request: OperationCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> OperationSchema:
    """
    Create a new operation for a path.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.CREATE)
    # Verify path belongs to tenant
    path = db.get_path_by_id(path_id, auth_data['tenant_id'])
    if not path:
        raise HTTPException(status_code=404, detail=f"Path not found: {path_id}")

    try:
        operation = db.create_operation(
            version_path_id=path_id,
            operation=request.operation,
            metadata=request.metadata
        )
        return OperationSchema(**operation)
    except Exception as e:
        if "unique constraint" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail=f"Operation '{request.operation}' already exists for this path"
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}")
async def update_operation(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    operation_id: str,
    request: OperationUpdateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> OperationSchema:
    """
    Update an operation.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.EDIT)
    updates = request.model_dump(exclude_unset=True)
    operation = db.update_operation(operation_id, auth_data['tenant_id'], updates)

    if not operation:
        raise HTTPException(status_code=404, detail=f"Operation not found: {operation_id}")

    return OperationSchema(**operation)


@router.delete("/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}")
async def delete_operation(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    operation_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, bool]:
    """
    Delete an operation.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.DELETE)
    deleted = db.delete_operation(operation_id, auth_data['tenant_id'])
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Operation not found: {operation_id}")

    return {"success": True}


# ==================== Operation Description ====================

@router.get("/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}/description")
async def get_operation_description(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    operation_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, Any]:
    """
    Get operation description (summary, description, operationId, tags, etc.)
    """
    # Verify operation belongs to tenant
    operation = db.get_operation_by_id(operation_id, auth_data['tenant_id'])
    if not operation:
        raise HTTPException(status_code=404, detail=f"Operation not found: {operation_id}")

    desc = db.get_operation_description(operation_id)
    return desc or {}


@router.put("/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}/description")
async def update_operation_description(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    operation_id: str,
    request: OperationDescriptionRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, Any]:
    """
    Create or update operation description.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.EDIT)
    # Verify operation belongs to tenant
    operation = db.get_operation_by_id(operation_id, auth_data['tenant_id'])
    if not operation:
        raise HTTPException(status_code=404, detail=f"Operation not found: {operation_id}")

    desc = db.create_operation_description(
        path_operation_id=operation_id,
        summary=request.summary,
        description=request.description,
        operation_id=request.operation_id,
        metadata=request.metadata
    )
    return desc


# ==================== Shared Parameters ====================

@router.get("/{tenant_slug}/{version_id}/{path_id}/parameters")
async def list_shared_parameters(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> List[SharedParameterSchema]:
    """
    List all shared parameters for a path.
    """
    path = db.get_path_by_id(path_id, auth_data['tenant_id'])
    if not path:
        raise HTTPException(status_code=404, detail=f"Path not found: {path_id}")

    params = db.get_shared_parameters_for_path(path_id)
    return [SharedParameterSchema(**p) for p in params]


@router.post("/{tenant_slug}/{version_id}/{path_id}/parameters")
async def create_shared_parameter(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    request: SharedParameterCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> SharedParameterSchema:
    """
    Create a shared parameter for a path.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.CREATE)
    path = db.get_path_by_id(path_id, auth_data['tenant_id'])
    if not path:
        raise HTTPException(status_code=404, detail=f"Path not found: {path_id}")

    param = db.create_shared_parameter(
        version_path_id=path_id,
        name=request.name,
        in_location=request.in_location,
        summary=request.summary,
        description=request.description,
        data=request.data
    )
    return SharedParameterSchema(**param)


@router.post("/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}/parameters/{parameter_id}/link")
async def link_parameter_to_operation(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    operation_id: str,
    parameter_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, Any]:
    """
    Link a shared parameter to an operation.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.CREATE)
    operation = db.get_operation_by_id(operation_id, auth_data['tenant_id'])
    if not operation:
        raise HTTPException(status_code=404, detail=f"Operation not found: {operation_id}")

    link = db.link_parameter_to_operation(operation_id, parameter_id)
    return link


@router.delete("/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}/parameters/{parameter_id}/link")
async def unlink_parameter_from_operation(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    operation_id: str,
    parameter_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, bool]:
    """
    Unlink a shared parameter from an operation.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.DELETE)
    deleted = db.unlink_parameter_from_operation(operation_id, parameter_id)
    return {"success": deleted}


@router.delete("/{tenant_slug}/{version_id}/{path_id}/parameters/{parameter_id}")
async def delete_shared_parameter(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    parameter_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, bool]:
    """
    Delete a shared parameter.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.DELETE)
    deleted = db.delete_shared_parameter(parameter_id, auth_data['tenant_id'])
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Parameter not found: {parameter_id}")

    return {"success": True}


# ==================== Shared Request Bodies ====================

@router.get("/{tenant_slug}/{version_id}/{path_id}/request-bodies")
async def list_shared_request_bodies(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> List[SharedRequestBodySchema]:
    """
    List all shared request bodies for a path.
    """
    path = db.get_path_by_id(path_id, auth_data['tenant_id'])
    if not path:
        raise HTTPException(status_code=404, detail=f"Path not found: {path_id}")

    bodies = db.get_shared_request_bodies_for_path(path_id)
    return [SharedRequestBodySchema(**b) for b in bodies]


@router.post("/{tenant_slug}/{version_id}/{path_id}/request-bodies")
async def create_shared_request_body(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    request: SharedRequestBodyCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> SharedRequestBodySchema:
    """
    Create a shared request body for a path.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.CREATE)
    path = db.get_path_by_id(path_id, auth_data['tenant_id'])
    if not path:
        raise HTTPException(status_code=404, detail=f"Path not found: {path_id}")

    body = db.create_shared_request_body(
        version_path_id=path_id,
        name=request.name,
        description=request.description,
        required=request.required
    )
    return SharedRequestBodySchema(**body)


@router.post("/{tenant_slug}/{version_id}/{path_id}/request-bodies/{request_body_id}/content-types")
async def add_request_body_content_type(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    request_body_id: str,
    request: RequestBodyContentTypeRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, Any]:
    """
    Add a content type to a request body.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.CREATE)
    content = db.add_request_body_content_type(
        shared_request_body_id=request_body_id,
        media_type=request.media_type,
        class_id=request.class_id,
        inline_schema=request.inline_schema,
        encoding=request.encoding,
        examples=request.examples
    )
    return content


@router.post("/{tenant_slug}/{version_id}/{path_id}/request-bodies/{request_body_id}/content-types/{media_type}/copy-from-class")
async def copy_class_to_request_body_inline_schema(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    request_body_id: str,
    media_type: str,
    request: CopyClassToInlineSchemaRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, Any]:
    """
    Copy class properties to create an inline schema for the request body content type.
    This creates a copy of the class schema, not a reference.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.CREATE)
    # Get class properties and build inline schema
    inline_schema = db.copy_class_properties_to_inline_schema(request.class_id)

    # Update the content type with the inline schema
    content = db.add_request_body_content_type(
        shared_request_body_id=request_body_id,
        media_type=media_type.replace('_', '/'),  # URL-safe media type
        class_id=None,  # No class reference - this is a copy
        inline_schema=inline_schema
    )
    return content


@router.post("/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}/request-body/{request_body_id}/link")
async def link_request_body_to_operation(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    operation_id: str,
    request_body_id: str,
    request: LinkOperationRequest = None,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, Any]:
    """
    Link a shared request body to an operation.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.CREATE)
    operation = db.get_operation_by_id(operation_id, auth_data['tenant_id'])
    if not operation:
        raise HTTPException(status_code=404, detail=f"Operation not found: {operation_id}")

    metadata = request.metadata if request else None
    link = db.link_request_body_to_operation(operation_id, request_body_id, metadata)
    return link


@router.delete("/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}/request-body/link")
async def unlink_request_body_from_operation(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    operation_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, bool]:
    """
    Unlink request body from an operation.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.DELETE)
    deleted = db.unlink_request_body_from_operation(operation_id)
    return {"success": deleted}


@router.delete("/{tenant_slug}/{version_id}/{path_id}/request-bodies/{request_body_id}")
async def delete_shared_request_body(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    request_body_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, bool]:
    """
    Delete a shared request body.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.DELETE)
    deleted = db.delete_shared_request_body(request_body_id, auth_data['tenant_id'])
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Request body not found: {request_body_id}")

    return {"success": True}


# ==================== Shared Responses ====================

@router.get("/{tenant_slug}/{version_id}/{path_id}/responses")
async def list_shared_responses(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> List[SharedResponseSchema]:
    """
    List all shared responses for a path.
    """
    path = db.get_path_by_id(path_id, auth_data['tenant_id'])
    if not path:
        raise HTTPException(status_code=404, detail=f"Path not found: {path_id}")

    responses = db.get_shared_responses_for_path(path_id)
    return [SharedResponseSchema(**r) for r in responses]


@router.post("/{tenant_slug}/{version_id}/{path_id}/responses")
async def create_shared_response(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    request: SharedResponseCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> SharedResponseSchema:
    """
    Create a shared response for a path.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.CREATE)
    path = db.get_path_by_id(path_id, auth_data['tenant_id'])
    if not path:
        raise HTTPException(status_code=404, detail=f"Path not found: {path_id}")

    response = db.create_shared_response(
        version_path_id=path_id,
        status_code=request.status_code,
        description=request.description,
        data=request.data,
        class_id=request.class_id,
        inline_schema=request.inline_schema
    )
    return SharedResponseSchema(**response)


@router.post("/{tenant_slug}/{version_id}/{path_id}/responses/{response_id}/content-types")
async def add_response_content_type(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    response_id: str,
    request: ResponseContentTypeRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, Any]:
    """
    Add a content type to a response.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.CREATE)
    content = db.add_response_content_type(
        shared_response_id=response_id,
        media_type=request.media_type,
        class_id=request.class_id,
        inline_schema=request.inline_schema,
        examples=request.examples
    )
    return content


@router.post("/{tenant_slug}/{version_id}/{path_id}/responses/{response_id}/content-types/{media_type}/copy-from-class")
async def copy_class_to_response_inline_schema(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    response_id: str,
    media_type: str,
    request: CopyClassToInlineSchemaRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, Any]:
    """
    Copy class properties to create an inline schema for the response content type.
    This creates a copy of the class schema, not a reference.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.CREATE)
    inline_schema = db.copy_class_properties_to_inline_schema(request.class_id)

    content = db.add_response_content_type(
        shared_response_id=response_id,
        media_type=media_type.replace('_', '/'),
        class_id=None,
        inline_schema=inline_schema
    )
    return content


@router.post("/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}/responses/{response_id}/link")
async def link_response_to_operation(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    operation_id: str,
    response_id: str,
    request: LinkOperationRequest = None,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, Any]:
    """
    Link a shared response to an operation.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.CREATE)
    operation = db.get_operation_by_id(operation_id, auth_data['tenant_id'])
    if not operation:
        raise HTTPException(status_code=404, detail=f"Operation not found: {operation_id}")

    metadata = request.metadata if request else None
    link = db.link_response_to_operation(operation_id, response_id, metadata)
    return link


@router.delete("/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}/responses/{response_id}/link")
async def unlink_response_from_operation(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    operation_id: str,
    response_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, bool]:
    """
    Unlink a shared response from an operation.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.DELETE)
    deleted = db.unlink_response_from_operation(operation_id, response_id)
    return {"success": deleted}


@router.delete("/{tenant_slug}/{version_id}/{path_id}/responses/{response_id}")
async def delete_shared_response(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    response_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, bool]:
    """
    Delete a shared response.
    """
    enforce_permission(db, auth_data, Resource.PATHS, Action.DELETE)
    deleted = db.delete_shared_response(response_id, auth_data['tenant_id'])
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Response not found: {response_id}")

    return {"success": True}


# ==================== Full Path with Operations Data ====================

@router.get("/{tenant_slug}/{version_id}/{path_id}/full")
async def get_path_full(
    tenant_slug: str,
    version_id: str,
    path_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, Any]:
    """
    Get a path with full operation details (parameters, request bodies, responses).
    Useful for loading complete path data for the canvas.
    """
    path = db.get_path_by_id(path_id, auth_data['tenant_id'])
    if not path:
        raise HTTPException(status_code=404, detail=f"Path not found: {path_id}")

    operations_data = db.get_operations_for_path(path_id)
    operations = []

    for op in operations_data:
        op_id = op['id']

        # Get operation description
        description = db.get_operation_description(op_id)

        # Get parameters
        parameters = db.get_parameters_for_operation(op_id)

        # Get request body
        request_body = db.get_request_body_for_operation(op_id)

        # Get responses
        responses = db.get_responses_for_operation(op_id)

        operations.append({
            **op,
            'description': description,
            'parameters': parameters,
            'requestBody': request_body,
            'responses': responses
        })

    return {
        **path,
        'operations': operations
    }
