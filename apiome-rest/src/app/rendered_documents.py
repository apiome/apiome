"""Rendered documents of a revision, cached in the document store (COA-5.5, #7081).

A revision's OpenAPI document is generated from its normalized rows: classes, properties, paths,
servers, security schemes and pins. Generating it reads every one of those rows, so a large
revision is slow to render. This module renders a document once and keeps the bytes:

* :func:`rendered_document` returns a revision's document of one kind (:data:`KIND_OPENAPI`,
  :data:`KIND_OPENAPI_MEMBERS` or :data:`KIND_CANONICAL`). It looks the document up in
  ``version_documents`` by revision, role, content stamp, generator and generator version. On a
  miss it renders, writes the bytes to the document store (:mod:`app.document_store`), records
  them, and returns them.
* The **content stamp** (``versions.content_stamp``, COA-5.2) moves on every edit of the
  revision, so an edited revision misses and is rendered again. The earlier row and object are
  left in place for the lifecycle job (COA-5.10).
* The OpenAPI document also names the project (slug, description, metadata), which the stamp does
  not cover. A digest of those three values is part of the recorded generator version
  (``<version>+<digest>``), so a project rename misses too.
* A **generator version** bump (:data:`OPENAPI_GENERATOR_VERSION`) changes the key. Nothing is
  deleted; older rows simply stop matching.
* Renders are **single-flight** per key inside a worker: concurrent requests for the same
  document wait for one render. Two workers can still render the same key at once. That is
  harmless, because the bytes are the same object and the row is an upsert.
* The cache never fails a read. When the store or the database cannot keep the document, the
  rendered bytes are returned without being recorded.

There are two OpenAPI kinds (COA-5.13, #7089). :data:`KIND_OPENAPI` is the public document
``GET /v1/schema`` serves: OpenAPI 3.1, without the operations marked ``x-private``.
:data:`KIND_OPENAPI_MEMBERS` is the document the UI shows a workspace member
(``GET /v1/versions/…/document``): OpenAPI 3.2, with those operations kept. Each has its own
``version_documents`` role, so the lifecycle job never treats one as a stale copy of the other.

Frozen schemas (#3214) use the same store: :func:`store_frozen_schema` writes a frozen version's
bytes as its ``frozen_schema`` object and :func:`open_frozen_schema` reads them back.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Callable, Dict, Iterator, Mapping, Optional, Tuple, Union

from .document_store import get_document_store
from .original_documents import ENCODING_IDENTITY
from .spec_snapshot import build_live_spec, render_spec_bytes, sha256_hex

logger = logging.getLogger(__name__)

__all__ = [
    "CANONICAL_GENERATOR",
    "CANONICAL_GENERATOR_VERSION",
    "KIND_CANONICAL",
    "KIND_OPENAPI",
    "KIND_OPENAPI_MEMBERS",
    "MEMBERS_OPENAPI_VERSION",
    "MEDIA_TYPE",
    "OPENAPI_GENERATOR",
    "OPENAPI_GENERATOR_VERSION",
    "ROLE_FROZEN_SCHEMA",
    "ROLE_RENDERED_CANONICAL",
    "ROLE_RENDERED_OPENAPI",
    "ROLE_RENDERED_OPENAPI_MEMBERS",
    "RenderedDocument",
    "etag_for",
    "etag_matches",
    "iter_stream",
    "open_frozen_schema",
    "rendered_document",
    "store_frozen_schema",
    "warm_rendered_documents",
]

#: The document kinds :func:`rendered_document` renders.
KIND_OPENAPI = "openapi"
KIND_OPENAPI_MEMBERS = "openapi_members"
KIND_CANONICAL = "canonical"

#: ``version_documents.role`` values written here.
ROLE_RENDERED_OPENAPI = "rendered_openapi"
ROLE_RENDERED_OPENAPI_MEMBERS = "rendered_openapi_members"
ROLE_RENDERED_CANONICAL = "rendered_canonical"
ROLE_FROZEN_SCHEMA = "frozen_schema"

#: Generator names and versions recorded with a rendered row. Bump a version whenever the
#: generator's output for unchanged rows changes; rows of the old version then stop matching.
OPENAPI_GENERATOR = "apiome-openapi"
#: Version 2 (COA-5.13, #7089): property descriptions from the row's column, ``operationId``,
#: every security scheme type, a parent's ``required`` flag on an object property with children,
#: and no ``type: object`` forced on a composed schema.
OPENAPI_GENERATOR_VERSION = "2"
#: The OpenAPI version the members' document declares (the UI's studio export version).
MEMBERS_OPENAPI_VERSION = "3.2.0"
CANONICAL_GENERATOR = "apiome-canonical"
CANONICAL_GENERATOR_VERSION = "1"

#: Every rendered document is compact UTF-8 JSON, stored without a content coding so the object's
#: SHA-256 is the digest of the bytes a client receives.
MEDIA_TYPE = "application/json"

_STREAM_CHUNK_BYTES = 64 * 1024
_CONTEXT_DIGEST_CHARS = 16


@dataclass(frozen=True)
class RenderedDocument:
    """One rendered document of a revision.

    Attributes:
        tenant_id: The owning tenant.
        version_id: The revision (``versions.id``).
        kind: :data:`KIND_OPENAPI`, :data:`KIND_OPENAPI_MEMBERS` or :data:`KIND_CANONICAL`.
        sha256: Lower-case hex SHA-256 of the document's bytes; also its object identity.
        size_bytes: Length of the document.
        content_stamp: The revision's content stamp the document was rendered at.
        generator: The generator recorded with the document.
        generator_version: Its recorded version (for OpenAPI, ``<version>+<project digest>``).
        cached: ``True`` when the bytes came from the store; ``False`` when this call rendered them.
        stored: ``True`` when the store holds the bytes and the row is recorded.
    """

    tenant_id: str
    version_id: str
    kind: str
    sha256: str
    size_bytes: int
    content_stamp: int
    generator: str
    generator_version: str
    cached: bool
    stored: bool
    media_type: str = MEDIA_TYPE
    _content: Optional[bytes] = field(default=None, repr=False, compare=False)
    _store: Any = field(default=None, repr=False, compare=False)

    @property
    def etag(self) -> str:
        """The strong HTTP entity tag of the document: its quoted SHA-256."""
        return etag_for(self.sha256)

    def open_stream(self) -> BinaryIO:
        """Return a readable binary stream of the document; the caller closes it.

        Raises:
            DocumentNotFound: if the stored object was removed after the lookup.
        """
        if self._content is not None:
            return io.BytesIO(self._content)
        return self._store.open_stream(self.tenant_id, self.sha256)

    def content(self) -> bytes:
        """Return the whole document."""
        if self._content is not None:
            return self._content
        with self.open_stream() as stream:
            return stream.read()

    def json(self) -> Any:
        """Return the document parsed from JSON."""
        return json.loads(self.content().decode("utf-8"))


@dataclass(frozen=True)
class _Kind:
    """How one document kind is keyed and rendered."""

    role: str
    generator: str
    generator_version: Callable[[Mapping[str, Any]], str]
    render: Callable[[Any, str, Mapping[str, Any]], Optional[bytes]]


class _SingleFlight:
    """One lock per key, so concurrent callers of the same key run one at a time."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._entries: Dict[Tuple[Any, ...], Tuple[threading.Lock, int]] = {}

    @contextmanager
    def hold(self, key: Tuple[Any, ...]) -> Iterator[None]:
        """Hold the lock of ``key``; the entry is dropped when its last holder leaves."""
        with self._guard:
            lock, users = self._entries.get(key, (threading.Lock(), 0))
            self._entries[key] = (lock, users + 1)
        try:
            with lock:
                yield
        finally:
            with self._guard:
                lock, users = self._entries[key]
                if users <= 1:
                    del self._entries[key]
                else:
                    self._entries[key] = (lock, users - 1)


