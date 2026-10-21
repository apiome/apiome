"""ISO 20022 import source — MFI-22.5.

The :class:`~app.import_source.ImportSource` adapter that makes ISO 20022 XML messages
importable into the catalog (store-raw, MFI-23.7).

SEPA payment files (FMT-6.6) route here: a ``pain.001`` / ``pain.008`` / ``pacs.008`` message is
recognised by its namespace, its message id is named in the detection reason and recorded as the
SEPA ``format_profile`` (:mod:`app.iso20022_sepa`), and the two structural rules its message
definition carries are applied at parse time.
"""

from __future__ import annotations

from typing import Any, Optional

from . import iso20022_normalizer  # noqa: F401 — self-registers the normalizer
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
from .iso20022_parser import (
    Iso20022Document,
    Iso20022ParseError,
    declared_message_id,
    is_iso20022,
    parse_iso20022,
)
from .iso20022_sepa import check_sepa_document, sepa_message
from .secure_xml import SecureXmlError

__all__ = ["Iso20022ImportSource"]


def _detection_reason(text: str) -> str:
    """Name the namespace marker and, when it is legible, the message id (SEPA flagged)."""
    reason = "`urn:iso:std:iso:20022:tech:xsd:` namespace"
    message_id = declared_message_id(text)
    if message_id is None:
        return reason
    if sepa_message(message_id) is not None:
        return f"{reason} — {message_id} (SEPA payment message)"
    return f"{reason} — {message_id}"


class Iso20022ImportSource(ImportSource, register=True):
    """Adapter for ISO 20022 financial XML messages."""

    key = "iso20022"
    label = "ISO 20022"
    description = "Import an ISO 20022 financial XML message and infer its schema."
    icon = "landmark"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = ("iso20022",)
    file_extensions = (".xml",)

    def detect(self, payload: DetectionInput) -> DetectionResult:
        text = payload.text
        if text is not None and is_iso20022(text):
            return DetectionResult(
                confidence=0.98,
                format="iso20022",
                reason=_detection_reason(text),
            )

        filename = (payload.filename or "").lower()
        if filename.endswith(".xml") and text is not None and is_iso20022(text):
            return DetectionResult(
                confidence=0.85,
                format="iso20022",
                reason="ISO 20022 XML filename with namespace marker",
            )
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> Iso20022Document:
        """Parse the message, then apply the SEPA structural rules when it is a SEPA family."""
        try:
            document = parse_iso20022(raw, source_label=source_label)
            check_sepa_document(document)
            return document
        except (Iso20022ParseError, SecureXmlError) as exc:
            # SecureXmlError carries the taxonomy code for a rejected DTD /
            # entity / external reference or an exceeded size or depth limit.
            raise ImportSourceError(str(exc), code=getattr(exc, "code", None)) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> Iso20022Document:
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError("ISO 20022 fileset is missing its root document")
        return self.parse(fileset.members[root], source_label=root or source_label)

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(native_ast, Iso20022Document):
            raise ImportSourceError(
                "ISO 20022 source must be an Iso20022Document (see app.iso20022_parser.parse_iso20022)"
            )
        return self._normalize_via_registry("iso20022", native_ast, include_raw=include_raw)
