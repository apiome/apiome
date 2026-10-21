"""TRADACOMS import source — FMT-6.5 (#5449).

The :class:`~app.import_source.ImportSource` adapter that makes TRADACOMS transmissions — the UK
retail EDI standard — importable into the catalog, beside the EDIFACT adapter whose lexical layer
it reads with (:mod:`app.edifact_import_source`). It follows that adapter's shape exactly: parse the
transmission, normalize one detail message, and analyze every transmission, file and message
natively, recording the TRADACOMS dialect profile (:mod:`app.edi_dialect_profiles`).
"""

from __future__ import annotations

from typing import Any, Optional

from . import tradacoms_normalizer  # noqa: F401 — self-registers the normalizer
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
from .tradacoms_analysis import (
    TRADACOMS_ANALYZER_KEY,
    TRADACOMS_ANALYZER_VERSION,
    analyze_tradacoms,
    tradacoms_capabilities,
)
from .tradacoms_parser import (
    TradacomsDocument,
    TradacomsParseError,
    carries_message_header,
    is_tradacoms,
    parse_tradacoms,
)

__all__ = ["TradacomsImportSource"]


class TradacomsImportSource(ImportSource, register=True):
    """Adapter for TRADACOMS transmissions (``.edi`` / ``.tra`` file / url / paste)."""

    key = "tradacoms"
    label = "TRADACOMS"
    description = "Import a TRADACOMS transmission and infer its message schema."
    icon = "file-text"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = ("tradacoms",)
    file_extensions = (".edi", ".tra")
    analyzer_key = TRADACOMS_ANALYZER_KEY
    analyzer_version = TRADACOMS_ANALYZER_VERSION

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim text that opens with a TRADACOMS ``STX=`` transmission header.

        The marker is positional, so an EDIFACT interchange (``UNB``) or an X12 one sharing the
        ``.edi`` extension is never claimed. A header with no ``MHD`` message is still TRADACOMS —
        claimed at lower confidence, so the parser can say what is wrong with it.

        Args:
            payload: The candidate text and its file name.

        Returns:
            The detection result.
        """
        text = payload.text
        if text is None or not is_tradacoms(text):
            return NO_MATCH
        if carries_message_header(text):
            return DetectionResult(
                confidence=0.95,
                format="tradacoms",
                reason="`STX=` transmission header with `MHD` messages (TRADACOMS profile)",
            )
        return DetectionResult(
            confidence=0.7,
            format="tradacoms",
            reason="`STX=` transmission header without an `MHD` message",
        )

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> TradacomsDocument:
        """Parse a transmission, carrying the parser's taxonomy code onto the error."""
        try:
            return parse_tradacoms(raw, source_label=source_label)
        except TradacomsParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> TradacomsDocument:
        """Parse a fileset's root transmission, as the EDIFACT adapter does."""
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError("TRADACOMS fileset is missing its root document")
        return self.parse(fileset.members[root], source_label=root or source_label)

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(native_ast, TradacomsDocument):
            raise ImportSourceError(
                "TRADACOMS source must be a TradacomsDocument "
                "(see app.tradacoms_parser.parse_tradacoms)"
            )
        return self._normalize_via_registry("tradacoms", native_ast, include_raw=include_raw)

    def analysis_capabilities(self) -> AnalyzerCapabilities:
        """Return the TRADACOMS extractor's capability declaration."""
        return tradacoms_capabilities()

    def analyze(
        self, native_ast: Any, *, source: Optional[str] = None
    ) -> PayloadAnalysisDocument:
        """Describe the document natively — every transmission, file and message.

        Args:
            native_ast: The parsed :class:`~app.tradacoms_parser.TradacomsDocument`.
            source: The exact text analysed; defaults to the document's retained raw.

        Returns:
            The analysis document.

        Raises:
            ImportSourceError: If ``native_ast`` is not a TRADACOMS document.
        """
        if not isinstance(native_ast, TradacomsDocument):
            raise ImportSourceError(
                "TRADACOMS analysis needs a TradacomsDocument "
                "(see app.tradacoms_parser.parse_tradacoms)"
            )
        return analyze_tradacoms(native_ast, source=source, source_format=self.key)