_flights = _SingleFlight()


# ───────────────────────────── HTTP validators ─────────────────────────────


def etag_for(sha256: str) -> str:
    """Return the strong entity tag for a document digest: ``"<sha256>"``."""
    return f'"{str(sha256).strip()}"'


def etag_matches(if_none_match: Optional[str], sha256: str) -> bool:
    """Report whether an ``If-None-Match`` header matches a document digest.

    Uses the weak comparison RFC 9110 prescribes for ``If-None-Match``: a ``W/`` prefix is
    ignored, the header may list several tags, and ``*`` matches any current document.

    Args:
        if_none_match: The header value, if the request sent one.
        sha256: The current document's SHA-256.

    Returns:
        ``True`` when the client already holds the current document.
    """
    if not if_none_match:
        return False
    current = str(sha256).strip().lower()
    for candidate in if_none_match.split(","):
        tag = candidate.strip()
        if tag == "*":
            return True
        if tag[:2] in ("W/", "w/"):
            tag = tag[2:]
        if len(tag) >= 2 and tag[0] == '"' and tag[-1] == '"' and tag[1:-1].lower() == current:
            return True
    return False


def iter_stream(stream: BinaryIO, chunk_bytes: int = _STREAM_CHUNK_BYTES) -> Iterator[bytes]:
    """Yield a stream in chunks and close it when done (or when the consumer stops early).

    Args:
        stream: A readable binary stream.
        chunk_bytes: Size of each chunk.

    Yields:
        The stream's bytes, in order.
    """
    try:
        while True:
            chunk = stream.read(chunk_bytes)
            if not chunk:
                return
            yield chunk
    finally:
        stream.close()


