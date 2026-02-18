from fastapi import FastAPI, HTTPException, Response, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.openapi.docs import get_swagger_ui_html
from typing import Dict, Any, Optional
import yaml
import json

from .database import db
from .openapi_generator import generate_openapi_spec, generate_class_openapi_spec
from .arazzo_generator import generate_arazzo_spec, generate_class_arazzo_spec
from .jsonschema_generator import generate_jsonschema_spec, generate_class_jsonschema_spec
from .models import OpenAPIResponse
from .primitives_routes import router as primitives_router
from .classes_routes import router as classes_router
from .projects_routes import router as projects_router
from .versions_routes import router as versions_router
from .properties_routes import router as properties_router
from .paths_routes import router as paths_router

# Create FastAPI app
app = FastAPI(
    title="Objectified REST API",
    description="REST API for serving OpenAPI specifications from the Objectified database",
    version="1.0.4"
)


def custom_openapi() -> Dict[str, Any]:
    """Generate OpenAPI schema with security schemes for JWT and API key."""
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema.setdefault("components", {})
    openapi_schema["components"]["securitySchemes"] = {
        "Bearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT token from NextAuth (Authorization: Bearer &lt;token&gt;)",
        },
        "ApiKey": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "API key for tenant-scoped access (alternative to JWT)",
        },
    }
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Next.js default port
        "http://localhost:3001",  # Next.js when 3000 is taken
    ],
    allow_origin_regex=r"https://.*\.objectified\.dev",  # Allow all *.objectified.dev subdomains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(primitives_router)
app.include_router(classes_router)
app.include_router(projects_router)
app.include_router(versions_router)
app.include_router(properties_router)
app.include_router(paths_router)


@app.on_event("startup")
async def startup_event():
    """Connect to database on startup."""
    db.connect()


@app.on_event("shutdown")
async def shutdown_event():
    """Close database connection on shutdown."""
    db.close()


def validate_private_access(version: Dict[str, Any], tenant_slug: str, api_key: Optional[str]) -> None:
    """
    Validate access to a private version.

    Args:
        version: The version data from database
        tenant_slug: The requested tenant slug
        api_key: The API key from request headers (if provided)

    Raises:
        HTTPException: If access is denied
    """
    # Public versions don't require API key
    if version['visibility'] == 'public':
        return

    # Private versions require API key
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="API key required for private versions",
            headers={"WWW-Authenticate": "API-Key"}
        )

    # Validate the API key
    api_key_data = db.validate_api_key(api_key)

    if not api_key_data:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired API key",
            headers={"WWW-Authenticate": "API-Key"}
        )

    # Check if the API key's tenant matches the requested tenant
    if api_key_data['tenant_slug'] != tenant_slug:
        raise HTTPException(
            status_code=401,
            detail="API key does not have access to this tenant"
        )


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Objectified REST API",
        "version": "1.0.0",
        "endpoints": {
            "version_spec": "/v1/schema/{tenant-slug}/{project-slug}/{version-slug}",
            "class_spec": "/v1/schema/{tenant-slug}/{project-slug}/{version-slug}/{class-name}",
            "swagger_ui": "/v1/swagger/{tenant-slug}/{project-slug}/{version-slug}",
            "arazzo_spec": "/v1/arazzo/{tenant-slug}/{project-slug}/{version-slug}",
            "class_arazzo_spec": "/v1/arazzo/{tenant-slug}/{project-slug}/{version-slug}/{class-name}",
            "jsonschema_spec": "/v1/json/{tenant-slug}/{project-slug}/{version-slug}",
            "class_jsonschema_spec": "/v1/json/{tenant-slug}/{project-slug}/{version-slug}/{class-name}",
            "primitives": {
                "list": "/v1/primitives/{tenant-slug}",
                "get": "/v1/primitives/{tenant-slug}/{primitive-id}",
                "create": "POST /v1/primitives/{tenant-slug}",
                "update": "PUT /v1/primitives/{tenant-slug}/{primitive-id}",
                "delete": "DELETE /v1/primitives/{tenant-slug}/{primitive-id}",
                "import": "POST /v1/primitives/{tenant-slug}/import"
            },
            "paths": {
                "list": "/v1/paths/{tenant-slug}/{version-id}",
                "get": "/v1/paths/{tenant-slug}/{version-id}/{path-id}",
                "get_full": "/v1/paths/{tenant-slug}/{version-id}/{path-id}/full",
                "create": "POST /v1/paths/{tenant-slug}/{version-id}",
                "update": "PUT /v1/paths/{tenant-slug}/{version-id}/{path-id}",
                "delete": "DELETE /v1/paths/{tenant-slug}/{version-id}/{path-id}",
                "operations": "/v1/paths/{tenant-slug}/{version-id}/{path-id}/operations",
                "parameters": "/v1/paths/{tenant-slug}/{version-id}/{path-id}/parameters",
                "request_bodies": "/v1/paths/{tenant-slug}/{version-id}/{path-id}/request-bodies",
                "responses": "/v1/paths/{tenant-slug}/{version-id}/{path-id}/responses"
            }
        }
    }


