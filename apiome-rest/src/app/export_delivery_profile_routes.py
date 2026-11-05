"""Export delivery profile routes — MFX-38.4 (#4331).

**The profiles** — a workspace's reusable delivery destinations:

* ``POST   /v1/export/{tenant_slug}/delivery-profiles`` stores one (a webhook secret sealed on arrival);
* ``GET    /v1/export/{tenant_slug}/delivery-profiles`` lists them (``?channel=`` narrows);
* ``GET    /v1/export/{tenant_slug}/delivery-profiles/{profile_id}`` reads one;
* ``PATCH  /v1/export/{tenant_slug}/delivery-profiles/{profile_id}`` changes its name, description or
  destination (never its channel);
* ``DELETE /v1/export/{tenant_slug}/delivery-profiles/{profile_id}`` removes it — its deliveries stay;
* ``GET    /v1/export/{tenant_slug}/delivery-profiles/{profile_id}/deliveries`` is its delivery trail.

**The deliveries** — ``POST /v1/export/{tenant_slug}/jobs/{job_id}/deliveries`` delivers a completed job
with a profile, through the channel's own delivery (git, webhook or object storage), and records the
profile on the run; ``GET`` on the same path lists every delivery of the job across all channels.

**Permissions.** Managing a profile is ``projects:edit`` (reading ``projects:view``), as a storage
credential is; delivering is ``versions:publish``, as every delivery is. Profile changes are audited
as ``export.delivery_profile.*``; a delivery is audited by its channel (``export.git_delivery``, …) with
the ``profileId`` — never with a secret.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from psycopg2 import errors as pg_errors
from pydantic import BaseModel, ConfigDict, Field

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .export_delivery_profiles import (
    DeliveryProfileCreate,
    DeliveryProfileRequestError,
    DeliveryProfileUpdate,
    NormalizedProfile,
    channel_request,
    credential_ref,
    delivery_outcome,
    normalize_create,
    normalize_update,
    public_destination,
)
from .export_delivery_results import ExportDeliveryResult, delivery_result
from .export_git_delivery_routes import _check_tenant, perform_git_delivery
from .export_object_storage_delivery_routes import perform_object_storage_delivery
from .export_webhook_delivery import display_url
from .export_webhook_delivery_routes import perform_webhook_delivery
from .mcp_credential_crypto import CredentialEncryptionError, seal_credential_payload, unseal_credential_payload
from .permissions import Action, Resource, enforce_permission
from .sdk_publish_routes import tenant_id_of, write_audit
from .ssrf_guard import SSRFError, validate_url

router = APIRouter(prefix="/v1/export", tags=["export-delivery"])

AUDIT_PROFILE_CREATED = "export.delivery_profile.created"
AUDIT_PROFILE_UPDATED = "export.delivery_profile.updated"
AUDIT_PROFILE_DELETED = "export.delivery_profile.deleted"

_NOT_FOUND = "Delivery profile not found"


class CredentialRefModel(BaseModel):
    """What a profile delivers with, by reference."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["repository", "storage_credential", "webhook_secret"] = Field(
        description="`repository` (the registered repository's linked account), `storage_credential` (a "
        "credential in the storage vault) or `webhook_secret` (sealed on the profile, never returned).")
    id: Optional[str] = Field(default=None, description="The repository or storage credential id; null for a "
                              "webhook secret.")


class ExportDeliveryProfileModel(BaseModel):
    """A stored delivery profile, described without its secret.

    Attributes:
        id: The profile.
        name: Its unique name in the workspace.
        description: What it is for.
        channel: ``git``, ``webhook`` or ``object_storage``.
        destination: The channel's delivery body, minus any secret (a webhook URL without its query).
        credential_ref: What it delivers with.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    name: str
    description: Optional[str] = None
    channel: str
    destination: Dict[str, Any] = Field(default_factory=dict)
    credential_ref: CredentialRefModel = Field(serialization_alias="credentialRef")
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, serialization_alias="updatedAt")
    created_by: Optional[str] = Field(default=None, serialization_alias="createdBy")
    updated_by: Optional[str] = Field(default=None, serialization_alias="updatedBy")


class ExportDeliveryProfileListResponse(BaseModel):
    """A workspace's delivery profiles, by name."""

    model_config = ConfigDict(extra="forbid")

    profiles: List[ExportDeliveryProfileModel] = Field(default_factory=list)


