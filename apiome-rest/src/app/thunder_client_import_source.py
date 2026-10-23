"""Thunder Client collection import source — FMT-10.2 (#5475).

The :class:`~app.import_source.ImportSource` adapter for Thunder Client, the API client built into
VS Code: a collection export (``thunder-collection_*.json``), optionally uploaded as a fileset beside
the environment exports (``thunder-environment_*.json``) its ``{{variables}}`` come from. Read by
:mod:`app.thunder_client_parser` and normalized by :mod:`app.thunder_client_normalizer` through the
shared inferred-spec engine — folders become operation groups, requests operations, request bodies
inferred schemas, and environment variables server variables. Saved credentials are never read;
every other value passes the secret-scrub gate before it reaches the model.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from . import thunder_client_normalizer  # noqa: F401 — self-registers the normalizer
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
from .thunder_client_parser import (
    FORMAT_KEY,
    ThunderDocument,
    ThunderParseError,
    is_thunder_collection,
    is_thunder_environment,
    parse_thunder_fileset,
    parse_thunder_text,
)

__all__ = ["ThunderClientImportSource"]

#: The marker every Thunder Client export carries.
_CLIENT_MARKER = "Thunder Client"


def _as_import_error(exc: ThunderParseError) -> ImportSourceError:
    """Carry the reader's taxonomy code onto the adapter error."""
    return ImportSourceError(str(exc), code=exc.code)


class ThunderClientImportSource(ImportSource, register=True):
    """Adapter for Thunder Client collection exports and their environments."""

    key = FORMAT_KEY
    label = "Thunder Client collection"
    description = (
        "Import a Thunder Client collection export, optionally with its environment files: folders "
        "become operation groups, requests operations with inferred body schemas, and environment "
        "variables server variables. Saved credentials are never kept."
    )
    icon = "send"
    paradigm = ApiParadigm.REST
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY, "thunder-collection")
    file_extensions = (".json", ".zip", ".tar.gz", ".tgz")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a collection by its ``clientName`` and shape; an environment alone only weakly.

        ``"clientName": "Thunder Client"`` with ``collectionName`` and ``requests[]`` is claimed with
        confidence; an older export without the client name, by its ``colId`` / ``containerId``
        request links, a little less. An environment on its own is claimed weakly, so the reader can
        say it needs its collection.
        """
        text = payload.text
        if text is None or not text.lstrip().startswith("{"):
            return NO_MATCH
        try:
            document = json.loads(text)
        except ValueError:
            return NO_MATCH
        if is_thunder_collection(document):
            if _CLIENT_MARKER in str(document.get("clientName") or ""):
                return DetectionResult(
                    confidence=0.97, format=FORMAT_KEY, reason="Thunder Client collection (clientName, requests[])"
                )
            return DetectionResult(confidence=0.88, format=FORMAT_KEY, reason="Thunder Client collection shape")
        if is_thunder_environment(document):
            return DetectionResult(confidence=0.5, format=FORMAT_KEY, reason="Thunder Client environment variables")
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> ThunderDocument:
        """Parse one collection export, carrying the reader's taxonomy code."""
        try:
            return parse_thunder_text(raw, source_label=source_label)
        except ThunderParseError as exc:
            raise _as_import_error(exc) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> ThunderDocument:
        """Parse collections together with the environments uploaded beside them.

        Raises:
            ImportSourceError: When a member cannot be read or no collection is present.
        """
        try:
            return parse_thunder_fileset(fileset.members, root=fileset.root, source_label=source_label)
        except ThunderParseError as exc:
            raise _as_import_error(exc) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a parsed upload through the shared inferred-spec engine.

        Raises:
            ImportSourceError: When ``native_ast`` is not a parsed Thunder Client document.
        """
        if not isinstance(native_ast, ThunderDocument):
            raise ImportSourceError("Thunder Client source must be a ThunderDocument (see app.thunder_client_parser)")
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)
