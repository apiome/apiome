"""One way to read the source an import captured for a revision (COA-5.4, #7080).

An import keeps the document it read. Since COA-5.3 that document lives in the document store
(:mod:`app.document_store`), linked to the revision by ``version_documents`` rows. Before that it
lived in one of two database columns, which the ``db`` backend still writes and which older
revisions still hold:

* ``versions.format_metadata.sourceContent`` — every format the adapter pipeline imports;
* ``version_import_snapshots.source_text`` — OpenAPI and Swagger decomposed by the apiome-ui worker.

:func:`revision_source` is the only reader of both. It tries the store first and the two columns
second, and returns the same :class:`RevisionSource` either way. No other module names those
columns for reading: ``tests/test_revision_source_readers.py`` fails when one does.

Three more pieces live here because they need the same column names:

* :func:`source_from_row` reads a source off a row a caller already holds: the one
  :func:`attach_revision_source` put there, or legacy keys the row still carries.
* :func:`sourceless_format_metadata_sql` and :func:`source_captured_sql` are the SQL fragments
  that keep the source out of version queries while still saying whether one exists.
* :class:`CanonicalModelCache` keeps parsed canonical models in this process, keyed by the digest
  of the source they were parsed from, bounded by entry count and by source bytes.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from .config import settings
from .original_documents import (
    MANIFEST_MEDIA_TYPE,
    ROLE_ORIGINAL,
    ROLE_ORIGINAL_PART,
    decode_original,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ORIGIN_LEGACY",
    "ORIGIN_STORE",
    "SOURCE_ROW_KEY",
    "CanonicalModelCache",
    "RevisionSource",
    "attach_revision_source",
    "canonical_model_cache",
    "has_revision_source",
    "legacy_fileset",
    "revision_source",
    "row_has_source",
    "source_captured_sql",
    "source_from_row",
    "source_from_text",
    "sourceless_format_metadata_sql",
]

#: Row key under which :func:`attach_revision_source` puts a revision's :class:`RevisionSource`.
SOURCE_ROW_KEY = "revision_source"

#: Where a :class:`RevisionSource` was read from.
ORIGIN_STORE = "store"
ORIGIN_LEGACY = "legacy"

# The legacy ``format_metadata`` key and the older spellings some rows still carry, in priority
# order. The project's ``metadata`` bag is read with the same keys when the revision has none.
_CONTENT_KEY = "sourceContent"
_CONTENT_KEYS: Tuple[str, ...] = (
    _CONTENT_KEY, "source_content",
    "sourceText", "source_text",
    "rawSource", "raw_source",
    "raw", "content",
)
_SNAPSHOT_TEXT_COLUMN = "source_text"

_ORIGINALS_SQL = f"""
    SELECT d.role, d.part_path, o.sha256, o.media_type, o.encoding,
           v.source_format,
           (coalesce(v.format_metadata -> 'sourceDocument' ->> 'sha256', '') <> ''
            OR coalesce(v.format_metadata ->> '{_CONTENT_KEY}', '') <> '') AS adapter_captured
    FROM apiome.version_documents d
    JOIN apiome.document_objects o ON o.id = d.object_id
    JOIN apiome.versions v ON v.id = d.version_id
    JOIN apiome.projects p ON p.id = v.project_id
    WHERE d.version_id = %s::uuid AND o.tenant_id = %s AND p.tenant_id = %s
      AND v.deleted_at IS NULL
      AND d.role IN ('{ROLE_ORIGINAL}', '{ROLE_ORIGINAL_PART}')
    ORDER BY (d.role = '{ROLE_ORIGINAL}') DESC, d.part_path
"""

_LEGACY_SQL = f"""
    SELECT v.source_format, v.format_metadata, p.metadata,
           s.{_SNAPSHOT_TEXT_COLUMN} AS snapshot_text
    FROM apiome.versions v
    JOIN apiome.projects p ON p.id = v.project_id
    LEFT JOIN apiome.version_import_snapshots s
           ON s.version_id = v.id AND s.tenant_id = p.tenant_id
    WHERE v.id = %s::uuid AND p.tenant_id = %s AND v.deleted_at IS NULL
