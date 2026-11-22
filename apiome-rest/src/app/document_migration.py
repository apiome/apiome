"""Move documents still held in the database into the document store — COA-5.8 (#7084).

Since COA-5.3 / COA-5.5 every new import, freeze and large export writes its bytes to the
document store (:mod:`app.document_store`). Rows written before that still hold them in the
database, in four places this job calls **sources**:

=================== =========================================== ==========================================
Source              Database copy                                Where the store copy is recorded
=================== =========================================== ==========================================
``adapter_source``  ``versions.format_metadata.sourceContent``  ``version_documents`` ``original`` (plus
                    (a base64 archive is unpacked into files)    one ``original_part`` per file) and the
                                                                 ``format_metadata.sourceDocument`` pointer
``import_snapshot`` ``version_import_snapshots.source_text``    ``version_documents`` ``original``
``frozen_schema``   ``version_spec_snapshots.content``          ``version_documents`` ``frozen_schema``
``export_artifact`` ``export_job_artifact.content``             ``export_job_artifact.storage_uri``
=================== =========================================== ==========================================

The job runs in two **steps**, never both at once:

* ``copy`` writes each database copy to the store exactly as an import would have (same coding,
  same media type, same fileset layout), reads it back and checks its SHA-256 and its content,
  stamps ``document_objects.verified_at``, then links it. The database copy is left in place.
* ``purge`` (``--purge-db-copies``) reads each linked object back from the store again, checks it
  is byte-for-byte the database copy, and only then drops the database copy. It is refused on the
  ``db`` backend, where the database copies are kept by design (see
  :func:`app.original_documents.legacy_source_columns_kept`).

Guarantees:

* **Re-running is a no-op.** Each step's query selects only rows that still need it: a copied
  row is linked to an object on the current backend, and a purged row has no database copy.
* **Resumable.** After each batch the step records the key of the last row it finished in
  ``apiome.document_migration_checkpoints`` (V405). A run of an unfinished step starts after it.
* **Never loses a document.** A row whose store copy cannot be read back identically is counted
  as ``failed`` and keeps its database copy. A revision whose stored original differs from its
  database copy is ``skipped``, never overwritten.
* **Bounded.** One row's document is in memory at a time per worker; rows are paged by key;
  ``rate`` caps rows per second; one worker by default. Only one non-dry run proceeds at a time
  (a Postgres advisory lock).
* **Does not touch the content stamp.** Recording the pointer or dropping ``sourceContent``
  changes no rendered content, so ``versions.content_stamp`` is claimed in the same statement
  and the rendered-document caches stay valid.

``scripts/migrate_documents_to_store.py`` runs it from a shell; ``POST /v1/ops/document-migration``
(:mod:`app.document_migration_routes`) runs it as a background job.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .document_store import BACKEND_DB, BACKEND_TENANT_S3, parse_object_uri
from .export_artifact_store import content_sha256_hex
from .original_documents import (
    ENCODING_IDENTITY,
    MANIFEST_MEDIA_TYPE,
    decode_original,
    encode_original,
    fileset_manifest,
    media_type_for,
)
from .revision_source import legacy_fileset

logger = logging.getLogger(__name__)

__all__ = [
    "ADAPTER_SOURCE",
    "EXPORT_ARTIFACT",
    "FROZEN_SCHEMA",
    "IMPORT_SNAPSHOT",
    "MigrationBusy",
    "MigrationOptions",
    "MigrationRefused",
    "MigrationReport",
    "RateLimiter",
    "SOURCES",
    "STEP_COPY",
    "check_options",
    "STEP_PURGE",
    "list_checkpoints",
    "run_document_migration",
]

ADAPTER_SOURCE = "adapter_source"
IMPORT_SNAPSHOT = "import_snapshot"
FROZEN_SCHEMA = "frozen_schema"
EXPORT_ARTIFACT = "export_artifact"
#: Every source, in the order a run visits them.
SOURCES: Tuple[str, ...] = (ADAPTER_SOURCE, IMPORT_SNAPSHOT, FROZEN_SCHEMA, EXPORT_ARTIFACT)

STEP_COPY = "copy"
STEP_PURGE = "purge"

#: Row outcomes. A dry run reports ``would-copy`` / ``would-purge`` instead of writing.
COPIED = "copied"
PURGED = "purged"
WOULD_COPY = "would-copy"
WOULD_PURGE = "would-purge"
SKIPPED = "skipped"
FAILED = "failed"

#: ``checkpoint.scope`` of a run over every tenant.
SCOPE_ALL = "all"
#: Most failed or skipped rows a report lists one by one (the totals count every one).
MAX_LISTED_ROWS = 100
#: Upper bounds on the knobs, so a typo cannot open dozens of connections or fetch huge pages.
MAX_WORKERS = 4
MAX_BATCH_SIZE = 500

_LOCK_KEY = "apiome-document-migration"
_FROZEN_MEDIA_TYPE = "application/json"


class MigrationRefused(Exception):
    """The run cannot start as asked (for example a purge on the ``db`` backend)."""


class MigrationBusy(Exception):
    """Another run holds the migration lock."""


@dataclass(frozen=True)
class MigrationOptions:
    """What one run does.

    Attributes:
        purge_db_copies: Run the ``purge`` step instead of the ``copy`` step.
        dry_run: Report what the step would do; write nothing (no checkpoint either).
        tenant_id: Limit the run to one tenant (``tenants.id``); every tenant when ``None``.
        sources: The sources to visit, in :data:`SOURCES` order; all of them by default.
        batch_size: Rows fetched per page and checkpointed together (1–500).
        rate: Most rows processed per second; ``0`` or less means no limit.
        workers: Rows processed in parallel within a batch (1–4). Each worker thread uses its own
            database connection, so keep it at 1 when the database handle is pinned to one
            connection (as in tests).
    """

    purge_db_copies: bool = False
    dry_run: bool = False
    tenant_id: Optional[str] = None
    sources: Tuple[str, ...] = SOURCES
    batch_size: int = 50
    rate: float = 20.0
    workers: int = 1

    @property
    def step(self) -> str:
        """``purge`` or ``copy``."""
        return STEP_PURGE if self.purge_db_copies else STEP_COPY

    @property
    def scope(self) -> str:
        """The checkpoint scope: the tenant id, or ``all``."""
        return str(self.tenant_id) if self.tenant_id else SCOPE_ALL

    def validated(self) -> "MigrationOptions":
        """Return the options with the knobs clamped to their bounds.

        Raises:
            MigrationRefused: when a source name is unknown.
        """
        unknown = [name for name in self.sources if name not in SOURCES]
        if unknown:
            raise MigrationRefused(f"Unknown source(s): {', '.join(unknown)}. Known: {', '.join(SOURCES)}.")
        ordered = tuple(name for name in SOURCES if name in self.sources)
        tenant = str(self.tenant_id).strip() if self.tenant_id else ""
        if tenant:
            try:
                tenant = str(uuid.UUID(tenant))
            except ValueError:
                raise MigrationRefused(f"--tenant must be a tenant id (UUID), not {tenant!r}.") from None
        return MigrationOptions(
            purge_db_copies=self.purge_db_copies,
            dry_run=self.dry_run,
            tenant_id=tenant or None,
            sources=ordered,
            batch_size=min(MAX_BATCH_SIZE, max(1, int(self.batch_size))),
            rate=float(self.rate),
            workers=min(MAX_WORKERS, max(1, int(self.workers))),
        )


@dataclass
class SourceTotals:
    """One source's totals for this run, and where the step started.

    Attributes:
        counts: Rows by outcome, plus ``scanned`` and ``bytes`` (database-copy bytes handled).
        resumed_after: The checkpoint key this run started after, when it resumed an unfinished
            step; ``None`` when it started from the beginning.
        completed: Whether the step reached the end of the source.
        note: Why the source was not visited, when it was not.
    """

    counts: Dict[str, int] = field(default_factory=dict)
    resumed_after: Optional[str] = None
    completed: bool = False
    note: Optional[str] = None

    def add(self, status: str, size: int = 0) -> None:
        """Count one row with ``status`` and its document's size."""
        self.counts["scanned"] = self.counts.get("scanned", 0) + 1
        self.counts[status] = self.counts.get(status, 0) + 1
        self.counts["bytes"] = self.counts.get("bytes", 0) + max(0, int(size))

    def as_dict(self) -> Dict[str, Any]:
        """JSON-ready form."""
        return {
            "counts": dict(self.counts),
            "resumed_after": self.resumed_after,
            "completed": self.completed,
            "note": self.note,
        }


