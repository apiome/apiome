"""Staging orchestrator for the Primitives import pipeline (#3460).

The import pipeline's job in this ticket is *staging*: take an ingested source
document (see :mod:`import_ingestion`), detect the candidate types it carries,
and produce a **staged result** — a list of candidates that a later step parses
into discrete types (#3461/#3462), rewrites refs for (#3463), and reviews for
conflicts (#3464). Nothing is committed to the registry here.

Detection is intentionally *shallow*: it locates the candidate type fragments and
records a cheap per-candidate ref count, but it does not parse, validate, or
rewrite them — those are the downstream tickets. Detection is dispatched on the
source **kind**:

- ``json-schema``: each ``$defs`` / ``definitions`` entry is a candidate; a bare
  document with neither is itself a single candidate.
- ``type-def-bundle``: each entry under ``types`` (or ``$defs`` / ``definitions``)
  is a candidate.
- ``openapi``: each ``components.schemas`` entry is a candidate.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .primitives_bundle import BundleError, parse_type_def_bundle
from .primitives_parser import parse_json_schema_document
from .primitives_scope import iter_refs

# Source document shapes the pipeline understands. Must stay in sync with the
# apiome.primitive_imports.source_kind CHECK constraint.
VALID_SOURCE_KINDS = {"json-schema", "type-def-bundle", "openapi"}


@dataclass
class StagedCandidate:
    """One candidate type detected in a source document, staged for later parsing.

    Attributes:
        name: The candidate's name (the ``$defs`` / schema key, or a derived name
            for a single bare document).
        pointer: A JSON Pointer locating the fragment within the source document
            (e.g. ``#/$defs/Money``), so a later stage can re-read it.
        ref_count: How many ``$ref`` values the fragment contains — a cheap signal
            of how much ref rewriting (#3463) the candidate will need.
        internal_refs: The candidate's intra-document ``$ref`` edges (``#/$defs/...``)
            captured for the rewrite stage (#3463), each
            ``{relative_ref, resolved_target, status}`` with ``status == "internal"``.
            Populated by the JSON Schema parser (#3461); empty for source kinds whose
            deep parse is a later ticket.
        valid: Whether the fragment is a valid draft 2020-12 schema (the per-candidate
            validation report). Defaults to ``True`` for kinds not yet deep-parsed.
        validation_errors: Field-level draft 2020-12 errors when ``valid`` is
            ``False`` (empty otherwise).
    """

    name: str
    pointer: str
    ref_count: int = 0
    internal_refs: List[Dict[str, str]] = field(default_factory=list)
    valid: bool = True
    validation_errors: List[Dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        """Return the candidate as a plain JSON-serializable mapping."""
        return {
            "name": self.name,
            "pointer": self.pointer,
            "ref_count": self.ref_count,
            "internal_refs": self.internal_refs,
            "valid": self.valid,
            "validation_errors": self.validation_errors,
        }


@dataclass
class StagedImport:
    """The staged result of one import: candidates plus their provenance context.

    This is what the staging endpoint returns and (in summarized form) records on
    the ``apiome.primitive_imports`` row, so every source kind/method reaches a staged
    result with an import record (the ticket's acceptance criterion).
    """

    source_kind: str
    source_method: str
    source_label: Optional[str]
    target_namespace: Optional[str]
    candidates: List[StagedCandidate] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    status: str = "staged"

    @property
    def detected_count(self) -> int:
        """Number of candidate types detected in the source."""
        return len(self.candidates)

    def report(self) -> Dict[str, Any]:
        """Build the JSON report persisted on the import provenance record.

        Kept lean — candidate metadata (name / pointer / ref_count) and warnings,
        not the full schema fragments, which a later stage re-reads from source.
        """
        return {
            "status": self.status,
            "detected_count": self.detected_count,
            "staged": [c.as_dict() for c in self.candidates],
            "warnings": self.warnings,
        }


def _ref_count(fragment: Any) -> int:
    """Count the ``$ref`` values anywhere within a schema fragment."""
    return sum(1 for _ in iter_refs(fragment))


def _candidates_from_mapping(
    mapping: Dict[str, Any], pointer_prefix: str
) -> List[StagedCandidate]:
    """Turn a name→fragment mapping into staged candidates under a pointer prefix.

    Non-mapping members (a malformed bundle entry) are skipped by the caller via
    the returned warnings; here every string-keyed member becomes a candidate.
    """
    candidates: List[StagedCandidate] = []
    for name, fragment in mapping.items():
        candidates.append(
            StagedCandidate(
                name=str(name),
                pointer=f"{pointer_prefix}/{name}",
                ref_count=_ref_count(fragment),
            )
        )
    return candidates


def _detect_json_schema(
    document: Dict[str, Any], source_label: Optional[str]
) -> Tuple[List[StagedCandidate], List[str]]:
    """Detect candidates in a JSON Schema document via the 2020-12 parser (#3461).

    Delegates to :func:`app.primitives_parser.parse_json_schema_document`, which
    turns each ``$defs`` / ``definitions`` entry into a discrete type (a document with
    neither container is itself one type), captures each type's intra-document
    ``$ref`` edges for rewrite (#3463), and validates each fragment against draft
    2020-12 — so the staged candidate now carries internal refs and a validation
    report, not just a ref count.
    """
    parsed, warnings = parse_json_schema_document(document, source_label=source_label)
    candidates = [
        StagedCandidate(
            name=p.name,
            pointer=p.pointer,
            ref_count=p.ref_count,
            internal_refs=p.internal_refs,
            valid=p.valid,
            validation_errors=p.validation_errors,
        )
        for p in parsed
    ]
    return candidates, warnings


def _detect_type_def_bundle(
    document: Dict[str, Any], source_label: Optional[str]
) -> Tuple[List[StagedCandidate], List[str]]:
    """Detect candidates in an Apiome type-definition bundle via the expander (#3462).

    Delegates to :func:`app.primitives_bundle.parse_type_def_bundle`, which reads the
    bundle's ``types`` (or legacy ``$defs`` / ``definitions``) container, turns each entry
    into a discrete type, captures its inter-type ``$ref`` edges for rewrite (#3463), and
    validates each fragment against draft 2020-12 — so a staged bundle candidate carries the
    same internal refs and per-type validation report as the JSON Schema path.

    A malformed bundle (no recognizable container, no usable types) is non-fatal at the
    *staging* step: its clear :class:`~app.primitives_bundle.BundleError` message is surfaced
    as a warning with no candidates, mirroring the prior empty-bundle behavior. The commit
    path (``POST /import``) turns the same error into a 400.
    """
    try:
        parsed, warnings = parse_type_def_bundle(document, source_label=source_label)
    except BundleError as exc:
        return [], [exc.message]

    candidates = [
        StagedCandidate(
            name=p.name,
            pointer=p.pointer,
            ref_count=p.ref_count,
            internal_refs=p.internal_refs,
            valid=p.valid,
            validation_errors=p.validation_errors,
        )
        for p in parsed
    ]
    return candidates, warnings


def _detect_openapi(
    document: Dict[str, Any], source_label: Optional[str]
) -> Tuple[List[StagedCandidate], List[str]]:
    """Detect candidates in an OpenAPI document: each ``components/schemas`` entry."""
    warnings: List[str] = []
    components = document.get("components")
    schemas = components.get("schemas") if isinstance(components, dict) else None
    if isinstance(schemas, dict) and schemas:
        return _candidates_from_mapping(schemas, "#/components/schemas"), warnings

    warnings.append("No 'components.schemas' found in the OpenAPI document")
    return [], warnings


_DETECTORS = {
    "json-schema": _detect_json_schema,
    "type-def-bundle": _detect_type_def_bundle,
    "openapi": _detect_openapi,
}


def detect_candidates(
    document: Dict[str, Any], source_kind: str, source_label: Optional[str] = None
) -> Tuple[List[StagedCandidate], List[str]]:
    """Detect the candidate types in a parsed document for a given source kind.

    Args:
        document: The parsed source document (a mapping).
        source_kind: One of :data:`VALID_SOURCE_KINDS`.
        source_label: Optional label used to derive a single-document name.

    Returns:
        ``(candidates, warnings)`` — the detected candidates and any non-fatal
        warnings (e.g. an empty container).

    Raises:
        ValueError: If ``source_kind`` is not recognized.
    """
    detector = _DETECTORS.get(source_kind)
    if detector is None:
        raise ValueError(
            f"Invalid source_kind '{source_kind}'. "
            f"Expected one of: {', '.join(sorted(VALID_SOURCE_KINDS))}"
        )
    return detector(document, source_label)


def build_staged_import(
    document: Dict[str, Any],
    *,
    source_kind: str,
    source_method: str,
    source_label: Optional[str] = None,
    target_namespace: Optional[str] = None,
) -> StagedImport:
    """Stage a parsed document: detect candidates and assemble the staged result.

    This is the pipeline core — pure (no network/DB), so it is unit-testable on a
    parsed document. The route pairs it with :func:`import_ingestion.ingest_source`
    (fetch) and ``db.create_primitive_import`` (record).

    Args:
        document: The parsed source document.
        source_kind: One of :data:`VALID_SOURCE_KINDS`.
        source_method: The intake method (paste/file/url/git), recorded for
            provenance.
        source_label: Optional human label (filename / URL / git path).
        target_namespace: Optional registry namespace the import targets.

    Returns:
        The :class:`StagedImport` result.

    Raises:
        ValueError: If ``source_kind`` is not recognized.
    """
    candidates, warnings = detect_candidates(document, source_kind, source_label)
    return StagedImport(
        source_kind=source_kind,
        source_method=source_method,
        source_label=source_label,
        target_namespace=target_namespace,
        candidates=candidates,
        warnings=warnings,
    )
