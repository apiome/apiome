"""Linked-data intake shared by the SHACL, OWL/RDFS and JSON-LD readers — FMT-9.4 (#5471).

The three FMT-9.4 adapters read the same kind of input: an RDF graph written in Turtle, RDF/XML or
JSON-LD, or a JSON-LD context. This module is the hardened front half they share:

* **Loading.** :func:`load_rdf_text` reads one document into an :class:`rdflib.Graph`;
  :func:`load_json_document` reads one JSON(-LD) document. Both refuse a non-UTF-8 upload, apply
  the shared intake size and depth guards, and turn a syntax failure into a taxonomy code —
  ``INPUT_TRUNCATED`` when the bytes end while a construct is still open, ``INPUT_MALFORMED``
  otherwise. RDF/XML passes the hardened XML parser (no DTD, entity or external reference) before
  ``rdflib`` sees it.
* **No network.** Nothing here fetches anything. An ``owl:imports`` target or a JSON-LD
  ``@context`` / ``@import`` reference must be a member of the upload; a reference outside it is
  refused as ``INPUT_REFERENCE_UNRESOLVED`` and named, never silently treated as empty. The only
  exception is an ``owl:imports`` of a well-known W3C / DCMI vocabulary
  (:data:`WELL_KNOWN_VOCABULARIES`): it is kept as a declared external import.
* **Filesets.** :func:`load_rdf_document` reads a single file or a fileset: every RDF member is
  loaded and merged, and every ``owl:imports`` must resolve to an ontology another member declares.

Taxonomy codes raised (on :class:`RdfParseError`):

* ``INPUT_ENCODING_INVALID`` — a byte-order mark, NULs or U+FFFD replacement characters (a UTF-16
  upload decoded as UTF-8);
* ``INPUT_TRUNCATED`` / ``INPUT_MALFORMED`` — see above;
* ``INPUT_REFERENCE_UNRESOLVED`` — an import or context outside the upload;
* the intake guard's own codes (``INPUT_TOO_LARGE``, ``INPUT_DEPTH_LIMIT``, ``INPUT_UNSAFE_CONSTRUCT``).
"""

from __future__ import annotations

import json
import posixpath
import re
import warnings
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from rdflib import Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, XSD, Namespace

from .fileset import IntakeFileset
from .intake_resource_guard import IntakeLimitError, guard_document_text, guard_parsed_document
from .secure_xml import SecureXmlError, parse_xml

__all__ = [
    "OWL",
    "RDF",
    "RDFS",
    "RDF_SUFFIXES",
    "SH",
    "SKOS",
    "DCT",
    "WELL_KNOWN_VOCABULARIES",
    "XSD",
    "XSD_TO_CANONICAL",
    "assign_type_keys",
    "RdfDocument",
    "RdfParseError",
    "RdfSource",
    "datatype_ref_name",
    "is_rdf_member",
    "json_has_context",
    "literal_text",
    "literal_value",
    "load_json_document",
    "load_rdf_document",
    "load_rdf_text",
    "local_name",
    "read_list",
    "refuse_encoding_faults",
    "refuse_unresolved_contexts",
    "resolve_json_contexts",
    "sniff_syntax",
]

#: The SHACL namespace.
SH = Namespace("http://www.w3.org/ns/shacl#")
#: The SKOS namespace (code lists and preferred labels).
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
#: DCMI terms (ontology titles and licences).
DCT = Namespace("http://purl.org/dc/terms/")

#: File suffixes read as RDF in a fileset (anything else — a README, a licence — is ignored).
RDF_SUFFIXES: Tuple[str, ...] = (".ttl", ".turtle", ".nt", ".n3", ".owl", ".rdf", ".xml", ".jsonld", ".json")

