"""Export object-storage delivery: the rules — MFX-38.3 (#4330).

Data platforms expect artifacts in buckets with a predictable layout. Object-storage delivery uploads
a completed export job's bundle to an S3-compatible bucket. This module is the pure half — no
database, no network:

* **The credential** (:class:`StorageCredentialCreate`, :func:`normalize_credential`) — an access key
  pair (and optional session token) plus the non-secret endpoint, region and addressing style. The
  secret half is sealed into the credential vault by the route; this module only validates it and
  says which part is secret (:attr:`NormalizedCredential.secret_payload`).
* **The request** (:class:`ObjectStorageDeliveryRequest`, :func:`normalize_request`) — which stored
  credential, which bucket, the prefix and the partitioning.
* **The layout** (:func:`object_prefix`, :func:`object_key`) — ``<prefix>/<artifact>/<version>/<target>``
  by default, every partition optional and in the order asked, each segment made key-safe. The bundle's
  files keep their bundle paths below it.
* **The manifest** (:func:`manifest_document`, :func:`manifest_keys`) — every object's key, size and
  SHA-256, with the export's provenance and fidelity summary; no clock and no job id, so the same export
  writes the same manifest. It is written twice: at ``manifests/<its own sha256>.json`` (immutable,
  content-addressed) and at ``manifest.json`` (the latest delivery to that prefix).
* **Redaction** (:func:`redact`) — every message that leaves the pipeline has the secrets replaced.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .export_git_delivery import BundleFile, DeliverySubject
from .ssrf_guard import SSRFError, validate_url_policy

__all__ = [
    "DEFAULT_PARTITIONING",
    "MANIFEST_NAME",
    "MANIFEST_SCHEMA_VERSION",
    "PARTITIONS",
    "REDACTION_MARKER",
    "ExportObjectStorageRequestError",
    "NormalizedCredential",
    "NormalizedDeliveryRequest",
    "ObjectStorageDeliveryRequest",
    "PlannedObject",
    "StorageCredentialCreate",
    "manifest_document",
    "manifest_keys",
    "normalize_credential",
    "normalize_request",
    "object_key",
    "object_prefix",
    "partition_segment",
    "plan_objects",
    "redact",
]

#: The partitions a layout may use, and the default order.
PARTITIONS = ("artifact", "version", "target")
DEFAULT_PARTITIONING: Tuple[str, ...] = PARTITIONS
#: The manifest's addressable shape.
MANIFEST_SCHEMA_VERSION = "export.object-storage-delivery.v1"
#: The manifest that always names the latest delivery to a prefix.
MANIFEST_NAME = "manifest.json"
#: What a secret is replaced with in any message.
REDACTION_MARKER = "[redacted]"
PREFIX_MAX_CHARS = 512
NAME_MAX_CHARS = 120

#: S3 bucket naming: 3–63 lowercase letters, digits, dots and hyphens, starting and ending alphanumeric.
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_IP_LIKE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_REGION = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_KEY_ID = re.compile(r"^[A-Za-z0-9+/=._-]{3,128}$")
_UNSAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")


class ExportObjectStorageRequestError(ValueError):
    """A credential or delivery request that cannot be accepted.

    Attributes:
        errors: One message per problem, so a form can mark every bad field at once.
    """

    def __init__(self, *errors: str) -> None:
        self.errors: List[str] = [str(error) for error in errors if error]
        super().__init__("; ".join(self.errors) or "invalid export object-storage request")


# -------------------------------------------------------------------------------------------
# The credential
# -------------------------------------------------------------------------------------------


class StorageCredentialCreate(BaseModel):
    """A bucket credential for the vault: ``POST /v1/export/{tenant}/storage-credentials``."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str = Field(description="A name unique in the workspace (`data-lake-prod`).")
    access_key_id: SecretStr = Field(alias="accessKeyId", description="The access key id. Sealed; only its "
                                     "last four characters are ever shown.")
    secret_access_key: SecretStr = Field(alias="secretAccessKey", description="The secret access key. Sealed; "
                                         "never shown.")
    session_token: Optional[SecretStr] = Field(default=None, alias="sessionToken",
                                               description="A session token, for temporary credentials.")
    endpoint_url: Optional[str] = Field(
        default=None, alias="endpointUrl",
        description="An S3-compatible endpoint (`https://minio.example.com`, "
        "`https://<account>.r2.cloudflarestorage.com`). Empty means AWS S3. It must resolve to public "
        "addresses only.",
    )
    region: str = Field(default="us-east-1", description="The bucket's region (`auto` for R2).")
    force_path_style: bool = Field(
        default=False, alias="forcePathStyle",
        description="Address buckets as `<endpoint>/<bucket>/…` instead of `<bucket>.<endpoint>/…` — "
        "most self-hosted stores (MinIO, Ceph) need it.",
    )


