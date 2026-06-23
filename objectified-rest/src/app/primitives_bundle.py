"""Objectified type-definition bundle importer for the Primitives import pipeline (#3462).

The JSON Schema parser (#3461) expands one ingested *document* into discrete types,
treating each ``$defs`` / ``definitions`` entry as a type and capturing intra-document
``#/$defs/...`` refs. This module is the sibling expander for the **type-def-bundle**
source kind: an *Objectified type-definition bundle* — many interlinked types shipped
together as a single ``.json`` document or a ``.zip`` archive of per-type files.

A bundle differs from a raw JSON Schema document only in its **container**: types live
under a ``types`` mapping (``$defs`` / ``definitions`` are accepted as equivalents so a
bundle authored either way ingests). Each named entry becomes one discrete type, and for
each one this module

* keeps the type's schema **fragment** (so the rewrite/commit stage can persist it);
* captures the type's **inter-type** ``$ref`` edges — refs at a sibling type in the same
  bundle (``#/types/Money``, and also ``#/$defs/Money`` / ``#/definitions/Money``) — in the
  ``{relative_ref, resolved_target, status}`` shape persisted on ``odb.primitives.refs``,
  marked ``internal``; the rewrite stage (#3463) turns each into a relative registry ref
  (``#/types/Money`` → ``./money``), so a bundle of N types commits N rows with their
  inter-type refs intact (the ticket's acceptance criterion);
* runs the shared draft 2020-12 meta-validator over the fragment, yielding a per-type
  validation report.

Two delivery shapes are handled:

* :func:`parse_type_def_bundle` — a parsed ``.json`` / ``.yaml`` bundle document (a mapping
  with a ``types`` container);
* :func:`expand_zip_bundle` — a ``.zip`` archive whose JSON/YAML members are each one type;
  it merges them into a single bundle document that :func:`parse_type_def_bundle` then
  expands, so both delivery shapes converge on one parser.

A bundle that is not a mapping, carries no recognizable container, or yields no usable type
raises :class:`BundleError` with a human-readable message — the "malformed bundle reports a
clear error" half of the acceptance criterion. Everything here is pure and side-effect free
(no network/DB) except the stdlib ``zipfile`` read in :func:`expand_zip_bundle`.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .primitives_parser import (
    STATUS_INTERNAL,
    ParsedType,
    _unescape_pointer_token,
    internal_ref_target,
)
from .primitives_scope import iter_refs
from .schema_validation import validate_schema_document

__all__ = [
    "BundleError",
    "BUNDLE_CONTAINERS",
    "bundle_internal_ref_target",
    "build_bundle_internal_ref_edges",
    "parse_type_def_bundle",
    "expand_zip_bundle",
]

# Containers of named types in a bundle, paired with the JSON Pointer prefix each maps to.
# ``types`` is the Objectified bundle keyword; ``$defs`` / ``definitions`` are accepted as
# equivalents so a bundle authored as a plain JSON Schema document ingests too. The first
# non-empty container in this order is the one the bundle is read from.
BUNDLE_CONTAINERS: Tuple[Tuple[str, str], ...] = (
    ("types", "#/types"),
    ("$defs", "#/$defs"),
    ("definitions", "#/definitions"),
)

# Pointer prefix for an inter-type ref into the bundle's ``types`` container. Refs into
# ``$defs`` / ``definitions`` are handled by the parser's ``internal_ref_target`` (#3461).
_TYPES_POINTER_PREFIX = "#/types/"

# Members a ``.zip`` bundle is read from — each is parsed as one type's schema document.
_BUNDLE_MEMBER_SUFFIXES = (".json", ".yaml", ".yml")

# Cap on a ``.zip`` bundle's total *uncompressed* size, so a decompression-bomb archive
# cannot exhaust memory. Mirrors the ingestion layer's per-document limit.
DEFAULT_MAX_ZIP_BYTES = 2_000_000


class BundleError(Exception):
    """A type-definition bundle could not be expanded into types.

    Carries a human-readable ``message`` so the import route can surface it directly
    (a 400 detail) without leaking stack traces — the "malformed bundle reports a clear
    error" acceptance criterion (#3462).
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def bundle_internal_ref_target(ref: str) -> Optional[str]:
    """Return the sibling type name an inter-type ``$ref`` names, or ``None``.

    Extends the parser's :func:`app.primitives_parser.internal_ref_target` (which handles
    ``#/$defs/...`` / ``#/definitions/...``) with the bundle's ``#/types/...`` container, so
    a ref at a sibling *bundle* type is recognized as an inter-type edge. A registry-relative
    ref (``../primitives/string``), an absolute URL, or a pointer elsewhere in the document
    is not one and yields ``None``.

    Args:
        ref: The ``$ref`` value exactly as written in the bundle.

    Returns:
        The referenced type's local name (e.g. ``Money`` for ``#/types/Money/properties/c``),
        or ``None`` when the ref does not target a sibling type container.
    """
    if not isinstance(ref, str):
        return None
    # Reuse the parser's $defs/definitions handling first, then add the bundle's container.
    target = internal_ref_target(ref)
    if target is not None:
        return target
    if ref.startswith(_TYPES_POINTER_PREFIX):
        first_segment = ref[len(_TYPES_POINTER_PREFIX):].split("/", 1)[0]
        if first_segment:
            return _unescape_pointer_token(first_segment)
    return None


