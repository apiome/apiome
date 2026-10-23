"""PL/I structure import source — FMT-11.1 (#5480).

The :class:`~app.import_source.ImportSource` adapter for PL/I ``DECLARE`` structures and their
``%INCLUDE`` members: :mod:`app.pli_parser` reads them, :mod:`app.pli_layout` computes the storage
map, :mod:`app.pli_normalizer` projects them onto the ``data_schema`` paradigm and
:mod:`app.pli_analysis` describes them natively.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Dict, Optional

from . import pli_normalizer  # noqa: F401 — self-registers the normalizer
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
from .mainframe_misc_common import MainframeParseError
from .payload_analysis import AnalyzerCapabilities, PayloadAnalysisDocument
from .pli_analysis import PLI_ANALYZER_KEY, PLI_ANALYZER_VERSION, analyze_pli, pli_capabilities, pli_tool_versions
from .pli_parser import FORMAT_KEY, PliDocument, has_pli_declarations, parse_pli_fileset, parse_pli_text

__all__ = ["PliImportSource"]

#: Suffixes claimed weakly when the text holds no declaration, so the reader can explain the fault.
_STRUCTURE_SUFFIXES = (".pli", ".pl1")
#: A level-1 structure declaration (``DCL 1 NAME``) — what separates an include member from a
#: program that merely declares a few scalars.
_STRUCTURE_DECLARATION = re.compile(r"\b(?:DCL|DECLARE)\s+1\s+[A-Z_@#$]", re.I)
_COMMENT = re.compile(r"/\*.*?\*/", re.S)


class PliImportSource(ImportSource, register=True):
    """Adapter for PL/I structure declarations (``.pli`` / ``.pl1`` / ``.inc``)."""

    key = FORMAT_KEY
    label = "PL/I structures"
    description = (
        "Import PL/I DECLARE structures and their %INCLUDE members: each structure becomes a record "
        "with a byte-accurate storage map under stated alignment and encoding assumptions."
    )
    icon = "file-code"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY, "pl1", "pl/i", "pli-include")
    file_extensions = (".pli", ".pl1", ".inc")
    analyzer_key = PLI_ANALYZER_KEY
    analyzer_version = PLI_ANALYZER_VERSION

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim ``DCL`` / ``DECLARE`` structures and ``%INCLUDE`` directives.

        A level-1 structure declaration (``DCL 1 NAME``) is claimed strongly; any other declaration
        or include directive less so. A ``.pli`` / ``.pl1`` file with neither is claimed weakly, so the
        reader can say what is wrong with it.
        """
        text = payload.text
        if text is None:
            return NO_MATCH
        if has_pli_declarations(text):
            if _has_structure(text):
                return DetectionResult(confidence=0.95, format=self.key, reason="DCL level-1 structure declaration")
            return DetectionResult(confidence=0.85, format=self.key, reason="PL/I DCL statement or %INCLUDE directive")
        if PurePosixPath((payload.filename or "").lower()).suffix in _STRUCTURE_SUFFIXES:
            return DetectionResult(confidence=0.5, format=self.key, reason="PL/I file extension")
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> PliDocument:
        """Parse one file; any ``%INCLUDE`` in it is unresolved.

        Raises:
            ImportSourceError: With the reader's taxonomy code (see :mod:`app.pli_parser`).
        """
        try:
            return parse_pli_text(raw, label=source_label)
        except MainframeParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> PliDocument:
        """Parse a fileset's root, resolving ``%INCLUDE`` against its members.

        Raises:
            ImportSourceError: With the reader's taxonomy code (see :mod:`app.pli_parser`).
        """
        try:
            return parse_pli_fileset(fileset, label=source_label)
        except MainframeParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize the parsed document onto the data_schema paradigm.

        Raises:
            ImportSourceError: When ``native_ast`` is not a :class:`~app.pli_parser.PliDocument`.
        """
        if not isinstance(native_ast, PliDocument):
            raise ImportSourceError("PL/I source must be a PliDocument (see app.pli_parser)")
        return self._normalize_via_registry(self.key, native_ast, include_raw=include_raw)

    def analyzer_tool_versions(self) -> Dict[str, str]:
        """Return the PL/I reader version behind the analysis."""
        return pli_tool_versions()

    def analysis_capabilities(self) -> AnalyzerCapabilities:
        """Return the PL/I extractor's capability declaration."""
        return pli_capabilities()

    def analyze(self, native_ast: Any, *, source: Optional[str] = None) -> PayloadAnalysisDocument:
        """Describe the declarations natively — levels, attributes and the storage map.

        Raises:
            ImportSourceError: When ``native_ast`` is not a :class:`~app.pli_parser.PliDocument`.
        """
        if not isinstance(native_ast, PliDocument):
            raise ImportSourceError("PL/I analysis needs a PliDocument (see app.pli_parser)")
        return analyze_pli(native_ast, source=source, source_format=self.key)


def _has_structure(text: str) -> bool:
    """Whether a ``DCL 1 name`` structure declaration appears (comments ignored)."""
    return bool(_STRUCTURE_DECLARATION.search(_COMMENT.sub(" ", text)))
