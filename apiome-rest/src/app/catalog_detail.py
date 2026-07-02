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
"""

from typing import Any, Dict, Optional, Tuple


# Keys (in priority order) that may carry each piece of provenance across metadata shapes. These
# mirror the UI's resolveCatalogSource so both layers read the same bag the same way.
_LABEL_KEYS: Tuple[str, ...] = (
    "sourceLabel", "source_label",
    "sourceUri", "source_uri", "sourceUrl", "source_url",
    "fileName", "file_name", "filename",
)
_KIND_KEYS: Tuple[str, ...] = ("inputKind", "input_kind", "sourceKind", "source_kind")
_URI_KEYS: Tuple[str, ...] = ("sourceUri", "source_uri", "sourceUrl", "source_url")
_CONTENT_KEYS: Tuple[str, ...] = (
    "sourceContent", "source_content",
    "sourceText", "source_text",
    "rawSource", "raw_source",
    "raw", "content",
)

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
    """Normalise a raw input-kind token to file / url / paste / discovery, or None."""
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
    return None


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


def derive_catalog_source(format_metadata: Any, metadata: Any) -> Dict[str, Any]:
    """Derive the source-material descriptor for a catalog item.

    Reads the input kind, a display label, an optional source URL and whether raw content was
    captured, from ``format_metadata`` (preferred) falling back to the project's ``metadata``.

    Args:
        format_metadata: The latest revision's ``format_metadata`` bag, or None.
        metadata: The project's generic ``metadata`` bag, or None.

    Returns:
        A descriptor dict ``{kind, label, uri, has_content, downloadable}``. ``downloadable`` is True
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

    has_content = _first_str_in(fmd, md, _CONTENT_KEYS) is not None
    downloadable = has_content or uri is not None

    return {
        "kind": kind,
        "label": label,
        "uri": uri,
        "has_content": has_content,
        "downloadable": downloadable,
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
        item: The catalog item row (must include ``format_metadata`` / ``metadata``).

    Returns:
        ``{"mode": "content", "content", "media_type", "filename"}`` when raw source content was
        captured; ``{"mode": "redirect", "url"}`` when only a source URL is recorded; or None when
        nothing retrievable was captured (the caller 404s).
    """
    fmd = _as_bag(item.get("format_metadata"))
    md = _as_bag(item.get("metadata"))

    content = _first_str_in(fmd, md, _CONTENT_KEYS)
    if content is not None:
        label = _first_str_in(fmd, md, _LABEL_KEYS)
        source_format = item.get("source_format")
        _, media_type = _file_hint(source_format)
        return {
            "mode": "content",
            "content": content,
            "media_type": media_type,
            "filename": _download_filename(item, label, source_format),
        }

    uri_value = _first_str_in(fmd, md, _URI_KEYS)
    label = _first_str_in(fmd, md, _LABEL_KEYS)
    url = uri_value if _looks_like_url(uri_value) else (label if _looks_like_url(label) else None)
    if url is not None:
        return {"mode": "redirect", "url": url}

    return None
