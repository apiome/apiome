"""Export object-storage delivery routes — MFX-38.3 (#4330).

**The vault** — a workspace's S3-compatible bucket credentials, write-only:

* ``POST   /v1/export/{tenant_slug}/storage-credentials`` stores one (the key pair sealed on arrival);
* ``GET    /v1/export/{tenant_slug}/storage-credentials`` lists them — name, endpoint, region and the
  access key id's last four characters, never a secret;
* ``DELETE /v1/export/{tenant_slug}/storage-credentials/{credential_id}`` removes one.

**The delivery** — ``POST /v1/export/{tenant_slug}/jobs/{job_id}/deliveries/object-storage`` uploads a
**completed** export job's bundle and a content-addressed manifest under
``<prefix>/<artifact>/<version>/<target>/``; ``GET`` on the same path lists the job's deliveries. The
upload itself is :func:`app.export_object_storage_delivery_pipeline.deliver_to_object_storage`.

**Permissions.** Managing credentials is ``projects:edit`` (listing ``projects:view``), as a tenant
package-registry credential (SDK-4.1) is. Delivering is ``versions:publish``, as a git (MFX-38.1) or
webhook (MFX-38.2) delivery is. Credential changes are audited as ``export.storage_credential.*`` and
deliveries as ``export.object_storage_delivery`` — never with a secret.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from psycopg2 import errors as pg_errors
from pydantic import BaseModel, ConfigDict, Field

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .export_git_delivery import BundleFile, bundle_files_from_artifact, bundle_files_from_emit
from .export_git_delivery_routes import _check_tenant, _subject
from .export_job_engine import (
    ExportJobResult,
    get_export_job_emit_result,
    get_export_job_status,
    resolve_export_download,
    serialize_file_content,
)
from .export_object_storage_delivery import (
    ExportObjectStorageRequestError,
    ObjectStorageDeliveryRequest,
    StorageCredentialCreate,
    normalize_credential,
    normalize_request,
)
from .export_object_storage_delivery_pipeline import deliver_to_object_storage
from .mcp_credential_crypto import CredentialEncryptionError, seal_credential_payload
from .permissions import Action, Resource, enforce_permission
from .sdk_publish_routes import tenant_id_of, write_audit
from .ssrf_guard import SSRFError, validate_url

router = APIRouter(prefix="/v1/export", tags=["export-delivery"])

AUDIT_DELIVERY = "export.object_storage_delivery"
AUDIT_CREDENTIAL_CREATED = "export.storage_credential.created"
AUDIT_CREDENTIAL_DELETED = "export.storage_credential.deleted"


class StorageCredentialModel(BaseModel):
    """A stored bucket credential, described without its secrets."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    name: str
    provider: str = "s3"
    endpoint_url: Optional[str] = Field(default=None, serialization_alias="endpointUrl",
                                        description="The S3-compatible endpoint; null for AWS S3.")
    region: str
    force_path_style: bool = Field(default=False, serialization_alias="forcePathStyle")
    access_key_hint: str = Field(serialization_alias="accessKeyHint",
                                 description="The access key id's last four characters.")
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, serialization_alias="updatedAt")


class StorageCredentialListResponse(BaseModel):
    """A workspace's storage credentials, by name."""

    model_config = ConfigDict(extra="forbid")

    credentials: List[StorageCredentialModel] = Field(default_factory=list)


class ExportObjectStorageObjectModel(BaseModel):
    """One object a delivery wrote."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    key: str
    size_bytes: int = Field(alias="sizeBytes")
    sha256: str
    content_type: Optional[str] = Field(default=None, alias="contentType")


class ExportObjectStorageDeliveryRunModel(BaseModel):
    """One export object-storage delivery.

    Attributes:
        run_id: The run record (null only when it could not be stored).
        status: ``in_progress``, ``delivered`` or ``failed``.
        job_id: The export job delivered.
        credential_id: The storage credential used.
        endpoint_url: The endpoint (null for AWS S3).
        bucket: The bucket.
        key_prefix: The resolved prefix every object is under.
        partitioning: The partitions used, in order.
        objects: Every object written (on a failure, those written before it).
        manifest_key: The content-addressed manifest (``<keyPrefix>/manifests/<sha256>.json``).
        manifest_sha256: Its SHA-256.
        fidelity: The export's fidelity summary.
        error_code: Set when the run failed.
        error_message: Set when the run failed, redacted.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    run_id: Optional[str] = Field(default=None, serialization_alias="runId")
    status: str
    job_id: str = Field(serialization_alias="jobId")
    credential_id: Optional[str] = Field(default=None, serialization_alias="credentialId")
    endpoint_url: Optional[str] = Field(default=None, serialization_alias="endpointUrl")
    bucket: str
    key_prefix: str = Field(default="", serialization_alias="keyPrefix")
    partitioning: List[str] = Field(default_factory=list)
    objects: List[ExportObjectStorageObjectModel] = Field(default_factory=list)
    manifest_key: Optional[str] = Field(default=None, serialization_alias="manifestKey")
    manifest_sha256: Optional[str] = Field(default=None, serialization_alias="manifestSha256")
    fidelity: Dict[str, Any] = Field(default_factory=dict)
    error_code: Optional[str] = Field(default=None, serialization_alias="errorCode")
    error_message: Optional[str] = Field(default=None, serialization_alias="errorMessage")
    started_at: Optional[datetime] = Field(default=None, serialization_alias="startedAt")
    finished_at: Optional[datetime] = Field(default=None, serialization_alias="finishedAt")