class ProfileDeliveryRequest(BaseModel):
    """Deliver a job with a profile: ``POST …/jobs/{job_id}/deliveries``."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    profile_id: str = Field(alias="profileId", description="A delivery profile of this workspace "
                            "(`GET /v1/export/{tenant}/delivery-profiles`).")


class ExportDeliveryAttemptModel(BaseModel):
    """One delivery attempt, whatever its channel.

    Attributes:
        channel: ``git``, ``webhook`` or ``object_storage``.
        run_id: The channel's run.
        status: The channel's own status (``opened``, ``retrying``, ``delivered``, …).
        outcome: ``in_progress``, ``delivered`` or ``failed``.
        profile_id: The profile it was made from (null for a direct delivery or a deleted profile).
        profile_name: That profile's name.
        destination: Where it went: ``owner/repo``, the receiver URL without its query, or ``bucket/prefix``.
        attempt_count: Send attempts so far (a webhook retries; the other channels make one).
        result: What it left at the destination — PR link, receiver status, object URLs (MFX-46.3).
        run: In the answer to a delivery only — the channel's full run, as its own endpoint returns it.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    channel: str
    run_id: Optional[str] = Field(default=None, serialization_alias="runId")
    job_id: str = Field(serialization_alias="jobId")
    artifact_id: Optional[str] = Field(default=None, serialization_alias="artifactId")
    export_target: Optional[str] = Field(default=None, serialization_alias="exportTarget")
    status: str
    outcome: Literal["in_progress", "delivered", "failed"]
    profile_id: Optional[str] = Field(default=None, serialization_alias="profileId")
    profile_name: Optional[str] = Field(default=None, serialization_alias="profileName")
    destination: Optional[str] = None
    attempt_count: int = Field(default=1, serialization_alias="attemptCount")
    error_code: Optional[str] = Field(default=None, serialization_alias="errorCode")
    error_message: Optional[str] = Field(default=None, serialization_alias="errorMessage")
    started_at: Optional[datetime] = Field(default=None, serialization_alias="startedAt")
    finished_at: Optional[datetime] = Field(default=None, serialization_alias="finishedAt")
    created_by: Optional[str] = Field(default=None, serialization_alias="createdBy")
    result: Optional[ExportDeliveryResult] = Field(
        default=None,
        description="What the delivery left at its destination (MFX-46.3): the pull request or commit, the "
        "webhook receiver's HTTP status, the objects written. Null until it has produced something.",
    )
    run: Optional[Dict[str, Any]] = None


class ExportDeliveryAttemptListResponse(BaseModel):
    """Delivery attempts across every channel, newest first."""

    model_config = ConfigDict(extra="forbid")

    deliveries: List[ExportDeliveryAttemptModel] = Field(default_factory=list)


def profile_model(row: Dict[str, Any]) -> ExportDeliveryProfileModel:
    """Project a stored profile onto the wire model (its secret never reaches it)."""
    channel = str(row["channel"])
    destination = dict(row.get("destination") or {})
    return ExportDeliveryProfileModel(
        id=str(row["id"]), name=str(row["name"]), description=row.get("description"), channel=channel,
        destination=public_destination(channel, destination),
        credential_ref=CredentialRefModel(**credential_ref(channel, destination)),
        created_at=row.get("created_at"), updated_at=row.get("updated_at"), created_by=row.get("created_by"),
        updated_by=row.get("updated_by"),
    )


def attempt_model(row: Dict[str, Any]) -> ExportDeliveryAttemptModel:
    """Project a row of :meth:`app.database.Database.list_export_delivery_attempts` onto the wire model."""
    channel = str(row["channel"])
    destination = row.get("destination")
    if channel == "webhook" and destination:
        destination = display_url(str(destination))
    return ExportDeliveryAttemptModel(
        channel=channel, run_id=row.get("id"), job_id=str(row["job_id"]), artifact_id=row.get("artifact_id"),
        export_target=row.get("export_target"), status=str(row["status"]),
        outcome=delivery_outcome(channel, row.get("status")), profile_id=row.get("delivery_profile_id"),
        profile_name=row.get("profile_name"), destination=destination,
        attempt_count=int(row.get("attempt_count") or 0), error_code=row.get("error_code"),
        error_message=row.get("error_message"), started_at=row.get("started_at"),
        finished_at=row.get("finished_at"), created_by=row.get("created_by"),
        result=delivery_result(channel, row),
    )


def _invalid(exc: DeliveryProfileRequestError) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": "export-delivery-profile-invalid", "errors": exc.errors})


