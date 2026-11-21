"""Document store — one interface for immutable, content-addressed objects (COA-5.1, #7077).

Captured originals, rendered documents and large export artifacts are bytes that never change
once written. This module stores them behind one contract, :class:`DocumentStore`, with three
backends chosen by server configuration (``APIOME_DOCUMENT_STORE``):

* ``db`` (default) — Postgres ``apiome.document_store_blob``; an install without a bucket works.
* ``s3`` — any S3-compatible service (AWS, MinIO, Garage, Cloudflare R2, GCS interop).
* ``filesystem`` — a directory on this host, for development and single-node installs.

Rules every backend follows:

* **Content-addressed.** An object's identity is the SHA-256 of its bytes. Writing the same
  bytes twice for one tenant returns the same :class:`ObjectRef` and the second ``put`` writes
  nothing (``ObjectRef.created`` is ``False``).
* **Tenant isolation in the key.** The layout is
  ``<prefix>/tenants/<tenant_id>/objects/sha256/<aa>/<hex>`` — a tenant never shares a
  namespace with another, so equal bytes in two tenants are two objects.
* **Bounded memory.** ``put`` accepts bytes or a binary stream; a stream is hashed while it is
  spooled to a temporary file (in memory only up to :data:`SPOOL_MAX_MEMORY_BYTES`), and the S3
  backend switches to a multipart upload above :data:`MULTIPART_THRESHOLD_BYTES`.
* **No secrets in errors.** Every provider failure is re-raised as :class:`DocumentStoreError`
  with the configured access key and secret key redacted, and without the original exception
  chained.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import shutil
import tempfile
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Callable, Optional, Protocol, Sequence, Tuple, Union, runtime_checkable

from .config import settings

logger = logging.getLogger(__name__)

__all__ = [
    "BACKEND_DB",
    "BACKEND_FILESYSTEM",
    "BACKEND_S3",
    "BaseDocumentStore",
    "DbDocumentStore",
    "DocumentNotFound",
    "DocumentStore",
    "DocumentStoreConfigError",
    "DocumentStoreError",
    "DocumentTooLarge",
    "FilesystemDocumentStore",
    "MULTIPART_THRESHOLD_BYTES",
    "ObjectRef",
    "S3DocumentStore",
    "build_document_store",
    "get_document_store",
    "normalize_prefix",
    "object_key",
    "parse_object_uri",
    "set_document_store",
]

BACKEND_DB = "db"
BACKEND_S3 = "s3"
BACKEND_FILESYSTEM = "filesystem"
BACKENDS = (BACKEND_DB, BACKEND_S3, BACKEND_FILESYSTEM)

DEFAULT_MEDIA_TYPE = "application/octet-stream"

#: A stream is kept in memory up to this size while it is hashed; beyond it, on disk.
SPOOL_MAX_MEMORY_BYTES = 8 * 1024 * 1024
#: The S3 backend uploads in parts above this size.
MULTIPART_THRESHOLD_BYTES = 16 * 1024 * 1024
#: Size of each part of a multipart upload (also the upload's peak buffer).
MULTIPART_CHUNK_BYTES = 8 * 1024 * 1024
#: S3 refuses presigned links that live longer than seven days.
PRESIGN_MAX_TTL_SECONDS = 7 * 24 * 60 * 60

_COPY_CHUNK_BYTES = 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_URI_SCHEMES = {BACKEND_S3: "s3", BACKEND_FILESYSTEM: "fs", BACKEND_DB: "db"}
_KEY_RE = re.compile(r"(?:^|/)tenants/(?P<tenant>[^/]+)/objects/sha256/[0-9a-f]{2}/(?P<sha>[0-9a-f]{64})$")

_ADDRESSING_STYLES = {"auto": "auto", "path": "path", "virtual": "virtual", "virtual-host": "virtual"}
_SSE_MODES = {
    "": None,
    "none": None,
    "s3": "AES256",
    "sse-s3": "AES256",
    "aes256": "AES256",
    "kms": "aws:kms",
    "sse-kms": "aws:kms",
    "aws:kms": "aws:kms",
}
_REDACTION_MARKER = "[redacted]"
_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


class DocumentStoreError(Exception):
    """A document store operation failed. The message never contains a credential."""


class DocumentStoreConfigError(DocumentStoreError):
    """The ``APIOME_DOCUMENT_STORE*`` settings do not describe a usable store."""


class DocumentNotFound(DocumentStoreError):
    """No object exists for the (tenant, SHA-256) pair."""

    def __init__(self, tenant_id: str, sha256: str) -> None:
        self.tenant_id = tenant_id
        self.sha256 = sha256
        super().__init__(f"No stored object sha256:{sha256} for tenant {tenant_id!r}.")


class DocumentTooLarge(DocumentStoreError):
    """The object is larger than the backend accepts."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        super().__init__(
            f"The object is larger than the {max_bytes} bytes this document store backend accepts."
        )


