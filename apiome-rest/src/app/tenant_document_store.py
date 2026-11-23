"""A tenant's own bucket for the document store — COA-5.15 (#7092).

COA-5.1 gave the install one document store. A tenant can keep its originals and rendered
documents in an S3-compatible bucket it owns instead: its settings live in
``apiome.tenant_document_stores`` (V408) and name a sealed storage credential
(``export_storage_credentials``, the ones export delivery uses). The platform store stays the
default — a tenant without a row, or whose row says ``platform``, uses it.

This module holds everything about *one tenant's* store:

* :class:`TenantStoreSettings` and :func:`load_settings` / :func:`save_settings` — the row.
* :func:`normalize_settings` — validation of what a tenant admin submits, including the SSRF
  guard on a custom endpoint.
* :class:`TenantS3DocumentStore` and :func:`build_tenant_store` — the store built from the row and
  the unsealed credential. It refuses any key outside its own tenant's folder.
* :class:`TenantDocumentStoreUnavailable` and :func:`record_outage` / :func:`record_recovery` —
  what an unreachable or revoked bucket turns into: an error with a redacted reason, a flag on
  the row for the ops health check, and one notification to the tenant's administrators per
  outage.

Routing between the platform store and tenant stores is :mod:`app.document_store_router`; moving
existing objects is :mod:`app.document_store_move`.

**Secrets.** The access key and secret key are only ever held inside the store object. Every
message this module produces passes through the store's redaction, and nothing here logs,
returns or audits a key.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional

from .config import settings
from .db_cursor import db_cursor
from .document_store import (
    BACKEND_TENANT_S3,
    DocumentStoreConfigError,
    DocumentStoreError,
    S3DocumentStore,
    normalize_prefix,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CODE_UNAVAILABLE",
    "MODE_PLATFORM",
    "MODE_TENANT",
    "MOVE_COMPLETED",
    "MOVE_FAILED",
    "MOVE_IDLE",
    "MOVE_RUNNING",
    "TenantDocumentStoreUnavailable",
    "TenantS3DocumentStore",
    "TenantStoreInputError",
    "TenantStoreSettings",
    "build_tenant_store",
    "list_tenant_stores",
    "load_settings",
    "normalize_settings",
    "record_outage",
    "record_recovery",
    "save_settings",
    "tenant_buckets_allowed",
]

MODE_PLATFORM = "platform"
MODE_TENANT = "tenant"

MOVE_IDLE = "idle"
MOVE_RUNNING = "running"
MOVE_COMPLETED = "completed"
MOVE_FAILED = "failed"

#: The error code of an unreachable or revoked tenant bucket (``503``).
CODE_UNAVAILABLE = "tenant-document-store-unavailable"

DEFAULT_PREFIX = "apiome"

#: S3 bucket naming: 3–63 characters of lower-case letters, digits, dots and hyphens.
_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_ADDRESSING = ("auto", "path", "virtual")
_SSE = ("", "s3", "kms")
_MAX_REASON_CHARS = 500

S3ClientFactory = Callable[[], Any]


class TenantDocumentStoreUnavailable(DocumentStoreError):
    """A tenant's own bucket cannot be used right now.

    Attributes:
        tenant_id: The tenant whose bucket failed.
        reason: Why, with credentials redacted — safe to return to the tenant.
    """

    code = CODE_UNAVAILABLE

    def __init__(self, tenant_id: str, reason: str) -> None:
        self.tenant_id = str(tenant_id)
        self.reason = str(reason or "The bucket could not be reached.")[:_MAX_REASON_CHARS]
        super().__init__(self.reason)


class TenantStoreInputError(ValueError):
    """Submitted settings were refused.

    Attributes:
        code: A stable error code.
        errors: One sentence per refused field, ``field: what is wrong``.
    """

    def __init__(self, code: str, errors: List[str]) -> None:
        super().__init__("; ".join(errors))
        self.code = code
        self.errors = list(errors)


@dataclass(frozen=True)
class TenantStoreSettings:
    """One ``apiome.tenant_document_stores`` row.

    Attributes:
        tenant_id: The tenant.
        mode: ``platform`` or ``tenant`` — where new objects go.
        credential_id: The sealed storage credential that reaches the bucket.
        bucket: The tenant's bucket.
        prefix: Folder inside the bucket.
        region: Signing region; empty takes the credential's.
        endpoint_url: Service URL; empty takes the credential's (empty there too means AWS).
        addressing_style: ``auto``, ``path`` or ``virtual``.
        sse: Empty, ``s3`` or ``kms``.
        kms_key_id: The KMS key for ``kms``.
        move_state: ``idle``, ``running``, ``completed`` or ``failed``.
        move_target: Where the current or last move copies objects to.
        move_last_key: The last object the move finished (its resume point).
        move_counts: ``{"total", "moved", "failed"}`` of the current or last move.
        move_error: Why the last move failed.
        move_started_at: When the current or last move started.
        move_finished_at: When it ended.
        cleanup_pending: A finished move left old copies that await an explicit confirm.
        unavailable_since: When the bucket first failed in the current outage.
        last_error: The redacted reason of the current outage.
        updated_at: When the settings last changed.
    """

    tenant_id: str
    mode: str = MODE_PLATFORM
    credential_id: Optional[str] = None
    bucket: Optional[str] = None
    prefix: str = DEFAULT_PREFIX
    region: str = ""
    endpoint_url: str = ""
    addressing_style: str = "auto"
    sse: str = ""
    kms_key_id: str = ""
    move_state: str = MOVE_IDLE
    move_target: Optional[str] = None
    move_last_key: Optional[str] = None
    move_counts: Optional[Dict[str, Any]] = None
    move_error: Optional[str] = None
    move_started_at: Optional[datetime] = None
    move_finished_at: Optional[datetime] = None
    cleanup_pending: bool = False
    unavailable_since: Optional[datetime] = None
    last_error: Optional[str] = None
    updated_at: Optional[datetime] = None

    @property
    def has_bucket(self) -> bool:
        """Whether the row describes a bucket (it may after a move back to the platform store)."""
        return bool(self.credential_id and self.bucket)

    @property
    def uses_tenant_bucket(self) -> bool:
        """Whether new objects go to the tenant's bucket."""
        return self.mode == MODE_TENANT and self.has_bucket


