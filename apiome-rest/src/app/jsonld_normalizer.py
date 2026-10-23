"""JSON-LD context → canonical model — FMT-9.4 (#5471).

A JSON-LD context is the mapping layer between JSON property names and IRIs. This module reads one
(a single ``.jsonld`` file, or a fileset whose context array references sibling context files) and
maps it onto the **data_schema** paradigm:

.. code-block:: text

    "@context": { … }                          → RECORD  <FileName> (one field per term)
    "email": { "@id": "schema:email" }         → field   email   (native_id https://schema.org/email)
    "birthDate": { "@type": "xsd:date" }       → field   birthDate : date
    "homepage": { "@type": "@id" }             → field   homepage : string (format iri)
    "knows": { "@container": "@set" }          → field   knows : list
    "labels": { "@container": "@language" }    → field   labels : LanguageMap (string → string)
    "address": { "@context": { … } }           → RECORD  Address, and field address : Address
    "status": { "@type": "@vocab", "@context": { "new": … } }
                                               → ENUM    Status (new, paid)

Terms become property names and the IRI each term expands to is kept as ``native_id`` provenance
(with the term definition as written in ``extras['jsonld_definition']``). Prefix definitions
(``"schema": "https://schema.org/"``), keyword aliases (``"id": "@id"``) and class names
(``"Dataset": "dcat:Dataset"``) are not properties; they are recorded on the root record's extras.
Context arrays are merged in order (a later definition overrides an earlier one), and a
string entry is another context document, inlined from the upload by :mod:`app.rdf_graph` —
nothing is fetched, and a context outside the upload is refused as ``INPUT_REFERENCE_UNRESOLVED``.

JSON-LD has no cardinality, so every field is optional. Declared limits
(``extras['jsonld']['capability_limits']``): the open vocabulary ``@vocab`` implies, instance data
in the document (``@graph``), reverse properties and graph containers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from rdflib import URIRef

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    EnumValue,
    Type,
    TypeKind,
    TypeRef,
)
from .fileset import IntakeFileset
from .inference_provenance import SYNTHESIZED, provenance_extras
from .normalizer import Keys, Normalizer, normalize_ordering
from .rdf_graph import (
    RdfParseError,
    datatype_ref_name,
    json_has_context,
    load_json_document,
    local_name,
    refuse_unresolved_contexts,
    resolve_json_contexts,
)
from .typescript_types_normalizer import _limits_payload
from .typescript_types_parser import LimitRecorder

__all__ = [
    "FORMAT_KEY",
    "JSONLD_EXTRAS_KEY",
    "JsonLdDocument",
    "JsonLdNormalizer",
    "LIMIT_DETAILS",
    "NO_CONTEXT_MARKER",
    "PARTIAL_LIMITS",
    "read_jsonld",
]

#: Adapter and canonical format key.
FORMAT_KEY = "jsonld"

#: Root extras key of the projection record.
JSONLD_EXTRAS_KEY = "jsonld"

#: Prefix of the message raised for a JSON document with no ``@context`` (the import source turns
#: it into ``FORMAT_MISMATCH`` when another adapter claims the document).
NO_CONTEXT_MARKER = "has no @context"

#: The declared-limit vocabulary (stable keys → reviewed sentence).
LIMIT_DETAILS: Dict[str, str] = {
    "jsonld.open_vocabulary": (
        "The context sets @vocab, so any JSON key it does not define still expands to an IRI under "
        "the vocabulary. Only the defined terms are fields; the open vocabulary is kept in "
        "extras['jsonld_vocab']."
    ),
    "jsonld.instance_data": (
        "The document carries instance data (@graph or node properties) beside its context. A "
        "context import catalogs the vocabulary; the nodes are counted in "
        "extras['jsonld']['instance_data'], not imported."
    ),
    "jsonld.reverse_property": (
        "A reverse property (@reverse) states the relationship from the other node's side; it is a "
        "field here, with the reversed IRI kept in extras['jsonld_reverse']."
    ),
    "jsonld.graph_container": (
        "A @graph container holds named graphs, which the canonical model has no shape for; the field "
        "keeps the any type."
    ),
}

#: Limits whose construct is still modelled, with only a detail lost.
PARTIAL_LIMITS = frozenset(LIMIT_DETAILS) - {"jsonld.instance_data"}

#: Characters that end an IRI usable as a prefix (JSON-LD 1.1 gen-delims).
_PREFIX_ENDINGS = ("/", "#", ":", "?", "[", "]", "@")

_SCOPED_EVIDENCE = "A scoped context has no name of its own; the type is named after its term by Apiome."
_MAP_EVIDENCE = "A JSON-LD container map has no name of its own; the map type is named by Apiome."

#: The keywords a context may set for itself (rather than define a term).
_CONTEXT_SETTINGS = ("@version", "@base", "@vocab", "@language", "@direction", "@protected", "@propagate")


@dataclass
class JsonLdDocument:
    """A validated JSON-LD context import.

    Attributes:
        path: The root document's path.
        document: The root document with every context reference inlined.
        context: The root context entries, in order (objects, or ``None`` for a reset).
        sources: Every file read, ``path → text``, the root first.
        resolved_contexts: Member paths whose contexts were inlined.
        is_fileset: Whether the import was a fileset.
    """

    path: str
    document: Any
    context: List[Optional[Dict[str, Any]]]
    sources: Dict[str, str]
    resolved_contexts: List[str] = field(default_factory=list)
    is_fileset: bool = False


def _context_entries(value: Any) -> List[Optional[Dict[str, Any]]]:
    """A ``@context`` value as a list of its objects (``None`` kept as a reset)."""
    entries = value if isinstance(value, list) else [value]
    return [entry for entry in entries if entry is None or isinstance(entry, dict)]


def read_jsonld(text: Optional[str] = None, *, label: str, fileset: Optional[IntakeFileset] = None) -> JsonLdDocument:
    """Load and validate a JSON-LD context (a single file, or a fileset of contexts).

    Raises:
        RdfParseError: With the taxonomy code of the failure — a syntax or encoding fault, no
            ``@context`` (``INPUT_SEMANTIC_INVALID``; the message contains :data:`NO_CONTEXT_MARKER`),
            a context reference outside the upload (``INPUT_REFERENCE_UNRESOLVED``), or a context
            that defines no terms (``INPUT_SEMANTIC_INVALID``).
    """
    members: Mapping[str, str] = dict(fileset.members) if fileset is not None else {}
    path = fileset.root if fileset is not None else label
    root_text = fileset.root_content() if fileset is not None else (text or "")
    loaded = load_json_document(root_text, label=path)
    if not json_has_context(loaded):
        raise RdfParseError(
            f"{path} {NO_CONTEXT_MARKER}: a JSON-LD context import needs a top-level @context that "
            "maps terms to IRIs; plain JSON instance data has no vocabulary to import.",
            code="INPUT_SEMANTIC_INVALID",
        )
    unresolved: List[str] = []
    resolved: List[str] = []
    document = resolve_json_contexts(loaded, path=path, members=members, unresolved=unresolved, resolved=resolved)
    refuse_unresolved_contexts(unresolved, path)
    roots = document if isinstance(document, list) else [document]
    context: List[Optional[Dict[str, Any]]] = []
    for node in roots:
        if isinstance(node, dict) and "@context" in node:
            context.extend(_context_entries(node["@context"]))
    sources = {path: root_text, **{p: members[p] for p in resolved}}
    built = JsonLdDocument(
        path=path,
        document=document,
        context=context,
        sources=sources,
        resolved_contexts=resolved,
        is_fileset=fileset is not None,
    )
    active = _merge(context, {})
    if not any(_classify(term, definition, active) in ("property", "class") for term, definition in active.items()):
        raise RdfParseError(
            f"{path} has a @context that defines no terms (only prefixes, keyword aliases or "
            "settings), so there is no vocabulary to import.",
            code="INPUT_SEMANTIC_INVALID",
        )
    return built


# ===========================================================================
# Active-context processing
# ===========================================================================


def _merge(entries: List[Optional[Dict[str, Any]]], parent: Mapping[str, Any]) -> Dict[str, Any]:
    """Merge context entries over ``parent`` in order (``None`` resets; a later term overrides)."""
    active: Dict[str, Any] = dict(parent)
    for entry in entries:
        if entry is None:
            active = {}
            continue
        for key, value in entry.items():
            if value is None and not key.startswith("@"):
                active.pop(key, None)
            else:
                active[key] = value
    return active


def _expand(
    value: Optional[str], active: Mapping[str, Any], *, vocab: bool = True, stack: Tuple[str, ...] = ()
) -> Optional[str]:
    """Expand a term, compact IRI or relative IRI against an active context (no network)."""
    if value is None or value.startswith("@"):
        return value
    if ":" in value:
        prefix, suffix = value.split(":", 1)
        if suffix.startswith("//"):
            return value
        if prefix in active and prefix not in stack:
            base = _term_iri(prefix, active.get(prefix), active, stack + (prefix,))
            if base and not base.startswith("@"):
                return base + suffix
        return value
    if vocab and value in active and value not in stack and not value.startswith("@"):
        return _term_iri(value, active.get(value), active, stack + (value,))
    if vocab and isinstance(active.get("@vocab"), str):
        return (_expand(active["@vocab"], active, stack=stack) or "") + value
    return value


def _term_iri(term: str, definition: Any, active: Mapping[str, Any], stack: Tuple[str, ...] = ()) -> Optional[str]:
    """The IRI (or keyword) a term definition maps ``term`` to."""
    if isinstance(definition, str):
        return _expand(definition, active, stack=stack + (term,))
    if isinstance(definition, dict):
        for key in ("@reverse", "@id"):
            if isinstance(definition.get(key), str):
                return _expand(definition[key], active, stack=stack + (term,))
    if ":" in term:
        return _expand(term, active, stack=stack + (term,))
    vocab = active.get("@vocab")
    if isinstance(vocab, str):
        return (_expand(vocab, active, stack=stack + (term,)) or "") + term
    return None


def _classify(term: str, definition: Any, active: Mapping[str, Any]) -> str:
    """``setting``, ``alias``, ``prefix``, ``class`` or ``property``."""
    if term.startswith("@"):
        return "setting"
    iri = _term_iri(term, definition, active)
    if iri is not None and iri.startswith("@"):
        return "alias"
    simple = isinstance(definition, str) or (
        isinstance(definition, dict) and set(definition) <= {"@id", "@prefix", "@protected"}
    )
    if isinstance(definition, str) and iri and ":" not in term and iri.endswith(_PREFIX_ENDINGS):
        return "prefix"
    if simple and term[:1].isupper() and iri and local_name(iri)[:1].isupper():
        return "class"
    return "property"


def _containers(definition: Any) -> Set[str]:
    """The ``@container`` keywords of a term definition."""
    if not isinstance(definition, dict):
        return set()
    value = definition.get("@container")
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {v for v in value if isinstance(v, str)}
    return set()


def _pascal(term: str) -> str:
    """``postal-code`` → ``PostalCode``: a type name made from a term or file stem."""
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", term) if p]
    name = "".join(p[:1].upper() + p[1:] for p in parts) or "Term"
    return name if name[:1].isalpha() else f"T{name}"


class _Builder:
    """Accumulates types and limits while one context is normalized."""

    def __init__(self, document: JsonLdDocument) -> None:
        """Start with no types and an empty limit recorder."""
        self.document = document
        self.types: Dict[str, Type] = {}
        self.limits = LimitRecorder(details=LIMIT_DETAILS)

    def _unique_key(self, base: str) -> str:
        """``base``, or ``base2``, ``base3`` … — the first key no type uses yet."""
        key = base
        counter = 2
        while key in self.types:
            key = f"{base}{counter}"
            counter += 1
        return key

    def _compact(self, iri: str, active: Mapping[str, Any]) -> str:
        """``iri`` in the context's own prefixed form where a prefix covers it."""
        best: Optional[Tuple[str, str]] = None
        for term, definition in active.items():
            if _classify(term, definition, active) != "prefix":
                continue
            namespace = _term_iri(term, definition, active) or ""
            if namespace and iri.startswith(namespace) and len(iri) > len(namespace):
                if best is None or len(namespace) > len(best[1]):
                    best = (term, namespace)
        return f"{best[0]}:{iri[len(best[1]) :]}" if best else iri

    def _language_map(self) -> str:
        """Define (once) and return the shared ``LanguageMap`` type."""
        key = "LanguageMap"
        if key not in self.types:
            self.types[key] = Type(
                key=key,
                name=key,
                kind=TypeKind.MAP,
                description="A JSON-LD language map: language tag → string.",
                key_type=TypeRef(name="string", nullable=False),
                value_type=TypeRef(name="string", nullable=False),
                extras={"jsonld_container": "@language", **provenance_extras(SYNTHESIZED, _MAP_EVIDENCE)},
            )
        return key

    def _keyed_map(self, owner: str, term: str, container: str, value: TypeRef) -> str:
        """Define and return the map type of an ``@index`` / ``@id`` / ``@type`` container."""
        key = self._unique_key(f"{owner}_{_pascal(term)}Map")
        self.types[key] = Type(
            key=key,
            name=key,
            kind=TypeKind.MAP,
            description=f"The {container} map of {term}: {container[1:]} → value.",
            key_type=TypeRef(name="string", nullable=False),
            value_type=value,
            extras={"jsonld_container": container, **provenance_extras(SYNTHESIZED, _MAP_EVIDENCE)},
        )
        return key

    def _enum(self, term: str, scoped: Mapping[str, Any], active: Mapping[str, Any]) -> Optional[str]:
        """An ``@type: @vocab`` term whose scoped context only names values → an enum."""
        merged = _merge(_context_entries(scoped), active)
        values = [
            (name, _term_iri(name, definition, merged))
            for name, definition in scoped.items()
            if not name.startswith("@") and isinstance(definition, (str, dict))
        ]
        if not values or any(isinstance(d, dict) and set(d) - {"@id"} for d in scoped.values() if isinstance(d, dict)):
            return None
        key = self._unique_key(_pascal(term))
        self.types[key] = Type(
            key=key,
            name=key,
            kind=TypeKind.ENUM,
            description=f"The values the {term} term maps to IRIs (@type: @vocab).",
            enum_values=[EnumValue(key=Keys.enum_value(key, name), name=name, value=iri) for name, iri in values],
            extras={"jsonld_term": term, **provenance_extras(SYNTHESIZED, _SCOPED_EVIDENCE)},
        )
        return key

    def element(self, owner: str, term: str, definition: Any, active: Mapping[str, Any]) -> Tuple[str, Optional[str]]:
        """The canonical type (and format) of one term's values, before any container."""
        if not isinstance(definition, dict):
            return "any", None
        coercion = definition.get("@type")
        scoped = definition.get("@context")
        if isinstance(scoped, (dict, list)):
            if coercion == "@vocab" and isinstance(scoped, dict):
                enum_key = self._enum(term, scoped, active)
                if enum_key:
                    return enum_key, None
            own = _merge(_context_entries(scoped), {})
            return self.record(_pascal(term), own, _merge(_context_entries(scoped), active), scoped_from=term), None
        if coercion in ("@id", "@vocab"):
            return "string", "iri"
        if coercion == "@json":
            return "any", None
        if isinstance(coercion, str) and not coercion.startswith("@"):
            iri = _expand(coercion, active, vocab=False)
            scalar, fmt = datatype_ref_name(URIRef(iri or coercion))
            return scalar or "string", fmt
        return "any", None

    def term_field(self, owner: str, term: str, definition: Any, active: Mapping[str, Any]) -> CanonicalField:
        """One term as an (optional) field of ``owner``."""
        key = Keys.field(owner, term)
        iri = _term_iri(term, definition, active)
        type_name, fmt = self.element(owner, term, definition, active)
        containers = _containers(definition)
        element = TypeRef(name=type_name, nullable=False)
        many = bool(containers & {"@set", "@list"})
        extras: Dict[str, Any] = {"jsonld_definition": definition}
        if iri:
            extras["native_id"] = iri
        if "@language" in containers:
            type_ref = TypeRef(name=self._language_map(), nullable=True)
        elif containers & {"@index", "@id", "@type"}:
            container = next(c for c in ("@index", "@id", "@type") if c in containers)
            value = TypeRef(item=element, nullable=False) if many else element
            type_ref = TypeRef(name=self._keyed_map(owner, term, container, value), nullable=True)
        elif "@graph" in containers:
            self.limits.record("jsonld.graph_container", location=key)
            type_ref = TypeRef(name="any", nullable=True)
        elif many:
            type_ref = TypeRef(item=element, nullable=True)
        else:
            type_ref = TypeRef(name=type_name, nullable=True)
        if "@list" in containers:
            extras["jsonld_ordered"] = True
        if isinstance(definition, dict) and "@reverse" in definition:
            extras["jsonld_reverse"] = True
            self.limits.record("jsonld.reverse_property", location=key)
        constraints = Constraints(format=fmt) if fmt else None
        return CanonicalField(key=key, name=term, type=type_ref, constraints=constraints, extras=extras)

    def record(
        self, name: str, own: Mapping[str, Any], active: Mapping[str, Any], *, scoped_from: Optional[str] = None
    ) -> str:
        """Define the record of one (root or scoped) context and return its key.

        Args:
            name: The record's base name.
            own: The definitions this context makes itself (its fields).
            active: The active context the definitions expand against (``own`` over its parents).
            scoped_from: The term a scoped context belongs to (``None`` for the root context).
        """
        key = self._unique_key(name)
        self.types[key] = Type(key=key, name=key, kind=TypeKind.RECORD)
        fields: List[CanonicalField] = []
        prefixes: Dict[str, str] = {}
        aliases: Dict[str, str] = {}
        classes: Dict[str, str] = {}
        settings: Dict[str, Any] = {}
        for term in sorted(own):
            definition = own[term]
            kind = _classify(term, definition, active)
            if kind == "setting":
                if term in _CONTEXT_SETTINGS:
                    settings[term] = definition
                continue
            iri = _term_iri(term, definition, active) or ""
            if kind == "alias":
                aliases[term] = iri
            elif kind == "prefix":
                prefixes[term] = iri
            elif kind == "class":
                classes[term] = iri
            else:
                fields.append(self.term_field(key, term, definition, active))
        extras: Dict[str, Any] = {}
        if scoped_from:
            extras["jsonld_scoped_from"] = scoped_from
            extras.update(provenance_extras(SYNTHESIZED, _SCOPED_EVIDENCE))
        if settings.get("@vocab"):
            extras["jsonld_vocab"] = _expand(settings["@vocab"], active, vocab=False)
            if scoped_from is None:
                self.limits.record("jsonld.open_vocabulary", location=key)
        for setting, extras_key in (
            ("@base", "jsonld_base"),
            ("@language", "jsonld_language"),
            ("@version", "jsonld_version"),
            ("@protected", "jsonld_protected"),
            ("@direction", "jsonld_direction"),
        ):
            if setting in settings and scoped_from is None:
                extras[extras_key] = settings[setting]
        if scoped_from is None:
            if prefixes:
                extras["jsonld_prefixes"] = prefixes
            if aliases:
                extras["jsonld_keyword_aliases"] = aliases
            if classes:
                extras["jsonld_class_terms"] = classes
        self.types[key] = Type(
            key=key,
            name=key,
            kind=TypeKind.RECORD,
            description=None if scoped_from else "The terms of the JSON-LD context.",
            fields=fields,
            extras=extras,
        )
        return key


