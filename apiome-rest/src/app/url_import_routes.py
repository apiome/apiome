"""URL import refresh routes (RAR-6.1, #3538).

A spec imported into a project from a URL is kept up to date by the URL refresh sweep
(:mod:`app.url_import_refresh_sweep`). These routes record and manage those URL lineages:

* ``POST  /v1/tenants/{tenant}/url-imports`` — record a URL import that just succeeded
  (``imports:create``). REST fetches the URL once to store its ``ETag`` / ``Last-Modified`` and
  checksum; an import fetched with credentials is recorded but never refreshed.
* ``GET   /v1/tenants/{tenant}/url-imports`` — list them, optionally for one project
  (``imports:view``).
* ``PATCH /v1/tenants/{tenant}/url-imports/{id}`` — turn a lineage's refresh on or off and set its
  cadence (``imports:edit``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Literal, Mapping, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import url_import_store as store
from .auth import validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission
from .revision_deprecation import is_uuid_string
from .url_import_refresh import UrlImportError
from .url_import_refresh_sweep import record_url_import

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/tenants", tags=["url-imports"])

UrlImportStatus = Literal["up-to-date", "refreshing", "refreshed", "diverged", "failed"]


class UrlImportRecordRequest(BaseModel):
    """A URL import that just succeeded."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    project_id: str = Field(alias="projectId", description="The project the import landed in.")
    url: str = Field(description="The http/https URL the spec was imported from.", max_length=4096)
    version_id: Optional[str] = Field(
        default=None,
        alias="versionId",
        description="The version the import produced (versions.id); its content is the manual-edit baseline.",
    )
    source_kind: str = Field(
        default="openapi", alias="sourceKind", description="Importer kind (openapi, arazzo).", max_length=128
    )
    format_override: Optional[str] = Field(
        default=None, alias="formatOverride", description="Resolved spec format, when recorded.", max_length=64
    )
    content_type: Optional[str] = Field(
        default=None, alias="contentType", description="MIME type the document was parsed as.", max_length=128
    )
    options: Dict[str, Any] = Field(
        default_factory=dict, description="The import options, verbatim; a refresh replays them."
    )
    authenticated: bool = Field(
        default=False,
        description="The import was fetched with credentials. Recorded but never refreshed; credentials are not sent.",
    )


class UrlImportSettingsPatch(BaseModel):
    """Change a URL lineage's refresh; an omitted field is left as it is."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    auto_refresh_enabled: Optional[bool] = Field(
        default=None, alias="autoRefreshEnabled", description="Refresh this URL on its cadence."
    )
    refresh_interval_seconds: Optional[int] = Field(
        default=None,
        alias="refreshIntervalSeconds",
        ge=1,
        description="Seconds between checks (raised to the deployment floor). Omit to keep it.",
    )
    use_default_interval: bool = Field(
        default=False, alias="useDefaultInterval", description="Go back to the deployment's default cadence."
    )


class UrlImportOut(BaseModel):
    """A URL import lineage and its refresh state."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    project_id: str = Field(alias="projectId")
    project_name: Optional[str] = Field(default=None, alias="projectName")
    project_slug: Optional[str] = Field(default=None, alias="projectSlug")
    url: str
    source_kind: str = Field(alias="sourceKind")
    authenticated: bool = Field(description="Imported with credentials: never refreshed.")
    refreshable: bool = Field(description="On, and not authenticated: the sweep checks it.")
    auto_refresh_enabled: bool = Field(alias="autoRefreshEnabled")
    refresh_interval_seconds: Optional[int] = Field(
        default=None, alias="refreshIntervalSeconds", description="Own cadence; null means the default."
    )
    effective_interval_seconds: int = Field(
        alias="effectiveIntervalSeconds", description="The cadence the sweep uses."
    )
    etag: Optional[str] = Field(default=None, description="ETag recorded at the last import.")
    last_modified: Optional[str] = Field(
        default=None, alias="lastModified", description="Last-Modified recorded at the last import."
    )
    last_version_id: Optional[str] = Field(default=None, alias="lastVersionId")
    last_checked_at: Optional[str] = Field(default=None, alias="lastCheckedAt")
    last_refreshed_at: Optional[str] = Field(default=None, alias="lastRefreshedAt")
    last_status: Optional[UrlImportStatus] = Field(default=None, alias="lastStatus")
    last_reason: Optional[str] = Field(
        default=None,
        alias="lastReason",
        description="Why: not-modified, idempotent, stale, newer-content, baseline, manual-edit, or an error class.",
    )
    last_error: Optional[str] = Field(default=None, alias="lastError")
    consecutive_failures: int = Field(default=0, alias="consecutiveFailures")
    backoff_until: Optional[str] = Field(default=None, alias="backoffUntil")
    created_at: Optional[str] = Field(default=None, alias="createdAt")
    updated_at: Optional[str] = Field(default=None, alias="updatedAt")


class UrlImportList(BaseModel):
    """URL import lineages, newest first."""

    model_config = ConfigDict(populate_by_name=True)

    url_imports: List[UrlImportOut] = Field(alias="urlImports")


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value is not None else None)


