import asyncio
import io
import json
import logging
from typing import Any, Dict, Optional

import yaml
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .access_routes import platform_router as access_platform_router
from .access_routes import router as access_router
from .agent_key_routes import router as agent_key_router
from .cli_login_routes import router as cli_login_router
from .agent_toolset_routes import router as agent_toolset_router
from .agent_invocation_export_routes import router as agent_invocation_export_router
from .agent_usage_routes import router as agent_usage_router
from .api_check_suite_routes import router as api_check_suite_router
from .arazzo_generator import generate_arazzo_spec, generate_class_arazzo_spec
from .arazzo_spec import ArazzoVersionError
from .auth_provider_config_routes import router as auth_provider_config_router
from .auth_provider_resolved_routes import router as auth_provider_resolved_router
from .internal_auth_event_routes import router as internal_auth_event_router
from .sso_provider_routes import admin_router as sso_provider_admin_router
from .sso_provider_routes import internal_router as sso_provider_internal_router
from .tenant_sso_routes import router as tenant_sso_router
from .auth_provider_secret_crypto import validate_auth_config_encryption_keys
from .avro_registry_push_routes import router as avro_registry_push_router
from .schema_registry_push_routes import router as schema_registry_push_router
from .browse_agentic_routes import router as browse_agentic_router
from .xregistry_routes import router as xregistry_router
from .browse_export_routes import router as browse_export_router
from .browse_public_routes import router as browse_public_router
from .bulk_import_routes import router as bulk_import_router
from .catalog_connector_routes import router as catalog_connector_router
from .catalog_agent_routes import router as catalog_agent_router
from .catalog_entity_routes import router as catalog_entity_router
from .catalog_drift_routes import router as catalog_drift_router
from .url_import_routes import router as url_import_router
from .import_original_routes import router as import_original_router
from .catalog_refresh_routes import router as catalog_refresh_router
from .catalog_routes import router as catalog_router
from .catalog_upload_routes import router as catalog_upload_router
from .model_search_routes import router as model_search_router
from .change_report_routes import router as change_report_router
from .change_report_enterprise_routes import audit_router as change_report_audit_router
from .change_report_enterprise_routes import router as change_report_enterprise_router
from .change_report_template_routes import router as change_report_template_router
from .classes_routes import router as classes_router
from .classified_diff_routes import router as classified_diff_router
from .comment_routes import router as comment_router
from .presence_routes import router as presence_router
from .review_suggestion_routes import router as review_suggestion_router
from .merge_request_routes import router as merge_request_router
from .compatibility_routes import router as compatibility_router
from .compatibility_rules_routes import router as compatibility_rules_router
from .config import settings
from .consumer_contract_routes import router as consumer_contract_router
from .consumer_pact_export_routes import router as consumer_pact_export_router
from .consumer_binding_routes import router as consumer_binding_router
from .consumption_index_routes import router as consumption_index_router
from .contract_runner_routes import router as contract_runner_router
from .contract_suite_routes import router as contract_suite_router
from .database import ConnectionPoolExhausted, StatementTimeout, db
from .sweep_runtime import async_sweep_tick, close_sweep_databases, sweep_database, sweep_tick
from .request_threads import configure_request_thread_pool
from .deploy_gate_routes import router as deploy_gate_router
from .deploy_gate_routes import tenant_router as deploy_gate_tenant_router
from .domains_routes import router as domains_router
from .draft_binding_routes import router as draft_binding_router
from .draft_lock_routes import router as draft_lock_router
from .version_overlay_routes import router as version_overlay_router
from .project_references_routes import router as project_references_router
from .entity_owner_routes import router as entity_owner_router
from .export_job_routes import router as export_job_router
from .export_mock_routes import router as export_mock_router
from .export_tool_check_routes import router as export_tool_check_router
from .export_routes import router as export_router
from .export_routes import tenant_router as export_tenant_router
from .format_matrix_routes import router as format_matrix_router
from .git_import_routes import router as git_import_router
from .gateway_config_routes import router as gateway_config_router
from .catalog_migration_routes import router as catalog_migration_router
from .graph_routes import router as graph_router
from .identity_routes import router as identity_router
from .import_sources_routes import router as import_sources_router
from .postman_convert_routes import router as postman_convert_router
from .jsonschema_generator import generate_class_jsonschema_spec, generate_jsonschema_spec
from .license_routes import router as license_router
from .linked_account_token_crypto import validate_linked_account_token_keys
from .lint_routes import decisions_router as lint_decisions_router
from .lint_routes import router as lint_router
from .lint_routes import rules_router as lint_rules_router
from .lint_fix_routes import plan_router as lint_fix_plan_router
from .lint_fix_routes import router as lint_fix_router
from .overlay_lint_routes import router as overlay_lint_router
from .lint_workspace_routes import router as lint_workspace_router
from .logging_config import configure_logging, get_logger
from .mcp_badge_routes import router as mcp_badge_router
from .mcp_catalog_digest_routes import router as mcp_catalog_digest_router
from .mcp_catalog_routes import mcp_endpoints_router
from .mcp_collection_routes import router as mcp_collection_router
from .mcp_credential_crypto import validate_credential_encryption_keys
from .mcp_endpoint_note_routes import router as mcp_endpoint_note_router
from .mcp_categorization_routes import router as mcp_categorization_router
from .mcp_feed_routes import router as mcp_feed_router
from .mcp_registry_routes import registry_router as mcp_registry_alias_router
from .mcp_registry_routes import router as mcp_registry_router
from .schema_registry_routes import router as schema_registry_router
from .schema_registry_confluent_routes import ConfluentRegistryError, confluent_error_handler
from .schema_registry_confluent_routes import router as schema_registry_confluent_router
from .mcp_key_routes import router as mcp_key_router
from .mcp_manifest_routes import router as mcp_manifest_router
from .mcp_policy_routes import router as mcp_policy_router
from .mcp_probe_routes import router as mcp_probe_router
from .mcp_saved_search_routes import router as mcp_saved_search_router
from .mcp_tool_routes import router as mcp_tool_router
from .mcp_trust_baseline_routes import router as mcp_trust_baseline_router
from .mock_routes import data_router as mock_data_router
from .mock_routes import router as mock_router
from .notification_routes import router as notification_router
from .observability import ObservabilityMiddleware, build_error_envelope
from .onboarding_routes import router as onboarding_router
from .openapi_enrichment import enrich_openapi_spec
from .openapi_generator import generate_class_openapi_spec
from .ops_routes import health_router, ops_router
from .document_migration_routes import router as document_migration_router
from .document_store_health import initialize_document_store
from .document_store_router import refresh_routing as refresh_document_store_routing
from .document_store_routes import admin_router as document_store_admin_router
from .document_store_routes import ops_router as document_store_ops_router
from .ownership_policy_routes import router as ownership_policy_router
from .pact_broker_compat_routes import fallback_router as pact_broker_fallback_router
from .pact_broker_compat_routes import router as pact_broker_compat_router
from .pact_broker_environment_routes import router as pact_broker_environment_router
from .pact_broker_host import PactBrokerHostAliasMiddleware
from .pact_broker_matrix_routes import router as pact_broker_matrix_router
from .pact_broker_routes import router as pact_broker_router
from .pact_broker_verification_routes import router as pact_broker_verification_router
from .pact_comparison_routes import router as pact_comparison_router
from .pact_webhook_delivery_routes import router as pact_webhook_delivery_router
from .pact_deployment_routes import router as pact_deployment_router
from .pact_postman_routes import router as pact_postman_router
from .pact_suite_routes import router as pact_suite_router
from .pact_remediation_routes import router as pact_remediation_router
from .pact_health_routes import router as pact_health_router
from .pact_secret_routes import router as pact_secret_router
from .pact_verification_ops_routes import router as pact_verification_ops_router
from .pact_verifier_routes import router as pact_verifier_router
from .pact_provider_state_routes import router as pact_provider_state_router
from .pact_broker_webhook_routes import router as pact_broker_webhook_router
from .pact_badge_routes import router as pact_badge_router
from .pact_broker_cleanup_routes import router as pact_broker_cleanup_router
from .pact_retention_routes import router as pact_retention_router
from .pact_commit_status_routes import router as pact_commit_status_router
from .pacticipant_routes import router as pacticipant_router
from .provider_contract_routes import router as provider_contract_router
from .paths_routes import router as paths_router
from .preservation_routes import router as preservation_router
from .primitives_lifecycle_routes import router as primitives_lifecycle_router
from .primitives_routes import router as primitives_router
from .project_repository_sources_routes import router as project_repository_sources_router
from .pr_back_routes import router as pr_back_router
from .repository_federation_routes import router as repository_federation_router
from .project_tags_routes import router as project_tags_router
from .projects_routes import router as projects_router
from .properties_routes import router as properties_router
from .provider_check_routes import router as provider_check_router
from .provider_verification_routes import router as provider_verification_router
from .public_types_routes import router as public_types_router
from .push_webhook_crypto import validate_webhook_signing_key
from .component_library_routes import router as component_library_router
from .component_governance_routes import router as component_governance_router
from .push_webhook_delivery import process_due_push_webhook_deliveries
from .push_webhook_subscriptions_routes import router as push_webhook_subscriptions_router
from .quality_policy_routes import router as quality_policy_router
from .rate_limit import RateLimitMiddleware
from .registry_audit_routes import router as registry_audit_router
from .repository_webhook_routes import router as repository_webhook_router
from .review_routes import router as review_router
from .schema_suite_routes import router as schema_suite_router
from .schema_synthesis_routes import router as schema_synthesis_router
from .schema_targets_routes import router as schema_targets_router
from .schema_validation_routes import router as schema_validation_router
from .scoped_catalog_routes import router as scoped_catalog_router
from .scrub_policy_routes import router as scrub_policy_router
from .sdk_generation_settings_routes import router as sdk_generation_settings_router
from .sdk_generation_settings_routes import (
    tenant_router as sdk_generation_settings_tenant_router,
)
from .sdk_git_delivery_routes import router as sdk_git_delivery_router
from .export_git_delivery_routes import router as export_git_delivery_router
from .export_run_routes import router as export_run_router
from .export_webhook_delivery_pipeline import process_due_export_webhook_deliveries
from .export_webhook_delivery_routes import router as export_webhook_delivery_router
from .export_object_storage_delivery_routes import router as export_object_storage_delivery_router
from .export_delivery_profile_routes import router as export_delivery_profile_router
from .export_preset_routes import router as export_preset_router
from .export_auto_routes import router as export_auto_router
from .mcp_export_routes import router as mcp_export_router
from .mcp_pact_routes import router as mcp_pact_router
from .sdk_kit_routes import router as sdk_kit_router
from .sdk_publish_routes import router as sdk_publish_router
from .sdk_publish_routes import tenant_router as sdk_publish_tenant_router
from .sdk_regen_routes import router as sdk_regen_router
from .sdk_registry_credentials import validate_registry_credential_keys
from .shadow_api_routes import router as shadow_api_router
from .signup_policy_routes import router as signup_policy_router
from .portal_auth_routes import router as portal_auth_router
from .consumer_feedback_routes import router as consumer_feedback_router
from .sdk_beacon_routes import router as sdk_beacon_router
from .sdk_compat_routes import router as sdk_compat_router
from .slate_agent_outputs_routes import router as slate_agent_outputs_router
from .slate_cache_routes import router as slate_cache_router
from .slate_cdn_routes import router as slate_cdn_router
from .slate_domains_routes import router as slate_domains_router
from .slate_functions_routes import router as slate_functions_router
from .slate_git_preview_routes import router as slate_git_preview_router
from .slate_insights_routes import router as slate_insights_router
from .slate_routes import router as slate_router
from .slate_security_routes import router as slate_security_router
from .snippet_routes import browse_router as snippet_browse_router
from .snippet_routes import versions_router as snippet_versions_router
from .source_review_routes import router as source_review_router
from .source_provenance_routes import router as source_provenance_router
from .spec_import_routes import router as spec_import_router
from .rendered_documents import (
    KIND_OPENAPI,
    etag_for,
    etag_matches,
    iter_stream,
    open_frozen_schema,
    rendered_document,
    revision_openapi,
)
from .spec_sync_routes import router as spec_sync_router
from .style_guide_routes import router as style_guide_router
from .team_routes import router as team_router
from .api_product_routes import router as api_product_router
from .api_plan_routes import router as api_plan_router
from .tenant_repositories_routes import router as tenant_repositories_router
from .tenants_session_routes import router as tenants_session_router
from .toolchain_selfcheck import enforce_toolchain_selfcheck
from .two_factor_policy_routes import router as two_factor_policy_router
from .tenant_document_store import TenantDocumentStoreUnavailable
from .tenant_document_store_routes import router as tenant_document_store_router
from .tenant_document_store_routes import tenant_store_unavailable_handler
from .two_factor_reset_routes import admin_router as two_factor_reset_admin_router
from .two_factor_reset_routes import member_router as two_factor_reset_member_router
from .type_namespaces_routes import router as type_namespaces_router
from .unowned_findings_routes import router as unowned_findings_router
from .upstream_credential_routes import router as upstream_credential_router
from .upstream_credentials import validate_upstream_credential_keys
from .mock_broker_binding_routes import router as mock_broker_binding_router
from .mock_broker_bindings import validate_broker_credential_keys
from .slate_cdn_crypto import validate_slate_cdn_credential_keys
from .usage_ingest_routes import router as usage_ingest_router
from .usage_source_routes import router as usage_source_router
from .usage_controls_routes import router as usage_controls_router
from .verification_evidence_routes import router as verification_evidence_router
from .verification_policy_routes import router as verification_policy_router
from .verification_schedule_routes import router as verification_schedule_router
from .verification_target_routes import router as verification_target_router
from .probe_consent_routes import router as probe_consent_router
from .version_change_report_routes import router as version_change_report_router
from .version_changelog_routes import router as version_changelog_router
from .version_document_routes import router as version_document_router
from .version_original_routes import router as version_original_router
from .version_merge_routes import router as version_merge_router
from .revision_graph_routes import router as revision_graph_router
from .project_timeline_routes import router as project_timeline_router
from .version_tags_routes import router as version_tags_router
from .versions_routes import router as versions_router
from .workflow_audit_routes import router as workflow_audit_router
from .arazzo_workflow_routes import router as arazzo_workflow_router
from .openapi_upgrade_routes import router as openapi_upgrade_router
from .workspace_custom_action_routes import router as workspace_custom_action_router
from .workspace_property_routes import router as workspace_property_router
from .workspace_summary_routes import router as workspace_summary_router

