"""SoapUI / ReadyAPI project import source — FMT-10.3 (#5477).

The :class:`~app.import_source.ImportSource` adapter for SoapUI and ReadyAPI project XML, the file
a SOAP estate keeps its request corpus and test suites in. Read by :mod:`app.soapui_parser` and
normalized by :mod:`app.soapui_normalizer`: WSDL-backed interfaces delegate to the WSDL adapter,
REST interfaces go through the shared inferred-spec engine, and test suites are recorded as
declared test intent. A project whose WSDL interface names a local file is uploaded as a fileset
with that WSDL beside it (the project's own ``definitionCache`` copy is used when it has one).
Saved credentials are never read.
"""

from __future__ import annotations

from typing import Any, Optional

from . import soapui_normalizer  # noqa: F401 — self-registers the normalizer
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
from .soapui_parser import (
    FORMAT_KEY,
    SoapUiDocument,
    SoapUiParseError,
    is_soapui_project,
    parse_soapui_fileset,
    parse_soapui_text,
)

__all__ = ["SoapUiImportSource"]


def _as_import_error(exc: SoapUiParseError) -> ImportSourceError:
    """Carry the reader's taxonomy code onto the adapter error."""
    return ImportSourceError(str(exc), code=exc.code)


class SoapUiImportSource(ImportSource, register=True):
    """Adapter for SoapUI / ReadyAPI project XML, optionally with the WSDLs it names."""

    key = FORMAT_KEY
    label = "SoapUI / ReadyAPI project"
    description = (
        "Import a SoapUI or ReadyAPI project: WSDL interfaces are read by the WSDL adapter, REST "
        "interfaces become operations with inferred schemas, and test suites are kept as declared "
        "test intent. Saved credentials are never kept."
    )
    icon = "flask-conical"
    paradigm = ApiParadigm.REST
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY, "readyapi", "soapui-project")
    file_extensions = (".xml", ".zip", ".tar.gz", ".tgz")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a ``soapui-project`` root in the SoapUI config namespace.

        Only the head of the text is read, so a truncated or malformed project is still claimed
        (and then refused with the right code by :meth:`parse`).
        """
        if is_soapui_project(payload.text):
            return DetectionResult(
                confidence=0.97,
                format=FORMAT_KEY,
                reason="`<con:soapui-project>` root in the eviware SoapUI config namespace",
            )
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> SoapUiDocument:
        """Parse one project, carrying the reader's taxonomy code."""
        try:
            return parse_soapui_text(raw, source_label=source_label)
        except SoapUiParseError as exc:
            raise _as_import_error(exc) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> SoapUiDocument:
        """Parse a project together with the WSDL and XSD files uploaded beside it.

        Raises:
            ImportSourceError: When the project cannot be read or a WSDL it names is missing.
        """
        try:
            return parse_soapui_fileset(fileset.members, root=fileset.root, source_label=source_label)
        except SoapUiParseError as exc:
            raise _as_import_error(exc) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a parsed project.

        Raises:
            ImportSourceError: When ``native_ast`` is not a parsed SoapUI project.
        """
        if not isinstance(native_ast, SoapUiDocument):
            raise ImportSourceError("SoapUI source must be a SoapUiDocument (see app.soapui_parser)")
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)
