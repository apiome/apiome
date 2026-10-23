"""Natural / ADABAS DDM import source — FMT-11.4 (#5486).

The :class:`~app.import_source.ImportSource` adapter for Natural DDM listings:
:mod:`app.natural_ddm_parser` reads the listing (and any Natural ``DEFINE DATA`` views uploaded
beside it) and :mod:`app.natural_ddm_normalizer` projects the file's fields, groups, multiple-value
fields, periodic groups and descriptors onto the ``data_schema`` paradigm.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Optional

from . import natural_ddm_normalizer  # noqa: F401 — self-registers the normalizer
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
from .natural_ddm_parser import FORMAT_KEY, DdmDocument, has_ddm_header, parse_ddm_fileset, parse_ddm_text

__all__ = ["NaturalDdmImportSource"]

#: Suffix claimed weakly when the text holds no DDM header, so the reader can explain the fault.
_DDM_SUFFIX = ".ddm"


class NaturalDdmImportSource(ImportSource, register=True):
    """Adapter for Natural / ADABAS DDM listings (``.ddm``)."""

    key = FORMAT_KEY
    label = "Natural / ADABAS DDM"
    description = (
        "Import a Natural DDM listing: the ADABAS file's fields, groups, multiple-value fields and "
        "periodic groups become a record with byte lengths under stated assumptions, and its "
        "descriptors and superdescriptors become declared key metadata."
    )
    icon = "database"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY, "ddm", "adabas", "natural")
    file_extensions = (_DDM_SUFFIX,)

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a ``DDM Name ......`` header, strongly when the column banner follows it.

        A ``.ddm`` file with neither is claimed weakly, so the reader can say what is wrong with it.
        """
        text = payload.text
        if text is None:
            return NO_MATCH
        header, banner = has_ddm_header(text)
        if banner:
            return DetectionResult(confidence=0.95, format=self.key, reason="DDM header and field column banner")
        if header:
            return DetectionResult(confidence=0.85, format=self.key, reason="DDM Name header")
        if PurePosixPath((payload.filename or "").lower()).suffix == _DDM_SUFFIX:
            return DetectionResult(confidence=0.5, format=self.key, reason="DDM file extension")
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> DdmDocument:
        """Parse one DDM listing.

        Raises:
            ImportSourceError: With the reader's taxonomy code (see :mod:`app.natural_ddm_parser`).
        """
        try:
            return parse_ddm_text(raw, label=source_label)
        except MainframeParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> DdmDocument:
        """Parse DDM listings uploaded together, applying the Natural views read beside them.

        Raises:
            ImportSourceError: With the reader's taxonomy code (see :mod:`app.natural_ddm_parser`).
        """
        try:
            return parse_ddm_fileset(fileset, label=source_label)
        except MainframeParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize the parsed document onto the data_schema paradigm.

        Raises:
            ImportSourceError: When ``native_ast`` is not a :class:`~app.natural_ddm_parser.DdmDocument`.
        """
        if not isinstance(native_ast, DdmDocument):
            raise ImportSourceError("Natural DDM source must be a DdmDocument (see app.natural_ddm_parser)")
        return self._normalize_via_registry(self.key, native_ast, include_raw=include_raw)
