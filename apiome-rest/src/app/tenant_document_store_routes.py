"""``/v1/tenants/{tenant_slug}/document-store`` — a tenant's own bucket (COA-5.15, #7092).

* ``GET`` — where the tenant's documents are kept, the bucket settings (never a credential), the
  bucket's health and the progress of a move.
* ``PUT`` — choose the platform store or the tenant's own bucket. Changing the choice starts a
  move of the existing objects in the background; ``GET`` reports its progress.
* ``POST …/test`` — write, read back and delete a probe object in the bucket, under the tenant's
  own key layout, with the saved settings or with settings not saved yet.
* ``POST …/cleanup`` — after a finished move, delete the copies left in the old place. Needs
  ``{"confirm": true}``.

Every route needs ``document_store:manage`` (Owner and Admin by default). ``PUT``, ``test`` and
``cleanup`` are refused with ``403 tenant-document-store-disabled`` unless the install allows
tenant buckets (``APIOME_DOCUMENT_STORE_ALLOW_TENANT_BUCKETS``). Changes are audited; an audit
row never holds a credential.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .auth import validate_authentication
from .database import db
from .document_store import get_document_store
from .document_store_health import probe_store
from .document_store_move import (
    MoveBusy,
    begin_move,
    cleanup_old_copies,
    move_running_here,
    start_move_thread,
)
from .permissions import Action, Resource, enforce_permission
from .sdk_publish_routes import tenant_id_of, write_audit
from .tenant_document_store import (
    CODE_UNAVAILABLE,
    MODE_PLATFORM,
    MODE_TENANT,
    MOVE_RUNNING,
    TenantDocumentStoreUnavailable,
    TenantStoreInputError,
    TenantStoreSettings,
    build_tenant_store,
    load_settings,
    normalize_settings,
    save_settings,
    tenant_buckets_allowed,
)

logger = logging.getLogger(__name__)

__all__ = ["router", "tenant_store_unavailable_handler"]

router = APIRouter(prefix="/v1/tenants", tags=["tenants"])

_NO_STORE = {"Cache-Control": "no-store"}

CODE_DISABLED = "tenant-document-store-disabled"
CODE_MOVE_RUNNING = "tenant-document-store-move-running"
CODE_BUCKET_IN_USE = "tenant-document-store-bucket-in-use"
CODE_TEST_FAILED = "tenant-document-store-test-failed"
CODE_CONFIRM_REQUIRED = "tenant-document-store-confirm-required"

AUDIT_UPDATED = "document_store.settings_updated"
AUDIT_CLEANED = "document_store.old_copies_deleted"


class _CamelModel(BaseModel):
    """Fields are snake_case in Python and camelCase on the wire."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)


class TenantDocumentStoreInput(_CamelModel):
    """Where a tenant's documents should be kept."""

    mode: Literal["platform", "tenant"] = Field(
        description="`platform` keeps documents in the install's store; `tenant` keeps them in your own bucket."
    )
    credential_id: Optional[str] = Field(
        default=None,
        description="A storage credential of this workspace (`POST /v1/export/{tenant}/storage-credentials`).",
    )
    bucket: Optional[str] = Field(default=None, description="The bucket. It must already exist.")
    prefix: Optional[str] = Field(
        default=None, description="Folder inside the bucket. Defaults to `apiome`; empty writes at the root."
    )
    region: Optional[str] = Field(default=None, description="Signing region; empty takes the credential's.")
    endpoint_url: Optional[str] = Field(
        default=None, description="Service URL for a non-AWS store; empty takes the credential's."
    )
    addressing_style: Optional[Literal["auto", "path", "virtual"]] = Field(default=None)
    sse: Optional[Literal["", "s3", "kms"]] = Field(
        default=None, description="Server-side encryption: empty, `s3` (SSE-S3) or `kms` (SSE-KMS)."
    )
    kms_key_id: Optional[str] = Field(default=None, description="The KMS key for `sse = kms`.")


class TenantDocumentStoreHealth(_CamelModel):
    """Whether the tenant's bucket answered the last time it was used."""

    available: bool
    unavailable_since: Optional[datetime] = None
    error: Optional[str] = Field(default=None, description="Why it is unavailable. Never contains a credential.")