class ExportObjectStorageDeliveryRunListResponse(BaseModel):
    """A job's object-storage deliveries, newest first."""

    model_config = ConfigDict(extra="forbid")

    runs: List[ExportObjectStorageDeliveryRunModel] = Field(default_factory=list)


def credential_model(row: Dict[str, Any]) -> StorageCredentialModel:
    """Project a stored credential onto the wire model (the sealed payload never reaches it)."""
    return StorageCredentialModel(
        id=str(row["id"]), name=str(row["name"]), provider=str(row.get("provider") or "s3"),
        endpoint_url=row.get("endpoint_url"), region=str(row.get("region") or ""),
        force_path_style=bool(row.get("force_path_style")), access_key_hint=str(row.get("access_key_hint") or ""),
        created_at=row.get("created_at"), updated_at=row.get("updated_at"),
    )


def run_model(row: Dict[str, Any]) -> ExportObjectStorageDeliveryRunModel:
    """Project a stored (or in-memory) run onto the wire model."""
    return ExportObjectStorageDeliveryRunModel(
        run_id=row.get("id"), status=str(row["status"]), job_id=str(row["job_id"]),
        credential_id=row.get("credential_id"), endpoint_url=row.get("endpoint_url"), bucket=str(row["bucket"]),
        key_prefix=str(row.get("key_prefix") or ""), partitioning=list(row.get("partitioning") or []),
        objects=[ExportObjectStorageObjectModel.model_validate(item) for item in row.get("objects") or []],
        manifest_key=row.get("manifest_key"), manifest_sha256=row.get("manifest_sha256"),
        fidelity=dict(row.get("fidelity") or {}), error_code=row.get("error_code"),
        error_message=row.get("error_message"), started_at=row.get("started_at"), finished_at=row.get("finished_at"),
    )


def _invalid(exc: ExportObjectStorageRequestError) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": "export-object-storage-request-invalid",
                                                  "errors": exc.errors})


# -------------------------------------------------------------------------------------------
# The vault
# -------------------------------------------------------------------------------------------


