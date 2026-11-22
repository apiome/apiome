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

Since COA-5.14 (#7090) this module is the only one that calls the generator
(:func:`app.openapi_generator.generate_openapi_spec`); ``tests/test_rendered_document_architecture.py``
fails on a call anywhere else.

* A feature that reads a stored revision calls :func:`revision_openapi`, or
  :func:`app.compatibility_engine.openapi_for_revision`, which reads the cache the same way.
* A state that is not a stored revision (a preview of a change that is not written, rows read
  inside an open transaction) is rendered by :func:`render_uncached`, which takes the reason and
  stores nothing.
* A write that replaces a revision's rows in one step calls :func:`write_through` afterwards.
* :func:`build_live_spec` is the render behind the cache.

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
from typing import Any, BinaryIO, Callable, Dict, Iterator, List, Mapping, Optional, Tuple, Union

from .document_store import get_document_store
from .openapi_generator import generate_openapi_spec
from .original_documents import ENCODING_IDENTITY

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
    "REASON_COMPONENT_PINS_OVERRIDE",
    "REASON_SOURCE_APPLY",
    "RenderedDocument",
    "SpecCounts",
    "UNCACHED_REASONS",
    "build_live_spec",
    "etag_for",
    "etag_matches",
    "iter_stream",
    "load_classes_and_properties",
    "open_frozen_schema",
    "render_spec_bytes",
    "render_uncached",
    "rendered_document",
    "revision_openapi",
    "sha256_hex",
    "store_frozen_schema",
    "warm_rendered_documents",
    "write_through",
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

#: Why a document may be rendered without the cache (:func:`render_uncached`). Each names a state
#: that is not a stored revision, so no content stamp identifies it.
#:
#: * :data:`REASON_COMPONENT_PINS_OVERRIDE` — a revision rendered with other component-library
#:   pins than the ones it stores: the bulk-upgrade preview and the materialization preview.
#: * :data:`REASON_SOURCE_APPLY` — a source change being applied: the revision's rows as the open
#:   transaction sees them under its row lock, and the document the reviewed change would produce.
REASON_COMPONENT_PINS_OVERRIDE = "component-pins-override"
REASON_SOURCE_APPLY = "source-apply"
UNCACHED_REASONS: Tuple[str, ...] = (REASON_COMPONENT_PINS_OVERRIDE, REASON_SOURCE_APPLY)

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


# ───────────────────────────── rendering ─────────────────────────────


@dataclass(frozen=True)
class SpecCounts:
    """What a version's OpenAPI document holds."""

    classes: int
    properties: int
    paths: int


def load_classes_and_properties(db: Any, version_id: Any) -> Tuple[List[Dict[str, Any]], Dict[Any, Any]]:
    """Load a version's classes and every class's properties: one query per table.

    Args:
        db: Database handle (``get_classes_for_version``, ``get_properties_for_classes``).
        version_id: The version (``versions.id``).

    Returns:
        ``(classes, all_properties)`` where ``all_properties`` maps each class id to its property
        rows, in the order :func:`app.openapi_generator.generate_openapi_spec` expects.
    """
    classes = db.get_classes_for_version(version_id)
    all_properties = db.get_properties_for_classes([class_data["id"] for class_data in classes])
    return classes, all_properties


def build_live_spec(
    db: Any,
    version: Mapping[str, Any],
    tenant_slug: str,
    project_slug: str,
    version_slug: str,
    *,
    openapi_version: str = "3.1.0",
    include_private: bool = False,
) -> Tuple[Dict[str, Any], SpecCounts]:
    """Generate a stored version's OpenAPI document from its rows.

    This is the render behind the cache: :func:`rendered_document` calls it on a miss. With the
    defaults it gives the OpenAPI 3.1 document ``/v1/schema`` serves for an unfrozen version. The
    document workspace members read (COA-5.13, #7089) passes ``3.2.0`` and ``include_private=True``.
    Call it directly only when the counts are needed too (a freeze) or the document is a content
    identity that must not name the project (the URL-import divergence guard); every other reader
    of a stored revision uses :func:`revision_openapi`.

    Args:
        db: Database handle (``get_classes_for_version``, ``get_properties_for_classes``).
        version: The version row from ``get_version_by_slugs`` (needs ``id``, ``metadata``,
            ``project_description``, ``project_metadata``).
        tenant_slug: Tenant slug used in the document's URLs.
        project_slug: Project slug.
        version_slug: Version slug as requested (e.g. ``2.1.0``).
        openapi_version: The OpenAPI version the document declares.
        include_private: Keep the operations marked ``x-private``.

    Returns:
        The document and its :class:`SpecCounts`.
    """
    classes, all_properties = load_classes_and_properties(db, version["id"])
    spec = generate_openapi_spec(
        tenant_slug,
        project_slug,
        version_slug,
        classes,
        all_properties,
        version.get("project_description"),
        version_db_id=version["id"],
        revision_metadata=version.get("metadata"),
        project_metadata=version.get("project_metadata"),
        openapi_version=openapi_version,
        include_private=include_private,
    )
    counts = SpecCounts(
        classes=len(classes),
        properties=sum(len(props or []) for props in all_properties.values()),
        paths=len(spec.get("paths") or {}),
    )
    return spec, counts


def render_spec_bytes(spec: Any) -> bytes:
    """The response body ``JSONResponse(content=spec)`` sends — compact UTF-8 JSON."""
    return json.dumps(spec, ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":")).encode("utf-8")