#: Vocabularies an ``owl:imports`` may name without being part of the upload. Importing one of
#: these is how a shapes graph or an ontology says "I build on DCAT" — the vocabulary is
#: published, stable and not the thing being cataloged, so the import is declared, not refused.
WELL_KNOWN_VOCABULARIES: Tuple[str, ...] = (
    "http://www.w3.org/1999/02/22-rdf-syntax-ns",
    "http://www.w3.org/2000/01/rdf-schema",
    "http://www.w3.org/2002/07/owl",
    "http://www.w3.org/2001/XMLSchema",
    "http://www.w3.org/ns/shacl",
    "http://www.w3.org/2004/02/skos/core",
    "http://www.w3.org/ns/dcat",
    "http://www.w3.org/ns/prov",
    "http://www.w3.org/ns/org",
    "http://www.w3.org/ns/dqv",
    "http://www.w3.org/ns/locn",
    "http://www.w3.org/2006/time",
    "http://www.w3.org/2006/vcard/ns",
    "http://www.w3.org/ns/adms",
    "http://www.opengis.net/ont/geosparql",
    "http://purl.org/dc/terms",
    "http://purl.org/dc/elements/1.1",
    "http://xmlns.com/foaf/0.1",
    "https://schema.org",
    "http://schema.org",
)

#: XML Schema datatype (local name) → canonical scalar name. ``anyURI`` keeps ``string`` with a
#: ``uri`` format, set by the caller; the rest of the XSD string family is plain ``string``.
XSD_TO_CANONICAL: Dict[str, str] = {
    "string": "string",
    "normalizedString": "string",
    "token": "string",
    "language": "string",
    "Name": "string",
    "NCName": "string",
    "NMTOKEN": "string",
    "anyURI": "uri",
    "boolean": "boolean",
    "decimal": "decimal",
    "integer": "integer",
    "nonNegativeInteger": "integer",
    "positiveInteger": "integer",
    "nonPositiveInteger": "integer",
    "negativeInteger": "integer",
    "long": "int64",
    "int": "int32",
    "short": "int16",
    "byte": "int8",
    "unsignedLong": "uint64",
    "unsignedInt": "uint32",
    "unsignedShort": "uint16",
    "unsignedByte": "uint8",
    "float": "float",
    "double": "double",
    "date": "date",
    "dateTime": "datetime",
    "dateTimeStamp": "datetime",
    "time": "time",
    "duration": "duration",
    "dayTimeDuration": "duration",
    "yearMonthDuration": "duration",
    "gYear": "string",
    "gYearMonth": "string",
    "gMonth": "string",
    "gMonthDay": "string",
    "gDay": "string",
    "hexBinary": "bytes",
    "base64Binary": "bytes",
}


#: Characters that betray a non-UTF-8 upload decoded as UTF-8.
_ENCODING_FAULT_MARKERS = ("\x00", "�")

#: How deep JSON-LD context references may chain (a context file that references another …).
_MAX_CONTEXT_DEPTH = 8


class RdfParseError(ValueError):
    """The input is not a readable linked-data document.

    Args:
        message: Human-readable description, naming the file where it can.
        code: The intake taxonomy code (see the module docstring).
    """

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        """Keep the taxonomy code beside the message."""
        super().__init__(message)
        self.code = code


# ===========================================================================
# Small RDF helpers
# ===========================================================================


def local_name(iri: Any) -> str:
    """The local part of an IRI (after the last ``#``, ``/`` or ``:``), or the IRI itself."""
    text = str(iri).rstrip("#/")
    for separator in ("#", "/", ":"):
        if separator in text:
            candidate = text.rsplit(separator, 1)[1]
            if candidate:
                return candidate
    return text


def literal_text(graph: Graph, subject: Any, predicate: Any, *, language: str = "en") -> Optional[str]:
    """One literal value of ``predicate`` on ``subject`` as text, preferring ``language``.

    A language-tagged value in ``language`` wins, then an untagged value, then the first value in
    a stable (sorted) order — so a multilingual label always reads the same.
    """
    values = sorted((o for o in graph.objects(subject, predicate) if isinstance(o, Literal)), key=_literal_sort_key)
    if not values:
        return None
    for preferred in (language, None):
        for value in values:
            if value.language == preferred:
                return str(value)
    return str(values[0])


def _literal_sort_key(value: Literal) -> Tuple[str, str]:
    """Sort key that orders literals by language tag, then text."""
    return (value.language or "", str(value))


def literal_value(node: Any) -> Any:
    """A JSON-safe Python value for an RDF term: a literal's value, an IRI's text."""
    if isinstance(node, Literal):
        value = node.toPython()
        if isinstance(value, bool) or isinstance(value, (int, float, str)):
            return value
        return str(node)
    return str(node)