@dataclass
class MigrationReport:
    """What a run did: per-source totals and the rows that were skipped or failed.

    Attributes:
        step: ``copy`` or ``purge``.
        dry_run: Whether the run wrote nothing.
        backend: The document store backend written to or verified against.
        scope: ``all`` or the tenant id.
        sources: Totals per source, in visiting order.
        rows: Up to :data:`MAX_LISTED_ROWS` skipped or failed rows (source, key, status, detail).
        started_at / finished_at: Wall-clock seconds since the epoch.
    """

    step: str
    dry_run: bool
    backend: str
    scope: str
    sources: Dict[str, SourceTotals] = field(default_factory=dict)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    def note_row(self, source: str, key: str, status: str, detail: Optional[str]) -> None:
        """List a skipped or failed row, up to :data:`MAX_LISTED_ROWS` of them."""
        if len(self.rows) < MAX_LISTED_ROWS:
            self.rows.append({"source": source, "key": key, "status": status, "detail": detail})

    def total(self, status: str) -> int:
        """Rows with ``status`` across every source."""
        return sum(totals.counts.get(status, 0) for totals in self.sources.values())

    def as_dict(self) -> Dict[str, Any]:
        """JSON-ready report: totals first, then each source, then the listed rows."""
        done = (WOULD_PURGE if self.dry_run else PURGED) if self.step == STEP_PURGE else (
            WOULD_COPY if self.dry_run else COPIED
        )
        return {
            "step": self.step,
            "dry_run": self.dry_run,
            "backend": self.backend,
            "scope": self.scope,
            "scanned": self.total("scanned"),
            "done": self.total(done),
            "skipped": self.total(SKIPPED),
            "failed": self.total(FAILED),
            "sources": {name: totals.as_dict() for name, totals in self.sources.items()},
            "rows": list(self.rows),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class RateLimiter:
    """Spaces rows out so a run processes at most ``rate`` rows per second (shared by workers)."""

    def __init__(
        self,
        rate: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """
        Args:
            rate: Rows per second; ``0`` or less disables the limit.
            clock: Monotonic clock (tests inject a fake).
            sleep: Sleep function (tests inject a fake).
        """
        self._interval = 1.0 / rate if rate and rate > 0 else 0.0
        self._clock = clock
        self._sleep = sleep
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        """Block until the next row may start."""
        if not self._interval:
            return
        with self._lock:
            now = self._clock()
            start = max(now, self._next)
            self._next = start + self._interval
        if start > now:
            self._sleep(start - now)


# ───────────────────────────── row outcome and context ─────────────────────────────


@dataclass(frozen=True)
class _Outcome:
    """What happened to one row."""

    status: str
    size: int = 0
    detail: Optional[str] = None


@dataclass
class _Context:
    """What a row handler needs: the database layer, the store and the options."""

    db: Any
    store: Any
    options: MigrationOptions

    @property
    def backend(self) -> str:
        """The current store's backend name."""
        return str(getattr(self.store, "backend", BACKEND_DB))

    def in_store(self, backend: Any) -> bool:
        """Whether an object recorded with ``backend`` is in the current store.

        That is the platform store's backend, or ``tenant_s3``: a tenant that keeps documents in
        its own bucket (COA-5.15, #7092) is written there by the same store handle.
        """
        return str(backend) in (self.backend, BACKEND_TENANT_S3)


def _sha256(data: bytes) -> str:
    """Lower-case hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def _as_bytes(value: Any) -> bytes:
    """A ``bytea`` column value (``memoryview`` / ``bytes``) as bytes."""
    if isinstance(value, memoryview):
        return value.tobytes()
    return bytes(value)


def _first(db: Any, sql: str, params: Tuple[Any, ...]) -> Optional[Dict[str, Any]]:
    """The first row of a read, or ``None``."""
    rows = db.execute_query(sql, params)
    return dict(rows[0]) if rows else None


# ───────────────────────────── writing and verifying objects ─────────────────────────────


class _VerifyFailed(Exception):
    """A store copy did not read back identical to what was written or expected."""


def _read_back(store: Any, tenant: str, sha256: str, encoding: Optional[str]) -> bytes:
    """Read an object back, check its digest, and return its decoded content.

    Raises:
        _VerifyFailed: when the stored bytes do not hash to ``sha256`` or cannot be decoded.
        DocumentNotFound / DocumentStoreError: when the store cannot return the object.
    """
    stored = store.get(tenant, sha256)
    if _sha256(stored) != sha256:
        raise _VerifyFailed("stored bytes do not match their SHA-256")
    try:
        return decode_original(stored, encoding)
    except ValueError as exc:
        raise _VerifyFailed(str(exc)) from None


def _mark_verified(db: Any, object_id: str) -> None:
    """Stamp ``document_objects.verified_at`` after a successful read-back."""
    db.execute_query(
        "UPDATE apiome.document_objects SET verified_at = now() WHERE id = %s::uuid RETURNING id",
        (object_id,),
    )


def _put_verified(
    ctx: _Context, tenant: str, content: bytes, media_type: str, *, coded: bool = True
) -> Tuple[str, Dict[str, Any]]:
    """Write a document to the store, read it back, record and stamp it as verified.

    Args:
        ctx: The run context.
        tenant: The store tenant segment (a tenant id).
        content: The document's content.
        media_type: Its media type.
        coded: Apply the originals' gzip coding (``False`` for frozen schemas, served as-is).

    Returns:
        ``(object_id, facts)`` where ``facts`` holds ``sha256``, ``contentSha256``, ``sizeBytes``,
        ``mediaType`` and ``encoding`` — the ``sourceDocument`` pointer fields.

    Raises:
        _VerifyFailed: when the read-back does not match.
    """
    stored, encoding = encode_original(content) if coded else (content, ENCODING_IDENTITY)
    ref = ctx.store.put(tenant, stored, media_type)
    if ref.sha256 != _sha256(stored) or _read_back(ctx.store, tenant, ref.sha256, encoding) != content:
        raise _VerifyFailed("the store copy did not read back identical")
    object_id = ctx.db.upsert_document_object(
        tenant_id=tenant,
        sha256=ref.sha256,
        size_bytes=ref.size_bytes,
        media_type=media_type,
        encoding=encoding,
        backend=ref.backend,
        storage_key=ref.key,
    )
    _mark_verified(ctx.db, object_id)
    return object_id, {
        "sha256": ref.sha256,
        "contentSha256": _sha256(content),
        "sizeBytes": len(content),
        "mediaType": media_type,
        "encoding": encoding,
    }


# ───────────────────────────── originals (adapter sources and import snapshots) ─────────────────────────────


@dataclass(frozen=True)
class _LegacyDocument:
    """A revision's database copy, shaped the way an import stores it.

    ``members`` is set for an archive (one entry per file, keyed by path, with ``root``);
    otherwise ``content`` is the single document's bytes.
    """

    content: bytes
    media_type: str
    members: Optional[Dict[str, bytes]] = None
    root: Optional[str] = None

    @property
    def size(self) -> int:
        """Bytes of the database copy."""
        return sum(len(data) for data in self.members.values()) if self.members else len(self.content)


def _adapter_document(row: Mapping[str, Any]) -> _LegacyDocument:
    """Build the document an adapter import kept in ``format_metadata``.

    A base64 archive (``intakeKind`` ``archive``) is unpacked into its files, as the import
    pipeline stores it; one that will not unpack is kept as text, which is how readers treat it.
    """
    text = str(row["content"])
    if row.get("intake_kind") == "archive" and row.get("source_encoding") == "base64":
        unpacked = legacy_fileset(text, row.get("fileset_root"))
        if unpacked is not None:
            members, root = unpacked
            return _LegacyDocument(
                content=text.encode("utf-8"), media_type=MANIFEST_MEDIA_TYPE, members=members, root=root
            )
    label = row.get("source_label") if isinstance(row.get("source_label"), str) else None
    return _LegacyDocument(content=text.encode("utf-8"), media_type=media_type_for(label, text))


def _snapshot_document(row: Mapping[str, Any]) -> _LegacyDocument:
    """Build the document the worker kept in ``version_import_snapshots.source_text``."""
    source_format = "json" if row.get("snapshot_format") == "json" else "yaml"
    return _LegacyDocument(content=str(row["content"]).encode("utf-8"), media_type=f"application/{source_format}")


_ORIGINAL_ROWS_SQL = """
    SELECT d.role, d.part_path, o.id::text AS object_id, o.sha256, o.size_bytes, o.media_type,
           o.encoding, o.backend
    FROM apiome.version_documents d
    JOIN apiome.document_objects o ON o.id = d.object_id
    WHERE d.version_id = %s::uuid AND o.tenant_id = %s
      AND d.role IN ('original', 'original_part')
    ORDER BY (d.role = 'original') DESC, d.part_path
"""


def _original_rows(ctx: _Context, tenant: str, version_id: str) -> List[Dict[str, Any]]:
    """The revision's ``original`` row (first) and ``original_part`` rows with their objects."""
    return [dict(row) for row in ctx.db.execute_query(_ORIGINAL_ROWS_SQL, (version_id, tenant))]


def _expected_original_sha(document: _LegacyDocument) -> str:
    """The SHA-256 the ``original`` object of ``document`` will have, computed without writing.

    For a fileset that is the digest of its (coded) manifest, built from the files' digests.
    """
    if not document.members:
        return _sha256(encode_original(document.content)[0])
    entries = [
        {"path": path, "sha256": _sha256(bytes(data)), "sizeBytes": len(data), "mediaType": media_type_for(path)}
        for path, data in sorted(document.members.items())
    ]
    return _sha256(encode_original(fileset_manifest(document.root, entries))[0])


def _store_document(
    ctx: _Context, tenant: str, document: _LegacyDocument
) -> Tuple[str, List[Tuple[str, str]], Dict[str, Any]]:
    """Write a document (or a fileset's parts and manifest) to the store, verified.

    Returns:
        ``(original_object_id, parts, pointer)``: the object to link as ``original``, the
        ``(part_path, object_id)`` pairs of a fileset, and the ``sourceDocument`` pointer.
    """
    if not document.members:
        object_id, pointer = _put_verified(ctx, tenant, document.content, document.media_type)
        return object_id, [], pointer
    parts: List[Tuple[str, str]] = []
    entries: List[Dict[str, Any]] = []
    for path in sorted(document.members):
        data = bytes(document.members[path])
        part_type = media_type_for(path)
        part_id, facts = _put_verified(ctx, tenant, data, part_type)
        parts.append((path, part_id))
        entries.append({"path": path, "sha256": facts["contentSha256"], "sizeBytes": len(data), "mediaType": part_type})
    object_id, pointer = _put_verified(ctx, tenant, fileset_manifest(document.root, entries), MANIFEST_MEDIA_TYPE)
    pointer["parts"] = len(parts)
    return object_id, parts, pointer


def _matches_store(
    ctx: _Context, tenant: str, rows: Sequence[Mapping[str, Any]], document: _LegacyDocument
) -> Optional[str]:
    """Check that the revision's stored original is exactly its database copy.

    Every object involved is read back from the current store and its digest checked.

    Args:
        ctx: The run context.
        tenant: The owning tenant.
        rows: :func:`_original_rows` of the revision.
        document: The database copy.

    Returns:
        ``None`` when they match, else why not (a short reason for the report).

    Raises:
        _VerifyFailed / DocumentStoreError: when an object cannot be read back intact.
    """
    original = next((row for row in rows if row["role"] == "original"), None)
    if original is None:
        return "no-original"
    if any(not ctx.in_store(row["backend"]) for row in rows):
        return "original-on-another-backend"
    content = _read_back(ctx.store, tenant, original["sha256"], original["encoding"])
    if not document.members:
        same = content == document.content and original["media_type"] != MANIFEST_MEDIA_TYPE
        return None if same else "original-differs"
    if original["media_type"] != MANIFEST_MEDIA_TYPE:
        return "original-differs"
    manifest = json.loads(content.decode("utf-8"))
    parts = {row["part_path"]: row for row in rows if row["role"] == "original_part"}
    if manifest.get("root") != document.root or set(parts) != set(document.members):
        return "original-differs"
    for path, data in document.members.items():
        if _read_back(ctx.store, tenant, parts[path]["sha256"], parts[path]["encoding"]) != bytes(data):
            return "original-differs"
    return None


def _pointer_from_rows(ctx: _Context, tenant: str, rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The ``sourceDocument`` pointer of an already stored original (for a purge that adds it)."""
    original = rows[0]
    content = _read_back(ctx.store, tenant, original["sha256"], original["encoding"])
    pointer: Dict[str, Any] = {
        "sha256": original["sha256"],
        "contentSha256": _sha256(content),
        "sizeBytes": len(content),
        "mediaType": original["media_type"],
        "encoding": original["encoding"],
    }
    parts = sum(1 for row in rows if row["role"] == "original_part")
    if parts:
        pointer["parts"] = parts
    return pointer


def _copy_original(
    ctx: _Context, tenant: str, version_id: str, document: _LegacyDocument
) -> Tuple[_Outcome, Optional[Dict[str, Any]]]:
    """Copy a revision's database copy into the store and link it as its original.

    A revision that already has an original keeps it: when that original is the same content on
    another backend, it is re-written to the current one; when it is different content, the row
    is skipped.

    Returns:
        ``(outcome, pointer)``; the pointer is ``None`` unless the original was linked.
    """
    existing = _original_rows(ctx, tenant, version_id)
    if existing and existing[0]["sha256"] != _expected_original_sha(document):
        return _Outcome(SKIPPED, document.size, "original-differs"), None
    if ctx.options.dry_run:
        return _Outcome(WOULD_COPY, document.size), None
    object_id, parts, pointer = _store_document(ctx, tenant, document)
    linked = ctx.db.set_version_original_documents(
        tenant_id=tenant, version_id=version_id, original_object_id=object_id, parts=parts, keep_existing=not existing
    )
    if not linked:
        return _Outcome(SKIPPED, document.size, "original-recorded-meanwhile"), None
    return _Outcome(COPIED, document.size), pointer


# — adapter sources —

_ADAPTER_ROW_SQL = """
    SELECT v.id::text AS key, p.tenant_id::text AS tenant_id,
           v.format_metadata ->> 'sourceContent' AS content,
           v.format_metadata ->> 'sourceEncoding' AS source_encoding,
           v.format_metadata ->> 'intakeKind' AS intake_kind,
           v.format_metadata ->> 'filesetRoot' AS fileset_root,
           v.format_metadata ->> 'sourceLabel' AS source_label
    FROM apiome.versions v
    JOIN apiome.projects p ON p.id = v.project_id
    WHERE v.id = %s::uuid
"""

# The content stamp is claimed in the same statement, so the BEFORE UPDATE trigger on versions
# does not bump it: the pointer and the dropped column change nothing a renderer reads.
_SET_POINTER_SQL = """
    WITH claim AS (SELECT apiome.claim_version_content_stamp(%s::uuid) AS claimed)
    UPDATE apiome.versions v
       SET format_metadata = coalesce(v.format_metadata, '{}'::jsonb)
                             || jsonb_build_object('sourceDocument', %s::jsonb)
      FROM claim
     WHERE v.id = %s::uuid
    RETURNING v.id
"""

_DROP_ADAPTER_COPY_SQL = """
    WITH claim AS (SELECT apiome.claim_version_content_stamp(%s::uuid) AS claimed)
    UPDATE apiome.versions v
       SET format_metadata = (v.format_metadata - 'sourceContent' - 'sourceEncoding')
                             || jsonb_build_object('sourceDocument', %s::jsonb)
      FROM claim
     WHERE v.id = %s::uuid
       AND encode(sha256(convert_to(v.format_metadata ->> 'sourceContent', 'UTF8')), 'hex') = %s
    RETURNING v.id
"""


def _adapter_row(ctx: _Context, key: str) -> Optional[Dict[str, Any]]:
    """Load one revision's adapter source, or ``None`` when it no longer has one."""
    row = _first(ctx.db, _ADAPTER_ROW_SQL, (key,))
    return row if row and isinstance(row.get("content"), str) and row["content"] else None


def _copy_adapter(ctx: _Context, key: str) -> _Outcome:
    """Copy step for ``format_metadata.sourceContent``: store, verify, link, point."""
    row = _adapter_row(ctx, key)
    if row is None:
        return _Outcome(SKIPPED, 0, "source-gone")
    outcome, pointer = _copy_original(ctx, row["tenant_id"], key, _adapter_document(row))
    if pointer is not None:
        ctx.db.execute_query(_SET_POINTER_SQL, (key, json.dumps(pointer), key))
    return outcome


def _purge_adapter(ctx: _Context, key: str) -> _Outcome:
    """Purge step for ``format_metadata.sourceContent``: verify the store copy, then drop the column."""
    row = _adapter_row(ctx, key)
    if row is None:
        return _Outcome(SKIPPED, 0, "source-gone")
    document = _adapter_document(row)
    rows = _original_rows(ctx, row["tenant_id"], key)
    reason = _matches_store(ctx, row["tenant_id"], rows, document)
    if reason:
        return _Outcome(SKIPPED, document.size, reason)
    if ctx.options.dry_run:
        return _Outcome(WOULD_PURGE, document.size)
    for item in rows:
        _mark_verified(ctx.db, item["object_id"])
    pointer = _pointer_from_rows(ctx, row["tenant_id"], rows)
    dropped = ctx.db.execute_query(
        _DROP_ADAPTER_COPY_SQL, (key, json.dumps(pointer), key, _sha256(row["content"].encode("utf-8")))
    )
    return _Outcome(PURGED, document.size) if dropped else _Outcome(SKIPPED, document.size, "source-changed")


# — import snapshots —

_SNAPSHOT_ROW_SQL = """
    SELECT s.version_id::text AS key, p.tenant_id::text AS tenant_id,
           s.source_text AS content, s.source_format AS snapshot_format
    FROM apiome.version_import_snapshots s
    JOIN apiome.versions v ON v.id = s.version_id
    JOIN apiome.projects p ON p.id = v.project_id AND p.tenant_id = s.tenant_id
    WHERE s.version_id = %s::uuid
"""

_DROP_SNAPSHOT_COPY_SQL = """
    UPDATE apiome.version_import_snapshots
       SET source_text = NULL
     WHERE version_id = %s::uuid
       AND encode(sha256(convert_to(source_text, 'UTF8')), 'hex') = %s
    RETURNING version_id
"""


def _snapshot_row(ctx: _Context, key: str) -> Optional[Dict[str, Any]]:
    """Load one import snapshot's text, or ``None`` when it no longer has any."""
    row = _first(ctx.db, _SNAPSHOT_ROW_SQL, (key,))
    return row if row and isinstance(row.get("content"), str) and row["content"] else None


def _copy_snapshot(ctx: _Context, key: str) -> _Outcome:
    """Copy step for ``version_import_snapshots.source_text``: store, verify, link."""
    row = _snapshot_row(ctx, key)
    if row is None:
        return _Outcome(SKIPPED, 0, "source-gone")
    outcome, _ = _copy_original(ctx, row["tenant_id"], key, _snapshot_document(row))
    return outcome


def _purge_snapshot(ctx: _Context, key: str) -> _Outcome:
    """Purge step for ``version_import_snapshots.source_text``: verify, then drop the text."""
    row = _snapshot_row(ctx, key)
    if row is None:
        return _Outcome(SKIPPED, 0, "source-gone")
    document = _snapshot_document(row)
    rows = _original_rows(ctx, row["tenant_id"], key)
    reason = _matches_store(ctx, row["tenant_id"], rows, document)
    if reason:
        return _Outcome(SKIPPED, document.size, reason)
    if ctx.options.dry_run:
        return _Outcome(WOULD_PURGE, document.size)
    for item in rows:
        _mark_verified(ctx.db, item["object_id"])
    dropped = ctx.db.execute_query(_DROP_SNAPSHOT_COPY_SQL, (key, _sha256(document.content)))
    return _Outcome(PURGED, document.size) if dropped else _Outcome(SKIPPED, document.size, "source-changed")


# ───────────────────────────── frozen schemas ─────────────────────────────

_FROZEN_ROW_SQL = """
    SELECT s.version_id::text AS key, p.tenant_id::text AS tenant_id, s.content, trim(s.sha256) AS sha256
    FROM apiome.version_spec_snapshots s
    JOIN apiome.versions v ON v.id = s.version_id
    JOIN apiome.projects p ON p.id = v.project_id
    WHERE s.version_id = %s::uuid AND s.content IS NOT NULL
"""

_FROZEN_LINK_SQL = """
    SELECT o.id::text AS object_id, o.sha256, o.encoding, o.backend
    FROM apiome.version_documents d
    JOIN apiome.document_objects o ON o.id = d.object_id
    WHERE d.version_id = %s::uuid AND d.role = 'frozen_schema' AND o.tenant_id = %s AND o.sha256 = %s
"""

_DROP_FROZEN_COPY_SQL = """
    UPDATE apiome.version_spec_snapshots SET content = NULL
     WHERE version_id = %s::uuid AND trim(sha256) = %s AND content IS NOT NULL
    RETURNING version_id
"""


def _copy_frozen(ctx: _Context, key: str) -> _Outcome:
    """Copy step for ``version_spec_snapshots.content``: store as-is, verify, link ``frozen_schema``."""
    row = _first(ctx.db, _FROZEN_ROW_SQL, (key,))
    if row is None:
        return _Outcome(SKIPPED, 0, "source-gone")
    content = _as_bytes(row["content"])
    if _sha256(content) != row["sha256"]:
        return _Outcome(FAILED, len(content), "database-copy-digest-mismatch")
    if ctx.options.dry_run:
        return _Outcome(WOULD_COPY, len(content))
    object_id, _ = _put_verified(ctx, row["tenant_id"], content, _FROZEN_MEDIA_TYPE, coded=False)
    linked = ctx.db.set_version_document(
        tenant_id=row["tenant_id"], version_id=key, role="frozen_schema", object_id=object_id
    )
    return _Outcome(COPIED, len(content)) if linked else _Outcome(SKIPPED, len(content), "revision-not-linked")


def _purge_frozen(ctx: _Context, key: str) -> _Outcome:
    """Purge step for ``version_spec_snapshots.content``: verify the object, then drop the bytes."""
    row = _first(ctx.db, _FROZEN_ROW_SQL, (key,))
    if row is None:
        return _Outcome(SKIPPED, 0, "source-gone")
    content = _as_bytes(row["content"])
    link = _first(ctx.db, _FROZEN_LINK_SQL, (key, row["tenant_id"], row["sha256"]))
    if link is None:
        return _Outcome(SKIPPED, len(content), "not-copied")
    if not ctx.in_store(link["backend"]):
        return _Outcome(SKIPPED, len(content), "object-on-another-backend")
    if _read_back(ctx.store, row["tenant_id"], link["sha256"], link["encoding"]) != content:
        return _Outcome(SKIPPED, len(content), "object-differs")
    if ctx.options.dry_run:
        return _Outcome(WOULD_PURGE, len(content))
    _mark_verified(ctx.db, link["object_id"])
    dropped = ctx.db.execute_query(_DROP_FROZEN_COPY_SQL, (key, row["sha256"]))
    return _Outcome(PURGED, len(content)) if dropped else _Outcome(SKIPPED, len(content), "source-changed")


# ───────────────────────────── export artifacts ─────────────────────────────

_EXPORT_ROW_SQL = """
    SELECT job_id AS key, tenant_slug, content, content_sha256, media_type, storage_uri
    FROM apiome.export_job_artifact
    WHERE job_id = %s AND backend = 'db' AND content IS NOT NULL AND reaped_at IS NULL
"""

_SET_EXPORT_URI_SQL = """
    UPDATE apiome.export_job_artifact SET storage_uri = %s
     WHERE job_id = %s AND backend = 'db' AND content IS NOT NULL AND storage_uri IS NULL
    RETURNING job_id
"""

_DROP_EXPORT_COPY_SQL = """
    UPDATE apiome.export_job_artifact SET backend = 'object_store', content = NULL
     WHERE job_id = %s AND backend = 'db' AND storage_uri = %s AND content_sha256 = %s
    RETURNING job_id
"""


def _copy_export(ctx: _Context, key: str) -> _Outcome:
    """Copy step for ``export_job_artifact.content``: store, verify, record ``storage_uri``.

    The row stays on the ``db`` backend (it still serves its own bytes) until the purge step.
    Export artifacts are stored under the tenant slug, as the object-store backend writes them.
    """
    row = _first(ctx.db, _EXPORT_ROW_SQL, (key,))
    if row is None:
        return _Outcome(SKIPPED, 0, "source-gone")
    content = _as_bytes(row["content"])
    if content_sha256_hex(content) != row["content_sha256"]:
        return _Outcome(FAILED, len(content), "database-copy-digest-mismatch")
    if ctx.options.dry_run:
        return _Outcome(WOULD_COPY, len(content))
    ref = ctx.store.put(row["tenant_slug"], content, row["media_type"])
    if _read_back(ctx.store, row["tenant_slug"], ref.sha256, ENCODING_IDENTITY) != content:
        raise _VerifyFailed("the store copy did not read back identical")
    recorded = ctx.db.execute_query(_SET_EXPORT_URI_SQL, (ref.uri, key))
    return _Outcome(COPIED, len(content)) if recorded else _Outcome(SKIPPED, len(content), "artifact-changed")


def _purge_export(ctx: _Context, key: str) -> _Outcome:
    """Purge step for ``export_job_artifact.content``: verify the object, then switch the row over."""
    row = _first(ctx.db, _EXPORT_ROW_SQL, (key,))
    if row is None:
        return _Outcome(SKIPPED, 0, "source-gone")
    content = _as_bytes(row["content"])
    if not row.get("storage_uri"):
        return _Outcome(SKIPPED, len(content), "not-copied")
    tenant, sha256 = parse_object_uri(str(row["storage_uri"]))
    if tenant != row["tenant_slug"] or _sha256(content) != sha256:
        return _Outcome(SKIPPED, len(content), "object-differs")
    if _read_back(ctx.store, tenant, sha256, ENCODING_IDENTITY) != content:
        return _Outcome(SKIPPED, len(content), "object-differs")
    if ctx.options.dry_run:
        return _Outcome(WOULD_PURGE, len(content))
    dropped = ctx.db.execute_query(_DROP_EXPORT_COPY_SQL, (key, row["storage_uri"], row["content_sha256"]))
    return _Outcome(PURGED, len(content)) if dropped else _Outcome(SKIPPED, len(content), "artifact-changed")


# ───────────────────────────── candidate queries ─────────────────────────────

# Each query returns the next page of keys after %(after)s that the step still has to do, so a
# finished row is never selected again. %(backend)s is the current store's backend: an original
# on another backend (written before a backend change) still needs copying. An object in its
# tenant's own bucket ('tenant_s3', COA-5.15) is in the current store too.
_HAS_ORIGINAL_HERE = """
    EXISTS (SELECT 1 FROM apiome.version_documents d
            JOIN apiome.document_objects o ON o.id = d.object_id
            WHERE d.version_id = {version} AND d.role = 'original' AND o.backend IN (%(backend)s, 'tenant_s3'))
"""

_CANDIDATES: Dict[Tuple[str, str], str] = {
    (ADAPTER_SOURCE, STEP_COPY): """
        SELECT v.id::text AS key FROM apiome.versions v JOIN apiome.projects p ON p.id = v.project_id
        WHERE coalesce(v.format_metadata ->> 'sourceContent', '') <> ''
          AND NOT {has_original}
          AND (%(tenant)s::text IS NULL OR p.tenant_id::text = %(tenant)s)
          AND v.id::text COLLATE "C" > %(after)s
        ORDER BY v.id::text COLLATE "C" LIMIT %(limit)s
    """,
    (ADAPTER_SOURCE, STEP_PURGE): """
        SELECT v.id::text AS key FROM apiome.versions v JOIN apiome.projects p ON p.id = v.project_id
        WHERE coalesce(v.format_metadata ->> 'sourceContent', '') <> ''
          AND {has_original}
          AND (%(tenant)s::text IS NULL OR p.tenant_id::text = %(tenant)s)
          AND v.id::text COLLATE "C" > %(after)s
        ORDER BY v.id::text COLLATE "C" LIMIT %(limit)s
    """,
    (IMPORT_SNAPSHOT, STEP_COPY): """
        SELECT s.version_id::text AS key FROM apiome.version_import_snapshots s
        WHERE coalesce(s.source_text, '') <> ''
          AND NOT {has_original}
          AND (%(tenant)s::text IS NULL OR s.tenant_id::text = %(tenant)s)
          AND s.version_id::text COLLATE "C" > %(after)s
        ORDER BY s.version_id::text COLLATE "C" LIMIT %(limit)s
    """,
    (IMPORT_SNAPSHOT, STEP_PURGE): """
        SELECT s.version_id::text AS key FROM apiome.version_import_snapshots s
        WHERE coalesce(s.source_text, '') <> ''
          AND {has_original}
          AND (%(tenant)s::text IS NULL OR s.tenant_id::text = %(tenant)s)
          AND s.version_id::text COLLATE "C" > %(after)s
        ORDER BY s.version_id::text COLLATE "C" LIMIT %(limit)s
    """,
    (FROZEN_SCHEMA, STEP_COPY): """
        SELECT s.version_id::text AS key FROM apiome.version_spec_snapshots s
        JOIN apiome.versions v ON v.id = s.version_id JOIN apiome.projects p ON p.id = v.project_id
        WHERE s.content IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM apiome.version_documents d
                          JOIN apiome.document_objects o ON o.id = d.object_id
                          WHERE d.version_id = s.version_id AND d.role = 'frozen_schema'
                            AND o.sha256 = trim(s.sha256) AND o.backend IN (%(backend)s, 'tenant_s3'))
          AND (%(tenant)s::text IS NULL OR p.tenant_id::text = %(tenant)s)
          AND s.version_id::text COLLATE "C" > %(after)s
        ORDER BY s.version_id::text COLLATE "C" LIMIT %(limit)s
    """,
    (FROZEN_SCHEMA, STEP_PURGE): """
        SELECT s.version_id::text AS key FROM apiome.version_spec_snapshots s
        JOIN apiome.versions v ON v.id = s.version_id JOIN apiome.projects p ON p.id = v.project_id
        WHERE s.content IS NOT NULL
          AND EXISTS (SELECT 1 FROM apiome.version_documents d
                      JOIN apiome.document_objects o ON o.id = d.object_id
                      WHERE d.version_id = s.version_id AND d.role = 'frozen_schema'
                        AND o.sha256 = trim(s.sha256) AND o.backend IN (%(backend)s, 'tenant_s3'))
          AND (%(tenant)s::text IS NULL OR p.tenant_id::text = %(tenant)s)
          AND s.version_id::text COLLATE "C" > %(after)s
        ORDER BY s.version_id::text COLLATE "C" LIMIT %(limit)s
    """,
    (EXPORT_ARTIFACT, STEP_COPY): """
        SELECT a.job_id AS key FROM apiome.export_job_artifact a
        WHERE a.backend = 'db' AND a.content IS NOT NULL AND a.storage_uri IS NULL
          AND a.reaped_at IS NULL AND (a.expires_at IS NULL OR a.expires_at > now())
          AND (%(tenant)s::text IS NULL
               OR a.tenant_slug = (SELECT t.slug FROM apiome.tenants t WHERE t.id::text = %(tenant)s))
          AND a.job_id COLLATE "C" > %(after)s
        ORDER BY a.job_id COLLATE "C" LIMIT %(limit)s
    """,
    (EXPORT_ARTIFACT, STEP_PURGE): """
        SELECT a.job_id AS key FROM apiome.export_job_artifact a
        WHERE a.backend = 'db' AND a.content IS NOT NULL AND a.storage_uri IS NOT NULL
          AND a.reaped_at IS NULL
          AND (%(tenant)s::text IS NULL
               OR a.tenant_slug = (SELECT t.slug FROM apiome.tenants t WHERE t.id::text = %(tenant)s))
          AND a.job_id COLLATE "C" > %(after)s
        ORDER BY a.job_id COLLATE "C" LIMIT %(limit)s
    """,
}

_VERSION_COLUMN = {ADAPTER_SOURCE: "v.id", IMPORT_SNAPSHOT: "s.version_id"}

_HANDLERS: Dict[Tuple[str, str], Callable[[_Context, str], _Outcome]] = {
    (ADAPTER_SOURCE, STEP_COPY): _copy_adapter,
    (ADAPTER_SOURCE, STEP_PURGE): _purge_adapter,
    (IMPORT_SNAPSHOT, STEP_COPY): _copy_snapshot,
    (IMPORT_SNAPSHOT, STEP_PURGE): _purge_snapshot,
    (FROZEN_SCHEMA, STEP_COPY): _copy_frozen,
    (FROZEN_SCHEMA, STEP_PURGE): _purge_frozen,
    (EXPORT_ARTIFACT, STEP_COPY): _copy_export,
    (EXPORT_ARTIFACT, STEP_PURGE): _purge_export,
}


def _candidate_sql(source: str, step: str) -> str:
    """The page query of a source's step, with the "has an original here" clause filled in."""
    sql = _CANDIDATES[(source, step)]
    if source in _VERSION_COLUMN:
        sql = sql.replace("{has_original}", _HAS_ORIGINAL_HERE.format(version=_VERSION_COLUMN[source]))
    return sql


def _next_keys(ctx: _Context, source: str, after: str) -> List[str]:
    """The next page of keys the step still has to do, after ``after``."""
    rows = ctx.db.execute_query(
        _candidate_sql(source, ctx.options.step),
        {"backend": ctx.backend, "tenant": ctx.options.tenant_id, "after": after, "limit": ctx.options.batch_size},
    )
    return [str(row["key"]) for row in rows]


# ───────────────────────────── checkpoints (V405) ─────────────────────────────


def _load_checkpoint(db: Any, scope: str, step: str, source: str) -> Optional[Dict[str, Any]]:
    """The checkpoint row of (scope, step, source), or ``None``."""
    return _first(
        db,
        "SELECT last_key, counts, completed_at FROM apiome.document_migration_checkpoints "
        "WHERE scope = %s AND step = %s AND source = %s",
        (scope, step, source),
    )


def _start_checkpoint(db: Any, scope: str, step: str, source: str) -> Tuple[str, Optional[str]]:
    """Begin a step for a source: resume an unfinished checkpoint, or restart a finished one.

    Returns:
        ``(after, resumed_after)``: the key to start after (``""`` from the beginning), and the
        same key when the run resumes (``None`` when it starts over).
    """
    row = _load_checkpoint(db, scope, step, source)
    if row is not None and row.get("completed_at") is None and row.get("last_key"):
        return str(row["last_key"]), str(row["last_key"])
    db.execute_query(
        """
        INSERT INTO apiome.document_migration_checkpoints (scope, step, source)
        VALUES (%s, %s, %s)
        ON CONFLICT (scope, step, source) DO UPDATE
            SET last_key = NULL, counts = '{}'::jsonb, started_at = now(), updated_at = now(),
                completed_at = NULL
        RETURNING scope
        """,
        (scope, step, source),
    )
    return "", None


def _save_checkpoint(
    db: Any, scope: str, step: str, source: str, last_key: Optional[str], counts: Mapping[str, int], completed: bool
) -> None:
    """Record how far a step got, adding this batch's ``counts`` to the stored totals."""
    db.execute_query(
        """
        UPDATE apiome.document_migration_checkpoints
           SET last_key = coalesce(%s, last_key),
               counts = (SELECT coalesce(jsonb_object_agg(k, coalesce((counts ->> k)::bigint, 0)
                                                         + coalesce((%s::jsonb ->> k)::bigint, 0)), '{}'::jsonb)
                         FROM (SELECT jsonb_object_keys(counts || %s::jsonb) AS k) keys),
               updated_at = now(),
               completed_at = CASE WHEN %s THEN now() ELSE NULL END
         WHERE scope = %s AND step = %s AND source = %s
        RETURNING scope
        """,
        (last_key, json.dumps(dict(counts)), json.dumps(dict(counts)), completed, scope, step, source),
    )


def list_checkpoints(db: Any) -> List[Dict[str, Any]]:
    """Every checkpoint row, for the ops status endpoint.

    Returns:
        Rows of ``scope``, ``step``, ``source``, ``last_key``, ``counts``, ``started_at``,
        ``updated_at`` and ``completed_at`` (timestamps as ISO 8601 strings).
    """
    rows = db.execute_query(
        """
        SELECT scope, step, source, last_key, counts, started_at, updated_at, completed_at
        FROM apiome.document_migration_checkpoints
        ORDER BY scope, step, array_position(ARRAY['adapter_source', 'import_snapshot',
                                                   'frozen_schema', 'export_artifact'], source)
        """
    )
    out = []
    for row in rows:
        item = dict(row)
        for name in ("started_at", "updated_at", "completed_at"):
            if item.get(name) is not None and hasattr(item[name], "isoformat"):
                item[name] = item[name].isoformat()
        out.append(item)
    return out


# ───────────────────────────── the run ─────────────────────────────


def _process(ctx: _Context, source: str, key: str, limiter: RateLimiter) -> _Outcome:
    """Run one row's handler under the rate limit; a failure becomes a ``failed`` outcome."""
    limiter.wait()
    try:
        return _HANDLERS[(source, ctx.options.step)](ctx, key)
    except _VerifyFailed as exc:
        return _Outcome(FAILED, 0, f"verify: {exc}")
    except Exception as exc:  # noqa: BLE001 - one bad row must not stop the run; it keeps its copy
        logger.warning("document migration %s %s failed: %s", source, key, type(exc).__name__)
        return _Outcome(FAILED, 0, type(exc).__name__)


def _run_source(
    ctx: _Context,
    source: str,
    report: MigrationReport,
    limiter: RateLimiter,
    pool: Optional[ThreadPoolExecutor],
) -> None:
    """Walk one source page by page, checkpointing after each page (except in a dry run)."""
    options = ctx.options
    totals = report.sources.setdefault(source, SourceTotals())
    if source == EXPORT_ARTIFACT and ctx.backend == BACKEND_DB:
        totals.note = "export artifacts move only to an s3 or filesystem store"
        totals.completed = True
        return
    after = ""
    if not options.dry_run:
        after, totals.resumed_after = _start_checkpoint(ctx.db, options.scope, options.step, source)
    while True:
        keys = _next_keys(ctx, source, after)
        if not keys:
            break
        if pool is not None:
            outcomes = list(pool.map(lambda key: _process(ctx, source, key, limiter), keys))
        else:
            outcomes = [_process(ctx, source, key, limiter) for key in keys]
        batch: Dict[str, int] = {}
        for key, outcome in zip(keys, outcomes):
            totals.add(outcome.status, outcome.size)
            batch["scanned"] = batch.get("scanned", 0) + 1
            batch[outcome.status] = batch.get(outcome.status, 0) + 1
            batch["bytes"] = batch.get("bytes", 0) + outcome.size
            if outcome.status in (SKIPPED, FAILED):
                report.note_row(source, key, outcome.status, outcome.detail)
        after = keys[-1]
        if not options.dry_run:
            _save_checkpoint(ctx.db, options.scope, options.step, source, after, batch, completed=False)
        logger.info("document migration %s %s: %d rows, up to %s", options.step, source, len(keys), after)
    totals.completed = True
    if not options.dry_run:
        _save_checkpoint(ctx.db, options.scope, options.step, source, None, {}, completed=True)


def _try_lock(db: Any) -> bool:
    """Take the run's session advisory lock; ``False`` when another run holds it."""
    rows = db.execute_query("SELECT pg_try_advisory_lock(hashtext(%s)) AS locked", (_LOCK_KEY,))
    return bool(rows and rows[0].get("locked"))


def _unlock(db: Any) -> None:
    """Release the run's session advisory lock."""
    db.execute_query("SELECT pg_advisory_unlock(hashtext(%s)) AS unlocked", (_LOCK_KEY,))


def check_options(store: Any, options: MigrationOptions) -> MigrationOptions:
    """Validate a run before starting it.

    Args:
        store: The document store the run would write to.
        options: The requested run.

    Returns:
        The options with the knobs clamped.

    Raises:
        MigrationRefused: for an unknown source, or a purge on the ``db`` backend (the database
            copies are the ``db`` backend's design, and its objects live in the same database).
    """
    checked = options.validated()
    if checked.purge_db_copies and str(getattr(store, "backend", BACKEND_DB)) == BACKEND_DB:
        raise MigrationRefused(
            "--purge-db-copies needs an s3 or filesystem document store: with APIOME_DOCUMENT_STORE=db "
            "the database copies are kept by design."
        )
    return checked


def run_document_migration(
    db: Any,
    store: Any,
    options: MigrationOptions,
    *,
    limiter: Optional[RateLimiter] = None,
) -> MigrationReport:
    """Run one step of the migration over every requested source.

    Args:
        db: The database layer (``execute_query`` plus the document-object writers).
        store: The document store to copy into (the process-wide one in production).
        options: What to do.
        limiter: The rate limiter; one built from ``options.rate`` when omitted.

    Returns:
        The report. Failed rows are counted and listed; they never raise.

    Raises:
        MigrationRefused: when :func:`check_options` refuses the run.
        MigrationBusy: when another non-dry run holds the lock.
    """
    options = check_options(store, options)
    ctx = _Context(db=db, store=store, options=options)
    report = MigrationReport(step=options.step, dry_run=options.dry_run, backend=ctx.backend, scope=options.scope)
    limiter = limiter or RateLimiter(options.rate)
    locked = False
    if not options.dry_run:
        if not _try_lock(db):
            raise MigrationBusy("Another document migration run is in progress.")
        locked = True
    pool = ThreadPoolExecutor(max_workers=options.workers) if options.workers > 1 else None
    try:
        for source in options.sources:
            _run_source(ctx, source, report, limiter, pool)
    finally:
        if pool is not None:
            pool.shutdown(wait=True)
        if locked:
            _unlock(db)
        report.finished_at = time.time()
    return report
