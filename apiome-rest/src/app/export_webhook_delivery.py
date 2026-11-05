"""Export webhook delivery: the rules — MFX-38.2 (#4329).

An export job (MFX-4.x) ends with a download a pipeline would have to poll for. Webhook delivery
pushes the result instead: one ``POST`` to the pipeline's URL carrying the file manifest, the
fidelity report and the bundle. This module is the pure half — no database, no network:

* **The request** (:class:`WebhookDeliveryRequest`, :func:`normalize_request`) — the URL (its shape
  checked against the SSRF policy, :func:`app.ssrf_guard.validate_url_policy`), the shared signing
  secret, and how the bundle travels (``auto`` / ``fetch``).
* **The body** (:func:`build_payload`, :func:`stable_body`) — ``export.webhook-delivery.v1``: the
  export's coordinates, the manifest, the fidelity summary and full report, and the bundle — inline
  (UTF-8 text, or base64 for a zip) up to :attr:`app.config.Settings.export_webhook_inline_max_bytes`,
  otherwise a signed fetch link.
* **The signature** (:func:`sign_body`) — ``X-Apiome-Signature: sha256=<hex>``, an HMAC-SHA256 of the
  exact body under the shared secret: the push webhook scheme (#2588), so one verifier serves both.
* **The fetch link** (:func:`fetch_url`, :func:`verify_fetch_signature`) — an expiring URL signed with
  the server's fetch-link key, so a receiver without Apiome credentials can download a large bundle.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Union
from urllib.parse import urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

from .export_git_delivery import DeliverySubject
from .ssrf_guard import SSRFError, validate_url_policy

__all__ = [
    "ARTIFACT_MODES",
    "EVENT_TYPE",
    "PAYLOAD_SCHEMA_VERSION",
    "SECRET_MAX_CHARS",
    "SECRET_MIN_CHARS",
    "BundleArtifact",
    "ExportWebhookDeliveryRequestError",
    "NormalizedWebhookRequest",
    "WebhookDeliveryRequest",
    "build_payload",
    "display_url",
    "fetch_path",
    "fetch_signature",
    "fetch_url",
    "normalize_request",
    "sign_body",
    "stable_body",
    "verify_fetch_signature",
]

#: The body's addressable shape.
PAYLOAD_SCHEMA_VERSION = "export.webhook-delivery.v1"
#: Sent as ``X-Apiome-Event`` and as the body's ``event``.
EVENT_TYPE = "export.delivered"
#: ``auto``: inline when small enough, else a fetch link. ``fetch``: always a fetch link.
ARTIFACT_MODES = ("auto", "fetch")
#: A shared secret shorter than this is too easy to guess; longer than the cap is a mistake.
SECRET_MIN_CHARS = 16
SECRET_MAX_CHARS = 512
URL_MAX_CHARS = 2048


class ExportWebhookDeliveryRequestError(ValueError):
    """A delivery request that cannot be accepted.

    Attributes:
        errors: One message per problem, so a form can mark every bad field at once.
    """

    def __init__(self, *errors: str) -> None:
        self.errors: List[str] = [str(error) for error in errors if error]
        super().__init__("; ".join(self.errors) or "invalid export webhook delivery request")


class WebhookDeliveryRequest(BaseModel):
    """Where to deliver an export: ``POST …/jobs/{job_id}/deliveries/webhook``."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    url: str = Field(
        description="The receiver: a public `https` (or `http`) URL. Addresses inside private, "
        "loopback or link-local networks are refused, on the first attempt and on every retry.",
    )
    secret: str = Field(
        description=f"The shared secret ({SECRET_MIN_CHARS}–{SECRET_MAX_CHARS} characters) the body is "
        "signed with: `X-Apiome-Signature: sha256=<HMAC-SHA256 of the body, hex>`. Apiome signs the body "
        "once and never stores the secret.",
    )
    artifact: Literal["auto", "fetch"] = Field(
        default="auto",
        description="How the bundle travels. `auto` (default): inside the body when it is small enough, "
        "otherwise as a signed, expiring fetch link. `fetch`: always as a fetch link.",
    )


