"""Package publishing endpoints — SDK-4.1 (#4495).

Nine routes over two things a tenant needs to publish an SDK: somewhere to put the registry token,
and something to press.

```
GET|PUT|DELETE /v1/tenants/{t}/governance/sdk-registry-credentials[/{ecosystem}]
GET|PUT|DELETE /v1/projects/{t}/{project}/sdk-registry-credentials[/{ecosystem}]
POST           /v1/projects/{t}/{project}/sdk-publish
GET            /v1/projects/{t}/{project}/sdk-publish-runs[/{run_id}]
```

**Publishing is opt-in per request.** ``POST …/sdk-publish`` defaults to ``dryRun: true``: it
resolves the branding, the credential and the version number, builds the exact archive a real
publish would upload, reports its digest — and uploads nothing. Sending ``dryRun: false`` is the
deliberate act. A default that published would make a mis-typed request a public release.

**A credential is write-only.** ``PUT`` stores a token; ``GET`` describes what is stored — the
ecosystem, the registry, the token's public scheme prefix, its length and a truncated digest — and
there is no route that returns one. That is the same contract as a webhook signing secret, and the
digest is what lets an operator confirm a rotation without the API ever handing a token back.

**Permissions reuse what these surfaces already have, and no new RBAC resource is added.** Reading
how a project is configured to publish is ``projects:view`` and changing it is ``projects:edit``;
releasing a package — including a dry run, which decrypts a credential and predicts the next
version — is ``versions:publish``. Adding a resource costs four synchronised edits (the role grid,
the REST ``Resource`` enum, the enforcement call sites, and the UI role matrix), and a permission
that would always be granted alongside an existing one earns none of them — the identical argument
CTG-4.4, CTG-4.5 and SDK-3.4 made.

**Every mutation is audited, and no audit row carries a token.** The credential audit records the
ecosystem, the scope and the token's fingerprint; the publish audit records the package
coordinates and the run id.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .envelope_crypto import EnvelopeEncryptionError
from .export_source import ExportSource, ExportSourceError, load_export_source
from .permissions import Action, Resource, enforce_permission
from .revision_deprecation import is_uuid_string
from .sdk_publish_pipeline import (
    PublishContext,
    PublishError,
    PublishOutcome,
    publish,
    run_row_to_outcome,
)
from .sdk_publish_version import PUBLISH_ECOSYSTEMS
from .sdk_registry_credentials import (
    DEFAULT_REGISTRY_URLS,
    REGISTRY_CREDENTIAL_SCHEMA_VERSION,
    TOKEN_MAX_CHARS,
    RegistryCredentialError,
    RegistryCredentialOut,
    credential_encryption_configured,
    delete_credential,
    list_credentials,
    save_credential,
)

logger = logging.getLogger(__name__)

__all__ = [
    "load_published_source",
    "resolve_project",
    "router",
    "tenant_id_of",
    "tenant_router",
    "write_audit",
]

#: Project-scoped surface. Shares the ``/v1/projects`` prefix, and ``main`` registers it *after*
#: ``projects_router`` for the same reason SDK-3.4's settings router is: ``/{tenant}/{project}/…``
#: would otherwise also match ``/{tenant}/by-slug/{project_slug}``.
router = APIRouter(prefix="/v1/projects", tags=["sdk-publishing"])

#: Tenant-wide credentials, beside the other governance settings.
tenant_router = APIRouter(prefix="/v1/tenants", tags=["governance"])

#: Audit actions this module writes.
AUDIT_CREDENTIAL_UPDATE = "governance.sdk_registry_credential.update"
AUDIT_CREDENTIAL_CLEAR = "governance.sdk_registry_credential.clear"
AUDIT_PUBLISH = "sdk.package_publish"

#: Largest history page. Publish runs are small rows, but an unbounded page is an unbounded
#: response.
MAX_HISTORY_LIMIT = 200

_CREDENTIAL_DESCRIPTION = (
    "A credential is **write-only**: this API stores the token encrypted at rest and never "
    "returns it. What comes back is its public scheme prefix (`npm_`, `pypi-`), its length and a "
    "truncated SHA-256 — enough to confirm which token is stored, not enough to use it.\n\n"
    "A **project** credential replaces the workspace one for that ecosystem. Unlike SDK-3.4's "
    "generation settings, credentials do not merge field by field: a token is atomic.\n\n"
    f"Ecosystems: {', '.join('`' + e + '`' for e in PUBLISH_ECOSYSTEMS)}. `gomod` is absent "
    "because a Go module is released by pushing a tag (SDK-4.2), not by uploading to a registry.\n\n"
    "`registryUrl` defaults to the ecosystem's public registry and must be `https://` — a publish "
    "token sent over plain HTTP is a token disclosed."
)


# ===========================================================================
# Request / response models
# ===========================================================================


class RegistryCredentialPutRequest(BaseModel):
    """Body for storing a registry credential.

    Attributes:
        token: The plaintext registry token. Sealed before it is written and never returned.
        registry_url: Where to publish; defaults to the ecosystem's public registry.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    token: str = Field(
        min_length=1,
        max_length=TOKEN_MAX_CHARS,
        description=(
            "The registry token — an npm automation token or a PyPI API token. Stored "
            "envelope-encrypted; never returned by any route."
        ),
    )
    registry_url: Optional[str] = Field(
        default=None,
        alias="registryUrl",
        description=(
            "Registry endpoint. Defaults to "
            + ", ".join(f"`{eco}` → `{url}`" for eco, url in DEFAULT_REGISTRY_URLS.items())
            + ". Must be `https://`."
        ),
    )