def _root_name(path: str) -> str:
    """The root record's name, from the file name (``02-typical-context.jsonld`` → ``TypicalContext``)."""
    stem = PurePosixPath(path).name.split(".", 1)[0]
    stem = re.sub(r"^[0-9]+[-_]*", "", stem)
    return _pascal(stem) if stem else "Context"


def _instance_data(document: Any) -> Optional[Dict[str, Any]]:
    """Count the instance nodes beside the context (``@graph`` members or node properties)."""
    roots = document if isinstance(document, list) else [document]
    nodes = 0
    node_types: Set[str] = set()
    for root in roots:
        if not isinstance(root, dict):
            continue
        graph = root.get("@graph")
        members = graph if isinstance(graph, list) else ([graph] if isinstance(graph, dict) else [])
        if not members and set(root) - {"@context"}:
            members = [root]
        for member in members:
            if not isinstance(member, dict):
                continue
            nodes += 1
            for type_key in ("@type", "type"):
                value = member.get(type_key)
                for item in value if isinstance(value, list) else [value]:
                    if isinstance(item, str):
                        node_types.add(item)
    if not nodes:
        return None
    return {"nodes": nodes, "types": sorted(node_types)}


class JsonLdNormalizer(Normalizer, register=True):
    """Normalize a :class:`JsonLdDocument` into a data_schema :class:`CanonicalApi`."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map a validated JSON-LD context onto the canonical model.

        Args:
            source: The :class:`JsonLdDocument` from :func:`read_jsonld`.
            include_raw: Whether to keep every file's text on ``raw``.

        Returns:
            The canonical model.

        Raises:
            ValueError: When ``source`` is not a :class:`JsonLdDocument`.
        """
        if not isinstance(source, JsonLdDocument):
            raise ValueError("JSON-LD source must be a JsonLdDocument (see app.jsonld_normalizer.read_jsonld)")
        builder = _Builder(source)
        active = _merge(source.context, {})
        name = _root_name(source.path)
        root_key = builder.record(name, active, active)
        instance = _instance_data(source.document)
        if instance:
            builder.limits.record("jsonld.instance_data", location=root_key)
        record: Dict[str, Any] = {
            "input": "fileset" if source.is_fileset else "file",
            "files": list(source.sources),
            "root_type": root_key,
            **({"resolved_contexts": list(source.resolved_contexts)} if source.resolved_contexts else {}),
            **({"instance_data": instance} if instance else {}),
            "capability_limits": _limits_payload(builder.limits.limits()),
        }
        version = active.get("@version")
        terms = len(builder.types[root_key].fields)
        description = f"JSON-LD context{f' (JSON-LD {version})' if version else ''}: {terms} terms."
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=name),
            version=None,
            title=name,
            description=description,
            types=list(builder.types.values()),
            raw={"files": [{"path": p, "text": t} for p, t in source.sources.items()]} if include_raw else None,
            extras={JSONLD_EXTRAS_KEY: record},
        )
        return normalize_ordering(api)
