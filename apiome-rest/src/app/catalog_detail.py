"""
Catalog item detail helpers (MFI-23.9).

Pure, I/O-free derivations that back the catalog *item detail* + *source-material* surfaces. They
read the loose provenance an import records onto a revision's ``format_metadata`` (MFI-7.2) — and
fall back to the project's generic ``metadata`` — tolerating both camelCase and snake_case keys, so
the same data the UI registry (``catalog-format-registry.ts``) understands is understood here too.

Three entry points:

* :func:`derive_catalog_summary` — the normalized-content summary (services / operations / types /
  event channels counts) the import normalized the source to.
* :func:`derive_catalog_source` — the source-material descriptor (input kind, display label, source
  URL, and whether a raw source is retrievable) shown in the detail panel.
* :func:`resolve_source_payload` — decides what ``GET …/{id}/source`` actually serves: streamed
  inline content, a redirect to the source URL, or nothing.

Kept out of ``catalog_routes`` so the extraction logic is unit-testable without a database or an
HTTP client, and so the detail schema and the /source endpoint share one source of truth.

The captured source itself is not read here (COA-5.4, #7080): :func:`resolve_source_payload` asks
:func:`app.revision_source.source_from_row`, which reads the document store for a catalog item
row and otherwise only what the row carries.
"""

from typing import Any, Dict, Optional, Tuple

from .revision_source import row_has_source, source_from_row

# Keys (in priority order) that may carry each piece of provenance across metadata shapes. These
# mirror the UI's resolveCatalogSource so both layers read the same bag the same way.
_LABEL_KEYS: Tuple[str, ...] = (
    "sourceLabel", "source_label",
    "sourceUri", "source_uri", "sourceUrl", "source_url",
    "fileName", "file_name", "filename",
)
_KIND_KEYS: Tuple[str, ...] = ("inputKind", "input_kind", "sourceKind", "source_kind")
_URI_KEYS: Tuple[str, ...] = ("sourceUri", "source_uri", "sourceUrl", "source_url")

# Per-count aliases for the normalized summary. The canonical (plural) key is what
# ImportRoutingDecision.as_dict() emits under "counts"; the *Count variants are tolerated.
_COUNT_KEYS: Dict[str, Tuple[str, ...]] = {
    "services": ("services", "serviceCount", "service_count"),
    "operations": ("operations", "operationCount", "operation_count"),
    "types": ("types", "typeCount", "type_count"),
    "channels": ("channels", "channelCount", "channel_count"),
}

# Extension + media type per source format family, used to name and type a downloaded raw source.
_FORMAT_FILE_HINT: Tuple[Tuple[Tuple[str, ...], str, str], ...] = (
    (("graphql", "gql", "sdl"), "graphql", "application/graphql"),
    (("proto", "protobuf", "grpc"), "proto", "text/plain"),
    (("wsdl",), "wsdl", "application/xml"),
    (("xsd", "xmlschema"), "xsd", "application/xml"),
    (("avro", "avsc"), "avsc", "application/json"),
    (("openapi", "swagger", "oas", "asyncapi", "odata", "cloudevents", "jsonschema", "json"), "json", "application/json"),
)


def _as_bag(value: Any) -> Optional[Dict[str, Any]]:
    """Return ``value`` if it is a dict, else None (defensive against non-object JSONB)."""
    return value if isinstance(value, dict) else None


def _first_str(bag: Optional[Dict[str, Any]], keys: Tuple[str, ...]) -> Optional[str]:
    """Return the first present, non-empty, trimmed string value among ``keys``."""
    if not bag:
        return None
    for key in keys:
        value = bag.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_str_in(
    primary: Optional[Dict[str, Any]],
    secondary: Optional[Dict[str, Any]],
    keys: Tuple[str, ...],
) -> Optional[str]:
    """Look ``keys`` up in ``primary`` first, then fall back to ``secondary``."""
    return _first_str(primary, keys) or _first_str(secondary, keys)


