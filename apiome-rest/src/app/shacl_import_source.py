"""SHACL shapes import source — FMT-9.4 (#5471).

The :class:`~app.import_source.ImportSource` adapter for SHACL shapes graphs in Turtle, RDF/XML or
JSON-LD — one file, or a fileset whose shapes graphs compose with ``owl:imports``. The graph is read
by :mod:`app.rdf_graph` (hardened, never fetching anything) and normalized onto the
**data_schema** paradigm by :mod:`app.shacl_normalizer`: node shapes become records, property
shapes their fields, and cardinality, datatype and value constraints canonical constraints.
"""

from __future__ import annotations

from typing import Any, Optional

from . import shacl_normalizer  # noqa: F401 — self-registers the normalizer
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
from .rdf_graph import RdfParseError
from .shacl_normalizer import FORMAT_KEY, ShaclDocument, read_shacl

__all__ = ["ShaclImportSource", "looks_like_shacl"]

#: The SHACL namespace as it appears in source text.
_SHACL_NAMESPACE = "http://www.w3.org/ns/shacl#"

#: Tokens that only a shapes graph carries (Turtle prefixed names, RDF/XML elements, JSON-LD keys).
_SHAPE_MARKERS = ("NodeShape", "PropertyShape", "sh:property", "sh:path")


def looks_like_shacl(text: Optional[str]) -> bool:
    """Whether source text declares the SHACL namespace and uses its shape vocabulary."""
    return bool(text) and _SHACL_NAMESPACE in text and any(marker in text for marker in _SHAPE_MARKERS)


class ShaclImportSource(ImportSource, register=True):
    """Adapter for SHACL shapes graphs (Turtle, RDF/XML, JSON-LD) and shapes filesets."""

    key = FORMAT_KEY
    label = "SHACL shapes"
    description = (
        "Import a SHACL shapes graph (Turtle, RDF/XML or JSON-LD): node shapes become types, property "
        "shapes their fields, with cardinality, datatype, pattern and enumeration constraints."
    )
    icon = "shapes"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY, "shacl-shapes")
    file_extensions = (".ttl", ".turtle", ".jsonld", ".rdf", ".shacl", ".zip", ".tar.gz", ".tgz")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim text that declares the SHACL namespace and uses ``sh:NodeShape`` / ``sh:property``.

        The namespace decides, not the syntax: a Turtle ontology and a Turtle shapes graph look
        alike, and only the vocabulary tells them apart. The namespace alone (no shape vocabulary)
        is claimed weakly, so the reader can say what is missing.
        """
        text = payload.text
        if not text or _SHACL_NAMESPACE not in text:
            return NO_MATCH
        if looks_like_shacl(text):
            return DetectionResult(
                confidence=0.97, format=FORMAT_KEY, reason="SHACL namespace with node/property shapes"
            )
        return DetectionResult(confidence=0.5, format=FORMAT_KEY, reason="SHACL namespace declared")

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> ShaclDocument:
        """Read and validate one shapes graph, carrying the reader's taxonomy code."""
        try:
            return read_shacl(raw, label=source_label or "shapes.ttl")
        except RdfParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> ShaclDocument:
        """Read a set of shapes graphs composed with ``owl:imports``.

        Raises:
            ImportSourceError: When a member cannot be read or an import / shape reference cannot be
                resolved within the set.
        """
        try:
            return read_shacl(label=source_label or fileset.root, fileset=fileset)
        except RdfParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a validated shapes graph onto the data_schema paradigm.

        Raises:
            ImportSourceError: When ``native_ast`` is not a :class:`ShaclDocument`.
        """
        if not isinstance(native_ast, ShaclDocument):
            raise ImportSourceError("SHACL source must be a ShaclDocument (see app.shacl_normalizer)")
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)