"""


_AVAILABLE_SQL = f"""
    SELECT EXISTS (
               SELECT 1
               FROM apiome.version_documents d
               JOIN apiome.document_objects o ON o.id = d.object_id
               WHERE d.version_id = v.id AND o.tenant_id = %s AND d.role = '{ROLE_ORIGINAL}'
           ) AS stored,
           (coalesce(v.format_metadata -> 'sourceDocument' ->> 'sha256', '') <> ''
            OR coalesce(v.format_metadata ->> '{_CONTENT_KEY}', '') <> '') AS adapter_captured,
           coalesce(s.{_SNAPSHOT_TEXT_COLUMN}, '') <> '' AS snapshot_text
    FROM apiome.versions v
    JOIN apiome.projects p ON p.id = v.project_id
    LEFT JOIN apiome.version_import_snapshots s
           ON s.version_id = v.id AND s.tenant_id = p.tenant_id
    WHERE v.id = %s::uuid AND p.tenant_id = %s AND v.deleted_at IS NULL
"""

def sourceless_format_metadata_sql(alias: str = "v") -> str:
    """Return the SQL expression for a revision's ``format_metadata`` without its source text.

    Version queries use this instead of the bare column so a list or a projection does not carry
    every revision's whole document. Everything else in the bag (labels, counts, the
    ``sourceDocument`` pointer, ``sourceWithheld``) is kept.

    Args:
        alias: The ``apiome.versions`` table alias in the query.

    Returns:
        A JSONB expression. It has no column alias; add ``AS format_metadata`` where needed.
    """
    return f"({alias}.format_metadata - '{_CONTENT_KEY}')"


def source_captured_sql(alias: str = "v") -> str:
    """Return the SQL expression that says whether a revision has a captured source.

    True for a source kept in the document store (the ``sourceDocument`` pointer) and for one
    kept in the legacy column.

    Args:
        alias: The ``apiome.versions`` table alias in the query.

    Returns:
        A boolean expression with no column alias.
    """
    return (
        f"(coalesce({alias}.format_metadata -> 'sourceDocument' ->> 'sha256', '') <> ''"
        f" OR coalesce({alias}.format_metadata ->> '{_CONTENT_KEY}', '') <> '')"
    )


@dataclass(frozen=True)
class RevisionSource:
    """The source an import captured for one revision.

    Attributes:
        text: The document. For a set of files, the root file's text.
        digest: Hex SHA-256 that identifies the captured content: of the document's bytes, or of
            a set's manifest. Equal content gives an equal digest, so it keys the model cache.
        format: The revision's recorded ``source_format`` (``graphql``, ``protobuf``, …), if any.
        media_type: Media type of the document, when the store recorded one.
        origin: :data:`ORIGIN_STORE` or :data:`ORIGIN_LEGACY`.
        members: For a set of files, the exact bytes of every file keyed by its path; else ``None``.
        root: For a set of files, the path of the root file.
        decomposed: ``True`` when the document was read by a decomposing import (OpenAPI, Swagger
            or Arazzo through the apiome-ui worker). Such a revision's classes, paths and
            workflows are its truth and may have been edited since, so model rebuilds do not use
            this document; provenance does.
    """

    text: str
    digest: str
    format: Optional[str] = None
    media_type: Optional[str] = None
    origin: str = ORIGIN_LEGACY
    members: Optional[Mapping[str, bytes]] = None
    root: Optional[str] = None
    decomposed: bool = False

    @property
    def is_fileset(self) -> bool:
        """Whether the source is a set of files rather than one document."""
        return bool(self.members)

    @property
    def size_bytes(self) -> int:
        """Size of the captured content in bytes: the document, or every file of a set."""
        if self.members:
            return sum(len(data) for data in self.members.values())
        return len(self.text.encode("utf-8"))

    def intake_fileset(self) -> Any:
        """Return the set of files as the :class:`~app.fileset.IntakeFileset` an import parses.

        Returns:
            The fileset, or ``None`` for a single document.

        Raises:
            ValueError: When the recorded root is not one of the files.
        """
        if not self.members:
            return None
        from .fileset import IntakeFileset  # noqa: PLC0415 - keep this module light to import

        texts: Dict[str, str] = {}
        binary: Dict[str, bytes] = {}
        for path, data in self.members.items():
            try:
                texts[path] = bytes(data).decode("utf-8")
            except UnicodeDecodeError:
                texts[path] = bytes(data).decode("utf-8", errors="replace")
                binary[path] = bytes(data)
        return IntakeFileset.from_members(texts, root=self.root, binary_members=binary)


def _sha256(data: bytes) -> str:
    """Return the hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def source_from_text(text: str, *, source_format: Optional[str] = None) -> RevisionSource:
    """Wrap a document a caller built itself (not one an import captured) as a source.

    Used where a reader substitutes a regenerated document for a missing capture, so that the
    rest of the read path handles both the same way.

    Args:
        text: The document.
        source_format: The format the document is in.

    Returns:
        A :class:`RevisionSource` with the text, its digest and the format.
    """
    return RevisionSource(text=text, digest=_sha256(text.encode("utf-8")), format=source_format)


