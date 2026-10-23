"""``mainframe-misc`` import sources: VSAM catalog and CICS BMS maps — FMT-11.3 (#5484).

Two :class:`~app.import_source.ImportSource` adapters built from the same family of modules, each
pinned to one sub-format so that each refuses the other's text as ``FORMAT_MISMATCH``:

* ``vsam-idcams`` — IDCAMS ``DEFINE CLUSTER`` / ``AIX`` / ``PATH`` / ``GDG`` commands (bare or
  wrapped in JCL) and ``LISTCAT`` listings, read by :mod:`app.vsam_idcams_parser`: each cluster's
  record envelope — organisation, record size, primary and alternate keys — becomes a record;
* ``cics-bms`` — ``DFHMSD`` / ``DFHMDI`` / ``DFHMDF`` macro source and the symbolic-map copybooks
  BMS generates, read by :mod:`app.cics_bms_parser`: each map becomes a record whose fields are
  positioned by row and column.

Both normalize onto the ``data_schema`` paradigm (:mod:`app.mainframe_misc_normalizer`).
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Callable, ClassVar, Optional

from . import mainframe_misc_normalizer  # noqa: F401 — self-registers both normalizers
from .canonical_model import ApiParadigm, CanonicalApi
from .cics_bms_parser import FORMAT_KEY as BMS_FORMAT_KEY
from .cics_bms_parser import BmsDocument, has_bms_macros, is_symbolic_map, parse_bms_fileset, parse_bms_text
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
from .vsam_idcams_parser import FORMAT_KEY as VSAM_FORMAT_KEY
from .vsam_idcams_parser import (
    VsamDocument,
    has_idcams_commands,
    is_listcat_listing,
    parse_vsam_fileset,
    parse_vsam_text,
)

__all__ = ["CicsBmsImportSource", "MainframeMiscImportSource", "VsamIdcamsImportSource"]


def _suffix(filename: Optional[str]) -> str:
    return PurePosixPath((filename or "").strip().lower()).suffix


class MainframeMiscImportSource(ImportSource):
    """Shared steps of the ``mainframe-misc`` sub-format adapters (not registered itself).

    A subclass names its format key, the document class its reader returns, and the reader's two
    entry points; parsing, error mapping and normalization are the same for both.
    """

    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    #: The reader's document class, checked before normalizing.
    document_type: ClassVar[type]
    #: ``parse_text(text, label=...)`` and ``parse_fileset(fileset, label=...)`` of the reader.
    read_text: ClassVar[Callable[..., Any]]
    read_fileset: ClassVar[Callable[..., Any]]

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> Any:
        """Parse one file, carrying the reader's taxonomy code.

        Raises:
            ImportSourceError: When the source cannot be read (see the reader's module docstring).
        """
        try:
            return type(self).read_text(raw, label=source_label)
        except MainframeParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> Any:
        """Parse a set of members read together, carrying the reader's taxonomy code.

        Raises:
            ImportSourceError: When a member cannot be read or a reference cannot be resolved.
        """
        try:
            return type(self).read_fileset(fileset, label=source_label)
        except MainframeParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize the parsed document onto the data_schema paradigm.

        Raises:
            ImportSourceError: When ``native_ast`` is not this sub-format's parsed document.
        """
        if not isinstance(native_ast, self.document_type):
            raise ImportSourceError(
                f"{self.label} source must be a {self.document_type.__name__} (see {self.document_type.__module__})"
            )
        return self._normalize_via_registry(self.key, native_ast, include_raw=include_raw)


class VsamIdcamsImportSource(MainframeMiscImportSource, register=True):
    """Adapter for VSAM cluster definitions: IDCAMS commands and LISTCAT listings."""

    key = VSAM_FORMAT_KEY
    label = "VSAM cluster definitions (IDCAMS)"
    description = (
        "Import IDCAMS DEFINE CLUSTER / AIX / PATH commands or a LISTCAT listing: each cluster's "
        "record envelope — organisation, record size, primary and alternate keys — becomes a record."
    )
    icon = "database"
    formats = (VSAM_FORMAT_KEY, "vsam", "idcams")
    file_extensions = (".idcams", ".jcl")
    document_type = VsamDocument
    read_text = staticmethod(parse_vsam_text)
    read_fileset = staticmethod(parse_vsam_fileset)

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim IDCAMS ``DEFINE`` commands or a LISTCAT listing.

        A ``DEFINE CLUSTER`` / ``AIX`` / ``PATH`` / ``GDG`` command is specific to IDCAMS; it is
        claimed more strongly inside the JCL that runs IDCAMS. A file named ``.idcams`` without
        either is claimed weakly, so the reader can say what is wrong with it.
        """
        text = payload.text
        if text is None:
            return NO_MATCH
        if has_idcams_commands(text):
            if "PGM=IDCAMS" in text.upper():
                return DetectionResult(confidence=0.95, format=self.key, reason="IDCAMS job step with DEFINE commands")
            return DetectionResult(
                confidence=0.92, format=self.key, reason="IDCAMS DEFINE CLUSTER / AIX / PATH commands"
            )
        if is_listcat_listing(text):
            return DetectionResult(confidence=0.9, format=self.key, reason="LISTCAT listing of a VSAM cluster")
        if _suffix(payload.filename) == ".idcams":
            return DetectionResult(confidence=0.5, format=self.key, reason="IDCAMS file extension")
        return NO_MATCH


class CicsBmsImportSource(MainframeMiscImportSource, register=True):
    """Adapter for CICS BMS maps: DFHMSD / DFHMDI / DFHMDF macros and symbolic-map copybooks."""

    key = BMS_FORMAT_KEY
    label = "CICS BMS maps"
    description = (
        "Import a CICS BMS mapset (DFHMSD / DFHMDI / DFHMDF) or its symbolic-map copybook: each 3270 "
        "map becomes a record whose fields are positioned by row and column."
    )
    icon = "monitor"
    formats = (BMS_FORMAT_KEY, "bms", "cics-map")
    file_extensions = (".bms", ".cpy")
    document_type = BmsDocument
    read_text = staticmethod(parse_bms_text)
    read_fileset = staticmethod(parse_bms_fileset)

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim BMS macro source, or a BMS-generated symbolic map.

        A symbolic map is also a valid COBOL copybook; its ``<map>I`` / ``<map>O REDEFINES``
        records and ``L`` / ``F`` / ``I`` field entries are specific to BMS, so it is claimed above
        the general copybook adapter.
        """
        text = payload.text
        if text is None:
            return NO_MATCH
        if has_bms_macros(text):
            return DetectionResult(confidence=0.95, format=self.key, reason="DFHMSD / DFHMDI / DFHMDF macros")
        if is_symbolic_map(text):
            return DetectionResult(
                confidence=0.99, format=self.key, reason="BMS symbolic map (<map>I / <map>O REDEFINES records)"
            )
        if _suffix(payload.filename) == ".bms":
            return DetectionResult(confidence=0.5, format=self.key, reason="BMS file extension")
        return NO_MATCH