class TenantDocumentStoreMove(_CamelModel):
    """The move of existing objects to where documents are kept now."""

    state: Literal["idle", "running", "completed", "failed"]
    target: Optional[Literal["platform", "tenant"]] = None
    total: int = 0
    moved: int = 0
    failed: int = 0
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class TenantDocumentStore(_CamelModel):
    """A tenant's document store settings, health and move progress. Never a credential."""

    allowed: bool = Field(description="Whether this install lets workspaces use their own bucket.")
    mode: Literal["platform", "tenant"]
    credential_id: Optional[str] = None
    credential_name: Optional[str] = None
    bucket: Optional[str] = None
    prefix: str = "apiome"
    region: str = ""
    endpoint_url: str = ""
    addressing_style: Literal["auto", "path", "virtual"] = "auto"
    sse: Literal["", "s3", "kms"] = ""
    kms_key_id: str = ""
    health: TenantDocumentStoreHealth
    move: TenantDocumentStoreMove
    cleanup_pending: bool = Field(
        default=False, description="A finished move left old copies that `POST …/cleanup` deletes."
    )


class TenantDocumentStoreProbeStep(_CamelModel):
    """One step of the bucket test."""

    name: Literal["write", "read", "delete"]
    ok: bool
    skipped: bool = False
    duration_ms: float = 0.0
    error: Optional[str] = None


class TenantDocumentStoreProbeResult(_CamelModel):
    """The outcome of writing, reading back and deleting one probe object in the bucket."""

    ok: bool
    bucket: Optional[str] = None
    error: Optional[str] = Field(default=None, description="Why the test could not run at all.")
    steps: List[TenantDocumentStoreProbeStep] = Field(default_factory=list)


class TenantDocumentStoreCleanupInput(_CamelModel):
    """The explicit confirm that old copies may be deleted."""

    confirm: bool = False


class TenantDocumentStoreCleanupResult(_CamelModel):
    """What the cleanup removed."""

    checked: int
    deleted: int


# ── Helpers ───────────────────────────────────────────────────────────────────────────────────


def _refuse(status_code: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message, **extra})


def _require_allowed() -> None:
    if not tenant_buckets_allowed():
        raise _refuse(
            403,
            CODE_DISABLED,
            "This install does not let workspaces use their own bucket. A platform administrator "
            "turns it on with APIOME_DOCUMENT_STORE_ALLOW_TENANT_BUCKETS.",
        )