@dataclass(frozen=True)
class ObjectRef:
    """Where one stored object lives, and what it is.

    Attributes:
        tenant_id: The owning tenant (the ``tenants/<tenant_id>`` key segment).
        sha256: Lower-case hex SHA-256 of the object's bytes — its identity.
        size_bytes: Length of the object in bytes.
        media_type: The media type recorded by the first write.
        backend: ``db``, ``s3`` or ``filesystem``.
        key: The object key, ``<prefix>/tenants/<tenant_id>/objects/sha256/<aa>/<hex>``.
        uri: A locator to record beside metadata: ``s3://<bucket>/<key>``, ``fs://<key>`` or
            ``db://<key>``. Never contains a credential or a host path.
        created: ``True`` when this ``put`` wrote the bytes; ``False`` when they were already
            stored (and from ``head``). Not part of equality.
    """

    tenant_id: str
    sha256: str
    size_bytes: int
    media_type: str
    backend: str
    key: str
    uri: str
    created: bool = field(default=False, compare=False)


def normalize_prefix(prefix: Optional[str]) -> str:
    """Return the storage folder with surrounding slashes removed.

    Args:
        prefix: The configured folder, e.g. ``apiome`` or ``/teams/platform/apiome/``.

    Returns:
        The folder without leading or trailing ``/`` (``''`` for none).

    Raises:
        DocumentStoreConfigError: if a segment is empty, ``.`` or ``..``, or the folder holds a
            backslash or a control character.
    """
    text = (prefix or "").strip().strip("/")
    if not text:
        return ""
    for segment in text.split("/"):
        if segment in ("", ".", "..") or "\\" in segment or any(ord(ch) < 32 for ch in segment):
            raise DocumentStoreConfigError(
                "APIOME_DOCUMENT_STORE_PREFIX must be a plain folder path such as 'apiome' or "
                "'teams/platform/apiome'."
            )
    return text


def _require_tenant(tenant_id: str) -> str:
    """Return ``tenant_id`` when it is a safe single key segment, else raise ``ValueError``."""
    text = str(tenant_id or "")
    if not _SEGMENT_RE.match(text) or text in (".", ".."):
        raise ValueError("tenant_id must be 1-128 characters of letters, digits, '.', '_' or '-'.")
    return text


def _require_sha256(sha256: str) -> str:
    """Return the lower-case hex digest (a ``sha256:`` prefix is accepted), else raise."""
    text = str(sha256 or "").lower()
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    if not _SHA256_RE.match(text):
        raise ValueError("sha256 must be 64 hexadecimal characters.")
    return text


def object_key(prefix: str, tenant_id: str, sha256: str) -> str:
    """Build the key of an object.

    Args:
        prefix: The normalized storage folder (may be ``''``).
        tenant_id: The owning tenant.
        sha256: Hex SHA-256 of the bytes.

    Returns:
        ``<prefix>/tenants/<tenant_id>/objects/sha256/<aa>/<hex>``.

    Raises:
        ValueError: if the tenant or the digest is not a safe key segment.
    """
    tenant = _require_tenant(tenant_id)
    digest = _require_sha256(sha256)
    key = f"tenants/{tenant}/objects/sha256/{digest[:2]}/{digest}"
    return f"{prefix}/{key}" if prefix else key


