"""FIX Orchestra import source — FMT-6.9 (#5453).

The :class:`~app.import_source.ImportSource` adapter for FIX Orchestra repositories — the XML
**specification** of a FIX interface (message definitions, field types, code sets, components,
groups, actors, flows and state machines). It sits beside the ``fix`` adapter
(:mod:`app.fix_import_source`), which infers a schema from ``tag=value`` messages; this one reads
the contract those messages follow.

* **detect** — a ``repository`` root in the Orchestra namespace; see
  :func:`app.fix_orchestra_parser.is_orchestra`.
* **parse** — :func:`app.fix_orchestra_parser.parse_orchestra`; a fileset resolves the root's
  ``xi:include`` directives against its own members (:func:`parse_orchestra_fileset`).
* **normalize** — :mod:`app.fix_orchestra_normalizer`: messages → record types, code sets → enums,
  groups → lists of records, ``presence`` → optionality and constraints.
* **link** — the model records the ``msgType`` of every message (``extras.fix_msg_types``); the
  import stores it as ``format_metadata.fixMsgTypes``, the same key a ``fix`` message item carries,
  and the cross-format identity suggestions rank a shared message type
  (:func:`app.api_identity_service.rank_identity_suggestions`).
"""

from __future__ import annotations

from typing import Any, Optional

from . import fix_orchestra_normalizer  # noqa: F401 — self-registers the normalizer
from .canonical_model import ApiParadigm, CanonicalApi
from .fileset import IntakeFileset
from .fix_orchestra_normalizer import FORMAT_KEY
from .fix_orchestra_parser import (
    OrchestraParseError,
    OrchestraRepository,
    is_orchestra,
    parse_orchestra,
    parse_orchestra_fileset,
)
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
)

__all__ = ["FixOrchestraImportSource"]


class FixOrchestraImportSource(ImportSource, register=True):
    """Adapter for FIX Orchestra repository XML (file / url / paste / fileset)."""

    key = FORMAT_KEY
    label = "FIX Orchestra"
    description = (
        "Import a FIX Orchestra repository — message definitions, code sets, components, groups "
        "and presence rules — as the declared FIX schema."
    )
    icon = "trending-up"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY, "orchestra", "fixr")
    file_extensions = (".xml",)

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a ``repository`` root in the Orchestra namespace.

        Only the opening is examined, so a truncated or malformed repository is still claimed and
        the parser says what is wrong with it.

        Args:
            payload: The detection input.

        Returns:
            A high-confidence match on the root element, else :data:`~app.import_source.NO_MATCH`.
        """
        if payload.text is not None and is_orchestra(payload.text):
            return DetectionResult(
                confidence=0.96,
                format=FORMAT_KEY,
                reason="`<fixr:repository>` root in the FIX Orchestra namespace",
            )
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> OrchestraRepository:
        """Parse one repository document, carrying the parser's taxonomy code.

        Raises:
            ImportSourceError: When the document is not a readable Orchestra repository.
        """
        try:
            return parse_orchestra(raw, source_label=source_label)
        except OrchestraParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> OrchestraRepository:
        """Parse a fileset from its root repository, resolving ``xi:include`` against its members.

        Raises:
            ImportSourceError: When the root is missing, or the repository or an include is unreadable.
        """
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError("FIX Orchestra fileset is missing its root repository", code="INPUT_MALFORMED")
        try:
            return parse_orchestra_fileset(fileset.members, root, source_label=source_label)
        except OrchestraParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a parsed repository onto the canonical model.

        Raises:
            ImportSourceError: When ``native_ast`` is not a parsed repository.
        """
        if not isinstance(native_ast, OrchestraRepository):
            raise ImportSourceError(
                "FIX Orchestra source must be an OrchestraRepository (see app.fix_orchestra_parser.parse_orchestra)"
            )
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)
