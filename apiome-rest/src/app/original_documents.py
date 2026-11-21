"""Originals in the document store — every import keeps its source there (COA-5.3, #7079).

An import used to keep the document it read in one of two database columns:
``version_import_snapshots.source_text`` (OpenAPI through the apiome-ui worker) or
``versions.format_metadata.sourceContent`` (every other format). This module writes that same
content to the document store (:mod:`app.document_store`) and records it against the revision:

* a single document is one object and one ``version_documents`` row with role ``original``;
* a set of files (an archive, an Arazzo file with its sources, a multi-file protobuf) is one
  ``original`` row holding a JSON **manifest** plus one ``original_part`` row per file.

Rules:

* **Same content as before.** Callers pass what they would have written to the column: the text
  after the tenant's secret scrub (MFI-29.6). A withheld source is never passed in; the caller
  calls :func:`clear_originals` instead.
* **Content-addressed.** Identical bytes for one tenant are one object, so re-importing the same
  document writes nothing new.
* **Gzip above a threshold.** Content of at least ``APIOME_DOCUMENT_STORE_GZIP_MIN_BYTES`` bytes
  is stored gzip-coded, with ``document_objects.encoding = 'gzip'``. The gzip stream is
  deterministic (no timestamp), so equal content still yields equal objects. An object's
  ``sha256`` is always the digest of its **stored** bytes; for an ``identity`` object that is
  the digest of the content itself. :func:`decode_original` reverses the coding.
* **Never fails an import.** Every function here catches its errors, logs the error type and
  returns ``None``; the caller then keeps writing the database column, so a source is not lost
  because a bucket was unreachable.

While ``APIOME_DOCUMENT_STORE=db`` the legacy columns are still written beside the object
(:func:`legacy_source_columns_kept`); with ``s3`` or ``filesystem`` only the pointer is kept.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import zlib
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .config import settings
from .document_store import BACKEND_DB, get_document_store

logger = logging.getLogger(__name__)

__all__ = [
    "ENCODING_GZIP",
    "ENCODING_IDENTITY",
    "MANIFEST_MEDIA_TYPE",
    "ROLE_ORIGINAL",
    "ROLE_ORIGINAL_PART",
    "StoredOriginal",
    "clear_originals",
    "decode_original",
    "encode_original",
    "fileset_manifest",
    "legacy_source_columns_kept",
    "media_type_for",
    "store_original",
    "store_original_fileset",
]

ROLE_ORIGINAL = "original"
ROLE_ORIGINAL_PART = "original_part"
ENCODING_IDENTITY = "identity"
ENCODING_GZIP = "gzip"

#: Media type of a fileset's manifest (the ``original`` object of a set of files).
MANIFEST_MEDIA_TYPE = "application/vnd.apiome.fileset-manifest+json"
#: Version of the manifest layout written by :func:`fileset_manifest`.
MANIFEST_VERSION = 1

_GZIP_LEVEL = 6
_MEDIA_TYPES_BY_SUFFIX = {
    ".json": "application/json",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".xml": "application/xml",
    ".wsdl": "application/xml",
    ".xsd": "application/xml",
}
_TEXT_MEDIA_TYPE = "text/plain"


@dataclass(frozen=True)
class StoredOriginal:
    """What :func:`store_original` or :func:`store_original_fileset` recorded for a revision.

    Attributes:
        object_id: ``document_objects.id`` of the ``original`` object (a fileset's manifest).
        sha256: SHA-256 of the object's stored bytes: its identity in the store.
        content_sha256: SHA-256 of the content before any coding. Equals ``sha256`` when
            ``encoding`` is ``identity``.
        size_bytes: Length of the content before any coding.
        media_type: Media type of the content.
        encoding: ``identity`` or ``gzip``.
        backend: The backend that holds the bytes: ``db``, ``s3`` or ``filesystem``.
        created: ``True`` when this call wrote the object; ``False`` when the tenant already
            held these bytes and the object was reused.
        parts: Number of ``original_part`` rows (``0`` for a single document).
    """

    object_id: str
    sha256: str
    content_sha256: str
    size_bytes: int
    media_type: str
    encoding: str
    backend: str
    created: bool
    parts: int = 0

    def pointer(self) -> Dict[str, Any]:
        """Return the pointer recorded on ``format_metadata.sourceDocument``.

        Returns:
            ``sha256``, ``contentSha256``, ``sizeBytes``, ``mediaType`` and ``encoding`` of the
            ``original`` object, plus ``parts`` for a fileset. Never the content.
        """
        pointer: Dict[str, Any] = {
            "sha256": self.sha256,
            "contentSha256": self.content_sha256,
            "sizeBytes": self.size_bytes,
            "mediaType": self.media_type,
            "encoding": self.encoding,
        }
        if self.parts:
            pointer["parts"] = self.parts
        return pointer


def legacy_source_columns_kept(config: Any = None) -> bool:
    """Report whether imports still write ``source_text`` / ``sourceContent`` beside the object.

    Args:
        config: An object with a ``document_store`` attribute; the process settings when omitted.

    Returns:
        ``True`` for the ``db`` backend (the default); ``False`` for ``s3`` and ``filesystem``,
        where the database keeps a pointer only.
    """
    cfg = config if config is not None else settings
    return str(getattr(cfg, "document_store", "") or BACKEND_DB).strip().lower() == BACKEND_DB


def media_type_for(filename: Optional[str], content: Optional[str] = None) -> str:
    """Pick a media type for a captured document.

    Args:
        filename: The name the import gave the document, if any. Its suffix decides first.
        content: The document text; a leading ``{`` or ``[`` reads as JSON when the name does
            not decide.

    Returns:
        ``application/json``, ``application/yaml``, ``application/xml`` or ``text/plain``.
    """
    name = (filename or "").strip().lower()
    for suffix, media_type in _MEDIA_TYPES_BY_SUFFIX.items():
        if name.endswith(suffix):
            return media_type
    if content is not None and content.lstrip()[:1] in ("{", "["):
        return "application/json"
    return _TEXT_MEDIA_TYPE


def encode_original(data: bytes, gzip_min_bytes: Optional[int] = None) -> Tuple[bytes, str]:
    """Apply the store's content coding to a document.

    Args:
        data: The content.
        gzip_min_bytes: Content of at least this many bytes is gzip-coded; ``0`` or less never
            codes. Defaults to ``APIOME_DOCUMENT_STORE_GZIP_MIN_BYTES``.

    Returns:
        ``(stored_bytes, encoding)``. The content comes back unchanged with ``identity`` when it
        is below the threshold or when gzip would not make it smaller.
    """
    threshold = settings.document_store_gzip_min_bytes if gzip_min_bytes is None else gzip_min_bytes
    if threshold <= 0 or len(data) < threshold:
        return data, ENCODING_IDENTITY
    # mtime=0 keeps the stream free of a timestamp, so equal content gives equal bytes.
    coded = gzip.compress(data, compresslevel=_GZIP_LEVEL, mtime=0)
    if len(coded) >= len(data):
        return data, ENCODING_IDENTITY
    return coded, ENCODING_GZIP


def decode_original(data: bytes, encoding: Optional[str]) -> bytes:
    """Reverse :func:`encode_original`.

    Args:
        data: The stored bytes.
        encoding: ``document_objects.encoding`` of the object.

    Returns:
        The content.

    Raises:
        ValueError: if the encoding is not ``identity`` or ``gzip``, or the gzip stream is bad.
    """
    coding = (encoding or ENCODING_IDENTITY).strip().lower()
    if coding == ENCODING_IDENTITY:
        return data
    if coding == ENCODING_GZIP:
        try:
            return gzip.decompress(data)
        except (OSError, EOFError, zlib.error) as exc:
            raise ValueError("The stored document is not a valid gzip stream.") from exc
    raise ValueError(f"Unknown document encoding {coding!r}.")


def fileset_manifest(root: Optional[str], members: List[Dict[str, Any]]) -> bytes:
    """Serialize a fileset's manifest: the content of its ``original`` object.

    Args:
        root: Path of the primary document inside the set, if known.
        members: One ``{"path", "sha256", "sizeBytes", "mediaType"}`` entry per file, where
            ``sha256`` and ``sizeBytes`` describe the file's content before any coding.

    Returns:
        Canonical JSON bytes (sorted keys, members sorted by path), so the same set of files
        always gives the same manifest object.
    """
    document = {
        "kind": "fileset",
        "version": MANIFEST_VERSION,
        "root": root,
        "members": sorted(members, key=lambda member: member["path"]),
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _put_object(
    tenant_id: str, content: bytes, media_type: str, *, database: Any, store: Any
) -> Tuple[str, Dict[str, Any]]:
    """Write one document to the store and record it in ``document_objects``.

    Args:
        tenant_id: The owning tenant.
        content: The document's content (before any coding).
        media_type: The content's media type.
        database: The database layer.
        store: The document store.

    Returns:
        ``(object_id, facts)`` where ``facts`` has ``sha256``, ``content_sha256``, ``size_bytes``,
        ``encoding``, ``backend`` and ``created``.
    """
    stored, encoding = encode_original(content)
    ref = store.put(tenant_id, stored, media_type)
    object_id = database.upsert_document_object(
        tenant_id=tenant_id,
        sha256=ref.sha256,
        size_bytes=ref.size_bytes,
        media_type=media_type,
        encoding=encoding,
        backend=ref.backend,
        storage_key=ref.key,
    )
    content_sha256 = ref.sha256 if encoding == ENCODING_IDENTITY else hashlib.sha256(content).hexdigest()
    return object_id, {
        "sha256": ref.sha256,
        "content_sha256": content_sha256,
        "size_bytes": len(content),
        "encoding": encoding,
        "backend": ref.backend,
        "created": bool(ref.created),
    }


def _resolve(database: Any, store: Any) -> Tuple[Any, Any]:
    """Return the database layer and document store to use, defaulting to the process-wide ones."""
    if database is None:
        from .database import db as database  # noqa: PLC0415 - avoid an import cycle at load
    return database, store if store is not None else get_document_store()


def store_original(
    tenant_id: str,
    version_id: str,
    text: str,
    *,
    filename: Optional[str] = None,
    media_type: Optional[str] = None,
    keep_existing: bool = False,
    database: Any = None,
    store: Any = None,
) -> Optional[StoredOriginal]:
    """Store a revision's original document and point the revision at it, never raising.

    Args:
        tenant_id: The importing tenant.
        version_id: The revision (``versions.id``) the import wrote.
        text: The document as it would be kept in the database: after the tenant's secret scrub.
        filename: The file the import named, used to pick the media type.
        media_type: The media type, when the caller knows it better than the file name does.
        keep_existing: When ``True`` a revision that already has an original keeps it (the import
            snapshot's once-per-revision rule); otherwise this document replaces it.
        database: The database layer; the process-wide one when omitted.
        store: The document store; the process-wide one when omitted.

    Returns:
        What was recorded, or ``None`` when nothing was (no tenant or revision, a revision of
        another tenant, an existing original that was kept, or a store or database failure).
    """
    if not tenant_id or not version_id or not isinstance(text, str):
        return None
    try:
        database, store = _resolve(database, store)
        content = text.encode("utf-8")
        resolved_type = media_type or media_type_for(filename, text)
        object_id, facts = _put_object(tenant_id, content, resolved_type, database=database, store=store)
        linked = database.set_version_original_documents(
            tenant_id=tenant_id,
            version_id=version_id,
            original_object_id=object_id,
            parts=[],
            keep_existing=keep_existing,
        )
        if not linked:
            return None
        return StoredOriginal(object_id=object_id, media_type=resolved_type, **facts)
    except Exception as exc:  # noqa: BLE001 - capturing the original must not fail a finished import
        logger.warning("original not stored version_id=%s: %s", version_id, type(exc).__name__)
        return None


def store_original_fileset(
    tenant_id: str,
    version_id: str,
    members: Mapping[str, bytes],
    *,
    root: Optional[str] = None,
    database: Any = None,
    store: Any = None,
) -> Optional[StoredOriginal]:
    """Store a revision's original set of files: a manifest plus one object per file, never raising.

    Args:
        tenant_id: The importing tenant.
        version_id: The revision (``versions.id``) the import wrote.
        members: The exact bytes of every file, keyed by its path inside the set.
        root: Path of the primary document inside the set.
        database: The database layer; the process-wide one when omitted.
        store: The document store; the process-wide one when omitted.

    Returns:
        What was recorded for the manifest (``parts`` counts the files), or ``None`` when nothing
        was (no tenant, revision or files, a revision of another tenant, or a failure). The
        revision's rows are written together, so a failure leaves its earlier original in place.
    """
    if not tenant_id or not version_id or not members:
        return None
    try:
        database, store = _resolve(database, store)
        parts: List[Tuple[str, str]] = []
        entries: List[Dict[str, Any]] = []
        for path in sorted(members):
            content = bytes(members[path])
            part_type = media_type_for(path)
            object_id, facts = _put_object(tenant_id, content, part_type, database=database, store=store)
            parts.append((path, object_id))
            entries.append(
                {
                    "path": path,
                    "sha256": facts["content_sha256"],
                    "sizeBytes": facts["size_bytes"],
                    "mediaType": part_type,
                }
            )
        manifest = fileset_manifest(root, entries)
        object_id, facts = _put_object(tenant_id, manifest, MANIFEST_MEDIA_TYPE, database=database, store=store)
        linked = database.set_version_original_documents(
            tenant_id=tenant_id,
            version_id=version_id,
            original_object_id=object_id,
            parts=parts,
            keep_existing=False,
        )
        if not linked:
            return None
        return StoredOriginal(object_id=object_id, media_type=MANIFEST_MEDIA_TYPE, parts=len(parts), **facts)
    except Exception as exc:  # noqa: BLE001 - capturing the original must not fail a finished import
        logger.warning("original fileset not stored version_id=%s: %s", version_id, type(exc).__name__)
        return None


def clear_originals(tenant_id: str, version_id: str, *, database: Any = None) -> bool:
    """Remove a revision's original rows, for an import whose source is withheld; never raises.

    Only the ``version_documents`` rows go. The objects stay in the store: another revision may
    use them, and removing unused objects is the lifecycle job's work (COA-5.10).

    Args:
        tenant_id: The importing tenant.
        version_id: The revision (``versions.id``).
        database: The database layer; the process-wide one when omitted.

    Returns:
        ``True`` when at least one row was removed.
    """
    if not tenant_id or not version_id:
        return False
    try:
        if database is None:
            from .database import db as database  # noqa: PLC0415 - avoid an import cycle at load
        return bool(database.clear_version_original_documents(tenant_id=tenant_id, version_id=version_id))
    except Exception as exc:  # noqa: BLE001 - withholding must not fail a finished import
        logger.warning("originals not cleared version_id=%s: %s", version_id, type(exc).__name__)
        return False
