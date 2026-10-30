"""Smithy emitter validate + round-trip (Smithy CLI) — MFX-20.3 (#3916).

The Smithy emitter (:class:`app.smithy_emitter.SmithyEmitter`, MFX-20.1) writes a Smithy 2.0 model —
IDL (``.smithy``), JSON AST (``.json``) or both — and its fidelity pack (MFX-20.2) *predicts* what
Smithy cannot carry. This module validates the export with the **Smithy CLI**, the tool a
``smithy build`` runs, and then **measures** what survived by importing the built model again:

* **validate** — ``smithy validate`` (:func:`app.smithy_ast.validate_smithy_members`, the run the
  import's lint pack already makes, with the ``smithy-linters`` validators when the image has them)
  loads the model with the prelude and runs every validator. A ``smithy build`` fails on the same
  events: every ``ERROR`` and ``DANGER`` event makes the export **invalid**; ``WARNING`` and
  ``NOTE`` events (style lints) do not. Each emitted file is validated on its own — the IDL and the
  JSON AST of ``output: both`` describe the same model, so loading them together would collide.
  Without the CLI, the built-in reader (IDL) or the JSON AST reader parses the file instead, and
  :attr:`SmithyRoundTripReport.validator` says which ran. A CLI that is installed but gives no answer
  (a timeout, no events table) is a problem: "the CLI did not run" must never read as "it found
  nothing".
* **build + re-import** — :func:`reimport_built_model`: with the CLI, the model is assembled by
  ``smithy ast`` (:func:`app.smithy_ast.assemble_smithy_set`, the JSON AST a build's ``model``
  projection writes) and read by the AST mapper; without it, by the built-in reader. A failure is
  **unparseable**.
* **diff** — :func:`app.import_source.canonical_diff` against the source, by stable key;
* **reconcile** — :func:`app.roundtrip_matrix.reconcile` joins every difference to the fidelity finding
  that explains it (MFX-2.6): *unexplained* differences are silent losses, *overclaims* are constructs
  the report called preserved that changed.

Apiome does not run ``smithy build`` itself: a build reads a ``smithy-build.json``, resolves Maven
dependencies over the network and writes projections, none of which an export needs; ``validate``
and ``ast`` are the two halves of it that are. The CLI is a JVM subprocess; call these off the event
loop.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from . import smithy_ast
from .canonical_model import CanonicalApi
from .emitter import EmitResult, EmittedFile, Loss
from .fidelity_engine import compute_lossiness_for_emitter
from .import_source import CanonicalDiff, CanonicalDiffEntry, ImportSourceError, canonical_diff
from .roundtrip_matrix import reconcile
from .smithy_emitter import SmithyEmitter
from .smithy_import_source import SmithyImportSource
from .smithy_parser import SmithyDocument, SmithyParseError, parse_smithy
from .toolchain_runner import ToolchainError, ToolNotAvailableError

__all__ = [
    "BLOCKING_SEVERITIES",
    "RoundTripStatus",
    "SmithyRoundTripReport",
    "reimport_built_model",
    "round_trip_smithy",
    "validate_emitted_smithy",
]

#: Which check validated the model.
Validator = Literal["smithy", "reader"]

#: The ``smithy validate`` event severities that fail an export (and a ``smithy build``).
BLOCKING_SEVERITIES = frozenset({"ERROR", "DANGER"})


class RoundTripStatus(str, Enum):
    """The outcome of an emit → validate → build → re-import → diff round trip, worst first.

    * :attr:`INVALID` — the CLI reported an ``ERROR`` or ``DANGER`` event (or, without it, the reader
      could not parse the model).
    * :attr:`UNPARSEABLE` — it validated, but the built model does not import.
    * :attr:`LOSSY` — it imports, and differs from the source.
    * :attr:`LOSSLESS` — it imports, and matches the source entity for entity.
    """

    INVALID = "invalid"
    UNPARSEABLE = "unparseable"
    LOSSY = "lossy"
    LOSSLESS = "lossless"


class SmithyRoundTripReport(BaseModel):
    """What validating and round-tripping one Smithy export found."""

    model_config = ConfigDict(extra="forbid")

    validator: Validator = Field(description="``smithy`` when the Smithy CLI validated the model, else ``reader``.")
    problems: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="The blocking events (``severity``, ``id``, ``shape``, ``file``, ``line``, ``column``, "
        "``message``).",
    )
    reimported: bool = Field(default=False, description="Whether the built model imported again.")
    import_error: Optional[str] = Field(default=None, description="Why it did not import.")
    diff: Optional[CanonicalDiff] = Field(
        default=None, description="Source → re-imported model, by key. ``None`` when it did not import."
    )
    unexplained: List[CanonicalDiffEntry] = Field(
        default_factory=list, description="Differences no fidelity finding explains (silent losses)."
    )
    overclaims: List[str] = Field(
        default_factory=list, description="Constructs the fidelity report called preserved that changed."
    )
    predicted_losses: List[Loss] = Field(default_factory=list, description="The losses the emitter recorded.")

    @property
    def valid(self) -> bool:
        """Whether the model had no blocking event **and** imported again."""
        return not self.problems and self.reimported

    @property
    def empirically_lossless(self) -> bool:
        """Whether the measured round trip changed nothing."""
        return self.diff is not None and self.diff.is_empty

    @property
    def predicted_lossless(self) -> bool:
        """Whether the emitter predicted no loss."""
        return not self.predicted_losses

    @property
    def explained(self) -> bool:
        """Whether every measured difference is explained and nothing is over-claimed."""
        return self.diff is not None and not self.unexplained and not self.overclaims

    @property
    def diverges(self) -> bool:
        """Whether prediction and measurement disagree (MFX-2.6); ``False`` when nothing was measured."""
        if self.diff is None:
            return False
        return self.empirically_lossless != self.predicted_lossless or not self.explained

    @property
    def status(self) -> RoundTripStatus:
        """The single ordered verdict (see :class:`RoundTripStatus`)."""
        if self.problems:
            return RoundTripStatus.INVALID
        if not self.reimported:
            return RoundTripStatus.UNPARSEABLE
        if self.empirically_lossless:
            return RoundTripStatus.LOSSLESS
        return RoundTripStatus.LOSSY


def _read_with_reader(emitted: EmittedFile) -> None:
    """Parse one emitted model with the CLI-free reader (raises on a model it cannot read)."""
    text = str(emitted.content)
    if smithy_ast.is_smithy_ast_text(text):
        smithy_ast.parse_smithy_ast_text(text, source_label=emitted.path)
    else:
        parse_smithy(text, source_label=emitted.path)


def validate_emitted_smithy(emit_result: EmitResult) -> Tuple[Validator, List[Dict[str, Any]]]:
    """Validate every emitted Smithy file with ``smithy validate``, or the reader when the CLI is absent.

    Args:
        emit_result: The Smithy emitter's output (one IDL file, one JSON AST, or both).

    Returns:
        ``(validator, problems)``: which check ran, and its blocking events — every ``ERROR`` and
        ``DANGER`` event (each naming its ``file``), or the reader's parse error. Empty when valid.

    Raises:
        ValueError: When the export wrote no file.
    """
    if not emit_result.files:
        raise ValueError("The Smithy export wrote no file.")
    if smithy_ast.smithy_cli_available():
        problems: List[Dict[str, Any]] = []
        try:
            for emitted in emit_result.files:
                events = smithy_ast.validate_smithy_members({emitted.path: str(emitted.content)}, strict=True)
                problems.extend(
                    {**event, "file": emitted.path} for event in events if event.get("severity") in BLOCKING_SEVERITIES
                )
        except ToolNotAvailableError:
            pass  # the CLI went missing between the probe and the run: fall back to the reader
        except (ToolchainError, ValueError) as exc:
            failure = {"severity": "ERROR", "id": "SmithyCli", "message": f"the Smithy CLI could not validate the "
                       f"model: {exc}", "file": emit_result.files[0].path}
            return "smithy", [failure]
        else:
            return "smithy", problems
    problems = []
    for emitted in emit_result.files:
        try:
            _read_with_reader(emitted)
        except (ImportSourceError, SmithyParseError) as exc:
            problems.append({"severity": "ERROR", "id": "SmithyParse", "message": str(exc), "file": emitted.path})
    return "reader", problems


def _build_with_cli(emitted: EmittedFile, text: str) -> Optional[SmithyDocument]:
    """Assemble an IDL model with ``smithy ast``; ``None`` when the CLI went missing (use the reader).

    Raises:
        ImportSourceError: When the CLI ran and could not build the model.
    """
    try:
        return smithy_ast.assemble_smithy_set({emitted.path: text}, emitted.path, source_label=emitted.path)
    except ImportSourceError as exc:
        if exc.code == "ADAPTER_UNAVAILABLE":
            return None
        raise


def reimport_built_model(emit_result: EmitResult) -> CanonicalApi:
    """Build the first emitted model and import it the way an upload of the model would be.

    With the Smithy CLI, an IDL model is assembled by ``smithy ast`` and read by the AST mapper (a
    JSON AST is already the built form); without it — or when it goes missing mid-run — the built-in
    reader reads the IDL.

    Args:
        emit_result: The Smithy emitter's output; its first file is the model.

    Returns:
        The canonical model.

    Raises:
        ImportSourceError: When the model does not build, parse or normalize (a malformed shape the
            normalizer trips over is ``INPUT_MALFORMED``).
    """
    emitted = emit_result.files[0]
    text = str(emitted.content)
    try:
        if smithy_ast.is_smithy_ast_text(text):
            document = smithy_ast.parse_smithy_ast_text(text, source_label=emitted.path)
        else:
            document = _build_with_cli(emitted, text) if smithy_ast.smithy_cli_available() else None
            if document is None:
                document = parse_smithy(text, source_label=emitted.path)
        return SmithyImportSource().normalize(document, include_raw=False)
    except SmithyParseError as exc:
        raise ImportSourceError(str(exc)) from exc
    except ImportSourceError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ImportSourceError(f"Malformed Smithy model: {exc}", code="INPUT_MALFORMED") from exc


def round_trip_smithy(api: CanonicalApi, *, emit_result: Optional[EmitResult] = None) -> SmithyRoundTripReport:
    """Validate the Smithy export of ``api``, build and import it again, and reconcile the difference.

    Args:
        api: The source canonical model.
        emit_result: An emission to use instead of emitting here (the export job already has one).

    Returns:
        The :class:`SmithyRoundTripReport`.
    """
    emitter = SmithyEmitter()
    if emit_result is None:
        emit_result = emitter.emit(api)
    predicted = list(emit_result.losses)
    try:
        validator, problems = validate_emitted_smithy(emit_result)
    except ValueError as exc:
        failure = {"severity": "ERROR", "id": "SmithyExport", "message": str(exc), "file": None}
        return SmithyRoundTripReport(validator="reader", problems=[failure], predicted_losses=predicted)
    if problems:
        return SmithyRoundTripReport(validator=validator, problems=problems, predicted_losses=predicted)
    try:
        reimported = reimport_built_model(emit_result)
    except ImportSourceError as exc:
        return SmithyRoundTripReport(validator=validator, import_error=str(exc), predicted_losses=predicted)
    measured = canonical_diff(api, reimported)
    outcome = reconcile(measured, compute_lossiness_for_emitter(api, emitter))
    return SmithyRoundTripReport(
        validator=validator,
        reimported=True,
        diff=measured,
        unexplained=list(outcome.unexplained),
        overclaims=[item.construct_key for item in outcome.overclaims],
        predicted_losses=predicted,
    )
