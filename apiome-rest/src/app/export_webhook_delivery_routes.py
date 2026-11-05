"""Export webhook delivery routes — MFX-38.2 (#4329).

* ``POST /v1/export/{tenant_slug}/jobs/{job_id}/deliveries/webhook`` sends a **completed** export
  job's result — manifest, fidelity report and bundle — to a URL, HMAC-signed with the caller's
  secret, and returns the run after its first attempt. Retries happen in the background
  (:mod:`app.export_webhook_delivery_pipeline`).
* ``GET`` on the same path lists the job's webhook deliveries, every attempt included.
* ``GET …/deliveries/webhook/{delivery_id}/bundle?expires=…&signature=…`` is the **fetch link** a large
  bundle travels as. It needs no Apiome credentials — the signature is the credential — and stops
  working when it expires or the export's artifact does.

**Permissions.** Sending an export outside the workspace needs ``versions:publish``, as a git
delivery (MFX-38.1) does; listing needs ``projects:view``. Every delivery is audited as
``export.webhook_delivery`` with the receiver's host only (a webhook URL often carries a token).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .auth import get_authenticated_user_id, validate_authentication
from .config import settings
from .database import db
from .download_headers import attachment_headers
from .export_git_delivery_routes import _check_tenant, _subject
from .export_job_engine import (
    ExportJobResult,
    get_export_job_status,
    iter_download_chunks,
    resolve_export_download,
)
from .export_webhook_delivery import (
    BundleArtifact,
    ExportWebhookDeliveryRequestError,
    WebhookDeliveryRequest,
    build_payload,
    display_url,
    fetch_url,
    normalize_request,
    sign_body,
    stable_body,
    verify_fetch_signature,
)
from .export_webhook_delivery_pipeline import start_delivery
from .permissions import Action, Resource, enforce_permission
from .sdk_publish_routes import tenant_id_of, write_audit
from .ssrf_guard import SSRFError, validate_url

router = APIRouter(prefix="/v1/export", tags=["export-delivery"])

AUDIT_DELIVERY = "export.webhook_delivery"


class ExportWebhookDeliveryAttemptModel(BaseModel):
    """One attempt of a webhook delivery."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    attempt: int = Field(description="1-based attempt number (sent as `X-Apiome-Delivery-Attempt`).")
    at: str = Field(description="When it was made (UTC, ISO 8601).")
    http_status: Optional[int] = Field(default=None, alias="httpStatus",
                                       description="The receiver's status code; null when it never answered.")
    latency_ms: int = Field(default=0, alias="latencyMs")
    error: Optional[str] = Field(default=None, description="Why it did not succeed.")
    response_preview: Optional[str] = Field(default=None, alias="responsePreview",
                                            description="The start of the receiver's response body.")


class ExportWebhookDeliveryRunModel(BaseModel):
    """One export webhook delivery.

    Attributes:
        run_id: The delivery — also its `X-Apiome-Delivery` header and the body's `deliveryId`.
        status: ``pending``, ``delivering``, ``retrying``, ``delivered`` or ``failed``.
        job_id: The export job delivered.
        target_url: The receiver, without its query string.
        artifact_delivery: ``inline`` or ``fetch``.
        payload_sha256: SHA-256 of the signed body.
        attempt_count: Attempts made.
        max_attempts: Attempts before the run fails.
        attempts: Every attempt, oldest first.
        next_attempt_at: When the next retry is due (``retrying``).
        last_http_status: The receiver's last status code.
        fidelity: The fidelity summary the body carried.
        error_code: The last failure's code.
        error_message: The last failure's message.
        started_at: When the delivery was requested.
        finished_at: When it was delivered or failed.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    run_id: str = Field(serialization_alias="runId")
    status: str
    job_id: str = Field(serialization_alias="jobId")
    target_url: str = Field(serialization_alias="targetUrl")
    artifact_delivery: str = Field(serialization_alias="artifactDelivery")
    payload_sha256: Optional[str] = Field(default=None, serialization_alias="payloadSha256")
    attempt_count: int = Field(default=0, serialization_alias="attemptCount")
    max_attempts: int = Field(serialization_alias="maxAttempts")
    attempts: List[ExportWebhookDeliveryAttemptModel] = Field(default_factory=list)
    next_attempt_at: Optional[datetime] = Field(default=None, serialization_alias="nextAttemptAt")
    last_http_status: Optional[int] = Field(default=None, serialization_alias="lastHttpStatus")
    fidelity: Dict[str, Any] = Field(default_factory=dict)
    error_code: Optional[str] = Field(default=None, serialization_alias="errorCode")
    error_message: Optional[str] = Field(default=None, serialization_alias="errorMessage")
    started_at: Optional[datetime] = Field(default=None, serialization_alias="startedAt")
    finished_at: Optional[datetime] = Field(default=None, serialization_alias="finishedAt")


class ExportWebhookDeliveryRunListResponse(BaseModel):
    """A job's webhook deliveries, newest first."""

    model_config = ConfigDict(extra="forbid")

    runs: List[ExportWebhookDeliveryRunModel] = Field(default_factory=list)


