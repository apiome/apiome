"""SDK generation settings & branding endpoints — SDK-3.4 (#4494).

Six routes, three at project scope and three at tenant scope:

```
GET|PUT|DELETE /v1/projects/{tenant_slug}/{project_ref}/sdk-settings
GET|PUT|DELETE /v1/tenants/{tenant_slug}/governance/sdk-generation-settings
```

**A GET always answers, and never materialises a row.** A tenant that has configured nothing gets
an empty settings body with ``source: "default"`` — the same contract CTG-4.5's policy routes use,
and the reason a surface can call this unconditionally before branding an artifact.

**A GET returns three different things on purpose.** ``settings`` is the merged result,
``resolved`` is that result with its tokens substituted for the addressed scope (the package names
a publisher would actually use), and ``scopeBody`` is what is saved at *exactly* this scope. An
editor needs the third: only the raw body distinguishes a key that is absent (inherit from the
tenant) from one present as ``null`` (deliberately none).

**Permissions reuse what this surface already has, and no new RBAC resource is added.** These
settings say how a project's published API is packaged and branded, so reading them is
``projects:view`` and changing them is ``projects:edit``. Adding a resource costs four synchronised
edits (the role grid, the REST ``Resource`` enum, the enforcement call sites, and the UI role
matrix), and a permission that would always be granted alongside an existing one earns none of them
— the identical argument CTG-4.4 and CTG-4.5 made.

**No new API-key scope either.** A restricted CI key today carries ``diff:read`` or ``lint:read``,
neither of which has anything to do with package naming, and a full-access key already reaches
these routes. A third scope would have to be minted, picked in the Control Panel and carried
through apiome-db's key CLI for no extra safety.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission
from .revision_deprecation import is_uuid_string
from .sdk_generation_settings import (
    ECOSYSTEMS,
    LICENSE_HEADER_MAX_CHARS,
    PATTERN_TOKENS,
    USER_AGENT_MAX_CHARS,
    PatternContext,
    SdkGenerationSettingsOut,
    SdkSettingsError,
)
from .sdk_generation_settings_store import (
    audit_detail,
    clear_settings,
    load_settings,
    save_settings,
)

logger = logging.getLogger(__name__)

__all__ = ["router", "tenant_router"]

#: Project-scoped surface. Shares the ``/v1/projects`` prefix, and ``main`` registers it *after*
#: ``projects_router``: ``/{tenant}/{project}/sdk-settings`` would otherwise also match
#: ``/{tenant}/by-slug/{project_slug}`` for a project whose slug happens to be ``sdk-settings``.
router = APIRouter(prefix="/v1/projects", tags=["sdk-generation"])

#: Tenant-scoped defaults, beside the other governance settings.
tenant_router = APIRouter(prefix="/v1/tenants", tags=["governance"])

#: Audit actions this module writes.
AUDIT_SETTINGS_UPDATE = "governance.sdk_generation_settings.update"
AUDIT_SETTINGS_CLEAR = "governance.sdk_generation_settings.clear"

_SETTINGS_DESCRIPTION = (
    "Settings are merged **key by key**, tenant first: a project that overrides only its "
    "user-agent still inherits its tenant's package patterns. `packageNamePatterns` merges one "
    "ecosystem at a time.\n\n"
    "A key **absent** from a body inherits the next scope up; a key present as **`null`** is "
    "deliberately none, and blocks that inheritance.\n\n"
    f"Patterns may contain the tokens {', '.join('`{' + t + '}`' for t in PATTERN_TOKENS)}, "
    "substituted from the scope being resolved. A package pattern is validated by resolving it "
    "against probe values and checking the result against its registry's naming rules, so "
    "`@acme/{project}-sdk` is accepted and `@ACME/{project}` is not.\n\n"
    f"Ecosystems: {', '.join('`' + e + '`' for e in ECOSYSTEMS)}. `licenseHeader` is capped at "
    f"{LICENSE_HEADER_MAX_CHARS:,} characters; `userAgent` at {USER_AGENT_MAX_CHARS} and to "
    "characters legal in an HTTP header."
)


class SdkGenerationSettingsPutRequest(BaseModel):
    """Body for saving SDK generation settings.

    Attributes:
        settings: The ``sdk.generation-settings.v1`` body. Only the keys it names are stored.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    settings: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "The settings to save. Only the keys named here are stored, so a body naming one "
            "setting configures exactly that one and leaves the rest inheriting."
        ),
    )


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the authenticated tenant id, or refuse.

    Args:
        auth_data: The authenticated principal.

    Returns:
        The tenant id.

    Raises:
        HTTPException: 403 when the credential carries no tenant context.
    """
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=403, detail="No tenant context for this credential."
        )
    return str(tenant_id)


def _resolve_project(tenant_id: str, project_ref: str) -> Dict[str, Any]:
    """Resolve a project reference (id or slug) within the tenant, or refuse.

    Kept here rather than in a service module because it is the only project lookup this feature
    performs; it is the same id-or-slug dispatch every project-addressed surface does
    (:func:`app.deploy_gate_service.resolve_project`,
    :func:`app.consumer_contract_store.resolve_project`), over the same two accessors.

    Args:
        tenant_id: The caller's tenant.
        project_ref: A project UUID or slug.

    Returns:
        The project row — the slug on it is what ``{project}`` resolves to.

    Raises:
        HTTPException: 404 when nothing in this tenant answers to the reference.
    """
    ref = (project_ref or "").strip()
    row: Optional[Dict[str, Any]] = None
    if is_uuid_string(ref):
        row = db.get_project_by_id(ref, tenant_id)
    if row is None and ref:
        row = db.get_project_by_slug(ref, tenant_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "project-not-found",
                "message": f"No project named {project_ref!r} is visible in this tenant.",
            },
        )
    return row


def _settings_error(exc: SdkSettingsError) -> HTTPException:
    """Map a settings refusal onto ``422`` with every problem listed.

    Args:
        exc: The refusal.

    Returns:
        The exception to raise.
    """
    return HTTPException(
        status_code=422,
        detail={"code": "sdk-generation-settings-invalid", "errors": list(exc.errors)},
    )


def _audit(
    *,
    tenant_id: str,
    action: str,
    auth_data: Dict[str, Any],
    target: Optional[str],
    detail: Dict[str, Any],
) -> None:
    """Write one governance audit row (best-effort).

    Audit failures are logged and swallowed: a settings change that succeeded must not be reported
    as a failure because its audit row could not be appended.

    Args:
        tenant_id: The tenant whose settings changed.
        action: The audit action.
        auth_data: The authenticated principal.
        target: The scope this concerns.
        detail: The payload to record.
    """
    try:
        db.write_access_audit(
            tenant_id=tenant_id,
            action=action,
            actor_id=get_authenticated_user_id(auth_data),
            actor_label=auth_data.get("user_email") or auth_data.get("user_name"),
            target=target,
            source="api",
            detail=detail,
        )
    except Exception:  # noqa: BLE001 - auditing never fails the governed action
        logger.warning(
            "Failed to audit %s for tenant %s", action, tenant_id, exc_info=True
        )


def _project_context(tenant_slug: str, project: Dict[str, Any]) -> PatternContext:
    """Build the substitution context for a project scope.

    ``{version}`` is deliberately left empty: settings are resolved for a project, not for one
    revision, so a pattern naming a version renders it away here and the eventual publisher
    substitutes it. ``{year}`` fills from the clock.

    Args:
        tenant_slug: The tenant's slug, from the URL that authenticated the request.
        project: The resolved project row.

    Returns:
        The context.
    """
    return PatternContext(
        tenant=str(tenant_slug or ""), project=str(project.get("slug") or "")
    )


# -------------------------------------------------------------------------------------------
# Project scope
# -------------------------------------------------------------------------------------------


@router.get(
    "/{tenant_slug}/{project_ref}/sdk-settings",
    response_model=SdkGenerationSettingsOut,
    tags=["sdk-generation"],
    summary="Get the generation settings in force for a project",
    description=(
        "The package naming, licence header and user-agent this project's generated artifacts "
        "carry, and where they came from: `project` (an override saved here), `tenant` (the "
        "workspace default), `merged` (both), or `default` (nothing saved anywhere).\n\n"
        "`resolved` carries the same settings with their tokens substituted for this project — "
        "the package names a publisher would actually use.\n\n" + _SETTINGS_DESCRIPTION + "\n\n"
        "Requires `projects:view`."
    ),
    responses={404: {"description": "Project not found in this tenant."}},
)
async def get_project_sdk_settings(
    tenant_slug: str,
    project_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SdkGenerationSettingsOut:
    """Return the generation settings in force for a project.

    Args:
        tenant_slug: Tenant in the URL (the auth tenant scopes every read).
        project_ref: The project's id or slug.
        auth_data: Authenticated principal.

    Returns:
        The resolved settings.

    Raises:
        HTTPException: 403 without ``projects:view``; 404 when the project is unknown.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = _tenant_id(auth_data)
    project = _resolve_project(tenant_id, project_ref)
    return load_settings(
        tenant_id, str(project["id"]), _project_context(tenant_slug, project)
    )


