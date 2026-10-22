"""Pydantic model import source — FMT-8.4 (#5465).

The :class:`~app.import_source.ImportSource` adapter that makes a module (or package) of Pydantic
models importable. Unlike the TypeScript code-first readers it needs no toolchain — the REST
service is itself Python — and, deliberately, it never imports the upload: the source is read
with :mod:`ast` (:mod:`app.pydantic_parser`), because executing arbitrary user Python is an
unacceptable risk in a multi-tenant service. What only execution could reveal is declared as a
parsing limit.
"""

from __future__ import annotations

from typing import Any, Optional

from . import pydantic_normalizer  # noqa: F401 — self-registers the normalizer
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
from .pydantic_normalizer import PYDANTIC_FORMAT
from .pydantic_parser import (
    LIMIT_DETAILS,
    PYTHON_SUFFIXES,
    PydanticDocument,
    PydanticParseError,
    is_pydantic_module,
    parse_pydantic,
    parse_pydantic_fileset,
)

__all__ = ["PYDANTIC_CAPABILITIES", "PydanticImportSource"]

#: What the reader models and what it knowingly does not (CPDO-1.2 / CPDO-2.4). Every
#: ``unsupported`` key is also a :data:`app.pydantic_parser.LIMIT_DETAILS` entry.
PYDANTIC_CAPABILITIES: AnalyzerCapabilities = analyzer_capabilities(
    supported=[
        "pydantic.base_model",
        "pydantic.inheritance",
        "pydantic.generic_instantiation",
        "pydantic.field_constraints",
        "pydantic.string_constraints",
        "pydantic.annotated",
        "pydantic.optional",
        "pydantic.union",
        "pydantic.literal",
        "pydantic.enum",
        "pydantic.nested_model",
        "pydantic.self_reference",
        "pydantic.containers",
        "pydantic.scalar_types",
        "pydantic.alias",
        "pydantic.alias_generator_builtin",
        "pydantic.default",
        "pydantic.description",
        "pydantic.deprecated",
        "pydantic.extra_config",
        "pydantic.fileset",
    ],
    unsupported=sorted(LIMIT_DETAILS),
)


class PydanticImportSource(ImportSource, register=True):
    """Adapter for modules of Pydantic models, read statically (never executed)."""

    key = "pydantic"
    label = "Pydantic models"
    description = (
        "Import the Pydantic models of a Python module or package — fields, `Field` constraints, "
        "enums, unions and nested models — as a schemas-only catalog source. The source is read "
        "statically; the module is never imported or run."
    )
    icon = "file-code"
    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    formats = (PYDANTIC_FORMAT,)
    file_extensions = PYTHON_SUFFIXES

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a module that imports pydantic and defines a ``BaseModel`` subclass.

        Args:
            payload: The detection input.

        Returns:
            A :class:`DetectionResult` naming ``pydantic``, or :data:`NO_MATCH`.
        """
        text = payload.text
        if text is None or not is_pydantic_module(text):
            return NO_MATCH
        return DetectionResult(
            confidence=0.95,
            format=PYDANTIC_FORMAT,
            reason="Imports pydantic and defines a `BaseModel` subclass",
        )

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> PydanticDocument:
        """Read one module statically.

        Raises:
            ImportSourceError: With the intake taxonomy code the failure belongs to.
        """
        try:
            return parse_pydantic(raw, source_label=source_label)
        except PydanticParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> PydanticDocument:
        """Read a package of modules statically, resolving imports between them.

        Raises:
            ImportSourceError: If the root is missing or a module cannot be read.
        """
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError(
                "Pydantic fileset is missing its root module", code="INPUT_SEMANTIC_INVALID"
            )
        try:
            return parse_pydantic_fileset(fileset.members, root=root, source_label=source_label)
        except PydanticParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize statically-read models onto the canonical data-schema model.

        Raises:
            ImportSourceError: If ``native_ast`` is not a parsed Pydantic document.
        """
        if not isinstance(native_ast, PydanticDocument):
            raise ImportSourceError(
                "Pydantic source must be a PydanticDocument (see app.pydantic_parser.parse_pydantic)"
            )
        return self._normalize_via_registry(PYDANTIC_FORMAT, native_ast, include_raw=include_raw)

    def analysis_capabilities(self) -> AnalyzerCapabilities:
        """Return the reader's declared construct coverage (CPDO-1.2)."""
        return PYDANTIC_CAPABILITIES