def parse_object_uri(uri: str) -> Tuple[str, str]:
    """Read the tenant and digest back out of an :attr:`ObjectRef.uri` (or a bare key).

    Args:
        uri: A locator such as ``s3://bucket/apiome/tenants/acme/objects/sha256/ab/ab…``.

    Returns:
        ``(tenant_id, sha256)``.

    Raises:
        ValueError: if the locator does not end in the document store key layout.
    """
    match = _KEY_RE.search(str(uri or ""))
    if match is None:
        raise ValueError("Not a document store object locator.")
    return _require_tenant(match.group("tenant")), match.group("sha")


def _redact(message: Any, secrets: Sequence[Optional[str]]) -> str:
    """Return ``message`` with every secret (longest first) replaced by ``[redacted]``."""
    text = str(message or "")
    for secret in sorted((s for s in secrets if s and len(s) >= 3), key=len, reverse=True):
        text = text.replace(secret, _REDACTION_MARKER)
    return text


def _spool(data: Union[bytes, bytearray, memoryview, BinaryIO], max_bytes: Optional[int]) -> Tuple[BinaryIO, str, int]:
    """Hash ``data`` while copying it to a rewound temporary file.

    Args:
        data: The object's bytes, or a binary stream read from its current position.
        max_bytes: Refuse an object longer than this (``None`` for no limit).

    Returns:
        ``(spooled file positioned at 0, hex SHA-256, size in bytes)``. The caller closes it.

    Raises:
        DocumentTooLarge: if the object is longer than ``max_bytes``.
        TypeError: if ``data`` is text rather than bytes.
    """
    if isinstance(data, str):
        raise TypeError("Document store objects are bytes; encode text before storing it.")
    source: BinaryIO = io.BytesIO(bytes(data)) if isinstance(data, (bytes, bytearray, memoryview)) else data
    spool: BinaryIO = tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX_MEMORY_BYTES)  # type: ignore[assignment]
    digest = hashlib.sha256()
    size = 0
    try:
        while True:
            chunk = source.read(_COPY_CHUNK_BYTES)
            if not chunk:
                break
            if isinstance(chunk, str):
                raise TypeError("Document store streams must be opened in binary mode.")
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                raise DocumentTooLarge(max_bytes)
            digest.update(chunk)
            spool.write(chunk)
        spool.seek(0)
    except BaseException:
        spool.close()
        raise
    return spool, digest.hexdigest(), size


@runtime_checkable
class DocumentStore(Protocol):
    """The contract every document store backend meets."""

    backend: str

    def put(
        self,
        tenant_id: str,
        data: Union[bytes, BinaryIO],
        media_type: str = DEFAULT_MEDIA_TYPE,
    ) -> ObjectRef:
        """Store bytes (or a binary stream) under their SHA-256; idempotent."""

    def get(self, tenant_id: str, sha256: str) -> bytes:
        """Return the whole object; raise :class:`DocumentNotFound` when absent."""

    def open_stream(self, tenant_id: str, sha256: str) -> BinaryIO:
        """Return a readable binary stream of the object; the caller closes it."""

    def head(self, tenant_id: str, sha256: str) -> Optional[ObjectRef]:
        """Return the object's reference without reading it, or ``None`` when absent."""

    def exists(self, tenant_id: str, sha256: str) -> bool:
        """Report whether the object is stored."""

    def delete(self, tenant_id: str, sha256: str) -> bool:
        """Remove the object; return ``True`` when one was removed."""

    def presign_get(self, tenant_id: str, sha256: str, ttl: Optional[int] = None) -> Optional[str]:
        """Return a time-limited download link, or ``None`` when the backend has none."""


