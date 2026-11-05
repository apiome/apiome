"""The export object-storage delivery pipeline — MFX-38.3 (#4330).

One entry point, :func:`deliver_to_object_storage`, that uploads a completed export job's bundle to
an S3-compatible bucket. The rules (layout, manifest, redaction) live in
:mod:`app.export_object_storage_delivery`; what lives here is the order, what each failure means, and
the run row (``export_object_storage_delivery_runs``, V356):

1. The run is recorded ``in_progress``.
2. The credential is read from the vault (``export_storage_credentials``, tenant-scoped) and unsealed
   in memory (:func:`app.mcp_credential_crypto.unseal_credential_payload`). Its secrets are added to
   the redactor before anything could echo them.
3. A custom endpoint is checked against the SSRF policy (:func:`app.ssrf_guard.validate_url`) — again
   at every delivery, since what a name resolves to can change after the credential was stored.
4. Every bundle file is ``PUT`` under ``<prefix>/<partitions>/``, each with its SHA-256 in the
   ``x-amz-meta-sha256`` header.
5. The manifest is written **last** — at ``manifests/<sha256>.json`` and at ``manifest.json`` — so its
   presence means every object it lists is there.

:func:`deliver_to_object_storage` never raises for a delivery problem: a missing or unreadable
credential, a refused endpoint, an unknown bucket, a rejected key or a failed upload becomes a
``failed`` run with a stable ``export-object-storage-delivery-*`` code and a redacted message. The
objects written before a failure are listed on the run.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .database import db as default_db
from .export_git_delivery import BundleFile, DeliverySubject
from .export_object_storage_delivery import (
    NormalizedDeliveryRequest,
    manifest_document,
    manifest_keys,
    object_prefix,
    plan_objects,
    redact,
)
from .mcp_credential_crypto import unseal_credential_payload
from .ssrf_guard import SSRFError, validate_url

logger = logging.getLogger(__name__)

__all__ = [
    "ERROR_BUCKET_MISSING",
    "ERROR_CREDENTIAL_MISSING",
    "ERROR_CREDENTIAL_REJECTED",
    "ERROR_CREDENTIAL_UNAVAILABLE",
    "ERROR_EMPTY_BUNDLE",
    "ERROR_ENDPOINT_REFUSED",
    "ERROR_ENDPOINT_UNREACHABLE",
    "ERROR_INTERNAL",
    "ERROR_PERMISSION_DENIED",
    "ERROR_UPLOAD_FAILED",
    "RUN_STATUSES",
    "S3ClientFactory",
    "build_s3_client",
    "deliver_to_object_storage",
]

RUN_STATUS_IN_PROGRESS = "in_progress"
RUN_STATUS_DELIVERED = "delivered"
RUN_STATUS_FAILED = "failed"
#: Every status, matching V356's ``export_object_storage_delivery_runs_status_check``.
RUN_STATUSES = (RUN_STATUS_IN_PROGRESS, RUN_STATUS_DELIVERED, RUN_STATUS_FAILED)

ERROR_CREDENTIAL_MISSING = "export-object-storage-delivery-credential-missing"
ERROR_CREDENTIAL_UNAVAILABLE = "export-object-storage-delivery-credential-unavailable"
ERROR_CREDENTIAL_REJECTED = "export-object-storage-delivery-credential-rejected"
ERROR_PERMISSION_DENIED = "export-object-storage-delivery-permission-denied"
ERROR_BUCKET_MISSING = "export-object-storage-delivery-bucket-missing"
ERROR_ENDPOINT_REFUSED = "export-object-storage-delivery-endpoint-refused"
ERROR_ENDPOINT_UNREACHABLE = "export-object-storage-delivery-endpoint-unreachable"
ERROR_UPLOAD_FAILED = "export-object-storage-delivery-upload-failed"
ERROR_EMPTY_BUNDLE = "export-object-storage-delivery-empty-bundle"
ERROR_INTERNAL = "export-object-storage-delivery-internal-error"

#: Provider error codes that mean "these keys are wrong or expired".
_REJECTED_CODES = frozenset({"InvalidAccessKeyId", "SignatureDoesNotMatch", "ExpiredToken", "InvalidToken",
                             "TokenRefreshRequired", "InvalidClientTokenId"})
_DENIED_CODES = frozenset({"AccessDenied", "AllAccessDisabled", "Forbidden", "403"})
_MISSING_BUCKET_CODES = frozenset({"NoSuchBucket", "404"})
_MESSAGE_CHARS = 2000

#: ``(credential row, unsealed payload) -> S3 client``; tests pass one bound to a moto mock.
S3ClientFactory = Callable[[Dict[str, Any], Dict[str, Any]], Any]


class _DeliveryError(Exception):
    """A delivery that cannot continue, with the code and message its run records."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def build_s3_client(credential: Dict[str, Any], secret: Dict[str, Any]) -> Any:
    """A boto3 S3 client for a stored credential: its endpoint, region, addressing and keys.

    Bounded timeouts and the standard retry mode (three attempts with backoff on throttling and
    transient errors); nothing is read from the deployment's own AWS environment.

    Args:
        credential: The credential row (``endpoint_url``, ``region``, ``force_path_style``).
        secret: The unsealed ``{accessKeyId, secretAccessKey[, sessionToken]}``.

    Returns:
        The client.
    """
    config = Config(
        connect_timeout=10,
        read_timeout=60,
        retries={"max_attempts": 3, "mode": "standard"},
        s3={"addressing_style": "path" if credential.get("force_path_style") else "auto"},
        user_agent_extra="Apiome-Export-Delivery/1.0",
    )
    session = boto3.session.Session()
    return session.client(
        "s3",
        endpoint_url=credential.get("endpoint_url") or None,
        region_name=credential.get("region") or "us-east-1",
        aws_access_key_id=secret.get("accessKeyId"),
        aws_secret_access_key=secret.get("secretAccessKey"),
        aws_session_token=secret.get("sessionToken") or None,
        config=config,
    )