@dataclass(frozen=True)
class NormalizedWebhookRequest:
    """A validated request.

    Attributes:
        url: The receiver URL, trimmed.
        secret: The shared signing secret.
        artifact: ``auto`` or ``fetch``.
    """

    url: str
    secret: str
    artifact: str


def normalize_request(request: WebhookDeliveryRequest) -> NormalizedWebhookRequest:
    """Validate a delivery request's shape (no DNS: the route resolves the host).

    Args:
        request: The request body.

    Returns:
        The :class:`NormalizedWebhookRequest`.

    Raises:
        ExportWebhookDeliveryRequestError: For a URL that is not ``http(s)``, embeds credentials,
            has no host or is too long, and for a secret of the wrong length.
    """
    problems: List[str] = []
    url = (request.url or "").strip()
    if not url:
        problems.append("url is required")
    elif len(url) > URL_MAX_CHARS:
        problems.append(f"url is longer than {URL_MAX_CHARS} characters")
    else:
        try:
            validate_url_policy(url)
        except SSRFError as exc:
            problems.append(f"url: {exc}")
    secret = request.secret or ""
    if not SECRET_MIN_CHARS <= len(secret) <= SECRET_MAX_CHARS:
        problems.append(f"secret must be {SECRET_MIN_CHARS}–{SECRET_MAX_CHARS} characters")
    if problems:
        raise ExportWebhookDeliveryRequestError(*problems)
    return NormalizedWebhookRequest(url=url, secret=secret, artifact=request.artifact)


def display_url(url: str) -> str:
    """The receiver URL as the API and the audit log show it: without its query or fragment.

    A chat or pipeline webhook often carries its token in the query string, so it is kept out of
    every response and log line.

    Args:
        url: The stored receiver URL.

    Returns:
        ``https://host/path`` — with ``?…`` appended when a query was dropped.
    """
    parts = urlsplit(url)
    shown = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return shown + ("?…" if parts.query else "")


