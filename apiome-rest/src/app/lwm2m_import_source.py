"""LwM2M / IPSO object-definition import source — FMT-9.5 (#5472).

The :class:`~app.import_source.ImportSource` adapter for OMA LwM2M object definitions (the XML the
OMA registry publishes, IPSO smart objects included): one file, or a set of files in the
registry's one-file-per-object convention. Read by :mod:`app.lwm2m_parser` and normalized onto the
**data_schema** paradigm by :mod:`app.lwm2m_normalizer`: objects become records, readable and
writable resources fields, executable resources operations.

Crawling the public LwM2M registry is out of scope; it belongs to the registry-as-source seam
(#3978).
"""

from __future__ import annotations

from typing import Any, Optional

from . import lwm2m_normalizer  # noqa: F401 — self-registers the normalizer
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
from .lwm2m_parser import (
    FORMAT_KEY,
    Lwm2mDocument,
    Lwm2mParseError,
    is_lwm2m_document,
    parse_lwm2m_fileset,
    parse_lwm2m_text,
)

__all__ = ["Lwm2mImportSource"]

#: Markers of an object definition inside an ``LWM2M`` root.
_OBJECT_MARKERS = ('ObjectType="MODefinition"', "<ObjectID>")


def _as_import_error(exc: Lwm2mParseError) -> ImportSourceError:
    """Carry the reader's taxonomy code onto the adapter error."""
    return ImportSourceError(str(exc), code=exc.code)


class Lwm2mImportSource(ImportSource, register=True):
    """Adapter for LwM2M / IPSO object-definition XML."""

    key = FORMAT_KEY
    label = "LwM2M / IPSO objects"
    description = (
        "Import OMA LwM2M object definitions, IPSO smart objects included: objects become types, "
        "readable and writable resources fields with their units, ranges and mandatory flags, and "
        "executable resources operations."
    )
    icon = "cpu"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY, "ipso")
    file_extensions = (".xml", ".zip", ".tar.gz", ".tgz")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim an ``LWM2M`` root element, more confidently when it holds an object definition.

        Only the head is examined, so a truncated or malformed definition is still claimed and the
        reader says what is wrong with it.
        """
        text = payload.text
        if text is None or not is_lwm2m_document(text):
            return NO_MATCH
        if any(marker in text[:65536] for marker in _OBJECT_MARKERS):
            return DetectionResult(
                confidence=0.97, format=FORMAT_KEY, reason="`<LWM2M>` root with an object definition"
            )
        return DetectionResult(confidence=0.85, format=FORMAT_KEY, reason="`<LWM2M>` root element")

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> Lwm2mDocument:
        """Parse one object-definition file, carrying the reader's taxonomy code."""
        try:
            return parse_lwm2m_text(raw, label=source_label)
        except Lwm2mParseError as exc:
            raise _as_import_error(exc) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> Lwm2mDocument:
        """Parse a set of object-definition files.

        Raises:
            ImportSourceError: When a member cannot be read.
        """
        try:
            return parse_lwm2m_fileset(fileset, label=source_label)
        except Lwm2mParseError as exc:
            raise _as_import_error(exc) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize parsed object definitions onto the data_schema paradigm.

        Raises:
            ImportSourceError: When ``native_ast`` is not a parsed LwM2M document.
        """
        if not isinstance(native_ast, Lwm2mDocument):
            raise ImportSourceError("LwM2M source must be an Lwm2mDocument (see app.lwm2m_parser)")
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)