def build_bundle_internal_ref_edges(schema: Any) -> List[Dict[str, str]]:
    """Capture a fragment's inter-type ``$ref`` edges for later rewrite (#3463).

    Walks every ``$ref`` in ``schema`` and records the ones that target a sibling bundle
    type (``#/types/...``, ``#/$defs/...``, or ``#/definitions/...``) as ``internal`` edges,
    in the ``{relative_ref, resolved_target, status}`` shape persisted on
    ``odb.primitives.refs``. ``resolved_target`` is the referenced type's local name (what
    #3463 maps to a relative registry ref). Duplicate ``$ref`` values are recorded once, in
    first-seen document order; non-internal refs (registry-relative, absolute, external) are
    left for the resolver (#3456).

    This is the bundle counterpart of
    :func:`app.primitives_parser.build_internal_ref_edges`, used by the commit path so each
    imported bundle type persists its inter-type refs alongside its resolved registry refs.

    Args:
        schema: A parsed JSON Schema fragment (object, array, or scalar).

    Returns:
        The list of inter-type ref edges, empty when the fragment has none.
    """
    edges: List[Dict[str, str]] = []
    seen: set = set()
    for ref in iter_refs(schema):
        if ref in seen:
            continue
        target = bundle_internal_ref_target(ref)
        if target is None:
            continue
        seen.add(ref)
        edges.append(
            {"relative_ref": ref, "resolved_target": target, "status": STATUS_INTERNAL}
        )
    return edges