# -------------------------------------------------------------------------------------------
# The body
# -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BundleArtifact:
    """The bundle a delivery carries.

    Attributes:
        filename: The download filename (``openapi.yaml``, ``wsdl.zip``).
        media_type: Its media type.
        body: A single file's text, or a zip bundle's bytes.
        content_sha256: ``sha256:<hex>`` over the exact download bytes, when known.
    """

    filename: str
    media_type: str
    body: Union[str, bytes]
    content_sha256: Optional[str] = None

    @property
    def data(self) -> bytes:
        """The exact bytes the download route serves."""
        return self.body.encode("utf-8") if isinstance(self.body, str) else self.body

    @property
    def sha256_hex(self) -> str:
        """The bundle's SHA-256, hex (computed when the store did not record it)."""
        recorded = (self.content_sha256 or "").removeprefix("sha256:")
        return recorded or hashlib.sha256(self.data).hexdigest()


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_payload(
    *,
    delivery_id: str,
    created_at: datetime,
    subject: DeliverySubject,
    files: Sequence[Mapping[str, Any]],
    fidelity_report: Optional[Mapping[str, Any]],
    download_path: Optional[str],
    artifact: BundleArtifact,
    inline: bool,
    fetch: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """The delivery body (``export.webhook-delivery.v1``).

    Args:
        delivery_id: The run id — also sent as ``X-Apiome-Delivery``, for de-duplicating retries.
        created_at: When the delivery was requested (signed into the body, for replay checks).
        subject: What was exported (:func:`app.export_git_delivery_routes._subject`).
        files: The job result's file manifest (``result.files`` as JSON).
        fidelity_report: The full fidelity envelope (or ``{"targets": …}`` for a multi-target job).
        download_path: The job's authenticated download path.
        artifact: The bundle.
        inline: Carry the bundle in the body.
        fetch: ``{"url", "expiresAt"}`` when the bundle travels as a fetch link.

    Returns:
        The JSON-ready body.
    """
    bundle: Dict[str, Any] = {
        "delivery": "inline" if inline else "fetch",
        "filename": artifact.filename,
        "mediaType": artifact.media_type,
        "sizeBytes": len(artifact.data),
        "sha256": artifact.sha256_hex,
    }
    if inline and isinstance(artifact.body, str):
        bundle.update(encoding="utf-8", content=artifact.body)
    elif inline:
        bundle.update(encoding="base64", content=base64.b64encode(artifact.body).decode("ascii"))
    else:
        bundle.update(dict(fetch or {}))
    return {
        "schemaVersion": PAYLOAD_SCHEMA_VERSION,
        "event": EVENT_TYPE,
        "deliveryId": delivery_id,
        "createdAt": _iso(created_at),
        "tenant": subject.tenant_slug,
        "job": {"id": subject.job_id, "downloadPath": download_path},
        "export": {
            "artifact": subject.artifact_id,
            "artifactSlug": subject.artifact_slug,
            "artifactName": subject.artifact_name,
            "versionRecordId": subject.version_record_id,
            "versionLabel": subject.version_label,
            "target": subject.target,
            "targets": list(subject.targets),
            "snapshotHash": subject.snapshot_hash,
        },
        "manifest": {"files": [dict(item) for item in files]},
        "fidelity": {
            "summary": dict(subject.fidelity),
            "reportUrl": subject.report_url,
            "report": dict(fidelity_report) if fidelity_report else None,
        },
        "artifact": bundle,
    }


def stable_body(payload: Mapping[str, Any]) -> bytes:
    """The exact bytes sent and signed: sorted keys, no whitespace, UTF-8."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_body(secret: str, body: bytes) -> str:
    """``sha256=<hex>`` — the HMAC-SHA256 of ``body`` under the shared secret (the #2588 scheme)."""
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


# -------------------------------------------------------------------------------------------
# The fetch link
# -------------------------------------------------------------------------------------------


def fetch_path(tenant_slug: str, job_id: str, delivery_id: str) -> str:
    """The fetch route's path for one delivery's bundle."""
    return f"/v1/export/{tenant_slug}/jobs/{job_id}/deliveries/webhook/{delivery_id}/bundle"


def fetch_signature(key: bytes, tenant_slug: str, job_id: str, delivery_id: str, expires: int) -> str:
    """The fetch link's signature: HMAC-SHA256 (hex) of its coordinates and expiry.

    Args:
        key: The server's fetch-link key (:attr:`app.config.Settings.effective_export_fetch_url_signing_key`).
        tenant_slug: The tenant.
        job_id: The export job.
        delivery_id: The delivery the link was minted for.
        expires: The link's expiry, epoch seconds.

    Returns:
        64 hex characters.
    """
    message = "\n".join(("export-fetch-v1", tenant_slug, job_id, delivery_id, str(int(expires))))
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()


def fetch_url(base_url: str, key: bytes, tenant_slug: str, job_id: str, delivery_id: str,
              expires: int) -> str:
    """A signed, expiring link to one delivery's bundle.

    Args:
        base_url: The public base URL of apiome-rest.
        key: The fetch-link key.
        tenant_slug: The tenant.
        job_id: The export job.
        delivery_id: The delivery.
        expires: Expiry, epoch seconds.

    Returns:
        ``<base>/v1/export/<tenant>/jobs/<job>/deliveries/webhook/<delivery>/bundle?expires=…&signature=…``.
    """
    query = urlencode({"expires": int(expires),
                       "signature": fetch_signature(key, tenant_slug, job_id, delivery_id, expires)})
    return f"{base_url.rstrip('/')}{fetch_path(tenant_slug, job_id, delivery_id)}?{query}"


def verify_fetch_signature(key: bytes, tenant_slug: str, job_id: str, delivery_id: str, expires: int,
                           signature: str) -> bool:
    """Whether a fetch link's signature is the one :func:`fetch_signature` mints (constant time)."""
    expected = fetch_signature(key, tenant_slug, job_id, delivery_id, expires)
    return hmac.compare_digest(expected, (signature or "").strip().lower())
