"""CUE, Pkl and Dhall import sources — FMT-8.5 (#5466).

The three :class:`~app.import_source.ImportSource` adapters that make typed configuration
schemas importable as schemas-only catalog sources: a CUE package's definitions, a Pkl module's
classes and type aliases, and a Dhall expression's record and union types.

Each language is read by its **own** tool in the sandboxed toolchain runner — ``cue``, ``pkl``,
``dhall`` — network-free, time-bounded, with its own cache (:mod:`app.typed_config_common`),
projected to JSON Schema by its reader (:mod:`app.cue_parser`, :mod:`app.pkl_parser`,
:mod:`app.dhall_parser`) and normalized by the shared JSON Schema path
(:mod:`app.typed_config_normalizer`). The tools are **required** under the FMT-1.3 packaging
rule, so a shipped runtime never reports these adapters ``available: false``.
"""

from __future__ import annotations

from typing import Any, Callable, ClassVar, Optional, Tuple

from . import typed_config_normalizer  # noqa: F401 — self-registers the normalizers
from .canonical_model import ApiParadigm, CanonicalApi
from .cue_parser import CUE_FORMAT, CUE_SUFFIXES, CUE_TOOL_KEY, is_cue_source, parse_cue, parse_cue_fileset
from .cue_parser import LIMIT_DETAILS as CUE_LIMIT_DETAILS
from .dhall_parser import (
    DHALL_FORMAT,
    DHALL_SUFFIXES,
    DHALL_TOOL_KEY,
    is_dhall_source,
    parse_dhall,
    parse_dhall_fileset,
)
from .dhall_parser import LIMIT_DETAILS as DHALL_LIMIT_DETAILS
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
from .pkl_parser import LIMIT_DETAILS as PKL_LIMIT_DETAILS
from .pkl_parser import PKL_FORMAT, PKL_SUFFIXES, PKL_TOOL_KEY, is_pkl_source, parse_pkl, parse_pkl_fileset
from .typed_config_common import TypedConfigDocument, TypedConfigParseError

__all__ = [
    "CUE_CAPABILITIES",
    "CueImportSource",
    "DHALL_CAPABILITIES",
    "DhallImportSource",
    "PKL_CAPABILITIES",
    "PklImportSource",
]

#: What the CUE reader models and what it knowingly does not (CPDO-1.2 / CPDO-2.4). Every
#: ``unsupported`` key is also a :data:`app.cue_parser.LIMIT_DETAILS` entry.
CUE_CAPABILITIES: AnalyzerCapabilities = analyzer_capabilities(
    supported=[
        "cue.definition",
        "cue.closed_struct",
        "cue.open_struct",
        "cue.embedding",
        "cue.unification_narrowing",
        "cue.disjunction",
        "cue.bounds",
        "cue.regex",
        "cue.rune_and_item_bounds",
        "cue.optional_field",
        "cue.list",
        "cue.pattern_constraint",
        "cue.recursion",
        "cue.imported_package",
        "cue.module",
    ],
    unsupported=sorted(CUE_LIMIT_DETAILS),
)

#: What the Pkl reader models and what it knowingly does not.
PKL_CAPABILITIES: AnalyzerCapabilities = analyzer_capabilities(
    supported=[
        "pkl.class",
        "pkl.inheritance",
        "pkl.typealias",
        "pkl.string_literal_union",
        "pkl.union",
        "pkl.nullable",
        "pkl.listing",
        "pkl.mapping",
        "pkl.set",
        "pkl.int_aliases",
        "pkl.constraint_keywords",
        "pkl.default",
        "pkl.doc_comment",
        "pkl.module_template",
        "pkl.imported_module",
    ],
    unsupported=sorted(PKL_LIMIT_DETAILS),
)

#: What the Dhall reader models and what it knowingly does not.
DHALL_CAPABILITIES: AnalyzerCapabilities = analyzer_capabilities(
    supported=[
        "dhall.record_type",
        "dhall.union_type",
        "dhall.schema_record",
        "dhall.optional",
        "dhall.list",
        "dhall.map_entries",
        "dhall.record_type_merge",
        "dhall.type_application",
        "dhall.local_import",
        "dhall.default",
    ],
    unsupported=sorted(DHALL_LIMIT_DETAILS),
)