def _bag(value: Any) -> Dict[str, Any]:
    """Return ``value`` when it is a JSON object, else an empty one."""
    return value if isinstance(value, dict) else {}


def _first_text(bag: Mapping[str, Any]) -> Optional[str]:
    """Return the first non-blank legacy source value in ``bag``, trimmed, or ``None``."""
    for key in _CONTENT_KEYS:
        value = bag.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def legacy_fileset(content: str, root: Optional[str]) -> Optional[Tuple[Dict[str, bytes], str]]:
    """Unpack a legacy base64 archive into its files.

    Readers use it to serve an archive kept in ``format_metadata``; the migration job
    (:mod:`app.document_migration`, COA-5.8) uses it to move that archive into the store.

    Args:
        content: The base64 text of the archive.
        root: The root path the import chose, if recorded.

    Returns:
        ``(members, root)``, or ``None`` when the archive cannot be decoded or unpacked. The
        caller then falls back to treating ``content`` as plain text, as readers did before.
    """
    from .archive_intake import ArchiveIntakeError, unpack_archive  # noqa: PLC0415 - heavy import

    try:
        unpacked = unpack_archive(base64.standard_b64decode(content), root_path=root)
    except (ArchiveIntakeError, ValueError, binascii.Error) as exc:
        logger.info("legacy archive source not unpacked: %s", type(exc).__name__)
        return None
    members = {
        path: unpacked.binary_members[path] if path in unpacked.binary_members else text.encode("utf-8")
        for path, text in unpacked.members.items()
    }
    return members, unpacked.root_path


def _from_legacy_bags(
    format_metadata: Any, metadata: Any, source_format: Optional[str]
) -> Optional[RevisionSource]:
    """Read a source from the legacy ``format_metadata`` keys (then the project ``metadata``).

    Args:
        format_metadata: The revision's ``format_metadata`` bag.
        metadata: The project's ``metadata`` bag.
        source_format: The revision's ``source_format``.

    Returns:
        The source, or ``None`` when neither bag holds one.
    """
    fmd = _bag(format_metadata)
    content = _first_text(fmd) or _first_text(_bag(metadata))
    if content is None:
        return None
    if fmd.get("intakeKind") == "archive" and fmd.get("sourceEncoding") == "base64":
        root = fmd.get("filesetRoot") if isinstance(fmd.get("filesetRoot"), str) else None
        unpacked = legacy_fileset(content, root)
        if unpacked is not None:
            members, chosen = unpacked
            return RevisionSource(
                text=members[chosen].decode("utf-8", errors="replace"),
                # The archive's own bytes are what the legacy column identifies.
                digest=_sha256(content.encode("utf-8")),
                format=source_format,
                members=members,
                root=chosen,
            )
    return RevisionSource(text=content, digest=_sha256(content.encode("utf-8")), format=source_format)


