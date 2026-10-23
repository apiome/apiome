"""OWL / RDFS ontology import source — FMT-9.4 (#5471).

The :class:`~app.import_source.ImportSource` adapter for OWL and RDFS ontologies in Turtle, RDF/XML
or JSON-LD — one file, or a fileset whose ontologies compose with ``owl:imports``. The graph is read
by :mod:`app.rdf_graph` (hardened, never fetching an import) and normalized onto the
**data_schema** paradigm by :mod:`app.owl_normalizer`: classes become types with inheritance where
expressible, properties their fields. OWL's open-world, inference-driven semantics are declared
limits, never approximated.
"""

from __future__ import annotations

from typing import Any, Optional

from . import owl_normalizer  # noqa: F401 — self-registers the normalizer
from .canonical_model import ApiParadigm, CanonicalApi
from .fileset import IntakeFileset
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
)
from .owl_normalizer import FORMAT_KEY, OwlDocument, read_owl
from .rdf_graph import RdfParseError
from .shacl_import_source import looks_like_shacl

__all__ = ["OwlImportSource"]

#: The format a plain RDF Schema vocabulary (no OWL namespace) is detected as.
RDFS_FORMAT_KEY = "rdfs"

_OWL_NAMESPACE = "http://www.w3.org/2002/07/owl#"
_RDFS_NAMESPACE = "http://www.w3.org/2000/01/rdf-schema#"

#: Vocabulary tokens of an ontology, in Turtle prefixed names and RDF/XML element names alike.
_ONTOLOGY_MARKERS = ("Ontology", "Class", "ObjectProperty", "DatatypeProperty")
_RDFS_MARKERS = ("rdfs:Class", "rdfs:subClassOf", "rdf:Property")


class OwlImportSource(ImportSource, register=True):
    """Adapter for OWL / RDFS ontologies (Turtle, RDF/XML, JSON-LD) and ontology filesets."""

    key = FORMAT_KEY
    label = "OWL / RDFS ontologies"
    description = (
        "Import an OWL or RDFS ontology (Turtle, RDF/XML or JSON-LD): classes become types with "
        "inheritance, properties their fields with cardinality; open-world inference is declared, "
        "not imported."
    )
    icon = "share-2"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY, RDFS_FORMAT_KEY)
    file_extensions = (".owl", ".ttl", ".turtle", ".rdf", ".jsonld", ".zip", ".tar.gz", ".tgz")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim text in the OWL namespace that uses its class or property vocabulary.

        A shapes graph that also mentions OWL (``owl:imports`` composes shapes graphs) is left to
        the SHACL adapter: it is claimed only weakly here.
        """
        text = payload.text
        if not text:
            return NO_MATCH
        has_owl = _OWL_NAMESPACE in text and any(marker in text for marker in _ONTOLOGY_MARKERS)
        has_rdfs = _RDFS_NAMESPACE in text and any(marker in text for marker in _RDFS_MARKERS)
        if not has_owl and not has_rdfs:
            return NO_MATCH
        if looks_like_shacl(text):
            return DetectionResult(confidence=0.4, format=FORMAT_KEY, reason="OWL vocabulary in a shapes graph")
        if has_owl:
            return DetectionResult(
                confidence=0.95, format=FORMAT_KEY, reason="OWL namespace with class/property vocabulary"
            )
        return DetectionResult(confidence=0.88, format=RDFS_FORMAT_KEY, reason="RDFS class vocabulary")

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> OwlDocument:
        """Read and validate one ontology, carrying the reader's taxonomy code."""
        try:
            return read_owl(raw, label=source_label or "ontology.ttl")
        except RdfParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> OwlDocument:
        """Read a set of ontologies composed with ``owl:imports``.

        Raises:
            ImportSourceError: When a member cannot be read or an import cannot be resolved.
        """
        try:
            return read_owl(label=source_label or fileset.root, fileset=fileset)
        except RdfParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a validated ontology onto the data_schema paradigm.

        Raises:
            ImportSourceError: When ``native_ast`` is not an :class:`OwlDocument`.
        """
        if not isinstance(native_ast, OwlDocument):
            raise ImportSourceError("OWL source must be an OwlDocument (see app.owl_normalizer)")
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)