@app.get("/v1/schema/{tenant_slug}/{project_slug}/{version_slug}")
async def get_version_openapi_spec(
    tenant_slug: str,
    project_slug: str,
    version_slug: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None, description="API key for private versions (alternative to X-API-Key header)")
) -> JSONResponse:
    """
    Get the complete OpenAPI specification for all classes in a version.

    Args:
        tenant_slug: The tenant slug
        project_slug: The project slug
        version_slug: The version ID (e.g., "1.0.0")
        x_api_key: Optional API key for private versions (header)
        api_key: Optional API key for private versions (query, for links)

    Returns:
        OpenAPI 3.1.0 specification in JSON format
    """
    # Get version information
    version = db.get_version_by_slugs(tenant_slug, project_slug, version_slug)

    if not version:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {tenant_slug}/{project_slug}/{version_slug}"
        )

    # Check if version is published
    if not version['published']:
        raise HTTPException(
            status_code=403,
            detail="This version is not published"
        )

    # Validate access for private versions (header or query param)
    validate_private_access(version, tenant_slug, x_api_key or api_key)

    # Get all classes for this version
    classes = db.get_classes_for_version(version['id'])

    # Get properties for each class
    all_properties = {}
    for class_data in classes:
        class_id = class_data['id']
        properties = db.get_properties_for_class(class_id)
        all_properties[class_id] = properties

    # Generate OpenAPI specification with paths
    openapi_spec = generate_openapi_spec(
        tenant_slug,
        project_slug,
        version_slug,
        classes,
        all_properties,
        version.get('project_description'),
        version_db_id=version['id']  # Pass version database ID to load paths
    )

    return JSONResponse(content=openapi_spec)


@app.get("/v1/schema/{tenant_slug}/{project_slug}/{version_slug}/{class_name}")
async def get_class_openapi_spec(
    tenant_slug: str,
    project_slug: str,
    version_slug: str,
    class_name: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    accept: Optional[str] = Header(None)
) -> Response:
    """
    Get the OpenAPI specification for a single class.
    Uses content negotiation to determine response format (JSON or YAML).

    Args:
        tenant_slug: The tenant slug
        project_slug: The project slug
        version_slug: The version ID (e.g., "1.0.0")
        class_name: The name of the class
        x_api_key: Optional API key for private versions
        accept: Accept header for content negotiation

    Returns:
        OpenAPI 3.1.0 specification for the class in JSON or YAML format
    """
    # Get version information
    version = db.get_version_by_slugs(tenant_slug, project_slug, version_slug)

    if not version:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {tenant_slug}/{project_slug}/{version_slug}"
        )

    # Check if version is published
    if not version['published']:
        raise HTTPException(
            status_code=403,
            detail="This version is not published"
        )

    # Validate access for private versions
    validate_private_access(version, tenant_slug, x_api_key)

    # Get the specific class
    class_data = db.get_class_by_name(version['id'], class_name)

    if not class_data:
        raise HTTPException(
            status_code=404,
            detail=f"Class not found: {class_name}"
        )

    # Get properties for the class
    properties = db.get_properties_for_class(class_data['id'])

    # Generate OpenAPI specification for this class
    openapi_spec = generate_class_openapi_spec(
        tenant_slug,
        project_slug,
        version_slug,
        class_data,
        properties
    )

    # Determine response format based on Accept header
    # Default to JSON if no Accept header or if it's not specific
    accept_header = (accept or "").lower()

    # Check for YAML preference
    if any(mime in accept_header for mime in ["application/yaml", "application/x-yaml", "text/yaml", "text/x-yaml"]):
        # Convert to YAML
        yaml_content = yaml.dump(openapi_spec, sort_keys=False, default_flow_style=False)
        return Response(
            content=yaml_content,
            media_type="application/x-yaml",
            headers={
                "Content-Disposition": f'attachment; filename="{class_name}.yaml"'
            }
        )

    # Default to JSON (for application/json, */* or any other Accept header)
    return JSONResponse(content=openapi_spec)