_COLUMNS = """
    tenant_id::text AS tenant_id, mode, credential_id::text AS credential_id, bucket, prefix, region,
    endpoint_url, addressing_style, sse, kms_key_id, move_state, move_target, move_last_key,
    move_counts, move_error, move_started_at, move_finished_at, cleanup_pending,
    unavailable_since, last_error, updated_at
"""


def tenant_buckets_allowed() -> bool:
    """Whether this install lets tenants use their own bucket (``APIOME_DOCUMENT_STORE_ALLOW_TENANT_BUCKETS``)."""
    return bool(getattr(settings, "document_store_allow_tenant_buckets", False))


def _is_uuid(value: Any) -> bool:
    return bool(_UUID_RE.match(str(value or "")))


def _from_row(row: Mapping[str, Any]) -> TenantStoreSettings:
    counts = row.get("move_counts")
    return TenantStoreSettings(
        tenant_id=str(row["tenant_id"]),
        mode=str(row.get("mode") or MODE_PLATFORM),
        credential_id=row.get("credential_id") or None,
        bucket=row.get("bucket") or None,
        prefix=str(row.get("prefix") or ""),
        region=str(row.get("region") or ""),
        endpoint_url=str(row.get("endpoint_url") or ""),
        addressing_style=str(row.get("addressing_style") or "auto"),
        sse=str(row.get("sse") or ""),
        kms_key_id=str(row.get("kms_key_id") or ""),
        move_state=str(row.get("move_state") or MOVE_IDLE),
        move_target=row.get("move_target") or None,
        move_last_key=row.get("move_last_key") or None,
        move_counts=dict(counts) if isinstance(counts, dict) else {},
        move_error=row.get("move_error") or None,
        move_started_at=row.get("move_started_at"),
        move_finished_at=row.get("move_finished_at"),
        cleanup_pending=bool(row.get("cleanup_pending")),
        unavailable_since=row.get("unavailable_since"),
        last_error=row.get("last_error") or None,
        updated_at=row.get("updated_at"),
    )