def run_model(row: Dict[str, Any]) -> ExportWebhookDeliveryRunModel:
    """Project a stored run onto the wire model (the URL shown without its query string)."""
    return ExportWebhookDeliveryRunModel(
        run_id=str(row["id"]), status=str(row["status"]), job_id=str(row["job_id"]),
        target_url=display_url(str(row.get("target_url") or "")),
        artifact_delivery=str(row.get("artifact_delivery") or "inline"),
        payload_sha256=row.get("payload_sha256"), attempt_count=int(row.get("attempt_count") or 0),
        max_attempts=int(row.get("max_attempts") or 1),
        attempts=[ExportWebhookDeliveryAttemptModel.model_validate(item) for item in row.get("attempts") or []],
        next_attempt_at=row.get("next_attempt_at"), last_http_status=row.get("last_http_status"),
        fidelity=dict(row.get("fidelity") or {}), error_code=row.get("error_code"),
        error_message=row.get("error_message"), started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
    )


def _completed_result(status: Any) -> ExportJobResult:
    """The result of a job that can be delivered, or refuse (409)."""
    result = status.result
    if status.state != "completed" or result is None:
        raise HTTPException(status_code=409, detail={
            "code": "export-webhook-delivery-job-not-completed",
            "message": f"The export job is {status.state}; only a completed export can be delivered.",
        })
    if result.dry_run:
        raise HTTPException(status_code=409, detail={
            "code": "export-webhook-delivery-dry-run",
            "message": "A dry-run export has no bundle to deliver. Run the export for real, then deliver it.",
        })
    return result


def _fidelity_report(result: ExportJobResult) -> Optional[Dict[str, Any]]:
    """The full fidelity report: the job's envelope, or every target's plus the roll-up."""
    if result.fidelity is not None:
        return result.fidelity.model_dump(mode="json")
    if not result.targets:
        return None
    return {
        "targets": [{"target": t.target, "fidelity": t.fidelity.model_dump(mode="json")} for t in result.targets],
        "rollup": result.fidelity_rollup.model_dump(mode="json") if result.fidelity_rollup else None,
    }


def _manifest_files(result: ExportJobResult) -> List[Dict[str, Any]]:
    """The job's file manifest, camel-cased for the body."""
    out: List[Dict[str, Any]] = []
    for item in result.files:
        entry: Dict[str, Any] = {"path": item.path, "sizeBytes": item.size_bytes}
        if item.media_type:
            entry["mediaType"] = item.media_type
        if item.subject:
            entry["subject"] = item.subject
        out.append(entry)
    return out