@app.get("/v1/swagger/{tenant_slug}/{project_slug}/{version_slug}", response_class=HTMLResponse)
async def get_swagger_ui(
    tenant_slug: str,
    project_slug: str,
    version_slug: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None, description="API key for private versions (alternative to X-API-Key header)")
) -> HTMLResponse:
    """
    Display the OpenAPI specification in a Swagger UI interface.

    Args:
        tenant_slug: The tenant slug
        project_slug: The project slug
        version_slug: The version ID (e.g., "1.0.0")
        x_api_key: Optional API key for private versions (header)
        api_key: Optional API key for private versions (query, for links)

    Returns:
        HTML page with Swagger UI displaying the schema
    """
    # Get version information
    version = db.get_version_by_slugs(tenant_slug, project_slug, version_slug)

    if not version:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {tenant_slug}/{project_slug}/{version_slug}"
        )

    # Check if version is published
    if not version['published']:
        raise HTTPException(
            status_code=403,
            detail="This version is not published"
        )

    # Validate access for private versions (header or query param)
    validate_private_access(version, tenant_slug, x_api_key or api_key)

    # Get all classes for this version
    classes = db.get_classes_for_version(version['id'])

    # Get properties for each class
    all_properties = {}
    for class_data in classes:
        class_id = class_data['id']
        properties = db.get_properties_for_class(class_id)
        all_properties[class_id] = properties

    # Generate OpenAPI specification with paths
    openapi_spec = generate_openapi_spec(
        tenant_slug,
        project_slug,
        version_slug,
        classes,
        all_properties,
        version.get('project_description'),
        version_db_id=version['id']  # Pass version database ID to load paths
    )

    # Create a custom Swagger UI HTML page with the spec embedded
    swagger_html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{project_slug} API - Swagger UI</title>
    <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
    <style>
        body {{
            margin: 0;
            padding: 0;
        }}
        .topbar {{
            display: none;
        }}
    </style>
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
    <script>
        window.onload = function() {{
            const spec = {json.dumps(openapi_spec)};

            window.ui = SwaggerUIBundle({{
                spec: spec,
                dom_id: '#swagger-ui',
                deepLinking: true,
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIStandalonePreset
                ],
                plugins: [
                    SwaggerUIBundle.plugins.DownloadUrl
                ],
                layout: "StandaloneLayout"
            }});
        }};
    </script>
