"""NCPDP SCRIPT and Telecom import source — FMT-6.8 (#5452).

The :class:`~app.import_source.ImportSource` adapter for the two NCPDP pharmacy standards:

* **SCRIPT** (e-prescribing) — XML ``Message`` documents carrying ``NewRx``, ``RxFill``,
  ``RxChangeRequest`` and the other transactions (:mod:`app.ncpdp_script`);
* **Telecommunication D.0** (pharmacy claims) — a fixed transaction header and ``AM`` segments of
  two-character fields (:mod:`app.ncpdp_telecom`).

Each message's (or transmission's) transaction type is detected and recorded; the structure imports
as native canonical types with no payload values (:mod:`app.ncpdp_normalizer`), and the native
analysis keeps the shared EDI contract (:mod:`app.ncpdp_analysis`). No implementation guide is
consulted. A SCRIPT fileset is read as one conversation — the root and its SCRIPT siblings.
"""

from __future__ import annotations

from typing import Any, Optional

from . import ncpdp_normalizer  # noqa: F401 — self-registers the normalizer
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
from .ncpdp_analysis import (
    NCPDP_ANALYZER_KEY,
    NCPDP_ANALYZER_VERSION,
    analyze_ncpdp,
    ncpdp_capabilities,
)
from .ncpdp_parser import (
    SUB_FORMAT_SCRIPT,
    NcpdpDocument,
    NcpdpParseError,
    is_ncpdp,
    parse_ncpdp,
    parse_ncpdp_fileset,
)
from .ncpdp_telecom import SUPPORTED_TELECOM_VERSIONS
from .payload_analysis import AnalyzerCapabilities, PayloadAnalysisDocument

__all__ = ["NcpdpImportSource"]


class NcpdpImportSource(ImportSource, register=True):
    """Adapter for NCPDP SCRIPT (``.xml``) and Telecom D.0 (``.dat``, ``.ncpdp``) documents."""

    key = "ncpdp"
    label = "NCPDP SCRIPT / Telecom"
    description = (
        "Import an NCPDP SCRIPT e-prescribing message or a Telecommunication D.0 pharmacy claim and infer its schema."
    )
    icon = "pill"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = ("ncpdp", "ncpdp-script", "ncpdp-telecom")
    file_extensions = (".xml", ".dat", ".ncpdp")
    analyzer_key = NCPDP_ANALYZER_KEY
    analyzer_version = NCPDP_ANALYZER_VERSION

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a SCRIPT ``Message``/``Messages`` root, or a Telecom request header.

        Only the opening is examined, so a truncated or malformed document — or a Telecom header that
        names another version — is still claimed and the parser says what is wrong with it.
        """
        text = payload.text
        sub_format = is_ncpdp(text) if text is not None else None
        if sub_format is None:
            return NO_MATCH
        if sub_format == SUB_FORMAT_SCRIPT:
            return DetectionResult(
                confidence=0.97,
                format="ncpdp",
                reason="`<Message>` root in the NCPDP SCRIPT namespace",
            )
        assert text is not None
        version = text[6:8]
        return DetectionResult(
            confidence=0.95 if version in SUPPORTED_TELECOM_VERSIONS else 0.85,
            format="ncpdp",
            reason=f"NCPDP Telecom transaction header (version `{version}`) followed by `AM` segments",
        )

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> NcpdpDocument:
        """Parse a SCRIPT document or Telecom transmission, carrying the taxonomy code."""
        try:
            return parse_ncpdp(raw, source_label=source_label)
        except NcpdpParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> NcpdpDocument:
        """Parse a fileset from its root; a SCRIPT root reads its SCRIPT siblings with it.

        Raises:
            ImportSourceError: When the root is missing or a document is unreadable.
        """
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError("NCPDP fileset is missing its root document")
        try:
            return parse_ncpdp_fileset(fileset.members, root, source_label=source_label)
        except NcpdpParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(native_ast, NcpdpDocument):
            raise ImportSourceError("NCPDP source must be an NcpdpDocument (see app.ncpdp_parser.parse_ncpdp)")
        return self._normalize_via_registry("ncpdp", native_ast, include_raw=include_raw)

    def analysis_capabilities(self) -> AnalyzerCapabilities:
        """The NCPDP extractor's capability declaration (CPDO-1.2)."""
        return ncpdp_capabilities()

    def analyze(self, native_ast: Any, *, source: Optional[str] = None) -> PayloadAnalysisDocument:
        """Describe the document natively (CPDO-1.2).

        Raises:
            ImportSourceError: If ``native_ast`` is not a parsed NCPDP document.
        """
        if not isinstance(native_ast, NcpdpDocument):
            raise ImportSourceError("NCPDP analysis needs an NcpdpDocument (see app.ncpdp_parser.parse_ncpdp)")
        return analyze_ncpdp(native_ast, source=source, source_format=self.key)