class BaseDocumentStore(ABC):
    """Shared behavior: hashing, the idempotent ``put``, key building and defaults.

    A backend implements :meth:`head`, :meth:`open_stream`, :meth:`delete` and :meth:`_write`.
    """

    backend: str = ""

    def __init__(self, *, prefix: Optional[str] = "") -> None:
        """
        Args:
            prefix: The storage folder every key starts with (normalized here).
        """
        self.prefix = normalize_prefix(prefix)

    # -- helpers ---------------------------------------------------------------------------

    def key_for(self, tenant_id: str, sha256: str) -> str:
        """Return the key of the object for ``tenant_id`` and ``sha256``."""
        return object_key(self.prefix, tenant_id, sha256)

    def _uri(self, key: str) -> str:
        """Return the locator recorded for ``key`` (overridden by S3 to name the bucket)."""
        return f"{_URI_SCHEMES[self.backend]}://{key}"

    def _ref(
        self, tenant_id: str, sha256: str, size_bytes: int, media_type: str, *, created: bool = False
    ) -> ObjectRef:
        """Build the :class:`ObjectRef` of an object this backend holds."""
        key = self.key_for(tenant_id, sha256)
        return ObjectRef(
            tenant_id=tenant_id,
            sha256=_require_sha256(sha256),
            size_bytes=int(size_bytes),
            media_type=media_type or DEFAULT_MEDIA_TYPE,
            backend=self.backend,
            key=key,
            uri=self._uri(key),
            created=created,
        )

    def _max_object_bytes(self) -> Optional[int]:
        """Largest object ``put`` accepts (``None`` for no limit)."""
        return None

    # -- contract --------------------------------------------------------------------------

    def put(
        self,
        tenant_id: str,
        data: Union[bytes, BinaryIO],
        media_type: str = DEFAULT_MEDIA_TYPE,
    ) -> ObjectRef:
        """Store an object under the SHA-256 of its bytes.

        Args:
            tenant_id: The owning tenant.
            data: The bytes, or a binary stream read to its end (never loaded whole).
            media_type: The object's media type, recorded on the first write.

        Returns:
            The object's reference; ``created`` is ``False`` when the bytes were already
            stored, in which case nothing was written.

        Raises:
            DocumentTooLarge: if the backend caps object size and this one exceeds it.
            DocumentStoreError: if the backend fails.
        """
        tenant = _require_tenant(tenant_id)
        spool, sha256, size = _spool(data, self._max_object_bytes())
        try:
            existing = self.head(tenant, sha256)
            if existing is not None:
                return existing
            created = self._write(tenant, sha256, size, media_type or DEFAULT_MEDIA_TYPE, spool)
            return self._ref(tenant, sha256, size, media_type, created=created)
        finally:
            spool.close()

    def get(self, tenant_id: str, sha256: str) -> bytes:
        """Return the whole object.

        Raises:
            DocumentNotFound: if no such object is stored for the tenant.
        """
        with self.open_stream(tenant_id, sha256) as stream:
            return stream.read()

    def exists(self, tenant_id: str, sha256: str) -> bool:
        """Report whether the object is stored for the tenant."""
        return self.head(tenant_id, sha256) is not None

    def presign_get(self, tenant_id: str, sha256: str, ttl: Optional[int] = None) -> Optional[str]:
        """Return ``None``: this backend serves bytes through the REST API only."""
        return None

    @abstractmethod
    def head(self, tenant_id: str, sha256: str) -> Optional[ObjectRef]:
        """Return the object's reference without reading it, or ``None`` when absent."""

    @abstractmethod
    def open_stream(self, tenant_id: str, sha256: str) -> BinaryIO:
        """Return a readable binary stream of the object; the caller closes it.

        Raises:
            DocumentNotFound: if no such object is stored for the tenant.
        """

    @abstractmethod
    def delete(self, tenant_id: str, sha256: str) -> bool:
        """Remove the object; return ``True`` when one was removed."""

    @abstractmethod
    def _write(self, tenant_id: str, sha256: str, size_bytes: int, media_type: str, stream: BinaryIO) -> bool:
        """Write a new object from ``stream`` (positioned at 0).

        Returns:
            ``True`` when this call stored the bytes, ``False`` when a concurrent writer did.
        """


