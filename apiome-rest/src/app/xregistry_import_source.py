"""CNCF xRegistry import source — MFI-19.2 (#3980).

The :class:`~app.import_source.ImportSource` adapter for xRegistry documents — the CloudEvents
project's catalog of schemas, message definitions and endpoints (see :mod:`app.xregistry_parser`).
It sits beside the CloudEvents envelope adapter (:mod:`app.cloudevents_import_source`), which reads
single events; this one reads the registry that describes them.

* **detect** — a JSON object with ``schemagroups``, ``messagegroups`` (or ``definitiongroups``) or
  ``endpoints``; see :func:`app.xregistry_parser.is_xregistry_document`.
* **parse** — :func:`app.xregistry_parser.parse_xregistry` (JSON only).
* **normalize** — :mod:`app.xregistry_normalizer`: schemas → types, messages → channels and
  operations, endpoints → services.
* **fingerprint / diff / lint** — the SPI defaults over the event-paradigm model: a message added
  or removed is an ``operation`` entry, a schema change a ``type`` entry, an endpoint change a
  ``service`` entry.
* **live** — a registry is crawled by the ``xregistry`` registry crawl (MFI-18.5,
  :mod:`app.xregistry_crawl`, declared on the ``cloudevents`` adapter): each schema imports with
  the adapter its format names, and each message group and endpoint imports through this adapter.
"""

from __future__ import annotations

from typing import Any, Optional

from . import xregistry_normalizer  # noqa: F401 — self-registers the normalizer
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
from .xregistry_normalizer import FORMAT_KEY
from .xregistry_parser import (
    XRegistryDocument,
    XRegistryParseError,
    is_xregistry,
    is_xregistry_document,
    parse_xregistry,
)

__all__ = ["XRegistryImportSource"]

_SHAPE_REASON = "xRegistry `schemagroups` / `messagegroups` / `endpoints` collections"


class XRegistryImportSource(ImportSource, register=True):
    """Adapter for CNCF xRegistry documents (file / url / paste / fileset)."""

    key = FORMAT_KEY
    label = "CNCF xRegistry"
    description = (
        "Import a CNCF xRegistry document — CloudEvents schema groups, message definitions and "
        "endpoints over MQTT, AMQP, Kafka, NATS or HTTP — as one event catalog entry."
    )
    icon = "cloud"
    paradigm = ApiParadigm.EVENT
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY, "cloudevents-registry")
    file_extensions = (".xreg.json", ".xregistry.json", ".json")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Sniff a document for the xRegistry collections.

        Args:
            payload: The detection input (text and/or parsed document, plus hints).

        Returns:
            A high-confidence match on the shape, a weaker one on an ``.xreg.json`` filename, else
            :data:`~app.import_source.NO_MATCH`.
        """
        document = payload.document
        if document is not None and is_xregistry_document(document):
            return DetectionResult(confidence=0.95, format=FORMAT_KEY, reason=_SHAPE_REASON)
        text = payload.text
        if text is not None and is_xregistry(text):
            return DetectionResult(confidence=0.95, format=FORMAT_KEY, reason=_SHAPE_REASON)
        filename = (payload.filename or "").lower()
        if filename.endswith(".xreg.json") or filename.endswith(".xregistry.json"):
            return DetectionResult(
                confidence=0.6, format=FORMAT_KEY, reason="`.xreg.json` file extension"
            )
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> XRegistryDocument:
        """Parse xRegistry document text.

        Args:
            raw: The document text.
            source_label: Optional filename / URL for messages.

        Returns:
            The parsed :class:`~app.xregistry_parser.XRegistryDocument`.

        Raises:
            ImportSourceError: Carrying the parser's intake-taxonomy code.
        """
        try:
            return parse_xregistry(raw, source_label=source_label)
        except XRegistryParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> XRegistryDocument:
        """Parse the document at the root of a fileset (siblings are ignored).

        Args:
            fileset: The unpacked set; ``root`` names the registry document.
            source_label: Optional label for messages.

        Returns:
            The parsed document.

        Raises:
            ImportSourceError: When the root member is missing or cannot be parsed.
        """
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError(
                "xRegistry fileset is missing its root document", code="INPUT_MALFORMED"
            )
        return self.parse(fileset.members[root], source_label=root or source_label)

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a parsed document onto the canonical event-paradigm model.

        Args:
            native_ast: The parsed document.
            include_raw: Whether to preserve the document in ``raw``.

        Returns:
            The canonical model.

        Raises:
            ImportSourceError: When ``native_ast`` is not a parsed xRegistry document.
        """
        if not isinstance(native_ast, XRegistryDocument):
            raise ImportSourceError(
                "xRegistry source must be an XRegistryDocument "
                "(see app.xregistry_parser.parse_xregistry)"
            )
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)