def source_from_row(row: Optional[Mapping[str, Any]]) -> Optional[RevisionSource]:
    """Read the captured source for a row a caller already holds.

    Three places are tried, in order:

    1. the source attached under :data:`SOURCE_ROW_KEY` (see :func:`attach_revision_source`);
    2. for a catalog item row (it names its ``tenant_id`` and ``latest_version_id`` and says
       ``source_captured``), :func:`revision_source` with the process-wide database and store.
       Catalog item rows do not carry the source text, so this is where theirs comes from;
    3. the legacy keys in the row's own ``format_metadata`` / ``metadata``.

    Only step 2 reads the database or the store.

    Args:
        row: A revision or catalog-item row.

    Returns:
        The source, or ``None`` when the row has none.
    """
    if not row:
        return None
    attached = row.get(SOURCE_ROW_KEY)
    if isinstance(attached, RevisionSource):
        return attached
    if row.get("source_captured") is True and row.get("latest_version_id") and row.get("tenant_id"):
        stored = revision_source(None, None, str(row["tenant_id"]), str(row["latest_version_id"]))
        if stored is not None:
            return stored
    return _from_legacy_bags(row.get("format_metadata"), row.get("metadata"), row.get("source_format"))


def row_has_source(row: Optional[Mapping[str, Any]]) -> bool:
    """Say whether a row a caller holds has a captured source, without reading the source.

    Args:
        row: A revision or catalog-item row. ``source_captured`` (see :func:`source_captured_sql`)
            answers when the query selected it; otherwise an attached source or a legacy key does.

    Returns:
        ``True`` when the revision has a source to serve or rebuild from.
    """
    if not row:
        return False
    if row.get("source_captured") is True or isinstance(row.get(SOURCE_ROW_KEY), RevisionSource):
        return True
    return (_first_text(_bag(row.get("format_metadata"))) or _first_text(_bag(row.get("metadata")))) is not None


def _query(db: Any, sql: str, params: Tuple[Any, ...]) -> list:
    """Run a read and return its rows, or an empty list when the database cannot answer.

    Args:
        db: The database layer (``execute_query``).
        sql: The statement.
        params: Its parameters.

    Returns:
        The rows as a list. A failure is logged by type and reads as "no rows", so a reader
        falls through to whatever the caller's row still carries.
    """
    try:
        rows = db.execute_query(sql, params)
    except Exception as exc:  # noqa: BLE001 - a source read must degrade, not raise
        logger.warning("revision source query failed: %s", type(exc).__name__)
        return []
    return rows if isinstance(rows, list) else []


def _from_store(db: Any, store: Any, tenant_id: str, version_id: str) -> Optional[RevisionSource]:
    """Read a revision's original from the document store.

    Args:
        db: The database layer.
        store: The document store.
        tenant_id: The tenant that owns the revision and its objects.
        version_id: The revision (``versions.id``).

    Returns:
        The source, or ``None`` when the revision has no original row or its bytes cannot be read.
    """
    rows = _query(db, _ORIGINALS_SQL, (version_id, tenant_id, tenant_id))
    original = next((row for row in rows if row.get("role") == ROLE_ORIGINAL), None)
    if original is None:
        return None
    try:
        content = decode_original(store.get(tenant_id, original["sha256"]), original.get("encoding"))
        source_format = original.get("source_format")
        decomposed = not original.get("adapter_captured")
        if original.get("media_type") != MANIFEST_MEDIA_TYPE:
            return RevisionSource(
                text=content.decode("utf-8", errors="replace"),
                digest=_sha256(content),
                format=source_format,
                media_type=original.get("media_type"),
                origin=ORIGIN_STORE,
                decomposed=decomposed,
            )
        manifest = json.loads(content.decode("utf-8"))
        members = {
            str(row["part_path"]): decode_original(store.get(tenant_id, row["sha256"]), row.get("encoding"))
            for row in rows
            if row.get("role") == ROLE_ORIGINAL_PART and row.get("part_path")
        }
        root = manifest.get("root") if isinstance(manifest, dict) else None
        if not members or root not in members:
            logger.warning("original fileset incomplete version_id=%s", version_id)
            return None
        return RevisionSource(
            text=members[root].decode("utf-8", errors="replace"),
            digest=_sha256(content),
            format=source_format,
            media_type=MANIFEST_MEDIA_TYPE,
            origin=ORIGIN_STORE,
            members=members,
            root=root,
            decomposed=decomposed,
        )
    except Exception as exc:  # noqa: BLE001 - an unreadable object falls back to the legacy columns
        logger.warning("original not read version_id=%s: %s", version_id, type(exc).__name__)
        return None


