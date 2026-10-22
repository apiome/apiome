"""Zod schema import source — FMT-8.2 (#5463).

The :class:`~app.import_source.ImportSource` adapter that makes a module of exported Zod schemas
importable — a ``.ts`` file, a paste, or a set of modules that import schemas from one another.
Zod is where most TypeScript projects keep their runtime schema, with the validation constraints
(``min``/``max``, ``regex``, ``email``, ``uuid``) an API description needs; this adapter brings
those constraints into the catalog.

The module is **evaluated** by the bundled ``zod-schema-extractor`` tool
(:mod:`app.zod_parser`) — permission-locked, network-free and time-bounded — and its schemas
are mapped onto the canonical data-schema model by :mod:`app.zod_normalizer`. The extractor is a
**required** tool under the FMT-1.3 packaging rule, so a shipped runtime never reports this
adapter ``available: false``.
"""

from __future__ import annotations

from typing import Any, Optional

from . import zod_normalizer  # noqa: F401 — self-registers the normalizer
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
from .payload_analysis import AnalyzerCapabilities, analyzer_capabilities
from .typescript_types_parser import TYPESCRIPT_SUFFIXES
from .zod_normalizer import ZOD_FORMAT
from .zod_parser import (
    LIMIT_DETAILS,
    ZOD_SCHEMA_TOOL_KEY,
    ZodDocument,
    ZodParseError,
    is_zod_module,
    parse_zod,
    parse_zod_fileset,
)

__all__ = ["ZOD_CAPABILITIES", "ZodImportSource"]

#: What the reader models and what it knowingly does not (CPDO-1.2 / CPDO-2.4).
#:
#: The ``unsupported`` half is FMT-8.2's "refinements and transforms are declared limits, not
#: silently dropped" criterion in machine-readable form: every key is also a
#: :data:`app.zod_parser.LIMIT_DETAILS` entry.
ZOD_CAPABILITIES: AnalyzerCapabilities = analyzer_capabilities(
    supported=[
        "zod.object",
        "zod.string_constraints",
        "zod.string_formats",
        "zod.number_constraints",
        "zod.integer",
        "zod.bigint",
        "zod.boolean",
        "zod.date",
        "zod.literal",
        "zod.enum",
        "zod.native_enum",
        "zod.array",
        "zod.tuple",
        "zod.set",
        "zod.map",
        "zod.record",
        "zod.union",
        "zod.discriminated_union",
        "zod.intersection_of_objects",
        "zod.optional",
        "zod.nullable",
        "zod.default",
        "zod.describe",
        "zod.strict",
        "zod.passthrough",
        "zod.catchall",
        "zod.lazy",
        "zod.object_methods",
        "zod.fileset",
    ],
    unsupported=sorted(LIMIT_DETAILS),
)


class ZodImportSource(ImportSource, register=True):
    """Adapter for modules of exported Zod schemas."""

    key = "zod"
    label = "Zod schemas"
    description = (
        "Import the exported Zod schemas of a TypeScript module — or a set of modules that "
        "import one another — with their validation constraints, as a schemas-only catalog "
        "source. The module is evaluated in a sandbox with no network and a time limit."
    )
    icon = "shield-check"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    formats = (ZOD_FORMAT,)
    file_extensions = TYPESCRIPT_SUFFIXES
    required_tools = (ZOD_SCHEMA_TOOL_KEY,)

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a module that imports Zod and exports ``z.…`` values.

        A text sniff — no evaluation — so detection never runs user code. A module of plain
        TypeScript types imports no Zod and is left to the TypeScript-types adapter.

        Args:
            payload: The detection input.

        Returns:
            A :class:`DetectionResult` naming ``zod``, or :data:`NO_MATCH`.
        """
        text = payload.text
        if text is None or not is_zod_module(text):
            return NO_MATCH
        return DetectionResult(
            confidence=0.95,
            format=ZOD_FORMAT,
            reason="Imports `zod` and exports `z.…` schema values",
        )

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> ZodDocument:
        """Evaluate one module and read its exported schemas.

        Args:
            raw: The module source.
            source_label: The module's name, for error messages.

        Returns:
            The parsed :class:`~app.zod_parser.ZodDocument`.

        Raises:
            ImportSourceError: With the intake taxonomy code the failure belongs to.
        """
        try:
            return parse_zod(raw, source_label=source_label)
        except ZodParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> ZodDocument:
        """Evaluate a set of modules together, so schemas imported between them resolve.

        Args:
            fileset: The intake fileset, rooted at the module whose exports define the model.
            source_label: Fallback label when the set names no root.

        Returns:
            The parsed document.

        Raises:
            ImportSourceError: If the root is missing or a module fails to evaluate.
        """
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError(
                "Zod fileset is missing its root module", code="INPUT_SEMANTIC_INVALID"
            )
        try:
            return parse_zod_fileset(fileset.members, root=root, source_label=source_label)
        except ZodParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize parsed Zod schemas onto the canonical data-schema model.

        Args:
            native_ast: The parsed document.
            include_raw: Whether to retain the sources and the extracted JSON Schema.

        Returns:
            The canonical model.

        Raises:
            ImportSourceError: If ``native_ast`` is not a parsed Zod document.
        """
        if not isinstance(native_ast, ZodDocument):
            raise ImportSourceError(
                "Zod source must be a ZodDocument (see app.zod_parser.parse_zod)"
            )
        return self._normalize_via_registry(ZOD_FORMAT, native_ast, include_raw=include_raw)

    def analysis_capabilities(self) -> AnalyzerCapabilities:
        """Return the reader's declared construct coverage (CPDO-1.2)."""
        return ZOD_CAPABILITIES
