"""Smithy import source.

The :class:`~app.import_source.ImportSource` adapter that makes Smithy IDL models
importable into the catalog (store-raw). Three inputs (MFI-17.1, #3808):

* **one ``.smithy`` file** — assembled through the Smithy CLI when it is available (MFI-17.4),
  otherwise (or when the CLI cannot load it) read by the built-in IDL reader
  (:mod:`app.smithy_parser`);
* **one JSON AST model** (``{"smithy": "2.0", "shapes": {...}}``) — read directly with
  :mod:`json` (:func:`app.smithy_ast.parse_smithy_ast_text`), no CLI needed;
* **a set of several model files** — assembled by the bundled Smithy CLI into one JSON AST
  (:func:`app.smithy_ast.assemble_smithy_set`); without the CLI such a set is refused
  (``ADAPTER_UNAVAILABLE``) rather than imported from its root alone.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import Any, Mapping, Optional

from . import smithy_normalizer  # noqa: F401 — self-registers the normalizer
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
from .smithy_ast import (
    assemble_smithy_set,
    is_smithy_ast_text,
    model_members,
    parse_smithy_ast_text,
    smithy_cli_available,
    validate_smithy_members,
)
from .smithy_parser import SmithyDocument, SmithyParseError, is_smithy, parse_smithy

__all__ = ["SmithyImportSource"]

logger = logging.getLogger(__name__)


def _with_validation(document: SmithyDocument, members: Mapping[str, str]) -> SmithyDocument:
    """Attach ``smithy validate`` events when the Smithy CLI is available (MFI-17.3, #3810).

    Args:
        document: The parsed model.
        members: The model files it was read from, path → text.

    Returns:
        The document with ``validation_events`` set; unchanged without the CLI.
    """
    if not smithy_cli_available():
        return document
    return replace(document, validation_events=tuple(validate_smithy_members(members)))


def _assemble_single(raw: str, source_label: Optional[str]) -> Optional[SmithyDocument]:
    """Assemble one IDL file through the Smithy CLI, or ``None`` when the CLI cannot load it.

    Args:
        raw: The IDL text.
        source_label: Label used in error messages.

    Returns:
        The document read from the CLI's JSON AST; ``None`` so the caller falls back to the
        built-in reader (which reports its own errors).
    """
    try:
        return assemble_smithy_set({"model.smithy": raw}, "model.smithy", source_label=source_label)
    except ImportSourceError as exc:
        logger.info("Smithy CLI could not assemble the model (%s); using the built-in reader", exc)
        return None


class SmithyImportSource(ImportSource, register=True):
    """Adapter for Smithy 2.x IDL model files."""

    key = "smithy"
    label = "Smithy"
    description = "Import a Smithy IDL model (structures, enums, services, operations)."
    icon = "hammer"
    paradigm = ApiParadigm.RPC
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = ("smithy",)
    file_extensions = (".smithy", ".json")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        text = payload.text
        if text is not None and is_smithy_ast_text(text):
            return DetectionResult(
                confidence=0.97, format="smithy", reason="Smithy JSON AST (`smithy` + `shapes`)"
            )
        if text is not None and is_smithy(text):
            if re.search(r"""^\s*\$version\s*:\s*['"]""", text, re.MULTILINE):
                reason = "`$version` control statement"
            elif re.search(r"^\s*service\s+\w", text, re.MULTILINE):
                reason = "`service` definition"
            elif re.search(r"^\s*structure\s+\w", text, re.MULTILINE):
                reason = "`structure` definition"
            elif re.search(r"^\s*operation\s+\w", text, re.MULTILINE):
                reason = "`operation` definition"
            else:
                reason = "Smithy IDL marker"
            return DetectionResult(confidence=0.95, format="smithy", reason=reason)

        filename = (payload.filename or "").lower()
        if filename.endswith(".smithy"):
            if text is not None and is_smithy(text):
                return DetectionResult(
                    confidence=0.9,
                    format="smithy",
                    reason="`.smithy` file extension",
                )
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> SmithyDocument:
        """Parse one model: a JSON AST directly, IDL text through the Smithy CLI or the built-in reader.

        With the Smithy CLI available, IDL text is assembled into a JSON AST like a multi-file set
        (MFI-17.4, #3811: the CLI reads every shape, inline ``:=`` input / output members
        included), falling back to the built-in reader when the CLI cannot load it. The model is
        also validated with the ``smithy-linters`` validators (MFI-17.3, :func:`_with_validation`).
        """
        if is_smithy_ast_text(raw):
            document = parse_smithy_ast_text(raw, source_label=source_label)
            return _with_validation(document, {"model.json": raw})
        document = _assemble_single(raw, source_label) if smithy_cli_available() else None
        if document is None:
            try:
                document = parse_smithy(raw, source_label=source_label)
            except SmithyParseError as exc:
                raise ImportSourceError(str(exc)) from exc
        return _with_validation(document, {"model.smithy": raw})

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> SmithyDocument:
        """Parse a set: several model files are assembled through the Smithy CLI (MFI-17.1).

        A set with a single model file is read like that one file.
        """
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError("Smithy fileset is missing its root document")
        if len(model_members(fileset.members)) <= 1:
            return self.parse(fileset.members[root], source_label=root or source_label)
        document = assemble_smithy_set(dict(fileset.members), root, source_label=root or source_label)
        return _with_validation(document, model_members(fileset.members))

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(native_ast, SmithyDocument):
            raise ImportSourceError(
                "Smithy source must be a SmithyDocument (see app.smithy_parser.parse_smithy)"
            )
        return self._normalize_via_registry("smithy", native_ast, include_raw=include_raw)
