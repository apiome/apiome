from fastapi import FastAPI, HTTPException, Request, Response, Header, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.encoders import jsonable_encoder
from starlette.exceptions import HTTPException as StarletteHTTPException
from typing import Dict, Any, Optional
import asyncio
import json
import logging
import yaml

from .config import settings
from .database import db, Database
from .logging_config import configure_logging, get_logger
from .observability import ObservabilityMiddleware, build_error_envelope
from .ops_routes import health_router, ops_router
from .rate_limit import RateLimitMiddleware
from .openapi_generator import generate_openapi_spec, generate_class_openapi_spec
from .arazzo_generator import generate_arazzo_spec, generate_class_arazzo_spec
from .jsonschema_generator import generate_jsonschema_spec, generate_class_jsonschema_spec
from .models import OpenAPIResponse
from .primitives_routes import router as primitives_router
from .registry_audit_routes import router as registry_audit_router
from .type_namespaces_routes import router as type_namespaces_router
from .classes_routes import router as classes_router
from .projects_routes import router as projects_router
from .catalog_routes import router as catalog_router
from .identity_routes import router as identity_router
from .workflow_audit_routes import router as workflow_audit_router
from .versions_routes import router as versions_router
from .version_merge_routes import router as version_merge_router
from .properties_routes import router as properties_router
from .paths_routes import router as paths_router
from .data_routes import router as data_router
from .migration_plans_routes import router as migration_plans_router
from .version_tags_routes import router as version_tags_router
from .compatibility_routes import router as compatibility_router
from .lint_routes import router as lint_router
from .draft_lock_routes import router as draft_lock_router
from .push_webhook_delivery import process_due_push_webhook_deliveries
from .push_webhook_subscriptions_routes import router as push_webhook_subscriptions_router
from .mcp_credential_crypto import validate_credential_encryption_keys
from .push_webhook_crypto import validate_webhook_signing_key
from .change_report_routes import router as change_report_router
from .version_change_report_routes import router as version_change_report_router
from .change_report_template_routes import router as change_report_template_router
from .tenant_repositories_routes import router as tenant_repositories_router
from .tenants_session_routes import router as tenants_session_router
from .browse_public_routes import router as browse_public_router
from .browse_export_routes import router as browse_export_router
from .spec_import_routes import router as spec_import_router
from .import_sources_routes import router as import_sources_router
from .export_routes import router as export_router
from .export_job_routes import router as export_job_router
from .access_routes import router as access_router, platform_router as access_platform_router
from .mock_routes import router as mock_router, data_router as mock_data_router
from .mcp_catalog_routes import mcp_endpoints_router
from .mcp_badge_routes import router as mcp_badge_router
from .mcp_feed_routes import router as mcp_feed_router
from .mcp_catalog_digest_routes import router as mcp_catalog_digest_router
from .mcp_saved_search_routes import router as mcp_saved_search_router

# Configure structured JSON logging before anything else logs, so every line (including library
# loggers) is emitted in the consistent observability shape (RC1-3.2, #3617).
configure_logging(log_level=settings.effective_log_level, json_output=settings.log_json)