class DbDocumentStore(BaseDocumentStore):
    """Postgres backend: one ``apiome.document_store_blob`` row per (tenant, SHA-256)."""

    backend = BACKEND_DB

    def __init__(self, *, prefix: Optional[str] = "", max_bytes: int = 33_554_432, database: Any = None) -> None:
        """
        Args:
            prefix: The storage folder (part of the reported key only; rows are keyed by tenant
                and digest).
            max_bytes: Largest object accepted (``APIOME_DOCUMENT_STORE_DB_MAX_BYTES``).
            database: An object with the ``*_document_store_blob`` methods; the process
                database when omitted.
        """
        super().__init__(prefix=prefix)
        self.max_bytes = int(max_bytes)
        self._database = database

    @property
    def _db(self) -> Any:
        """The database handle (imported lazily so this module loads without a connection)."""
        if self._database is None:
            from .database import db

            self._database = db
        return self._database

    def _max_object_bytes(self) -> Optional[int]:
        return self.max_bytes

    def head(self, tenant_id: str, sha256: str) -> Optional[ObjectRef]:
        tenant, digest = _require_tenant(tenant_id), _require_sha256(sha256)
        row = self._db.head_document_store_blob(tenant, digest)
        if row is None:
            return None
        return self._ref(tenant, digest, row["size_bytes"], row["media_type"])

    def open_stream(self, tenant_id: str, sha256: str) -> BinaryIO:
        tenant, digest = _require_tenant(tenant_id), _require_sha256(sha256)
        content = self._db.get_document_store_blob(tenant, digest)
        if content is None:
            raise DocumentNotFound(tenant, digest)
        return io.BytesIO(bytes(content))

    def delete(self, tenant_id: str, sha256: str) -> bool:
        return bool(self._db.delete_document_store_blob(_require_tenant(tenant_id), _require_sha256(sha256)))

    def _write(self, tenant_id: str, sha256: str, size_bytes: int, media_type: str, stream: BinaryIO) -> bool:
        return bool(
            self._db.put_document_store_blob(
                tenant_id=tenant_id,
                sha256=sha256,
                size_bytes=size_bytes,
                media_type=media_type,
                content=stream.read(),
            )
        )


class FilesystemDocumentStore(BaseDocumentStore):
    """Directory backend for development and single-node installs.

    Each object is a file at ``<path>/<key>`` with a ``<key>.meta`` JSON sidecar holding its
    media type and size. Writes go to a temporary file in the target folder and are renamed
    into place, so a reader never sees a partial object.
    """

    backend = BACKEND_FILESYSTEM

    def __init__(self, *, path: str, prefix: Optional[str] = "") -> None:
        """
        Args:
            path: The storage directory (``APIOME_DOCUMENT_STORE_PATH``); created on first write.
            prefix: The storage folder inside ``path``.

        Raises:
            DocumentStoreConfigError: if ``path`` is empty.
        """
        super().__init__(prefix=prefix)
        if not str(path or "").strip():
            raise DocumentStoreConfigError(
                "APIOME_DOCUMENT_STORE=filesystem needs APIOME_DOCUMENT_STORE_PATH (a directory)."
            )
        self.root = Path(str(path).strip()).expanduser().resolve()

    def _path(self, tenant_id: str, sha256: str) -> Path:
        """Return the object's file path, refusing anything outside the storage directory."""
        target = (self.root / self.key_for(tenant_id, sha256)).resolve()
        if not target.is_relative_to(self.root):
            raise DocumentStoreError("The object key resolves outside the storage directory.")
        return target

    @staticmethod
    def _meta_path(target: Path) -> Path:
        """Return the sidecar path of an object file."""
        return target.with_name(target.name + ".meta")

    def head(self, tenant_id: str, sha256: str) -> Optional[ObjectRef]:
        target = self._path(tenant_id, sha256)
        try:
            size = target.stat().st_size
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise DocumentStoreError(f"The storage directory could not be read ({type(exc).__name__}).") from None
        media_type = DEFAULT_MEDIA_TYPE
        try:
            media_type = json.loads(self._meta_path(target).read_text("utf-8")).get("media_type") or media_type
        except (OSError, ValueError, AttributeError):
            pass  # a lost sidecar costs the media type, never the object
        return self._ref(tenant_id, sha256, size, media_type)

    def open_stream(self, tenant_id: str, sha256: str) -> BinaryIO:
        target = self._path(tenant_id, sha256)
        try:
            return open(target, "rb")
        except FileNotFoundError:
            raise DocumentNotFound(tenant_id, _require_sha256(sha256)) from None
        except OSError as exc:
            raise DocumentStoreError(f"The stored object could not be read ({type(exc).__name__}).") from None

    def delete(self, tenant_id: str, sha256: str) -> bool:
        target = self._path(tenant_id, sha256)
        try:
            self._meta_path(target).unlink(missing_ok=True)
            target.unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise DocumentStoreError(f"The stored object could not be deleted ({type(exc).__name__}).") from None
        return True

    def _write(self, tenant_id: str, sha256: str, size_bytes: int, media_type: str, stream: BinaryIO) -> bool:
        target = self._path(tenant_id, sha256)
        temp_name: Optional[str] = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._meta_path(target).write_text(
                json.dumps({"media_type": media_type, "size_bytes": size_bytes, "sha256": sha256}), "utf-8"
            )
            handle, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".upload-")
            with os.fdopen(handle, "wb") as out:
                shutil.copyfileobj(stream, out, _COPY_CHUNK_BYTES)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp_name, target)
            temp_name = None
        except OSError as exc:
            raise DocumentStoreError(
                f"The object could not be written to the storage directory ({type(exc).__name__}: "
                f"{exc.strerror or 'I/O error'}). Check APIOME_DOCUMENT_STORE_PATH and its permissions."
            ) from None
        finally:
            if temp_name is not None:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
        return True