@dataclass(frozen=True)
class NormalizedCredential:
    """A validated credential.

    Attributes:
        name: The trimmed name.
        endpoint_url: The endpoint without a trailing ``/``, or ``None`` for AWS S3.
        region: The region.
        force_path_style: Path-style addressing.
        access_key_hint: The access key id's last four characters.
        secret_payload: What is sealed into the vault: ``{accessKeyId, secretAccessKey[, sessionToken]}``.
    """

    name: str
    endpoint_url: Optional[str]
    region: str
    force_path_style: bool
    access_key_hint: str
    secret_payload: Dict[str, str]


def normalize_endpoint(endpoint_url: Optional[str]) -> Optional[str]:
    """Validate an endpoint's shape against the SSRF policy (no DNS; the route resolves it).

    Args:
        endpoint_url: The endpoint, or empty for AWS S3.

    Returns:
        The endpoint without a trailing ``/``, or ``None``.

    Raises:
        ExportObjectStorageRequestError: For a scheme other than http(s), embedded credentials, no
            host, or a query or fragment.
    """
    url = (endpoint_url or "").strip()
    if not url:
        return None
    try:
        validate_url_policy(url)
    except SSRFError as exc:
        raise ExportObjectStorageRequestError(f"endpointUrl: {exc}") from exc
    parts = urlsplit(url)
    if parts.query or parts.fragment:
        raise ExportObjectStorageRequestError("endpointUrl cannot carry a query or fragment")
    return url.rstrip("/")


def normalize_credential(request: StorageCredentialCreate) -> NormalizedCredential:
    """Validate a credential before it is sealed.

    Args:
        request: The request body.

    Returns:
        The :class:`NormalizedCredential`.

    Raises:
        ExportObjectStorageRequestError: Naming every bad field (never echoing a secret).
    """
    problems: List[str] = []
    name = (request.name or "").strip()
    if not 1 <= len(name) <= NAME_MAX_CHARS:
        problems.append(f"name must be 1–{NAME_MAX_CHARS} characters")
    key_id = request.access_key_id.get_secret_value().strip()
    if not _KEY_ID.match(key_id):
        problems.append("accessKeyId must be 3–128 characters with no spaces")
    secret = request.secret_access_key.get_secret_value()
    if not 1 <= len(secret) <= 256 or secret != secret.strip():
        problems.append("secretAccessKey must be 1–256 characters with no surrounding spaces")
    token = request.session_token.get_secret_value() if request.session_token else ""
    if len(token) > 4096:
        problems.append("sessionToken is longer than 4096 characters")
    region = (request.region or "").strip()
    if not _REGION.match(region):
        problems.append("region must be lowercase letters, digits and hyphens (`eu-west-1`, `auto`)")
    endpoint: Optional[str] = None
    try:
        endpoint = normalize_endpoint(request.endpoint_url)
    except ExportObjectStorageRequestError as exc:
        problems.extend(exc.errors)
    if problems:
        raise ExportObjectStorageRequestError(*problems)
    payload = {"accessKeyId": key_id, "secretAccessKey": secret}
    if token:
        payload["sessionToken"] = token
    return NormalizedCredential(name=name, endpoint_url=endpoint, region=region,
                                force_path_style=request.force_path_style, access_key_hint=key_id[-4:],
                                secret_payload=payload)


# -------------------------------------------------------------------------------------------
# The request
# -------------------------------------------------------------------------------------------