def _locate_container(
    document: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """Find the bundle's type container: the first non-empty one in :data:`BUNDLE_CONTAINERS`.

    Args:
        document: The parsed bundle document.

    Returns:
        ``(container, key, pointer_prefix)`` for the first present and non-empty container,
        or ``(None, None, None)`` when no recognizable container is found.
    """
    for key, pointer_prefix in BUNDLE_CONTAINERS:
        block = document.get(key)
        if isinstance(block, dict) and block:
            return block, key, pointer_prefix
    return None, None, None


def parse_type_def_bundle(
    document: Dict[str, Any], *, source_label: Optional[str] = None
) -> Tuple[List[ParsedType], List[str]]:
    """Expand an Objectified type-definition bundle into discrete interlinked types (#3462).

    Reads the bundle's ``types`` (or legacy ``$defs`` / ``definitions``) container and turns
    each named entry into one :class:`app.primitives_parser.ParsedType`, capturing the entry's
    inter-type refs (for rewrite #3463) and a per-type draft 2020-12 validation report. A bundle
    of N types yields N parsed types with their refs intact.

    Args:
        document: The parsed bundle document (a mapping). Typically the result of ingesting a
            ``.json`` / ``.yaml`` bundle, or the merged document from :func:`expand_zip_bundle`.
        source_label: Optional source label (filename / archive name) used only to make a
            malformed-bundle error specific.

    Returns:
        ``(types, warnings)`` — the parsed types in container order, and any non-fatal
        document-level warnings (a skipped non-object entry, or a dangling inter-type ref).

    Raises:
        BundleError: If the document is not a mapping, carries no recognizable type container,
            the container is empty, or every entry is unusable (no type could be expanded).
    """
    where = f" ({source_label})" if source_label else ""
    if not isinstance(document, dict):
        raise BundleError(
            f"Type-definition bundle must be a JSON object / YAML mapping at the top level{where}"
        )

    container, _key, pointer_prefix = _locate_container(document)
    if container is None:
        raise BundleError(
            "Type-definition bundle has no 'types', '$defs', or 'definitions' "
            f"container of types{where}"
        )

    warnings: List[str] = []
    def_names = {str(name) for name in container}
    types: List[ParsedType] = []

    for raw_name, fragment in container.items():
        name = str(raw_name)
        pointer = f"{pointer_prefix}/{name}"
        # A type entry must be a schema object. A non-object member (string, list, …) is a
        # malformed entry — skipped with a warning rather than failing the whole bundle, so
        # one bad type does not block the rest (matching the import pipeline's convention).
        if not isinstance(fragment, dict):
            warnings.append(
                f"Type '{name}' is not a schema object and was skipped"
            )
            continue

        internal_refs = build_bundle_internal_ref_edges(fragment)
        for edge in internal_refs:
            if edge["resolved_target"] not in def_names:
                warnings.append(
                    f"Type '{name}' references '{edge['relative_ref']}', "
                    f"which is not defined in the bundle"
                )

        errors = validate_schema_document(fragment)
        types.append(
            ParsedType(
                name=name,
                pointer=pointer,
                schema=fragment,
                internal_refs=internal_refs,
                valid=not errors,
                validation_errors=errors,
            )
        )

    if not types:
        raise BundleError(
            f"Type-definition bundle contains no usable type definitions{where}"
        )
    return types, warnings


def _member_type_name(filename: str) -> str:
    """Derive a type name from a ``.zip`` member's path: its filename without directory/suffix.

    Args:
        filename: The archive member path (e.g. ``schemas/money.json``).

    Returns:
        The bare filename stem (``money``).
    """
    base = filename.rsplit("/", 1)[-1]
    for suffix in _BUNDLE_MEMBER_SUFFIXES:
        if base.lower().endswith(suffix):
            return base[: -len(suffix)]
    return base


def expand_zip_bundle(
    raw: bytes, *, source_label: Optional[str] = None, max_bytes: int = DEFAULT_MAX_ZIP_BYTES
) -> Dict[str, Any]:
    """Expand a ``.zip`` type-definition bundle into a single bundle document.

    Each JSON/YAML member of the archive is one type's schema document; this reads them into
    a ``{"types": {name: schema, ...}}`` mapping keyed by each member's filename stem, which
    :func:`parse_type_def_bundle` then expands. Directories, non-JSON/YAML members, and macOS
    ``__MACOSX`` resource forks are ignored; total uncompressed size is capped to guard against
    a decompression bomb.

    Args:
        raw: The raw bytes of the ``.zip`` archive.
        source_label: Optional archive name, used only to make errors specific.
        max_bytes: Hard cap on the archive's total uncompressed size.

    Returns:
        A bundle document (``{"types": {...}}``) ready for :func:`parse_type_def_bundle`.

    Raises:
        BundleError: If the bytes are not a valid zip, exceed ``max_bytes``, contain a member
            that is not valid JSON/YAML or not a mapping, name two types the same, or contain
            no JSON/YAML members at all.
    """
    where = f" ({source_label})" if source_label else ""
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise BundleError(f"Bundle archive is not a valid .zip file{where}")

    types: Dict[str, Any] = {}
    total = 0
    try:
        for info in archive.infolist():
            if info.is_dir():
                continue
            filename = info.filename
            if filename.startswith("__MACOSX/") or "/." in f"/{filename}":
                # Skip macOS resource forks and dotfiles (e.g. .DS_Store).
                continue
            if not filename.lower().endswith(_BUNDLE_MEMBER_SUFFIXES):
                continue

            total += info.file_size
            if total > max_bytes:
                raise BundleError(
                    f"Bundle archive exceeds the {max_bytes}-byte uncompressed limit{where}"
                )

            name = _member_type_name(filename)
            if name in types:
                raise BundleError(
                    f"Bundle archive defines type '{name}' more than once{where}"
                )

            text = archive.read(info).decode("utf-8", errors="replace")
            try:
                parsed = yaml.safe_load(text)  # superset of JSON, so this parses both.
            except yaml.YAMLError as exc:
                raise BundleError(
                    f"Bundle member '{filename}' is not valid JSON or YAML{where}: {exc}"
                )
            if not isinstance(parsed, dict):
                raise BundleError(
                    f"Bundle member '{filename}' must be a JSON object / YAML mapping{where}"
                )
            types[name] = parsed
    finally:
        archive.close()

    if not types:
        raise BundleError(
            f"Bundle archive contains no .json/.yaml type definitions{where}"
        )
    return {"types": types}
