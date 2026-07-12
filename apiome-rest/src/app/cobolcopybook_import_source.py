"""COBOL copybook import source — MFI-22.7.

The :class:`~app.import_source.ImportSource` adapter that makes COBOL copybooks
importable into the catalog (store-raw, MFI-23.7).
"""

from __future__ import annotations

from typing import Any, Optional

from . import cobolcopybook_normalizer  # noqa: F401 — self-registers the normalizer
from .canonical_model import ApiParadigm, CanonicalApi
from .cobolcopybook_parser import (
    CobolCopybookDocument,
    CobolCopybookParseError,
    is_cobolcopybook,
    parse_cobolcopybook,
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

__all__ = ["CobolCopybookImportSource"]


class CobolCopybookImportSource(ImportSource, register=True):
    """Adapter for COBOL copybook record layouts (``.cpy`` / ``.copybook``)."""

    key = "cobolcopybook"
    label = "COBOL Copybook"
    description = "Import a COBOL copybook record layout and infer its data schema."
    icon = "file-code"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = ("cobolcopybook", "copybook", "cobol", "cobol-copybook")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        text = payload.text
        if text is not None and is_cobolcopybook(text):
            if " OCCURS " in text.upper():
                reason = "level-01 group with `PIC` / `OCCURS` clauses"
            else:
                reason = "level-01 group with `PIC` clauses"
            return DetectionResult(confidence=0.98, format="cobolcopybook", reason=reason)

        filename = (payload.filename or "").lower()
        if filename.endswith((".cpy", ".copybook", ".cbl")) and text is not None and is_cobolcopybook(text):
            return DetectionResult(
                confidence=0.85,
                format="cobolcopybook",
                reason="COBOL copybook filename extension",
            )
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> CobolCopybookDocument:
        try:
            return parse_cobolcopybook(raw, source_label=source_label)
        except CobolCopybookParseError as exc:
            raise ImportSourceError(str(exc)) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> CobolCopybookDocument:
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError("COBOL copybook fileset is missing its root document")
        return self.parse(fileset.members[root], source_label=root or source_label)

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(native_ast, CobolCopybookDocument):
            raise ImportSourceError(
                "COBOL copybook source must be a CobolCopybookDocument "
                "(see app.cobolcopybook_parser.parse_cobolcopybook)"
            )
        return self._normalize_via_registry("cobolcopybook", native_ast, include_raw=include_raw)
