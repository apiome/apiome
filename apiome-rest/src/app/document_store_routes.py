"""Document store settings and connection test — COA-5.9 (#7085).

The store is configured only by the REST server's environment (``APIOME_DOCUMENT_STORE*``);
these endpoints show that configuration and check it, and never change it or reveal a
credential. Each is served on two planes with the same body:

* ``GET /v1/ops/document-store`` and ``POST /v1/ops/document-store/test`` — platform admins
  (a bearer token or API key whose user is a platform administrator), like the rest of
  ``/v1/ops``.
* ``GET /v1/admin/document-store`` and ``POST /v1/admin/document-store/test`` — the super-admin
  console (a verified ``admin_session`` cookie or ``X-Admin-Session`` header), which the
  console's **Document store** page calls through its own proxy. The UI never talks to the
  bucket.

``GET`` reports the active backend, the configured one and any startup fallback, the non-secret
settings (bucket, prefix, region, endpoint, encryption, …), a cached reachability check, and the
document index's object count, bytes and latest integrity verification. ``POST …/test`` writes,
reads back and deletes one probe object and reports each step.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .auth_provider_config_routes import require_super_admin
from .database import db
from .document_store_health import describe_store, probe_store
from .keyset_pagination import MAX_REVISION_PAGE_LIMIT
from .permissions import enforce_platform_admin

ops_router = APIRouter(prefix="/v1/ops", tags=["ops"])
admin_router = APIRouter(prefix="/v1/admin", tags=["ops"])

_NO_STORE = {"Cache-Control": "no-store"}


class _CamelModel(BaseModel):
    """Fields are snake_case in Python and camelCase on the wire."""

    model_config = ConfigDict(populate_by_name=True)


class DocumentStoreHealth(_CamelModel):
    """The latest reachability check of the active store."""

    ok: bool = Field(..., description="Whether the store answered.")
    checked_at: float = Field(..., description="When the check ran (epoch seconds).", alias="checkedAt")
    error: Optional[str] = Field(None, description="The redacted failure; null when ok.")


class DocumentStoreBackendUsage(_CamelModel):
    """Indexed objects held by one backend."""

    backend: str = Field(..., description="db, s3 or filesystem.")
    objects: int = Field(..., description="Indexed objects this backend holds.")
    bytes: int = Field(..., description="Their total size in bytes.")


class DocumentStoreIntegrity(_CamelModel):
    """What integrity runs have verified so far."""

    last_verified_at: Optional[str] = Field(
        None,
        description="Latest time an integrity run verified an object (ISO 8601); null when none has.",
        alias="lastVerifiedAt",
    )
    verified_objects: int = Field(..., description="Indexed objects verified at least once.", alias="verifiedObjects")


class DocumentStoreUsage(_CamelModel):
    """Totals from the document index (originals, rendered documents, frozen schemas)."""

    objects: int = Field(..., description="Indexed objects across every backend.")
    bytes: int = Field(..., description="Their total size in bytes.")
    by_backend: List[DocumentStoreBackendUsage] = Field(default_factory=list, alias="byBackend")
    integrity: DocumentStoreIntegrity


class DocumentStoreTenantBucket(_CamelModel):
    """A tenant that keeps its documents in its own bucket (COA-5.15, #7092)."""

    tenant_id: str = Field(..., alias="tenantId")
    tenant_slug: str = Field(..., alias="tenantSlug")
    tenant_name: Optional[str] = Field(None, alias="tenantName")
    mode: Literal["platform", "tenant"] = Field(
        ..., description="tenant: documents go to the bucket. platform: it moved back; the bucket may hold old copies."
    )
    bucket: str
    endpoint_url: Optional[str] = Field(None, description="The service URL; null for AWS.", alias="endpointUrl")
    move_state: Literal["idle", "running", "completed", "failed"] = Field(..., alias="moveState")
    cleanup_pending: bool = Field(False, alias="cleanupPending")
    unavailable_since: Optional[str] = Field(
        None, description="When the bucket stopped answering; null while it works.", alias="unavailableSince"
    )
    last_error: Optional[str] = Field(None, description="Why it is unavailable (redacted).", alias="lastError")


class DocumentStoreStatus(_CamelModel):
    """The active document store: settings (never credentials), health and usage."""

    backend: str = Field(..., description="The backend the server runs on: db, s3 or filesystem.")
    configured_backend: str = Field(
        ..., description="The backend APIOME_DOCUMENT_STORE names.", alias="configuredBackend"
    )
    fallback: bool = Field(..., description="True when startup fell back to db (APIOME_DOCUMENT_STORE_FALLBACK=db).")
    fallback_reason: Optional[str] = Field(
        None, description="Why the configured backend was not usable (redacted).", alias="fallbackReason"
    )
    backends: List[str] = Field(..., description="Every backend this server supports.")
    bucket: Optional[str] = Field(None, description="s3: the bucket.")
    prefix: str = Field(..., description="The folder every object key starts with ('' for none).")
    region: Optional[str] = Field(None, description="s3: the signing region.")
    endpoint_url: Optional[str] = Field(None, description="s3: the service URL; null for AWS.", alias="endpointUrl")
    addressing_style: Optional[str] = Field(None, description="s3: auto, path or virtual.", alias="addressingStyle")
    path: Optional[str] = Field(None, description="filesystem: the storage directory.")
    encryption: Optional[str] = Field(None, description="s3: none, sse-s3 or sse-kms.")
    kms_key_id: Optional[str] = Field(
        None, description="s3 with sse-kms: the key; null for the bucket default.", alias="kmsKeyId"
    )
    credentials: Optional[Literal["static", "default-chain"]] = Field(
        None, description="s3: 'static' (keys in the environment) or 'default-chain' (boto3's chain / IAM role)."
    )
    presign_ttl_seconds: Optional[int] = Field(
        None, description="s3: default lifetime of a download link.", alias="presignTtlSeconds"
    )
    max_object_bytes: Optional[int] = Field(
        None, description="db: the largest object accepted.", alias="maxObjectBytes"
    )
    health: DocumentStoreHealth
    usage: Optional[DocumentStoreUsage] = Field(None, description="Null when the document index cannot be read.")
    tenant_buckets_allowed: bool = Field(
        False,
        description="Whether tenants may use their own bucket (APIOME_DOCUMENT_STORE_ALLOW_TENANT_BUCKETS).",
        alias="tenantBucketsAllowed",
    )
    tenant_buckets: List[DocumentStoreTenantBucket] = Field(
        default_factory=list,
        description="Tenants that have configured their own bucket, with its health.",
        alias="tenantBuckets",
    )
    tenant_buckets_truncated: bool = Field(
        False,
        description="True when more tenants have a bucket than `limit` listed.",
        alias="tenantBucketsTruncated",
    )


class DocumentStoreProbeStep(_CamelModel):
    """One step of the connection test."""

    name: Literal["write", "read", "delete"]
    ok: bool
    skipped: bool = Field(False, description="True when an earlier step failed, so this one did not run.")
    duration_ms: float = Field(..., alias="durationMs")
    error: Optional[str] = Field(None, description="The redacted failure; null when ok or skipped.")


class DocumentStoreProbeResult(_CamelModel):
    """The outcome of writing, reading back and deleting one probe object."""

    ok: bool = Field(..., description="True when every step succeeded.")
    backend: str
    checked_at: float = Field(..., description="When the test finished (epoch seconds).", alias="checkedAt")
    duration_ms: float = Field(..., alias="durationMs")
    steps: List[DocumentStoreProbeStep]


def _tenant_bucket_limit() -> Any:
    """The ``limit`` query parameter of the status read: how many ``tenantBuckets`` it lists."""
    return Query(
        default=MAX_REVISION_PAGE_LIMIT,
        ge=1,
        le=MAX_REVISION_PAGE_LIMIT,
        description=(
            f"How many `tenantBuckets` to list (by tenant slug). At most {MAX_REVISION_PAGE_LIMIT:,}; "
            "`tenantBucketsTruncated` says whether more exist."
        ),
    )


async def _status(limit: int) -> JSONResponse:
    """Describe the store from a worker thread (the check and the query block)."""
    body: Dict[str, Any] = await asyncio.to_thread(describe_store, db, tenant_bucket_limit=limit)
    return JSONResponse(content=body, headers=_NO_STORE)


async def _probe() -> JSONResponse:
    """Run the probe from a worker thread."""
    body: Dict[str, Any] = await asyncio.to_thread(probe_store)
    return JSONResponse(content=body, headers=_NO_STORE)


@ops_router.get("/document-store", response_model=DocumentStoreStatus)
async def ops_document_store(
    limit: int = _tenant_bucket_limit(),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> JSONResponse:
    """The active document store: backend, settings, health and usage (COA-5.9, #7085). Platform-admin only.

    Settings come from the server environment and are read-only here; credentials are never
    returned — ``credentials`` only says whether static keys or boto3's default chain are used.
    """
    await run_in_threadpool(enforce_platform_admin, db, auth_data)
    return await _status(limit)


@ops_router.post("/document-store/test", response_model=DocumentStoreProbeResult)
async def ops_test_document_store(auth_data: Dict[str, Any] = Depends(validate_authentication)) -> JSONResponse:
    """Test the document store: write, read back and delete a probe object (COA-5.9, #7085). Platform-admin only.

    Answers ``200`` whether or not the test passed; ``ok`` and each step's ``error`` say what
    failed.
    """
    await run_in_threadpool(enforce_platform_admin, db, auth_data)
    return await _probe()


@admin_router.get("/document-store", response_model=DocumentStoreStatus)
async def admin_document_store(
    limit: int = _tenant_bucket_limit(), _: None = Depends(require_super_admin)
) -> JSONResponse:
    """The super-admin console's view of ``GET /v1/ops/document-store`` (COA-5.9, #7085)."""
    return await _status(limit)


@admin_router.post("/document-store/test", response_model=DocumentStoreProbeResult)
async def admin_test_document_store(_: None = Depends(require_super_admin)) -> JSONResponse:
    """The super-admin console's view of ``POST /v1/ops/document-store/test`` (COA-5.9, #7085)."""
    return await _probe()
