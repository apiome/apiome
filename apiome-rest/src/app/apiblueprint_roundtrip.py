"""API Blueprint emitter validate + round-trip (drafter) — MFX-18.3 (#3907).

The API Blueprint emitter (:class:`app.apiblueprint_emitter.ApiblueprintEmitter`, MFX-18.1) writes a
``.apib`` document, and its fidelity pack (MFX-18.2) *predicts* what MSON cannot carry. This module
validates the export with drafter — the reference API Blueprint parser the import already runs for its
lint (MFI-16.3) — and then **measures** what survived by importing it again:

* **validate** — :func:`app.apiblueprint_drafter.run_drafter` parses the document. A good blueprint
  has **zero warnings** (the drafter lint's own bar), so every ``error`` *and* ``warning`` annotation
  makes the export **invalid**. When this runtime has no drafter, the built-in reader
  (:func:`app.apiblueprint_parser.parse_apiblueprint`) parses it instead — a parse error is the problem
  — and :attr:`ApiblueprintRoundTripReport.validator` says which ran. A drafter that is installed but
  gives no answer (a timeout, no parse result) is a problem too: "drafter did not run" must never read
  as "drafter found nothing";
* **re-import** — :class:`app.apiblueprint_import_source.ApiblueprintImportSource`, the path a user
  uploading the file would hit; a failure is **unparseable**;
* **diff** — :func:`app.import_source.canonical_diff` against the source, by stable key;
* **reconcile** — :func:`app.roundtrip_matrix.reconcile` joins every difference to the fidelity finding
  that explains it (MFX-2.6): *unexplained* differences are silent losses, *overclaims* are constructs
  the report called preserved that changed.

The export gate (:mod:`app.export_validation`) runs the validation plus :func:`reimport_with_reader`
(the built-in reader and normalizer, so drafter does not run twice). drafter is a subprocess; call
these off the event loop.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from . import apiblueprint_drafter
from .apiblueprint_emitter import ApiblueprintEmitter
from .apiblueprint_import_source import ApiblueprintImportSource
from .apiblueprint_parser import ApiblueprintParseError, parse_apiblueprint
from .canonical_model import CanonicalApi
from .emitter import EmitResult, Loss
from .fidelity_engine import compute_lossiness_for_emitter
from .import_source import CanonicalDiff, CanonicalDiffEntry, ImportSourceError, canonical_diff
from .roundtrip_matrix import reconcile, reimport_emitted
from .toolchain_runner import ToolchainError, ToolNotAvailableError

__all__ = [
    "ApiblueprintRoundTripReport",
    "BLOCKING_SEVERITIES",
    "RoundTripStatus",
    "reimport_with_reader",
    "round_trip_apiblueprint",
    "validate_emitted_apiblueprint",
]

#: Which check validated the document.
Validator = Literal["drafter", "reader"]

#: The drafter annotation severities that fail an export: a good blueprint has zero warnings.
BLOCKING_SEVERITIES = frozenset({"error", "warning"})


class RoundTripStatus(str, Enum):
    """The outcome of an emit → validate → re-import → diff round trip, worst first.

    * :attr:`INVALID` — drafter reported an error or a warning (or, without drafter, the reader could
      not parse the document).
    * :attr:`UNPARSEABLE` — it validated, but does not import.
    * :attr:`LOSSY` — it imports, and differs from the source.
    * :attr:`LOSSLESS` — it imports, and matches the source entity for entity.
    """

    INVALID = "invalid"
    UNPARSEABLE = "unparseable"
    LOSSY = "lossy"
    LOSSLESS = "lossless"


class ApiblueprintRoundTripReport(BaseModel):
    """What validating and round-tripping one API Blueprint export found."""

    model_config = ConfigDict(extra="forbid")

    validator: Validator = Field(description="``drafter`` when drafter parsed the document, else ``reader``.")
    problems: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="The blocking annotations (``severity``, ``code``, ``message``, ``line``, ``column``, ``file``).",
    )
    reimported: bool = Field(default=False, description="Whether the document imported again.")
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
        """Whether the document had no blocking annotation **and** imported again."""
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


def validate_emitted_apiblueprint(emit_result: EmitResult) -> Tuple[Validator, List[Dict[str, Any]]]:
    """Validate every emitted API Blueprint file with drafter, or the reader when drafter is absent.

    Args:
        emit_result: The API Blueprint emitter's output.

    Returns:
        ``(validator, problems)``: which check ran, and its blocking annotations — every drafter
        ``error`` and ``warning`` (each with ``file``), or the reader's parse error. Empty when valid.

    Raises:
        ValueError: When the export wrote no file.
    """
    if not emit_result.files:
        raise ValueError("The API Blueprint export wrote no file.")
    if apiblueprint_drafter.drafter_available():
        problems: List[Dict[str, Any]] = []
        try:
            for emitted in emit_result.files:
                for annotation in apiblueprint_drafter.run_drafter(str(emitted.content), strict=True):
                    if annotation.get("severity") in BLOCKING_SEVERITIES:
                        problems.append({**annotation, "file": emitted.path})
        except ToolNotAvailableError:
            pass  # drafter went missing between the probe and the run: fall back to the reader
        except (ToolchainError, ValueError) as exc:
            failure = {"severity": "error", "code": None, "message": f"drafter could not parse the document: {exc}"}
            return "drafter", [{**failure, "file": emit_result.files[0].path}]
        else:
            return "drafter", problems
    problems = []
    for emitted in emit_result.files:
        try:
            parse_apiblueprint(str(emitted.content), source_label=emitted.path)
        except ApiblueprintParseError as exc:
            problems.append({"severity": "error", "code": None, "message": str(exc), "file": emitted.path})
    return "reader", problems


def reimport_with_reader(emit_result: EmitResult) -> CanonicalApi:
    """Import an emitted API Blueprint document through the built-in reader and normalizer.

    Args:
        emit_result: The API Blueprint emitter's output; its first file is the document.

    Returns:
        The canonical model.

    Raises:
        ImportSourceError: When the document does not parse or normalize (a malformed shape the
            normalizer trips over is ``INPUT_MALFORMED``).
    """
    root = emit_result.files[0]
    try:
        document = parse_apiblueprint(str(root.content), source_label=root.path)
        return ApiblueprintImportSource().normalize(document, include_raw=False)
    except ApiblueprintParseError as exc:
        raise ImportSourceError(str(exc)) from exc
    except ImportSourceError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ImportSourceError(f"Malformed API Blueprint document: {exc}", code="INPUT_MALFORMED") from exc


def round_trip_apiblueprint(
    api: CanonicalApi, *, emit_result: Optional[EmitResult] = None
) -> ApiblueprintRoundTripReport:
    """Validate the API Blueprint export of ``api``, import it again, and reconcile the difference.

    Args:
        api: The source canonical model.
        emit_result: An emission to use instead of emitting here (the export job already has one).

    Returns:
        The :class:`ApiblueprintRoundTripReport`.
    """
    emitter = ApiblueprintEmitter()
    if emit_result is None:
        emit_result = emitter.emit(api)
    predicted = list(emit_result.losses)
    try:
        validator, problems = validate_emitted_apiblueprint(emit_result)
    except ValueError as exc:
        failure = {"severity": "error", "code": None, "message": str(exc), "file": None}
        return ApiblueprintRoundTripReport(validator="reader", problems=[failure], predicted_losses=predicted)
    if problems:
        return ApiblueprintRoundTripReport(validator=validator, problems=problems, predicted_losses=predicted)
    try:
        reimported = reimport_emitted(ApiblueprintImportSource(), emit_result, multi_file=False)
    except (ImportSourceError, ValueError) as exc:
        return ApiblueprintRoundTripReport(validator=validator, import_error=str(exc), predicted_losses=predicted)
    measured = canonical_diff(api, reimported)
    outcome = reconcile(measured, compute_lossiness_for_emitter(api, emitter))
    return ApiblueprintRoundTripReport(
        validator=validator,
        reimported=True,
        diff=measured,
        unexplained=list(outcome.unexplained),
        overclaims=[item.construct_key for item in outcome.overclaims],
        predicted_losses=predicted,
    )
