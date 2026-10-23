"""MQTT Sparkplug B import source — FMT-9.2 (#5469).

The :class:`~app.import_source.ImportSource` adapter for Sparkplug B, the payload and topic
standard of industrial MQTT:

* **a binary payload** (``.bin``) through the binary intake SPI
  (:meth:`SparkplugImportSource.accepts_bytes` / :meth:`~SparkplugImportSource.parse_bytes`),
  decoded by :mod:`app.sparkplug_payload` — or a **fileset** of them, so the DATA payloads that
  name their metrics only by alias are read beside the BIRTH that declared the names;
* **a topic-namespace description** (JSON): the group, the edge node, its topics and the metric
  catalogue of the node and of each device.

Both normalize to the **event** paradigm (:mod:`app.sparkplug_normalizer`): each topic a channel
whose address is the topic, its components (group, message type, edge node, device) recorded, and
the metrics the message schema. A payload alone does not say where it was published, so everything
a payload-only import produces is stamped ``inferred``. The native analysis
(:mod:`app.sparkplug_analysis`) describes every payload, metric value included under the
value-visibility policy.
"""

from __future__ import annotations

from typing import Any, Optional

from . import sparkplug_normalizer  # noqa: F401 — self-registers the normalizer
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
from .payload_analysis import AnalyzerCapabilities, PayloadAnalysisDocument
from .sparkplug_analysis import (
    SPARKPLUG_ANALYZER_KEY,
    SPARKPLUG_ANALYZER_VERSION,
    analyze_sparkplug,
    sparkplug_capabilities,
)
from .sparkplug_parser import (
    FORMAT_KEY,
    PAYLOAD_SUFFIXES,
    SparkplugDocument,
    SparkplugParseError,
    declares_namespace,
    has_namespace_marker,
    is_namespace_document,
    parse_sparkplug_bytes,
    parse_sparkplug_fileset,
    parse_sparkplug_text,
)
from .sparkplug_payload import sniff_payload

__all__ = ["SparkplugImportSource"]


def _as_import_error(exc: SparkplugParseError) -> ImportSourceError:
    """Carry the reader's taxonomy code (or its deliberate absence) onto the adapter error."""
    return ImportSourceError(str(exc), code=exc.code)


def _has_payload_suffix(filename: Optional[str]) -> bool:
    return (filename or "").strip().lower().endswith(PAYLOAD_SUFFIXES)


class SparkplugImportSource(ImportSource, register=True):
    """Adapter for MQTT Sparkplug B payloads and topic-namespace descriptions (file / url / paste / fileset)."""

    key = FORMAT_KEY
    label = "MQTT Sparkplug B"
    description = (
        "Import Sparkplug B payloads (NBIRTH, DBIRTH, DDATA …) or a topic-namespace description: "
        "topics become MQTT channels and metrics the message schema, with datatypes and aliases."
    )
    icon = "radio-tower"
    paradigm = ApiParadigm.EVENT
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY, "sparkplug-b")
    file_extensions = PAYLOAD_SUFFIXES + (".json",)
    analyzer_key = SPARKPLUG_ANALYZER_KEY
    analyzer_version = SPARKPLUG_ANALYZER_VERSION

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a payload by decoding it, or a namespace description by its ``spBv1.0`` namespace.

        The undecoded bytes are tried first: a payload has no text marker, and either decodes
        completely as Sparkplug B — top-level fields 1–5 only, at least one addressable metric —
        or it does not. A namespace description declares ``"namespace": "spBv1.0"``, which is
        claimed even when the rest of the document is broken, so the reader can say what is wrong
        with it. Text that only quotes an ``spBv1.0/`` topic is weaker evidence, and a ``.bin`` name
        alone is the weakest signal.
        """
        if sniff_payload(payload.data):
            return DetectionResult(
                confidence=0.9,
                format=FORMAT_KEY,
                reason="decodes as a Sparkplug B payload (timestamp, metrics, seq)",
            )
        document = payload.document
        if document is not None and is_namespace_document(document):
            return DetectionResult(
                confidence=0.95, format=FORMAT_KEY, reason='`"namespace": "spBv1.0"` topic-namespace description'
            )
        text = payload.text
        if declares_namespace(text):
            return DetectionResult(
                confidence=0.95, format=FORMAT_KEY, reason='`"namespace": "spBv1.0"` topic-namespace description'
            )
        if has_namespace_marker(text):
            # Quoting a Sparkplug topic is weaker evidence: an AsyncAPI document may too.
            return DetectionResult(confidence=0.6, format=FORMAT_KEY, reason="quotes a Sparkplug `spBv1.0/` topic")
        if payload.data is not None and _has_payload_suffix(payload.filename):
            return DetectionResult(confidence=0.5, format=FORMAT_KEY, reason="Sparkplug payload file extension")
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> SparkplugDocument:
        """Parse a topic-namespace description, carrying the reader's taxonomy code."""
        try:
            return parse_sparkplug_text(raw, label=source_label)
        except SparkplugParseError as exc:
            raise _as_import_error(exc) from exc

    def accepts_bytes(self, raw: bytes, *, filename: Optional[str] = None) -> bool:
        """Claim payload bytes for :meth:`parse_bytes`.

        Claims on a successful decode and — the IXH-7.5 suffix rule — on a ``.bin``
        filename *even when the bytes are broken*, so a truncated or malformed payload is reported
        by the payload reader rather than as a text-decoding fault. JSON is never claimed: a
        namespace description is text.
        """
        if _has_payload_suffix(filename):
            return True
        return sniff_payload(raw)

    def parse_bytes(self, raw: bytes, *, source_label: Optional[str] = None) -> SparkplugDocument:
        """Parse one binary payload."""
        try:
            return parse_sparkplug_bytes(raw, label=source_label)
        except SparkplugParseError as exc:
            raise _as_import_error(exc) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> SparkplugDocument:
        """Parse a set of payloads (a BIRTH and the DATA / DEATH payloads after it), root first.

        Raises:
            ImportSourceError: When a payload cannot be read.
        """
        try:
            return parse_sparkplug_fileset(fileset, label=source_label)
        except SparkplugParseError as exc:
            raise _as_import_error(exc) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a parsed Sparkplug input onto the event paradigm.

        Raises:
            ImportSourceError: When ``native_ast`` is not a parsed Sparkplug document.
        """
        if not isinstance(native_ast, SparkplugDocument):
            raise ImportSourceError("Sparkplug source must be a SparkplugDocument (see app.sparkplug_parser)")
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)

    def analysis_capabilities(self) -> AnalyzerCapabilities:
        """The Sparkplug extractor's capability declaration (CPDO-1.2)."""
        return sparkplug_capabilities()

    def analyze(self, native_ast: Any, *, source: Optional[str] = None) -> PayloadAnalysisDocument:
        """Describe the input natively — every payload and metric, or the namespace's topics.

        Raises:
            ImportSourceError: If ``native_ast`` is not a parsed Sparkplug document.
        """
        if not isinstance(native_ast, SparkplugDocument):
            raise ImportSourceError("Sparkplug analysis needs a SparkplugDocument (see app.sparkplug_parser)")
        return analyze_sparkplug(native_ast, source=source, source_format=self.key)