def read_list(graph: Graph, node: Any) -> List[Any]:
    """The members of an RDF collection (``( a b c )``), or ``[]`` when ``node`` is not one."""
    if node is None or node == RDF.nil:
        return []
    if (node, RDF.first, None) not in graph:
        return []
    return list(Collection(graph, node))


def datatype_ref_name(datatype: Any) -> Tuple[Optional[str], Optional[str]]:
    """Map an XSD (or RDF literal) datatype IRI onto a canonical scalar name.

    Returns:
        ``(scalar, format)``: the canonical scalar (``None`` when the datatype is not an XSD or RDF
        literal type) and a ``format`` hint (``uri`` for ``xsd:anyURI``, else ``None``).
    """
    text = str(datatype)
    if text.startswith(str(XSD)):
        name = XSD_TO_CANONICAL.get(text[len(str(XSD)) :])
        if name == "uri":
            return "string", "uri"
        return name, None
    if datatype in (RDF.langString, RDFS.Literal, RDF.PlainLiteral, RDF.HTML, RDF.XMLLiteral):
        return "string", None
    if datatype == RDF.JSON:
        return "any", None
    return None, None


# ===========================================================================
# Text loading and syntax-error classification
# ===========================================================================


def refuse_encoding_faults(text: str, label: str) -> None:
    """Refuse text that was decoded from a non-UTF-8 upload."""
    if text.startswith("﻿") or any(marker in text for marker in _ENCODING_FAULT_MARKERS):
        raise RdfParseError(
            f"{label} is not UTF-8 text (it carries a byte-order mark, NULs or replacement "
            "characters — a UTF-16 upload?). Save it as UTF-8 and import it again.",
            code="INPUT_ENCODING_INVALID",
        )


def _guard_text(text: str, label: str) -> None:
    """Refuse non-UTF-8 or empty text and apply the shared pre-parse intake guards."""
    refuse_encoding_faults(text, label)
    if not text.strip():
        raise RdfParseError(f"{label} is empty", code="INPUT_EMPTY")
    try:
        guard_document_text(text, source_label=label)
    except IntakeLimitError as exc:
        raise RdfParseError(str(exc), code=exc.code) from exc


def sniff_syntax(text: str, filename: Optional[str] = None) -> str:
    """Pick the RDF syntax of a document: ``json-ld``, ``xml`` or ``turtle``.

    The content decides (a ``{`` / ``[`` is JSON, a ``<`` that opens an element is XML); the file
    name only breaks the tie for an empty-looking prefix. Turtle is the default.
    """
    stripped = text.lstrip("﻿ \t\r\n")
    if stripped.startswith(("{", "[")):
        return "json-ld"
    # An element name (``rdf:RDF``, ``Ontology``) followed by whitespace, ``>`` or ``/>`` is XML; a
    # Turtle IRI subject (``<https://…>``) is not — ``https:`` is followed by ``//``.
    if re.match(r"<(\?xml|!--|!DOCTYPE|[A-Za-z_][\w.-]*(:[A-Za-z_][\w.-]*)?(\s|>|/>))", stripped):
        return "xml"
    suffix = PurePosixPath((filename or "").lower()).suffix
    if suffix in (".jsonld", ".json"):
        return "json-ld"
    if suffix in (".rdf", ".xml") and stripped.startswith("<"):
        return "xml"
    if suffix == ".nt":
        return "nt"
    return "turtle"


def _turtle_open_at_eof(text: str) -> bool:
    """Whether a Turtle text ends while a bracket, list, string or IRI is still open.

    A lexical scan (comments skipped): an unclosed ``[`` / ``(``, a string literal or an IRI with
    nothing but whitespace after the point it broke off means the bytes ran out — truncation. An
    IRI or short string broken by a newline *followed by more content* is a malformed line instead.
    """
    depth = 0
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "#":
            newline = text.find("\n", index)
            if newline < 0:
                return depth > 0
            index = newline + 1
            continue
        if char == "<":
            end = index + 1
            while end < length and text[end] not in ">\n":
                end += 1
            if end >= length:
                return True
            if text[end] == "\n":
                return not text[end:].strip()
            index = end + 1
            continue
        if char in "\"'":
            long_quote = text.startswith(char * 3, index)
            end = index + (3 if long_quote else 1)
            closer = char * 3 if long_quote else char
            while end < length:
                if text[end] == "\\":
                    end += 2
                    continue
                if text.startswith(closer, end):
                    break
                if not long_quote and text[end] == "\n":
                    return not text[end:].strip()
                end += 1
            if end >= length:
                return True
            index = end + len(closer)
            continue
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        index += 1
    return depth > 0


