"""Insomnia export import source — MFI-32.3 (#4405).

The :class:`~app.import_source.ImportSource` adapter for Insomnia exports: a v4 JSON export
(``Export → Insomnia v4``) or a v5 YAML export (Insomnia 10 and later), optionally uploaded as a
fileset beside the environment exports its variables come from. Read by :mod:`app.insomnia_parser`
and normalized by :mod:`app.insomnia_normalizer` through the shared inferred-spec engine — folders
become operation groups, requests operations (single-sample, bodies as declared), and environment
variables server variables and parameter defaults. Saved credentials are never read; every other
value passes the secret-scrub gate, which ``insomnia`` always enforces (MFI-29.6).
"""

from __future__ import annotations

from typing import Any, Optional

from . import insomnia_normalizer  # noqa: F401 — self-registers the normalizer
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
from .insomnia_parser import (
    FORMAT_KEY,
    InsomniaDocument,
    InsomniaParseError,
    detect_insomnia,
    parse_insomnia_fileset,
    parse_insomnia_text,
)

__all__ = ["InsomniaImportSource"]


def _as_import_error(exc: InsomniaParseError) -> ImportSourceError:
    """Carry the reader's taxonomy code onto the adapter error."""
    return ImportSourceError(str(exc), code=exc.code)


class InsomniaImportSource(ImportSource, register=True):
    """Adapter for Insomnia v4 (JSON) and v5 (YAML) exports and their environments."""

    key = FORMAT_KEY
    label = "Insomnia collection"
    description = (
        "Import an Insomnia export — v4 JSON or v5 YAML, optionally with its environment files: folders "
        "become operation groups, requests operations with inferred body schemas, and environment "
        "variables server variables and parameter defaults. Saved credentials are never kept."
    )
    icon = "send"
    paradigm = ApiParadigm.REST
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY,)
    file_extensions = (".json", ".yaml", ".yml")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a v4 export by ``_type: export`` + ``resources[]``, a v5 one by its ``type:`` marker.

        A v4 export written by Insomnia (``__export_format: 4``, ``__export_source: insomnia…``) and
        a v5 ``collection`` / ``spec`` document are claimed with confidence; an environment or mock
        document on its own only weakly, so the reader can say what it needs.
        """
        text = payload.text
        if text is None:
            return NO_MATCH
        found = detect_insomnia(text)
        if found is None:
            return NO_MATCH
        reason, confidence = found
        return DetectionResult(confidence=confidence, format=FORMAT_KEY, reason=reason)

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> InsomniaDocument:
        """Parse one export, carrying the reader's taxonomy code."""
        try:
            return parse_insomnia_text(raw, source_label=source_label)
        except InsomniaParseError as exc:
            raise _as_import_error(exc) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> InsomniaDocument:
        """Parse exports together with the environment files uploaded beside them.

        Raises:
            ImportSourceError: When a member cannot be read or no HTTP request is present.
        """
        try:
            return parse_insomnia_fileset(fileset.members, root=fileset.root, source_label=source_label)
        except InsomniaParseError as exc:
            raise _as_import_error(exc) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a parsed upload through the shared inferred-spec engine.

        Raises:
            ImportSourceError: When ``native_ast`` is not a parsed Insomnia document.
        """
        if not isinstance(native_ast, InsomniaDocument):
            raise ImportSourceError("Insomnia source must be an InsomniaDocument (see app.insomnia_parser)")
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)
