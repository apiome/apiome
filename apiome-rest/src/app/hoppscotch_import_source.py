"""Hoppscotch collection import source — FMT-10.1 (#5473).

The :class:`~app.import_source.ImportSource` adapter for Hoppscotch, the open-source API client:
a collection export (or an export of several collections), optionally uploaded as a fileset beside
the environment exports its ``<<variables>>`` come from. Read by :mod:`app.hoppscotch_parser` and
normalized by :mod:`app.hoppscotch_normalizer` through the shared inferred-spec engine — folders
become operation groups, requests operations, request bodies inferred schemas, and environment
variables server variables. Saved credentials are never read; every other value passes the
secret-scrub gate before it reaches the model.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from . import hoppscotch_normalizer  # noqa: F401 — self-registers the normalizer
from .canonical_model import ApiParadigm, CanonicalApi
from .fileset import IntakeFileset
from .hoppscotch_parser import (
    FORMAT_KEY,
    HoppscotchDocument,
    HoppscotchParseError,
    is_hoppscotch_collection,
    is_hoppscotch_environment,
    parse_hoppscotch_fileset,
    parse_hoppscotch_text,
)
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
)

__all__ = ["HoppscotchImportSource"]

#: Variables written ``<<name>>`` — the quickest tell of a Hoppscotch collection.
_VARIABLE_MARKER = "<<"


def _as_import_error(exc: HoppscotchParseError) -> ImportSourceError:
    """Carry the reader's taxonomy code onto the adapter error."""
    return ImportSourceError(str(exc), code=exc.code)


class HoppscotchImportSource(ImportSource, register=True):
    """Adapter for Hoppscotch collection exports and their environments."""

    key = FORMAT_KEY
    label = "Hoppscotch collection"
    description = (
        "Import a Hoppscotch collection export, optionally with its environment files: folders "
        "become operation groups, requests operations with inferred body schemas, and environment "
        "variables server variables. Saved credentials are never kept."
    )
    icon = "send"
    paradigm = ApiParadigm.REST
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY, "hoppscotch-collection")
    file_extensions = (".json", ".zip", ".tar.gz", ".tgz")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a collection by its tree shape; an environment alone only weakly.

        A collection is ``{name, folders[], requests[]}`` — a shape no other supported format
        shares — so it is claimed with confidence, more so with a schema ``v`` or ``<<variables>>``.
        An environment on its own is claimed weakly, so the reader can say it needs its collection.
        """
        text = payload.text
        if text is None or not text.lstrip().startswith(("{", "[")):
            return NO_MATCH
        try:
            document = json.loads(text)
        except ValueError:
            return NO_MATCH
        if is_hoppscotch_collection(document):
            first = document[0] if isinstance(document, list) else document
            if "v" in first or _VARIABLE_MARKER in text:
                return DetectionResult(
                    confidence=0.96, format=FORMAT_KEY, reason="Hoppscotch collection (name, folders[], requests[], v)"
                )
            return DetectionResult(confidence=0.9, format=FORMAT_KEY, reason="Hoppscotch collection tree shape")
        if is_hoppscotch_environment(document) and _VARIABLE_MARKER not in text:
            return DetectionResult(confidence=0.5, format=FORMAT_KEY, reason="Hoppscotch environment variables")
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> HoppscotchDocument:
        """Parse one collection export, carrying the reader's taxonomy code."""
        try:
            return parse_hoppscotch_text(raw, source_label=source_label)
        except HoppscotchParseError as exc:
            raise _as_import_error(exc) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> HoppscotchDocument:
        """Parse collections together with the environments uploaded beside them.

        Raises:
            ImportSourceError: When a member cannot be read or no collection is present.
        """
        try:
            return parse_hoppscotch_fileset(fileset.members, root=fileset.root, source_label=source_label)
        except HoppscotchParseError as exc:
            raise _as_import_error(exc) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a parsed upload through the shared inferred-spec engine.

        Raises:
            ImportSourceError: When ``native_ast`` is not a parsed Hoppscotch document.
        """
        if not isinstance(native_ast, HoppscotchDocument):
            raise ImportSourceError("Hoppscotch source must be a HoppscotchDocument (see app.hoppscotch_parser)")
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)