def _out(row: Mapping[str, Any]) -> UrlImportOut:
    """A stored row as the API returns it."""
    from .config import settings
    from .repository_refresh_cadence import resolve_refresh_interval

    effective = resolve_refresh_interval(
        row.get("refresh_interval_seconds"),
        default_seconds=int(settings.refresh_default_interval_seconds),
        floor_seconds=int(settings.refresh_min_interval_seconds),
    )
    return UrlImportOut(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        project_name=row.get("project_name"),
        project_slug=row.get("project_slug"),
        url=str(row["url"]),
        source_kind=str(row.get("source_kind") or "openapi"),
        authenticated=bool(row.get("authenticated")),
        refreshable=bool(row.get("auto_refresh_enabled")) and not bool(row.get("authenticated")),
        auto_refresh_enabled=bool(row.get("auto_refresh_enabled")),
        refresh_interval_seconds=row.get("refresh_interval_seconds"),
        effective_interval_seconds=int(effective),
        etag=row.get("etag"),
        last_modified=row.get("last_modified"),
        last_version_id=str(row["last_version_id"]) if row.get("last_version_id") else None,
        last_checked_at=_iso(row.get("last_checked_at")),
        last_refreshed_at=_iso(row.get("last_refreshed_at")),
        last_status=row.get("last_status"),
        last_reason=row.get("last_reason"),
        last_error=row.get("last_error"),
        consecutive_failures=int(row.get("consecutive_failures") or 0),
        backoff_until=_iso(row.get("backoff_until")),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )


def _tenant_id(auth_data: Mapping[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for URL imports.")
    return str(tenant_id)


@router.post(
    "/{tenant_slug}/url-imports",
    response_model=UrlImportOut,
    response_model_by_alias=True,
    status_code=201,
    summary="Record a URL import for auto-refresh",
)
async def record_url_import_route(
    tenant_slug: str,
    body: UrlImportRecordRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> UrlImportOut:
    """Record a URL import that just succeeded, so the URL refresh sweep keeps it up to date.

    REST fetches the URL once (SSRF-guarded) to store the ``ETag``, ``Last-Modified`` and SHA-256
    a refresh compares with. When that fetch fails the lineage is still recorded, with the error,
    and the first check anchors on what the URL serves then. Recording the same URL for the same
    project again replaces the stored spec and anchors and keeps the refresh settings.

    Raises:
        HTTPException: 404 when the project is not the tenant's; 422 for a URL that is not
            http/https or carries credentials, or a version that is not the project's.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    actor_id = enforce_permission(db, auth_data, Resource.IMPORTS, Action.CREATE, target="url-imports")
    if not is_uuid_string(body.project_id) or not db.get_project_by_id(body.project_id, tenant_id):
        raise HTTPException(status_code=404, detail=f"Project not found: {body.project_id}")
    if body.version_id:
        version = db.get_version_by_id(body.version_id, tenant_id)
        if not version or str(version.get("project_id")) != body.project_id:
            raise HTTPException(status_code=422, detail="versionId is not a version of this project.")
    try:
        row = await asyncio.to_thread(
            record_url_import,
            db,
            tenant_id=tenant_id,
            user_id=actor_id,
            project_id=body.project_id,
            url=body.url,
            source_kind=body.source_kind,
            format_override=body.format_override,
            content_type=body.content_type,
            options=body.options,
            authenticated=body.authenticated,
            version_id=body.version_id,
        )
    except UrlImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _out(store.get_spec(db, tenant_id, str(row["id"])) or row)


@router.get(
    "/{tenant_slug}/url-imports",
    response_model=UrlImportList,
    response_model_by_alias=True,
    summary="List URL imports and their refresh state",
)
async def list_url_imports(
    tenant_slug: str,
    project_id: Optional[str] = Query(default=None, alias="projectId", description="Only this project's."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> UrlImportList:
    """List the tenant's URL imports, newest first, with when each was last checked and refreshed."""
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.VIEW, target="url-imports")
    if project_id is not None and not is_uuid_string(project_id):
        return UrlImportList(url_imports=[])
    return UrlImportList(url_imports=[_out(row) for row in store.list_specs(db, tenant_id, project_id=project_id)])


@router.patch(
    "/{tenant_slug}/url-imports/{url_import_id}",
    response_model=UrlImportOut,
    response_model_by_alias=True,
    summary="Turn a URL import's refresh on or off, or set its cadence",
)
async def patch_url_import(
    tenant_slug: str,
    url_import_id: str,
    body: UrlImportSettingsPatch,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> UrlImportOut:
    """Change a URL import's refresh (``imports:edit``). Turning it on clears any backoff.

    Raises:
        HTTPException: 404 when the URL import is not the tenant's.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.EDIT, target=f"url-imports:{url_import_id}")
    row = (
        store.update_settings(
            db,
            tenant_id,
            url_import_id,
            auto_refresh_enabled=body.auto_refresh_enabled,
            refresh_interval_seconds=body.refresh_interval_seconds,
            clear_interval=body.use_default_interval,
        )
        if is_uuid_string(url_import_id)
        else None
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"URL import not found: {url_import_id}")
    return _out(store.get_spec(db, tenant_id, url_import_id) or row)
