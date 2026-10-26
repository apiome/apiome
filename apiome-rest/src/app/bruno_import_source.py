"""Bruno collection import source — MFI-32.4 (#4406).

The :class:`~app.import_source.ImportSource` adapter for Bruno, the git-native API client. A
collection is a folder — ``bruno.json``, one ``.bru`` file per request, ``collection.bru`` /
``folder.bru`` settings and ``environments/*.bru`` — so it normally arrives as a fileset: an archive
upload (MFI-29.1) or a git selection (MFI-29.3). Both yield the same model and fingerprint, because
the reader keys everything relative to ``bruno.json``. A single ``.bru`` request can also be uploaded
or pasted. Read by :mod:`app.bruno_parser` (grammar in :mod:`app.bru_lang`) and normalized by
:mod:`app.bruno_normalizer` through the shared inferred-spec engine. Saved credentials are never
read; every other value passes the secret-scrub gate, which ``bruno`` always enforces (MFI-29.6).
"""

from __future__ import annotations

from typing import Any, Optional

from . import bruno_normalizer  # noqa: F401 — self-registers the normalizer
from .bruno_parser import (
    FORMAT_KEY,
    BrunoDocument,
    BrunoParseError,
    detect_bruno,
    parse_bruno_fileset,
    parse_bruno_text,
)
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

__all__ = ["BrunoImportSource"]


def _as_import_error(exc: BrunoParseError) -> ImportSourceError:
    """Carry the reader's taxonomy code onto the adapter error."""
    return ImportSourceError(str(exc), code=exc.code)


class BrunoImportSource(ImportSource, register=True):
    """Adapter for Bruno collection folders (and single ``.bru`` requests)."""

    key = FORMAT_KEY
    label = "Bruno collection"
    description = (
        "Import a Bruno collection folder — bruno.json, its .bru requests, folder settings and environments — "
        "as an archive or from git: folders become operation groups, requests operations with inferred body "
        "schemas, and environment variables server variables and parameter defaults. Saved credentials are "
        "never kept."
    )
    icon = "send"
    paradigm = ApiParadigm.REST
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY,)
    file_extensions = (".bru", ".json")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim ``bruno.json`` and request ``.bru`` files firmly; other ``.bru`` files weakly.

        ``bruno.json`` (``"type": "collection"`` with a ``version``) is what an archive or git
        selection resolves as its root. A ``collection.bru``, ``folder.bru`` or environment file is
        claimed only weakly, so the reader can say it needs the collection around it.
        """
        if payload.text is None and payload.data is not None:
            data = payload.data
            if data[:2] == b"PK" and b"bruno.json" in data:
                return DetectionResult(confidence=0.97, format=FORMAT_KEY, reason="zip with a `bruno.json` member")
            return NO_MATCH
        text = payload.text
        if text is None:
            return NO_MATCH
        found = detect_bruno(text)
        if found is None:
            return NO_MATCH
        reason, confidence = found
        return DetectionResult(confidence=confidence, format=FORMAT_KEY, reason=reason)

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> BrunoDocument:
        """Parse a single uploaded ``.bru`` request, carrying the reader's taxonomy code."""
        try:
            return parse_bruno_text(raw, source_label=source_label)
        except BrunoParseError as exc:
            raise _as_import_error(exc) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> BrunoDocument:
        """Parse a collection folder from an archive or a git selection.

        Raises:
            ImportSourceError: When a member cannot be read, ``bruno.json`` is missing, or no HTTP
                request is present.
        """
        try:
            return parse_bruno_fileset(fileset.members, root=fileset.root, source_label=source_label)
        except BrunoParseError as exc:
            raise _as_import_error(exc) from exc

    def parse_bytes(self, raw: bytes, *, source_label: Optional[str] = None) -> BrunoDocument:
        """Parse a zipped collection folder handed over as bytes.

        The bytes are unpacked by the archive-intake sandbox (size, entry count, depth, path
        safety, dotfiles such as ``.env`` skipped) and read exactly like an archive upload, so the
        result — and its fingerprint — matches the fileset path.

        Raises:
            ImportSourceError: ``INPUT_ARCHIVE_INVALID`` (or a size code) for an unsafe or
                unreadable archive, plus everything :meth:`parse_fileset` raises.
        """
        from .archive_intake import ArchiveIntakeError, unpack_archive_members

        try:
            members = unpack_archive_members(raw, source_label=source_label)
        except ArchiveIntakeError as exc:
            raise ImportSourceError(str(exc), code=getattr(exc, "code", None) or "INPUT_ARCHIVE_INVALID") from exc
        try:
            return parse_bruno_fileset(members, source_label=source_label)
        except BrunoParseError as exc:
            raise _as_import_error(exc) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a parsed collection through the shared inferred-spec engine.

        Raises:
            ImportSourceError: When ``native_ast`` is not a parsed Bruno document.
        """
        if not isinstance(native_ast, BrunoDocument):
            raise ImportSourceError("Bruno source must be a BrunoDocument (see app.bruno_parser)")
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)
