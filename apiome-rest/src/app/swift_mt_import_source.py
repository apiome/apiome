"""SWIFT MT import source — FMT-6.3 (#5447).

The :class:`~app.import_source.ImportSource` adapter for SWIFT FIN (MT) messages — MT103, MT202
(and COV), MT940 and MT942 — beside the shipped ISO 20022 (MX) adapter. A fileset (archive) is read
from its root document, as the X12 and EDIFACT adapters read theirs; several messages written one
after another in one file are all read, and the analysis shows which one covers which.
"""

from __future__ import annotations

from typing import Any, Optional

from . import swift_mt_normalizer  # noqa: F401 — self-registers the normalizer
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
from .payload_analysis import AnalyzerCapabilities, PayloadAnalysisDocument
from .swift_mt_analysis import (
    SWIFT_MT_ANALYZER_KEY,
    SWIFT_MT_ANALYZER_VERSION,
    analyze_swift_mt,
    swift_mt_capabilities,
)
from .swift_mt_parser import SwiftMtFile, SwiftMtParseError, is_swift_mt, parse_swift_mt

__all__ = ["SwiftMtImportSource"]


class SwiftMtImportSource(ImportSource, register=True):
    """Adapter for SWIFT MT messages (``.fin``, ``.mt``, ``.txt``; file / url / paste / fileset)."""

    key = "swift-mt"
    label = "SWIFT MT"
    description = "Import SWIFT MT messages (MT103, MT202, MT940, MT942) and infer their field schema."
    icon = "file-text"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = ("swift-mt", "swift", "mt")
    file_extensions = (".fin", ".mt", ".txt")
    analyzer_key = SWIFT_MT_ANALYZER_KEY
    analyzer_version = SWIFT_MT_ANALYZER_VERSION

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim text that opens with a ``{1:`` basic header and carries a ``{4:`` text block.

        An unterminated text block is still claimed, at lower confidence, so the parser can say
        whether it was truncated or only lost its ``-}``.
        """
        text = payload.text
        if text is None or not is_swift_mt(text):
            return NO_MATCH
        if "-}" in text:
            return DetectionResult(
                confidence=0.96, format="swift-mt", reason="`{1:` basic header and `{4:` … `-}` text"
            )
        return DetectionResult(
            confidence=0.8, format="swift-mt", reason="`{1:` basic header with an unterminated text block"
        )

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> SwiftMtFile:
        """Parse MT text, carrying the parser's taxonomy code onto the error."""
        try:
            return parse_swift_mt(raw, source_label=source_label)
        except SwiftMtParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> SwiftMtFile:
        """Parse the fileset's root document.

        Raises:
            ImportSourceError: When the root is missing or is not a readable MT message.
        """
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError("SWIFT MT fileset is missing its root document")
        return self.parse(fileset.members[root], source_label=root or source_label)

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(native_ast, SwiftMtFile):
            raise ImportSourceError(
                "SWIFT MT source must be a SwiftMtFile (see app.swift_mt_parser.parse_swift_mt)"
            )
        return self._normalize_via_registry("swift-mt", native_ast, include_raw=include_raw)

    def analysis_capabilities(self) -> AnalyzerCapabilities:
        """The MT extractor's capability declaration (CPDO-1.2)."""
        return swift_mt_capabilities()

    def analyze(self, native_ast: Any, *, source: Optional[str] = None) -> PayloadAnalysisDocument:
        """Describe every message natively (CPDO-1.2).

        Raises:
            ImportSourceError: If ``native_ast`` is not a SWIFT MT file.
        """
        if not isinstance(native_ast, SwiftMtFile):
            raise ImportSourceError(
                "SWIFT MT analysis needs a SwiftMtFile (see app.swift_mt_parser.parse_swift_mt)"
            )
        return analyze_swift_mt(native_ast, source=source, source_format=self.key)