def _from_legacy_columns(db: Any, tenant_id: str, version_id: str) -> Optional[RevisionSource]:
    """Read a revision's source from the legacy database columns.

    Args:
        db: The database layer.
        tenant_id: The tenant that owns the revision.
        version_id: The revision (``versions.id``).

    Returns:
        The ``format_metadata`` source when there is one; else the import snapshot's text (a
        decomposed import); else ``None``.
    """
    rows = _query(db, _LEGACY_SQL, (version_id, tenant_id))
    row = rows[0] if rows and isinstance(rows[0], Mapping) else None
    if row is None:
        return None
    source = _from_legacy_bags(row.get("format_metadata"), row.get("metadata"), row.get("source_format"))
    if source is not None:
        return source
    text = row.get("snapshot_text")
    if isinstance(text, str) and text:
        return RevisionSource(
            text=text,
            digest=_sha256(text.encode("utf-8")),
            format=row.get("source_format"),
            decomposed=True,
        )
    return None


def revision_source(
    db: Any, store: Any, tenant_id: str, version_id: str, *, decomposed: bool = False
) -> Optional[RevisionSource]:
    """Return the source an import captured for a revision: its text, digest and format.

    Tries the document store (``version_documents``) first and the legacy columns second. Never
    raises: a missing object, an unreachable bucket or a failed query reads as "not there" and
    the next place is tried.

    Args:
        db: The database layer (``execute_query``); the process-wide one when ``None``.
        store: The document store; the process-wide one when ``None``.
        tenant_id: The tenant that owns the revision. A revision of another tenant reads as
            having no source.
        version_id: The revision (``versions.id``).
        decomposed: Also return the document a decomposing import read (see
            :attr:`RevisionSource.decomposed`). Leave ``False`` to rebuild a model; pass ``True``
            to show or quote what was imported.

    Returns:
        The source, or ``None`` when none was captured (or it was withheld at import).
    """
    if not tenant_id or not version_id:
        return None
    tenant, version = str(tenant_id), str(version_id)
    try:
        if db is None:
            from .database import db as database  # noqa: PLC0415 - avoid an import cycle at load

            db = database
        if store is None:
            from .document_store import get_document_store  # noqa: PLC0415

            store = get_document_store()
    except Exception as exc:  # noqa: BLE001 - a misconfigured store must not fail a read
        logger.warning("revision source unavailable: %s", type(exc).__name__)
        return None
    source = _from_store(db, store, tenant, version) or _from_legacy_columns(db, tenant, version)
    if source is None or (source.decomposed and not decomposed):
        return None
    return source


def has_revision_source(db: Any, tenant_id: str, version_id: str, *, decomposed: bool = False) -> bool:
    """Say whether :func:`revision_source` would find a source, without reading its content.

    Args:
        db: The database layer (``execute_query``).
        tenant_id: The tenant that owns the revision.
        version_id: The revision (``versions.id``).
        decomposed: Count the document a decomposing import read (see :func:`revision_source`).

    Returns:
        ``True`` when the revision has an original in the store or a source in a legacy column.
        The store's bytes are not checked.
    """
    if not tenant_id or not version_id:
        return False
    rows = _query(db, _AVAILABLE_SQL, (str(tenant_id), str(version_id), str(tenant_id)))
    row = rows[0] if rows and isinstance(rows[0], Mapping) else None
    if row is None:
        return False
    if row.get("adapter_captured"):
        return True
    return decomposed and bool(row.get("stored") or row.get("snapshot_text"))


def attach_revision_source(
    row: Mapping[str, Any],
    *,
    tenant_id: Optional[str],
    version_id: Optional[str],
    db: Any = None,
    store: Any = None,
) -> Dict[str, Any]:
    """Return a copy of a row carrying its revision's captured source for :func:`source_from_row`.

    The row-shaped readers (source download, conversion, fingerprinting) take a revision or
    catalog-item row. A caller that loaded the row from the database passes it through here so
    those readers see the stored original, whatever backend holds it.

    Args:
        row: The row to copy.
        tenant_id: The tenant that owns the revision.
        version_id: The revision (``versions.id``) the row describes.
        db: The database layer; the process-wide one when omitted.
        store: The document store; the process-wide one when omitted.

    Returns:
        A dict copy of ``row``. It carries the source under :data:`SOURCE_ROW_KEY` when
        :func:`revision_source` found one; otherwise it is unchanged, so legacy keys the row
        itself holds are still read.
    """
    copy = dict(row)
    if copy.get(SOURCE_ROW_KEY) is None and tenant_id and version_id:
        source = revision_source(db, store, str(tenant_id), str(version_id))
        if source is not None:
            copy[SOURCE_ROW_KEY] = source
    return copy