class ObjectStorageDeliveryRequest(BaseModel):
    """Where to deliver an export: ``POST …/jobs/{job_id}/deliveries/object-storage``."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    credential_id: str = Field(alias="credentialId", description="A storage credential of this workspace "
                               "(`GET /v1/export/{tenant}/storage-credentials`).")
    bucket: str = Field(description="The bucket (S3 naming rules: 3–63 lowercase letters, digits, `.` and `-`).")
    prefix: str = Field(default="", description="The key prefix every object is written under (`exports/apis`). "
                        "Empty means the bucket root.")
    partitioning: List[Literal["artifact", "version", "target"]] = Field(
        default_factory=lambda: list(DEFAULT_PARTITIONING),
        description="The partitions below the prefix, in order. Default `[artifact, version, target]` → "
        "`<prefix>/orders/1.4.0/openapi-3.1/…`; `[]` writes straight under the prefix.",
    )


@dataclass(frozen=True)
class NormalizedDeliveryRequest:
    """A validated delivery request.

    Attributes:
        credential_id: The stored credential.
        bucket: The bucket.
        prefix: The normalised prefix (``''`` for the bucket root).
        partitioning: The partitions, in order.
    """

    credential_id: str
    bucket: str
    prefix: str
    partitioning: Tuple[str, ...]


def normalize_prefix(prefix: Optional[str]) -> str:
    """A key prefix with no empty, ``.`` or ``..`` segment and no surrounding ``/``.

    Raises:
        ExportObjectStorageRequestError: For ``..``, a backslash, a control character or an over-long prefix.
    """
    raw = (prefix or "").strip()
    if len(raw) > PREFIX_MAX_CHARS:
        raise ExportObjectStorageRequestError(f"prefix is longer than {PREFIX_MAX_CHARS} characters")
    if "\\" in raw or any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise ExportObjectStorageRequestError("prefix cannot contain a backslash or a control character")
    segments = [segment for segment in raw.split("/") if segment]
    if any(segment in (".", "..") for segment in segments):
        raise ExportObjectStorageRequestError("prefix cannot contain a '.' or '..' segment")
    return "/".join(segments)


def normalize_request(request: ObjectStorageDeliveryRequest) -> NormalizedDeliveryRequest:
    """Validate and normalise a delivery request.

    Raises:
        ExportObjectStorageRequestError: Naming every bad field.
    """
    problems: List[str] = []
    credential_id = (request.credential_id or "").strip()
    if not credential_id:
        problems.append("credentialId is required")
    bucket = (request.bucket or "").strip()
    if not _BUCKET.match(bucket) or ".." in bucket or _IP_LIKE.match(bucket):
        problems.append("bucket must be 3–63 lowercase letters, digits, '.' and '-', start and end with a "
                        "letter or digit, and not look like an IP address")
    prefix = ""
    try:
        prefix = normalize_prefix(request.prefix)
    except ExportObjectStorageRequestError as exc:
        problems.extend(exc.errors)
    if len(set(request.partitioning)) != len(request.partitioning):
        problems.append("partitioning cannot name a partition twice")
    if problems:
        raise ExportObjectStorageRequestError(*problems)
    return NormalizedDeliveryRequest(credential_id=credential_id, bucket=bucket, prefix=prefix,
                                     partitioning=tuple(request.partitioning))


# -------------------------------------------------------------------------------------------
# The layout
# -------------------------------------------------------------------------------------------


def partition_segment(value: Optional[str], fallback: str) -> str:
    """One key-safe path segment: letters, digits, ``.``, ``_`` and ``-``; anything else becomes ``-``.

    Args:
        value: The raw value (a slug, a version label, a target key).
        fallback: Used when nothing safe is left.

    Returns:
        A non-empty segment that is never ``.`` or ``..``, at most 100 characters.
    """
    segment = _UNSAFE_SEGMENT.sub("-", (value or "").strip()).strip("-.")[:100].strip("-.")
    return segment or fallback


def object_prefix(prefix: str, partitioning: Sequence[str], subject: DeliverySubject) -> str:
    """The prefix one delivery writes under: the configured prefix, then each partition.

    Args:
        prefix: The normalised configured prefix.
        partitioning: The partitions, in order.
        subject: What is being delivered.

    Returns:
        ``exports/orders/1.4.0/openapi-3.1`` — ``''`` when there is no prefix and no partition.
    """
    values = {
        "artifact": partition_segment(subject.artifact_slug or subject.artifact_id, "artifact"),
        "version": partition_segment(subject.version_label or subject.version_record_id, "unversioned"),
        "target": partition_segment(subject.target, "export"),
    }
    return "/".join([part for part in (prefix,) if part] + [values[name] for name in partitioning])


def object_key(base: str, path: str) -> str:
    """``<base>/<path>``, or ``path`` at the bucket root."""
    return f"{base}/{path}" if base else path


@dataclass(frozen=True)
class PlannedObject:
    """One object a delivery writes.

    Attributes:
        key: The object key.
        body: Its bytes.
        content_type: Its ``Content-Type``.
        sha256: Its SHA-256, hex.
    """

    key: str
    body: bytes
    content_type: str
    sha256: str

    def describe(self) -> Dict[str, Any]:
        """``{key, sizeBytes, sha256, contentType}`` — the run's and the manifest's record of it."""
        return {"key": self.key, "sizeBytes": len(self.body), "sha256": self.sha256,
                "contentType": self.content_type}


def _content_type(path: str, media_types: Mapping[str, str]) -> str:
    if media_types.get(path):
        return media_types[path]
    lowered = path.lower()
    for suffix, media in ((".json", "application/json"), (".yaml", "application/yaml"),
                          (".yml", "application/yaml"), (".xml", "application/xml"), (".xsd", "application/xml"),
                          (".wsdl", "application/xml"), (".graphql", "application/graphql"),
                          (".proto", "text/plain"), (".avsc", "application/json")):
        if lowered.endswith(suffix):
            return media + "; charset=utf-8"
    return "text/plain; charset=utf-8"


def plan_objects(base: str, files: Iterable[BundleFile], media_types: Optional[Mapping[str, str]] = None
                 ) -> List[PlannedObject]:
    """The bundle's files as objects under ``base``, in path order.

    Args:
        base: The delivery's prefix (:func:`object_prefix`).
        files: The bundle's files at their bundle paths (already made safe).
        media_types: A media type per bundle path, when the job named one.

    Returns:
        One :class:`PlannedObject` per file.
    """
    out = []
    for item in sorted(files, key=lambda f: f.path):
        body = item.text.encode("utf-8")
        out.append(PlannedObject(object_key(base, item.path), body, _content_type(item.path, media_types or {}),
                                 hashlib.sha256(body).hexdigest()))
    return out


def manifest_document(subject: DeliverySubject, base: str, objects: Sequence[PlannedObject]) -> bytes:
    """The delivery manifest: provenance, fidelity, and every object's key, size and SHA-256.

    No clock and no job id: the same export to the same prefix writes byte-identical manifests, so its
    content address is stable.

    Args:
        subject: What was delivered.
        base: The prefix the objects are under.
        objects: The bundle's objects.

    Returns:
        Pretty-printed UTF-8 JSON, ending with a newline.
    """
    document = {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "notice": "Generated by Apiome (MFX-38.3 export object-storage delivery). Every object of this "
                  "delivery is listed with its SHA-256; verify each one against it.",
        "prefix": base,
        "artifact": subject.artifact_slug or subject.artifact_id,
        "artifactName": subject.artifact_name,
        "version": subject.version_label,
        "versionRecordId": subject.version_record_id,
        "target": subject.target,
        "targets": list(subject.targets),
        "snapshotHash": subject.snapshot_hash,
        "fidelity": dict(subject.fidelity),
        "objects": [item.describe() for item in objects],
    }
    return (json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False) + "\n").encode("utf-8")


def manifest_keys(base: str, manifest: bytes) -> Tuple[str, str, str]:
    """Where the manifest goes.

    Returns:
        ``(content-addressed key, latest key, sha256 hex)`` — ``<base>/manifests/<sha256>.json`` and
        ``<base>/manifest.json``.
    """
    digest = hashlib.sha256(manifest).hexdigest()
    return object_key(base, f"manifests/{digest}.json"), object_key(base, MANIFEST_NAME), digest


# -------------------------------------------------------------------------------------------
# Redaction
# -------------------------------------------------------------------------------------------


def redact(message: Optional[str], secrets: Iterable[Optional[str]]) -> str:
    """``message`` with every secret (longest first) replaced by :data:`REDACTION_MARKER`.

    Args:
        message: Any text that could quote a secret (a provider error, an exception).
        secrets: The values to hide — the access key id, the secret key, the session token.

    Returns:
        The redacted text (``''`` for ``None``).
    """
    text = str(message or "")
    for secret in sorted((s for s in secrets if s and len(s) >= 3), key=len, reverse=True):
        text = text.replace(secret, REDACTION_MARKER)
    return text