def _syntax_message(exc: Exception) -> str:
    """A one-line description of an ``rdflib`` syntax error: ``line 12: EOF found after object``."""
    text = str(exc)
    line = re.search(r"at line (\d+)", text)
    reason = re.search(r"Bad syntax \((.*?)\) at \^", text, re.S)
    if reason:
        return f"line {line.group(1)}: {reason.group(1)}" if line else reason.group(1)
    return text.split("\n", 1)[0]


def _is_json_truncation(exc: json.JSONDecodeError, text: str) -> bool:
    """Whether a JSON failure is the stream ending rather than a wrong token."""
    return exc.pos >= len(text.rstrip()) or exc.msg.startswith("Unterminated string")


def load_json_document(text: str, *, label: str) -> Any:
    """Load one JSON(-LD) document under the shared intake guards.

    Raises:
        RdfParseError: ``INPUT_TRUNCATED`` when the stream ends mid-value, ``INPUT_MALFORMED`` for
            any other syntax error, or the guard's code for an oversized or too-deep document.
    """
    _guard_text(text, label)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        if _is_json_truncation(exc, text):
            raise RdfParseError(
                f"{label} ends while a JSON value is still open — the upload is truncated: {exc}",
                code="INPUT_TRUNCATED",
            ) from exc
        raise RdfParseError(f"{label} is not valid JSON: {exc}", code="INPUT_MALFORMED") from exc
    try:
        guard_parsed_document(parsed, source_label=label)
    except IntakeLimitError as exc:
        raise RdfParseError(str(exc), code=exc.code) from exc
    return parsed


# ===========================================================================
# JSON-LD context references
# ===========================================================================


def json_has_context(document: Any) -> bool:
    """Whether a loaded JSON value carries a top-level ``@context`` (or is a list of such nodes)."""
    if isinstance(document, dict):
        return "@context" in document
    if isinstance(document, list):
        return any(isinstance(item, dict) and "@context" in item for item in document)
    return False


def _member_path(reference: str, current: str) -> str:
    """A relative context reference resolved against the referencing member's directory."""
    base = posixpath.dirname(current)
    return posixpath.normpath(posixpath.join(base, reference.split("#", 1)[0]))


def resolve_json_contexts(
    document: Any,
    *,
    path: str,
    members: Mapping[str, str],
    unresolved: Optional[List[str]] = None,
    resolved: Optional[List[str]] = None,
    _depth: int = 0,
) -> Any:
    """Return ``document`` with every ``@context`` / ``@import`` reference inlined from the upload.

    A context entry that is a string is a reference to another context document. It is looked up
    among ``members`` (resolved against ``path``'s directory) and replaced by that document's
    ``@context`` value. Nothing is fetched: a remote URL, or a relative path the upload does not
    contain, is appended to ``unresolved`` and left out.

    Args:
        document: The loaded JSON value.
        path: The upload path of the document being resolved (for relative references).
        members: Every member of the upload, by path (empty for a single file).
        unresolved: Collects the references that could not be resolved.
        resolved: Collects the member paths that were inlined.

    Returns:
        A copy of ``document`` whose contexts hold only objects.
    """
    unresolved = [] if unresolved is None else unresolved
    resolved = [] if resolved is None else resolved
    if isinstance(document, list):
        return [
            resolve_json_contexts(
                item, path=path, members=members, unresolved=unresolved, resolved=resolved, _depth=_depth
            )
            for item in document
        ]
    if not isinstance(document, dict):
        return document
    result: Dict[str, Any] = {}
    for key, value in document.items():
        if key == "@context":
            result[key] = _resolve_context_value(value, path, members, unresolved, resolved, _depth)
        else:
            result[key] = resolve_json_contexts(
                value, path=path, members=members, unresolved=unresolved, resolved=resolved, _depth=_depth
            )
    return result