class RegistryCredentialListResponse(BaseModel):
    """The credentials configured for one scope.

    Attributes:
        schema_version: The projection's shape.
        scope: The scope that was addressed.
        encryption_configured: Whether this deployment can store credentials at all.
        ecosystems: Which ecosystems can be published to.
        credentials: One entry per stored credential, tenant-wide first.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(
        default=REGISTRY_CREDENTIAL_SCHEMA_VERSION, serialization_alias="schemaVersion"
    )
    scope: str
    encryption_configured: bool = Field(serialization_alias="encryptionConfigured")
    ecosystems: List[str]
    credentials: List[RegistryCredentialOut]


class SdkPublishRequest(BaseModel):
    """Body for a publish (or a dry run).

    Attributes:
        ecosystem: ``npm`` or ``pypi``.
        version: The revision to publish — a revision UUID or a version label. Defaults to the
            project's latest revision.
        dry_run: When ``true`` (the default), everything is resolved and built and nothing is
            uploaded.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ecosystem: str = Field(description="`npm` or `pypi`.")
    version: Optional[str] = Field(
        default=None,
        description="Revision UUID or version label. Defaults to the latest revision.",
    )
    dry_run: bool = Field(
        default=True,
        alias="dryRun",
        description=(
            "Validate without publishing. Defaults to **true**: uploading to a public registry is "
            "irreversible, so it is always the deliberate choice."
        ),
    )