@router.put(
    "/{tenant_slug}/{project_ref}/sdk-settings",
    response_model=SdkGenerationSettingsOut,
    tags=["sdk-generation"],
    summary="Set this project's generation settings",
    description=(
        "Save an override for one project, replacing whatever it held. The workspace defaults "
        "still supply every key this body does not name.\n\n" + _SETTINGS_DESCRIPTION + "\n\n"
        "Requires `projects:edit`. Audited as `governance.sdk_generation_settings.update`."
    ),
    responses={
        404: {"description": "Project not found in this tenant."},
        422: {"description": "The settings body is not valid."},
    },
)
async def put_project_sdk_settings(
    tenant_slug: str,
    project_ref: str,
    body: SdkGenerationSettingsPutRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SdkGenerationSettingsOut:
    """Save a project's generation-settings override.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        body: The settings body.
        auth_data: Authenticated principal.

    Returns:
        The settings now in force for the project.

    Raises:
        HTTPException: 403 without ``projects:edit``; 404 when the project is unknown; 422 when
            the settings are not valid.
    """
    actor_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = _tenant_id(auth_data)
    project = _resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    try:
        saved = save_settings(
            tenant_id,
            project_id=project_id,
            body=body.settings,
            actor_id=actor_id,
            context=_project_context(tenant_slug, project),
        )
    except SdkSettingsError as exc:
        raise _settings_error(exc) from exc
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_SETTINGS_UPDATE,
        auth_data=auth_data,
        target=saved.project_settings_id,
        detail={"projectId": project_id, **audit_detail(saved)},
    )
    return saved