def load_settings(db: Any, tenant_id: str) -> Optional[TenantStoreSettings]:
    """Read a tenant's document store settings.

    Safe inside a caller's open transaction: it neither commits nor rolls it back.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: The tenant (a UUID; anything else has no row).

    Returns:
        The row, or ``None`` when the tenant never configured its own bucket.
    """
    if not _is_uuid(tenant_id):
        return None
    with db_cursor(db) as cursor:
        cursor.execute(
            f"SELECT {_COLUMNS} FROM apiome.tenant_document_stores WHERE tenant_id = %s::uuid",
            (str(tenant_id),),
        )
        row = cursor.fetchone()
    return _from_row(row) if row else None


def list_tenant_stores(db: Any, *, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Every tenant that has configured its own bucket, for the ops health check and admin screen.

    Args:
        db: Database handle.
        limit: Rows to read; ``None`` reads them all (the health check counts every bucket).

    Returns:
        ``{tenant_id, tenant_slug, tenant_name, mode, bucket, endpoint_url, move_state,
        cleanup_pending, unavailable_since, last_error}`` per live tenant, ordered by slug.
    """
    limit_sql, params = ("LIMIT %s", (int(limit),)) if limit is not None else ("", ())
    with db_cursor(db) as cursor:
        cursor.execute(
            f"""
            SELECT s.tenant_id::text AS tenant_id, t.slug AS tenant_slug, t.name AS tenant_name,
                   s.mode, s.bucket, s.endpoint_url, s.move_state, s.cleanup_pending,
                   s.unavailable_since, s.last_error
              FROM apiome.tenant_document_stores s
              JOIN apiome.tenants t ON t.id = s.tenant_id AND t.deleted_at IS NULL
             WHERE s.bucket IS NOT NULL
             ORDER BY t.slug
             {limit_sql}
            """,
            params,
        )
        return [dict(row) for row in cursor.fetchall()]


def save_settings(
    db: Any, tenant_id: str, values: Mapping[str, Any], *, actor_id: Optional[str]
) -> TenantStoreSettings:
    """Insert or update a tenant's settings row.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        values: Normalized settings (:func:`normalize_settings`): ``mode``, ``credential_id``,
            ``bucket``, ``prefix``, ``region``, ``endpoint_url``, ``addressing_style``, ``sse``,
            ``kms_key_id``.
        actor_id: Who changed them.

    Returns:
        The stored row.
    """
    params = {
        "tenant": str(tenant_id),
        "mode": values["mode"],
        "credential": values.get("credential_id"),
        "bucket": values.get("bucket"),
        "prefix": values.get("prefix") or "",
        "region": values.get("region") or "",
        "endpoint": values.get("endpoint_url") or "",
        "addressing": values.get("addressing_style") or "auto",
        "sse": values.get("sse") or "",
        "kms": values.get("kms_key_id") or "",
        "actor": actor_id if _is_uuid(actor_id) else None,
    }
    with db_cursor(db) as cursor:
        cursor.execute(
            f"""
            INSERT INTO apiome.tenant_document_stores
                (tenant_id, mode, credential_id, bucket, prefix, region, endpoint_url,
                 addressing_style, sse, kms_key_id, updated_by)
            VALUES (%(tenant)s::uuid, %(mode)s, %(credential)s::uuid, %(bucket)s, %(prefix)s, %(region)s,
                    %(endpoint)s, %(addressing)s, %(sse)s, %(kms)s, %(actor)s::uuid)
            ON CONFLICT (tenant_id) DO UPDATE SET
                mode = EXCLUDED.mode, credential_id = EXCLUDED.credential_id, bucket = EXCLUDED.bucket,
                prefix = EXCLUDED.prefix, region = EXCLUDED.region, endpoint_url = EXCLUDED.endpoint_url,
                addressing_style = EXCLUDED.addressing_style, sse = EXCLUDED.sse,
                kms_key_id = EXCLUDED.kms_key_id, updated_by = EXCLUDED.updated_by, updated_at = now()
            RETURNING {_COLUMNS}
            """,
            params,
        )
        return _from_row(cursor.fetchone())


# ── Validation ────────────────────────────────────────────────────────────────────────────────


def _check_endpoint(endpoint_url: str) -> None:
    """Run the SSRF guard over a tenant's endpoint.

    The address filter is lifted only by ``APIOME_DOCUMENT_STORE_TENANT_ALLOW_PRIVATE``; scheme
    and credentials-in-URL rules always apply.

    Raises:
        SSRFError: if the endpoint is malformed or resolves to an address the guard refuses.
    """
    from .ssrf_guard import validate_url, validate_url_policy

    if getattr(settings, "document_store_tenant_allow_private", False):
        validate_url_policy(endpoint_url)
    else:
        validate_url(endpoint_url)


def normalize_settings(payload: Mapping[str, Any], *, credential: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Validate what a tenant admin submitted and return the values to store.

    Blocking when an endpoint is given (the SSRF guard resolves its host): call it from a worker
    thread.

    Args:
        payload: ``mode``, ``credential_id``, ``bucket``, ``prefix``, ``region``, ``endpoint_url``,
            ``addressing_style``, ``sse``, ``kms_key_id``.
        credential: The storage credential row ``credential_id`` names in this tenant, or
            ``None`` when there is none.

    Returns:
        The normalized values for :func:`save_settings`.

    Raises:
        TenantStoreInputError: listing every refused field.
    """
    from .ssrf_guard import SSRFError

    errors: List[str] = []
    mode = str(payload.get("mode") or "").strip().lower()
    if mode not in (MODE_PLATFORM, MODE_TENANT):
        raise TenantStoreInputError("tenant-document-store-invalid", ["mode: must be platform or tenant."])

    bucket = str(payload.get("bucket") or "").strip() or None
    credential_id = str(payload.get("credential_id") or "").strip() or None
    if mode == MODE_TENANT or bucket or credential_id:
        if not bucket:
            errors.append("bucket: is required to use your own bucket.")
        elif not _BUCKET_RE.match(bucket) or ".." in bucket:
            errors.append(
                "bucket: must be 3 to 63 lower-case letters, digits, dots or hyphens, starting and "
                "ending with a letter or digit."
            )
        if not credential_id:
            errors.append("credentialId: is required to use your own bucket.")
        elif credential is None:
            errors.append("credentialId: no storage credential with this id exists in the workspace.")

    prefix = DEFAULT_PREFIX if payload.get("prefix") is None else str(payload.get("prefix"))
    try:
        prefix = normalize_prefix(prefix)
    except (DocumentStoreConfigError, ValueError):
        errors.append("prefix: must be path segments of letters, digits, dots, hyphens and underscores.")
        prefix = ""

    addressing = str(payload.get("addressing_style") or "auto").strip().lower()
    if addressing not in _ADDRESSING:
        errors.append("addressingStyle: must be auto, path or virtual.")
    sse = str(payload.get("sse") or "").strip().lower()
    if sse not in _SSE:
        errors.append("sse: must be empty, s3 or kms.")
    kms_key_id = str(payload.get("kms_key_id") or "").strip()
    if kms_key_id and sse != "kms":
        errors.append("kmsKeyId: is only used with sse = kms.")
    if len(kms_key_id) > 2048:
        errors.append("kmsKeyId: is too long.")
    region = str(payload.get("region") or "").strip()
    if region and not re.match(r"^[A-Za-z0-9-]{1,64}$", region):
        errors.append("region: must be letters, digits and hyphens.")

    endpoint_url = str(payload.get("endpoint_url") or "").strip()
    effective_endpoint = endpoint_url or str((credential or {}).get("endpoint_url") or "")
    if effective_endpoint:
        try:
            _check_endpoint(effective_endpoint)
        except SSRFError as exc:
            raise TenantStoreInputError(
                "tenant-document-store-endpoint-refused", [f"endpointUrl: {exc}"]
            ) from None

    if errors:
        raise TenantStoreInputError("tenant-document-store-invalid", errors)
    return {
        "mode": mode,
        "credential_id": credential_id,
        "bucket": bucket,
        "prefix": prefix,
        "region": region,
        "endpoint_url": endpoint_url,
        "addressing_style": addressing,
        "sse": sse,
        "kms_key_id": kms_key_id,
    }


# ── The store ─────────────────────────────────────────────────────────────────────────────────


class TenantS3DocumentStore(S3DocumentStore):
    """One tenant's own S3-compatible bucket.

    Differs from the platform S3 store in three ways: its objects are recorded with the backend
    ``tenant_s3``; it refuses every key outside its own tenant's folder, so a routing mistake
    cannot write one tenant's bytes into another tenant's bucket; and a provider failure is a
    :class:`TenantDocumentStoreUnavailable` worded for the tenant, not for the operator.
    """

    backend = BACKEND_TENANT_S3

    def __init__(self, *, tenant_id: str, session_token: str = "", **kwargs: Any) -> None:
        """
        Args:
            tenant_id: The only tenant this store serves.
            session_token: The credential's session token, when it has one.
            **kwargs: The :class:`~app.document_store.S3DocumentStore` settings.
        """
        self.tenant_id = str(tenant_id)
        self._session_token = session_token or ""
        super().__init__(**kwargs)

    def _safe(self, message: Any) -> str:
        from .document_store import _redact

        return _redact(message, (self._secret_access_key, self._access_key_id, self._session_token))

    def key_for(self, tenant_id: str, sha256: str) -> str:
        """Return the object key, refusing any tenant but this store's own."""
        self._require_own(tenant_id)
        return super().key_for(tenant_id, sha256)

    def tenant_prefix(self, tenant_id: str) -> str:
        self._require_own(tenant_id)
        return super().tenant_prefix(tenant_id)

    def _require_own(self, tenant_id: str) -> None:
        if str(tenant_id) != self.tenant_id:
            raise DocumentStoreError("A tenant's bucket only holds that tenant's objects.")

    def _build_client(self) -> Any:
        """Build the boto3 client with the tenant's keys — never the deployment's own chain."""
        import boto3
        from botocore.config import Config

        options: dict = {
            "connect_timeout": 10,
            "read_timeout": 60,
            "retries": {"max_attempts": 3, "mode": "standard"},
            "s3": {"addressing_style": self.addressing_style},
            "signature_version": "s3v4",
            "user_agent_extra": "Apiome-Document-Store/1.0",
        }
        if self.endpoint_url:
            options["request_checksum_calculation"] = "when_required"
            options["response_checksum_validation"] = "when_required"
        try:
            config = Config(**options)
        except TypeError:  # botocore older than the checksum options
            options.pop("request_checksum_calculation", None)
            options.pop("response_checksum_validation", None)
            config = Config(**options)
        return boto3.session.Session().client(
            "s3",
            endpoint_url=self.endpoint_url or None,
            region_name=self.region,
            aws_access_key_id=self._access_key_id,
            aws_secret_access_key=self._secret_access_key,
            aws_session_token=self._session_token or None,
            config=config,
        )

    def _failure(self, action: str, exc: Exception) -> DocumentStoreError:
        """Turn a provider failure into a redacted :class:`TenantDocumentStoreUnavailable`."""
        response = getattr(exc, "response", None)
        if isinstance(response, dict) and response.get("Error"):
            error = response["Error"]
            detail = f"{error.get('Code') or 'error'}: {error.get('Message') or ''}".rstrip(": ")
        else:
            detail = f"{type(exc).__name__}: {exc}"
        reason = self._safe(
            f"Apiome could not {action} bucket {self.bucket!r} ({detail}). Check the bucket, its "
            "policy and the storage credential."
        )
        logger.warning("tenant document store: tenant %s: %s", self.tenant_id, reason)
        return TenantDocumentStoreUnavailable(self.tenant_id, reason)


def _credential_with_secret(db: Any, tenant_id: str, credential_id: str) -> Optional[Dict[str, Any]]:
    """The tenant's credential row with its sealed payload; ``None`` when it does not exist.

    Does not commit or roll back a caller's open transaction.
    """
    if not (_is_uuid(tenant_id) and _is_uuid(credential_id)):
        return None
    with db_cursor(db) as cursor:
        cursor.execute(
            """
            SELECT id::text AS id, name, endpoint_url, region, force_path_style, access_key_hint,
                   encrypted_payload, key_version
              FROM apiome.export_storage_credentials
             WHERE tenant_id = %s::uuid AND id = %s::uuid
            """,
            (str(tenant_id), str(credential_id)),
        )
        row = cursor.fetchone()
    return dict(row) if row else None


def build_tenant_store(
    db: Any,
    store_settings: TenantStoreSettings,
    *,
    client_factory: Optional[S3ClientFactory] = None,
) -> TenantS3DocumentStore:
    """Build the store for a tenant's bucket from its settings and unsealed credential.

    Args:
        db: Database handle.
        store_settings: The tenant's row; it must describe a bucket.
        client_factory: Builds the S3 client instead of the store (tests).

    Returns:
        The store. Its client is built on first use.

    Raises:
        TenantDocumentStoreUnavailable: if the credential is gone or cannot be opened, or the
            settings or endpoint are refused.
    """
    from .mcp_credential_crypto import unseal_credential_payload

    tenant_id = store_settings.tenant_id
    if not store_settings.has_bucket:
        raise TenantDocumentStoreUnavailable(tenant_id, "No bucket is configured for this workspace.")
    credential = _credential_with_secret(db, tenant_id, str(store_settings.credential_id))
    if credential is None:
        raise TenantDocumentStoreUnavailable(
            tenant_id, "The storage credential for this workspace's bucket no longer exists."
        )
    payload = credential.get("encrypted_payload")
    secret = unseal_credential_payload(bytes(payload) if payload is not None else None, credential.get("key_version"))
    if not secret or not secret.get("accessKeyId") or not secret.get("secretAccessKey"):
        raise TenantDocumentStoreUnavailable(
            tenant_id,
            f"The storage credential {credential.get('name')!r} cannot be opened on this deployment. "
            "Store it again, then choose it in Document storage.",
        )
    addressing = store_settings.addressing_style
    if addressing == "auto" and credential.get("force_path_style"):
        addressing = "path"
    try:
        return TenantS3DocumentStore(
            tenant_id=tenant_id,
            session_token=str(secret.get("sessionToken") or ""),
            bucket=str(store_settings.bucket),
            prefix=store_settings.prefix,
            region=store_settings.region or str(credential.get("region") or ""),
            endpoint_url=store_settings.endpoint_url or str(credential.get("endpoint_url") or ""),
            addressing_style=addressing,
            sse=store_settings.sse,
            kms_key_id=store_settings.kms_key_id,
            access_key_id=str(secret["accessKeyId"]),
            secret_access_key=str(secret["secretAccessKey"]),
            presign_ttl_seconds=int(getattr(settings, "document_store_presign_ttl_seconds", 300)),
            allow_private=bool(getattr(settings, "document_store_tenant_allow_private", False)),
            client_factory=client_factory,
        )
    except DocumentStoreConfigError:
        # The config error names platform settings; the tenant gets a sentence about its own.
        raise TenantDocumentStoreUnavailable(
            tenant_id,
            "The bucket settings were refused (the endpoint is not allowed, or a setting is invalid). "
            "Review Document storage and save it again.",
        ) from None


# ── Outage bookkeeping ────────────────────────────────────────────────────────────────────────

#: Tenants this process currently believes are down, so the row is written once per outage.
_down: Dict[str, str] = {}
_down_lock = threading.Lock()

SETTINGS_LINK = "/ade/dashboard/tenants"


def _on_own_connection(work: Callable[[], None]) -> None:
    """Run a small database write on its own pooled connection.

    A bucket fails in the middle of whatever the caller was doing — often inside its open
    transaction. Each thread has its own connection, so a short-lived thread commits the outage
    row regardless of what the caller's transaction goes on to do.
    """
    failure: List[BaseException] = []

    def run() -> None:
        try:
            work()
        except Exception as exc:  # noqa: BLE001 - bookkeeping never fails the request
            failure.append(exc)

    thread = threading.Thread(target=run, name="tenant-document-store-health", daemon=True)
    thread.start()
    thread.join(timeout=10)
    if failure:
        logger.warning("tenant document store: outage bookkeeping failed: %s", type(failure[0]).__name__)


def record_outage(db: Any, tenant_id: str, reason: str) -> None:
    """Flag a tenant's bucket as unavailable and tell its administrators — once per outage.

    The first failure of an outage stamps ``unavailable_since`` and ``last_error`` and writes one
    ``document_store_unavailable`` notification per tenant owner / administrator. Later failures
    of the same outage (in any instance) write nothing.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        reason: The redacted reason.
    """
    tenant = str(tenant_id)
    text = str(reason or "")[:_MAX_REASON_CHARS]
    with _down_lock:
        if _down.get(tenant) == text:
            return
        _down[tenant] = text

    def work() -> None:
        from .notification_fanout import NotificationDraft
        from .notifications import MAX_RECIPIENTS, TYPE_DOCUMENT_STORE_UNAVAILABLE
        from .tenant_admins import tenant_admin_ids

        with db_cursor(db) as cursor:
            cursor.execute(
                """
                UPDATE apiome.tenant_document_stores
                   SET unavailable_since = COALESCE(unavailable_since, now()), last_error = %s
                 WHERE tenant_id = %s::uuid
                """,
                (text, tenant),
            )
            # Claim the notification: only the first caller of an outage gets a row back.
            cursor.execute(
                """
                UPDATE apiome.tenant_document_stores SET last_notified_at = now()
                 WHERE tenant_id = %s::uuid AND last_notified_at IS NULL
                RETURNING bucket
                """,
                (tenant,),
            )
            claimed = cursor.fetchone()
            if not claimed:
                return
            payload = {
                "summary": "Documents cannot be read from or written to your workspace's bucket. " + text,
                "link": SETTINGS_LINK,
                "bucket": claimed.get("bucket"),
                "reason": text,
            }
            recipients = tenant_admin_ids(cursor, tenant)[:MAX_RECIPIENTS]
            db._insert_notifications(
                cursor,
                tenant_id=tenant,
                notify=lambda _produced: [
                    NotificationDraft(user_id=user, type=TYPE_DOCUMENT_STORE_UNAVAILABLE, payload=dict(payload))
                    for user in recipients
                ],
            )

    _on_own_connection(work)


def record_recovery(db: Any, tenant_id: str, *, flagged: bool = False) -> None:
    """Clear a tenant's outage flag after its bucket answered.

    Costs nothing while the tenant is healthy: the row is only written when this process saw the
    outage or the settings it read still carry the flag.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        flagged: Whether the settings the caller holds have ``unavailable_since`` set.
    """
    tenant = str(tenant_id)
    with _down_lock:
        known = _down.pop(tenant, None) is not None
    if not (known or flagged):
        return

    def work() -> None:
        with db_cursor(db) as cursor:
            cursor.execute(
                """
                UPDATE apiome.tenant_document_stores
                   SET unavailable_since = NULL, last_error = NULL, last_notified_at = NULL
                 WHERE tenant_id = %s::uuid AND unavailable_since IS NOT NULL
                """,
                (tenant,),
            )

    _on_own_connection(work)


def reset_outage_memory() -> None:
    """Forget which tenants this process believes are down (tests)."""
    with _down_lock:
        _down.clear()
