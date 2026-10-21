"""SAP IDoc import source — FMT-6.2 (#5446).

The :class:`~app.import_source.ImportSource` adapter for SAP IDocs in the flat-file form
(``EDI_DC40`` + ``EDI_DD40`` records) and the IDoc XML form. A fileset (archive) may carry
WE60-style segment-definition exports beside the IDoc; they supply the field offsets a flat
segment's ``SDATA`` is cut by.
"""

from __future__ import annotations

from typing import Any, List, Optional

from . import idoc_normalizer  # noqa: F401 — self-registers the normalizer
from .canonical_model import ApiParadigm, CanonicalApi
from .fileset import IntakeFileset
from .idoc_analysis import (
    IDOC_ANALYZER_KEY,
    IDOC_ANALYZER_VERSION,
    analyze_idoc,
    idoc_capabilities,
)
from .idoc_parser import (
    IdocFile,
    IdocParseError,
    SegmentDefinitionSet,
    has_xml_control_record,
    is_idoc,
    is_segment_definition,
    merge_definitions,
    parse_idoc,
    parse_segment_definitions,
)
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
)
from .payload_analysis import AnalyzerCapabilities, PayloadAnalysisDocument

__all__ = ["IdocImportSource"]


class IdocImportSource(ImportSource, register=True):
    """Adapter for SAP IDocs (flat ``.idoc``/``.txt`` or XML; file / url / paste / fileset)."""

    key = "idoc"
    label = "SAP IDoc"
    description = "Import an SAP IDoc (flat file or XML) and infer its basic-type schema."
    icon = "file-text"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = ("idoc", "sap-idoc")
    file_extensions = (".idoc", ".txt", ".xml")
    analyzer_key = IDOC_ANALYZER_KEY
    analyzer_version = IDOC_ANALYZER_VERSION

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a flat file that opens with ``EDI_DC40``, or XML holding an ``<IDOC>``.

        An XML IDoc without its ``<EDI_DC40>`` is still claimed, at lower confidence, so the parser
        can refuse it for the right reason (no control record) rather than as another format.
        """
        text = payload.text
        if text is None or not is_idoc(text):
            return NO_MATCH
        if text.lstrip().startswith("EDI_DC40"):
            return DetectionResult(
                confidence=0.97, format="idoc", reason="flat `EDI_DC40` control record"
            )
        if has_xml_control_record(text):
            return DetectionResult(
                confidence=0.95, format="idoc", reason="IDoc XML `<IDOC>` with `<EDI_DC40>`"
            )
        # Above the greedy 0.7 claims other sniffers make on any prose (gRPC on the word
        # "message"): an <IDOC> element is the stronger evidence.
        return DetectionResult(
            confidence=0.75, format="idoc", reason="IDoc XML `<IDOC>` without a control record"
        )

    def parse(
        self,
        raw: str,
        *,
        source_label: Optional[str] = None,
        definitions: Optional[SegmentDefinitionSet] = None,
    ) -> IdocFile:
        """Parse an IDoc, carrying the parser's taxonomy code onto the error."""
        try:
            return parse_idoc(raw, source_label=source_label, definitions=definitions)
        except IdocParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> IdocFile:
        """Parse the root IDoc with every segment-definition member applied to it.

        Members that are segment definitions are read first; the root is the fileset's root, or — when
        the root is itself a definition — the first member that is an IDoc.

        Raises:
            ImportSourceError: When no member is an IDoc, or a definition member is unreadable.
        """
        definitions: List[SegmentDefinitionSet] = []
        for path in sorted(fileset.members):
            text = fileset.members[path]
            if is_segment_definition(text):
                try:
                    definitions.append(parse_segment_definitions(text, source_label=path))
                except IdocParseError as exc:
                    raise ImportSourceError(str(exc), code=exc.code) from exc
        root = fileset.root
        if root not in fileset.members or not is_idoc(fileset.members[root]):
            root = next(
                (path for path in sorted(fileset.members) if is_idoc(fileset.members[path])), None
            )
        if root is None:
            raise ImportSourceError("IDoc fileset carries no IDoc document")
        return self.parse(
            fileset.members[root],
            source_label=root or source_label,
            definitions=merge_definitions(definitions),
        )

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(native_ast, IdocFile):
            raise ImportSourceError("IDoc source must be an IdocFile (see app.idoc_parser.parse_idoc)")
        return self._normalize_via_registry("idoc", native_ast, include_raw=include_raw)

    def analysis_capabilities(self) -> AnalyzerCapabilities:
        """The format-wide declaration: what the analyzer models for a flat IDoc it can read."""
        return idoc_capabilities(flat=True)

    def analyze(self, native_ast: Any, *, source: Optional[str] = None) -> PayloadAnalysisDocument:
        """Describe every IDoc in the file natively (CPDO-1.2).

        Raises:
            ImportSourceError: If ``native_ast`` is not an IDoc file.
        """
        if not isinstance(native_ast, IdocFile):
            raise ImportSourceError("IDoc analysis needs an IdocFile (see app.idoc_parser.parse_idoc)")
        return analyze_idoc(native_ast, source=source, source_format=self.key)
