"""DICOM import source — FMT-6.7 (#5451).

The :class:`~app.import_source.ImportSource` adapter for DICOM, the imaging half of healthcare beside
FHIR. It reads the **metadata layer only**:

* a binary **Part 10** file (``.dcm``) through the binary intake SPI
  (:meth:`DicomImportSource.accepts_bytes` / :meth:`~DicomImportSource.parse_bytes`):
  the file meta information and the dataset's attribute structure (:mod:`app.dicom_part10`);
* the **DICOM JSON** model (PS3.18 Annex F) a DICOMweb server returns, pasted or uploaded
  (:mod:`app.dicom_json`);
* an **archive** of DICOM JSON documents — a study-level query result and its instances.

Attributes normalize to canonical properties keyed by tag with the VR as the type; sequences become
nested types; a Structured Report's content tree is recorded as a hierarchy
(:mod:`app.dicom_normalizer`). **Pixel data is never read, never stored and never analysed**: the
readers step over it by length and record that they did (:data:`PIXEL_DATA_BOUNDARY_STATEMENT`).
No attribute value enters the canonical model; values reach only the native analysis
(:mod:`app.dicom_analysis`), where the value-visibility policy keeps presence and length by
default — and the verbatim upload is not kept as the version's source.
"""

from __future__ import annotations

from typing import Any, Optional

from . import dicom_normalizer  # noqa: F401 — self-registers the normalizer
from .canonical_model import ApiParadigm, CanonicalApi
from .dicom_analysis import (
    DICOM_ANALYZER_KEY,
    DICOM_ANALYZER_VERSION,
    analyze_dicom,
    dicom_capabilities,
)
from .dicom_dictionary import PIXEL_DATA_BOUNDARY_STATEMENT
from .dicom_json import has_dicom_json_marker, is_dicom_json, is_dicom_json_document
from .dicom_model import DicomDocument, DicomParseError
from .dicom_parser import parse_dicom_bytes, parse_dicom_fileset, parse_dicom_text
from .dicom_part10 import PART10_SUFFIXES, sniff_part10
from .fileset import IntakeFileset
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
)
from .payload_analysis import AnalyzerCapabilities, PayloadAnalysisDocument

__all__ = ["DicomImportSource", "PIXEL_DATA_BOUNDARY_STATEMENT"]


def _as_import_error(exc: DicomParseError) -> ImportSourceError:
    return ImportSourceError(str(exc), code=exc.code)


class DicomImportSource(ImportSource, register=True):
    """Adapter for DICOM (Part 10 ``.dcm`` files and the DICOM JSON model; file / url / paste / fileset)."""

    key = "dicom"
    label = "DICOM"
    description = (
        "Import a DICOM Part 10 file or DICOM JSON metadata and infer its SOP class, attribute "
        "and Structured Report schema. Pixel data is never read."
    )
    icon = "heart-pulse"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = ("dicom", "dcm", "dicom-json")
    file_extensions = PART10_SUFFIXES + (".json",)
    analyzer_key = DICOM_ANALYZER_KEY
    analyzer_version = DICOM_ANALYZER_VERSION

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a Part 10 file by its magic, or DICOM JSON by its tag-keyed attributes.

        The undecoded bytes are consulted first: the ``DICM`` magic at offset 128 *is* the evidence
        and is not reachable through a text sniff. DICOM JSON is recognised when every key of every
        dataset is an 8-hex-digit tag holding an object with a ``vr``; a document too broken to
        parse is still claimed, at lower confidence, when its text spells such an attribute — so
        the reader can say what is wrong with it. A ``.dcm`` filename alone is the weakest signal.
        """
        if sniff_part10(payload.data):
            return DetectionResult(
                confidence=0.97, format="dicom", reason="DICOM Part 10 preamble and `DICM` magic at offset 128"
            )
        document = payload.document
        if document is not None and is_dicom_json_document(document):
            return DetectionResult(
                confidence=0.95, format="dicom", reason="DICOM JSON: 8-hex-digit tag keys holding `vr` objects"
            )
        text = payload.text
        if text is not None:
            if is_dicom_json(text):
                return DetectionResult(
                    confidence=0.95, format="dicom", reason="DICOM JSON: 8-hex-digit tag keys holding `vr` objects"
                )
            if has_dicom_json_marker(text):
                return DetectionResult(
                    confidence=0.6, format="dicom", reason="DICOM JSON attribute spelling (`\"00100010\": {\"vr\"`)"
                )
        if (payload.filename or "").strip().lower().endswith(PART10_SUFFIXES):
            return DetectionResult(confidence=0.6, format="dicom", reason="DICOM file extension")
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> DicomDocument:
        """Parse DICOM JSON text, carrying the reader's taxonomy code onto the error."""
        try:
            return parse_dicom_text(raw, label=source_label)
        except DicomParseError as exc:
            raise _as_import_error(exc) from exc

    def accepts_bytes(self, raw: bytes, *, filename: Optional[str] = None) -> bool:
        """Claim Part 10 bytes for :meth:`parse_bytes`.

        Claims on the magic, and — the IXH-7.5 suffix rule — on a ``.dcm``/``.dicom``/``.dic``
        filename *even when the bytes are broken*, so a truncated file or one without the magic is
        reported by the Part 10 reader rather than as a text-decoding fault.
        """
        if (filename or "").strip().lower().endswith(PART10_SUFFIXES):
            return True
        return sniff_part10(raw)

    def parse_bytes(self, raw: bytes, *, source_label: Optional[str] = None) -> DicomDocument:
        """Parse a Part 10 file's metadata layer; pixel data is stepped over, never read."""
        try:
            return parse_dicom_bytes(raw, label=source_label)
        except DicomParseError as exc:
            raise _as_import_error(exc) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> DicomDocument:
        """Parse an archive of DICOM JSON documents, root first.

        Raises:
            ImportSourceError: When the root is missing or is not readable DICOM JSON.
        """
        if fileset.root not in fileset.members:
            raise ImportSourceError("DICOM fileset is missing its root document", code="INPUT_SEMANTIC_INVALID")
        try:
            return parse_dicom_fileset(fileset.members, root=fileset.root)
        except DicomParseError as exc:
            raise _as_import_error(exc) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(native_ast, DicomDocument):
            raise ImportSourceError("DICOM source must be a DicomDocument (see app.dicom_parser)")
        return self._normalize_via_registry("dicom", native_ast, include_raw=include_raw)

    def analysis_capabilities(self) -> AnalyzerCapabilities:
        """The DICOM extractor's capability declaration (CPDO-1.2)."""
        return dicom_capabilities()

    def analyze(self, native_ast: Any, *, source: Optional[str] = None) -> PayloadAnalysisDocument:
        """Describe the upload natively (CPDO-1.2).

        Raises:
            ImportSourceError: If ``native_ast`` is not a parsed DICOM document.
        """
        if not isinstance(native_ast, DicomDocument):
            raise ImportSourceError("DICOM analysis needs a DicomDocument (see app.dicom_parser)")
        return analyze_dicom(native_ast, source=source, source_format=self.key)