def _resolve_context_value(
    value: Any, path: str, members: Mapping[str, str], unresolved: List[str], resolved: List[str], depth: int
) -> Any:
    """Inline one ``@context`` value (a string, an object, or an array of them)."""
    entries = value if isinstance(value, list) else [value]
    out: List[Any] = []
    for entry in entries:
        if isinstance(entry, str):
            out.extend(_dereference_context(entry, path, members, unresolved, resolved, depth))
        elif isinstance(entry, dict):
            out.append(_resolve_context_object(entry, path, members, unresolved, resolved, depth))
        else:
            out.append(entry)
    if not isinstance(value, list) and len(out) == 1:
        return out[0]
    return out


def _resolve_context_object(
    entry: Dict[str, Any], path: str, members: Mapping[str, str], unresolved: List[str], resolved: List[str], depth: int
) -> Dict[str, Any]:
    """Inline an ``@import`` and every scoped ``@context`` inside one context object."""
    local: Dict[str, Any] = {}
    imported: Dict[str, Any] = {}
    for key, definition in entry.items():
        if key == "@import" and isinstance(definition, str):
            for item in _dereference_context(definition, path, members, unresolved, resolved, depth):
                if isinstance(item, dict):
                    imported.update(item)
            continue
        if isinstance(definition, dict) and "@context" in definition:
            definition = {
                **definition,
                "@context": _resolve_context_value(definition["@context"], path, members, unresolved, resolved, depth),
            }
        local[key] = definition
    # JSON-LD 1.1 @import: the imported definitions apply first; the local ones override them.
    return {**imported, **local}


def _dereference_context(
    reference: str, path: str, members: Mapping[str, str], unresolved: List[str], resolved: List[str], depth: int
) -> List[Any]:
    """The context entries a string reference stands for, or ``[]`` (recorded as unresolved)."""
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", reference):
        unresolved.append(reference)
        return []
    target = _member_path(reference, path)
    if target not in members or depth >= _MAX_CONTEXT_DEPTH:
        unresolved.append(reference)
        return []
    loaded = load_json_document(members[target], label=target)
    if not isinstance(loaded, dict) or "@context" not in loaded:
        unresolved.append(reference)
        return []
    if target not in resolved:
        resolved.append(target)
    inner = _resolve_context_value(loaded["@context"], target, members, unresolved, resolved, depth + 1)
    return inner if isinstance(inner, list) else [inner]


def refuse_unresolved_contexts(unresolved: Sequence[str], label: str) -> None:
    """Raise ``INPUT_REFERENCE_UNRESOLVED`` naming every context reference outside the upload."""
    if unresolved:
        names = ", ".join(f"'{name}'" for name in dict.fromkeys(unresolved))
        raise RdfParseError(
            f"{label} references JSON-LD context(s) {names} that are not part of the upload. Apiome "
            "never fetches a remote context: add each context document to the upload (a .zip with "
            "the referencing file) and import it again.",
            code="INPUT_REFERENCE_UNRESOLVED",
        )


# ===========================================================================
# RDF documents
# ===========================================================================


@dataclass(frozen=True)
class RdfSource:
    """One loaded RDF file.

    Attributes:
        path: The file's name or upload path.
        syntax: ``turtle``, ``xml``, ``nt`` or ``json-ld``.
        text: The file's text, exactly as uploaded.
        graph: The file's own triples.
        ontologies: IRIs the file declares ``a owl:Ontology`` (and their ``owl:versionIRI`` s).
        imports: The ``owl:imports`` targets the file declares, sorted.
        prefixes: The prefixes the file binds (prefix → namespace).
    """

    path: str
    syntax: str
    text: str
    graph: Graph
    ontologies: Tuple[str, ...]
    imports: Tuple[str, ...]
    prefixes: Tuple[Tuple[str, str], ...]


