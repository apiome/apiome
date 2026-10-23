"""JSON-LD context import source — FMT-9.4 (#5471).

The :class:`~app.import_source.ImportSource` adapter for JSON-LD contexts: a single ``.jsonld``
document (a context, or a context plus the ``@graph`` it describes), or a fileset whose context
array references sibling context files. Read by :mod:`app.jsonld_normalizer` onto the
**data_schema** paradigm: terms become property names and the IRIs they expand to are kept as
provenance. Remote contexts are never fetched.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from . import jsonld_normalizer  # noqa: F401 — self-registers the normalizer
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
from .jsonld_normalizer import FORMAT_KEY, NO_CONTEXT_MARKER, JsonLdDocument, read_jsonld
from .rdf_graph import RdfParseError, json_has_context
from .shacl_import_source import looks_like_shacl

__all__ = ["JsonLdImportSource"]

#: Below this confidence another adapter's claim is not taken as evidence of a wrong-format upload.
_MISMATCH_CONFIDENCE = 0.5


def _loaded(payload: DetectionInput) -> Any:
    """The payload's JSON value, parsing the text when the caller did not."""
    if payload.document is not None:
        return payload.document
    text = (payload.text or "").lstrip()
    if not text.startswith(("{", "[")):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


class JsonLdImportSource(ImportSource, register=True):
    """Adapter for JSON-LD contexts (single documents and context filesets)."""

    key = FORMAT_KEY
    label = "JSON-LD contexts"
    description = (
        "Import a JSON-LD context: terms become property names with their IRIs kept as provenance, "
        "type coercion and containers become field types, scoped contexts nested types."
    )
    icon = "file-json"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY, "json-ld")
    file_extensions = (".jsonld", ".json", ".zip", ".tar.gz", ".tgz")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a JSON document with a top-level ``@context``.

        A JSON-LD serialization of a SHACL shapes graph is left to the SHACL adapter (claimed only
        weakly here). A ``.jsonld`` file that does not parse is claimed weakly so the reader can say
        what is wrong.
        """
        loaded = _loaded(payload)
        if loaded is None:
            if (payload.filename or "").lower().endswith(".jsonld") and payload.text:
                return DetectionResult(confidence=0.5, format=FORMAT_KEY, reason="`.jsonld` file extension")
            return NO_MATCH
        if not json_has_context(loaded):
            return NO_MATCH
        if looks_like_shacl(payload.text):
            return DetectionResult(confidence=0.6, format=FORMAT_KEY, reason="JSON-LD shapes graph")
        return DetectionResult(confidence=0.93, format=FORMAT_KEY, reason="top-level JSON-LD @context")

    @staticmethod
    def _as_import_error(exc: RdfParseError, text: Optional[str], filename: Optional[str]) -> ImportSourceError:
        """Carry the reader's code — a context-less document another adapter claims is a mismatch."""
        code = exc.code
        if code == "INPUT_SEMANTIC_INVALID" and NO_CONTEXT_MARKER in str(exc) and text is not None:
            from .import_source import detect_import_source

            best = detect_import_source(DetectionInput(text=text, filename=filename))
            if best is not None and best[0].key != FORMAT_KEY and best[1].confidence >= _MISMATCH_CONFIDENCE:
                return ImportSourceError(
                    f"{exc} The document reads as {best[0].label} — import it with that format.",
                    code="FORMAT_MISMATCH",
                )
        return ImportSourceError(str(exc), code=code)

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> JsonLdDocument:
        """Read and validate one JSON-LD context document."""
        try:
            return read_jsonld(raw, label=source_label or "context.jsonld")
        except RdfParseError as exc:
            raise self._as_import_error(exc, raw, source_label) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> JsonLdDocument:
        """Read a context whose context array references sibling context files in the set.

        Raises:
            ImportSourceError: When a member cannot be read or a context reference cannot be
                resolved within the set.
        """
        try:
            return read_jsonld(label=source_label or fileset.root, fileset=fileset)
        except RdfParseError as exc:
            raise self._as_import_error(exc, fileset.root_content(), fileset.root) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a validated JSON-LD context onto the data_schema paradigm.

        Raises:
            ImportSourceError: When ``native_ast`` is not a :class:`JsonLdDocument`.
        """
        if not isinstance(native_ast, JsonLdDocument):
            raise ImportSourceError("JSON-LD source must be a JsonLdDocument (see app.jsonld_normalizer)")
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)