def _name_taken(name: str) -> HTTPException:
    return HTTPException(status_code=409, detail={
        "code": "export-delivery-profile-name-taken",
        "message": f"A delivery profile named {name!r} already exists.",
    })


async def _check_references(tenant_id: str, profile: NormalizedProfile) -> None:
    """Refuse (400) a destination whose credential reference or receiver cannot be used.

    A git repository and a storage credential must exist in the workspace; a webhook receiver must
    resolve to public addresses. They are checked again at every delivery — this only stops a profile
    that could never deliver from being stored.
    """
    destination = profile.destination or {}
    unknown: Optional[str] = None
    if profile.channel == "git":
        repository_id = str(destination.get("repositoryId") or "")
        if not await asyncio.to_thread(db.get_tenant_repository, tenant_id, repository_id):
            unknown = f"git.repositoryId: no repository {repository_id!r} is registered in this workspace"
    elif profile.channel == "object_storage":
        credential_id = str(destination.get("credentialId") or "")
        if not await asyncio.to_thread(db.get_export_storage_credential, tenant_id, credential_id):
            unknown = f"objectStorage.credentialId: no storage credential {credential_id!r} exists in this workspace"
    elif profile.channel == "webhook":
        try:
            await asyncio.to_thread(validate_url, str(destination.get("url") or ""))
        except SSRFError as exc:
            raise HTTPException(status_code=400, detail={"code": "export-delivery-profile-destination-refused",
                                                         "errors": [f"webhook.url: {exc}"]}) from exc
    if unknown:
        raise HTTPException(status_code=400, detail={"code": "export-delivery-profile-reference-unknown",
                                                     "errors": [unknown]})


def _seal_secret(secret: Optional[str]) -> tuple[Optional[bytes], Optional[int]]:
    """Seal a webhook secret, or ``(None, None)`` when there is none; 503 without an encryption key."""
    if secret is None:
        return None, None
    try:
        return seal_credential_payload({"secret": secret})
    except CredentialEncryptionError as exc:
        raise HTTPException(status_code=503, detail={
            "code": "export-delivery-profile-encryption-unconfigured",
            "message": "Credential encryption is not configured on this deployment; set "
                       "APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS.",
        }) from exc


def _audit_detail(row: Dict[str, Any]) -> Dict[str, Any]:
    """What a profile change records: its name, channel and destination, never a secret."""
    channel = str(row["channel"])
    destination = dict(row.get("destination") or {})
    return {"name": row.get("name"), "channel": channel, "destination": public_destination(channel, destination),
            "credentialRef": credential_ref(channel, destination)}


async def _profile_or_404(tenant_id: str, profile_id: str, *, with_secret: bool = False) -> Dict[str, Any]:
    row = await asyncio.to_thread(db.get_export_delivery_profile, tenant_id, profile_id, with_secret=with_secret)
    if not row:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return row


# -------------------------------------------------------------------------------------------
# The profiles
# -------------------------------------------------------------------------------------------


