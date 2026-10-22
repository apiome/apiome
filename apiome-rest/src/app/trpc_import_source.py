"""tRPC router import source — FMT-8.3 (#5464).

The :class:`~app.import_source.ImportSource` adapter that makes a tRPC router importable — a
router module, a paste, or a set of modules (feature routers merged into an app router, schemas
in a shared module). tRPC has no IDL at all; the contract exists only as the router value, so
the module is **evaluated** by the sandboxed extractor FMT-8.2 built (:mod:`app.trpc_parser`)
and its procedures become ``rpc`` operations (:mod:`app.trpc_normalizer`).
"""

from __future__ import annotations

from typing import Any, Optional

from . import trpc_normalizer  # noqa: F401 — self-registers the normalizer
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
from .trpc_normalizer import TRPC_FORMAT
from .trpc_parser import (
    LIMIT_DETAILS,
    TrpcDocument,
    TrpcParseError,
    is_trpc_module,
    parse_trpc,
    parse_trpc_fileset,
)
from .typescript_types_parser import TYPESCRIPT_SUFFIXES
from .zod_parser import ZOD_SCHEMA_TOOL_KEY

__all__ = ["TRPC_CAPABILITIES", "TrpcImportSource"]

#: What the reader models and what it knowingly does not (CPDO-1.2 / CPDO-2.4). Every
#: ``unsupported`` key is also a :data:`app.trpc_parser.LIMIT_DETAILS` entry.
TRPC_CAPABILITIES: AnalyzerCapabilities = analyzer_capabilities(
    supported=[
        "trpc.router",
        "trpc.nested_router",
        "trpc.merged_routers",
        "trpc.query",
        "trpc.mutation",
        "trpc.subscription",
        "trpc.zod_input",
        "trpc.chained_input",
        "trpc.zod_output",
        "trpc.meta",
        "trpc.shared_schemas",
        "trpc.fileset",
    ],
    unsupported=sorted(LIMIT_DETAILS),
)


class TrpcImportSource(ImportSource, register=True):
    """Adapter for tRPC routers (procedures as ``rpc`` operations)."""

    key = "trpc"
    label = "tRPC router"
    description = (
        "Import a tRPC router — its procedures as query, mutation and subscription operations, "
        "nested routers as operation groups, and Zod inputs and outputs as schemas. The module "
        "is evaluated in a sandbox with no network and a time limit."
    )
    icon = "network"
    paradigm = ApiParadigm.RPC
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    formats = (TRPC_FORMAT,)
    file_extensions = TYPESCRIPT_SUFFIXES
    required_tools = (ZOD_SCHEMA_TOOL_KEY,)

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a module that imports ``@trpc/server`` and builds a router (a text sniff).

        Args:
            payload: The detection input.

        Returns:
            A :class:`DetectionResult` naming ``trpc``, or :data:`NO_MATCH`.
        """
        text = payload.text
        if text is None or not is_trpc_module(text):
            return NO_MATCH
        return DetectionResult(
            confidence=0.97,
            format=TRPC_FORMAT,
            reason="Imports `@trpc/server` and builds a router",
        )

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> TrpcDocument:
        """Evaluate one router module.

        Raises:
            ImportSourceError: With the intake taxonomy code the failure belongs to.
        """
        try:
            return parse_trpc(raw, source_label=source_label)
        except TrpcParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> TrpcDocument:
        """Evaluate a router set (an app router, feature routers, shared schemas) together.

        Raises:
            ImportSourceError: If the root is missing or the set fails to evaluate.
        """
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError(
                "tRPC fileset is missing its root module", code="INPUT_SEMANTIC_INVALID"
            )
        try:
            return parse_trpc_fileset(fileset.members, root=root, source_label=source_label)
        except TrpcParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize parsed routers onto the canonical ``rpc`` model.

        Raises:
            ImportSourceError: If ``native_ast`` is not a parsed tRPC document.
        """
        if not isinstance(native_ast, TrpcDocument):
            raise ImportSourceError(
                "tRPC source must be a TrpcDocument (see app.trpc_parser.parse_trpc)"
            )
        return self._normalize_via_registry(TRPC_FORMAT, native_ast, include_raw=include_raw)

    def analysis_capabilities(self) -> AnalyzerCapabilities:
        """Return the reader's declared construct coverage (CPDO-1.2)."""
        return TRPC_CAPABILITIES