@dataclass
class RdfDocument:
    """A loaded RDF import: one file or a fileset, merged into one graph.

    Attributes:
        graph: Every source's triples, merged.
        sources: The loaded files, the root first.
        external_imports: ``owl:imports`` of well-known vocabularies that are not in the upload.
        is_fileset: Whether the import was a fileset.
    """

    graph: Graph
    sources: Tuple[RdfSource, ...]
    external_imports: Tuple[str, ...] = ()
    is_fileset: bool = False
    _prefixes: List[Tuple[str, str]] = field(default_factory=list, repr=False)
    _files: Dict[Any, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        """Index the sources' prefixes (longest namespace first) and the file describing each subject."""
        seen: Set[str] = set()
        for source in self.sources:
            for prefix, namespace in source.prefixes:
                if prefix and namespace not in seen:
                    seen.add(namespace)
                    self._prefixes.append((prefix, namespace))
        # Longest namespace first, so ``ex:`` never shadows ``exschema:`` style overlaps.
        self._prefixes.sort(key=lambda pair: (-len(pair[1]), pair[0]))
        for source in self.sources:
            for subject in source.graph.subjects(unique=True):
                self._files.setdefault(subject, source.path)

    @property
    def root(self) -> RdfSource:
        """The root (first) source."""
        return self.sources[0]

    @property
    def ontologies(self) -> Tuple[str, ...]:
        """Every ontology IRI the sources declare, in source order."""
        return tuple(iri for source in self.sources for iri in source.ontologies)

    def file_of(self, node: Any) -> Optional[str]:
        """The upload path of the file that describes ``node`` (only meaningful in a fileset)."""
        return self._files.get(node) if self.is_fileset else None

    def compact(self, iri: Any) -> str:
        """``iri`` in prefixed form (``ex:Person``) using the document's own prefixes, else ``<iri>``."""
        text = str(iri)
        for prefix, namespace in self._prefixes:
            if text.startswith(namespace) and len(text) > len(namespace):
                return f"{prefix}:{text[len(namespace) :]}"
        return f"<{text}>"

    def prefix_of(self, iri: Any) -> Optional[str]:
        """The document prefix whose namespace ``iri`` is in, if any."""
        text = str(iri)
        for prefix, namespace in self._prefixes:
            if text.startswith(namespace):
                return prefix
        return None

    def raw_record(self) -> Dict[str, Any]:
        """The lossless native record kept on ``CanonicalApi.raw``: every file's text."""
        return {
            "files": [{"path": source.path, "syntax": source.syntax, "text": source.text} for source in self.sources]
        }


def is_rdf_member(path: str) -> bool:
    """Whether a fileset member is read as RDF (by suffix)."""
    return PurePosixPath(path.lower()).suffix in RDF_SUFFIXES


def _ontology_key(iri: str) -> str:
    """An ontology IRI with the trailing ``#`` / ``/`` dropped, for import matching."""
    return iri.rstrip("#/")


def load_rdf_text(text: str, *, label: str, members: Optional[Mapping[str, str]] = None) -> RdfSource:
    """Read one RDF document (Turtle, N-Triples, RDF/XML or JSON-LD) into a graph.

    Args:
        text: The document text.
        label: The file name (or upload path) — used for syntax selection and in messages.
        members: The upload's other members, against which a JSON-LD ``@context`` reference is
            resolved (empty for a single file).

    Raises:
        RdfParseError: With the taxonomy code of the failure (see the module docstring).
    """
    _guard_text(text, label)
    syntax = sniff_syntax(text, label)
    graph = Graph(bind_namespaces="none")
    public_id = "urn:apiome:rdf:" + re.sub(r"[^A-Za-z0-9._-]", "_", label)
    if syntax == "json-ld":
        document = load_json_document(text, label=label)
        unresolved: List[str] = []
        inlined = resolve_json_contexts(document, path=label, members=members or {}, unresolved=unresolved)
        refuse_unresolved_contexts(unresolved, label)
        data = json.dumps(inlined)
        try:
            with warnings.catch_warnings():
                # rdflib's JSON-LD reader builds a ConjunctiveGraph internally and warns about it.
                warnings.simplefilter("ignore", DeprecationWarning)
                graph.parse(data=data, format="json-ld", publicID=public_id)
        except Exception as exc:  # noqa: BLE001 - rdflib raises assorted types for bad JSON-LD
            raise RdfParseError(f"{label} is not valid JSON-LD: {exc}", code="INPUT_MALFORMED") from exc
    elif syntax == "xml":
        try:
            parse_xml(text, source_label=label)
        except SecureXmlError as exc:
            raise RdfParseError(str(exc), code=exc.code) from exc
        try:
            graph.parse(data=text, format="xml", publicID=public_id)
        except Exception as exc:  # noqa: BLE001 - rdflib's RDF/XML reader raises assorted types
            raise RdfParseError(f"{label} is not valid RDF/XML: {exc}", code="INPUT_MALFORMED") from exc
    else:
        try:
            graph.parse(data=text, format=syntax, publicID=public_id)
        except Exception as exc:  # noqa: BLE001 - BadSyntax and friends
            message = _syntax_message(exc)
            if syntax == "turtle" and _turtle_open_at_eof(text):
                raise RdfParseError(
                    f"{label} ends while a bracket, list, string or IRI is still open — the upload is "
                    f"truncated ({message})",
                    code="INPUT_TRUNCATED",
                ) from exc
            raise RdfParseError(f"{label} is not valid Turtle: {message}", code="INPUT_MALFORMED") from exc
    ontologies: List[str] = []
    for subject in sorted(graph.subjects(RDF.type, OWL.Ontology), key=str):
        if isinstance(subject, URIRef):
            ontologies.append(str(subject))
            ontologies.extend(sorted(str(v) for v in graph.objects(subject, OWL.versionIRI)))
    imports = tuple(sorted({str(o) for o in graph.objects(None, OWL.imports) if isinstance(o, URIRef)}))
    prefixes = tuple(sorted((str(prefix), str(namespace)) for prefix, namespace in graph.namespaces() if str(prefix)))
    return RdfSource(
        path=label,
        syntax=syntax,
        text=text,
        graph=graph,
        ontologies=tuple(ontologies),
        imports=imports,
        prefixes=prefixes,
    )


def _is_well_known(iri: str) -> bool:
    """Whether ``iri`` names one of :data:`WELL_KNOWN_VOCABULARIES`."""
    return _ontology_key(iri) in WELL_KNOWN_VOCABULARIES


def load_rdf_document(
    text: Optional[str] = None, *, label: str, fileset: Optional[IntakeFileset] = None
) -> RdfDocument:
    """Read a single RDF file or an RDF fileset and check every ``owl:imports`` resolves.

    In a fileset every RDF member (by suffix) is loaded — the root first — and merged. Each
    ``owl:imports`` must name an ontology (or ontology version) some member declares; an import of
    a well-known vocabulary is kept as a declared external import; any other is refused.

    Args:
        text: The document text (single-file import).
        label: The file name or import label.
        fileset: The fileset (fileset import); ``text`` is ignored when given.

    Raises:
        RdfParseError: With the taxonomy code of the failure.
    """
    if fileset is not None:
        members = dict(fileset.members)
        paths = [fileset.root] + sorted(p for p in members if p != fileset.root and is_rdf_member(p))
        sources = tuple(load_rdf_text(members[p], label=p, members=members) for p in paths)
    else:
        sources = (load_rdf_text(text or "", label=label),)
    declared = {_ontology_key(iri) for source in sources for iri in source.ontologies}
    external: List[str] = []
    missing: List[Tuple[str, str]] = []
    for source in sources:
        for target in source.imports:
            if _ontology_key(target) in declared:
                continue
            if _is_well_known(target):
                external.append(target)
            else:
                missing.append((source.path, target))
    if missing:
        listed = "; ".join(f"{path} imports <{target}>" for path, target in missing)
        raise RdfParseError(
            f"owl:imports cannot be resolved: {listed}. Apiome never fetches an imported ontology: "
            "add the imported file to the upload (a .zip of the set) and import it again.",
            code="INPUT_REFERENCE_UNRESOLVED",
        )
    merged = Graph(bind_namespaces="none")
    for source in sources:
        for triple in source.graph:
            merged.add(triple)
    return RdfDocument(
        graph=merged,
        sources=sources,
        external_imports=tuple(sorted(set(external))),
        is_fileset=fileset is not None,
    )


def assign_type_keys(document: "RdfDocument", nodes: Sequence[Any]) -> Dict[Any, str]:
    """IRI → canonical type key: the local name, prefix-qualified only where two local names collide.

    Args:
        document: The loaded document (for its prefixes).
        nodes: The IRIs that become named types.

    Returns:
        A key for every node, unique across ``nodes``.
    """
    by_name: Dict[str, List[Any]] = {}
    for node in sorted(nodes, key=str):
        by_name.setdefault(local_name(node), []).append(node)
    keys: Dict[Any, str] = {}
    used: Set[str] = set()
    for name, owners in sorted(by_name.items()):
        for node in owners:
            prefix = document.prefix_of(node) if len(owners) > 1 else None
            key = base = f"{prefix}.{name}" if prefix else name
            counter = 2
            while key in used:
                key = f"{base}{counter}"
                counter += 1
            used.add(key)
            keys[node] = key
    return keys