@router.post(
    "/{tenant_slug}/delivery-profiles",
    response_model=ExportDeliveryProfileModel,
    response_model_by_alias=True,
    status_code=201,
    summary="Store an export delivery profile",
    description=(
        "Stores a reusable delivery destination: a `name`, a `channel` (`git`, `webhook` or `object_storage`) "
        "and that channel's delivery body in the matching block — `git`, `webhook` or `objectStorage` — "
        "validated by the channel's own rules. The credential is a reference: the git repository's linked "
        "account, or a storage credential in the vault. A webhook's `secret` is sealed on the profile and "
        "never returned. Requires `projects:edit`; audited as `export.delivery_profile.created`.\n\n"
        "`400` for an invalid field, an unknown repository or storage credential, or a refused receiver; "
        "`409` for a name already in use; `503` when a webhook secret cannot be sealed "
        "(`APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS`)."
    ),
    responses={400: {"description": "Invalid field, unknown reference or refused receiver."},
               409: {"description": "A profile of that name exists."},
               503: {"description": "Credential encryption is not configured."}},
)
async def create_delivery_profile(
    tenant_slug: str,
    body: DeliveryProfileCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportDeliveryProfileModel:
    """Validate and store one delivery profile.

    Args:
        tenant_slug: The tenant.
        body: The profile.
        auth_data: Authenticated principal.

    Returns:
        The stored profile.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    try:
        profile = normalize_create(body)
    except DeliveryProfileRequestError as exc:
        raise _invalid(exc) from exc
    await _check_references(tenant_id, profile)
    sealed, key_version = _seal_secret(profile.secret)
    try:
        row = await asyncio.to_thread(
            db.insert_export_delivery_profile, tenant_id=tenant_id, name=profile.name,
            description=profile.description, channel=profile.channel, destination=profile.destination or {},
            sealed_secret=sealed, secret_key_version=key_version, actor_id=get_authenticated_user_id(auth_data),
        )
    except pg_errors.UniqueViolation as exc:
        raise _name_taken(profile.name) from exc
    if not row:
        raise HTTPException(status_code=500, detail="The delivery profile could not be stored.")
    write_audit(tenant_id=tenant_id, action=AUDIT_PROFILE_CREATED, auth_data=auth_data, target=row["id"],
                detail=_audit_detail(row))
    return profile_model(row)


@router.get(
    "/{tenant_slug}/delivery-profiles",
    response_model=ExportDeliveryProfileListResponse,
    response_model_by_alias=True,
    summary="List the workspace's export delivery profiles",
    description="Every delivery profile, by name — never a secret. `channel` narrows to one channel. "
    "Requires `projects:view`.",
)
async def list_delivery_profiles(
    tenant_slug: str,
    channel: Optional[Literal["git", "webhook", "object_storage"]] = Query(default=None),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportDeliveryProfileListResponse:
    """List the tenant's delivery profiles."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    rows = await asyncio.to_thread(db.list_export_delivery_profiles, tenant_id, channel)
    return ExportDeliveryProfileListResponse(profiles=[profile_model(row) for row in rows])


@router.get(
    "/{tenant_slug}/delivery-profiles/{profile_id}",
    response_model=ExportDeliveryProfileModel,
    response_model_by_alias=True,
    summary="Read an export delivery profile",
    description="One delivery profile — never its secret. Requires `projects:view`. `404` when the "
    "workspace has no such profile.",
    responses={404: {"description": "Unknown profile for this tenant."}},
)
async def get_delivery_profile(
    tenant_slug: str,
    profile_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportDeliveryProfileModel:
    """Read one delivery profile."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    return profile_model(await _profile_or_404(tenant_id, profile_id))


@router.patch(
    "/{tenant_slug}/delivery-profiles/{profile_id}",
    response_model=ExportDeliveryProfileModel,
    response_model_by_alias=True,
    summary="Change an export delivery profile",
    description=(
        "Changes a profile's `name`, `description` or destination. A destination block replaces the stored "
        "destination whole and must be the profile's own channel — the channel never changes. On a webhook "
        "profile, leave `webhook.secret` out to keep the stored secret. Past deliveries keep their record. "
        "Requires `projects:edit`; audited as `export.delivery_profile.updated`."
    ),
    responses={400: {"description": "Invalid field, another channel's block, unknown reference or refused "
                                    "receiver."},
               404: {"description": "Unknown profile for this tenant."},
               409: {"description": "Another profile has that name."},
               503: {"description": "Credential encryption is not configured."}},
)
async def update_delivery_profile(
    tenant_slug: str,
    profile_id: str,
    body: DeliveryProfileUpdate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportDeliveryProfileModel:
    """Change one delivery profile.

    Args:
        tenant_slug: The tenant.
        profile_id: The profile.
        body: What changes.
        auth_data: Authenticated principal.

    Returns:
        The updated profile.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    existing = await _profile_or_404(tenant_id, profile_id)
    try:
        profile = normalize_update(body, existing)
    except DeliveryProfileRequestError as exc:
        raise _invalid(exc) from exc
    if profile.destination is not None:
        await _check_references(tenant_id, profile)
    sealed, key_version = _seal_secret(profile.secret)
    destination = profile.destination if profile.destination is not None else dict(existing.get("destination") or {})
    try:
        row = await asyncio.to_thread(
            db.update_export_delivery_profile, tenant_id, profile_id, name=profile.name,
            description=profile.description, destination=destination,
            sealed_secret=sealed, secret_key_version=key_version, actor_id=get_authenticated_user_id(auth_data),
        )
    except pg_errors.UniqueViolation as exc:
        raise _name_taken(profile.name) from exc
    if not row:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    detail = _audit_detail(row)
    detail["secretReplaced"] = sealed is not None
    write_audit(tenant_id=tenant_id, action=AUDIT_PROFILE_UPDATED, auth_data=auth_data, target=profile_id,
                detail=detail)
    return profile_model(row)


@router.delete(
    "/{tenant_slug}/delivery-profiles/{profile_id}",
    status_code=204,
    summary="Delete an export delivery profile",
    description="Removes the profile (and a webhook profile's sealed secret); its deliveries keep their record, "
    "no longer naming it. Requires `projects:edit`; audited as `export.delivery_profile.deleted`. `404` when "
    "the workspace has no such profile.",
    responses={404: {"description": "Unknown profile for this tenant."}},
)
async def delete_delivery_profile(
    tenant_slug: str,
    profile_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Delete one delivery profile."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    existing = await _profile_or_404(tenant_id, profile_id)
    if not await asyncio.to_thread(db.delete_export_delivery_profile, tenant_id, profile_id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    write_audit(tenant_id=tenant_id, action=AUDIT_PROFILE_DELETED, auth_data=auth_data, target=profile_id,
                detail=_audit_detail(existing))
    return Response(status_code=204)


@router.get(
    "/{tenant_slug}/delivery-profiles/{profile_id}/deliveries",
    response_model=ExportDeliveryAttemptListResponse,
    response_model_by_alias=True,
    summary="List a delivery profile's deliveries",
    description="Every delivery made with the profile, across export jobs, newest first (at most `limit`). "
    "Requires `projects:view`.",
    responses={404: {"description": "Unknown profile for this tenant."}},
)
async def list_delivery_profile_deliveries(
    tenant_slug: str,
    profile_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportDeliveryAttemptListResponse:
    """List one profile's delivery trail."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    await _profile_or_404(tenant_id, profile_id)
    rows = await asyncio.to_thread(db.list_export_delivery_attempts, tenant_id, profile_id=profile_id, limit=limit)
    return ExportDeliveryAttemptListResponse(deliveries=[attempt_model(row) for row in rows])


# -------------------------------------------------------------------------------------------
# The deliveries
# -------------------------------------------------------------------------------------------


def _webhook_secret(profile: Dict[str, Any]) -> str:
    """A webhook profile's unsealed secret, or 503 when this deployment cannot open it."""
    payload = unseal_credential_payload(profile.get("sealed_secret"), profile.get("secret_key_version"))
    secret = (payload or {}).get("secret")
    if not secret:
        raise HTTPException(status_code=503, detail={
            "code": "export-delivery-profile-secret-unavailable",
            "message": f"The webhook secret of profile {profile.get('name')!r} cannot be opened on this "
                       "deployment (its encryption key is missing or changed). Set the secret again "
                       "(PATCH the profile), then deliver.",
        })
    return str(secret)


@router.post(
    "/{tenant_slug}/jobs/{job_id}/deliveries",
    response_model=ExportDeliveryAttemptModel,
    response_model_by_alias=True,
    summary="Deliver a completed export with a delivery profile",
    description=(
        "Delivers a **completed** export job to the profile's destination through the channel's own delivery "
        "— exactly as `POST …/deliveries/git`, `…/webhook` or `…/object-storage` with the profile's body — "
        "and records the profile on the run. The answer summarises the attempt (`outcome`: `in_progress`, "
        "`delivered` or `failed`) and carries the channel's full run in `run`.\n\n"
        "As with each channel, a delivery that reaches the destination and fails answers `200` with "
        "`outcome: failed` and the channel's `errorCode`. Requires `versions:publish`; audited by the channel "
        "(`export.git_delivery`, `export.webhook_delivery`, `export.object_storage_delivery`) with `profileId`."
    ),
    responses={
        400: {"description": "The stored destination is no longer valid for its channel."},
        404: {"description": "Unknown export job or profile for this tenant."},
        409: {"description": "The job is not completed, is a dry run, or its bundle cannot be read."},
        410: {"description": "The export's artifact has expired; export again, then deliver."},
        503: {"description": "A webhook profile's secret cannot be opened on this deployment."},
    },
)
async def deliver_export_job_with_profile(
    tenant_slug: str,
    job_id: str,
    body: ProfileDeliveryRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportDeliveryAttemptModel:
    """Deliver one completed export job with a delivery profile.

    Args:
        tenant_slug: The tenant the job was submitted under.
        job_id: The export job.
        body: Which profile.
        auth_data: Authenticated principal.

    Returns:
        The attempt, with the channel's run.

    Raises:
        HTTPException: 403 without ``versions:publish``; 404 for an unknown profile or job; the
            channel's own 400 / 409 / 410; 503 for a webhook secret this deployment cannot open.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    return await deliver_with_profile(tenant_slug, tenant_id, job_id, body.profile_id, auth_data)


async def deliver_with_profile(
    tenant_slug: str,
    tenant_id: str,
    job_id: str,
    profile_id: str,
    auth_data: Dict[str, Any],
) -> ExportDeliveryAttemptModel:
    """Deliver one completed export job with one delivery profile, through the profile's channel.

    Shared by ``POST …/jobs/{job_id}/deliveries`` and an export job submitted with
    ``delivery_profiles`` (delivered on completion by the export engine); the caller has already
    enforced ``versions:publish`` and checked the tenant.

    Args:
        tenant_slug: The tenant the job was submitted under.
        tenant_id: That tenant's id.
        job_id: The export job.
        profile_id: The delivery profile.
        auth_data: Authenticated principal the delivery runs, and is audited, as.

    Returns:
        The attempt, with the channel's run.

    Raises:
        HTTPException: 404 for an unknown profile or job; 400 for a stored destination that is no
            longer valid; the channel's own 400 / 409 / 410; 503 for a webhook secret this
            deployment cannot open.
    """
    profile = await _profile_or_404(tenant_id, profile_id, with_secret=True)
    channel = str(profile["channel"])
    destination = dict(profile.get("destination") or {})
    secret = _webhook_secret(profile) if channel == "webhook" else None
    try:
        request = channel_request(channel, destination, secret)
    except ValueError as exc:  # a pydantic ValidationError is a ValueError
        raise HTTPException(status_code=400, detail={
            "code": "export-delivery-profile-destination-invalid",
            "message": f"The profile's stored destination is not a valid {channel} delivery ({exc}). Update "
                       "the profile, then deliver.",
        }) from exc
    profile_id = str(profile["id"])
    if channel == "git":
        git_run = await perform_git_delivery(tenant_slug, tenant_id, job_id, request, auth_data,
                                             profile_id=profile_id)
        run = git_run.model_dump(mode="json", by_alias=True)
        shown = git_run.repository_full_name
        result_row = {"result_mode": git_run.mode, "result_pull_request_url": git_run.pull_request_url,
                      "result_pull_request_number": git_run.pull_request_number,
                      "result_branch": git_run.branch_name, "result_commit_sha": git_run.commit_sha}
    elif channel == "webhook":
        webhook_run = await perform_webhook_delivery(tenant_slug, tenant_id, job_id, request, auth_data,
                                                     profile_id=profile_id)
        run = webhook_run.model_dump(mode="json", by_alias=True)
        shown = webhook_run.target_url
        result_row = {"result_http_status": webhook_run.last_http_status,
                      "result_payload_sha256": getattr(webhook_run, "payload_sha256", None)}
    else:
        storage_run = await perform_object_storage_delivery(tenant_slug, tenant_id, job_id, request, auth_data,
                                                            profile_id=profile_id)
        run = storage_run.model_dump(mode="json", by_alias=True)
        shown = storage_run.bucket + (f"/{storage_run.key_prefix}" if storage_run.key_prefix else "")
        result_row = {"result_endpoint_url": storage_run.endpoint_url, "result_bucket": storage_run.bucket,
                      "result_objects": run.get("objects") or [], "result_manifest_key": storage_run.manifest_key}
    status = str(run.get("status") or "")
    return ExportDeliveryAttemptModel(
        channel=channel, run_id=run.get("runId"), job_id=job_id, artifact_id=None,
        export_target=run.get("exportTarget"), status=status, outcome=delivery_outcome(channel, status),
        profile_id=profile_id, profile_name=str(profile["name"]), destination=shown,
        attempt_count=int(run.get("attemptCount") or 1), error_code=run.get("errorCode"),
        error_message=run.get("errorMessage"), started_at=run.get("startedAt"), finished_at=run.get("finishedAt"),
        created_by=get_authenticated_user_id(auth_data), run=run,
        result=delivery_result(channel, result_row),
    )


@router.get(
    "/{tenant_slug}/jobs/{job_id}/deliveries",
    response_model=ExportDeliveryAttemptListResponse,
    response_model_by_alias=True,
    summary="List every delivery of an export job",
    description="Every delivery of one export job across the git, webhook and object-storage channels, newest "
    "first, each with its profile (when it was made from one), outcome and attempt count. Requires "
    "`projects:view`.",
)
async def list_export_job_deliveries(
    tenant_slug: str,
    job_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportDeliveryAttemptListResponse:
    """List one export job's deliveries across channels."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    rows = await asyncio.to_thread(db.list_export_delivery_attempts, tenant_id, job_id=job_id, limit=limit)
    return ExportDeliveryAttemptListResponse(deliveries=[attempt_model(row) for row in rows])
