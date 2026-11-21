"""Serve the file an import stored for a revision: its original (COA-5.7, #7083).

COA-5.3 stores the document every import read as the revision's ``original`` object (a set of
files as a manifest plus one ``original_part`` per file). This module finds that object and hands
it back as a download:

* :func:`resolve_original` picks the object (the original, or one part of a set), its file name,
  media type and coding, or raises :class:`OriginalNotStoredError` / :class:`OriginalWithheldError`;
* :func:`materialize` opens the **content** for reading: the stored bytes, gzip-decoded when the
  object was stored gzip-coded (into a spooled temporary file, so a large document never sits
  whole in memory), together with its SHA-256 and length;
* :func:`parse_range` reads one ``Range: bytes=…`` request against that length;
* :func:`iter_stream` yields a byte range of an open stream in bounded chunks.

The digest of what is served is the digest of the content as it was imported, after the tenant's
secret scrub: ``document_objects.sha256`` for an object stored as it is, the recorded
``contentSha256`` for a gzip-coded one. It is the response's ``ETag``.

Revisions imported before the document store keep their source in the legacy columns; a single
document there is served too (read through :func:`app.revision_source.revision_source`), so a
download works before the migration of COA-5.8. A legacy set of files is not: it has no parts to
address until it is migrated.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import logging
import re
import tempfile
from dataclasses import dataclass
from typing import Any, BinaryIO, Dict, Iterator, List, Mapping, Optional, Tuple
from urllib.parse import urlparse

from .original_documents import (
    ENCODING_GZIP,
    ENCODING_IDENTITY,
    MANIFEST_MEDIA_TYPE,
    ROLE_ORIGINAL,
    ROLE_ORIGINAL_PART,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CHUNK_BYTES",
    "MaterializedOriginal",
    "OriginalNotStoredError",
    "OriginalWithheldError",
    "RangeNotSatisfiableError",
    "ResolvedOriginal",
    "describe",
    "etag_matches",
    "iter_stream",
    "materialize",
    "parse_range",
    "resolve_original",
]

#: Bytes read and sent per chunk of a streamed download.
CHUNK_BYTES = 64 * 1024
#: Content up to this size stays in memory while it is gzip-decoded; larger spills to disk.
SPOOL_MEMORY_BYTES = 1024 * 1024

#: File extension offered for a media type when the import recorded no file name.
_EXTENSIONS = {
    "application/json": "json",
    "application/yaml": "yaml",
    "application/xml": "xml",
    MANIFEST_MEDIA_TYPE: "manifest.json",
}
_RANGE = re.compile(r"^\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*$", re.IGNORECASE)


class OriginalNotStoredError(LookupError):
    """The revision has no stored original (or no part at the requested path)."""


class OriginalWithheldError(Exception):
    """The import withheld the source under the tenant's intake policy.

    Attributes:
        reason: The reason the import recorded (``secrets-detected``, …).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RangeNotSatisfiableError(ValueError):
    """The ``Range`` header asks for bytes past the end of the content."""


@dataclass(frozen=True)
class ResolvedOriginal:
    """The object a download serves, before it is read.

    Attributes:
        tenant_id: The owning tenant (the object's store namespace).
        sha256: SHA-256 of the **stored** bytes (the object's identity in the store); ``None``
            for a legacy source held in a database column.
        encoding: ``identity`` or ``gzip``: how the stored bytes are coded.
        media_type: The content's media type.
        filename: The file name to offer.
        stored_size: Length of the stored bytes, when the object row recorded it.
        is_manifest: ``True`` for the manifest of a set of files.
        legacy_content: The content itself, for a legacy source (no object to read).
    """

    tenant_id: str
    sha256: Optional[str]
    encoding: str
    media_type: str
    filename: str
    stored_size: Optional[int] = None
    is_manifest: bool = False
    legacy_content: Optional[bytes] = None

    @property
    def served_as_stored(self) -> bool:
        """Whether the stored bytes are the content itself (so a presigned link can serve them)."""
        return self.legacy_content is None and self.encoding == ENCODING_IDENTITY


@dataclass
class MaterializedOriginal:
    """The content of an original, open for reading.

    Attributes:
        stream: A seekable binary stream positioned anywhere; :func:`iter_stream` seeks it.
        sha256: Hex SHA-256 of the content.
        size: Length of the content in bytes.
    """

    stream: BinaryIO
    sha256: str
    size: int

    def close(self) -> None:
        """Close the stream (and remove its temporary file, if it spilled to disk)."""
        try:
            self.stream.close()
        except Exception:  # noqa: BLE001 - closing must never fail a finished response
            pass