def _credential_row(tenant_id: str, credential_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """The tenant's credential without its payload, or ``None``."""
    if not credential_id:
        return None
    row = db.get_export_storage_credential(tenant_id, credential_id)
    if not row:
        return None
    row = dict(row)
    row.pop("encrypted_payload", None)
    return row


def _view(tenant_id: str, current: Optional[TenantStoreSettings]) -> Dict[str, Any]:
    """The response body for a tenant's settings row (or for none)."""
    current = current or TenantStoreSettings(tenant_id=tenant_id)
    credential = _credential_row(tenant_id, current.credential_id)
    counts = current.move_counts or {}
    return TenantDocumentStore(
        allowed=tenant_buckets_allowed(),
        mode=current.mode,  # type: ignore[arg-type]
        credential_id=current.credential_id,
        credential_name=(credential or {}).get("name"),
        bucket=current.bucket,
        prefix=current.prefix,
        region=current.region,
        endpoint_url=current.endpoint_url,
        addressing_style=current.addressing_style,  # type: ignore[arg-type]
        sse=current.sse,  # type: ignore[arg-type]
        kms_key_id=current.kms_key_id,
        health=TenantDocumentStoreHealth(
            available=current.unavailable_since is None,
            unavailable_since=current.unavailable_since,
            error=current.last_error,
        ),
        move=TenantDocumentStoreMove(
            state=current.move_state,  # type: ignore[arg-type]
            target=current.move_target,  # type: ignore[arg-type]
            total=int(counts.get("total") or 0),
            moved=int(counts.get("moved") or 0),
            failed=int(counts.get("failed") or 0),
            error=current.move_error,
            started_at=current.move_started_at,
            finished_at=current.move_finished_at,
        ),
        cleanup_pending=current.cleanup_pending,
    ).model_dump(mode="json", by_alias=True)


def _payload(body: TenantDocumentStoreInput, current: Optional[TenantStoreSettings]) -> Dict[str, Any]:
    """Submitted settings, with every omitted field taken from the saved row."""
    sent = body.model_dump(exclude_unset=True)
    base = current or TenantStoreSettings(tenant_id="")
    return {
        "mode": body.mode,
        "credential_id": sent.get("credential_id", base.credential_id),
        "bucket": sent.get("bucket", base.bucket),
        "prefix": sent["prefix"] if sent.get("prefix") is not None else (base.prefix if current else None),
        "region": sent.get("region") if sent.get("region") is not None else base.region,
        "endpoint_url": sent.get("endpoint_url") if sent.get("endpoint_url") is not None else base.endpoint_url,
        "addressing_style": sent.get("addressing_style") or base.addressing_style,
        "sse": sent.get("sse") if sent.get("sse") is not None else base.sse,
        "kms_key_id": sent.get("kms_key_id") if sent.get("kms_key_id") is not None else base.kms_key_id,
    }


def _normalized(tenant_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate ``payload`` (blocking: SSRF guard) or raise the 400 it deserves."""
    credential = _credential_row(tenant_id, payload.get("credential_id"))
    try:
        return normalize_settings(payload, credential=credential)
    except TenantStoreInputError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "errors": exc.errors}) from None


def _probe(tenant_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """Build the store ``values`` describe and run the write / read / delete probe on it."""
    candidate = TenantStoreSettings(tenant_id=tenant_id, **{**values, "mode": MODE_TENANT})
    try:
        store = build_tenant_store(db, candidate)
    except TenantDocumentStoreUnavailable as exc:
        return {"ok": False, "bucket": candidate.bucket, "error": exc.reason, "steps": []}
    result = probe_store(store, tenant_id=tenant_id)
    return {"ok": bool(result["ok"]), "bucket": candidate.bucket, "error": None, "steps": result["steps"]}


def _objects_in_bucket(tenant_id: str) -> bool:
    rows = db.execute_query(
        "SELECT 1 AS present FROM apiome.document_objects WHERE tenant_id = %s AND backend = 'tenant_s3' LIMIT 1",
        (tenant_id,),
    )
    return bool(rows)


_LOCATION_FIELDS = ("bucket", "prefix", "endpoint_url")


def _save(tenant_id: str, body: TenantDocumentStoreInput, auth_data: Dict[str, Any], actor_id: str) -> Dict[str, Any]:
    """The whole ``PUT`` (blocking): validate, test, store, start the move, audit."""
    router_store = get_document_store()
    current = load_settings(db, tenant_id)
    if current is not None and current.move_state == MOVE_RUNNING:
        if move_running_here(tenant_id) or body.mode != current.move_target:
            raise _refuse(
                409, CODE_MOVE_RUNNING, "A move of this workspace's documents is running. Wait for it to finish."
            )
        # The run that owned this move is gone (a restart): pick it up where it stopped.
        start_move_thread(db, router_store, tenant_id)
        return _view(tenant_id, load_settings(db, tenant_id))
    if current is None and body.mode == MODE_PLATFORM:
        return _view(tenant_id, None)

    values = _normalized(tenant_id, _payload(body, current))
    if current is not None and current.has_bucket and any(
        (values.get(name) or "") != (getattr(current, name) or "") for name in _LOCATION_FIELDS
    ):
        if current.uses_tenant_bucket or current.cleanup_pending or _objects_in_bucket(tenant_id):
            raise _refuse(
                409,
                CODE_BUCKET_IN_USE,
                "Documents are stored in the current bucket. Move them back to the platform store and "
                "delete the old copies before pointing at a different bucket, folder or endpoint.",
            )
    if values["mode"] == MODE_TENANT:
        probe = _probe(tenant_id, values)
        if not probe["ok"]:
            raise _refuse(
                400,
                CODE_TEST_FAILED,
                "The bucket did not pass the write, read and delete test, so nothing was changed.",
                test=probe,
            )

    mode_changed = (current.mode if current else MODE_PLATFORM) != values["mode"]
    save_settings(db, tenant_id, values, actor_id=actor_id)
    if mode_changed:
        begin_move(db, tenant_id, values["mode"])
    router_store.invalidate(tenant_id)
    if mode_changed:
        start_move_thread(db, router_store, tenant_id)
    write_audit(
        tenant_id=tenant_id,
        action=AUDIT_UPDATED,
        auth_data=auth_data,
        target="document-store",
        detail={
            "mode": values["mode"],
            "previousMode": current.mode if current else MODE_PLATFORM,
            "credentialId": values["credential_id"],
            "bucket": values["bucket"],
            "prefix": values["prefix"],
            "region": values["region"],
            "endpointUrl": values["endpoint_url"],
            "addressingStyle": values["addressing_style"],
            "sse": values["sse"],
            "kmsKeyId": values["kms_key_id"],
            "moveStarted": mode_changed,
        },
    )
    return _view(tenant_id, load_settings(db, tenant_id))


# ── Routes ────────────────────────────────────────────────────────────────────────────────────


@router.get(
    "/{tenant_slug}/document-store",
    response_model=TenantDocumentStore,
    summary="Read where the workspace's documents are kept",
    description=(
        "Whether originals and rendered documents are kept in the install's store (`platform`) or "
        "in the workspace's own S3-compatible bucket (`tenant`), the bucket settings, whether the "
        "bucket answered the last time it was used, and the progress of a move. `allowed` is false "
        "when the install does not offer tenant buckets. A credential is never returned — only the "
        "id and name of the storage credential in use.\n\nRequires `document_store:manage`."
    ),
)
async def get_tenant_document_store(
    tenant_slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> JSONResponse:
    """Read the tenant's document store settings."""
    enforce_permission(db, auth_data, Resource.DOCUMENT_STORE, Action.MANAGE, target="document-store")
    _ = tenant_slug
    tenant_id = tenant_id_of(auth_data)
    body = await asyncio.to_thread(lambda: _view(tenant_id, load_settings(db, tenant_id)))
    return JSONResponse(content=body, headers=_NO_STORE)


@router.put(
    "/{tenant_slug}/document-store",
    response_model=TenantDocumentStore,
    summary="Choose where the workspace's documents are kept",
    description=(
        "Set `mode` to `tenant` with a `credentialId` and `bucket` to keep documents in your own "
        "bucket, or to `platform` to go back to the install's store. Fields left out keep their "
        "saved value.\n\n"
        "Before a bucket is saved it must pass the same write, read and delete test as "
        "`POST …/document-store/test`; a failed test answers `400 tenant-document-store-test-failed` "
        "and changes nothing. The endpoint must pass the SSRF guard.\n\n"
        "Changing `mode` starts a move of the existing objects in the background. New documents go "
        "to the new place at once; each existing one is copied, verified and only then read from "
        "the new place, so nothing fails while the move runs. `GET` reports its progress. Old "
        "copies stay until `POST …/document-store/cleanup`.\n\n"
        "`409 tenant-document-store-move-running` while a move runs. "
        "`409 tenant-document-store-bucket-in-use` when the bucket, folder or endpoint is changed "
        "while documents are stored there. `403 tenant-document-store-disabled` when the install "
        "does not offer tenant buckets.\n\n"
        "Audited as `document_store.settings_updated`. Requires `document_store:manage`."
    ),
)
async def put_tenant_document_store(
    tenant_slug: str,
    body: TenantDocumentStoreInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> JSONResponse:
    """Change the tenant's document store settings and start the move if the mode changed."""
    actor_id = enforce_permission(db, auth_data, Resource.DOCUMENT_STORE, Action.MANAGE, target="document-store")
    _ = tenant_slug
    _require_allowed()
    tenant_id = tenant_id_of(auth_data)
    content = await asyncio.to_thread(_save, tenant_id, body, auth_data, actor_id)
    return JSONResponse(content=content, headers=_NO_STORE)


@router.post(
    "/{tenant_slug}/document-store/test",
    response_model=TenantDocumentStoreProbeResult,
    summary="Test the workspace's bucket",
    description=(
        "Writes, reads back and deletes one small probe object under "
        "`<prefix>/tenants/<tenant id>/objects/sha256/…` — the key layout every document uses — so "
        "a bucket policy that does not allow it fails here and not during an import. Send settings "
        "in the body to test them before saving; send no body to test the saved settings.\n\n"
        "Answers `200` whether or not the test passed: `ok` and each step's `error` say what "
        "failed. An error never contains a credential.\n\nRequires `document_store:manage`."
    ),
)
async def test_tenant_document_store(
    tenant_slug: str,
    body: Optional[TenantDocumentStoreInput] = None,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> JSONResponse:
    """Probe the tenant's bucket with submitted or saved settings."""
    enforce_permission(db, auth_data, Resource.DOCUMENT_STORE, Action.MANAGE, target="document-store")
    _ = tenant_slug
    _require_allowed()
    tenant_id = tenant_id_of(auth_data)

    def run() -> Dict[str, Any]:
        current = load_settings(db, tenant_id)
        if body is None:
            if current is None or not current.has_bucket:
                message = "No bucket is configured for this workspace."
                return {"ok": False, "bucket": None, "error": message, "steps": []}
            payload = {name: getattr(current, name) for name in (
                "credential_id", "bucket", "prefix", "region", "endpoint_url", "addressing_style", "sse", "kms_key_id"
            )}
            payload["mode"] = MODE_TENANT
        else:
            payload = {**_payload(body, current), "mode": MODE_TENANT}
        return _probe(tenant_id, _normalized(tenant_id, payload))

    result = await asyncio.to_thread(run)
    content = TenantDocumentStoreProbeResult.model_validate(
        {**result, "steps": [
            {"name": s["name"], "ok": s["ok"], "skipped": s.get("skipped", False),
             "duration_ms": s.get("durationMs", 0.0), "error": s.get("error")}
            for s in result["steps"]
        ]}
    ).model_dump(mode="json", by_alias=True)
    return JSONResponse(content=content, headers=_NO_STORE)


@router.post(
    "/{tenant_slug}/document-store/cleanup",
    response_model=TenantDocumentStoreCleanupResult,
    summary="Delete the copies a move left behind",
    description=(
        "After a move, every moved object still has a copy in the place it came from. This deletes "
        "those copies. It needs `{\"confirm\": true}`; anything else answers "
        "`400 tenant-document-store-confirm-required`. An object that failed to move is never "
        "touched, so no document's only copy can be deleted. In your own bucket only keys under "
        "Apiome's folder for this workspace are removed.\n\n"
        "`409 tenant-document-store-move-running` while a move runs.\n\n"
        "Audited as `document_store.old_copies_deleted`. Requires `document_store:manage`."
    ),
)
async def cleanup_tenant_document_store(
    tenant_slug: str,
    body: TenantDocumentStoreCleanupInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> JSONResponse:
    """Delete old copies after an explicit confirm."""
    enforce_permission(db, auth_data, Resource.DOCUMENT_STORE, Action.MANAGE, target="document-store")
    _ = tenant_slug
    _require_allowed()
    if not body.confirm:
        raise _refuse(
            400, CODE_CONFIRM_REQUIRED, "Send {\"confirm\": true} to delete the old copies. This cannot be undone."
        )
    tenant_id = tenant_id_of(auth_data)
    try:
        result = await asyncio.to_thread(cleanup_old_copies, db, get_document_store(), tenant_id)
    except MoveBusy as exc:
        raise _refuse(409, CODE_MOVE_RUNNING, str(exc)) from None
    write_audit(
        tenant_id=tenant_id,
        action=AUDIT_CLEANED,
        auth_data=auth_data,
        target="document-store",
        detail=dict(result),
    )
    return JSONResponse(content=result, headers=_NO_STORE)


# ── The 503 ───────────────────────────────────────────────────────────────────────────────────


async def tenant_store_unavailable_handler(_request: Any, exc: Exception) -> JSONResponse:
    """Answer ``503 tenant-document-store-unavailable`` with the redacted reason.

    Registered for :class:`~app.tenant_document_store.TenantDocumentStoreUnavailable`, so any
    route that needs a stored document and cannot fall back answers the same way.
    """
    reason = getattr(exc, "reason", None) or "The workspace's bucket could not be reached."
    message = f"This workspace keeps its documents in its own bucket, which is unavailable. {reason}"
    return JSONResponse(
        status_code=503,
        content={"detail": {"code": CODE_UNAVAILABLE, "message": message, "reason": reason}},
        headers={**_NO_STORE, "Retry-After": "60"},
    )

