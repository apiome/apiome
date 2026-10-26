"""HAR capture import source — MFI-32.2 (#4404).

The :class:`~app.import_source.ImportSource` adapter for HAR (HTTP Archive) files: record a session
in a browser's devtools or a debugging proxy, save it as HAR, and import the traffic. Read by
:mod:`app.har_parser` and normalized by :mod:`app.har_normalizer` through the shared inferred-spec
engine — repeated calls cluster into parameterized operations (``/users/{id}``), and request and
response bodies become schemas widened across samples. Page assets, analytics beacons and CORS
preflights are left out; each host the page called becomes its own catalog item.

Import options (all optional, read by :meth:`HarImportSource.configure`):

* ``har_hosts`` — the host(s) to import; default is the host with the most API calls.
* ``har_include`` / ``har_exclude`` — ``host/path`` glob patterns to keep / drop.
* ``har_keep_noise`` — ``true`` turns the built-in noise filter off.

Credentials never reach the model: cookies are not read, ``Authorization`` keeps only its scheme,
and every other value passes the secret-scrub gate — which also redacts the stored source, since
``har`` is one of the formats that gate always enforces (MFI-29.6).
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from . import har_normalizer  # noqa: F401 — self-registers the normalizer
from .canonical_model import ApiParadigm, CanonicalApi
from .fileset import IntakeFileset
from .har_filters import HarOptions, HarOptionsError
from .har_parser import FORMAT_KEY, HarDocument, HarParseError, is_har, parse_har_fileset, parse_har_text
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
)

__all__ = ["HarImportSource"]

#: The HAR versions current tools write; any other ``log.version`` is still read, claimed less firmly.
_KNOWN_VERSIONS = frozenset({"1.1", "1.2"})


def _as_import_error(exc: HarParseError) -> ImportSourceError:
    """Carry the reader's taxonomy code onto the adapter error."""
    return ImportSourceError(str(exc), code=exc.code)


class HarImportSource(ImportSource, register=True):
    """Adapter for HAR captures from browser devtools and debugging proxies."""

    key = FORMAT_KEY
    label = "HAR (inferred)"
    description = (
        "Import a HAR capture saved from browser devtools or a debugging proxy: repeated calls become "
        "parameterized operations with request and response schemas inferred from the traffic. Page "
        "assets and analytics are left out, each host becomes its own catalog item, and cookies and "
        "credentials are never kept."
    )
    icon = "activity"
    paradigm = ApiParadigm.REST
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY,)
    file_extensions = (".har",)

    def __init__(self, *, options: Optional[HarOptions] = None) -> None:
        """Build the adapter, optionally with this import's HAR options.

        Args:
            options: The options every parse reads under. Set by :meth:`configure` from the
                import's options rather than constructed directly.
        """
        self._options = options or HarOptions()

    def configure(self, options: Mapping[str, Any]) -> "HarImportSource":
        """Return an adapter honouring this import's ``har_*`` options.

        Args:
            options: The import's options mapping (keys this adapter does not own are ignored).

        Returns:
            ``self`` when no HAR option was given, otherwise a configured copy — the registry's
            instance stays stateless, so two concurrent imports cannot read each other's options.

        Raises:
            ImportSourceError: ``INPUT_SEMANTIC_INVALID`` when a HAR option has the wrong shape.
        """
        try:
            parsed = HarOptions.from_mapping(options)
        except HarOptionsError as exc:
            raise ImportSourceError(str(exc), code="INPUT_SEMANTIC_INVALID") from exc
        return self if parsed.is_default else HarImportSource(options=parsed)

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a JSON object whose ``log`` holds an ``entries`` list.

        ``{"log": {"version": "1.2", …, "entries": […]}}`` (or ``1.1``) is claimed with confidence;
        a ``log.entries`` capture with another or no version, a little less.
        """
        text = payload.text
        if text is None or not text.lstrip().startswith("{"):
            return NO_MATCH
        try:
            document = json.loads(text)
        except ValueError:
            return NO_MATCH
        if not is_har(document):
            return NO_MATCH
        version = str(document["log"].get("version") or "").strip()
        if version in _KNOWN_VERSIONS:
            return DetectionResult(confidence=0.97, format=FORMAT_KEY, reason=f"HAR {version} capture (log.entries)")
        return DetectionResult(confidence=0.85, format=FORMAT_KEY, reason="HAR-shaped capture (log.entries)")

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> HarDocument:
        """Parse one capture, carrying the reader's taxonomy code."""
        try:
            return parse_har_text(raw, source_label=source_label, options=self._options)
        except HarParseError as exc:
            raise _as_import_error(exc) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> HarDocument:
        """Parse several captures together (one recording session each).

        Raises:
            ImportSourceError: When a capture cannot be read or none of the members is a capture.
        """
        try:
            return parse_har_fileset(
                fileset.members, root=fileset.root, source_label=source_label, options=self._options
            )
        except HarParseError as exc:
            raise _as_import_error(exc) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a parsed capture through the shared inferred-spec engine.

        Raises:
            ImportSourceError: When ``native_ast`` is not a parsed HAR document.
        """
        if not isinstance(native_ast, HarDocument):
            raise ImportSourceError("HAR source must be a HarDocument (see app.har_parser)")
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)
