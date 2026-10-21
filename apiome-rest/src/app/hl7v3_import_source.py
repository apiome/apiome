"""HL7 v3 / CDA import source — FMT-6.4 (#5448).

The :class:`~app.import_source.ImportSource` adapter for HL7 v3 Clinical Document Architecture (CDA
R2) documents — CCDs, discharge summaries and the other C-CDA document types — completing the HL7 set
beside the shipped HL7 v2 and FHIR adapters. A fileset (archive) is read from its root: a CDA document,
or the HL7 v3 transmission wrapper whose payload reference names the member holding one.
"""

from __future__ import annotations

from typing import Any, Optional

from . import hl7v3_normalizer  # noqa: F401 — self-registers the normalizer
from .canonical_model import ApiParadigm, CanonicalApi
from .fileset import IntakeFileset
from .hl7v3_parser import CdaDocument, Hl7V3ParseError, is_hl7v3, parse_hl7v3, parse_hl7v3_fileset
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
)

__all__ = ["Hl7V3ImportSource"]


class Hl7V3ImportSource(ImportSource, register=True):
    """Adapter for HL7 v3 / CDA documents (``.xml``, ``.cda``; file / url / paste / fileset)."""

    key = "hl7v3"
    label = "HL7 v3 / CDA"
    description = "Import an HL7 v3 CDA document (CCD, discharge summary, other C-CDA types) and infer its schema."
    icon = "heart-pulse"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = ("hl7v3", "cda", "c-cda", "hl7-cda")
    file_extensions = (".xml", ".cda")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a ``ClinicalDocument`` (or an HL7 v3 interaction) rooted in ``urn:hl7-org:v3``.

        Only the first start tag is examined, so a truncated or malformed document is still claimed
        and the parser names its fault.
        """
        text = payload.text
        root = is_hl7v3(text) if text is not None else None
        if root is None:
            return NO_MATCH
        if root == "ClinicalDocument":
            return DetectionResult(
                confidence=0.97, format="hl7v3", reason="`<ClinicalDocument>` root in `urn:hl7-org:v3`"
            )
        return DetectionResult(
            confidence=0.9, format="hl7v3", reason=f"HL7 v3 `<{root}>` root in `urn:hl7-org:v3`"
        )

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> CdaDocument:
        """Parse a CDA document, carrying the parser's taxonomy code onto the error."""
        try:
            return parse_hl7v3(raw, source_label=source_label)
        except Hl7V3ParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> CdaDocument:
        """Parse a fileset rooted at a CDA document or at the transmission wrapper carrying one.

        Raises:
            ImportSourceError: When the root is missing, unreadable, or a wrapper whose payload is
                not among the members.
        """
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError("HL7 v3 fileset is missing its root document")
        try:
            return parse_hl7v3_fileset(fileset.members, root, source_label=root or source_label)
        except Hl7V3ParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(native_ast, CdaDocument):
            raise ImportSourceError(
                "HL7 v3 source must be a CdaDocument (see app.hl7v3_parser.parse_hl7v3)"
            )
        return self._normalize_via_registry("hl7v3", native_ast, include_raw=include_raw)
