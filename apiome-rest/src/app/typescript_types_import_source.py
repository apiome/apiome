"""TypeScript type declarations import source — FMT-8.1 (#5462).

The :class:`~app.import_source.ImportSource` adapter that makes a module of TypeScript
``interface``, ``type`` and ``enum`` declarations importable — a ``.ts`` or ``.d.ts`` file, a
paste, or a set of modules that ``import type`` from one another. A team with a ``types.ts`` and
no OpenAPI document now has something to bring into the catalog.

The module is read by the TypeScript compiler itself (:mod:`app.typescript_types_parser`, the
bundled ``typescript-types-extractor`` tool) and mapped onto the canonical data-schema model by
:mod:`app.typescript_types_normalizer`. The extractor is a **required** tool under the FMT-1.3
packaging rule: the image installs and smoke-tests it, the startup self-check refuses to boot
without it, and the adapter therefore never reports itself ``available: false`` in a shipped
runtime.
"""

from __future__ import annotations

from typing import Any, Optional

from . import typescript_types_normalizer  # noqa: F401 — self-registers the normalizer
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
from .typescript_types_normalizer import TYPESCRIPT_TYPES_FORMAT
from .typescript_types_parser import (
    TYPESCRIPT_SUFFIXES,
    TYPESCRIPT_TYPES_TOOL_KEY,
    TsDocument,
    TsParseError,
    is_typescript_types,
    parse_typescript_types,
    parse_typescript_types_fileset,
)

__all__ = ["TYPESCRIPT_TYPES_CAPABILITIES", "TypeScriptTypesImportSource"]

#: What the reader models and what it knowingly does not (CPDO-1.2 / CPDO-2.4).
#:
#: The ``unsupported`` half is FMT-8.1's "unresolvable generics, conditional and mapped types
#: are declared parsing limits" criterion in machine-readable form: every key is also a
#: :data:`app.typescript_types_parser.LIMIT_DETAILS` entry, so the registry's list, the
#: adapter's declaration and the per-document coverage ledger name the same constructs in the
#: same words.
TYPESCRIPT_TYPES_CAPABILITIES: AnalyzerCapabilities = analyzer_capabilities(
    supported=[
        "typescript.interface",
        "typescript.type_alias",
        "typescript.enum",
        "typescript.const_enum",
        "typescript.primitive",
        "typescript.literal",
        "typescript.literal_union",
        "typescript.union",
        "typescript.discriminated_union",
        "typescript.intersection_of_objects",
        "typescript.array",
        "typescript.readonly_array",
        "typescript.tuple",
        "typescript.object_literal",
        "typescript.index_signature_map",
        "typescript.record",
        "typescript.map",
        "typescript.set",
        "typescript.optional",
        "typescript.readonly",
        "typescript.nullable",
        "typescript.extends",
        "typescript.generic_instantiation",
        "typescript.utility_type",
        "typescript.indexed_access",
        "typescript.keyof",
        "typescript.jsdoc",
        "typescript.deprecated",
        "typescript.import_type",
        "typescript.re_export",
        "typescript.fileset",
    ],
    unsupported=[
        "typescript.conditional_type",
        "typescript.declaration_merging",
        "typescript.function_type",
        "typescript.index_signature",
        "typescript.intersection",
        "typescript.lib_type",
        "typescript.mapped_type",
        "typescript.symbol_key",
        "typescript.template_literal_type",
        "typescript.tuple_positions",
        "typescript.type_query",
        "typescript.unmodelled_reference",
        "typescript.unresolved_generic",
    ],
)


class TypeScriptTypesImportSource(ImportSource, register=True):
    """Adapter for TypeScript ``interface`` / ``type`` / ``enum`` declarations."""

    key = "typescript-types"
    label = "TypeScript types"
    description = (
        "Import the exported `interface`, `type` and `enum` declarations of a TypeScript "
        "module (`.ts` / `.d.ts`) — or a set of modules that import one another — as a "
        "schemas-only catalog source."
    )
    icon = "braces"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    formats = (TYPESCRIPT_TYPES_FORMAT,)
    file_extensions = TYPESCRIPT_SUFFIXES
    required_tools = (TYPESCRIPT_TYPES_TOOL_KEY,)

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a module of exported type declarations.

        Detection is a text sniff — no compiler run — so it is cheap and never raises. An
        exported ``interface`` / ``type`` / ``enum`` (or a re-export) is the evidence; a
        TypeScript filename raises the confidence. A module that imports a code-first schema
        library (Zod and its kin) is never claimed: its schemas are values, and they belong to
        that library's own adapter.

        Args:
            payload: The detection input.

        Returns:
            A :class:`DetectionResult` naming ``typescript-types``, or :data:`NO_MATCH`.
        """
        text = payload.text
        if text is None or not is_typescript_types(text):
            return NO_MATCH
        filename = (payload.filename or "").strip().lower()
        if filename.endswith(TYPESCRIPT_SUFFIXES):
            return DetectionResult(
                confidence=0.95,
                format=TYPESCRIPT_TYPES_FORMAT,
                reason="Exported TypeScript type declarations in a `.ts` / `.d.ts` module",
            )
        return DetectionResult(
            confidence=0.85,
            format=TYPESCRIPT_TYPES_FORMAT,
            reason="Exported TypeScript `interface` / `type` / `enum` declarations",
        )

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> TsDocument:
        """Read one module through the TypeScript compiler.

        Args:
            raw: The module source.
            source_label: The module's name (its suffix tells the compiler a ``.d.ts`` from a
                ``.ts``), for the compiler and error messages.

        Returns:
            The parsed :class:`~app.typescript_types_parser.TsDocument`.

        Raises:
            ImportSourceError: With the intake taxonomy code the failure belongs to.
        """
        try:
            return parse_typescript_types(raw, source_label=source_label)
        except TsParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> TsDocument:
        """Read a set of modules together, so ``import type`` between them resolves.

        Args:
            fileset: The intake fileset, rooted at the module whose exports define the model.
            source_label: Fallback label when the set names no root.

        Returns:
            The parsed document.

        Raises:
            ImportSourceError: If the root is missing, a module fails to read, or an exported
                type refers to a module the set does not contain.
        """
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError(
                "TypeScript fileset is missing its root module", code="INPUT_SEMANTIC_INVALID"
            )
        try:
            return parse_typescript_types_fileset(
                fileset.members, root=root, source_label=source_label
            )
        except TsParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a parsed module onto the canonical data-schema model.

        Args:
            native_ast: The parsed document.
            include_raw: Whether to retain the module sources in the fidelity bag.

        Returns:
            The canonical model.

        Raises:
            ImportSourceError: If ``native_ast`` is not a parsed TypeScript document.
        """
        if not isinstance(native_ast, TsDocument):
            raise ImportSourceError(
                "TypeScript source must be a TsDocument "
                "(see app.typescript_types_parser.parse_typescript_types)"
            )
        return self._normalize_via_registry(
            TYPESCRIPT_TYPES_FORMAT, native_ast, include_raw=include_raw
        )

    def analysis_capabilities(self) -> AnalyzerCapabilities:
        """Return the reader's declared construct coverage (CPDO-1.2)."""
        return TYPESCRIPT_TYPES_CAPABILITIES