class SdkPublishRunModel(BaseModel):
    """One publish run.

    Attributes:
        run_id: The ledger row.
        status: ``dry_run``, ``in_progress``, ``published``, ``already_published`` or ``failed``.
        dry_run: Whether anything was uploaded.
        ecosystem: ``npm`` or ``pypi``.
        package_name: The resolved package name.
        package_version: The version claimed.
        release_series: The series the counter was allocated under.
        regen_counter: Which release of that series this is.
        version_line: The version label the package version was derived from.
        registry_url: Where it published (or would have).
        credential_scope: Which scope supplied the credential.
        artifact_filename: The archive's filename.
        artifact_sha256: The archive's digest.
        artifact_bytes: The archive's size.
        operation_count: How many operations shipped snippets.
        truncated: Whether the API has more operations than one package carries snippets for.
        skipped: Operations no snippet is defined for.
        files: What is inside the archive (a dry run's report; empty for a stored run).
        provenance: The provenance embedded in the package's own metadata.
        log: The publish event log, redacted of secrets.
        error_code: Set when the run failed.
        error_message: Set when the run failed.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    run_id: Optional[str] = Field(default=None, serialization_alias="runId")
    status: str
    dry_run: bool = Field(serialization_alias="dryRun")
    ecosystem: str
    package_name: str = Field(serialization_alias="packageName")
    package_version: str = Field(serialization_alias="packageVersion")
    release_series: str = Field(serialization_alias="releaseSeries")
    regen_counter: int = Field(serialization_alias="regenCounter")
    version_line: Optional[str] = Field(default=None, serialization_alias="versionLine")
    registry_url: Optional[str] = Field(default=None, serialization_alias="registryUrl")
    credential_scope: Optional[str] = Field(default=None, serialization_alias="credentialScope")
    artifact_filename: Optional[str] = Field(default=None, serialization_alias="artifactFilename")
    artifact_sha256: Optional[str] = Field(default=None, serialization_alias="artifactSha256")
    artifact_bytes: Optional[int] = Field(default=None, serialization_alias="artifactBytes")
    operation_count: int = Field(default=0, serialization_alias="operationCount")
    truncated: bool = Field(default=False)
    skipped: List[Dict[str, str]] = Field(default_factory=list)
    files: List[Dict[str, Any]] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    log: List[Dict[str, Any]] = Field(default_factory=list)
    error_code: Optional[str] = Field(default=None, serialization_alias="errorCode")
    error_message: Optional[str] = Field(default=None, serialization_alias="errorMessage")


class SdkPublishRunListResponse(BaseModel):
    """A page of publish history.

    Attributes:
        runs: The rows, newest first.
        total: How many rows match.
        limit: The page size used.
        offset: The offset used.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    runs: List[SdkPublishRunModel]
    total: int
    limit: int
    offset: int


def _run_model(outcome: PublishOutcome) -> SdkPublishRunModel:
    """Project a pipeline outcome onto its wire model.

    Args:
        outcome: What the pipeline produced.

    Returns:
        The response model.
    """
    return SdkPublishRunModel(
        run_id=outcome.run_id,
        status=outcome.status,
        dry_run=outcome.dry_run,
        ecosystem=outcome.ecosystem,
        package_name=outcome.package_name,
        package_version=outcome.package_version,
        release_series=outcome.release_series,
        regen_counter=outcome.regen_counter,
        version_line=outcome.version_line,
        registry_url=outcome.registry_url,
        credential_scope=outcome.credential_scope,
        artifact_filename=outcome.artifact_filename,
        artifact_sha256=outcome.artifact_sha256,
        artifact_bytes=outcome.artifact_bytes,
        operation_count=outcome.operation_count,
        truncated=outcome.truncated,
        skipped=list(outcome.skipped),
        files=list(outcome.files),
        provenance=dict(outcome.provenance),
        log=list(outcome.log),
        error_code=outcome.error_code,
        error_message=outcome.error_message,
    )


# ===========================================================================
# Shared helpers — public because SDK-4.2's git delivery routes (app.sdk_git_delivery_routes)
# address the same projects and revisions the same way.
# ===========================================================================