class _TypedConfigImportSource(ImportSource):
    """The shared adapter body: detect with a text sniff, evaluate with the language's tool."""

    paradigm = ApiParadigm.DATA_SCHEMA
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)

    #: The language's display name, for messages.
    language_label: ClassVar[str] = ""
    #: Detection sniff (no subprocess).
    sniff: ClassVar[Callable[[str], bool]]
    #: Single-file reader.
    reader: ClassVar[Callable[..., TypedConfigDocument]]
    #: Fileset reader.
    fileset_reader: ClassVar[Callable[..., TypedConfigDocument]]
    #: Declared construct coverage.
    capabilities: ClassVar[AnalyzerCapabilities]
    #: Why detection claimed a document.
    detection_reason: ClassVar[str] = ""

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a document by its language's markers — a text sniff that never runs the tool.

        Args:
            payload: The detection input.

        Returns:
            A :class:`DetectionResult` naming this adapter's format, or :data:`NO_MATCH`.
        """
        text = payload.text
        if text is None or not type(self).sniff(text):
            return NO_MATCH
        filename = (payload.filename or "").lower()
        confidence = 0.95 if filename.endswith(self.file_extensions) else 0.85
        return DetectionResult(confidence=confidence, format=self.formats[0], reason=self.detection_reason)

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> TypedConfigDocument:
        """Evaluate one file with the language's tool and project it to JSON Schema.

        Raises:
            ImportSourceError: With the intake taxonomy code the failure belongs to.
        """
        try:
            return type(self).reader(raw, source_label=source_label)
        except TypedConfigParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> TypedConfigDocument:
        """Evaluate a set of files that import one another, rooted at the set's root.

        Raises:
            ImportSourceError: If the root is missing or the set cannot be evaluated.
        """
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError(
                f"{self.language_label} fileset is missing its root file", code="INPUT_SEMANTIC_INVALID"
            )
        try:
            return type(self).fileset_reader(fileset.members, root=root, source_label=source_label)
        except TypedConfigParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize the projection onto the canonical data-schema model.

        Raises:
            ImportSourceError: If ``native_ast`` is not a document this adapter's reader produced.
        """
        if not isinstance(native_ast, TypedConfigDocument) or native_ast.language != self.formats[0]:
            raise ImportSourceError(
                f"{self.language_label} source must be a TypedConfigDocument read by the "
                f"{self.language_label} reader"
            )
        return self._normalize_via_registry(self.formats[0], native_ast, include_raw=include_raw)

    def analysis_capabilities(self) -> AnalyzerCapabilities:
        """Return the reader's declared construct coverage (CPDO-1.2)."""
        return type(self).capabilities


class CueImportSource(_TypedConfigImportSource, register=True):
    """Adapter for CUE packages and modules."""

    key = CUE_FORMAT
    label = "CUE"
    description = (
        "Import the definitions of a CUE package — or a module of packages — with their "
        "constraints, as a schemas-only catalog source. `cue export` evaluates it in a sandbox "
        "with no network and a time limit."
    )
    icon = "braces"
    formats = (CUE_FORMAT,)
    file_extensions = CUE_SUFFIXES
    required_tools: Tuple[str, ...] = (CUE_TOOL_KEY,)
    language_label = "CUE"
    sniff = staticmethod(is_cue_source)
    reader = staticmethod(parse_cue)
    fileset_reader = staticmethod(parse_cue_fileset)
    capabilities = CUE_CAPABILITIES
    detection_reason = "`package` clause with `#Definition:` declarations"


class PklImportSource(_TypedConfigImportSource, register=True):
    """Adapter for Pkl modules."""

    key = PKL_FORMAT
    label = "Pkl"
    description = (
        "Import the classes and type aliases of a Pkl module — or a set of modules that import "
        "one another — with their type constraints, as a schemas-only catalog source. `pkl eval` "
        "reads it in a sandbox with no network, no resource reads and a time limit."
    )
    icon = "braces"
    formats = (PKL_FORMAT,)
    file_extensions = PKL_SUFFIXES
    required_tools: Tuple[str, ...] = (PKL_TOOL_KEY,)
    language_label = "Pkl"
    sniff = staticmethod(is_pkl_source)
    reader = staticmethod(parse_pkl)
    fileset_reader = staticmethod(parse_pkl_fileset)
    capabilities = PKL_CAPABILITIES
    detection_reason = "`module` clause or `class` / `typealias` declarations"


class DhallImportSource(_TypedConfigImportSource, register=True):
    """Adapter for Dhall expressions and packages."""

    key = DHALL_FORMAT
    label = "Dhall"
    description = (
        "Import the record and union types of a Dhall expression — or a package of files — as a "
        "schemas-only catalog source. The Dhall interpreter resolves, type-checks and normalizes "
        "it in a sandbox with no network and a time limit; imports from outside the upload are "
        "refused."
    )
    icon = "braces"
    formats = (DHALL_FORMAT,)
    file_extensions = DHALL_SUFFIXES
    required_tools: Tuple[str, ...] = (DHALL_TOOL_KEY,)
    language_label = "Dhall"
    sniff = staticmethod(is_dhall_source)
    reader = staticmethod(parse_dhall)
    fileset_reader = staticmethod(parse_dhall_fileset)
    capabilities = DHALL_CAPABILITIES
    detection_reason = "`let … in` bindings, typed record fields or a `{ Type, default }` schema record"

