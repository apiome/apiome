"""UN/EDIFACT import source — FMT-6.1 (#5445).

The :class:`~app.import_source.ImportSource` adapter that makes UN/EDIFACT batch interchanges
(ISO 9735) importable into the catalog, beside its North American twin
(:mod:`app.edix12_import_source`). It follows the X12 adapter's shape exactly: parse the
interchange, normalize the first group's first message, and analyze the whole envelope natively.
"""

from __future__ import annotations

from typing import Any, Optional

from . import edifact_normalizer  # noqa: F401 — self-registers the normalizer
from .canonical_model import ApiParadigm, CanonicalApi
from .edi_dialect_profiles import UN_EDIFACT, edifact_profile
from .edifact_analysis import (
    EDIFACT_ANALYZER_KEY,
    EDIFACT_ANALYZER_VERSION,
    analyze_edifact,
    edifact_capabilities,
)
from .edifact_parser import (
    EdifactDocument,
    EdifactParseError,
    carries_message_header,
    is_edifact,
    parse_edifact,
)
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

__all__ = ["EdifactImportSource"]


def _profile_reason(text: str) -> str:
    """Name the dialect profile an interchange is written in, for a detection reason.

    Args:
        text: Text :func:`~app.edifact_parser.is_edifact` claimed.

    Returns:
        ``" — EANCOM profile"`` (or ODETTE/VDA) when one applies, else ``""`` — including when the
        text does not parse, which the parse phase reports properly.
    """
    try:
        match = edifact_profile(parse_edifact(text))
    except EdifactParseError:
        return ""
    if match.profile is UN_EDIFACT:
        return ""
    return f" — {match.profile.label} profile"


class EdifactImportSource(ImportSource, register=True):
    """Adapter for UN/EDIFACT interchanges (``.edi`` / ``.edifact`` file / url / paste)."""

    key = "edifact"
    label = "UN/EDIFACT"
    description = "Import a UN/EDIFACT interchange and infer its message schema."
    icon = "file-text"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = ("edifact", "un-edifact")
    file_extensions = (".edi", ".edifact")
    analyzer_key = EDIFACT_ANALYZER_KEY
    analyzer_version = EDIFACT_ANALYZER_VERSION

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim text that opens with an EDIFACT interchange header.

        The marker is positional (``UNB`` first, optionally after ``UNA``), so an X12 interchange
        or a TRADACOMS transmission (``STX=``) sharing the ``.edi`` extension is never claimed. An
        interchange header with no ``UNH`` is still EDIFACT — claimed at lower confidence, so the
        parser can say what is wrong with it. The reason names the dialect profile (EANCOM,
        ODETTE/VDA — FMT-6.5) when the interchange carries one's evidence.

        Args:
            payload: The candidate text and its file name.

        Returns:
            The detection result.
        """
        text = payload.text
        if text is None or not is_edifact(text):
            return NO_MATCH
        if carries_message_header(text):
            return DetectionResult(
                confidence=0.95,
                format="edifact",
                reason="`UNB` interchange header (optionally after `UNA`) with `UNH` messages"
                + _profile_reason(text),
            )
        return DetectionResult(
            confidence=0.7,
            format="edifact",
            reason="`UNB` interchange header without a `UNH` message",
        )

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> EdifactDocument:
        """Parse an interchange, carrying the parser's taxonomy code onto the error."""
        try:
            return parse_edifact(raw, source_label=source_label)
        except EdifactParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> EdifactDocument:
        """Parse a fileset's root interchange, as the X12 adapter does."""
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError("EDIFACT fileset is missing its root document")
        return self.parse(fileset.members[root], source_label=root or source_label)

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(native_ast, EdifactDocument):
            raise ImportSourceError(
                "EDIFACT source must be an EdifactDocument (see app.edifact_parser.parse_edifact)"
            )
        return self._normalize_via_registry("edifact", native_ast, include_raw=include_raw)

    def analysis_capabilities(self) -> AnalyzerCapabilities:
        """Return the EDIFACT extractor's capability declaration (CPDO-1.2).

        Returns:
            The analyzer's capability declaration — the same for every record, because the parser
            reads positions and empty element positions from the text itself.
        """
        return edifact_capabilities()

    def analyze(
        self, native_ast: Any, *, source: Optional[str] = None
    ) -> PayloadAnalysisDocument:
        """Describe the interchange natively — every group and message (CPDO-1.2).

        Args:
            native_ast: The parsed :class:`~app.edifact_parser.EdifactDocument`.
            source: The exact interchange text analysed; defaults to the document's retained raw.

        Returns:
            The analysis document.

        Raises:
            ImportSourceError: If ``native_ast`` is not an EDIFACT document.
        """
        if not isinstance(native_ast, EdifactDocument):
            raise ImportSourceError(
                "EDIFACT analysis needs an EdifactDocument (see app.edifact_parser.parse_edifact)"
            )
        return analyze_edifact(native_ast, source=source, source_format=self.key)