def sha256_hex(content: bytes) -> str:
    """Lower-case hex SHA-256 of ``content``."""
    return hashlib.sha256(content).hexdigest()


def render_uncached(
    *,
    reason: str,
    tenant_slug: str,
    project_slug: str,
    version_label: str,
    classes: List[Dict[str, Any]],
    all_properties: Dict[Any, List[Dict[str, Any]]],
    project_description: Optional[str] = None,
    **generator_options: Any,
) -> Dict[str, Any]:
    """Generate an OpenAPI document for a state that is not a stored revision.

    The cache keys a document by a stored revision's content stamp. A preview of a change that
    is not written, or rows read inside an open transaction, has no such key, so it is rendered
    directly and never stored. This is the only way to reach the generator outside this module;
    ``tests/test_rendered_document_architecture.py`` fails on any other call and pins the call
    sites of this one.

    Args:
        reason: One of :data:`UNCACHED_REASONS`, saying why the cache cannot serve the document.
        tenant_slug: Tenant slug.
        project_slug: Project slug (the document's title is ``<slug> API``).
        version_label: The version label written to ``info.version``.
        classes: Class rows, as ``get_classes_for_version`` returns them.
        all_properties: Property rows by class id.
        project_description: The project's description.
        **generator_options: Further keyword arguments of
            :func:`app.openapi_generator.generate_openapi_spec` (``version_db_id``,
            ``revision_metadata``, ``project_metadata``, ``paths_data``, ``security_scheme_rows``,
            ``server_rows``, ``component_pin_rows``).

    Returns:
        The OpenAPI document.

    Raises:
        ValueError: if ``reason`` is not one of :data:`UNCACHED_REASONS`.
    """
    if reason not in UNCACHED_REASONS:
        raise ValueError(f"Unknown uncached render reason {reason!r}.")
    return generate_openapi_spec(
        tenant_slug,
        project_slug,
        version_label,
        classes,
        all_properties,
        project_description,
        **generator_options,
    )


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
    # Anything but a row (nothing found, or a stand-in database in a test) is "no such revision".
    if not context or not isinstance(context, Mapping):
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


def revision_openapi(
    version: Mapping[str, Any],
    tenant_slug: str,
    tenant_id: Optional[str],
    *,
    database: Any = None,
    store: Any = None,
    project_slug: Optional[str] = None,
    version_label: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a stored revision's public OpenAPI document, parsed, through the cache.

    This is what a REST feature calls to read a stored revision (COA-5.14, #7090): lint, mocks,
    Swagger UI, preservation, source review and the rest. A warm revision is read from the
    document store and no class, property or path row is queried. The reading also keeps the
    document, so the first read after an edit (a committed merge, an applied source change)
    stores the new stamp's document for the next one.

    When the cache cannot serve the revision — the tenant has no such live revision, no tenant
    is known, or the cached render fails — the document is generated from ``version``'s own
    values, which raises whatever the generator raises.

    Args:
        version: The revision row. Needs ``id``; the direct render also reads ``version_id``,
            ``metadata``, ``project_slug`` (else ``project_id``), ``project_description`` and
            ``project_metadata``.
        tenant_slug: Tenant slug, used by the direct render.
        tenant_id: The tenant that must own the revision; ``None`` skips the cache.
        database: The database layer; the process-wide one when omitted.
        store: The document store; the process-wide one when omitted.
        project_slug: Project slug for the direct render, when the row does not carry it.
        version_label: Version label for the direct render, when the row does not carry it.

    Returns:
        The document. The caller owns it: every call parses a fresh copy.
    """
    database = _database(database)
    document: Optional[RenderedDocument] = None
    if tenant_id:
        try:
            document = rendered_document(
                str(version["id"]), KIND_OPENAPI, tenant_id=str(tenant_id), database=database, store=store
            )
        except Exception as exc:  # noqa: BLE001 - the direct render below raises the real error
            logger.warning("rendered OpenAPI not read version_id=%s: %s", version.get("id"), type(exc).__name__)
    if document is not None:
        return document.json()
    spec, _counts = build_live_spec(
        database,
        version,
        tenant_slug,
        str(project_slug or version.get("project_slug") or version.get("project_id") or ""),
        str(version_label or version.get("version_id") or ""),
    )
    return spec


def write_through(tenant_id: str, version_id: str, *, database: Any = None, store: Any = None) -> bool:
    """Render and store a just-written revision's public OpenAPI document, never raising.

    Called after a write that replaces a revision's rows in one step (an applied source change),
    so the document of the new content stamp is stored before the next reader asks for it.

    Args:
        tenant_id: The owning tenant.
        version_id: The revision (``versions.id``).
        database: The database layer; the process-wide one when omitted.
        store: The document store; the process-wide one when omitted.

    Returns:
        ``True`` when the document of the revision's current stamp is stored after the call.
    """
    try:
        document = rendered_document(version_id, KIND_OPENAPI, tenant_id=tenant_id, database=database, store=store)
    except Exception as exc:  # noqa: BLE001 - the next read renders it
        logger.warning("rendered document not written through version_id=%s: %s", version_id, type(exc).__name__)
        return False
    return document is not None and document.stored


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
