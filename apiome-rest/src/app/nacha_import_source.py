"""NACHA ACH import source — FMT-6.6 (#5450).

The :class:`~app.import_source.ImportSource` adapter for NACHA ACH payment files: fixed-width
94-character records whose type code drives the field map (:mod:`app.nacha_records`). Batches and
entries import as native structure (:mod:`app.nacha_normalizer`), and every batch and file control
total is recorded as declared versus observed (:mod:`app.nacha_controls`), following the X12
control-total contract. A fileset (archive) is read from its root document.

SEPA payment files are the European counterpart, but they are ISO 20022 XML and route to the
shipped ``iso20022`` adapter (:mod:`app.iso20022_sepa`), never here.
"""

from __future__ import annotations

from typing import Any, Optional

from . import nacha_normalizer  # noqa: F401 — self-registers the normalizer
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
from .nacha_analysis import (
    NACHA_ANALYZER_KEY,
    NACHA_ANALYZER_VERSION,
    analyze_nacha,
    nacha_capabilities,
)
from .nacha_parser import NachaFile, NachaParseError, is_nacha, parse_nacha
from .payload_analysis import AnalyzerCapabilities, PayloadAnalysisDocument

__all__ = ["NachaImportSource"]


class NachaImportSource(ImportSource, register=True):
    """Adapter for NACHA ACH files (``.ach``, ``.txt``, ``.nacha``; file / url / paste / fileset)."""

    key = "nacha"
    label = "NACHA ACH"
    description = "Import a NACHA ACH payment file and infer its batch and entry record schema."
    icon = "landmark"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = ("nacha", "ach")
    file_extensions = (".ach", ".nacha", ".txt")
    analyzer_key = NACHA_ANALYZER_KEY
    analyzer_version = NACHA_ANALYZER_VERSION

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim text whose first record is an ACH file header.

        The marker is the header's fixed fields — record type ``1``, record size ``094`` and
        blocking factor ``10`` — so a file that is truncated or malformed further on is still
        claimed and the parser can say what is wrong with it.
        """
        if not is_nacha(payload.text):
            return NO_MATCH
        return DetectionResult(
            confidence=0.97,
            format="nacha",
            reason="ACH file header: record type `1`, record size `094`, blocking factor `10`",
        )

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> NachaFile:
        """Parse ACH text, carrying the parser's taxonomy code onto the error."""
        try:
            return parse_nacha(raw, source_label=source_label)
        except NachaParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> NachaFile:
        """Parse the fileset's root document.

        Raises:
            ImportSourceError: When the root is missing or is not a readable ACH file.
        """
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError("NACHA ACH fileset is missing its root document")
        return self.parse(fileset.members[root], source_label=root or source_label)

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(native_ast, NachaFile):
            raise ImportSourceError("NACHA source must be a NachaFile (see app.nacha_parser.parse_nacha)")
        return self._normalize_via_registry("nacha", native_ast, include_raw=include_raw)

    def analysis_capabilities(self) -> AnalyzerCapabilities:
        """The ACH extractor's capability declaration (CPDO-1.2)."""
        return nacha_capabilities()

    def analyze(self, native_ast: Any, *, source: Optional[str] = None) -> PayloadAnalysisDocument:
        """Describe the file natively (CPDO-1.2).

        Raises:
            ImportSourceError: If ``native_ast`` is not a parsed ACH file.
        """
        if not isinstance(native_ast, NachaFile):
            raise ImportSourceError("NACHA analysis needs a NachaFile (see app.nacha_parser.parse_nacha)")
        return analyze_nacha(native_ast, source=source, source_format=self.key)
