"""JSON Schema draft 2020-12 parser for the Primitives import pipeline (#3461).

The import pipeline core (#3460) *detects* candidate types shallowly — it records a
name, a JSON Pointer, and a cheap ``$ref`` count per candidate, but it does not look
inside a candidate. This module is the parser that closes that gap for the
**json-schema** source kind: it turns one ingested JSON Schema document into a list
of discrete parsed types, and for each one it

* keeps the type's schema **fragment** (so a later stage can rewrite/persist it);
* captures the type's **intra-document** ``$ref`` edges (``#/$defs/Money`` /
  ``#/definitions/Money``) in the same ``{relative_ref, resolved_target, status}``
  shape used by ``odb.primitives.refs``, marked ``internal`` — the rewrite stage
  (#3463) turns each of these into a relative registry ref (``#/$defs/Money`` →
  ``./money``);
* runs the shared draft 2020-12 meta-validator over the fragment, yielding a
  per-type **validation report** (``valid`` plus field-level ``validation_errors``).

Two document shapes are handled, mirroring the import-review UX:

* a **``$defs`` / ``definitions`` bundle** — each named entry is one type (a document
  with three ``$defs`` yields three types, the ticket's acceptance criterion);
* a **single-root document** — a document with neither container is itself one type.

Everything here is pure and side-effect free (no network/DB), so it is unit-testable
on a parsed document and is shared by both the staging path (#3460) and the legacy
commit path. Cross-type *registry* refs (relative refs rooted at the import source,
e.g. ``../primitives/string``) are resolved separately by
:mod:`app.primitives_resolver`; only same-document fragment refs are captured here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote

from .primitives_scope import iter_refs
from .schema_validation import validate_schema_document

__all__ = [
    "STATUS_INTERNAL",
    "ParsedType",
    "internal_ref_target",
    "build_internal_ref_edges",
    "derive_single_name",
    "parse_json_schema_document",
]

# Edge status marking an intra-document ($defs/definitions) reference. It is distinct
# from the resolver's ``resolved`` / ``unresolved`` (#3456) so the unresolved-ref
# aggregates (#3457) and resolver listings ignore these edges; the rewrite stage
# (#3463) consumes them to turn ``#/$defs/Money`` into a relative registry ref.
STATUS_INTERNAL = "internal"

# Containers of named sub-schemas in a JSON Schema document, paired with the JSON
# Pointer prefix each one maps to. ``$defs`` is the draft 2020-12 keyword; the older
# ``definitions`` is accepted as an equivalent so pre-2020 documents ingest too.
_DEFS_CONTAINERS: Tuple[Tuple[str, str], ...] = (
    ("$defs", "#/$defs"),
    ("definitions", "#/definitions"),
)


def _unescape_pointer_token(token: str) -> str:
    """Decode one JSON Pointer reference token to the literal key it names.

    A ``$ref`` fragment is a URI-encoded `RFC 6901 <https://www.rfc-editor.org/rfc/rfc6901>`_
    JSON Pointer, so a key is first percent-decoded (``%20`` → space) and then has the
    two pointer escapes resolved — ``~1`` → ``/`` and ``~0`` → ``~``, in that order so
    an escaped ``~1`` does not become a slash.

    Args:
        token: A single reference token from a ``$ref`` fragment (e.g. ``Money``).

    Returns:
        The literal member name the token addresses.
    """
    return unquote(token).replace("~1", "/").replace("~0", "~")


def internal_ref_target(ref: str) -> Optional[str]:
    """Return the ``$defs`` / ``definitions`` sibling name an intra-doc ``$ref`` names.

    Only same-document references into a definitions container are intra-document type
    references that the rewrite stage (#3463) remaps. A registry-relative ref
    (``../primitives/string``), an absolute URL, a bare root ref (``#``), or a pointer
    into some other part of the document (``#/properties/x``) is **not** one and yields
    ``None``.

    Args:
        ref: The ``$ref`` value exactly as written in the document.

    Returns:
        The first pointer segment under ``$defs`` / ``definitions`` (the referenced
        type's local name, e.g. ``Money`` for ``#/$defs/Money/properties/c``), or
        ``None`` when the ref does not target a definitions container.
    """
    if not isinstance(ref, str):
        return None
    for _, prefix in _DEFS_CONTAINERS:
        token = f"{prefix}/"
        if ref.startswith(token):
            first_segment = ref[len(token):].split("/", 1)[0]
            if first_segment:
                return _unescape_pointer_token(first_segment)
    return None


def build_internal_ref_edges(schema: Any) -> List[Dict[str, str]]:
    """Capture a fragment's intra-document ``$ref`` edges for later rewrite (#3463).

    Walks every ``$ref`` in ``schema`` and records the ones that target a sibling
    ``$defs`` / ``definitions`` definition as ``internal`` edges, in the same
    ``{relative_ref, resolved_target, status}`` shape persisted on
    ``odb.primitives.refs``. ``resolved_target`` is the referenced type's local name
    (what #3463 maps to a relative registry ref). Duplicate ``$ref`` values are
    recorded once, in first-seen document order; non-internal refs (registry-relative,
    absolute, external) are left for the resolver (#3456).

    Args:
        schema: A parsed JSON Schema fragment (object, array, or scalar).

    Returns:
        The list of internal-ref edges, empty when the fragment has no intra-document
        definitions references.
    """
    edges: List[Dict[str, str]] = []
    seen: set = set()
    for ref in iter_refs(schema):
        if ref in seen:
            continue
        target = internal_ref_target(ref)
        if target is None:
            continue
        seen.add(ref)
        edges.append(
            {"relative_ref": ref, "resolved_target": target, "status": STATUS_INTERNAL}
        )
    return edges


@dataclass
class ParsedType:
    """One discrete type parsed from a JSON Schema document (#3461).

    Attributes:
        name: The type's name — the ``$defs`` / ``definitions`` key, or a derived
            name for a single-root document.
        pointer: A JSON Pointer locating the fragment within the source document
            (``#/$defs/Money`` for a bundled entry, ``#`` for a single root).
        schema: The parsed schema fragment itself, retained for rewrite/persist.
        internal_refs: The fragment's intra-document ``$ref`` edges, captured for
            rewrite (#3463); each is ``{relative_ref, resolved_target, status}`` with
            ``status == "internal"``.
        valid: Whether ``schema`` is a valid draft 2020-12 schema document.
        validation_errors: Field-level errors when ``valid`` is ``False`` (empty
            otherwise), as returned by
            :func:`app.schema_validation.validate_schema_document`.
    """

    name: str
    pointer: str
    schema: Any
    internal_refs: List[Dict[str, str]] = field(default_factory=list)
    valid: bool = True
    validation_errors: List[Dict[str, str]] = field(default_factory=list)

    @property
    def ref_count(self) -> int:
        """Total number of ``$ref`` values anywhere within the fragment."""
        return sum(1 for _ in iter_refs(self.schema))

    @property
    def internal_ref_count(self) -> int:
        """Number of intra-document ``$ref`` edges captured for rewrite."""
        return len(self.internal_refs)

    def as_candidate_dict(self) -> Dict[str, Any]:
        """Return the parsed type as the JSON-serializable staged-candidate mapping.

        Carries the per-type validation report and captured internal refs alongside
        the detection metadata, so the staging report (#3460) and the staged result
        surface them without re-parsing.
        """
        return {
            "name": self.name,
            "pointer": self.pointer,
            "ref_count": self.ref_count,
            "internal_refs": self.internal_refs,
            "valid": self.valid,
            "validation_errors": self.validation_errors,
        }


def derive_single_name(document: Dict[str, Any], source_label: Optional[str]) -> str:
    """Derive a name for a single-root (no ``$defs`` / ``definitions``) document.

    Prefers the document's ``title``, then the last path segment of its ``$id``, then
    the source label (filename stem); falls back to ``"document"`` so a nameless bare
    schema still parses to a usable type name.

    Args:
        document: The parsed single-root document.
        source_label: Optional source label (filename / URL) used as a name fallback.

    Returns:
        A non-empty type name.
    """
    title = document.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()

    doc_id = document.get("$id")
    if isinstance(doc_id, str) and doc_id.strip():
        tail = doc_id.rstrip("/").rsplit("/", 1)[-1]
        if tail:
            return tail

    if source_label and source_label.strip():
        # Strip directory and a trailing filename extension for a cleaner name.
        return source_label.strip().rsplit("/", 1)[-1].rsplit(".", 1)[0] or source_label.strip()

    return "document"


def _parse_fragment(
    name: str, pointer: str, fragment: Any, def_names: set, warnings: List[str]
) -> ParsedType:
    """Build a :class:`ParsedType` from one schema fragment, validating it.

    Captures the fragment's internal refs, runs draft 2020-12 meta-validation, and
    appends a document-level warning for any internal ref that points at a definition
    absent from the document (a dangling intra-doc reference the rewrite stage cannot
    resolve).

    Args:
        name: The type's name.
        pointer: The JSON Pointer locating the fragment in the source document.
        fragment: The parsed schema fragment.
        def_names: The set of all definition names present in the document (used to
            flag dangling internal refs).
        warnings: The document-level warning list, appended to in place.

    Returns:
        The assembled :class:`ParsedType`.
    """
    internal_refs = build_internal_ref_edges(fragment)
    for edge in internal_refs:
        if edge["resolved_target"] not in def_names:
            warnings.append(
                f"Type '{name}' references '{edge['relative_ref']}', "
                f"which is not defined in the document"
            )

    errors = validate_schema_document(fragment)
    return ParsedType(
        name=name,
        pointer=pointer,
        schema=fragment,
        internal_refs=internal_refs,
        valid=not errors,
        validation_errors=errors,
    )


def parse_json_schema_document(
    document: Dict[str, Any], *, source_label: Optional[str] = None
) -> Tuple[List[ParsedType], List[str]]:
    """Parse a JSON Schema 2020-12 document into discrete types (#3461).

    A document carrying a ``$defs`` (or legacy ``definitions``) container is a bundle:
    each named entry becomes one type, so a document with three ``$defs`` yields three
    types. A document with neither container is a single-root document and is itself
    one type. Each type carries its captured internal refs and a per-type validation
    report.

    Args:
        document: The parsed source document (a mapping).
        source_label: Optional source label used to name a single-root document.

    Returns:
        ``(types, warnings)`` — the parsed types in document order, and any non-fatal
        document-level warnings (e.g. a dangling intra-document ``$ref``).
    """
    warnings: List[str] = []

    # Collect every named definition across both containers first, so each fragment's
    # internal refs can be checked against the full set of sibling definitions.
    entries: List[Tuple[str, str]] = []  # (name, pointer) preserving document order
    def_names: set = set()
    for container, pointer_prefix in _DEFS_CONTAINERS:
        block = document.get(container)
        if isinstance(block, dict):
            for key in block:
                entries.append((str(key), f"{pointer_prefix}/{key}"))
                def_names.add(str(key))

    if entries:
        types: List[ParsedType] = []
        for name, pointer in entries:
            container = "$defs" if pointer.startswith("#/$defs/") else "definitions"
            fragment = document[container][name]
            types.append(_parse_fragment(name, pointer, fragment, def_names, warnings))
        return types, warnings

    # No definitions container: the whole document is a single type.
    name = derive_single_name(document, source_label)
    return [_parse_fragment(name, "#", document, def_names, warnings)], warnings