def _provider_failure(exc: Exception, bucket: str, secrets: Sequence[str]) -> _DeliveryError:
    """Map a boto3 failure onto a run code and a redacted, actionable message."""
    if isinstance(exc, ClientError):
        error = exc.response.get("Error", {}) if isinstance(exc.response, dict) else {}
        code = str(error.get("Code") or "")
        detail = redact(f"{code}: {error.get('Message') or exc}", secrets)
        if code in _REJECTED_CODES:
            return _DeliveryError(ERROR_CREDENTIAL_REJECTED, "The storage provider rejected the credential "
                                  f"({detail}). Store a valid key pair, then deliver again.")
        if code in _DENIED_CODES:
            return _DeliveryError(ERROR_PERMISSION_DENIED, f"The credential may not write to bucket {bucket!r} "
                                  f"({detail}). Grant it s3:PutObject on the prefix, then deliver again.")
        if code in _MISSING_BUCKET_CODES:
            return _DeliveryError(ERROR_BUCKET_MISSING, f"Bucket {bucket!r} does not exist at this endpoint "
                                  f"({detail}). Create it, or check the region and endpoint.")
        return _DeliveryError(ERROR_UPLOAD_FAILED, f"An upload failed ({detail}).")
    return _DeliveryError(ERROR_ENDPOINT_UNREACHABLE, "The storage endpoint could not be reached "
                          f"({redact(f'{type(exc).__name__}: {exc}', secrets)}). Check the endpoint and region.")