# Create FastAPI app
app = FastAPI(
    title="Apiome REST API",
    description="REST API for serving OpenAPI specifications from the Apiome database",
    version="1.0.65"
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

# Per-tenant rate limiting (#3612). Added before CORS so CORS ends up the
# outermost middleware and its headers are applied to 429 responses too.
app.add_middleware(RateLimitMiddleware)

# CORS allow-list is configuration-driven (APIOME_CORS_ALLOWED_ORIGINS /
# APIOME_CORS_ALLOWED_ORIGIN_REGEX) so production can lock origins down without a code
# change; defaults preserve local dev ports + *.apiome.app. See app/config.py.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_origin_regex=settings.effective_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Observability middleware is added last so it is the OUTERMOST layer (#3617): it assigns the
# request id and binds the structured-log context before any other middleware or handler runs, and
# observes the final status/latency of every response — including those produced by CORS and the
# rate limiter — for the metrics surface and access log.
app.add_middleware(ObservabilityMiddleware)

_error_log = get_logger("app.errors")


def _request_id_of(request: Request) -> Optional[str]:
    """Pull the correlation id the observability middleware stashed on the request (if any)."""
    return getattr(request.state, "request_id", None)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Wrap HTTP errors (404/403/401/4xx raised via HTTPException) in the consistent envelope.

    ``detail`` is preserved verbatim so existing clients/tests keep working; an ``error`` object and
    top-level ``request_id`` are added for uniform, diagnosable error reporting.
    """
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    envelope = build_error_envelope(
        status_code=exc.status_code,
        message=message,
        detail=exc.detail,
        error_type="http_error",
        request_id=_request_id_of(request),
    )
    return JSONResponse(status_code=exc.status_code, content=envelope, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return 422 validation errors in the consistent envelope, preserving FastAPI's ``detail`` list."""
    envelope = build_error_envelope(
        status_code=422,
        message="Request validation failed",
        detail=jsonable_encoder(exc.errors()),
        error_type="validation_error",
        request_id=_request_id_of(request),
    )
    return JSONResponse(status_code=422, content=envelope)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: log the full exception with its request id and return a safe 500 envelope.

    This is the "error tracking" half of observability — an unexpected failure is logged with a
    stack trace correlated to the ``request_id`` (so it is diagnosable from logs), while the client
    receives a generic message that never leaks internal details.
    """
    request_id = _request_id_of(request)
    _error_log.bind(request_id=request_id).exception(
        "unhandled_exception", path=request.url.path, method=request.method
    )
    envelope = build_error_envelope(
        status_code=500,
        message="Internal server error",
        detail="Internal server error",
        error_type="internal_error",
        request_id=request_id,
    )
    # An unhandled exception propagates past the observability middleware, so its header injection is
    # skipped — set the correlation header here so the 500 response still carries it (the middleware
    # already set it on every non-500 response).
    headers = {settings.request_id_header: request_id} if request_id else None
    return JSONResponse(status_code=500, content=envelope, headers=headers)

# Include routers (browse_public_router first for unauthenticated /v1/browse/* routes;
# data_router next so /v1/data/* is matched before any generic patterns)
app.include_router(browse_public_router)
# mcp_badge_router: anonymous public SVG status badges at /mcp/badge/* (unauthenticated, like browse).
app.include_router(mcp_badge_router)
# mcp_feed_router: anonymous public RSS/Atom/JSON change feeds at /mcp/feed/* (unauthenticated, like browse).
app.include_router(mcp_feed_router)
app.include_router(browse_export_router)
app.include_router(data_router)
# registry_audit_router before primitives_router so its literal /{tenant_slug}/audit route is
# matched ahead of the primitives /{tenant_slug}/{primitive_id} catch-all (#3481).
app.include_router(registry_audit_router)
app.include_router(primitives_router)
app.include_router(type_namespaces_router)
app.include_router(classes_router)
app.include_router(projects_router)
app.include_router(catalog_router)
app.include_router(identity_router)
app.include_router(compatibility_router)
app.include_router(lint_router)
app.include_router(version_merge_router)
app.include_router(workflow_audit_router)
app.include_router(versions_router)
app.include_router(properties_router)
app.include_router(paths_router)
app.include_router(migration_plans_router)
app.include_router(version_tags_router)
app.include_router(draft_lock_router)
app.include_router(push_webhook_subscriptions_router)
app.include_router(change_report_router)
app.include_router(version_change_report_router)
app.include_router(change_report_template_router)
app.include_router(tenants_session_router)
app.include_router(spec_import_router)
app.include_router(import_sources_router)
# Multi-format export (MFX-2.5, #3842): tenant-scoped fidelity report surfacing — per-target
# fidelity badges (/export/{tenant}/targets) and the dry-run preview (/export/{tenant}/preview).
app.include_router(export_router)
app.include_router(export_job_router)
app.include_router(tenant_repositories_router)
app.include_router(access_router)
app.include_router(access_platform_router)
# Mock Server (#3615): tenant-scoped management plane, then the public data plane catch-all.
app.include_router(mock_router)
app.include_router(mock_data_router)
# MCP Catalog (#3663): tenant-scoped CRUD over registered external MCP endpoints.
app.include_router(mcp_endpoints_router)
app.include_router(mcp_catalog_digest_router)
app.include_router(mcp_saved_search_router)
# Observability & ops (#3617): liveness/readiness probes + platform-admin ops dashboard.
app.include_router(health_router)
app.include_router(ops_router)


_webhook_delivery_task: asyncio.Task | None = None
_repository_file_scan_task: asyncio.Task | None = None
_repository_refresh_task: asyncio.Task | None = None
_mcp_discovery_task: asyncio.Task | None = None
_mcp_catalog_digest_task: asyncio.Task | None = None


@app.on_event("startup")
async def startup_event():
    """Connect to database on startup."""
    db.connect()
    _startup_log = logging.getLogger("uvicorn.error")
    # Fail fast in production if the JWT secret is missing (refuses the insecure default).
    settings.effective_jwt_secret
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
    validate_credential_encryption_keys()

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

    async def _repository_file_scan_sweep() -> None:
        log = logging.getLogger(__name__)
        while True:
            await asyncio.sleep(5)
            try:

                def _run_scan() -> int:
                    thread_db = Database()
                    try:
                        from .repository_file_scan import process_next_repository_file_scan_job

                        return process_next_repository_file_scan_job(thread_db)
                    finally:
                        thread_db.close()

                await asyncio.to_thread(_run_scan)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("repository file scan sweep")

    async def _repository_refresh_sweep() -> None:
        """Periodically enqueue spec-faithful re-imports for stale files (RAR-3.2).

        Ticks on the configured refresh floor (``APIOME_REFRESH_MIN_INTERVAL``,
        default 60s) and lets the per-repo cadence + due-selection in
        ``list_due_repositories`` decide which repositories are actually processed
        each tick, so the cheap floor cadence here never refreshes a repo more
        often than its own ``refresh_interval_seconds`` allows.
        """
        from .config import settings

        log = logging.getLogger(__name__)
        tick_seconds = max(1, int(settings.refresh_min_interval_seconds))
        while True:
            await asyncio.sleep(tick_seconds)
            try:

                def _run_refresh() -> int:
                    thread_db = Database()
                    try:
                        from .repository_refresh_sweep import (
                            process_repository_refresh_sweep,
                        )

                        return process_repository_refresh_sweep(thread_db)
                    finally:
                        thread_db.close()

                await asyncio.to_thread(_run_refresh)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("repository refresh sweep")

    async def _mcp_discovery_sweep() -> None:
        """Periodically re-discover MCP catalog endpoints on their cadence (MCAT-5.1/5.2).

        Ticks on the configured floor (``APIOME_MCP_DISCOVERY_MIN_INTERVAL``, default 60s)
        and lets the per-endpoint cadence + due-selection in ``list_due_mcp_endpoints`` decide
        which endpoints are actually re-discovered each tick, so the cheap floor cadence here
        never re-discovers an endpoint more often than its own cadence allows. Unlike the other
        sweeps the discovery pipeline is natively async (the MCP client is asyncio), so the tick
        runs on the event loop and ``process_mcp_discovery_sweep`` pushes only its blocking DB
        writes to worker threads. Each tick runs the due endpoints under a concurrency cap and a
        per-endpoint timeout (MCAT-5.2) and awaits them, so a tick can outlast the floor; the
        next tick simply starts after it drains (enqueue dedup prevents any double-run).
        """
        from .config import settings

        log = logging.getLogger(__name__)
        tick_seconds = max(1, int(settings.mcp_discovery_min_interval_seconds))
        while True:
            await asyncio.sleep(tick_seconds)
            try:
                from .mcp_discovery_sweep import process_mcp_discovery_sweep

                # The due-selection read runs on a dedicated connection (like the other
                # sweeps) so it never contends with request handlers on the shared `db`.
                # The dispatched discovery runs use the engine's own (global) handle.
                thread_db = Database()
                try:
                    await process_mcp_discovery_sweep(thread_db)
                finally:
                    thread_db.close()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("mcp discovery sweep")

    async def _mcp_catalog_digest_sweep() -> None:
        """Periodically compile and deliver per-tenant catalog digests (MCAT-19.5).

        Ticks on the configured floor (``APIOME_MCP_DIGEST_MIN_INTERVAL``, default 300s) and lets
        the per-tenant cadence + due-selection in ``list_due_mcp_catalog_digests`` decide which
        tenants actually receive a digest each tick, so the cheap floor cadence here never sends a
        tenant a digest more often than its own cadence allows. Runs on a dedicated DB connection
        (like the other sweeps) so its advisory locks and reads never contend with request handlers.
        """
        from .config import settings

        log = logging.getLogger(__name__)
        tick_seconds = max(1, int(settings.mcp_digest_min_interval_seconds))
        while True:
            await asyncio.sleep(tick_seconds)
            try:

                def _run_digest() -> int:
                    thread_db = Database()
                    try:
                        from .mcp_catalog_digest_sweep import (
                            process_mcp_catalog_digest_sweep,
                        )

                        return process_mcp_catalog_digest_sweep(thread_db)
                    finally:
                        thread_db.close()

                await asyncio.to_thread(_run_digest)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("mcp catalog digest sweep")

    global _webhook_delivery_task
    _webhook_delivery_task = asyncio.create_task(_webhook_delivery_sweep())
    global _repository_file_scan_task
    _repository_file_scan_task = asyncio.create_task(_repository_file_scan_sweep())
    global _repository_refresh_task
    _repository_refresh_task = asyncio.create_task(_repository_refresh_sweep())
    global _mcp_discovery_task
    _mcp_discovery_task = asyncio.create_task(_mcp_discovery_sweep())
    global _mcp_catalog_digest_task
    _mcp_catalog_digest_task = asyncio.create_task(_mcp_catalog_digest_sweep())


@app.on_event("shutdown")
async def shutdown_event():
    """Close database connection on shutdown."""
    global _webhook_delivery_task
    if _webhook_delivery_task is not None:
        _webhook_delivery_task.cancel()
        try:
            await _webhook_delivery_task
        except asyncio.CancelledError:
            pass
        _webhook_delivery_task = None
    global _repository_file_scan_task
    if _repository_file_scan_task is not None:
        _repository_file_scan_task.cancel()
        try:
            await _repository_file_scan_task
        except asyncio.CancelledError:
            pass
        _repository_file_scan_task = None
    global _repository_refresh_task
    if _repository_refresh_task is not None:
        _repository_refresh_task.cancel()
        try:
            await _repository_refresh_task
        except asyncio.CancelledError:
            pass
        _repository_refresh_task = None
    global _mcp_discovery_task
    if _mcp_discovery_task is not None:
        _mcp_discovery_task.cancel()
        try:
            await _mcp_discovery_task
        except asyncio.CancelledError:
            pass
        _mcp_discovery_task = None
    global _mcp_catalog_digest_task
    if _mcp_catalog_digest_task is not None:
        _mcp_catalog_digest_task.cancel()
        try:
            await _mcp_catalog_digest_task
        except asyncio.CancelledError:
            pass
        _mcp_catalog_digest_task = None
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
        "message": "Apiome REST API",
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
                "health": "/v1/primitives/health",
                "list": "/v1/primitives/{tenant-slug}",
                "get": "/v1/primitives/{tenant-slug}/{primitive-id}",
                "create": "POST /v1/primitives/{tenant-slug}",
                "update": "PUT /v1/primitives/{tenant-slug}/{primitive-id}",
                "delete": "DELETE /v1/primitives/{tenant-slug}/{primitive-id}",
                "import": "POST /v1/primitives/{tenant-slug}/import"
            },
            "type_namespaces": {
                "list": "/v1/types/{tenant-slug}/namespaces",
                "create": "POST /v1/types/{tenant-slug}/namespaces",
                "update": "PUT /v1/types/{tenant-slug}/namespaces/{namespace-id}"
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
        project_metadata=version.get('project_metadata'),
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
        project_metadata=version.get('project_metadata'),
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