</body>
</html>
"""

    return HTMLResponse(content=swagger_html)


@app.get("/v1/arazzo/{tenant_slug}/{project_slug}/{version_slug}")
async def get_version_arazzo_spec(
    tenant_slug: str,
    project_slug: str,
    version_slug: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None, description="API key for private versions (alternative to X-API-Key header)"),
    accept: Optional[str] = Header(None)
) -> Response:
    """
    Get the complete Arazzo workflow specification for all classes in a version.
    Uses content negotiation to determine response format (JSON or YAML).

    Args:
        tenant_slug: The tenant slug
        project_slug: The project slug
        version_slug: The version ID (e.g., "1.0.0")
        x_api_key: Optional API key for private versions (header)
        api_key: Optional API key for private versions (query, for links)
        accept: Accept header for content negotiation

    Returns:
        Arazzo 1.0.1 specification in JSON or YAML format
    """
    # Get version information
    version = db.get_version_by_slugs(tenant_slug, project_slug, version_slug)

    if not version:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {tenant_slug}/{project_slug}/{version_slug}"
        )

    # Check if version is published
    if not version['published']:
        raise HTTPException(
            status_code=403,
            detail="This version is not published"
        )

    # Validate access for private versions (header or query param)
    validate_private_access(version, tenant_slug, x_api_key or api_key)

    # Get all classes for this version
    classes = db.get_classes_for_version(version['id'])

    # Generate Arazzo specification
    arazzo_spec = generate_arazzo_spec(
        tenant_slug,
        project_slug,
        version_slug,
        classes,
        version.get('project_description')
    )

    # Determine response format based on Accept header
    accept_header = (accept or "").lower()

    # Check for YAML preference
    if any(mime in accept_header for mime in ["application/yaml", "application/x-yaml", "text/yaml", "text/x-yaml"]):
        # Convert to YAML
        yaml_content = yaml.dump(arazzo_spec, sort_keys=False, default_flow_style=False)
        return Response(
            content=yaml_content,
            media_type="application/x-yaml",
            headers={
                "Content-Disposition": f'attachment; filename="{project_slug}-workflows.yaml"'
            }
        )

    # Default to JSON
    return JSONResponse(content=arazzo_spec)


@app.get("/v1/arazzo/{tenant_slug}/{project_slug}/{version_slug}/{class_name}")
async def get_class_arazzo_spec(
    tenant_slug: str,
    project_slug: str,
    version_slug: str,
    class_name: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    accept: Optional[str] = Header(None)
) -> Response:
    """
    Get the Arazzo workflow specification for a single class.
    Uses content negotiation to determine response format (JSON or YAML).

    Args:
        tenant_slug: The tenant slug
        project_slug: The project slug
        version_slug: The version ID (e.g., "1.0.0")
        class_name: The name of the class
        x_api_key: Optional API key for private versions
        accept: Accept header for content negotiation

    Returns:
        Arazzo 1.0.1 specification for the class in JSON or YAML format
    """
    # Get version information
    version = db.get_version_by_slugs(tenant_slug, project_slug, version_slug)

    if not version:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {tenant_slug}/{project_slug}/{version_slug}"
        )

    # Check if version is published
    if not version['published']:
        raise HTTPException(
            status_code=403,
            detail="This version is not published"
        )

    # Validate access for private versions
    validate_private_access(version, tenant_slug, x_api_key)

    # Get the specific class
    class_data = db.get_class_by_name(version['id'], class_name)

    if not class_data:
        raise HTTPException(
            status_code=404,
            detail=f"Class not found: {class_name}"
        )

    # Generate Arazzo specification for this class
    arazzo_spec = generate_class_arazzo_spec(
        tenant_slug,
        project_slug,
        version_slug,
        class_data
    )

    # Determine response format based on Accept header
    accept_header = (accept or "").lower()

    # Check for YAML preference
    if any(mime in accept_header for mime in ["application/yaml", "application/x-yaml", "text/yaml", "text/x-yaml"]):
        # Convert to YAML
        yaml_content = yaml.dump(arazzo_spec, sort_keys=False, default_flow_style=False)
        return Response(
            content=yaml_content,
            media_type="application/x-yaml",
            headers={
                "Content-Disposition": f'attachment; filename="{class_name}-workflow.yaml"'
            }
        )

    # Default to JSON
    return JSONResponse(content=arazzo_spec)


@app.get("/v1/json/{tenant_slug}/{project_slug}/{version_slug}")
async def get_version_jsonschema_spec(
    tenant_slug: str,
    project_slug: str,
    version_slug: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None, description="API key for private versions (alternative to X-API-Key header)"),
    accept: Optional[str] = Header(None)
) -> Response:
    """
    Get the complete JSON Schema specification for all classes in a version.
    Uses content negotiation to determine response format (JSON or YAML).

    Args:
        tenant_slug: The tenant slug
        project_slug: The project slug
        version_slug: The version ID (e.g., "1.0.0")
        x_api_key: Optional API key for private versions (header)
        api_key: Optional API key for private versions (query, for links)
        accept: Accept header for content negotiation

    Returns:
        JSON Schema specification in JSON or YAML format
    """
    # Get version information
    version = db.get_version_by_slugs(tenant_slug, project_slug, version_slug)

    if not version:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {tenant_slug}/{project_slug}/{version_slug}"
        )

    # Check if version is published
    if not version['published']:
        raise HTTPException(
            status_code=403,
            detail="This version is not published"
        )

    # Validate access for private versions (header or query param)
    validate_private_access(version, tenant_slug, x_api_key or api_key)

    # Get all classes for this version
    classes = db.get_classes_for_version(version['id'])

    # Get properties for each class
    all_properties = {}
    for class_data in classes:
        class_id = class_data['id']
        properties = db.get_properties_for_class(class_id)
        all_properties[class_id] = properties

    # Generate JSON Schema specification
    jsonschema_spec = generate_jsonschema_spec(
        tenant_slug,
        project_slug,
        version_slug,
        classes,
        all_properties,
        version.get('project_description')
    )

    # Determine response format based on Accept header
    accept_header = (accept or "").lower()

    # Check for YAML preference
    if any(mime in accept_header for mime in ["application/yaml", "application/x-yaml", "text/yaml", "text/x-yaml"]):
        # Convert to YAML
        yaml_content = yaml.dump(jsonschema_spec, sort_keys=False, default_flow_style=False)
        return Response(
            content=yaml_content,
            media_type="application/x-yaml",
            headers={
                "Content-Disposition": f'attachment; filename="{project_slug}-schema.yaml"'
            }
        )

    # Default to JSON
    return JSONResponse(content=jsonschema_spec)


@app.get("/v1/json/{tenant_slug}/{project_slug}/{version_slug}/{class_name}")
async def get_class_jsonschema_spec(
    tenant_slug: str,
    project_slug: str,
    version_slug: str,
    class_name: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    accept: Optional[str] = Header(None)
) -> Response:
    """
    Get the JSON Schema specification for a single class.
    Uses content negotiation to determine response format (JSON or YAML).

    Args:
        tenant_slug: The tenant slug
        project_slug: The project slug
        version_slug: The version ID (e.g., "1.0.0")
        class_name: The name of the class
        x_api_key: Optional API key for private versions
        accept: Accept header for content negotiation

    Returns:
        JSON Schema specification for the class in JSON or YAML format
    """
    # Get version information
    version = db.get_version_by_slugs(tenant_slug, project_slug, version_slug)

    if not version:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {tenant_slug}/{project_slug}/{version_slug}"
        )

    # Check if version is published
    if not version['published']:
        raise HTTPException(
            status_code=403,
            detail="This version is not published"
        )

    # Validate access for private versions
    validate_private_access(version, tenant_slug, x_api_key)

    # Get the specific class
    class_data = db.get_class_by_name(version['id'], class_name)

    if not class_data:
        raise HTTPException(
            status_code=404,
            detail=f"Class not found: {class_name}"
        )

    # Get properties for the class
    properties = db.get_properties_for_class(class_data['id'])

    # Generate JSON Schema specification for this class
    jsonschema_spec = generate_class_jsonschema_spec(
        tenant_slug,
        project_slug,
        version_slug,
        class_data,
        properties
    )

    # Determine response format based on Accept header
    accept_header = (accept or "").lower()

    # Check for YAML preference
    if any(mime in accept_header for mime in ["application/yaml", "application/x-yaml", "text/yaml", "text/x-yaml"]):
        # Convert to YAML
        yaml_content = yaml.dump(jsonschema_spec, sort_keys=False, default_flow_style=False)
        return Response(
            content=yaml_content,
            media_type="application/x-yaml",
            headers={
                "Content-Disposition": f'attachment; filename="{class_name}-schema.yaml"'
            }
        )

    # Default to JSON
    return JSONResponse(content=jsonschema_spec)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        # Try to connect to database
        db.connect()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}