#: ``() -> boto3 S3 client``; tests pass one bound to a moto mock.
S3ClientFactory = Callable[[], Any]


class S3DocumentStore(BaseDocumentStore):
    """S3-compatible backend (AWS S3, MinIO, Garage, Cloudflare R2, GCS interop)."""

    backend = BACKEND_S3

    def __init__(
        self,
        *,
        bucket: str,
        prefix: Optional[str] = "",
        region: str = "",
        endpoint_url: str = "",
        addressing_style: str = "auto",
        sse: str = "",
        kms_key_id: str = "",
        access_key_id: str = "",
        secret_access_key: str = "",
        presign_ttl_seconds: int = 300,
        allow_private: bool = False,
        client_factory: Optional[S3ClientFactory] = None,
    ) -> None:
        """
        Args:
            bucket: The bucket objects are written to (it must already exist).
            prefix: The storage folder inside the bucket.
            region: The signing region (``us-east-1`` when empty; ``garage`` for Garage).
            endpoint_url: The service URL for a non-AWS store; empty for AWS.
            addressing_style: ``auto``, ``path`` or ``virtual``.
            sse: Empty, ``s3`` (SSE-S3) or ``kms`` (SSE-KMS).
            kms_key_id: The KMS key for ``kms``; empty uses the bucket's default key.
            access_key_id: A static access key; empty uses boto3's credential chain.
            secret_access_key: The static secret key that goes with ``access_key_id``.
            presign_ttl_seconds: Default lifetime of a presigned link.
            allow_private: Skip the SSRF address filter for ``endpoint_url`` (a store on a
                private network); scheme and credentials-in-URL rules still apply.
            client_factory: Builds the client instead of this class (tests).

        Raises:
            DocumentStoreConfigError: if a setting is missing, unknown or refused.
        """
        super().__init__(prefix=prefix)
        self.bucket = str(bucket or "").strip()
        if not self.bucket:
            raise DocumentStoreConfigError("APIOME_DOCUMENT_STORE=s3 needs APIOME_DOCUMENT_STORE_BUCKET.")
        style = _ADDRESSING_STYLES.get(str(addressing_style or "auto").strip().lower())
        if style is None:
            raise DocumentStoreConfigError("APIOME_DOCUMENT_STORE_ADDRESSING_STYLE must be auto, path or virtual.")
        sse_key = str(sse or "").strip().lower()
        if sse_key not in _SSE_MODES:
            raise DocumentStoreConfigError("APIOME_DOCUMENT_STORE_SSE must be empty, s3 or kms.")
        if bool(access_key_id) != bool(secret_access_key):
            raise DocumentStoreConfigError(
                "Set both APIOME_DOCUMENT_STORE_ACCESS_KEY_ID and APIOME_DOCUMENT_STORE_SECRET_ACCESS_KEY, "
                "or neither (to use the environment or an IAM role)."
            )
        self.region = str(region or "").strip() or "us-east-1"
        self.endpoint_url = str(endpoint_url or "").strip()
        self.addressing_style = style
        self.sse = _SSE_MODES[sse_key]
        self.kms_key_id = str(kms_key_id or "").strip()
        self.presign_ttl_seconds = int(presign_ttl_seconds)
        self.allow_private = bool(allow_private)
        self._access_key_id = access_key_id or ""
        self._secret_access_key = secret_access_key or ""
        self._client_factory = client_factory
        self._client: Any = None
        self._lock = threading.Lock()
        self._check_endpoint()

    def __repr__(self) -> str:
        """A description without credentials."""
        return (
            f"S3DocumentStore(bucket={self.bucket!r}, prefix={self.prefix!r}, region={self.region!r}, "
            f"endpoint_url={self._safe(self.endpoint_url)!r})"
        )

    # -- client ----------------------------------------------------------------------------

    def _safe(self, message: Any) -> str:
        """Return ``message`` with the configured keys redacted."""
        return _redact(message, (self._secret_access_key, self._access_key_id))

    def _check_endpoint(self) -> None:
        """Run the SSRF guard over a custom endpoint.

        Raises:
            DocumentStoreConfigError: if the endpoint is malformed or resolves to an address
                the guard refuses.
        """
        if not self.endpoint_url:
            return
        from .ssrf_guard import SSRFError, validate_url, validate_url_policy

        try:
            if self.allow_private:
                validate_url_policy(self.endpoint_url)
            else:
                validate_url(self.endpoint_url)
        except SSRFError as exc:
            raise DocumentStoreConfigError(
                f"APIOME_DOCUMENT_STORE_ENDPOINT_URL is refused: {self._safe(exc)}. For a store on "
                "your own network, set APIOME_DOCUMENT_STORE_ALLOW_PRIVATE=true."
            ) from None

    def _build_client(self) -> Any:
        """Build the boto3 client: bounded timeouts, standard retries, the configured keys."""
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
            # Non-AWS stores (Garage, R2, older MinIO) reject the CRC trailers recent boto3 adds
            # by default; integrity is the SHA-256 the key is derived from.
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
            aws_access_key_id=self._access_key_id or None,
            aws_secret_access_key=self._secret_access_key or None,
            config=config,
        )

    @property
    def client(self) -> Any:
        """The S3 client, built on first use and shared (boto3 clients are thread-safe)."""
        if self._client is None:
            with self._lock:
                if self._client is None:
                    try:
                        self._client = (self._client_factory or self._build_client)()
                    except DocumentStoreError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - never leak a key through a build error
                        raise self._failure("connect to", exc) from None
        return self._client

    def _failure(self, action: str, exc: Exception) -> DocumentStoreError:
        """Turn a provider failure into a redacted, actionable :class:`DocumentStoreError`."""
        from botocore.exceptions import ClientError

        if isinstance(exc, ClientError):
            error = exc.response.get("Error", {}) if isinstance(exc.response, dict) else {}
            detail = f"{error.get('Code') or 'error'}: {error.get('Message') or ''}".rstrip(": ")
        else:
            detail = f"{type(exc).__name__}: {exc}"
        message = self._safe(
            f"The document store could not {action} bucket {self.bucket!r} ({detail}). Check the "
            "APIOME_DOCUMENT_STORE_* settings, the bucket and the key's permissions."
        )
        logger.warning("document store: %s", message)
        return DocumentStoreError(message)

    @staticmethod
    def _is_missing(exc: Exception) -> bool:
        """Report whether a provider error means "no such object"."""
        response = getattr(exc, "response", None)
        if not isinstance(response, dict):
            return False
        code = str(response.get("Error", {}).get("Code") or "")
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return code in _NOT_FOUND_CODES or (status == 404 and code != "NoSuchBucket")

    def _uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    # -- contract --------------------------------------------------------------------------

    def head(self, tenant_id: str, sha256: str) -> Optional[ObjectRef]:
        key = self.key_for(tenant_id, sha256)
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=key)
        except DocumentStoreError:
            raise
        except Exception as exc:  # noqa: BLE001 - every provider error is redacted below
            if self._is_missing(exc):
                return None
            raise self._failure("read from", exc) from None
        return self._ref(tenant_id, sha256, response.get("ContentLength", 0), response.get("ContentType") or "")

    def open_stream(self, tenant_id: str, sha256: str) -> BinaryIO:
        key = self.key_for(tenant_id, sha256)
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        except DocumentStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            if self._is_missing(exc):
                raise DocumentNotFound(tenant_id, _require_sha256(sha256)) from None
            raise self._failure("read from", exc) from None

    def delete(self, tenant_id: str, sha256: str) -> bool:
        if self.head(tenant_id, sha256) is None:
            return False
        try:
            self.client.delete_object(Bucket=self.bucket, Key=self.key_for(tenant_id, sha256))
        except Exception as exc:  # noqa: BLE001
            raise self._failure("delete from", exc) from None
        return True

    def presign_get(self, tenant_id: str, sha256: str, ttl: Optional[int] = None) -> Optional[str]:
        """Return a link that downloads the object straight from the store.

        Args:
            tenant_id: The owning tenant.
            sha256: The object's digest.
            ttl: Lifetime in seconds; the configured default when omitted. Clamped to 1 s – 7 days.

        Returns:
            The URL. It embeds a signature, so treat it as a secret and never log it.
        """
        seconds = max(1, min(int(ttl if ttl is not None else self.presign_ttl_seconds), PRESIGN_MAX_TTL_SECONDS))
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": self.key_for(tenant_id, sha256)},
                ExpiresIn=seconds,
            )
        except DocumentStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._failure("sign a link for", exc) from None

    def _write(self, tenant_id: str, sha256: str, size_bytes: int, media_type: str, stream: BinaryIO) -> bool:
        from boto3.s3.transfer import TransferConfig

        extra: dict = {"ContentType": media_type, "Metadata": {"sha256": sha256}}
        if self.sse:
            extra["ServerSideEncryption"] = self.sse
            if self.sse == "aws:kms" and self.kms_key_id:
                extra["SSEKMSKeyId"] = self.kms_key_id
        transfer = TransferConfig(
            multipart_threshold=MULTIPART_THRESHOLD_BYTES,
            multipart_chunksize=MULTIPART_CHUNK_BYTES,
            use_threads=False,  # one part in memory at a time
        )
        try:
            self.client.upload_fileobj(
                stream, self.bucket, self.key_for(tenant_id, sha256), ExtraArgs=extra, Config=transfer
            )
        except DocumentStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._failure("write to", exc) from None
        return True