def _fetch_link(tenant_slug: str, job_id: str, delivery_id: str, result: ExportJobResult) -> Dict[str, Any]:
    """``{url, expiresAt}`` for a bundle too large to inline, or refuse (409) without a public address."""
    base = (settings.api_public_url or settings.repository_webhook_base_url or "").strip()
    if not base:
        raise HTTPException(status_code=409, detail={
            "code": "export-webhook-delivery-fetch-url-unavailable",
            "message": "This bundle travels as a fetch link, but the server does not know its public "
            "address. Set APIOME_API_PUBLIC_URL (or raise APIOME_EXPORT_WEBHOOK_INLINE_MAX_BYTES), then "
            "deliver again.",
        })
    expires = int(time.time()) + max(60, int(settings.export_webhook_fetch_url_ttl_seconds))
    if result.download_expires_at:
        expires = min(expires, int(result.download_expires_at) // 1000)
    url = fetch_url(base, settings.effective_export_fetch_url_signing_key, tenant_slug, job_id, delivery_id,
                    expires)
    return {"url": url, "expiresAt": datetime.fromtimestamp(expires, timezone.utc).isoformat().replace(
        "+00:00", "Z")}


async def perform_webhook_delivery(
    tenant_slug: str,
    tenant_id: str,
    job_id: str,
    body: WebhookDeliveryRequest,
    auth_data: Dict[str, Any],
    *,
    profile_id: Optional[str] = None,
) -> ExportWebhookDeliveryRunModel:
    """Send one completed export job's result to a webhook, record it and audit it.

    Shared by the direct route and a delivery profile (MFX-38.4); the caller has already enforced
    ``versions:publish`` and checked the tenant.

    Args:
        tenant_slug: The tenant the job was submitted under.
        tenant_id: That tenant's id.
        job_id: The export job.
        body: The receiver, the signing secret and how the bundle travels.
        auth_data: Authenticated principal.
        profile_id: The delivery profile the request came from, recorded on the run and in the audit.

    Returns:
        The run — whatever its outcome.

    Raises:
        HTTPException: 400 for an invalid or refused destination; 404 for an unknown job; 409 for a job
            that cannot be delivered; 410 for an expired artifact.
    """
    try:
        request = normalize_request(body)
        await asyncio.to_thread(validate_url, request.url)
    except ExportWebhookDeliveryRequestError as exc:
        raise HTTPException(status_code=400, detail={"code": "export-webhook-delivery-request-invalid",
                                                     "errors": exc.errors}) from exc
    except SSRFError as exc:
        raise HTTPException(status_code=400, detail={"code": "export-webhook-delivery-destination-refused",
                                                     "errors": [f"url: {exc}"]}) from exc

    status = await get_export_job_status(tenant_slug, job_id)
    result = _completed_result(status)
    download = await asyncio.to_thread(resolve_export_download, tenant_slug, job_id)  # 409 / 410 propagate
    artifact = BundleArtifact(download.filename, download.media_type, download.body, download.content_sha256)
    subject = await asyncio.to_thread(_subject, tenant_slug, tenant_id, job_id, result)

    run_id = str(uuid.uuid4())
    inline = request.artifact == "auto" and len(artifact.data) <= settings.export_webhook_inline_max_bytes
    fetch = None if inline else _fetch_link(tenant_slug, job_id, run_id, result)
    payload = stable_body(build_payload(
        delivery_id=run_id, created_at=datetime.now(timezone.utc), subject=subject,
        files=_manifest_files(result), fidelity_report=_fidelity_report(result),
        download_path=result.download_path, artifact=artifact, inline=inline, fetch=fetch,
    ))
    row = await asyncio.to_thread(
        start_delivery, db, run_id=run_id, tenant_id=tenant_id, job_id=job_id, artifact_id=result.artifact,
        target_url=request.url, artifact_delivery="inline" if inline else "fetch", payload=payload,
        payload_sha256=hashlib.sha256(payload).hexdigest(), signature=sign_body(request.secret, payload),
        version_record_id=result.version_record_id, version_label=result.version_label,
        export_target=subject.target, fidelity=subject.fidelity, actor_id=get_authenticated_user_id(auth_data),
    )
    if row is None:
        raise HTTPException(status_code=500, detail={"code": "export-webhook-delivery-internal-error",
                                                     "message": "The delivery could not be recorded."})
    if profile_id and run_id:
        await asyncio.to_thread(db.set_export_delivery_run_profile, "webhook", tenant_id, run_id, profile_id)
    write_audit(
        tenant_id=tenant_id,
        action=AUDIT_DELIVERY,
        auth_data=auth_data,
        target=result.artifact,
        detail={
            "runId": run_id,
            "status": row.get("status"),
            "jobId": job_id,
            "exportTarget": subject.target,
            "receiverHost": urlsplit(request.url).hostname,
            "artifactDelivery": "inline" if inline else "fetch",
            "httpStatus": row.get("last_http_status"),
            "errorCode": row.get("error_code"),
            **({"profileId": profile_id} if profile_id else {}),
        },
    )
    return run_model(row)


@router.post(
    "/{tenant_slug}/jobs/{job_id}/deliveries/webhook",
    response_model=ExportWebhookDeliveryRunModel,
    response_model_by_alias=True,
    summary="Deliver a completed export to a webhook",
    description=(
        "POSTs a **completed** export job's result to `url` as one JSON body "
        "(`schemaVersion: export.webhook-delivery.v1`, `event: export.delivered`): the export's "
        "coordinates, the file manifest, the fidelity summary and full report, and the bundle — inside "
        "the body (`artifact.delivery: inline`, UTF-8 text or base64 for a zip) when it fits under "
        "`APIOME_EXPORT_WEBHOOK_INLINE_MAX_BYTES` (1 MiB), otherwise as a signed, expiring fetch link "
        "(`artifact.delivery: fetch`) that needs no Apiome credentials. `artifact: fetch` always sends "
        "the link.\n\n"
        "**Signed.** `X-Apiome-Signature: sha256=<hex>` is the HMAC-SHA256 of the exact body under "
        "`secret`. The secret is used once and never stored; retries re-send the same bytes and "
        "signature, with `X-Apiome-Delivery` (the run id, for de-duplication) and "
        "`X-Apiome-Delivery-Attempt`.\n\n"
        "**Retried.** The first attempt is made before this answers. No answer, `408`, `425`, `429` or "
        "a `5xx` is retried after 10 s, 60 s and 5 min (longer when `Retry-After` asks); a `3xx` "
        "(redirects are not followed) or another `4xx` fails the run at once.\n\n"
        "**Guarded.** `url` must resolve to public addresses only — checked now and on every attempt.\n\n"
        "Every outcome is a run on the job (`GET` this path). Requires `versions:publish`. Audited as "
        "`export.webhook_delivery`."
    ),
    responses={
        400: {"description": "Invalid URL or secret, or a destination the SSRF guard refuses."},
        404: {"description": "Unknown export job for this tenant."},
        409: {"description": "The job is not completed or is a dry run, or a fetch link is needed but "
                             "the server's public address is not configured."},
        410: {"description": "The export's artifact has expired; export again, then deliver."},
    },
)
async def deliver_export_job_to_webhook(
    tenant_slug: str,
    job_id: str,
    body: WebhookDeliveryRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportWebhookDeliveryRunModel:
    """Send one completed export job's result to a webhook.

    Args:
        tenant_slug: The tenant the job was submitted under.
        job_id: The export job.
        body: The receiver, the signing secret and how the bundle travels.
        auth_data: Authenticated principal.

    Returns:
        The run after its first attempt — whatever its outcome.

    Raises:
        HTTPException: 403 without ``versions:publish``; 400 for an invalid or refused destination;
            404 for an unknown job; 409 for a job that cannot be delivered; 410 for an expired artifact.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    return await perform_webhook_delivery(tenant_slug, tenant_id, job_id, body, auth_data)


@router.get(
    "/{tenant_slug}/jobs/{job_id}/deliveries/webhook",
    response_model=ExportWebhookDeliveryRunListResponse,
    response_model_by_alias=True,
    summary="List a job's webhook deliveries",
    description="Every webhook delivery of one export job, newest first, with every attempt. Requires "
    "`projects:view`.",
)
async def list_export_job_webhook_deliveries(
    tenant_slug: str,
    job_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportWebhookDeliveryRunListResponse:
    """List one export job's webhook deliveries.

    Args:
        tenant_slug: The tenant the job was submitted under.
        job_id: The export job.
        auth_data: Authenticated principal.

    Returns:
        The runs, newest first.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    rows = await asyncio.to_thread(db.list_export_webhook_delivery_runs, tenant_id, job_id)
    return ExportWebhookDeliveryRunListResponse(runs=[run_model(row) for row in rows])


@router.get(
    "/{tenant_slug}/jobs/{job_id}/deliveries/webhook/{delivery_id}/bundle",
    summary="Fetch a webhook delivery's bundle (signed link)",
    description=(
        "The fetch link a webhook delivery hands the receiver when the bundle is too large to inline "
        "(`artifact.url` in the body). The `expires` and `signature` query parameters are the "
        "credential: no Apiome sign-in is needed, and nothing else is accepted. Streams the same bytes "
        "as the job's download (with `Digest` / `X-Content-SHA256`). `403` for a bad signature, `410` "
        "once the link or the export's artifact has expired."
    ),
    response_class=StreamingResponse,
)
async def fetch_export_webhook_bundle(
    tenant_slug: str,
    job_id: str,
    delivery_id: str,
    expires: int = Query(..., description="The link's expiry, epoch seconds."),
    signature: str = Query(..., max_length=128, description="The link's signature."),
) -> StreamingResponse:
    """Stream the bundle a signed fetch link names.

    Args:
        tenant_slug: The tenant.
        job_id: The export job.
        delivery_id: The delivery the link was minted for.
        expires: Expiry, epoch seconds (signed).
        signature: HMAC-SHA256 of the coordinates and expiry.

    Returns:
        The bundle, streamed.

    Raises:
        HTTPException: 403 for a signature that does not match; 410 for an expired link or artifact.
    """
    if not verify_fetch_signature(settings.effective_export_fetch_url_signing_key, tenant_slug, job_id,
                                  delivery_id, expires, signature):
        raise HTTPException(status_code=403, detail={"code": "export-webhook-delivery-fetch-link-invalid",
                                                     "message": "This fetch link is not valid."})
    if time.time() >= expires:
        raise HTTPException(status_code=410, detail={
            "code": "export-webhook-delivery-fetch-link-expired",
            "message": "This fetch link has expired. Deliver the export again for a new one.",
        })
    artifact = await asyncio.to_thread(resolve_export_download, tenant_slug, job_id)  # 404 / 409 / 410
    headers = {**attachment_headers(artifact.filename, "export"), "Content-Length": str(artifact.content_length)}
    if artifact.content_sha256:
        from .export_artifact_store import content_sha256_hex_only, digest_header_value  # noqa: PLC0415

        headers["Digest"] = digest_header_value(artifact.content_sha256)
        headers["X-Content-SHA256"] = content_sha256_hex_only(artifact.content_sha256)
    return StreamingResponse(iter_download_chunks(artifact), media_type=artifact.media_type, headers=headers)