def _load_secret(database: Any, tenant_id: str, credential_id: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """The credential row and its unsealed payload, or a delivery error."""
    try:
        credential = database.get_export_storage_credential(tenant_id, credential_id)
    except Exception as exc:  # noqa: BLE001 - a lookup fault is a failed run, not a lost one
        logger.warning("Storage credential lookup failed for %s", credential_id, exc_info=True)
        raise _DeliveryError(ERROR_INTERNAL, "The storage credential could not be read. Try again.") from exc
    if not credential:
        raise _DeliveryError(ERROR_CREDENTIAL_MISSING, "No storage credential with this id exists in the "
                             "workspace. Store one (POST /v1/export/{tenant}/storage-credentials), then deliver.")
    secret = unseal_credential_payload(credential.get("encrypted_payload"), credential.get("key_version"))
    if not secret or not secret.get("accessKeyId") or not secret.get("secretAccessKey"):
        raise _DeliveryError(ERROR_CREDENTIAL_UNAVAILABLE, f"The storage credential {credential.get('name')!r} "
                             "cannot be opened on this deployment (its encryption key is missing or changed). "
                             "Store it again, then deliver.")
    return credential, secret


def deliver_to_object_storage(
    *,
    tenant_id: str,
    actor_id: Optional[str],
    subject: DeliverySubject,
    request: NormalizedDeliveryRequest,
    files: Sequence[BundleFile],
    media_types: Optional[Dict[str, str]] = None,
    database: Any = None,
    client_factory: S3ClientFactory = build_s3_client,
) -> Dict[str, Any]:
    """Upload one export's bundle and manifest to a bucket and record the run.

    Args:
        tenant_id: The caller's tenant (scopes the credential and the run).
        actor_id: Who asked for the delivery.
        subject: What is being delivered.
        request: The validated request.
        files: The bundle's files at their bundle paths.
        media_types: A media type per bundle path.
        database: The database (default: the shared one).
        client_factory: Builds the S3 client from the credential.

    Returns:
        The run row (``delivered`` or ``failed``). When the run could not even be recorded, an
        unsaved row-shaped dict with ``id: None``.
    """
    database = database or default_db
    base = object_prefix(request.prefix, request.partitioning, subject)
    row = database.insert_export_object_storage_delivery_run(
        tenant_id=tenant_id, job_id=subject.job_id, artifact_id=subject.artifact_id,
        credential_id=request.credential_id, bucket=request.bucket, key_prefix=base,
        partitioning=request.partitioning, version_record_id=subject.version_record_id,
        version_label=subject.version_label, export_target=subject.target, fidelity=subject.fidelity,
        actor_id=actor_id,
    ) or {"id": None, "job_id": subject.job_id, "bucket": request.bucket, "key_prefix": base,
          "partitioning": list(request.partitioning), "status": RUN_STATUS_IN_PROGRESS, "objects": [],
          "fidelity": subject.fidelity}
    written: List[Dict[str, Any]] = []
    secrets: List[str] = []
    try:
        credential, secret = _load_secret(database, tenant_id, request.credential_id)
        secrets = [str(secret.get(k) or "") for k in ("secretAccessKey", "sessionToken", "accessKeyId")]
        endpoint = credential.get("endpoint_url")
        if endpoint:
            try:
                validate_url(endpoint)
            except SSRFError as exc:
                raise _DeliveryError(ERROR_ENDPOINT_REFUSED, f"The storage endpoint is refused: {exc}. Use an "
                                     "endpoint that resolves to public addresses.") from exc
        objects = plan_objects(base, files, media_types)
        if not objects:
            raise _DeliveryError(ERROR_EMPTY_BUNDLE, "The export has no files to upload.")
        manifest = manifest_document(subject, base, objects)
        addressed_key, latest_key, manifest_sha = manifest_keys(base, manifest)
        client = client_factory(credential, secret)
        try:
            for item in objects:
                client.put_object(Bucket=request.bucket, Key=item.key, Body=item.body, ContentType=item.content_type,
                                  Metadata={"sha256": item.sha256})
                written.append(item.describe())
            for key in (addressed_key, latest_key):
                client.put_object(Bucket=request.bucket, Key=key, Body=manifest,
                                  ContentType="application/json; charset=utf-8", Metadata={"sha256": manifest_sha})
        except (ClientError, BotoCoreError) as exc:
            raise _provider_failure(exc, request.bucket, secrets) from exc
        finished = _finish(database, row, tenant_id, status=RUN_STATUS_DELIVERED, objects=written,
                           manifest_key=addressed_key, manifest_sha256=manifest_sha)
    except _DeliveryError as exc:
        finished = _finish(database, row, tenant_id, status=RUN_STATUS_FAILED, objects=written,
                           error_code=exc.code, error_message=redact(exc.message, secrets)[:_MESSAGE_CHARS])
    except Exception as exc:  # noqa: BLE001 - never lose a run to an unexpected fault
        logger.error("Export object-storage delivery %s failed internally: %s", row.get("id"), type(exc).__name__)
        finished = _finish(database, row, tenant_id, status=RUN_STATUS_FAILED, objects=written,
                           error_code=ERROR_INTERNAL,
                           error_message=redact(f"Internal error ({type(exc).__name__}). Try again.", secrets))
    finally:
        secrets = []
    return finished


def _finish(database: Any, row: Dict[str, Any], tenant_id: str, **outcome: Any) -> Dict[str, Any]:
    """Close the run; fall back to the in-memory row when it was never stored or the update fails."""
    if row.get("id"):
        try:
            stored = database.finish_export_object_storage_delivery_run(str(row["id"]), tenant_id, **outcome)
            if stored:
                return stored
        except Exception:  # noqa: BLE001 - the caller still gets the outcome
            logger.warning("Could not record export object-storage delivery %s", row.get("id"), exc_info=True)
    return {**row, **outcome}