class CanonicalModelCache:
    """Parsed canonical models kept in this process, least recently used first out.

    Parsing and normalizing a large document costs far more than copying its model, and the same
    revision is read again and again (export, lint, compatibility, conversion preview). Entries
    are keyed by the digest of the source they were parsed from, so a changed source is a new
    entry and nothing needs invalidating.

    Two limits bound memory: a number of entries, and the total size of the sources the cached
    models came from (a stand-in for model size that needs no measuring). A source larger than
    a quarter of the byte limit is not cached. Either limit at ``0`` turns the cache off.

    A cached model is never handed out: :meth:`get_or_build` returns a deep copy each time,
    because readers change the model they get (plans, overlays, pack refinements).
    """

    def __init__(self, max_entries: int, max_source_bytes: int) -> None:
        """Create a cache.

        Args:
            max_entries: Most models kept.
            max_source_bytes: Most source bytes the kept models may add up to.
        """
        self._max_entries = max(0, int(max_entries))
        self._max_bytes = max(0, int(max_source_bytes))
        self._entries: "OrderedDict[Tuple[Any, ...], Tuple[Any, int]]" = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @property
    def enabled(self) -> bool:
        """Whether the cache keeps anything."""
        return self._max_entries > 0 and self._max_bytes > 0

    def __len__(self) -> int:
        """Return the number of models kept."""
        return len(self._entries)

    @property
    def source_bytes(self) -> int:
        """Total source bytes of the models kept."""
        return self._bytes

    def clear(self) -> None:
        """Drop every model and reset the counters."""
        with self._lock:
            self._entries.clear()
            self._bytes = 0
            self.hits = 0
            self.misses = 0

    def get_or_build(self, key: Tuple[Any, ...], size_bytes: int, build: Callable[[], Any]) -> Any:
        """Return the model for ``key``, building and keeping it on a miss.

        Args:
            key: What identifies the parse: tenant, source digest, format, adapter.
            size_bytes: Size of the source the model is parsed from.
            build: Parses and normalizes the source. Its exceptions pass through and nothing is
                kept.

        Returns:
            A model the caller owns: a deep copy of the kept one, or the freshly built one.
        """
        if not self.enabled:
            return build()
        with self._lock:
            kept = self._entries.get(key)
            if kept is not None:
                self._entries.move_to_end(key)
                self.hits += 1
        if kept is not None:
            return kept[0].model_copy(deep=True)
        model = build()
        size = max(0, int(size_bytes))
        if size > self._max_bytes // 4:
            with self._lock:
                self.misses += 1
            return model
        snapshot = model.model_copy(deep=True)
        with self._lock:
            self.misses += 1
            previous = self._entries.pop(key, None)
            if previous is not None:
                self._bytes -= previous[1]
            self._entries[key] = (snapshot, size)
            self._bytes += size
            while self._entries and (len(self._entries) > self._max_entries or self._bytes > self._max_bytes):
                _, (_, dropped) = self._entries.popitem(last=False)
                self._bytes -= dropped
        return model


_cache_lock = threading.Lock()
_cache: Optional[CanonicalModelCache] = None


def canonical_model_cache() -> CanonicalModelCache:
    """Return the process-wide model cache, sized from the settings on first use.

    Returns:
        The cache built from ``APIOME_CANONICAL_MODEL_CACHE_ENTRIES`` and
        ``APIOME_CANONICAL_MODEL_CACHE_MAX_BYTES``.
    """
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                _cache = CanonicalModelCache(
                    settings.canonical_model_cache_entries,
                    settings.canonical_model_cache_max_bytes,
                )
    return _cache