def build_document_store(config: Any = None) -> BaseDocumentStore:
    """Build the store the settings describe.

    Args:
        config: An object with the ``document_store*`` attributes; the process settings when
            omitted.

    Returns:
        A :class:`DbDocumentStore`, :class:`S3DocumentStore` or :class:`FilesystemDocumentStore`.

    Raises:
        DocumentStoreConfigError: if the backend is unknown or a required setting is missing.
    """
    cfg = config if config is not None else settings
    backend = str(getattr(cfg, "document_store", "") or BACKEND_DB).strip().lower()
    prefix = getattr(cfg, "document_store_prefix", "")
    if backend == BACKEND_DB:
        return DbDocumentStore(prefix=prefix, max_bytes=cfg.document_store_db_max_bytes)
    if backend == BACKEND_FILESYSTEM:
        return FilesystemDocumentStore(path=cfg.document_store_path, prefix=prefix)
    if backend == BACKEND_S3:
        return S3DocumentStore(
            bucket=cfg.document_store_bucket,
            prefix=prefix,
            region=cfg.document_store_region,
            endpoint_url=cfg.document_store_endpoint_url,
            addressing_style=cfg.document_store_addressing_style,
            sse=cfg.document_store_sse,
            kms_key_id=cfg.document_store_kms_key_id,
            access_key_id=cfg.document_store_access_key_id,
            secret_access_key=cfg.document_store_secret_access_key,
            presign_ttl_seconds=cfg.document_store_presign_ttl_seconds,
            allow_private=cfg.document_store_allow_private,
        )
    raise DocumentStoreConfigError(f"APIOME_DOCUMENT_STORE must be one of {', '.join(BACKENDS)}.")


_store: Optional[DocumentStore] = None
_store_lock = threading.Lock()


def get_document_store() -> DocumentStore:
    """Return the process-wide document store, building it from the settings on first use."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = build_document_store()
    return _store


def set_document_store(store: Optional[DocumentStore]) -> None:
    """Replace (or, with ``None``, clear) the process-wide store — for tests and reconfiguration."""
    global _store
    with _store_lock:
        _store = store

