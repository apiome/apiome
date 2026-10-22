"""OPC UA NodeSet2 import source — FMT-9.1 (#5468).

The :class:`~app.import_source.ImportSource` adapter for OPC UA NodeSet2 XML — the information
model of industrial automation: object, variable, data and reference types, methods, and the
address space a factory's machines expose.

* **detect** — a ``UANodeSet`` root element; see :func:`app.opcua_nodeset_parser.is_nodeset`.
* **parse** — :func:`app.opcua_nodeset_parser.parse_nodeset` (hardened XML intake); a fileset —
  a model plus the companion models it requires — is merged by
  :func:`~app.opcua_nodeset_parser.parse_nodeset_fileset`, so a ``RequiredModel`` shipped beside
  the model resolves.
* **normalize** — :mod:`app.opcua_nodeset_normalizer`: types → canonical types, methods → RPC
  operations, references kept on each type, namespaces and model versions in provenance.
* **analyze** — :mod:`app.opcua_nodeset_analysis`: the whole nodeset, address-space instances and
  reference graph included, bounded by the analyzer's node budget.
"""

from __future__ import annotations

from typing import Any, Optional

from . import opcua_nodeset_normalizer  # noqa: F401 — self-registers the normalizer
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
from .opcua_nodeset_analysis import (
    OPCUA_ANALYZER_KEY,
    OPCUA_ANALYZER_VERSION,
    analyze_nodeset,
    opcua_capabilities,
)
from .opcua_nodeset_parser import (
    FORMAT_KEY,
    NodeSetDocument,
    NodeSetParseError,
    declares_nodeset_namespace,
    is_nodeset,
    parse_nodeset,
    parse_nodeset_fileset,
)
from .payload_analysis import AnalyzerCapabilities, PayloadAnalysisDocument

__all__ = ["OpcUaNodeSetImportSource"]


class OpcUaNodeSetImportSource(ImportSource, register=True):
    """Adapter for OPC UA NodeSet2 XML (file / url / paste / fileset)."""

    key = FORMAT_KEY
    label = "OPC UA NodeSet2"
    description = (
        "Import an OPC UA NodeSet2 information model — object, variable and data types, methods "
        "and the reference graph — with its namespaces and model versions."
    )
    icon = "factory"
    paradigm = ApiParadigm.RPC
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY, "nodeset2", "opcua")
    file_extensions = (".xml",)
    analyzer_key = OPCUA_ANALYZER_KEY
    analyzer_version = OPCUA_ANALYZER_VERSION

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a ``UANodeSet`` root, more confidently when it names the NodeSet2 namespace.

        Only the opening is examined, so a truncated or malformed nodeset is still claimed and the
        parser says what is wrong with it.

        Args:
            payload: The detection input.

        Returns:
            A match on the root element, else :data:`~app.import_source.NO_MATCH`.
        """
        if payload.text is None or not is_nodeset(payload.text):
            return NO_MATCH
        if declares_nodeset_namespace(payload.text):
            return DetectionResult(
                confidence=0.97,
                format=FORMAT_KEY,
                reason="`<UANodeSet>` root in the OPC UA NodeSet2 namespace",
            )
        return DetectionResult(confidence=0.85, format=FORMAT_KEY, reason="`<UANodeSet>` root element")

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> NodeSetDocument:
        """Parse one NodeSet2 document, carrying the parser's taxonomy code.

        Raises:
            ImportSourceError: When the document is not a readable nodeset.
        """
        try:
            return parse_nodeset(raw, source_label=source_label)
        except NodeSetParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> NodeSetDocument:
        """Parse a fileset from its root nodeset, merging every other NodeSet2 member into it.

        Raises:
            ImportSourceError: When the root is missing, a member is unreadable, or a reference
                cannot be satisfied by the merged set.
        """
        try:
            return parse_nodeset_fileset(fileset.members, fileset.root, source_label=source_label)
        except NodeSetParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a parsed nodeset onto the canonical model.

        Raises:
            ImportSourceError: When ``native_ast`` is not a parsed nodeset.
        """
        if not isinstance(native_ast, NodeSetDocument):
            raise ImportSourceError(
                "OPC UA source must be a NodeSetDocument (see app.opcua_nodeset_parser.parse_nodeset)"
            )
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)

    def analysis_capabilities(self) -> AnalyzerCapabilities:
        """What the analyzer models for any nodeset."""
        return opcua_capabilities()

    def analyze(self, native_ast: Any, *, source: Optional[str] = None) -> PayloadAnalysisDocument:
        """Describe the parsed nodeset — instances and references included — as a payload analysis.

        Args:
            native_ast: The parsed nodeset.
            source: The exact text analysed.

        Returns:
            The analysis document.
        """
        return analyze_nodeset(native_ast, source=source, source_format=self.key)