@router.post(
    "/{tenant_slug}/storage-credentials",
    response_model=StorageCredentialModel,
    response_model_by_alias=True,
    status_code=201,
    summary="Store an S3-compatible bucket credential",
    description=(
        "Stores an access key pair (and optional session token) for export object-storage delivery, sealed "
        "in the credential vault on arrival. The answer — and every later read — names the endpoint, region "
        "and the access key id's last four characters, never a secret. A custom `endpointUrl` must resolve "
        "to public addresses. Requires `projects:edit`. `409` for a name already in use; `503` when the "
        "deployment has no credential encryption key (`APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS`)."
    ),
    responses={400: {"description": "Invalid field, or a refused endpoint."},
               409: {"description": "A credential of that name exists."},
               503: {"description": "Credential encryption is not configured."}},
)
async def create_storage_credential(
    tenant_slug: str,
    body: StorageCredentialCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> StorageCredentialModel:
    """Seal and store one bucket credential.

    Args:
        tenant_slug: The tenant.
        body: The credential.
        auth_data: Authenticated principal.

    Returns:
        The stored credential's description.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    try:
        credential = normalize_credential(body)
        if credential.endpoint_url:
            await asyncio.to_thread(validate_url, credential.endpoint_url)
    except ExportObjectStorageRequestError as exc:
        raise _invalid(exc) from exc
    except SSRFError as exc:
        raise HTTPException(status_code=400, detail={"code": "export-object-storage-endpoint-refused",
                                                     "errors": [f"endpointUrl: {exc}"]}) from exc
    try:
        sealed, key_version = seal_credential_payload(credential.secret_payload)
    except CredentialEncryptionError as exc:
        raise HTTPException(status_code=503, detail={
            "code": "export-object-storage-encryption-unconfigured",
            "message": "Credential encryption is not configured on this deployment; set "
                       "APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS.",
        }) from exc
    try:
        row = await asyncio.to_thread(
            db.insert_export_storage_credential, tenant_id=tenant_id, name=credential.name,
            endpoint_url=credential.endpoint_url, region=credential.region,
            force_path_style=credential.force_path_style, access_key_hint=credential.access_key_hint,
            encrypted_payload=sealed, key_version=key_version, actor_id=get_authenticated_user_id(auth_data),
        )
    except pg_errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail={
            "code": "export-object-storage-credential-name-taken",
            "message": f"A storage credential named {credential.name!r} already exists.",
        }) from exc
    if not row:
        raise HTTPException(status_code=500, detail="The credential could not be stored.")
    write_audit(tenant_id=tenant_id, action=AUDIT_CREDENTIAL_CREATED, auth_data=auth_data, target=row["id"],
                detail={"name": row["name"], "endpointUrl": row.get("endpoint_url"), "region": row.get("region"),
                        "accessKeyHint": row.get("access_key_hint")})
    return credential_model(row)


@router.get(
    "/{tenant_slug}/storage-credentials",
    response_model=StorageCredentialListResponse,
    response_model_by_alias=True,
    summary="List the workspace's bucket credentials",
    description="Every storage credential, by name — never a secret. Requires `projects:view`.",
)
async def list_storage_credentials(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> StorageCredentialListResponse:
    """List the tenant's storage credentials."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    rows = await asyncio.to_thread(db.list_export_storage_credentials, tenant_id)
    return StorageCredentialListResponse(credentials=[credential_model(row) for row in rows])


@router.delete(
    "/{tenant_slug}/storage-credentials/{credential_id}",
    status_code=204,
    summary="Delete a bucket credential",
    description="Removes the credential from the vault; past deliveries keep their record. Requires "
    "`projects:edit`. `404` when the workspace has no such credential.",
)
async def delete_storage_credential(
    tenant_slug: str,
    credential_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Delete one storage credential."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    if not await asyncio.to_thread(db.delete_export_storage_credential, tenant_id, credential_id):
        raise HTTPException(status_code=404, detail="Storage credential not found")
    write_audit(tenant_id=tenant_id, action=AUDIT_CREDENTIAL_DELETED, auth_data=auth_data, target=credential_id,
                detail={"credentialId": credential_id})
    return Response(status_code=204)


# -------------------------------------------------------------------------------------------
# The delivery
# -------------------------------------------------------------------------------------------


def _completed_result(status: Any) -> ExportJobResult:
    """The result of a job that can be delivered, or refuse (409)."""
    result = status.result
    if status.state != "completed" or result is None:
        raise HTTPException(status_code=409, detail={
            "code": "export-object-storage-delivery-job-not-completed",
            "message": f"The export job is {status.state}; only a completed export can be delivered.",
        })
    if result.dry_run:
        raise HTTPException(status_code=409, detail={
            "code": "export-object-storage-delivery-dry-run",
            "message": "A dry-run export has no files to deliver. Run the export for real, then deliver it.",
        })
    return result


def _bundle(tenant_slug: str, job_id: str, result: ExportJobResult) -> List[BundleFile]:
    """The job's files: the retained emit result on this instance, else the stored artifact."""
    emitted = get_export_job_emit_result(tenant_slug, job_id)
    if emitted is not None:
        return bundle_files_from_emit((f.path, serialize_file_content(f.content)) for f in emitted.files)
    artifact = resolve_export_download(tenant_slug, job_id)  # 409 / 410 propagate
    try:
        return bundle_files_from_artifact(
            artifact.body, media_type=artifact.media_type, listed_paths=[f.path for f in result.files],
            multi_target=bool(result.targets),
        )
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=409, detail={
            "code": "export-object-storage-delivery-artifact-unreadable",
            "message": f"The export's stored bundle could not be read ({exc}). Export again, then deliver.",
        }) from exc


async def perform_object_storage_delivery(
    tenant_slug: str,
    tenant_id: str,
    job_id: str,
    body: ObjectStorageDeliveryRequest,
    auth_data: Dict[str, Any],
    *,
    profile_id: Optional[str] = None,
) -> ExportObjectStorageDeliveryRunModel:
    """Upload one completed export job's bundle to a bucket, record it and audit it.

    Shared by the direct route and a delivery profile (MFX-38.4); the caller has already enforced
    ``versions:publish`` and checked the tenant.

    Args:
        tenant_slug: The tenant the job was submitted under.
        tenant_id: That tenant's id.
        job_id: The export job.
        body: Which credential, bucket, prefix and partitioning.
        auth_data: Authenticated principal.
        profile_id: The delivery profile the request came from, recorded on the run and in the audit.

    Returns:
        The run — whatever its outcome.

    Raises:
        HTTPException: 400 for an invalid request; 404 for an unknown job; 409 for a job that cannot be
            delivered; 410 for an expired artifact.
    """
    try:
        request = normalize_request(body)
    except ExportObjectStorageRequestError as exc:
        raise _invalid(exc) from exc

    status = await get_export_job_status(tenant_slug, job_id)
    result = _completed_result(status)
    files = await asyncio.to_thread(_bundle, tenant_slug, job_id, result)
    subject = await asyncio.to_thread(_subject, tenant_slug, tenant_id, job_id, result)
    media_types = {f.path: f.media_type for f in result.files if f.media_type}
    row = await asyncio.to_thread(
        deliver_to_object_storage, tenant_id=tenant_id, actor_id=get_authenticated_user_id(auth_data),
        subject=subject, request=request, files=files, media_types=media_types,
    )
    if profile_id and row.get("id"):
        await asyncio.to_thread(db.set_export_delivery_run_profile, "object_storage", tenant_id, row["id"],
                                profile_id)
    write_audit(
        tenant_id=tenant_id,
        action=AUDIT_DELIVERY,
        auth_data=auth_data,
        target=result.artifact,
        detail={
            "runId": row.get("id"),
            "status": row.get("status"),
            "jobId": job_id,
            "exportTarget": subject.target,
            "credentialId": request.credential_id,
            "bucket": request.bucket,
            "keyPrefix": row.get("key_prefix"),
            "objectCount": len(row.get("objects") or []),
            "manifestSha256": row.get("manifest_sha256"),
            "errorCode": row.get("error_code"),
            **({"profileId": profile_id} if profile_id else {}),
        },
    )
    return run_model(row)


@router.post(
    "/{tenant_slug}/jobs/{job_id}/deliveries/object-storage",
    response_model=ExportObjectStorageDeliveryRunModel,
    response_model_by_alias=True,
    summary="Deliver a completed export to an S3-compatible bucket",
    description=(
        "Uploads a **completed** export job's bundle to `bucket` with a stored credential "
        "(`credentialId`). Objects are written under `<prefix>/<artifact>/<version>/<target>/` — "
        "`partitioning` picks and orders the partitions, `[]` writes straight under `prefix` — each at its "
        "bundle path, with its SHA-256 in `x-amz-meta-sha256`.\n\n"
        "**Manifest, last.** A manifest listing every object's key, size and SHA-256, with the export's "
        "provenance and fidelity summary, is written after the objects at `<keyPrefix>/manifests/<sha256>.json` "
        "(content-addressed, immutable: the same export writes the same manifest) and at "
        "`<keyPrefix>/manifest.json` (the latest delivery to that prefix).\n\n"
        "**Failures are runs.** A missing or unreadable credential, a refused endpoint, an unknown bucket, a "
        "rejected key or a failed upload answers `200` with `status: failed`, a stable `errorCode` and a "
        "redacted message; the objects written before it are listed. Credentials never appear in a response, "
        "a log line or the audit.\n\n"
        "Requires `versions:publish`. Audited as `export.object_storage_delivery`."
    ),
    responses={
        400: {"description": "Invalid credential id, bucket, prefix or partitioning."},
        404: {"description": "Unknown export job for this tenant."},
        409: {"description": "The job is not completed, is a dry run, or its bundle cannot be read."},
        410: {"description": "The export's artifact has expired; export again, then deliver."},
    },
)
async def deliver_export_job_to_object_storage(
    tenant_slug: str,
    job_id: str,
    body: ObjectStorageDeliveryRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportObjectStorageDeliveryRunModel:
    """Upload one completed export job's bundle to a bucket.

    Args:
        tenant_slug: The tenant the job was submitted under.
        job_id: The export job.
        body: Which credential, bucket, prefix and partitioning.
        auth_data: Authenticated principal.

    Returns:
        The run — whatever its outcome.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    return await perform_object_storage_delivery(tenant_slug, tenant_id, job_id, body, auth_data)


@router.get(
    "/{tenant_slug}/jobs/{job_id}/deliveries/object-storage",
    response_model=ExportObjectStorageDeliveryRunListResponse,
    response_model_by_alias=True,
    summary="List a job's object-storage deliveries",
    description="Every object-storage delivery of one export job, newest first. Requires `projects:view`.",
)
async def list_export_job_object_storage_deliveries(
    tenant_slug: str,
    job_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportObjectStorageDeliveryRunListResponse:
    """List one export job's object-storage deliveries."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    rows = await asyncio.to_thread(db.list_export_object_storage_delivery_runs, tenant_id, job_id)
    return ExportObjectStorageDeliveryRunListResponse(runs=[run_model(row) for row in rows])