def tenant_id_of(auth_data: Dict[str, Any]) -> str:
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
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def resolve_project(tenant_id: str, project_ref: str) -> Dict[str, Any]:
    """Resolve a project reference (id or slug) within the tenant, or refuse.

    The same id-or-slug dispatch every project-addressed surface does, over the same two accessors.

    Args:
        tenant_id: The caller's tenant.
        project_ref: A project UUID or slug.

    Returns:
        The project row.

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


def load_published_source(
    tenant_id: str,
    project_id: str,
    version: Optional[str],
    *,
    code_prefix: str = "sdk-publish",
    refusal: str = (
        "Only a published revision can be released as a package. Publish the version first, then "
        "publish its SDK."
    ),
) -> ExportSource:
    """Load a revision's canonical model, refusing one that is not published.

    A package is a public artifact, and a delivered SDK is the same package, so both are only ever
    built from a revision that is itself published within the workspace. Shared by SDK-4.1's publish
    route and SDK-4.2's git delivery route.

    Args:
        tenant_id: The caller's tenant.
        project_id: The resolved project id.
        version: A revision UUID or version label, or ``None`` for the latest revision.
        code_prefix: Prefix of the refusal codes (``sdk-publish`` → ``sdk-publish-not-published``).
        refusal: The message for an unpublished revision.

    Returns:
        The loaded :class:`~app.export_source.ExportSource`.

    Raises:
        HTTPException: The source loader's own status (404 unknown version, 422 no captured source)
            as ``<prefix>-source-unavailable``; 400 ``<prefix>-not-published`` for a revision that is
            not published.
    """
    try:
        source = load_export_source(tenant_id, project_id, version)
    except ExportSourceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": f"{code_prefix}-source-unavailable", "message": str(exc)},
        ) from exc

    revision = db.get_version_by_id(source.version_record_id, tenant_id)
    if not revision or not revision.get("published"):
        raise HTTPException(
            status_code=400,
            detail={"code": f"{code_prefix}-not-published", "message": refusal},
        )
    return source


def _credential_error(exc: RegistryCredentialError) -> HTTPException:
    """Map a credential refusal onto ``422`` with every problem listed."""
    return HTTPException(
        status_code=422,
        detail={"code": "sdk-registry-credential-invalid", "errors": list(exc.errors)},
    )


def _publish_error(exc: PublishError) -> HTTPException:
    """Map a publish refusal onto the status the pipeline chose.

    The refusal's own ``code`` and ``message`` are written last, so a ``detail`` payload that
    happened to carry either key cannot shadow the two fields a caller dispatches on.

    Args:
        exc: The refusal.

    Returns:
        The exception to raise.
    """
    return HTTPException(
        status_code=exc.status_code,
        detail={**exc.detail, "code": exc.code, "message": exc.message},
    )


def write_audit(
    *,
    tenant_id: str,
    action: str,
    auth_data: Dict[str, Any],
    target: Optional[str],
    detail: Dict[str, Any],
) -> None:
    """Write one audit row (best-effort).

    Audit failures are logged and swallowed: an action that succeeded must not be reported as a
    failure because its audit row could not be appended.

    Args:
        tenant_id: The tenant the action belongs to.
        action: The audit action.
        auth_data: The authenticated principal.
        target: What the action concerns.
        detail: The payload to record. Never contains a token.
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
        logger.warning("Failed to audit %s for tenant %s", action, tenant_id, exc_info=True)


def _credentials_response(
    tenant_id: str, scope: str, project_id: Optional[str]
) -> RegistryCredentialListResponse:
    """Assemble the credential listing for one scope.

    Args:
        tenant_id: The caller's tenant.
        scope: ``tenant`` or ``project``.
        project_id: The project, when the scope is a project.

    Returns:
        The response.
    """
    return RegistryCredentialListResponse(
        scope=scope,
        encryption_configured=credential_encryption_configured(),
        ecosystems=list(PUBLISH_ECOSYSTEMS),
        credentials=list_credentials(tenant_id, project_id=project_id),
    )


