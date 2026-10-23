"""IMS DBD and PSB import source — FMT-11.2 (#5482).

The :class:`~app.import_source.ImportSource` adapter for IMS database descriptions (DBD) and
program specification blocks (PSB): :mod:`app.ims_parser` reads the macro source and
:mod:`app.ims_normalizer` projects the segment hierarchy, its byte-accurate fields and each
program's ``PROCOPT`` access profile onto the ``data_schema`` paradigm.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Optional

from . import ims_normalizer  # noqa: F401 — self-registers the normalizer
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
from .ims_parser import FORMAT_KEY, ImsDocument, has_ims_statements, parse_ims_fileset, parse_ims_text
from .mainframe_misc_common import MainframeParseError

__all__ = ["ImsImportSource"]

#: Suffixes claimed weakly when the text holds no DBD / PCB statement, so the reader can explain
#: the fault.
_IMS_SUFFIXES = (".dbd", ".psb")


class ImsImportSource(ImportSource, register=True):
    """Adapter for IMS DBD and PSB macro source (``.dbd`` / ``.psb``)."""

    key = FORMAT_KEY
    label = "IMS DBD and PSB"
    description = (
        "Import IMS database descriptions (DBD) and program specification blocks (PSB): the segment "
        "hierarchy becomes nested records with byte-accurate fields, and each program's PROCOPT "
        "becomes a declared access profile."
    )
    icon = "database"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY, "ims-dbd", "ims-psb", "dbd", "psb")
    file_extensions = _IMS_SUFFIXES

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim ``DBD NAME=`` / ``PCB TYPE=`` macro source.

        A ``DBD`` or ``PCB`` statement with ``SEGM`` / ``SENSEG`` statements is claimed strongly; the
        opening statement alone less so. A ``.dbd`` / ``.psb`` file with neither is claimed weakly,
        so the reader can say what is wrong with it.
        """
        text = payload.text
        if text is None:
            return NO_MATCH
        opens, segments = has_ims_statements(text)
        if segments:
            return DetectionResult(confidence=0.95, format=self.key, reason="IMS DBD SEGM or PSB SENSEG statements")
        if opens:
            return DetectionResult(confidence=0.9, format=self.key, reason="IMS DBD or PCB statement")
        if PurePosixPath((payload.filename or "").lower()).suffix in _IMS_SUFFIXES:
            return DetectionResult(confidence=0.5, format=self.key, reason="IMS DBD / PSB file extension")
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> ImsDocument:
        """Parse one DBD or PSB file; a PSB read alone leaves its DBDs unresolved.

        Raises:
            ImportSourceError: With the reader's taxonomy code (see :mod:`app.ims_parser`).
        """
        try:
            return parse_ims_text(raw, label=source_label)
        except MainframeParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> ImsDocument:
        """Parse DBDs and PSBs uploaded together, resolving each PSB's DBD in the set.

        Raises:
            ImportSourceError: With the reader's taxonomy code (see :mod:`app.ims_parser`).
        """
        try:
            return parse_ims_fileset(fileset, label=source_label)
        except MainframeParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize the parsed document onto the data_schema paradigm.

        Raises:
            ImportSourceError: When ``native_ast`` is not an :class:`~app.ims_parser.ImsDocument`.
        """
        if not isinstance(native_ast, ImsDocument):
            raise ImportSourceError("IMS source must be an ImsDocument (see app.ims_parser)")
        return self._normalize_via_registry(self.key, native_ast, include_raw=include_raw)
