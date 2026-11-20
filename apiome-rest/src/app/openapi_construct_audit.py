"""OpenAPI construct losslessness audit and matrix — COA-2.1 (#7044).

OpenAPI is Apiome's core format, so a construct that silently disappears between import and
export is the worst failure it can have. This module states, construct by construct and per
OpenAPI version, what survives the canonical pipeline — and *measures* it:

1. **Catalogue.** :data:`CONSTRUCTS` lists every OpenAPI 3.0 / 3.1 / 3.2 construct the audit
   tracks: an id, a label, the versions it exists in, the RC7 loss-report category it falls
   under when lost (Naming, Type precision, Definitions, Structure, Behaviour, Identity,
   Placeholders) and a matcher that finds its occurrences in a document
   (:mod:`app.openapi_document_walk` supplies each object's kind and pointer).
2. **Audit.** :func:`audit_document` runs one document through import → canonical → emit at
   its own version → re-import → emit again, and gives every occurrence a verdict:

   * ``preserved`` — the value at the occurrence's pointer is identical in both emissions;
   * ``reported`` — it is not, and the emitter recorded a loss at (or above) that pointer;
   * ``silent`` — it is not, and nothing said so. The audit's test fails on any of these.

   It also requires the canonical round trip itself to be lossless (an empty entity diff).
3. **Matrix.** :func:`build_matrix` aggregates a corpus into one cell per construct and
   version, and :func:`render_matrix_markdown` renders the table the docs page
   ``reference/openapi-construct-matrix.md`` publishes. The page is generated from this
   module by ``scripts/generate_openapi_construct_matrix_doc.py`` and drift-tested, so the
   published fidelity statement is always the measured one.

Everything here is pure and deterministic.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .emitter import Loss
from .openapi_document_walk import (
    Node,
    is_missing,
    join_pointer,
    resolve_pointer,
    walk_document,
)
from .openapi_emitter import OpenApiEmitOptions, OpenApiEmitter
from .openapi_import_source import OpenApiImportSource
from .openapi_source_preservation import json_safe, source_family

__all__ = [
    "CONSTRUCTS",
    "VERSIONS",
    "Construct",
    "DocumentAudit",
    "MatrixCell",
    "Occurrence",
    "audit_corpus",
    "audit_document",
    "build_matrix",
    "find_occurrences",
    "load_corpus",
    "render_matrix_markdown",
]

#: The OpenAPI version families the matrix covers, in column order.
VERSIONS: Tuple[str, ...] = ("3.0", "3.1", "3.2")
_ALL = VERSIONS
_SINCE_31 = ("3.1", "3.2")
_ONLY_32 = ("3.2",)

#: The seven loss-report categories (RC7 ship plan §3.1).
CATEGORIES: Tuple[str, ...] = (
    "Naming",
    "Type precision",
    "Definitions",
    "Structure",
    "Behaviour",
    "Identity",
    "Placeholders",
)

#: Media types whose payload is a stream of items (OpenAPI 3.2 "sequential media types").
STREAMING_MEDIA_TYPES = frozenset(
    {
        "text/event-stream",
        "application/jsonl",
        "application/x-ndjson",
        "application/json-seq",
        "application/geo+json-seq",
        "multipart/mixed",
    }
)

#: Finds a construct in one walked object: returns the keys of ``node.value`` that are an
#: occurrence, or ``[""]`` when the object itself is the occurrence.
Matcher = Callable[[Node], List[str]]


@dataclass(frozen=True)
class Construct:
    """One row of the construct matrix.

    Attributes:
        id: Stable kebab-case id (used in tests and the docs anchor).
        label: The construct as the docs table names it.
        versions: The version families the construct exists in.
        category: The loss-report category a loss of this construct belongs to.
        matcher: Finds the construct's occurrences (see :data:`Matcher`).
    """

    id: str
    label: str
    versions: Tuple[str, ...]
    category: str
    matcher: Matcher


def _keys(kinds: Sequence[str], keys: Sequence[str]) -> Matcher:
    """Matcher for fixed ``keys`` on objects of the given ``kinds``."""
    kind_set, key_set = frozenset(kinds), tuple(keys)

    def match(node: Node) -> List[str]:
        if node.kind not in kind_set:
            return []
        return [key for key in key_set if key in node.value]

    return match


def _extensions(node: Node) -> List[str]:
    """Every ``x-`` specification extension, on any object."""
    if node.kind == "callback":
        # A callback's keys are runtime expressions; only ``x-`` keys are extensions.
        return [key for key in node.value if str(key).startswith("x-")]
    return [key for key in node.value if isinstance(key, str) and key.startswith("x-")]


def _streaming_media(node: Node) -> List[str]:
    """A media type entry whose name is a streaming (sequential) media type."""
    if node.kind == "media_type" and (node.name or "").split(";")[0].strip() in STREAMING_MEDIA_TYPES:
        return [""]
    return []


def _querystring(node: Node) -> List[str]:
    """A parameter in the 3.2 ``querystring`` location."""
    return [""] if node.kind == "parameter" and node.value.get("in") == "querystring" else []


def _multiple_media_types(node: Node) -> List[str]:
    """A body or response that offers more than one media type."""
    content = node.value.get("content")
    if node.kind in ("request_body", "response") and isinstance(content, dict) and len(content) > 1:
        return ["content"]
    return []


def _null_type(node: Node) -> List[str]:
    """Nullability: 3.0 ``nullable``, or a 2020-12 ``"null"`` type (3.1+)."""
    if node.kind != "schema":
        return []
    found = ["nullable"] if "nullable" in node.value else []
    type_ = node.value.get("type")
    if type_ == "null" or (isinstance(type_, list) and "null" in type_):
        found.append("type")
    return found


def _reference_siblings(node: Node) -> List[str]:
    """``summary`` / ``description`` written next to a ``$ref`` (3.1+ Reference Object)."""
    if "$ref" not in node.value or node.kind == "schema":
        return []
    return [key for key in ("summary", "description") if key in node.value]


def _component_sections(node: Node) -> List[str]:
    """The reusable component sections other than ``schemas``."""
    if node.kind != "components":
        return []
    return [key for key in node.value if key != "schemas" and not str(key).startswith("x-")]


_SCHEMA_2020_12_KEYWORDS = (
    "const",
    "prefixItems",
    "if",
    "then",
    "else",
    "dependentSchemas",
    "dependentRequired",
    "unevaluatedProperties",
    "unevaluatedItems",
    "contentMediaType",
    "contentEncoding",
    "contentSchema",
    "$defs",
    "$anchor",
    "$id",
    "$schema",
    "$comment",
    "propertyNames",
    "contains",
    "minContains",
    "maxContains",
    "patternProperties",
    "examples",
)

#: The construct catalogue — one matrix row each, in docs order.
CONSTRUCTS: Tuple[Construct, ...] = (
    # --- document ----------------------------------------------------------------
    Construct("self", "`$self` document URI", _ONLY_32, "Identity", _keys(["root"], ["$self"])),
    Construct(
        "json-schema-dialect",
        "`jsonSchemaDialect`",
        _SINCE_31,
        "Type precision",
        _keys(["root"], ["jsonSchemaDialect"]),
    ),
    Construct(
        "info-metadata",
        "Info contact, licence and terms of service",
        _ALL,
        "Definitions",
        _keys(["info"], ["contact", "license", "termsOfService"]),
    ),
    Construct("info-summary", "`info.summary`", _SINCE_31, "Definitions", _keys(["info"], ["summary"])),
    Construct(
        "license-identifier",
        "SPDX `license.identifier`",
        _SINCE_31,
        "Definitions",
        _keys(["license"], ["identifier"]),
    ),
    Construct(
        "servers",
        "Servers and server variables (document, path, operation)",
        _ALL,
        "Behaviour",
        _keys(["root", "path_item", "operation"], ["servers"]),
    ),
    Construct("server-name", "Server `name`", _ONLY_32, "Naming", _keys(["server"], ["name"])),
    Construct("tags", "Tag descriptions and documents", _ALL, "Definitions", _keys(["root"], ["tags"])),
    Construct(
        "tag-hierarchy",
        "Tag `parent`, `kind` and `summary`",
        _ONLY_32,
        "Structure",
        _keys(["tag"], ["parent", "kind", "summary"]),
    ),
    Construct(
        "external-docs",
        "`externalDocs`",
        _ALL,
        "Definitions",
        _keys(["root", "tag", "operation", "schema"], ["externalDocs"]),
    ),
    Construct("extensions", "`x-` specification extensions", _ALL, "Definitions", _extensions),
    Construct(
        "security",
        "Security requirements and schemes",
        _ALL,
        "Behaviour",
        _keys(["root", "operation"], ["security"]),
    ),
    Construct(
        "component-sections",
        "Reusable components other than schemas",
        _ALL,
        "Structure",
        _component_sections,
    ),
    # --- paths and operations ----------------------------------------------------------
    Construct(
        "path-item-fields",
        "Path item summary, description, servers and shared parameters",
        _ALL,
        "Structure",
        _keys(["path_item"], ["summary", "description", "parameters"]),
    ),
    Construct("path-item-ref", "Path item `$ref`", _ALL, "Structure", _keys(["path_item"], ["$ref"])),
    Construct(
        "operation-metadata",
        "Operation id, summary, description, tags and `deprecated`",
        _ALL,
        "Definitions",
        _keys(["operation"], ["operationId", "summary", "description", "tags", "deprecated"]),
    ),
    Construct("query-method", "`QUERY` method", _ONLY_32, "Behaviour", _keys(["path_item"], ["query"])),
    Construct(
        "additional-operations",
        "`additionalOperations` (custom methods)",
        _ONLY_32,
        "Behaviour",
        _keys(["path_item"], ["additionalOperations"]),
    ),
    Construct("callbacks", "Callbacks", _ALL, "Behaviour", _keys(["operation"], ["callbacks"])),
    Construct("webhooks", "Webhooks", _SINCE_31, "Behaviour", _keys(["root"], ["webhooks"])),
    Construct("links", "Response links", _ALL, "Behaviour", _keys(["response"], ["links"])),
    # --- parameters, bodies and responses -------------------------------------------------
    Construct(
        "parameter-serialization",
        "Parameter `style`, `explode`, `allowReserved`, `allowEmptyValue`, `content`",
        _ALL,
        "Structure",
        _keys(["parameter"], ["style", "explode", "allowReserved", "allowEmptyValue", "content"]),
    ),
    Construct(
        "querystring-parameter", "`in: querystring` parameter", _ONLY_32, "Behaviour", _querystring
    ),
    Construct(
        "request-body-required",
        "Request body `required`",
        _ALL,
        "Behaviour",
        _keys(["request_body"], ["required"]),
    ),
    Construct(
        "examples",
        "Examples on parameters, media types and headers",
        _ALL,
        "Definitions",
        _keys(["parameter", "media_type", "header"], ["example", "examples"]),
    ),
    Construct(
        "multiple-media-types",
        "Several media types on one body or response",
        _ALL,
        "Structure",
        _multiple_media_types,
    ),
    Construct(
        "streaming-media-types",
        "Streaming media types (SSE, JSON Lines, JSON Text Sequences, multipart/mixed)",
        _ALL,
        "Behaviour",
        _streaming_media,
    ),
    Construct(
        "item-schema",
        "`itemSchema` for sequential media",
        _ONLY_32,
        "Behaviour",
        _keys(["media_type"], ["itemSchema"]),
    ),
    Construct(
        "encoding",
        "Media type `encoding`",
        _ALL,
        "Structure",
        _keys(["media_type"], ["encoding"]),
    ),
    Construct(
        "positional-encoding",
        "`prefixEncoding` and `itemEncoding`",
        _ONLY_32,
        "Structure",
        _keys(["media_type"], ["prefixEncoding", "itemEncoding"]),
    ),
    Construct(
        "response-headers", "Response headers", _ALL, "Behaviour", _keys(["response"], ["headers"])
    ),
    Construct(
        "response-summary", "Response `summary`", _ONLY_32, "Definitions", _keys(["response"], ["summary"])
    ),
    Construct(
        "reference-siblings",
        "`summary` / `description` beside `$ref`",
        _SINCE_31,
        "Definitions",
        _reference_siblings,
    ),
    # --- schemas -----------------------------------------------------------------------
    Construct(
        "discriminator", "`discriminator`", _ALL, "Structure", _keys(["schema"], ["discriminator"])
    ),
    Construct(
        "composition",
        "`allOf`, `oneOf`, `anyOf`, `not`",
        _ALL,
        "Structure",
        _keys(["schema"], ["allOf", "oneOf", "anyOf", "not"]),
    ),
    Construct("nullability", "Nullability", _ALL, "Type precision", _null_type),
    Construct(
        "dynamic-references",
        "`$dynamicRef` / `$dynamicAnchor`",
        _SINCE_31,
        "Structure",
        _keys(["schema"], ["$dynamicRef", "$dynamicAnchor"]),
    ),
    Construct(
        "json-schema-2020-12",
        "JSON Schema 2020-12 keywords (`const`, `prefixItems`, `if`/`then`/`else`, …)",
        _SINCE_31,
        "Type precision",
        _keys(["schema"], _SCHEMA_2020_12_KEYWORDS),
    ),
    Construct(
        "schema-constraints",
        "Numeric, string, array and object constraints",
        _ALL,
        "Type precision",
        _keys(
            ["schema"],
            [
                "minimum",
                "maximum",
                "exclusiveMinimum",
                "exclusiveMaximum",
                "multipleOf",
                "minLength",
                "maxLength",
                "pattern",
                "minItems",
                "maxItems",
                "uniqueItems",
                "minProperties",
                "maxProperties",
                "enum",
            ],
        ),
    ),
    Construct("schema-format", "Schema `format`", _ALL, "Type precision", _keys(["schema"], ["format"])),
    Construct(
        "schema-annotations",
        "Schema `readOnly`, `writeOnly`, `xml`, `example`, `default`, `deprecated`, `title`",
        _ALL,
        "Definitions",
        _keys(["schema"], ["readOnly", "writeOnly", "xml", "example", "default", "deprecated", "title"]),
    ),
)


@dataclass(frozen=True)
class Occurrence:
    """One construct found at one pointer of one document, with its verdict.

    Attributes:
        construct: The :attr:`Construct.id`.
        pointer: RFC 6901 pointer to the construct's value in the source document.
        verdict: ``preserved``, ``reported`` or ``silent``.
        loss: The loss that reported it (subject: detail), when ``reported``.
    """

    construct: str
    pointer: str
    verdict: str
    loss: Optional[str] = None


@dataclass
class DocumentAudit:
    """The audit of one document (see :func:`audit_document`).

    Attributes:
        name: The document's label (its corpus path).
        version: Its version family.
        occurrences: Every construct occurrence with its verdict.
        round_trip_lossless: Whether the canonical entity diff of the round trip was empty.
        losses: The losses the emitter recorded.
        schema_errors: Meta-schema errors of the emitted document (3.1 / 3.2 only).
    """

    name: str
    version: str
    occurrences: List[Occurrence] = field(default_factory=list)
    round_trip_lossless: bool = True
    losses: List[Loss] = field(default_factory=list)
    schema_errors: List[Dict[str, str]] = field(default_factory=list)

    @property
    def silent(self) -> List[Occurrence]:
        """The occurrences lost without a loss record — each one fails the audit."""
        return [occurrence for occurrence in self.occurrences if occurrence.verdict == "silent"]


def find_occurrences(document: Dict[str, Any], version: str) -> List[Tuple[str, str]]:
    """List every ``(construct id, pointer)`` occurrence in ``document``.

    Only constructs that exist in ``version`` are looked for, so a 3.1 keyword that happens
    to appear in a 3.0 document is not counted against 3.0.
    """
    constructs = [construct for construct in CONSTRUCTS if version in construct.versions]
    found: List[Tuple[str, str]] = []
    for node in walk_document(document):
        for construct in constructs:
            for key in construct.matcher(node):
                pointer = node.pointer if key == "" else join_pointer(node.pointer, key)
                found.append((construct.id, pointer))
    return found


def _emit(document: Dict[str, Any], version: str) -> Tuple[Dict[str, Any], List[Loss], Any]:
    """Import ``document`` and emit it at ``version``; return (document, losses, model)."""
    source = OpenApiImportSource()
    model = source.normalize(copy.deepcopy(document), include_raw=False)
    result = OpenApiEmitter().emit(model, opts=OpenApiEmitOptions(openapi_version=version))
    return result.document, list(result.losses), model


def _reported_by(pointer: str, losses: Iterable[Loss]) -> Optional[Loss]:
    """The first loss recorded at ``pointer``, or at an object that contains it."""
    for loss in losses:
        target = (loss.pointer or "").lstrip("#")
        if target and (pointer == target or pointer.startswith(target + "/")):
            return loss
    return None


def audit_document(name: str, document: Dict[str, Any]) -> DocumentAudit:
    """Audit one OpenAPI document: import → emit → re-import → emit, construct by construct.

    The document is emitted at its own version family (a 3.0 document as 3.0, …), which is
    the losslessness promise; cross-version conversion is reported by the emitter's losses.

    Args:
        name: A label for the document (its corpus path).
        document: The parsed OpenAPI 3.x document.

    Returns:
        The :class:`DocumentAudit`.
    """
    from .diff import diff  # local: the diff engine is only needed here

    version = source_family(document.get("openapi"))
    first, losses, model = _emit(document, version)
    # Re-import through the wire format, as a user re-importing the exported file would.
    second, second_losses, reimported = _emit(OpenApiImportSource().parse(json.dumps(first)), version)
    all_losses = [*losses, *second_losses]

    audit = DocumentAudit(
        name=name,
        version=version,
        round_trip_lossless=diff(model, reimported).is_empty(),
        losses=losses,
    )
    if version in ("3.0", "3.1", "3.2"):
        from .openapi_validator import validate_openapi_document

        # Only errors the export introduced count: the bundled meta-schema can be stricter
        # than a newer OAI test document (meta-schema currency is COA-2.2).
        source_errors = {
            (error.get("path"), error.get("message")) for error in validate_openapi_document(document)
        }
        audit.schema_errors = [
            error
            for error in validate_openapi_document(first)
            if (error.get("path"), error.get("message")) not in source_errors
        ]

    for construct_id, pointer in find_occurrences(document, version):
        expected = resolve_pointer(document, pointer)
        survived = all(
            not is_missing(resolve_pointer(emitted, pointer))
            and resolve_pointer(emitted, pointer) == expected
            for emitted in (first, second)
        )
        if survived:
            audit.occurrences.append(Occurrence(construct_id, pointer, "preserved"))
            continue
        loss = _reported_by(pointer, all_losses)
        if loss is None:
            audit.occurrences.append(Occurrence(construct_id, pointer, "silent"))
        else:
            audit.occurrences.append(
                Occurrence(construct_id, pointer, "reported", f"{loss.subject}: {loss.detail}")
            )
    return audit


@dataclass
class MatrixCell:
    """One construct × version cell of the matrix.

    Attributes:
        construct: The :attr:`Construct.id`.
        version: The version family.
        applicable: Whether the construct exists in this version.
        preserved / reported / silent: Occurrence counts across the corpus.
        documents: How many corpus documents contain the construct.
    """

    construct: str
    version: str
    applicable: bool
    preserved: int = 0
    reported: int = 0
    silent: int = 0
    documents: int = 0

    @property
    def status(self) -> str:
        """``n/a``, ``uncovered`` (no corpus document has it), ``silent``, ``reported`` or ``lossless``."""
        if not self.applicable:
            return "n/a"
        if self.preserved + self.reported + self.silent == 0:
            return "uncovered"
        if self.silent:
            return "silent"
        if self.reported:
            return "reported"
        return "lossless"


def build_matrix(audits: Iterable[DocumentAudit]) -> Dict[Tuple[str, str], MatrixCell]:
    """Aggregate document audits into one :class:`MatrixCell` per construct and version."""
    cells = {
        (construct.id, version): MatrixCell(construct.id, version, version in construct.versions)
        for construct in CONSTRUCTS
        for version in VERSIONS
    }
    for audit in audits:
        seen = set()
        for occurrence in audit.occurrences:
            cell = cells[(occurrence.construct, audit.version)]
            setattr(cell, occurrence.verdict, getattr(cell, occurrence.verdict) + 1)
            seen.add(occurrence.construct)
        for construct_id in seen:
            cells[(construct_id, audit.version)].documents += 1
    return cells


_STATUS_LABELS = {
    "lossless": "✅ Lossless",
    "reported": "⚠️ Reported",
    "silent": "❌ Silent loss",
    "uncovered": "Not covered",
    "n/a": "—",
}


def render_matrix_markdown(
    cells: Dict[Tuple[str, str], MatrixCell], *, corpus_counts: Dict[str, int]
) -> str:
    """Render the matrix as the Markdown table the docs page publishes.

    Args:
        cells: The matrix from :func:`build_matrix`.
        corpus_counts: Corpus documents per version family (shown under the table).

    Returns:
        Markdown: one row per construct (label, category, one cell per version), each cell
        the status plus its occurrence count, followed by the corpus size line.
    """
    header = "| Construct | Loss category | " + " | ".join(f"OpenAPI {v}" for v in VERSIONS) + " |"
    lines = [header, "| --- | --- | " + " | ".join("---" for _ in VERSIONS) + " |"]
    for construct in CONSTRUCTS:
        row = [construct.label, construct.category]
        for version in VERSIONS:
            cell = cells[(construct.id, version)]
            label = _STATUS_LABELS[cell.status]
            if cell.status in ("lossless", "reported", "silent"):
                total = cell.preserved + cell.reported + cell.silent
                label += f" ({total} in {cell.documents} doc{'s' if cell.documents != 1 else ''})"
            row.append(label)
        lines.append("| " + " | ".join(row) + " |")
    counts = ", ".join(f"OpenAPI {v}: {corpus_counts.get(v, 0)}" for v in VERSIONS)
    lines.append("")
    lines.append(f"Corpus documents — {counts}.")
    return "\n".join(lines) + "\n"


def load_corpus(root: Any) -> List[Tuple[str, Dict[str, Any]]]:
    """Load every OpenAPI 3.x document under ``root`` (``*.yaml`` / ``*.yml`` / ``*.json``).

    Args:
        root: A :class:`pathlib.Path` (or path string) of the corpus directory.

    Returns:
        ``(relative path, document)`` pairs sorted by path; files that are not an OpenAPI 3.x
        document (a README, a JSON fragment) are skipped.
    """
    from pathlib import Path

    from .import_ingestion import parse_document

    base = Path(root)
    documents: List[Tuple[str, Dict[str, Any]]] = []
    for path in sorted(base.rglob("*")):
        if path.suffix not in (".yaml", ".yml", ".json") or not path.is_file():
            continue
        # The import pipeline's own loader, so the corpus is read exactly as an import reads it.
        document = parse_document(path.read_text(encoding="utf-8"), source_label=path.name)
        if isinstance(document, dict) and str(document.get("openapi", "")).startswith("3."):
            documents.append((path.relative_to(base).as_posix(), json_safe(document)))
    return documents


def audit_corpus(root: Any) -> List[DocumentAudit]:
    """Audit every document of the corpus under ``root`` (see :func:`load_corpus`)."""
    return [audit_document(name, document) for name, document in load_corpus(root)]