def _store_credential(
    *,
    tenant_id: str,
    project_id: Optional[str],
    ecosystem: str,
    body: RegistryCredentialPutRequest,
    auth_data: Dict[str, Any],
) -> RegistryCredentialOut:
    """Seal and store a credential for one scope, then audit it.

    Args:
        tenant_id: Owning tenant.
        project_id: The project, or ``None`` for the tenant-wide credential.
        ecosystem: ``npm`` or ``pypi``.
        body: The submitted token and registry.
        auth_data: The authenticated principal.

    Returns:
        The stored credential's metadata.

    Raises:
        HTTPException: 422 when the token or registry is not acceptable; 503 when this deployment
            has no encryption key configured, naming the variable to set.
    """
    try:
        stored = save_credential(
            tenant_id,
            ecosystem=ecosystem,
            token=body.token,
            project_id=project_id,
            registry_url=body.registry_url,
            actor_id=get_authenticated_user_id(auth_data),
        )
    except RegistryCredentialError as exc:
        raise _credential_error(exc) from exc
    except EnvelopeEncryptionError as exc:
        # Fail closed: a token that cannot be sealed is never written in the clear.
        raise HTTPException(
            status_code=503,
            detail={
                "code": "sdk-registry-credential-encryption-unconfigured",
                "message": (
                    "Registry credentials cannot be stored on this deployment: "
                    f"{exc}. Set APIOME_SDK_REGISTRY_CREDENTIAL_ENCRYPTION_KEYS and restart."
                ),
            },
        ) from exc

    write_audit(
        tenant_id=tenant_id,
        action=AUDIT_CREDENTIAL_UPDATE,
        auth_data=auth_data,
        target=project_id or tenant_id,
        detail={
            "ecosystem": stored.ecosystem,
            "scope": stored.scope,
            "registryUrl": stored.registry_url,
            "tokenFingerprint": stored.token_fingerprint,
            "keyVersion": stored.key_version,
        },
    )
    return stored


