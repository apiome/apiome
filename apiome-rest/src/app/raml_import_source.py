"""RAML import source — MFI-16.6, MFI-15.1.

The :class:`~app.import_source.ImportSource` adapter that makes RAML REST API
definitions importable into the catalog (store-raw, MFI-23.7). Parsing goes through AMF
when the toolchain has it, so ``!include`` fragments and ``uses`` libraries resolve
(MFI-15.1, :mod:`app.raml_amf`); otherwise the YAML reader handles self-contained documents.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from . import raml_normalizer  # noqa: F401 — self-registers the normalizer
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
from .raml_amf import amf_available, parse_raml_set_with_amf, references_other_files
from .raml_parser import RamlDocument, RamlParseError, is_raml, parse_raml

__all__ = ["RamlImportSource"]

_RAMl_HEADER_RE = re.compile(r"^\s*#%RAML\s+(\d+\.\d+)", re.IGNORECASE)

#: Member path a single pasted / uploaded document is staged under for AMF.
_SINGLE_DOCUMENT_PATH = "api.raml"


def _parse_members(members: Mapping[str, str], root: str, *, source_label: Optional[str]) -> RamlDocument:
    """Parse a RAML set, through AMF when the toolchain has it (MFI-15.1, #3799).

    AMF resolves ``!include`` fragments and ``uses`` libraries into one model. Without AMF,
    a document that references no other file still imports through the YAML reader; one
    that includes or uses another file is refused (``ADAPTER_UNAVAILABLE``) rather than
    imported with only its root.

    Args:
        members: The set's members, path → text.
        root: The root document's path.
        source_label: Label used in error messages.

    Returns:
        The parsed document.

    Raises:
        ImportSourceError: On any parse, resolution or availability failure.
    """
    if amf_available():
        return parse_raml_set_with_amf(members, root, source_label=source_label)
    if references_other_files(members):
        raise ImportSourceError(
            "This RAML document includes or uses other files (`!include` / `uses`), which "
            "needs the bundled AMF toolchain to resolve, and AMF is not available on this "
            "server (see docs/toolchain_packaging.md).",
            code="ADAPTER_UNAVAILABLE",
        )
    try:
        return parse_raml(members[root], source_label=source_label)
    except RamlParseError as exc:
        raise ImportSourceError(str(exc)) from exc


class RamlImportSource(ImportSource, register=True):
    """Adapter for RAML REST API definitions (``.raml`` file / url / paste)."""

    key = "raml"
    label = "RAML"
    description = "Import a RAML 1.0 REST API definition with types and resources."
    icon = "book-marked"
    paradigm = ApiParadigm.REST
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = ("raml",)
    file_extensions = (".raml",)

    def detect(self, payload: DetectionInput) -> DetectionResult:
        text = payload.text
        if text is not None and is_raml(text):
            match = _RAMl_HEADER_RE.match(text.strip())
            if match:
                reason = f"`#%RAML {match.group(1)}` header"
            else:
                reason = "RAML root keys (`title` + `baseUri`/`types`)"
            return DetectionResult(confidence=0.99 if match else 0.85, format="raml", reason=reason)

        filename = (payload.filename or "").lower()
        if filename.endswith(".raml"):
            return DetectionResult(confidence=0.75, format="raml", reason="`.raml` file extension")
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> RamlDocument:
        """Parse one RAML document (a one-file set; see :meth:`parse_fileset`)."""
        return _parse_members({_SINGLE_DOCUMENT_PATH: raw}, _SINGLE_DOCUMENT_PATH, source_label=source_label)

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> RamlDocument:
        """Parse a RAML set: the root document plus the files it includes and uses (MFI-15.1)."""
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError("RAML fileset is missing its root document")
        return _parse_members(dict(fileset.members), root, source_label=root or source_label)

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(native_ast, RamlDocument):
            raise ImportSourceError(
                "RAML source must be a RamlDocument (see app.raml_parser.parse_raml)"
            )
        return self._normalize_via_registry("raml", native_ast, include_raw=include_raw)