# ───────────────────────────── kinds ─────────────────────────────


def _openapi_generator_version(context: Mapping[str, Any]) -> str:
    """The OpenAPI generator version plus a digest of the project values the document names."""
    project = json.dumps(
        [context.get("project_slug"), context.get("project_description"), context.get("project_metadata")],
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    digest = hashlib.sha256(project.encode("utf-8")).hexdigest()[:_CONTEXT_DIGEST_CHARS]
    return f"{OPENAPI_GENERATOR_VERSION}+{digest}"


def _render_openapi(database: Any, tenant_id: str, context: Mapping[str, Any]) -> Optional[bytes]:
    """Generate the revision's OpenAPI document: the bytes ``GET /v1/schema`` sends."""
    spec, _counts = build_live_spec(
        database,
        context,
        str(context.get("tenant_slug") or ""),
        str(context.get("project_slug") or ""),
        str(context.get("version_id") or ""),
    )
    return render_spec_bytes(spec)


def _members_generator_version(context: Mapping[str, Any]) -> str:
    """The members' document version: the generator's, the OpenAPI version, the project digest."""
    return f"{MEMBERS_OPENAPI_VERSION}+{_openapi_generator_version(context)}"


def _render_openapi_members(database: Any, tenant_id: str, context: Mapping[str, Any]) -> Optional[bytes]:
    """Generate the document a workspace member reads: OpenAPI 3.2, private operations kept."""
    spec, _counts = build_live_spec(
        database,
        context,
        str(context.get("tenant_slug") or ""),
        str(context.get("project_slug") or ""),
        str(context.get("version_id") or ""),
        openapi_version=MEMBERS_OPENAPI_VERSION,
        include_private=True,
    )
    return render_spec_bytes(spec)


def _render_canonical(database: Any, tenant_id: str, context: Mapping[str, Any]) -> Optional[bytes]:
    """Serialize the revision's canonical model; ``None`` when it has no canonical artifact."""
    from .canonical_persistence import dump_canonical_tree  # noqa: PLC0415 - heavy, rarely needed

    model = database.load_canonical_api(tenant_id=tenant_id, version_id=str(context["id"]))
    if model is None:
        return None
    return json.dumps(
        dump_canonical_tree(model), sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


_KINDS: Dict[str, _Kind] = {
    KIND_OPENAPI: _Kind(ROLE_RENDERED_OPENAPI, OPENAPI_GENERATOR, _openapi_generator_version, _render_openapi),
    KIND_OPENAPI_MEMBERS: _Kind(
        ROLE_RENDERED_OPENAPI_MEMBERS, OPENAPI_GENERATOR, _members_generator_version, _render_openapi_members
    ),
    KIND_CANONICAL: _Kind(
        ROLE_RENDERED_CANONICAL,
        CANONICAL_GENERATOR,
        lambda _context: CANONICAL_GENERATOR_VERSION,
        _render_canonical,
    ),
}


#: The kinds rendered when a revision is published. The members' document is rendered when a
#: member first opens it, so publishing does not pay for a document nobody may read.
_WARMED_KINDS: Tuple[str, ...] = (KIND_OPENAPI, KIND_CANONICAL)


# ───────────────────────────── store access ─────────────────────────────


def _database(database: Any) -> Any:
    """Return the database layer to use, defaulting to the process-wide one."""
    if database is None:
        from .database import db as database  # noqa: PLC0415 - avoid an import cycle at load
    return database


def _store(store: Any) -> Any:
    """Return the document store to use, or ``None`` when it cannot be built."""
    if store is not None:
        return store
    try:
        return get_document_store()
    except Exception as exc:  # noqa: BLE001 - a misconfigured store must not fail a read
        logger.warning("document store unavailable: %s", type(exc).__name__)
        return None


def _put(database: Any, store: Any, tenant_id: str, content: bytes) -> str:
    """Write a JSON document to the store and record it; return its ``document_objects.id``."""
    ref = store.put(tenant_id, content, MEDIA_TYPE)
    return database.upsert_document_object(
        tenant_id=tenant_id,
        sha256=ref.sha256,
        size_bytes=ref.size_bytes,
        media_type=MEDIA_TYPE,
        encoding=ENCODING_IDENTITY,
        backend=ref.backend,
        storage_key=ref.key,
    )


def _lookup(
    database: Any,
    store: Any,
    tenant_id: str,
    kind: str,
    spec: _Kind,
    context: Mapping[str, Any],
    generator_version: str,
) -> Optional[RenderedDocument]:
    """Return the stored document of a key, or ``None`` when there is none to serve."""
    if store is None:
        return None
    try:
        row = database.find_version_document(
            tenant_id=tenant_id,
            version_id=str(context["id"]),
            role=spec.role,
            content_stamp=int(context["content_stamp"]),
            generator=spec.generator,
            generator_version=generator_version,
        )
        if not row or (row.get("encoding") or ENCODING_IDENTITY) != ENCODING_IDENTITY:
            return None
        # The row can outlive its object (a pruned bucket); such a document is rendered again.
        if not store.exists(tenant_id, row["sha256"]):
            return None
    except Exception as exc:  # noqa: BLE001 - an unreadable cache is a miss
        logger.warning("rendered document lookup failed version_id=%s: %s", context["id"], type(exc).__name__)
        return None
    return RenderedDocument(
        tenant_id=tenant_id,
        version_id=str(context["id"]),
        kind=kind,
        sha256=str(row["sha256"]),
        size_bytes=int(row["size_bytes"]),
        content_stamp=int(context["content_stamp"]),
        generator=spec.generator,
        generator_version=generator_version,
        cached=True,
        stored=True,
        _store=store,
    )


def _record(
    database: Any,
    store: Any,
    tenant_id: str,
    kind: str,
    spec: _Kind,
    context: Mapping[str, Any],
    generator_version: str,
    content: bytes,
) -> RenderedDocument:
    """Keep freshly rendered bytes and describe them; a failure to keep them is logged, not raised."""
    stored = False
    if store is not None:
        try:
            object_id = _put(database, store, tenant_id, content)
            stored = database.set_version_document(
                tenant_id=tenant_id,
                version_id=str(context["id"]),
                role=spec.role,
                object_id=object_id,
                content_stamp=int(context["content_stamp"]),
                generator=spec.generator,
                generator_version=generator_version,
            )
        except Exception as exc:  # noqa: BLE001 - the caller still gets the rendered bytes
            logger.warning("rendered document not stored version_id=%s: %s", context["id"], type(exc).__name__)
    return RenderedDocument(
        tenant_id=tenant_id,
        version_id=str(context["id"]),
        kind=kind,
        sha256=sha256_hex(content),
        size_bytes=len(content),
        content_stamp=int(context["content_stamp"]),
        generator=spec.generator,
        generator_version=generator_version,
        cached=False,
        stored=bool(stored),
        _content=content,
    )


# ───────────────────────────── the cache ─────────────────────────────


def rendered_document(
    revision: Union[str, Mapping[str, Any]],
    kind: str = KIND_OPENAPI,
    *,
    tenant_id: str,
    database: Any = None,
    store: Any = None,
) -> Optional[RenderedDocument]:
    """Return a revision's rendered document, rendering it only when no current one is stored.

    Args:
        revision: The revision's ``versions.id``, or a row that carries it as ``id``.
        kind: :data:`KIND_OPENAPI` (the document ``GET /v1/schema`` serves),
            :data:`KIND_OPENAPI_MEMBERS` (the document a workspace member reads) or
            :data:`KIND_CANONICAL` (the canonical model as JSON).
        tenant_id: The tenant that must own the revision.
        database: The database layer; the process-wide one when omitted.
        store: The document store; the process-wide one when omitted.

    Returns:
        The document, or ``None`` when the tenant has no such revision or, for
        :data:`KIND_CANONICAL`, the revision has no canonical model.

    Raises:
        ValueError: if ``kind`` is not a known kind.
        Exception: whatever the generator raises. Store and cache failures are never raised.
    """
    spec = _KINDS.get(kind)
    if spec is None:
        raise ValueError(f"Unknown rendered document kind {kind!r}.")
    version_id = str(revision.get("id") if isinstance(revision, Mapping) else revision or "")
    if not version_id or not tenant_id:
        return None
    tenant = str(tenant_id)
    database = _database(database)
    context = database.get_rendered_document_context(tenant_id=tenant, version_id=version_id)
    if not context:
        return None
    # The stamp is read before the rows: an edit that lands mid-render is recorded under the
    # older stamp, which no later read asks for.
    generator_version = spec.generator_version(context)
    store = _store(store)

    found = _lookup(database, store, tenant, kind, spec, context, generator_version)
    if found is not None:
        return found
    flight = (tenant, version_id, spec.role, int(context["content_stamp"]), spec.generator, generator_version)
    with _flights.hold(flight):
        found = _lookup(database, store, tenant, kind, spec, context, generator_version)
        if found is not None:
            return found
        content = spec.render(database, tenant, context)
        if content is None:
            return None
        return _record(database, store, tenant, kind, spec, context, generator_version, content)


def warm_rendered_documents(tenant_id: str, version_id: str, *, database: Any = None, store: Any = None) -> int:
    """Render and store a revision's public OpenAPI and canonical documents, never raising.

    Called when a revision is published, so the first reader of a published revision is served
    stored bytes.

    Args:
        tenant_id: The owning tenant.
        version_id: The revision (``versions.id``).
        database: The database layer; the process-wide one when omitted.
        store: The document store; the process-wide one when omitted.

    Returns:
        The number of kinds that are stored after the call.
    """
    stored = 0
    for kind in _WARMED_KINDS:
        try:
            document = rendered_document(version_id, kind, tenant_id=tenant_id, database=database, store=store)
        except Exception as exc:  # noqa: BLE001 - warming is best effort
            logger.warning(
                "rendered document not warmed version_id=%s kind=%s: %s", version_id, kind, type(exc).__name__
            )
            continue
        if document is not None and document.stored:
            stored += 1
    return stored


# ───────────────────────────── frozen schemas ─────────────────────────────


def store_frozen_schema(
    tenant_id: str, version_id: str, content: bytes, *, database: Any = None, store: Any = None
) -> bool:
    """Write a frozen version's document to the store and link it as ``frozen_schema``, never raising.

    Args:
        tenant_id: The owning tenant.
        version_id: The frozen revision (``versions.id``).
        content: The exact bytes ``GET /v1/schema`` serves while the version is frozen.
        database: The database layer; the process-wide one when omitted.
        store: The document store; the process-wide one when omitted.

    Returns:
        ``True`` when the object is stored and linked; ``False`` when it is not, in which case
        the caller keeps the bytes in the snapshot row.
    """
    if not tenant_id or not version_id:
        return False
    try:
        database = _database(database)
        store = _store(store)
        if store is None:
            return False
        object_id = _put(database, store, str(tenant_id), content)
        return bool(
            database.set_version_document(
                tenant_id=str(tenant_id), version_id=str(version_id), role=ROLE_FROZEN_SCHEMA, object_id=object_id
            )
        )
    except Exception as exc:  # noqa: BLE001 - the snapshot row is the fallback
        logger.warning("frozen schema not stored version_id=%s: %s", version_id, type(exc).__name__)
        return False


def open_frozen_schema(tenant_id: str, sha256: str, *, store: Any = None) -> Optional[BinaryIO]:
    """Open a frozen version's stored document.

    Args:
        tenant_id: The owning tenant.
        sha256: ``version_spec_snapshots.sha256`` of the frozen version.
        store: The document store; the process-wide one when omitted.

    Returns:
        A readable binary stream the caller closes, or ``None`` when the store does not hold
        the object or cannot be reached.
    """
    store = _store(store)
    if store is None or not tenant_id:
        return None
    try:
        return store.open_stream(str(tenant_id), str(sha256).strip())
    except Exception as exc:  # noqa: BLE001 - the caller reports the missing document
        logger.warning("frozen schema not read tenant_id=%s: %s", tenant_id, type(exc).__name__)
        return None