def _normalize_token(value: str) -> str:
    """Lower-case and strip non-alphanumerics (matches the UI's normalizeToken)."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _normalize_kind(value: Optional[str]) -> Optional[str]:
    """Normalise a raw input-kind token to file / url / paste / discovery / connector, or None."""
    if not value:
        return None
    key = _normalize_token(value)
    if key in ("file", "upload"):
        return "file"
    if key in ("url", "uri", "link"):
        return "url"
    if key in ("paste", "clipboard", "pasted", "inline"):
        return "paste"
    if key in ("discovery", "livediscovery", "live", "endpoint"):
        return "discovery"
    if key == "connector":
        return "connector"
    return None


#: ``format_metadata`` keys a connector sync records (CDG-1.1), by descriptor field.
_CONNECTOR_KEYS: Tuple[Tuple[str, str], ...] = (
    ("connector_id", "connectorId"),
    ("connector_kind", "connectorKind"),
    ("connector_name", "connectorName"),
    ("remote_id", "remoteId"),
    ("remote_name", "remoteName"),
    ("remote_revision", "remoteRevision"),
)


def derive_connector_source(format_metadata: Any) -> Optional[Dict[str, Optional[str]]]:
    """The connector a catalog revision was synced from (CDG-1.1), or None for any other intake.

    Args:
        format_metadata: The latest revision's ``format_metadata`` bag, or None.

    Returns:
        ``{connector_id, connector_kind, connector_name, remote_id, remote_name,
        remote_revision}`` when the revision records ``inputKind: "connector"`` and a connector
        id; otherwise None.
    """
    fmd = _as_bag(format_metadata)
    if not fmd or _normalize_kind(_first_str(fmd, _KIND_KEYS)) != "connector":
        return None
    out = {field: _first_str(fmd, (key,)) for field, key in _CONNECTOR_KEYS}
    return out if out["connector_id"] else None


def _looks_like_url(value: Optional[str]) -> bool:
    """True when ``value`` is an http(s) URL."""
    return bool(value) and value.lower().startswith(("http://", "https://"))


def _read_counts(format_metadata: Any) -> Dict[str, Optional[int]]:
    """Read the per-entity counts, tolerating a nested ``counts``/``summary`` bag or flat keys."""
    fmd = _as_bag(format_metadata) or {}
    # The import records counts under "counts" (ImportRoutingDecision.as_dict); some shapes nest
    # them under "summary". Either of those, or the format_metadata root itself, may hold the keys.
    sources = [_as_bag(fmd.get("counts")), _as_bag(fmd.get("summary")), fmd]
    out: Dict[str, Optional[int]] = {}
    for field, keys in _COUNT_KEYS.items():
        value: Optional[int] = None
        for bag in sources:
            if not bag:
                continue
            for key in keys:
                raw = bag.get(key)
                if isinstance(raw, bool):  # bool is an int subclass; never a count
                    continue
                if isinstance(raw, int):
                    value = raw
                    break
            if value is not None:
                break
        out[field] = value
    return out


def derive_catalog_summary(format_metadata: Any) -> Dict[str, Optional[int]]:
    """Derive the normalized-content summary (services/operations/types/channels) for a catalog item.

    Args:
        format_metadata: The latest revision's ``format_metadata`` bag (JSONB), or None.

    Returns:
        A dict with ``services``/``operations``/``types``/``channels`` — each an int when the import
        recorded it, or None when it has not (yet) been captured onto the revision.
    """
    return _read_counts(format_metadata)


def derive_catalog_source(
    format_metadata: Any, metadata: Any, source_captured: Optional[bool] = None
) -> Dict[str, Any]:
    """Derive the source-material descriptor for a catalog item.

    Reads the input kind, a display label, an optional source URL and whether raw content was
    captured, from ``format_metadata`` (preferred) falling back to the project's ``metadata``.

    Args:
        format_metadata: The latest revision's ``format_metadata`` bag, or None.
        metadata: The project's generic ``metadata`` bag, or None.
        source_captured: The row's ``source_captured`` flag, when the query selected it (catalog
            item rows do, because they no longer carry the source text itself).

    Returns:
        A descriptor dict ``{kind, label, uri, has_content, downloadable, connector}``;
        ``connector`` is the CDG-1.1 sync descriptor, or None for any other intake. ``downloadable`` is True
        when a raw source is retrievable via the /source endpoint (inline content *or* a URL).
    """
    fmd = _as_bag(format_metadata)
    md = _as_bag(metadata)

    label = _first_str_in(fmd, md, _LABEL_KEYS)
    raw_kind = _first_str_in(fmd, md, _KIND_KEYS)
    uri_value = _first_str_in(fmd, md, _URI_KEYS)
    uri = uri_value if _looks_like_url(uri_value) else (label if _looks_like_url(label) else None)

    kind = _normalize_kind(raw_kind)
    if kind is None:
        if uri is not None:
            kind = "url"
        elif label is not None:
            kind = "file"

    has_content = row_has_source(
        {"format_metadata": fmd, "metadata": md, "source_captured": source_captured}
    )
    downloadable = has_content or uri is not None

    return {
        "kind": kind,
        "label": label,
        "uri": uri,
        "has_content": has_content,
        "downloadable": downloadable,
        "connector": derive_connector_source(format_metadata),
    }


def _file_hint(source_format: Optional[str]) -> Tuple[str, str]:
    """Return ``(extension, media_type)`` for a source format, defaulting to a plain-text fallback."""
    key = _normalize_token(source_format) if source_format else ""
    for tokens, ext, media_type in _FORMAT_FILE_HINT:
        if any(key.startswith(token) for token in tokens):
            return ext, media_type
    return "txt", "text/plain"


def _download_filename(item: Dict[str, Any], label: Optional[str], source_format: Optional[str]) -> str:
    """Pick a download filename: the source label when it already looks like a file, else slug+ext."""
    if label and "." in label and not _looks_like_url(label):
        # A bare file name (e.g. "petstore.yaml"); strip any path component.
        return label.replace("\\", "/").rsplit("/", 1)[-1]
    ext, _ = _file_hint(source_format)
    base = (item.get("slug") or item.get("id") or "catalog-source")
    return f"{base}.{ext}"


def resolve_source_payload(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Decide what ``GET …/{id}/source`` should serve for a catalog item.

    Args:
        item: The catalog item row (``format_metadata`` / ``metadata``), carrying its captured
            source when the caller attached one (:func:`app.revision_source.attach_revision_source`).

    Returns:
        ``{"mode": "content", "content", "media_type", "filename", "source"}`` when a source was
        captured (``content`` is its trimmed text; for a set of files, the root file's; ``source`` is
        the :class:`~app.revision_source.RevisionSource`); ``{"mode": "redirect", "url"}`` when
        only a source URL is recorded; or None when nothing retrievable was captured (the caller
        404s).
    """
    fmd = _as_bag(item.get("format_metadata"))
    md = _as_bag(item.get("metadata"))

    source = source_from_row(item)
    if source is not None:
        label = _first_str_in(fmd, md, _LABEL_KEYS)
        source_format = item.get("source_format")
        _, media_type = _file_hint(source_format)
        return {
            "mode": "content",
            # Trimmed, as this payload always was: the digests recorded for earlier conversions
            # were taken over the trimmed text. ``source`` keeps the exact text.
            "content": source.text.strip(),
            "media_type": media_type,
            "filename": _download_filename(item, label, source_format),
            "source": source,
        }

    uri_value = _first_str_in(fmd, md, _URI_KEYS)
    label = _first_str_in(fmd, md, _LABEL_KEYS)
    url = uri_value if _looks_like_url(uri_value) else (label if _looks_like_url(label) else None)
    if url is not None:
        return {"mode": "redirect", "url": url}

    return None