# Configure structured JSON logging before anything else logs, so every line (including library
# loggers) is emitted in the consistent observability shape (RC1-3.2, #3617).
configure_logging(log_level=settings.effective_log_level, json_output=settings.log_json)

# Create FastAPI app
app = FastAPI(
    title="Apiome REST API",
    description=(
        "REST API for managing tenants, projects, versions, primitives, classes, paths, operations, "
        "catalog items, imports, exports, governance, and MCP catalog surfaces."
    ),
    version="1.649.0",
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
    openapi_schema = enrich_openapi_spec(openapi_schema)
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

# Per-tenant rate limiting (#3612). Added before CORS so CORS ends up the
# outermost middleware and its headers are applied to 429 responses too.
app.add_middleware(RateLimitMiddleware)

# CORS allow-list is configuration-driven (APIOME_CORS_ALLOWED_ORIGINS /
# APIOME_CORS_ALLOWED_ORIGIN_REGEX) so production can lock origins down without a code
# change; defaults preserve local dev ports + *.apiome.dev. See app/config.py.
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

# The Pact Broker tenant-host alias (PFX-1.2, #6915) rewrites ``<tenant>.<suffix>/<path>`` onto
# ``/v1/tenants/<tenant>/pact-broker/<path>``. It is added after everything else so it runs first:
# the access log, the rate limiter and the router all see the real path. A no-op unless
# ``APIOME_PACT_BROKER_HOST_SUFFIX`` is set.
app.add_middleware(PactBrokerHostAliasMiddleware)

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


def _database_busy_response(request: Request, *, message: str, error_type: str, exc: Exception) -> JSONResponse:
    """A ``503`` envelope with ``Retry-After`` for a database that is busy rather than broken."""
    request_id = _request_id_of(request)
    _error_log.bind(request_id=request_id).warning(error_type, path=request.url.path, error=str(exc)[:200])
    envelope = build_error_envelope(
        status_code=503, message=message, detail=message, error_type=error_type, request_id=request_id
    )
    headers = {"Retry-After": "5"}
    if request_id:
        headers[settings.request_id_header] = request_id
    return JSONResponse(status_code=503, content=envelope, headers=headers)


@app.exception_handler(StatementTimeout)
async def statement_timeout_handler(request: Request, exc: StatementTimeout) -> JSONResponse:
    """A statement ran past ``DB_STATEMENT_TIMEOUT_MS`` (DBP-1.2, #7185): ``503 statement_timeout``."""
    return _database_busy_response(
        request,
        message="The database took too long to answer this request. Try again shortly.",
        error_type="statement_timeout",
        exc=exc,
    )


@app.exception_handler(ConnectionPoolExhausted)
async def connection_pool_exhausted_handler(request: Request, exc: ConnectionPoolExhausted) -> JSONResponse:
    """Every allowed connection is in use (``DB_POOL_MAX_IN_USE``, DBP-1.2): ``503 database_busy``."""
    return _database_busy_response(
        request,
        message="The service is at its database connection limit. Try again shortly.",
        error_type="database_busy",
        exc=exc,
    )


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

# Include routers (browse_public_router first for unauthenticated /v1/browse/* routes)
app.include_router(browse_public_router)
app.include_router(browse_agentic_router)
app.include_router(xregistry_router)
# public_types_router: anonymous dereference of a registry $id at /types/* (unauthenticated). Serves
# only is_system AND is_public rows, so the std/* core set and nothing a tenant owns.
app.include_router(public_types_router)
# mcp_badge_router: anonymous public SVG status badges at /mcp/badge/* (unauthenticated, like browse).
app.include_router(mcp_badge_router)
# mcp_feed_router: anonymous public RSS/Atom/JSON change feeds at /mcp/feed/* (unauthenticated, like browse).
app.include_router(mcp_feed_router)
# mcp_registry_router: MCP Registry API v0.1 at /v1/tenants/{t}/mcp-registry/* — anonymous public
# slice, widened to private entries by a tenant credential (AAU-5.3, #5724).
app.include_router(mcp_registry_router)
# mcp_registry_alias_router: the same routes at /registry/mcp/{t}/v0.1/* (CDG-4.1, #5973).
app.include_router(mcp_registry_alias_router)
# schema_registry_router: schema subjects, ids and versions at /v1/tenants/{t}/schema-registry/* (CDG-4.2, #5974).
app.include_router(schema_registry_router)
# schema_registry_confluent_router: the Confluent-compatible schema registry at /registry/schema/{t}/* (CDG-4.3, #5975).
app.include_router(schema_registry_confluent_router)
app.add_exception_handler(ConfluentRegistryError, confluent_error_handler)
app.include_router(browse_export_router)
app.include_router(snippet_browse_router)
app.include_router(sdk_kit_router)
# registry_audit_router before primitives_router so its literal /{tenant_slug}/audit route is
# matched ahead of the primitives /{tenant_slug}/{primitive_id} catch-all (#3481).
app.include_router(registry_audit_router)
app.include_router(primitives_router)
# Deprecate / restore a type (#3482): /{tenant_slug}/{primitive_id}/deprecate.
app.include_router(primitives_lifecycle_router)
app.include_router(type_namespaces_router)
app.include_router(classes_router)
app.include_router(projects_router)
# deploy_gate_router shares the `/v1/projects` prefix and is registered *after* it, so
# `/{tenant}/by-slug/{project_slug}` still wins for a project whose slug is literally `gate`
# (CTG-4.5, #4502). Nothing else in projects_routes matches three segments ending in a literal.
app.include_router(deploy_gate_router)
# sdk_generation_settings_router shares the `/v1/projects` prefix for the same reason and is
# registered after it too, so `/{tenant}/by-slug/{project_slug}` still wins for a project
# slugged `sdk-settings` (SDK-3.4, #4494).
app.include_router(sdk_generation_settings_router)
# sdk_publish_router shares the `/v1/projects` prefix for the same reason and is registered
# after it too, so `/{tenant}/by-slug/{project_slug}` still wins for a project slugged
# `sdk-publish` or `sdk-registry-credentials` (SDK-4.1, #4495).
app.include_router(sdk_publish_router)
# sdk_git_delivery_router shares the `/v1/projects` prefix for the same reason and is registered
# after it too, so `/{tenant}/by-slug/{project_slug}` still wins for a project slugged
# `sdk-git-delivery` or `sdk-git-delivery-targets` (SDK-4.2, #4496).
app.include_router(sdk_git_delivery_router)
app.include_router(export_git_delivery_router)
app.include_router(export_run_router)
app.include_router(export_webhook_delivery_router)
app.include_router(export_object_storage_delivery_router)
app.include_router(export_delivery_profile_router)
app.include_router(export_preset_router)
app.include_router(export_auto_router)
app.include_router(mcp_export_router)
app.include_router(mcp_pact_router)
# sdk_regen_router shares the `/v1/projects` prefix for the same reason and is registered after it
# too, so `/{tenant}/by-slug/{project_slug}` still wins for a project slugged `sdk-regen-runs`,
# `sdk-regen-jobs` or `sdk-regen-subscriptions` (SDK-4.3, #4497).
app.include_router(sdk_regen_router)
# The unified entity list (CDG-5.1, #5979) shares `/v1/catalog` and goes first, so
# `/{tenant}/entities` is not read as `/{tenant}/{item_id}`.
app.include_router(catalog_entity_router)
# Before catalog_router: its GET /{tenant_slug}/{item_id} would otherwise capture /refresh-policy,
# /upload-policy and /drift-notifications.
app.include_router(catalog_refresh_router)
app.include_router(catalog_upload_router)
app.include_router(catalog_drift_router)
app.include_router(url_import_router)
app.include_router(import_original_router)
app.include_router(catalog_router)
app.include_router(model_search_router)
# Catalog connectors (CDG-1.1, #5952): `/v1/tenants/{t}/connectors…`.
app.include_router(catalog_connector_router)
app.include_router(shadow_api_router)
# Gateway configs (CDG-5.3, #5981): `/v1/tenants/{t}/gateway-configs…`.
app.include_router(gateway_config_router)
app.include_router(catalog_migration_router)
app.include_router(identity_router)
app.include_router(compatibility_router)
app.include_router(compatibility_rules_router)
app.include_router(contract_suite_router)
app.include_router(contract_runner_router)
app.include_router(provider_verification_router)
app.include_router(verification_target_router)
app.include_router(probe_consent_router)
app.include_router(verification_schedule_router)
app.include_router(deploy_gate_tenant_router)
app.include_router(sdk_generation_settings_tenant_router)
app.include_router(sdk_publish_tenant_router)
# upstream_credential_router: the AGX-2.2 upstream auth vault under
# /v1/tenants/{t}/agent-toolsets/{toolset}/upstream-credentials (#4534).
app.include_router(upstream_credential_router)
# mock_broker_binding_router: XPC-2.1 broker bindings (Kafka bootstrap, TLS, sealed SASL credential)
# under /v1/versions/{t}/{project}/{version}/mock/broker-bindings (#5735).
app.include_router(mock_broker_binding_router)
# agent_key_router: AGX-3.1 agent keys (kind=agent api_keys bound to a toolset + tool allowlist)
# under /v1/tenants/{t}/agent-keys (#4537).
app.include_router(agent_key_router)
# cli_login_router: `apiome login` browser-approved CLI sign-in (#5501) at /v1/cli/login/*.
app.include_router(cli_login_router)
# agent_toolset_router: AGX-1.2 tool selection & curation (safe-by-default toolsets per published
# version) under /v1/tenants/{t}/agent-toolsets (#4530).
app.include_router(agent_toolset_router)
# agent_usage_router: AGX-3.4 usage rollups for the Control Panel charts under
# /v1/tenants/{t}/agent-usage (#4540).
app.include_router(agent_usage_router)
app.include_router(agent_invocation_export_router)
app.include_router(verification_evidence_router)
app.include_router(classified_diff_router)
app.include_router(consumer_contract_router)
app.include_router(consumer_pact_export_router)
# Pact Broker registry (PFX-1.1, #6914): pacticipants, versions, branches and tags.
app.include_router(pacticipant_router)
# PFX-1.11 (#6924): selector-based cleanup of pacticipant versions (dry run first).
app.include_router(pact_retention_router)
# PFX-4.4 (#6941): pact verdicts posted to GitHub / GitLab commits — list and retry.
app.include_router(pact_commit_status_router)
# Pact Broker-compatible publication and retrieval (PFX-1.2, #6915).
# PFX-1.8 (#6921): the catalogued unsupported endpoints first (so ``…/latest/badge`` is not read as
# the tag ``badge``), the real Pact Broker routes, then a catch-all — every request under
# ``…/pact-broker`` no real route serves gets a documented 501, never a bare 404.
app.include_router(pact_broker_compat_router)
app.include_router(pact_broker_router)
app.include_router(pact_broker_verification_router)
app.include_router(pact_comparison_router)  # PFX-2.5 (#6929): comparison fidelity reports
app.include_router(pact_webhook_delivery_router)  # PFX-5.6 (#6950): webhook delivery log, redeliver
app.include_router(pact_deployment_router)  # PFX-5.7 (#6951): environment topology, deployment history, simulator
app.include_router(pact_postman_router)  # PFX-4.7 (#6944): Postman collection export of a pact
app.include_router(pact_suite_router)  # PFX-3.1 (#6931): pact version → contract suite
app.include_router(pact_verifier_router)  # PFX-3.2 (#6932): hosted provider verifier
app.include_router(pact_verification_ops_router)  # PFX-5.5 (#6949): verification results and operations
app.include_router(pact_remediation_router)  # PFX-6.2 (#6954): verification settings, re-publish requests
app.include_router(pact_health_router)  # PFX-6.3 (#6955): contract health rollup and verification analytics
app.include_router(pact_secret_router)  # PFX-6.5 (#6957): workspace secrets for webhooks and targets
app.include_router(pact_provider_state_router)  # PFX-3.3 (#6933): provider-state registry
app.include_router(pact_broker_environment_router)
app.include_router(pact_broker_matrix_router)
app.include_router(pact_broker_webhook_router)
app.include_router(pact_badge_router)  # PFX-1.10 (#6923): public pact badges
app.include_router(pact_broker_cleanup_router)  # PFX-1.11 (#6924): labels and deletes
app.include_router(provider_contract_router)  # PFX-2.1 (#6925): provider contracts
app.include_router(pact_broker_fallback_router)
# consumer_binding_router: RDG-1.8 consumer bindings + declared-vs-observed runtime edges under
# /v1/tenants/{t}/projects/{p}/consumers/{c}/bindings|runtime (#5765).
app.include_router(consumer_binding_router)
app.include_router(team_router)
app.include_router(api_product_router)
app.include_router(api_plan_router)
# Agent and model entities (CDG-5.2, #5980): `/v1/tenants/{t}/catalog-agents|catalog-models…`.
app.include_router(catalog_agent_router)
app.include_router(entity_owner_router)
app.include_router(unowned_findings_router)
app.include_router(ownership_policy_router)
# two_factor_policy_router: TFA-1.3 tenant two-factor requirement GET|PUT …/two-factor-policy (#5657).
app.include_router(two_factor_policy_router)
# tenant_document_store_router: COA-5.15 a tenant's own bucket GET|PUT …/document-store, POST …/test|cleanup (#7092).
app.include_router(tenant_document_store_router)
# An unreachable or revoked tenant bucket answers 503 tenant-document-store-unavailable everywhere.
app.add_exception_handler(TenantDocumentStoreUnavailable, tenant_store_unavailable_handler)
app.include_router(graph_router)
# usage_ingest_router: RDG-1.2 usage ingest door POST /v1/tenants/{t}/usage/ingest (#5760).
app.include_router(usage_ingest_router)
# usage_source_router: RDG-1.4 HAR source find-or-create POST /v1/tenants/{t}/usage/sources/har (#5762).
app.include_router(usage_source_router)
# usage_controls_router: RDG-5.4 usage export, retention, source capture and toolset body samples (#5789).
app.include_router(usage_controls_router)
app.include_router(comment_router)
app.include_router(presence_router)
app.include_router(review_suggestion_router)
app.include_router(merge_request_router)
app.include_router(review_router)
app.include_router(draft_binding_router)
app.include_router(project_repository_sources_router)
app.include_router(pr_back_router)
app.include_router(repository_federation_router)
app.include_router(provider_check_router)
app.include_router(spec_sync_router)
app.include_router(api_check_suite_router)
app.include_router(notification_router)
app.include_router(lint_router)
app.include_router(lint_rules_router)
# GVM-3.2 (#5870): lint-fix plan / apply.
app.include_router(lint_fix_router)
app.include_router(lint_fix_plan_router)
app.include_router(overlay_lint_router)
app.include_router(lint_decisions_router)
app.include_router(lint_workspace_router)
app.include_router(style_guide_router)
app.include_router(quality_policy_router)
app.include_router(verification_policy_router)
app.include_router(scrub_policy_router)
app.include_router(version_merge_router)
# #2593: revision DAG reads (ancestors, history window, merge-base). Their literal segments keep
# the /{version_record_id} routes of versions_router from shadowing them.
app.include_router(revision_graph_router)
# #2594: project activity timeline; same reason (literal /timeline segment).
app.include_router(project_timeline_router)
app.include_router(workflow_audit_router)
# COA-1.3 (#7039): the Arazzo workflow viewer's reads under /v1/workflows.
app.include_router(arazzo_workflow_router)
# COA-2.6 (#7049): the OpenAPI spec upgrade assistant (plan, then apply as a new version).
app.include_router(openapi_upgrade_router)
# version_changelog_router before versions_router so its literal
# /{tenant_slug}/{project_id}/changelogs route wins over the versions
# /{tenant_slug}/{project_id}/{version_record_id} parameter route (CTG-3.2, #4476).
app.include_router(version_changelog_router)
# COA-5.7 (#7083): download a revision's stored original (literal /original suffix).
app.include_router(version_original_router)
app.include_router(version_document_router)  # COA-5.13 (#7089): the members' OpenAPI document
# Registered before versions_router for the same reason: the literal
# /{tenant_slug}/{project_id}/{version_record_id}/agent-outputs suffix stays unambiguous
# against the versions parameter routes (APX-3.4, private-suite#2459).
app.include_router(slate_agent_outputs_router)
app.include_router(snippet_versions_router)
app.include_router(versions_router)
app.include_router(properties_router)
app.include_router(project_tags_router)
app.include_router(domains_router)
app.include_router(scoped_catalog_router)
app.include_router(workspace_summary_router)
app.include_router(workspace_property_router)
app.include_router(workspace_custom_action_router)
app.include_router(consumption_index_router)
app.include_router(paths_router)
app.include_router(version_tags_router)
app.include_router(draft_lock_router)
app.include_router(version_overlay_router)
app.include_router(project_references_router)
app.include_router(preservation_router)
app.include_router(source_review_router)
app.include_router(source_provenance_router)
app.include_router(slate_router)
# Registered after slate_router so the existing surface's precedence stays unambiguous:
# /environments/{id}/cache* sits alongside /environments/{id} (UXE-3.1, private-suite#2473).
app.include_router(slate_cache_router)
# Same reasoning one surface over: /environments/{id}/security* sits alongside the cache plane
# and the existing environment routes (UXE-3.2, private-suite#2474).
app.include_router(slate_security_router)
# Same reasoning one surface further on: /environments/{id}/functions* sits alongside the cache and
# security planes and the existing environment routes (UXE-3.3, private-suite#2475).
app.include_router(slate_functions_router)
# Same reasoning one surface further on: /environments/{id}/insights* sits alongside the cache,
# security and function planes and the existing environment routes (UXE-3.4, private-suite#2476).
app.include_router(slate_insights_router)
# Custom domains: /environments/{id}/domains sits alongside the cache, security, function and
# insight planes, and /domains/{id} + /tls/authorize are disjoint from every existing /v1/slate
# path (Slate 10.1, private-suite#119).
app.include_router(slate_domains_router)
# The git-triggered preview plane: /git/connections, /git/events and /git/previews sit under
# the same /v1/slate prefix, disjoint from the /environments and /sites surfaces above
# (APX-3.3, private-suite#2458).
app.include_router(slate_git_preview_router)
# CDN / edge provider: /environments/{id}/cdn* sits alongside the cache plane whose purges it
# dispatches (Slate 10.2, private-suite#120).
app.include_router(slate_cdn_router)
app.include_router(component_library_router)
app.include_router(component_governance_router)
app.include_router(push_webhook_subscriptions_router)
app.include_router(change_report_router)
app.include_router(version_change_report_router)
# Enterprise change reports (#2705): approvals, PDF export and the audit trail.
app.include_router(change_report_enterprise_router)
app.include_router(change_report_audit_router)
app.include_router(change_report_template_router)
app.include_router(tenants_session_router)
app.include_router(license_router)
# First-tenant provisioning (OLO-4.3, #4207): atomic tenant + owner role +
# free-tier entitlements for the onboarding wizard and OAuth signup.
app.include_router(onboarding_router)
app.include_router(mcp_policy_router)
# MCP API key lifecycle (MTG-3.2, #4776): tenant-admin CRUD over mcp_api_keys.
app.include_router(mcp_key_router)
app.include_router(spec_import_router)
# Git-repository intake (MFI-29.3, #4390): POST /v1/tenants/{tenant}/import/git/fileset —
# fetches a repo path/glob at a ref as the archive payload the import flow already accepts.
app.include_router(git_import_router)
# Bulk import of independent specs (MFI-29.5, #4392): POST /v1/tenants/{tenant}/import/bulk[/plan]
# — partitions one archive/repository into N independent specs and starts one ordinary job each.
app.include_router(bulk_import_router)
# Schema instance validation (IXH-5.1, #5113): POST /v1/tenants/{tenant}/schemas/{ref}/validate
# — does this payload satisfy this schema? Mounted next to the import surface because the
# reference grammar addresses the same project/catalog revisions imports create.
app.include_router(schema_validation_router)
app.include_router(schema_synthesis_router)
app.include_router(schema_targets_router)
# Saved schema test suites (IXH-5.7, #5119): /v1/tenants/{tenant}/schema-suites — persist the
# payloads the 5.1/5.3 surfaces validate, re-run them per revision, and track regressions.
app.include_router(schema_suite_router)
app.include_router(import_sources_router)
app.include_router(postman_convert_router)
# Format matrix (FMT-1.5, #5416): /v1/formats/matrix — one row per registered format, the single
# machine-readable answer to "what do you support?". The same payload the generated
# supported-formats page and `apiome formats` render, so the three cannot disagree.
app.include_router(format_matrix_router)
# Multi-format export (MFX-2.5, #3842): tenant-scoped fidelity report surfacing — per-target
# fidelity badges (/export/{tenant}/targets) and the dry-run preview (/export/{tenant}/preview).
app.include_router(export_router)
# Export pre-flight (IXH-2.4, #5099): the export twin of the import pre-flight, mounted under
# /v1/tenants/{tenant}/export/preflight so the two pre-flights sit side by side.
app.include_router(export_tenant_router)
app.include_router(export_job_router)
# Avro push (MFX-19.4, #3912): register an Avro export on a schema-registry connector's registry.
app.include_router(avro_registry_push_router)
app.include_router(schema_registry_push_router)
# Export test-drive mocks (MFX-44.5, #4371): provision a short-lived mock from an emitted
# artifact. Bound to the Mock Server engine below — this surface only provisions and inspects;
# the mock itself is served by the public /v1/mock data plane.
app.include_router(export_mock_router)
app.include_router(export_tool_check_router)
app.include_router(tenant_repositories_router)
# Repository webhook ingestion (REPO-4.3, #2781): unauthenticated by necessity — a provider
# holds no token — and authenticated instead by the HMAC signature over the raw body.
app.include_router(repository_webhook_router)
app.include_router(access_router)
app.include_router(access_platform_router)
# Mock Server (#3615): tenant-scoped management plane, then the public data plane catch-all.
app.include_router(mock_router)
app.include_router(mock_data_router)
# MCP Catalog (#3663): tenant-scoped CRUD over registered external MCP endpoints.
app.include_router(mcp_endpoints_router)
# MCP dynamic probes (CLX-3.3, #4857): consent-gated, sandboxed, audited active probing.
app.include_router(mcp_probe_router)
# MCP static manifests (FMT-1.7, #5418): catalog a server from a declared descriptor and
# attribute every surface fact to the manifest, the probe, or both.
app.include_router(mcp_manifest_router)
# MCP trust baselines, drift, and shadowing (CLX-3.4, #4858): diff each rediscovery/release against
# an approved baseline; classify normal/quality/security/coverage-loss deltas; detect shadowed names.
app.include_router(mcp_trust_baseline_router)
app.include_router(mcp_catalog_digest_router)
app.include_router(mcp_saved_search_router)
app.include_router(mcp_endpoint_note_router)
app.include_router(mcp_categorization_router)
app.include_router(mcp_collection_router)
# MCP tool catalog + capability presets (MTG-1.1 / MTG-5.1): GET /api-keys/mcp-tools,
# GET /api-keys/mcp-capability-presets for CLI + admin UX.
app.include_router(mcp_tool_router)
# Observability & ops (#3617): liveness/readiness probes + platform-admin ops dashboard.
app.include_router(health_router)
app.include_router(ops_router)
app.include_router(document_migration_router)
app.include_router(document_store_ops_router)
app.include_router(document_store_admin_router)
# Super-admin OAuth provider config CRUD (OLO-8.4, #4970): GET/PUT /v1/admin/auth-providers,
# gated by the signed super-admin session (OLO-8.1); secrets are write-only and never returned.
app.include_router(auth_provider_config_router)
# Internal resolved provider config (OLO-8.5, #4971): GET /v1/internal/auth-providers/resolved,
# service-token-gated, returns DECRYPTED secrets for the login-time DB-over-env merge resolver.
app.include_router(auth_provider_resolved_router)
# Enterprise SSO providers (EID-1.1, #5011): admin CRUD + the login-time resolved read path, and
# the server-to-server auth_events write path apiome-ui records SSO sign-in outcomes through.
app.include_router(sso_provider_admin_router)
app.include_router(sso_provider_internal_router)
app.include_router(tenant_sso_router)
app.include_router(internal_auth_event_router)
# Super-admin installation sign-up policy (SGN-1.4, #5653): GET/PUT /v1/admin/signup-policy —
# open / invite_only / closed + allowed email domains, DB-first with AUTH_SIGNUP_DISABLED fallback.
app.include_router(signup_policy_router)
app.include_router(portal_auth_router)
app.include_router(consumer_feedback_router)
app.include_router(sdk_beacon_router)
app.include_router(sdk_compat_router)
app.include_router(two_factor_reset_admin_router)
app.include_router(two_factor_reset_member_router)


_webhook_delivery_task: asyncio.Task | None = None
_repository_file_scan_task: asyncio.Task | None = None
_repository_refresh_task: asyncio.Task | None = None
_url_import_refresh_task: asyncio.Task | None = None
_repository_quality_task: asyncio.Task | None = None
_mcp_discovery_task: asyncio.Task | None = None
_mcp_health_task: asyncio.Task | None = None
_catalog_refresh_task: asyncio.Task | None = None
_mcp_catalog_digest_task: asyncio.Task | None = None
_catalog_graph_task: asyncio.Task | None = None
_usage_sweep_task: asyncio.Task | None = None
_lint_waiver_expiry_task: asyncio.Task | None = None
_verification_schedule_task: asyncio.Task | None = None
_pact_remediation_task: asyncio.Task | None = None
_async_job_retention_task: asyncio.Task | None = None
_mock_activity_flush_task: asyncio.Task | None = None
_document_lifecycle_task: asyncio.Task | None = None
_repository_webhook_secret_task: asyncio.Task | None = None
_repository_webhook_ip_range_task: asyncio.Task | None = None
_sdk_regen_task: asyncio.Task | None = None
_export_auto_task: asyncio.Task | None = None


@app.on_event("startup")
async def startup_event():
    """Connect to database on startup."""
    db.connect()
    _startup_log = logging.getLogger("uvicorn.error")
    # Request handlers that touch the database run on worker threads; keep that pool below the
    # connection cap (DBP-1.4, #7187).
    configure_request_thread_pool(_startup_log)
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
    validate_registry_credential_keys()
    validate_upstream_credential_keys()
    validate_broker_credential_keys()
    validate_slate_cdn_credential_keys()
    validate_linked_account_token_keys()
    validate_auth_config_encryption_keys()

    # Bundled-toolchain self-check (FMT-1.3, #5414). Resolves and actually invokes every
    # *required* bundled tool, logging the version it reports — so the boot log always names
    # the `@asyncapi/parser` this runtime is running. In an enforcing deployment a missing
    # required tool raises here and startup fails loudly, instead of the service coming up with
    # a shipped format silently unavailable.
    await enforce_toolchain_selfcheck(log=_startup_log)

    # Document store (COA-5.9, #7085). Builds the configured store and checks an s3 bucket or a
    # storage directory answers. An unusable store stops startup with a redacted message naming
    # the setting to fix — unless APIOME_DOCUMENT_STORE_FALLBACK=db, which starts on the database
    # store instead and reports the fallback on /health and GET /v1/ops/document-store.
    await asyncio.to_thread(initialize_document_store, log=_startup_log)
    # COA-5.15: tenants already on their own bucket keep resolving even with the setting off.
    await asyncio.to_thread(refresh_document_store_routing, db)

    async def _webhook_delivery_sweep() -> None:
        log = logging.getLogger(__name__)
        # One handle for every tick: its connection is reused, not reopened (DBP-1.2).
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(15)
            try:
                def _run_in_thread() -> int:
                    """Drain both delivery queues on the sweep's long-lived handle.

                    Each queue is claimed in batches and delivered on a bounded worker pool until
                    it is empty or ``APIOME_WEBHOOK_DELIVERY_TICK_SECONDS`` pass (DBP-1.18, #7201);
                    the loop then sleeps 15 s.
                    """
                    with sweep_tick(sweep_db) as thread_db:
                        made = process_due_push_webhook_deliveries(thread_db)
                        # Export webhook deliveries (MFX-38.2) retry on the same tick and backoff; a
                        # fault in one queue never starves the other.
                        try:
                            made += process_due_export_webhook_deliveries(thread_db)
                        except Exception:
                            log.exception("export webhook delivery sweep")
                        return made

                await asyncio.to_thread(_run_in_thread)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("push webhook delivery sweep")

    async def _repository_file_scan_sweep() -> None:
        log = logging.getLogger(__name__)
        # One handle for every tick: its connection is reused, not reopened (DBP-1.2).
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(5)
            try:

                def _run_scan() -> int:
                    with sweep_tick(sweep_db) as thread_db:
                        from .repository_file_scan import process_next_repository_file_scan_job

                        return process_next_repository_file_scan_job(thread_db)

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
        # One handle for every tick: its connection is reused, not reopened (DBP-1.2).
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(tick_seconds)
            try:

                def _run_refresh() -> int:
                    with sweep_tick(sweep_db) as thread_db:
                        from .repository_refresh_sweep import (
                            process_repository_refresh_sweep,
                        )

                        enqueued = process_repository_refresh_sweep(thread_db)
                        # Catalog connectors share the tick, the kill switch and the tenant
                        # quota (CDG-1.1): one refresh engine, two kinds of source.
                        from .catalog_connector_sync import process_connector_refresh_sweep

                        try:
                            process_connector_refresh_sweep(thread_db)
                        except Exception:
                            log.exception("catalog connector sweep")
                        return enqueued

                await asyncio.to_thread(_run_refresh)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("repository refresh sweep")

    async def _url_import_refresh_sweep() -> None:
        """Periodically re-check URL-sourced imports and refresh the changed ones (RAR-6.1).

        Ticks on the refresh floor (``APIOME_REFRESH_MIN_INTERVAL``) like the repository sweep;
        due-selection in ``url_import_store.list_due`` applies each URL's own cadence, and
        ``APIOME_REFRESH_ENABLED`` halts it with the repository sweep.
        """
        from .config import settings

        log = logging.getLogger(__name__)
        tick_seconds = max(1, int(settings.refresh_min_interval_seconds))
        # One handle for every tick: its connection is reused, not reopened (DBP-1.2).
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(tick_seconds)
            try:
                from .url_import_refresh_sweep import process_url_import_refresh_sweep

                async with async_sweep_tick(sweep_db) as thread_db:
                    await process_url_import_refresh_sweep(thread_db)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("url import refresh sweep")

    async def _repository_quality_sweep() -> None:
        """Periodically score newly discovered repository specs (REPO-2.8).

        Ticks on ``APIOME_REPOSITORY_QUALITY_INTERVAL`` (default 30s) and scores at most
        ``APIOME_REPOSITORY_QUALITY_BATCH_SIZE`` files per tick, so draining a monorepo's
        backlog is spread out instead of bursting at the provider. Each attempt stamps the
        blob it read, so the backlog strictly shrinks and a settled repository costs one
        empty query per tick. Set ``APIOME_REPOSITORY_QUALITY_SCORING=false`` to disable.
        """
        from .config import settings

        log = logging.getLogger(__name__)
        tick_seconds = max(1, int(settings.repository_quality_interval_seconds))
        # One handle for every tick: its connection is reused, not reopened (DBP-1.2).
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(tick_seconds)
            try:

                def _run_quality() -> Any:
                    with sweep_tick(sweep_db) as thread_db:
                        from .repository_quality_sweep import (
                            process_repository_spec_quality_batch,
                        )

                        return process_repository_spec_quality_batch(thread_db)

                await asyncio.to_thread(_run_quality)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("repository spec quality sweep")

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
        # One handle for every tick: its connection is reused, not reopened (DBP-1.2).
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(tick_seconds)
            try:
                from .mcp_discovery_sweep import process_mcp_discovery_sweep

                # The due-selection read runs on a dedicated connection (like the other
                # sweeps) so it never contends with request handlers on the shared `db`.
                # The dispatched discovery runs use the engine's own (global) handle.
                async with async_sweep_tick(sweep_db) as thread_db:
                    await process_mcp_discovery_sweep(thread_db)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("mcp discovery sweep")

    async def _mcp_health_sweep() -> None:
        """Periodically probe MCP catalog endpoints' reachability and latency (MCAT-13.3, #3713).

        Ticks on ``APIOME_MCP_HEALTH_MIN_INTERVAL`` (default 60s); due-selection in
        ``list_due_mcp_health_endpoints`` lets the health cadence (``APIOME_MCP_HEALTH_CADENCE``,
        default 300s) decide which endpoints are probed. Each probe is the ``initialize`` handshake
        only, so it is far lighter than a discovery run. Like the discovery sweep the probes are
        async and the blocking DB reads/writes go to worker threads, on a dedicated connection.
        """
        from .config import settings

        log = logging.getLogger(__name__)
        tick_seconds = max(1, int(settings.mcp_health_min_interval_seconds))
        # One handle for every tick: its connection is reused, not reopened (DBP-1.2).
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(tick_seconds)
            try:
                from .mcp_health_sweep import process_mcp_health_sweep

                async with async_sweep_tick(sweep_db) as thread_db:
                    await process_mcp_health_sweep(thread_db)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("mcp health sweep")

    async def _catalog_refresh_sweep(tick_seconds: int) -> None:
        """Periodically re-check catalog items whose refresh cadence has elapsed (MFI-31.1).

        Ticks every ``APIOME_CATALOG_REFRESH_TICK`` seconds; due-selection in
        ``catalog_refresh_store.list_due`` decides which items are checked. Like the MCP sweep the
        tick runs on the event loop and pushes blocking work to worker threads, and it awaits its
        checks, so the next tick starts only after this one drains.
        """
        log = logging.getLogger(__name__)
        # One handle for every tick: its connection is reused, not reopened (DBP-1.2).
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(tick_seconds)
            try:
                from .catalog_refresh_sweep import process_catalog_refresh_sweep

                async with async_sweep_tick(sweep_db) as thread_db:
                    await process_catalog_refresh_sweep(thread_db)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("catalog refresh sweep")

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
        # One handle for every tick: its connection is reused, not reopened (DBP-1.2).
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(tick_seconds)
            try:

                def _run_digest() -> int:
                    with sweep_tick(sweep_db) as thread_db:
                        from .mcp_catalog_digest_sweep import (
                            process_mcp_catalog_digest_sweep,
                        )

                        return process_mcp_catalog_digest_sweep(thread_db)

                await asyncio.to_thread(_run_digest)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("mcp catalog digest sweep")

    async def _catalog_graph_sweep() -> None:
        """Nightly re-derivation of every catalog graph edge family for every tenant (CDG-3.1).

        Repairs what the producers' in-transaction hooks missed and stamps/purges stale edges. Runs
        on a dedicated DB connection, which holds the sweep's advisory lock so replicas don't overlap.
        """
        from .catalog_graph import SWEEP_INTERVAL_SECONDS

        log = logging.getLogger(__name__)
        # One handle for every tick: its connection is reused, not reopened (DBP-1.2).
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
            try:

                def _run_graph() -> None:
                    with sweep_tick(sweep_db) as thread_db:
                        from .catalog_graph import sweep

                        sweep(thread_db)

                await asyncio.to_thread(_run_graph)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("catalog graph sweep")

    async def _usage_index_sweep(interval_seconds: int) -> None:
        """Roll up, finalize and prune the usage index on a schedule (RDG-1.1, #5759).

        Each tick runs :func:`app.usage_sweep.run_usage_sweep` on a dedicated DB connection, which
        holds the sweep's advisory lock so replicas don't overlap. Started only when
        ``APIOME_USAGE_SWEEP_INTERVAL_SECONDS`` is positive.
        """
        from .config import settings

        log = logging.getLogger(__name__)
        # One handle for every tick: its connection is reused, not reopened (DBP-1.2).
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(interval_seconds)
            try:

                def _run_usage() -> None:
                    with sweep_tick(sweep_db) as thread_db:
                        from .usage_sweep import run_usage_sweep_with_settings

                        run_usage_sweep_with_settings(thread_db, settings)

                await asyncio.to_thread(_run_usage)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("usage index sweep")

    async def _lint_waiver_expiry_sweep() -> None:
        """Periodically notify soon-expiring lint waivers (CLX-4.2, #4860).

        Each tick claims unnotified waivers expiring within the warning window
        (``APIOME_LINT_WAIVER_EXPIRY_WARNING_HOURS``, default 72h) and enqueues one
        ``lint.waiver.expiring`` webhook per claim. The claim is atomic across replicas
        (``FOR UPDATE SKIP LOCKED``), so several instances sweeping concurrently still
        notify each waiver exactly once. Runs on a dedicated DB connection like the other
        sweeps.
        """
        log = logging.getLogger(__name__)
        # One handle for every tick: its connection is reused, not reopened (DBP-1.2).
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(300)
            try:

                def _run_expiry() -> int:
                    with sweep_tick(sweep_db) as thread_db:
                        from .lint_waiver_expiry_sweep import (
                            process_lint_waiver_expiry_sweep,
                        )

                        return process_lint_waiver_expiry_sweep(thread_db)

                await asyncio.to_thread(_run_expiry)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("lint waiver expiry sweep")

    async def _verification_schedule_sweep() -> None:
        """Periodically verify deployments against their contracts and alert on drift (CTG-4.4).

        Ticks on ``APIOME_VERIFICATION_SCHEDULE_INTERVAL`` (default 60s) and lets the per-schedule
        cadence + due-selection in ``list_due_verification_schedules`` decide which schedules
        actually run, so the cheap floor cadence here never runs a schedule more often than its own
        cadence (minimum 5 minutes) allows. At most
        ``APIOME_VERIFICATION_SCHEDULE_BATCH_SIZE`` schedules execute per tick — unlike the other
        sweeps this one sends real requests to live deployments — and the remainder stays due for
        the next tick. Runs on a dedicated DB connection like the other sweeps, because the
        per-schedule advisory locks that give single-flight are session-scoped.
        """
        from .config import settings

        log = logging.getLogger(__name__)
        tick_seconds = max(1, int(settings.verification_schedule_interval_seconds))
        # One handle for every tick: its connection is reused, not reopened (DBP-1.2).
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(tick_seconds)
            try:

                def _run_schedules() -> int:
                    with sweep_tick(sweep_db) as thread_db:
                        from .verification_schedule_sweep import (
                            process_verification_schedule_sweep,
                        )

                        return process_verification_schedule_sweep(thread_db)

                await asyncio.to_thread(_run_schedules)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("verification schedule sweep")

    async def _pact_remediation_sweep() -> None:
        """Remediate stale pacts and run scheduled Pact verifications (PFX-6.2, #6954).

        Ticks on ``APIOME_PACT_REMEDIATION_INTERVAL`` (default 300s): records each pair's stale
        state, opens / closes / escalates re-publish requests, and runs at most
        ``APIOME_PACT_SCHEDULE_BATCH_SIZE`` due scheduled verifications. A dedicated DB connection,
        because the concurrency-slot and per-pair advisory locks are session-scoped.
        """
        from .config import settings

        log = logging.getLogger(__name__)
        tick_seconds = max(30, int(settings.pact_remediation_interval_seconds))
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(tick_seconds)
            try:

                def _run_remediation() -> Any:
                    with sweep_tick(sweep_db) as thread_db:
                        from .pact_remediation_sweep import process_pact_remediation_sweep

                        return process_pact_remediation_sweep(thread_db)

                await asyncio.to_thread(_run_remediation)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("pact remediation sweep")

    async def _async_job_retention_sweep() -> None:
        """Periodically reap expired async jobs and export artifacts (IXH-6.3, #5122).

        Each tick reaps expired artifact bytes, claims terminal ``async_job`` rows past the
        configured per-(kind, state) retention window under ``FOR UPDATE SKIP LOCKED``,
        writes slim history, deletes the live rows (CASCADE artifacts), and prunes old
        history. Concurrent replicas are safe — the claim is the lock.
        """
        log = logging.getLogger(__name__)
        # One handle for every tick: its connection is reused, not reopened (DBP-1.2).
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(300)
            try:

                def _run_retention() -> dict:
                    with sweep_tick(sweep_db) as thread_db:
                        from .async_job_retention_sweep import (
                            process_async_job_retention_sweep,
                        )
                        from .operational_retention_sweep import (
                            process_operational_retention_sweep,
                        )

                        counts = process_async_job_retention_sweep(thread_db)
                        # Finished discovery jobs and expired Slate request data share the
                        # tick (DBP-1.18, #7201); a fault there never stops the job reaping above.
                        try:
                            process_operational_retention_sweep(thread_db)
                        except Exception:
                            log.exception("operational retention sweep")
                        # Pacticipants and versions deleted longer ago than the grace period
                        # (PFX-1.11, #6924) are purged on the same tick.
                        try:
                            from .pact_cleanup_store import purge_deleted

                            purge_deleted(thread_db)
                        except Exception:
                            log.exception("pact deletion purge")
                        return counts

                await asyncio.to_thread(_run_retention)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("async job retention sweep")

    async def _mock_activity_flush_sweep() -> None:
        """Write the mock data plane's buffered request counts every few seconds (#7196).

        Served requests are counted in memory (:mod:`app.mock_data_plane`) so the data plane does
        not write a row per request; each tick adds the counts in one ``UPDATE``. An idle tick
        (nothing served) touches neither a thread nor the database.
        """
        from .mock_data_plane import ACTIVITY_FLUSH_SECONDS, activity_buffer, flush_activity

        log = logging.getLogger(__name__)
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(ACTIVITY_FLUSH_SECONDS)
            if not len(activity_buffer):
                continue
            try:

                def _flush() -> int:
                    with sweep_tick(sweep_db) as thread_db:
                        return flush_activity(thread_db)

                await asyncio.to_thread(_flush)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("mock activity flush sweep")

    async def _document_lifecycle_sweep(interval: int) -> None:
        """Run the document lifecycle job every ``interval`` seconds (COA-5.10, #7086).

        Deletes objects no live revision has used for the grace period, drops replaced rendered
        documents, empties deleted tenants' store prefixes and re-hashes a sample of objects. One
        run at a time across replicas (the job's advisory lock); the first run waits one interval.
        """
        log = logging.getLogger(__name__)
        # One handle for every tick: its connection is reused, not reopened (DBP-1.2).
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(interval)
            try:

                def _run_lifecycle() -> dict:
                    with sweep_tick(sweep_db) as thread_db:
                        from .document_lifecycle import run_document_lifecycle

                        return run_document_lifecycle(thread_db).as_dict()

                await asyncio.to_thread(_run_lifecycle)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("document lifecycle sweep")

    async def _repository_webhook_secret_sweep() -> None:
        """Periodically close webhook signing-secret rotation windows (REPO-4.7, #2785).

        Each tick retries the provider hook update for rotations that have not reached their
        provider yet, then retires every outgoing secret whose grace window has closed. The
        retirement claim is atomic across replicas (``FOR UPDATE SKIP LOCKED``), so each old
        secret is retired — and audited — exactly once no matter how many instances sweep.
        Runs on a dedicated DB connection like the other sweeps.
        """
        log = logging.getLogger(__name__)
        # One handle for every tick: its connection is reused, not reopened (DBP-1.2).
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(300)
            try:

                def _run_secret_sweep() -> dict:
                    with sweep_tick(sweep_db) as thread_db:
                        from .repository_webhook_secret_sweep import (
                            process_repository_webhook_secret_sweep,
                        )

                        return process_repository_webhook_secret_sweep(thread_db)

                await asyncio.to_thread(_run_secret_sweep)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("repository webhook secret rotation sweep")

    async def _repository_webhook_ip_range_sweep() -> None:
        """Keep the cached provider webhook IP ranges fresh (REPO-7.6, #2804).

        The allowlist filters on ranges the providers publish and periodically change, so a
        cache nobody refreshes becomes a filter that rejects legitimate deliveries. The tick
        is hourly and the *cadence* is daily (``APIOME_REPOSITORY_WEBHOOK_IP_REFRESH_INTERVAL
        _SECONDS``): due-ness is measured from each provider's last **success**, so a healthy
        provider is fetched once a day while one whose endpoint is failing is retried within
        the hour rather than tomorrow.

        The first tick runs shortly after startup rather than an hour in, so a fresh
        deployment has ranges to filter on before an operator turns enforcement on. Runs on a
        dedicated DB connection like the other sweeps.
        """
        log = logging.getLogger(__name__)
        # Enough of a delay that startup is not competing with an outbound fetch, short
        # enough that a new deployment is populated in the first minute.
        await asyncio.sleep(20)
        # One handle for every tick: its connection is reused, not reopened (DBP-1.2).
        sweep_db = sweep_database()
        while True:
            try:

                def _run_ip_refresh() -> Any:
                    with sweep_tick(sweep_db) as thread_db:
                        from .repository_webhook_ip_allowlist import (
                            refresh_due_provider_ip_ranges,
                        )

                        return refresh_due_provider_ip_ranges(thread_db)

                await asyncio.to_thread(_run_ip_refresh)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("repository webhook IP range refresh sweep")
            await asyncio.sleep(3600)

    async def _export_auto_sweep() -> None:
        """Run the auto-exports version publishes queue (MFX-39.4, #4336).

        Ticks on ``APIOME_EXPORT_AUTO_INTERVAL`` (default 30s). Unlike the threaded sweeps it runs on the
        event loop: each run schedules an export job on this instance's export engine and awaits it, then
        halts or delivers. Database calls go through ``asyncio.to_thread``. The claim is ``FOR UPDATE SKIP
        LOCKED``, so replicas share the queue. ``APIOME_EXPORT_AUTO_ENABLED=false`` halts it.
        """
        from .config import settings

        log = logging.getLogger(__name__)
        tick_seconds = max(1, int(settings.export_auto_interval_seconds))
        while True:
            await asyncio.sleep(tick_seconds)
            try:
                from .export_auto_worker import process_auto_export_sweep

                await process_auto_export_sweep(db)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("export auto sweep")

    async def _sdk_regen_sweep() -> None:
        """Regenerate and deliver subscribed SDKs after each publish (SDK-4.3, #4497).

        Ticks on ``APIOME_SDK_REGEN_INTERVAL`` (default 30s). Each tick dead-letters jobs whose
        worker outlived ``APIOME_SDK_REGEN_LEASE_SECONDS``, then claims and runs at most
        ``APIOME_SDK_REGEN_BATCH_SIZE`` due jobs — each an SDK-4.1 registry publish and/or an
        SDK-4.2 pull request. The claim is ``FOR UPDATE SKIP LOCKED``, so replicas share the queue.
        Runs on a dedicated DB connection like the other sweeps. ``APIOME_SDK_REGEN_ENABLED=false``
        halts it.
        """
        from .config import settings

        log = logging.getLogger(__name__)
        tick_seconds = max(1, int(settings.sdk_regen_interval_seconds))
        # One handle for every tick: its connection is reused, not reopened (DBP-1.2).
        sweep_db = sweep_database()
        while True:
            await asyncio.sleep(tick_seconds)
            try:

                def _run_regen() -> int:
                    with sweep_tick(sweep_db) as thread_db:
                        from .sdk_regen_worker import process_sdk_regen_sweep

                        return process_sdk_regen_sweep(thread_db, apiome_version=app.version)

                await asyncio.to_thread(_run_regen)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("sdk regen sweep")

    global _webhook_delivery_task
    _webhook_delivery_task = asyncio.create_task(_webhook_delivery_sweep())
    global _repository_file_scan_task
    _repository_file_scan_task = asyncio.create_task(_repository_file_scan_sweep())
    global _repository_refresh_task
    _repository_refresh_task = asyncio.create_task(_repository_refresh_sweep())
    global _url_import_refresh_task
    _url_import_refresh_task = asyncio.create_task(_url_import_refresh_sweep())
    global _repository_quality_task
    _repository_quality_task = asyncio.create_task(_repository_quality_sweep())
    global _mcp_discovery_task
    _mcp_discovery_task = asyncio.create_task(_mcp_discovery_sweep())
    global _mcp_health_task
    _mcp_health_task = asyncio.create_task(_mcp_health_sweep())
    global _catalog_refresh_task
    if int(settings.catalog_refresh_tick_seconds) > 0:
        _catalog_refresh_task = asyncio.create_task(
            _catalog_refresh_sweep(int(settings.catalog_refresh_tick_seconds))
        )
    global _mcp_catalog_digest_task
    _mcp_catalog_digest_task = asyncio.create_task(_mcp_catalog_digest_sweep())
    global _catalog_graph_task
    _catalog_graph_task = asyncio.create_task(_catalog_graph_sweep())
    global _usage_sweep_task
    if int(settings.usage_sweep_interval_seconds) > 0:
        _usage_sweep_task = asyncio.create_task(_usage_index_sweep(int(settings.usage_sweep_interval_seconds)))
    global _lint_waiver_expiry_task
    _lint_waiver_expiry_task = asyncio.create_task(_lint_waiver_expiry_sweep())
    global _verification_schedule_task
    _verification_schedule_task = asyncio.create_task(_verification_schedule_sweep())
    global _pact_remediation_task
    _pact_remediation_task = asyncio.create_task(_pact_remediation_sweep())
    global _async_job_retention_task
    _async_job_retention_task = asyncio.create_task(_async_job_retention_sweep())

    global _mock_activity_flush_task
    if settings.mock_server_enabled:
        _mock_activity_flush_task = asyncio.create_task(_mock_activity_flush_sweep())
    global _document_lifecycle_task
    if int(settings.document_lifecycle_interval_seconds) > 0:
        _document_lifecycle_task = asyncio.create_task(
            _document_lifecycle_sweep(int(settings.document_lifecycle_interval_seconds))
        )
    global _repository_webhook_secret_task
    _repository_webhook_secret_task = asyncio.create_task(
        _repository_webhook_secret_sweep()
    )
    global _repository_webhook_ip_range_task
    _repository_webhook_ip_range_task = asyncio.create_task(
        _repository_webhook_ip_range_sweep()
    )
    global _sdk_regen_task
    _sdk_regen_task = asyncio.create_task(_sdk_regen_sweep())
    global _export_auto_task
    _export_auto_task = asyncio.create_task(_export_auto_sweep())


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
    global _url_import_refresh_task
    if _url_import_refresh_task is not None:
        _url_import_refresh_task.cancel()
        try:
            await _url_import_refresh_task
        except asyncio.CancelledError:
            pass
        _url_import_refresh_task = None
    global _repository_quality_task
    if _repository_quality_task is not None:
        _repository_quality_task.cancel()
        try:
            await _repository_quality_task
        except asyncio.CancelledError:
            pass
        _repository_quality_task = None
    global _mcp_discovery_task
    if _mcp_discovery_task is not None:
        _mcp_discovery_task.cancel()
        try:
            await _mcp_discovery_task
        except asyncio.CancelledError:
            pass
        _mcp_discovery_task = None
    global _mcp_health_task
    if _mcp_health_task is not None:
        _mcp_health_task.cancel()
        try:
            await _mcp_health_task
        except asyncio.CancelledError:
            pass
        _mcp_health_task = None
    global _catalog_refresh_task
    if _catalog_refresh_task is not None:
        _catalog_refresh_task.cancel()
        try:
            await _catalog_refresh_task
        except asyncio.CancelledError:
            pass
        _catalog_refresh_task = None
    global _mcp_catalog_digest_task
    if _mcp_catalog_digest_task is not None:
        _mcp_catalog_digest_task.cancel()
        try:
            await _mcp_catalog_digest_task
        except asyncio.CancelledError:
            pass
        _mcp_catalog_digest_task = None
    global _catalog_graph_task
    if _catalog_graph_task is not None:
        _catalog_graph_task.cancel()
        try:
            await _catalog_graph_task
        except asyncio.CancelledError:
            pass
        _catalog_graph_task = None
    global _usage_sweep_task
    if _usage_sweep_task is not None:
        _usage_sweep_task.cancel()
        try:
            await _usage_sweep_task
        except asyncio.CancelledError:
            pass
        _usage_sweep_task = None
    global _lint_waiver_expiry_task
    if _lint_waiver_expiry_task is not None:
        _lint_waiver_expiry_task.cancel()
        try:
            await _lint_waiver_expiry_task
        except asyncio.CancelledError:
            pass
        _lint_waiver_expiry_task = None
    global _verification_schedule_task
    if _verification_schedule_task is not None:
        _verification_schedule_task.cancel()
        try:
            await _verification_schedule_task
        except asyncio.CancelledError:
            pass
        _verification_schedule_task = None
    global _pact_remediation_task
    if _pact_remediation_task is not None:
        _pact_remediation_task.cancel()
        try:
            await _pact_remediation_task
        except asyncio.CancelledError:
            pass
        _pact_remediation_task = None
    global _mock_activity_flush_task
    if _mock_activity_flush_task is not None:
        _mock_activity_flush_task.cancel()
        try:
            await _mock_activity_flush_task
        except asyncio.CancelledError:
            pass
        _mock_activity_flush_task = None
        # Whatever was served since the last tick is written before the connection closes.
        from .mock_data_plane import flush_activity

        await asyncio.to_thread(flush_activity, db)
    global _async_job_retention_task
    if _async_job_retention_task is not None:
        _async_job_retention_task.cancel()
        try:
            await _async_job_retention_task
        except asyncio.CancelledError:
            pass
        _async_job_retention_task = None
    global _document_lifecycle_task
    if _document_lifecycle_task is not None:
        _document_lifecycle_task.cancel()
        try:
            await _document_lifecycle_task
        except asyncio.CancelledError:
            pass
        _document_lifecycle_task = None
    global _repository_webhook_secret_task
    if _repository_webhook_secret_task is not None:
        _repository_webhook_secret_task.cancel()
        try:
            await _repository_webhook_secret_task
        except asyncio.CancelledError:
            pass
        _repository_webhook_secret_task = None
    global _repository_webhook_ip_range_task
    if _repository_webhook_ip_range_task is not None:
        _repository_webhook_ip_range_task.cancel()
        try:
            await _repository_webhook_ip_range_task
        except asyncio.CancelledError:
            pass
        _repository_webhook_ip_range_task = None
    global _sdk_regen_task
    if _sdk_regen_task is not None:
        _sdk_regen_task.cancel()
        try:
            await _sdk_regen_task
        except asyncio.CancelledError:
            pass
        _sdk_regen_task = None
    global _export_auto_task
    if _export_auto_task is not None:
        _export_auto_task.cancel()
        try:
            await _export_auto_task
        except asyncio.CancelledError:
            pass
        _export_auto_task = None
    close_sweep_databases()
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
def root():
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


@app.get(
    "/v1/schema/{tenant_slug}/{project_slug}/{version_slug}",
    responses={
        200: {
            "description": "The version's OpenAPI document.",
            "headers": {
                "ETag": {
                    "description": "The SHA-256 of the response body, in double quotes.",
                    "schema": {"type": "string"},
                },
                "X-Apiome-Snapshot-Sha256": {
                    "description": "The SHA-256 of the frozen snapshot; only sent for a frozen version.",
                    "schema": {"type": "string"},
                },
            },
        },
        304: {"description": "The document still matches an ETag sent in If-None-Match; no body."},
        503: {"description": "The version is frozen and its stored document cannot be read."},
    },
)
def get_version_openapi_spec(
    tenant_slug: str,
    project_slug: str,
    version_slug: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None, description="API key for private versions (alternative to X-API-Key header)"),
    if_none_match: Optional[str] = Header(
        None,
        alias="If-None-Match",
        description=(
            "An ETag from an earlier response; the answer is 304 with no body when the document has not changed."
        ),
    ),
) -> Response:
    """
    Get the complete OpenAPI specification for all classes in a version.

    The document is rendered once per change of the version and kept in the document store
    (COA-5.5, #7081); later requests stream the stored bytes. The response carries
    ``ETag: "<sha256>"``, the SHA-256 of the body. Send it back as ``If-None-Match`` to get
    ``304 Not Modified`` with no body while the document is unchanged.

    Args:
        tenant_slug: The tenant slug
        project_slug: The project slug
        version_slug: The version ID (e.g., "1.0.0")
        x_api_key: Optional API key for private versions (header)
        api_key: Optional API key for private versions (query, for links)
        if_none_match: Optional ETag(s) the client already holds

    Returns:
        OpenAPI 3.1.0 specification in JSON format, or 304 when ``If-None-Match`` matches
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

    version_record_id = str(version['id'])
    tenant_id = str(version.get('tenant_id') or '')

    # A frozen version (#3214) serves its stored snapshot byte-for-byte, and counts the download.
    snapshot = db.get_spec_snapshot(version_record_id)
    if snapshot:
        sha256 = str(snapshot['sha256']).strip()
        headers = {"ETag": etag_for(sha256), "X-Apiome-Snapshot-Sha256": sha256}
        if etag_matches(if_none_match, sha256):
            return Response(status_code=304, headers=headers)
        # The bytes are the version's frozen_schema object (COA-5.5, #7081); a snapshot frozen
        # before that, or with the db backend, still has them in its row.
        row = db.get_spec_snapshot(version_record_id, with_content=True) or {}
        content = row.get('content')
        stream = io.BytesIO(content) if content is not None else open_frozen_schema(tenant_id, sha256)
        if stream is None:
            raise HTTPException(
                status_code=503,
                detail="The frozen document of this version cannot be read from the document store"
            )
        db.record_spec_snapshot_download(version_record_id)
        headers["Content-Length"] = str(int(snapshot['size_bytes']))
        return StreamingResponse(iter_stream(stream), media_type="application/json", headers=headers)

    # Otherwise the rendered document of the version's current content: stored bytes when it was
    # rendered before, generated from classes, properties and paths (and stored) when it was not.
    document = rendered_document(version_record_id, KIND_OPENAPI, tenant_id=tenant_id, database=db)
    if document is None:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {tenant_slug}/{project_slug}/{version_slug}"
        )
    headers = {"ETag": document.etag}
    if etag_matches(if_none_match, document.sha256):
        return Response(status_code=304, headers=headers)
    headers["Content-Length"] = str(document.size_bytes)
    return StreamingResponse(iter_stream(document.open_stream()), media_type=document.media_type, headers=headers)


@app.get("/v1/schema/{tenant_slug}/{project_slug}/{version_slug}/{class_name}")
def get_class_openapi_spec(
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
def get_swagger_ui(
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

    # The document /v1/schema serves, read through the rendered document cache (COA-5.14, #7090)
    openapi_spec = revision_openapi(
        version,
        tenant_slug,
        version.get('tenant_id'),
        database=db,
        project_slug=project_slug,
        version_label=version_slug,
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
def get_version_arazzo_spec(
    tenant_slug: str,
    project_slug: str,
    version_slug: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None, description="API key for private versions (alternative to X-API-Key header)"),
    accept: Optional[str] = Header(None),
    arazzo_version: Optional[str] = Query(
        None,
        description=(
            "Arazzo specification version to write: any 1.0.x or 1.1.x version, for "
            "example `1.0.1` or `1.1.0`. Defaults to 1.0.1, because the generated "
            "document's only source description is the version's OpenAPI schema."
        ),
    ),
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
        arazzo_version: Arazzo version to write (``1.0.1`` / ``1.1.0`` …); ``None`` for the default

    Returns:
        Arazzo 1.0.x / 1.1.x specification in JSON or YAML format

    Raises:
        HTTPException: 400 when ``arazzo_version`` is not a supported Arazzo version
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
    try:
        arazzo_spec = generate_arazzo_spec(
            tenant_slug,
            project_slug,
            version_slug,
            classes,
            version.get('project_description'),
            arazzo_version=arazzo_version,
        )
    except ArazzoVersionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
def get_class_arazzo_spec(
    tenant_slug: str,
    project_slug: str,
    version_slug: str,
    class_name: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    accept: Optional[str] = Header(None),
    arazzo_version: Optional[str] = Query(
        None,
        description=(
            "Arazzo specification version to write: any 1.0.x or 1.1.x version, for "
            "example `1.0.1` or `1.1.0`. Defaults to 1.0.1, because the generated "
            "document's only source description is the version's OpenAPI schema."
        ),
    ),
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
        arazzo_version: Arazzo version to write (``1.0.1`` / ``1.1.0`` …); ``None`` for the default

    Returns:
        Arazzo 1.0.x / 1.1.x specification for the class in JSON or YAML format

    Raises:
        HTTPException: 400 when ``arazzo_version`` is not a supported Arazzo version
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
    try:
        arazzo_spec = generate_class_arazzo_spec(
            tenant_slug,
            project_slug,
            version_slug,
            class_data,
            arazzo_version=arazzo_version,
        )
    except ArazzoVersionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
def get_version_jsonschema_spec(
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

    # Every class's properties in one query (DBP-1.6, #7189)
    all_properties = db.get_properties_for_classes([class_data['id'] for class_data in classes])

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
def get_class_jsonschema_spec(
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