def _basename(value: Optional[str]) -> Optional[str]:
    """Return the last path segment of a file name or URL when it looks like a file, else ``None``."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if "://" in text:
        text = urlparse(text).path or ""
    name = text.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return name if "." in name.strip(".") else None


def _fallback_name(facts: Mapping[str, Any], media_type: str) -> str:
    """``<project-slug>-<version-label>.<ext>`` for a revision whose import named no file."""
    stem = "-".join(
        str(part) for part in (facts.get("project_slug"), facts.get("version_label")) if part
    ) or "original"
    return f"{stem}.{_EXTENSIONS.get(media_type, 'txt')}"


def _filename(facts: Mapping[str, Any], media_type: str) -> str:
    """The name of the imported file: the import's label, the snapshot's file name, or a fallback."""
    return (
        _basename(facts.get("source_label"))
        or _basename(facts.get("source_file"))
        or _fallback_name(facts, media_type)
    )


def _manifest_name(facts: Mapping[str, Any]) -> str:
    """The name offered for a set's manifest: the archive's name with ``.manifest.json``."""
    archive = _basename(facts.get("source_label"))
    if archive:
        return f"{archive}.manifest.json"
    return _fallback_name(facts, MANIFEST_MEDIA_TYPE)


def _from_rows(
    tenant_id: str, rows: List[Mapping[str, Any]], facts: Mapping[str, Any], part_path: Optional[str]
) -> ResolvedOriginal:
    """Pick the object to serve from a revision's ``version_documents`` rows.

    Raises:
        OriginalNotStoredError: When the requested part is not one of the set's files, or a part is
            asked of a single document.
    """
    original = next((row for row in rows if row.get("role") == ROLE_ORIGINAL), None)
    if original is None:
        raise OriginalNotStoredError("The revision has no stored original.")
    is_set = original.get("media_type") == MANIFEST_MEDIA_TYPE
    if part_path is None:
        row = original
        name = _manifest_name(facts) if is_set else _filename(facts, str(original.get("media_type") or ""))
    else:
        if not is_set:
            raise OriginalNotStoredError("The original is a single document; it has no parts.")
        wanted = part_path.strip("/")
        row = next(
            (r for r in rows if r.get("role") == ROLE_ORIGINAL_PART and r.get("part_path") == wanted),
            None,
        )
        if row is None:
            raise OriginalNotStoredError(f"The original has no file at {wanted!r}.")
        name = _basename(wanted) or wanted.rsplit("/", 1)[-1] or "part"
    size = row.get("size_bytes")
    return ResolvedOriginal(
        tenant_id=tenant_id,
        sha256=str(row["sha256"]),
        encoding=str(row.get("encoding") or ENCODING_IDENTITY),
        media_type=str(row.get("media_type") or "application/octet-stream"),
        filename=name,
        stored_size=int(size) if size is not None else None,
        is_manifest=part_path is None and is_set,
    )


def resolve_original(
    db: Any, tenant_id: str, version_id: str, part_path: Optional[str] = None
) -> ResolvedOriginal:
    """Find what ``GET …/original`` (or ``…/original/{part_path}``) serves for a revision.

    Args:
        db: The database layer: ``get_version_original_facts`` and
            ``list_version_original_documents``.
        tenant_id: The tenant that owns the revision.
        version_id: The revision (``versions.id``), already checked to belong to the tenant.
        part_path: A file of a stored set, by its path inside the set; ``None`` for the original
            itself (a set's manifest).

    Returns:
        The object to serve.

    Raises:
        OriginalWithheldError: When the import withheld the source (``sourceWithheld``).
        OriginalNotStoredError: When nothing is stored (or nothing at ``part_path``).
    """
    facts = db.get_version_original_facts(tenant_id=tenant_id, version_id=version_id) or {}
    withheld = facts.get("source_withheld")
    if isinstance(withheld, str) and withheld.strip():
        raise OriginalWithheldError(withheld.strip())
    rows = db.list_version_original_documents(tenant_id=tenant_id, version_id=version_id) or []
    if rows:
        return _from_rows(tenant_id, rows, facts, part_path)
    if part_path is not None:
        raise OriginalNotStoredError("The revision has no stored set of files.")
    return _legacy(db, tenant_id, version_id, facts)


def _legacy(db: Any, tenant_id: str, version_id: str, facts: Mapping[str, Any]) -> ResolvedOriginal:
    """Serve a single document a pre-store import kept in a database column.

    Raises:
        OriginalNotStoredError: When there is none, or it is a set of files (not addressable until
            COA-5.8 migrates it).
    """
    from .revision_source import revision_source  # noqa: PLC0415 - heavy module, load on demand

    source = revision_source(db, None, tenant_id, version_id, decomposed=True)
    if source is None or source.is_fileset:
        raise OriginalNotStoredError("The revision has no stored original.")
    media_type = source.media_type or "text/plain"
    return ResolvedOriginal(
        tenant_id=tenant_id,
        sha256=None,
        encoding=ENCODING_IDENTITY,
        media_type=media_type,
        filename=_filename(facts, media_type),
        legacy_content=source.text.encode("utf-8"),
    )


def _hash_copy(source: BinaryIO, target: BinaryIO) -> Tuple[str, int]:
    """Copy ``source`` into ``target`` in chunks, returning the SHA-256 and length copied."""
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = source.read(CHUNK_BYTES)
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
        target.write(chunk)
    return digest.hexdigest(), size


def materialize(store: Any, resolved: ResolvedOriginal) -> MaterializedOriginal:
    """Open the content of an original for reading.

    An object stored as it is is opened straight from the store when the backend's stream can
    seek, so nothing is copied; otherwise (and for a gzip-coded object, which is decoded) it is
    copied into a spooled temporary file that stays in memory up to 1 MiB.

    Args:
        store: The document store.
        resolved: What :func:`resolve_original` returned.

    Returns:
        The open content with its digest and length. The caller closes it.

    Raises:
        DocumentNotFound: When the object row exists but the store no longer has its bytes.
        DocumentStoreError: When the backend fails.
        ValueError: When a gzip-coded object is not a valid gzip stream.
    """
    if resolved.legacy_content is not None:
        data = resolved.legacy_content
        return MaterializedOriginal(io.BytesIO(data), hashlib.sha256(data).hexdigest(), len(data))
    assert resolved.sha256 is not None
    stream = store.open_stream(resolved.tenant_id, resolved.sha256)
    if resolved.encoding == ENCODING_IDENTITY and resolved.stored_size is not None and _seekable(stream):
        return MaterializedOriginal(stream, resolved.sha256, resolved.stored_size)
    spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES)  # noqa: SIM115 - closed by caller
    try:
        with stream:
            if resolved.encoding == ENCODING_GZIP:
                try:
                    with gzip.GzipFile(fileobj=stream, mode="rb") as decoded:
                        sha256, size = _hash_copy(decoded, spool)
                except (OSError, EOFError) as exc:
                    raise ValueError("The stored document is not a valid gzip stream.") from exc
            elif resolved.encoding == ENCODING_IDENTITY:
                sha256, size = _hash_copy(stream, spool)
            else:
                raise ValueError(f"Unknown document encoding {resolved.encoding!r}.")
    except BaseException:
        spool.close()
        raise
    spool.seek(0)
    return MaterializedOriginal(spool, sha256, size)  # type: ignore[arg-type]


def _seekable(stream: Any) -> bool:
    """Whether ``stream`` can seek (a file or an in-memory buffer; not an S3 body)."""
    try:
        return bool(stream.seekable())
    except Exception:  # noqa: BLE001 - a stream without seekable() cannot seek
        return False


def etag_matches(header: Optional[str], sha256: str) -> bool:
    """Whether an ``If-None-Match`` / ``If-Range`` value names this content's ETag.

    Args:
        header: The header's value (a list of entity tags, ``*``, or ``None``).
        sha256: The content's digest (the ETag is ``"<sha256>"``).

    Returns:
        ``True`` for ``*`` or a matching tag (weak tags compare by their opaque part).
    """
    if not header:
        return False
    for candidate in header.split(","):
        tag = candidate.strip()
        if tag == "*":
            return True
        if tag.startswith("W/"):
            tag = tag[2:]
        if tag.strip('"') == sha256:
            return True
    return False


def parse_range(header: Optional[str], size: int) -> Optional[Tuple[int, int]]:
    """Read a single ``Range: bytes=…`` request against content of ``size`` bytes.

    Args:
        header: The ``Range`` header, or ``None``.
        size: The content's length.

    Returns:
        ``(start, end)`` with ``end`` inclusive, or ``None`` to serve the whole content: no
        header, a malformed one, or several ranges (a server may ignore ``Range``, RFC 9110
        §14.2, and a multipart body is not offered).

    Raises:
        RangeNotSatisfiableError: When the one range asked for starts past the end (or asks for the
            last 0 bytes); the caller answers ``416``.
    """
    if not header or "," in header:
        return None
    match = _RANGE.match(header)
    if not match:
        return None
    first, last = match.group(1), match.group(2)
    if not first and not last:
        return None
    if not first:
        suffix = int(last)
        if suffix == 0 or size == 0:
            raise RangeNotSatisfiableError(header)
        return max(0, size - suffix), size - 1
    start = int(first)
    if last and int(last) < start:
        return None
    if start >= size:
        raise RangeNotSatisfiableError(header)
    end = int(last) if last else size - 1
    return start, min(end, size - 1)


def iter_stream(original: MaterializedOriginal, start: int = 0, end: Optional[int] = None) -> Iterator[bytes]:
    """Yield bytes ``start``…``end`` (inclusive) of an open original, then close it.

    Args:
        original: The open content.
        start: First byte to send.
        end: Last byte to send; the end of the content when ``None``.

    Yields:
        Chunks of at most :data:`CHUNK_BYTES`.
    """
    try:
        last = original.size - 1 if end is None else end
        remaining = last - start + 1
        original.stream.seek(start)
        while remaining > 0:
            chunk = original.stream.read(min(CHUNK_BYTES, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        original.close()


def describe(resolved: ResolvedOriginal) -> Dict[str, Any]:
    """Summarize an original for a log line: never its content or a link.

    Args:
        resolved: The object being served.

    Returns:
        The digest prefix, coding, media type and whether it is a manifest or a legacy column.
    """
    return {
        "sha256": (resolved.sha256 or "")[:12],
        "encoding": resolved.encoding,
        "media_type": resolved.media_type,
        "manifest": resolved.is_manifest,
        "legacy": resolved.legacy_content is not None,
    }
