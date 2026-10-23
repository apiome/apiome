"""Matter cluster and device-type import source — FMT-9.5 (#5472).

The :class:`~app.import_source.ImportSource` adapter for the Matter data-model XML (the
``configurator`` documents the ZAP tool and the Matter SDK ship): a cluster definition file, or a
device type uploaded beside the cluster definitions it includes as a fileset. Read by
:mod:`app.matter_parser` and normalized onto the **rpc** paradigm by :mod:`app.matter_normalizer`:
clusters become records of their attributes plus a service of their commands and events, and a
device type a record of the clusters it is composed of.

Crawling the public Matter registries is out of scope; it belongs to the registry-as-source seam
(#3978).
"""

from __future__ import annotations

from typing import Any, Optional

from . import matter_normalizer  # noqa: F401 — self-registers the normalizer
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
from .matter_parser import (
    FORMAT_KEY,
    MatterDocument,
    MatterParseError,
    is_matter_document,
    parse_matter_fileset,
    parse_matter_text,
)

__all__ = ["MatterImportSource"]

#: Markers of a cluster or device-type definition inside a ``configurator`` root.
_DEFINITION_MARKERS = ("<cluster>", "<cluster ", "<deviceType>", "<deviceType ")


def _as_import_error(exc: MatterParseError) -> ImportSourceError:
    """Carry the reader's taxonomy code onto the adapter error."""
    return ImportSourceError(str(exc), code=exc.code)


class MatterImportSource(ImportSource, register=True):
    """Adapter for Matter cluster and device-type definition XML."""

    key = FORMAT_KEY
    label = "Matter clusters and device types"
    description = (
        "Import Matter cluster and device-type definitions: clusters become types of their "
        "attributes with access, ranges and defaults, commands request/response operations, events "
        "subscribe operations, and a device type the set of clusters it is composed of."
    )
    icon = "lightbulb"
    paradigm = ApiParadigm.RPC
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY, "matter-zap")
    file_extensions = (".xml", ".zip", ".tar.gz", ".tgz")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a ``configurator`` root element, more confidently when it holds a cluster or device type.

        Only the head is examined, so a truncated or malformed definition is still claimed and the
        reader says what is wrong with it.
        """
        text = payload.text
        if text is None or not is_matter_document(text):
            return NO_MATCH
        if any(marker in text[:65536] for marker in _DEFINITION_MARKERS):
            return DetectionResult(
                confidence=0.97, format=FORMAT_KEY, reason="`<configurator>` root with a cluster or device type"
            )
        return DetectionResult(confidence=0.75, format=FORMAT_KEY, reason="`<configurator>` root element")

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> MatterDocument:
        """Parse one Matter definition file, carrying the reader's taxonomy code."""
        try:
            return parse_matter_text(raw, label=source_label)
        except MatterParseError as exc:
            raise _as_import_error(exc) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> MatterDocument:
        """Parse a device type beside its cluster definitions (or any set of definition files).

        Raises:
            ImportSourceError: When a member cannot be read or a reference cannot be resolved.
        """
        try:
            return parse_matter_fileset(fileset, label=source_label)
        except MatterParseError as exc:
            raise _as_import_error(exc) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize parsed Matter definitions onto the rpc paradigm.

        Raises:
            ImportSourceError: When ``native_ast`` is not a parsed Matter document.
        """
        if not isinstance(native_ast, MatterDocument):
            raise ImportSourceError("Matter source must be a MatterDocument (see app.matter_parser)")
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)