def _clear_credential(
    *,
    tenant_id: str,
    project_id: Optional[str],
    ecosystem: str,
    auth_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Remove a credential from one scope, then audit it.

    Args:
        tenant_id: Owning tenant.
        project_id: The project, or ``None`` for the tenant-wide credential.
        ecosystem: ``npm`` or ``pypi``.
        auth_data: The authenticated principal.

    Returns:
        ``{"cleared": bool}``.

    Raises:
        HTTPException: 422 when the ecosystem is not publishable.
    """
    try:
        cleared = delete_credential(tenant_id, ecosystem=ecosystem, project_id=project_id)
    except RegistryCredentialError as exc:
        raise _credential_error(exc) from exc
    if cleared:
        write_audit(
            tenant_id=tenant_id,
            action=AUDIT_CREDENTIAL_CLEAR,
            auth_data=auth_data,
            target=project_id or tenant_id,
            detail={
                "ecosystem": ecosystem,
                "scope": "project" if project_id else "tenant",
            },
        )
    return {"cleared": cleared}


# ===========================================================================
# Tenant-scoped credentials
# ===========================================================================


@tenant_router.get(
    "/{tenant_slug}/governance/sdk-registry-credentials",
    response_model=RegistryCredentialListResponse,
    tags=["governance"],
    summary="List the workspace's package-registry credentials",
    description=_CREDENTIAL_DESCRIPTION + "\n\nRequires `projects:view`.",
)
async def list_tenant_registry_credentials(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RegistryCredentialListResponse:
    """Describe the workspace-wide registry credentials.

    Args:
        tenant_slug: Tenant in the URL (the auth tenant scopes every read).
        auth_data: Authenticated principal.

    Returns:
        The credentials configured at tenant scope, described but never revealed.

    Raises:
        HTTPException: 403 without ``projects:view``.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    return _credentials_response(tenant_id_of(auth_data), "tenant", None)


@tenant_router.put(
    "/{tenant_slug}/governance/sdk-registry-credentials/{ecosystem}",
    response_model=RegistryCredentialOut,
    tags=["governance"],
    summary="Store the workspace's credential for one registry",
    description=(
        _CREDENTIAL_DESCRIPTION
        + "\n\nRequires `projects:edit`. Audited as "
        "`governance.sdk_registry_credential.update` — the audit row records the token's "
        "fingerprint, never the token."
    ),
    responses={
        422: {"description": "The token, registry URL or ecosystem is not acceptable."},
        503: {"description": "No credential-encryption key is configured on this deployment."},
    },
)
async def put_tenant_registry_credential(
    tenant_slug: str,
    ecosystem: str,
    body: RegistryCredentialPutRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RegistryCredentialOut:
    """Store or replace the workspace's credential for one registry.

    Args:
        tenant_slug: Tenant in the URL.
        ecosystem: ``npm`` or ``pypi``.
        body: The token and (optionally) the registry to publish to.
        auth_data: Authenticated principal.

    Returns:
        The stored credential's metadata.

    Raises:
        HTTPException: 403 without ``projects:edit``; 422 on an invalid body; 503 when encryption
            is unconfigured.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = tenant_id_of(auth_data)
    return _store_credential(
        tenant_id=tenant_id,
        project_id=None,
        ecosystem=ecosystem,
        body=body,
        auth_data=auth_data,
    )


@tenant_router.delete(
    "/{tenant_slug}/governance/sdk-registry-credentials/{ecosystem}",
    tags=["governance"],
    summary="Remove the workspace's credential for one registry",
    description=(
        "Nothing cascades: a project that stored its own credential keeps publishing with it.\n\n"
        "Requires `projects:edit`. Audited as `governance.sdk_registry_credential.clear`."
    ),
)
async def delete_tenant_registry_credential(
    tenant_slug: str,
    ecosystem: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Remove the workspace's credential for one registry.

    Args:
        tenant_slug: Tenant in the URL.
        ecosystem: ``npm`` or ``pypi``.
        auth_data: Authenticated principal.

    Returns:
        ``{"cleared": true}`` when one was stored at tenant scope.

    Raises:
        HTTPException: 403 without ``projects:edit``; 422 for an unknown ecosystem.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    return _clear_credential(
        tenant_id=tenant_id_of(auth_data),
        project_id=None,
        ecosystem=ecosystem,
        auth_data=auth_data,
    )


# ===========================================================================
# Project-scoped credentials
# ===========================================================================


@router.get(
    "/{tenant_slug}/{project_ref}/sdk-registry-credentials",
    response_model=RegistryCredentialListResponse,
    tags=["sdk-publishing"],
    summary="List the credentials a project would publish with",
    description=(
        "Both the workspace credentials and this project's overrides, workspace first, so a "
        "reader can see what is being overridden.\n\n" + _CREDENTIAL_DESCRIPTION + "\n\n"
        "Requires `projects:view`."
    ),
    responses={404: {"description": "Project not found in this tenant."}},
)
async def list_project_registry_credentials(
    tenant_slug: str,
    project_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RegistryCredentialListResponse:
    """Describe the credentials in scope for a project.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        auth_data: Authenticated principal.

    Returns:
        The credentials, described but never revealed.

    Raises:
        HTTPException: 403 without ``projects:view``; 404 when the project is unknown.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    return _credentials_response(tenant_id, "project", str(project["id"]))


@router.put(
    "/{tenant_slug}/{project_ref}/sdk-registry-credentials/{ecosystem}",
    response_model=RegistryCredentialOut,
    tags=["sdk-publishing"],
    summary="Store this project's credential for one registry",
    description=(
        "Replaces the workspace credential for this project and ecosystem, whole.\n\n"
        + _CREDENTIAL_DESCRIPTION
        + "\n\nRequires `projects:edit`. Audited as "
        "`governance.sdk_registry_credential.update`."
    ),
    responses={
        404: {"description": "Project not found in this tenant."},
        422: {"description": "The token, registry URL or ecosystem is not acceptable."},
        503: {"description": "No credential-encryption key is configured on this deployment."},
    },
)
async def put_project_registry_credential(
    tenant_slug: str,
    project_ref: str,
    ecosystem: str,
    body: RegistryCredentialPutRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RegistryCredentialOut:
    """Store or replace this project's credential for one registry.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        ecosystem: ``npm`` or ``pypi``.
        body: The token and (optionally) the registry to publish to.
        auth_data: Authenticated principal.

    Returns:
        The stored credential's metadata.

    Raises:
        HTTPException: 403 without ``projects:edit``; 404 for an unknown project; 422 on an
            invalid body; 503 when encryption is unconfigured.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    return _store_credential(
        tenant_id=tenant_id,
        project_id=str(project["id"]),
        ecosystem=ecosystem,
        body=body,
        auth_data=auth_data,
    )


@router.delete(
    "/{tenant_slug}/{project_ref}/sdk-registry-credentials/{ecosystem}",
    tags=["sdk-publishing"],
    summary="Remove this project's credential for one registry",
    description=(
        "The project falls back to the workspace credential, if there is one.\n\n"
        "Requires `projects:edit`. Audited as `governance.sdk_registry_credential.clear`."
    ),
    responses={404: {"description": "Project not found in this tenant."}},
)
async def delete_project_registry_credential(
    tenant_slug: str,
    project_ref: str,
    ecosystem: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Remove this project's credential for one registry.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        ecosystem: ``npm`` or ``pypi``.
        auth_data: Authenticated principal.

    Returns:
        ``{"cleared": true}`` when one was stored at project scope.

    Raises:
        HTTPException: 403 without ``projects:edit``; 404 for an unknown project.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    return _clear_credential(
        tenant_id=tenant_id,
        project_id=str(project["id"]),
        ecosystem=ecosystem,
        auth_data=auth_data,
    )


# ===========================================================================
# Publish
# ===========================================================================


@router.post(
    "/{tenant_slug}/{project_ref}/sdk-publish",
    response_model=SdkPublishRunModel,
    tags=["sdk-publishing"],
    summary="Publish a version's SDK package to npm or PyPI (dry run by default)",
    description=(
        "Builds the package a consumer would `npm install` / `pip install` from one **published** "
        "revision and, unless `dryRun` is false, uploads it with the tenant's stored registry "
        "credential.\n\n"
        "**The version number is derived, not chosen.** It is `major.minor.<regen counter>`, where "
        "`major.minor` come from the revision's version line and the counter is how many releases "
        "that line's release series has already had. Re-publishing the same line bumps the patch; "
        "a new line starts a new series. A prerelease line stays a prerelease "
        "(`1.5.0-beta.2` on npm, `1.5.0b2` on PyPI). A line with no leading number cannot be "
        "mapped and is refused.\n\n"
        "**A dry run is the same work minus the upload.** It resolves the credential (proving it "
        "is present and still decryptable), computes the version the next real publish would "
        "claim, builds the archive and reports its SHA-256 and contents. The build is "
        "byte-deterministic, so the digest a dry run reports is the digest a publish uploads.\n\n"
        "**Provenance is embedded in the package's own metadata** — `package.json`'s `apiome` "
        "object, PyPI's `Project-URL` entries — naming the revision id, the version line, the "
        "release series and the generator, so an installed package traces back to its spec.\n\n"
        "Requires `versions:publish`, for a dry run too. Audited as `sdk.package_publish`."
    ),
    responses={
        400: {"description": "Unsupported ecosystem, or the revision is not published."},
        404: {"description": "Project or version not found in this tenant."},
        409: {"description": "No free version number: another publish of this series is in flight."},
        422: {
            "description": (
                "No package name is configured, the version line cannot be mapped, no usable "
                "credential is stored, or there is nothing to package."
            )
        },
        503: {"description": "No credential-encryption key is configured on this deployment."},
    },
)
async def publish_project_sdk(
    tenant_slug: str,
    project_ref: str,
    body: SdkPublishRequest,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SdkPublishRunModel:
    """Validate or perform one package release for a published revision.

    Args:
        tenant_slug: Tenant in the URL; also what ``{tenant}`` resolves to in the package pattern.
        project_ref: The project's id or slug.
        body: Which ecosystem and revision, and whether this is a dry run.
        request: Used only for the running API version, recorded as provenance.
        auth_data: Authenticated principal.

    Returns:
        The run: what was built, what version it claimed, and what the registry said.

    Raises:
        HTTPException: 403 without ``versions:publish``; 404 for an unknown project or version;
            400 for an unpublished revision; and whatever status the pipeline chose for a refusal.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    source = load_published_source(tenant_id, str(project["id"]), body.version)

    context = PublishContext(
        tenant_id=tenant_id,
        tenant_slug=str(tenant_slug or ""),
        project_id=str(project["id"]),
        project_slug=str(project.get("slug") or ""),
        version_record_id=source.version_record_id,
        version_line=source.version_label,
        actor_id=get_authenticated_user_id(auth_data),
    )

    try:
        outcome = publish(
            source.api,
            context=context,
            ecosystem=body.ecosystem,
            dry_run=body.dry_run,
            source_text=source.source_text,
            source_format=source.source_format,
            apiome_version=getattr(request.app, "version", None),
        )
    except PublishError as exc:
        raise _publish_error(exc) from exc

    write_audit(
        tenant_id=tenant_id,
        action=AUDIT_PUBLISH,
        auth_data=auth_data,
        target=str(project["id"]),
        detail={
            "runId": outcome.run_id,
            "status": outcome.status,
            "dryRun": outcome.dry_run,
            "ecosystem": outcome.ecosystem,
            "packageName": outcome.package_name,
            "packageVersion": outcome.package_version,
            "releaseSeries": outcome.release_series,
            "regenCounter": outcome.regen_counter,
            "versionRecordId": context.version_record_id,
            "artifactSha256": outcome.artifact_sha256,
            "registryUrl": outcome.registry_url,
        },
    )
    return _run_model(outcome)


@router.get(
    "/{tenant_slug}/{project_ref}/sdk-publish-runs",
    response_model=SdkPublishRunListResponse,
    tags=["sdk-publishing"],
    summary="List a project's package publish history",
    description=(
        "Every publish attempt, newest first — dry runs included, because a dry run is the record "
        "of what a release *would* have been.\n\nRequires `versions:view`."
    ),
    responses={404: {"description": "Project not found in this tenant."}},
)
async def list_project_publish_runs(
    tenant_slug: str,
    project_ref: str,
    ecosystem: Optional[str] = Query(
        default=None, description="Narrow to one ecosystem (`npm` or `pypi`)."
    ),
    limit: int = Query(default=50, ge=1, le=MAX_HISTORY_LIMIT),
    offset: int = Query(default=0, ge=0),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SdkPublishRunListResponse:
    """Return a page of a project's publish history.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        ecosystem: Narrow to one ecosystem.
        limit: Page size.
        offset: Rows to skip.
        auth_data: Authenticated principal.

    Returns:
        The page, newest first.

    Raises:
        HTTPException: 403 without ``versions:view``; 404 when the project is unknown.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    rows = db.list_sdk_publish_runs(
        tenant_id, project_id, ecosystem=ecosystem, limit=limit, offset=offset
    )
    return SdkPublishRunListResponse(
        runs=[_run_model(run_row_to_outcome(row)) for row in rows],
        total=db.count_sdk_publish_runs(tenant_id, project_id, ecosystem=ecosystem),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{tenant_slug}/{project_ref}/sdk-publish-runs/{run_id}",
    response_model=SdkPublishRunModel,
    tags=["sdk-publishing"],
    summary="Read one publish run",
    description=(
        "The run's outcome, the version it claimed and its event log. The log is stored redacted "
        "— a registry error quoting the credential it rejected is replaced before it is written."
        "\n\nRequires `versions:view`."
    ),
    responses={404: {"description": "Project or run not found in this tenant."}},
)
async def get_project_publish_run(
    tenant_slug: str,
    project_ref: str,
    run_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SdkPublishRunModel:
    """Return one publish run.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        run_id: The run to read.
        auth_data: Authenticated principal.

    Returns:
        The run.

    Raises:
        HTTPException: 403 without ``versions:view``; 404 when the project or run is unknown, or
            the run belongs to another project.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    row = db.get_sdk_publish_run(run_id, tenant_id)
    if not row or str(row.get("project_id")) != str(project["id"]):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "sdk-publish-run-not-found",
                "message": f"No publish run {run_id!r} belongs to this project.",
            },
        )
    return _run_model(run_row_to_outcome(row))
