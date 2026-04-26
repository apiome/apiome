from fastapi import FastAPI, HTTPException, Response, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.openapi.docs import get_swagger_ui_html
from typing import Dict, Any, Optional
import asyncio
import json
import logging
import os
import yaml

from .database import db, Database
from .openapi_generator import generate_openapi_spec, generate_class_openapi_spec
from .arazzo_generator import generate_arazzo_spec, generate_class_arazzo_spec
from .jsonschema_generator import generate_jsonschema_spec, generate_class_jsonschema_spec
from .models import OpenAPIResponse
from .primitives_routes import router as primitives_router
from .classes_routes import router as classes_router
from .projects_routes import router as projects_router
from .workflow_audit_routes import router as workflow_audit_router
from .versions_routes import router as versions_router
from .version_merge_routes import router as version_merge_router
from .properties_routes import router as properties_router
from .paths_routes import router as paths_router
from .data_routes import router as data_router
from .migration_plans_routes import router as migration_plans_router
from .version_tags_routes import router as version_tags_router
from .version_quality_routes import router as version_quality_router
from .version_lint_routes import router as version_lint_router
from . import lint_rules as _lint_rules  # noqa: F401  (registers v1 lint rules)
from .compatibility_routes import router as compatibility_router
from .draft_lock_routes import router as draft_lock_router
from .push_webhook_delivery import process_due_push_webhook_deliveries
from .push_webhook_subscriptions_routes import router as push_webhook_subscriptions_router
from .push_webhook_crypto import validate_webhook_signing_key
from .change_report_routes import router as change_report_router
from .version_change_report_routes import router as version_change_report_router
from .change_report_template_routes import router as change_report_template_router
from .repositories_routes import process_pending_repository_scans, router as repositories_router

# Create FastAPI app
app = FastAPI(
    title="Objectified REST API",
    description="REST API for serving OpenAPI specifications from the Objectified database",
    version="1.0.44"
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

# Include routers (data_router first so /v1/data/* is matched before any generic patterns)
app.include_router(data_router)
app.include_router(primitives_router)
app.include_router(classes_router)
app.include_router(projects_router)
app.include_router(compatibility_router)
app.include_router(version_merge_router)
app.include_router(workflow_audit_router)
app.include_router(versions_router)
app.include_router(properties_router)
app.include_router(paths_router)
app.include_router(migration_plans_router)
app.include_router(version_tags_router)
app.include_router(version_quality_router)
app.include_router(version_lint_router)
app.include_router(draft_lock_router)
app.include_router(push_webhook_subscriptions_router)
app.include_router(change_report_router)
app.include_router(version_change_report_router)
app.include_router(change_report_template_router)
app.include_router(repositories_router)


_webhook_delivery_task: asyncio.Task | None = None
_repository_scan_worker_task: asyncio.Task | None = None


@app.on_event("startup")
async def startup_event():
    """Connect to database on startup."""
    db.connect()
    _startup_log = logging.getLogger("uvicorn.error")
    try:
        db.ensure_system_change_report_template()
    except Exception as e:
        # Distinguish "schema not yet migrated" (expected pre-migration) from
        # unexpected failures (permissions, connectivity, etc.).
        _err_str = str(e).lower()
        _schema_not_migrated = any(
            token in _err_str
            for token in ("undefined table", "does not exist", "undefinedtable", "42p01")
        )
        if _schema_not_migrated:
            _startup_log.warning(
                "change report system template seed skipped: migration 20260414-150000.sql "
                "has not been applied — project and template endpoints require that migration: %s",
                e,
            )
        else:
            _startup_log.exception(
                "change report system template seed failed with unexpected error: %s", e
            )
    validate_webhook_signing_key()
    # Log data API routes so we can confirm POST /v1/data/{tenant_slug}/records is registered
    for route in app.routes:
        if hasattr(route, "path") and "data" in route.path and hasattr(route, "methods"):
            logging.getLogger("uvicorn.error").info("Registered data route: %s %s", list(route.methods), route.path)

    async def _webhook_delivery_sweep() -> None:
        log = logging.getLogger(__name__)
        while True:
            await asyncio.sleep(15)
            try:
                def _run_in_thread() -> int:
                    """Run delivery with a dedicated, thread-local DB connection."""
                    thread_db = Database()
                    try:
                        return process_due_push_webhook_deliveries(thread_db)
                    finally:
                        thread_db.close()

                await asyncio.to_thread(_run_in_thread)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("push webhook delivery sweep")

    global _webhook_delivery_task
    _webhook_delivery_task = asyncio.create_task(_webhook_delivery_sweep())

    async def _repository_scan_worker_loop() -> None:
        log = logging.getLogger(__name__)
        while True:
            await asyncio.sleep(2)
            try:
                drained = process_pending_repository_scans()
                if drained > 0:
                    log.info("Processed %s pending repository scans", drained)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("repository scan worker loop")

    # Keep deterministic unit tests by disabling the worker under pytest.
    if "PYTEST_CURRENT_TEST" not in os.environ:
        global _repository_scan_worker_task
        _repository_scan_worker_task = asyncio.create_task(_repository_scan_worker_loop())


@app.on_event("shutdown")
async def shutdown_event():
    """Close database connection on shutdown."""
    global _webhook_delivery_task
    global _repository_scan_worker_task
    if _webhook_delivery_task is not None:
        _webhook_delivery_task.cancel()
        try:
            await _webhook_delivery_task
        except asyncio.CancelledError:
            pass
        _webhook_delivery_task = None
    if _repository_scan_worker_task is not None:
        _repository_scan_worker_task.cancel()
        try:
            await _repository_scan_worker_task
        except asyncio.CancelledError:
            pass
        _repository_scan_worker_task = None
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
        version_db_id=version['id'],  # Pass version database ID to load paths
        revision_metadata=version.get('metadata'),
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
        version_db_id=version['id'],  # Pass version database ID to load paths
        revision_metadata=version.get('metadata'),
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