@router.delete(
    "/{tenant_slug}/{project_ref}/sdk-settings",
    response_model=SdkGenerationSettingsOut,
    tags=["sdk-generation"],
    summary="Drop this project's override",
    description=(
        "Remove the project's settings, so it inherits the workspace defaults again. Returns the "
        "settings **now** in force, not a bare `204`, so a caller can see what it fell back to.\n\n"
        "Requires `projects:edit`. Audited as `governance.sdk_generation_settings.clear`."
    ),
    responses={404: {"description": "Project not found in this tenant."}},
)
async def delete_project_sdk_settings(
    tenant_slug: str,
    project_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SdkGenerationSettingsOut:
    """Drop a project's generation-settings override.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        auth_data: Authenticated principal.

    Returns:
        The settings now in force for the project.

    Raises:
        HTTPException: 403 without ``projects:edit``; 404 when the project is unknown.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = _tenant_id(auth_data)
    project = _resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    removed = clear_settings(tenant_id, project_id=project_id)
    now_in_force = load_settings(
        tenant_id, project_id, _project_context(tenant_slug, project)
    )
    if removed:
        _audit(
            tenant_id=tenant_id,
            action=AUDIT_SETTINGS_CLEAR,
            auth_data=auth_data,
            target=project_id,
            detail={"projectId": project_id, **audit_detail(now_in_force)},
        )
    return now_in_force


# -------------------------------------------------------------------------------------------
# Tenant scope
# -------------------------------------------------------------------------------------------


@tenant_router.get(
    "/{tenant_slug}/governance/sdk-generation-settings",
    response_model=SdkGenerationSettingsOut,
    tags=["governance"],
    summary="Get the workspace generation defaults",
    description=(
        "The package naming, licence header and user-agent every project in the workspace "
        "inherits unless it overrides them.\n\n" + _SETTINGS_DESCRIPTION + "\n\n"
        "Requires `projects:view`."
    ),
)
async def get_tenant_sdk_settings(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SdkGenerationSettingsOut:
    """Return the tenant-wide generation defaults.

    Args:
        tenant_slug: Tenant in the URL.
        auth_data: Authenticated principal.

    Returns:
        The saved defaults, or an empty ``default`` response when there are none.

    Raises:
        HTTPException: 403 without ``projects:view``.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = _tenant_id(auth_data)
    return load_settings(tenant_id, None, PatternContext(tenant=str(tenant_slug or "")))


@tenant_router.put(
    "/{tenant_slug}/governance/sdk-generation-settings",
    response_model=SdkGenerationSettingsOut,
    tags=["governance"],
    summary="Set the workspace generation defaults",
    description=(
        "Save the workspace-wide defaults, replacing whatever they held. Projects that have saved "
        "their own override keep it for the keys it names.\n\n" + _SETTINGS_DESCRIPTION + "\n\n"
        "Requires `projects:edit`. Audited as `governance.sdk_generation_settings.update`."
    ),
    responses={422: {"description": "The settings body is not valid."}},
)
async def put_tenant_sdk_settings(
    tenant_slug: str,
    body: SdkGenerationSettingsPutRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SdkGenerationSettingsOut:
    """Save the tenant-wide generation defaults.

    Args:
        tenant_slug: Tenant in the URL.
        body: The settings body.
        auth_data: Authenticated principal.

    Returns:
        The stored defaults.

    Raises:
        HTTPException: 403 without ``projects:edit``; 422 when the settings are not valid.
    """
    actor_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = _tenant_id(auth_data)
    try:
        saved = save_settings(
            tenant_id,
            project_id=None,
            body=body.settings,
            actor_id=actor_id,
            context=PatternContext(tenant=str(tenant_slug or "")),
        )
    except SdkSettingsError as exc:
        raise _settings_error(exc) from exc
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_SETTINGS_UPDATE,
        auth_data=auth_data,
        target=saved.tenant_settings_id,
        detail=audit_detail(saved),
    )
    return saved


@tenant_router.delete(
    "/{tenant_slug}/governance/sdk-generation-settings",
    response_model=SdkGenerationSettingsOut,
    tags=["governance"],
    summary="Clear the workspace generation defaults",
    description=(
        "Remove the workspace defaults. Project overrides are **not** cascaded away — they were "
        "configured deliberately. Returns the settings now in force at workspace scope.\n\n"
        "Requires `projects:edit`. Audited as `governance.sdk_generation_settings.clear`."
    ),
)
async def delete_tenant_sdk_settings(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SdkGenerationSettingsOut:
    """Clear the tenant-wide generation defaults.

    Args:
        tenant_slug: Tenant in the URL.
        auth_data: Authenticated principal.

    Returns:
        The settings now in force at workspace scope (an empty ``default`` response).

    Raises:
        HTTPException: 403 without ``projects:edit``.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = _tenant_id(auth_data)
    removed = clear_settings(tenant_id, project_id=None)
    now_in_force = load_settings(
        tenant_id, None, PatternContext(tenant=str(tenant_slug or ""))
    )
    if removed:
        _audit(
            tenant_id=tenant_id,
            action=AUDIT_SETTINGS_CLEAR,
            auth_data=auth_data,
            target=tenant_id,
            detail=audit_detail(now_in_force),
        )
    return now_in_force
