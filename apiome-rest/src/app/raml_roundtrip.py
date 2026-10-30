"""RAML emitter validate + round-trip (AMF) — MFX-17.3 (#3903).

The RAML emitter (:class:`app.raml_emitter.RamlEmitter`, MFX-17.1) writes a RAML 1.0 document, and
its fidelity report *predicts* what RAML cannot carry. This module validates the export with AMF —
the RAML authority the import already runs (MFI-15.1 / 15.3) — and then **measures** what survived
by importing it again and comparing it with the source:

* **validate** — :func:`app.raml_amf.validate_raml_set_with_amf` checks the document against AMF's
  RAML 1.0 profile; each ``Violation`` makes the export **invalid**, warnings and infos do not. When
  this runtime has no AMF, the RAML reader (:func:`app.raml_parser.parse_raml`) parses the document
  instead — a parse error is the violation — and :attr:`RamlRoundTripReport.validator` says which ran;
* **re-import** — the document goes through :class:`app.raml_import_source.RamlImportSource`, the path
  a user uploading it would hit (AMF-resolved when AMF is present); a failure is **unparseable**;
* **diff** — :func:`app.import_source.canonical_diff` compares the source with the re-imported model,
  by stable key;
* **reconcile** — :func:`app.roundtrip_matrix.reconcile` joins every difference to the fidelity
  finding that explains it (MFX-2.6). An *unexplained* difference is a silent loss; an *overclaim* is
  a construct the report called preserved that changed.

A RAML source round-trips with no difference; any other REST source loses what RAML cannot say, and
the reconciliation shows which of those losses the fidelity report already names.

The export gate (:mod:`app.export_validation`) runs the validation plus a re-import through the
pure-Python reader (:func:`reimport_with_reader`): the emitter writes one self-contained document,
so the reader needs no AMF, and AMF has already validated it. AMF runs as a JVM subprocess; call
these off the event loop.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from . import raml_amf
from .canonical_model import CanonicalApi
from .emitter import EmitResult, Loss
from .fidelity_engine import compute_lossiness_for_emitter
from .import_source import CanonicalDiff, CanonicalDiffEntry, ImportSourceError, canonical_diff
from .raml_emitter import RamlEmitter
from .raml_import_source import RamlImportSource
from .raml_parser import RamlParseError, parse_raml
from .roundtrip_matrix import reconcile, reimport_emitted

__all__ = [
    "RamlRoundTripReport",
    "RoundTripStatus",
    "reimport_with_reader",
    "round_trip_raml",
    "validate_emitted_raml",
]

#: Which check validated the document.
Validator = Literal["amf", "reader"]


class RoundTripStatus(str, Enum):
    """The outcome of an emit → validate → re-import → diff round trip, worst first.

    * :attr:`INVALID` — AMF reported a ``Violation`` (or, without AMF, the reader could not parse it).
    * :attr:`UNPARSEABLE` — it validated, but does not import.
    * :attr:`LOSSY` — it imports, and differs from the source.
    * :attr:`LOSSLESS` — it imports, and matches the source entity for entity.
    """

    INVALID = "invalid"
    UNPARSEABLE = "unparseable"
    LOSSY = "lossy"
    LOSSLESS = "lossless"


class RamlRoundTripReport(BaseModel):
    """What validating and round-tripping one RAML export found."""

    model_config = ConfigDict(extra="forbid")

    validator: Validator = Field(description="``amf`` when AMF validated the document, else ``reader``.")
    violations: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="The ``Violation`` results (``message``, ``file``, ``line``, ``column``, ``constraint``).",
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
        """Whether the document validated **and** imported again."""
        return not self.violations and self.reimported

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
        if self.violations:
            return RoundTripStatus.INVALID
        if not self.reimported:
            return RoundTripStatus.UNPARSEABLE
        if self.empirically_lossless:
            return RoundTripStatus.LOSSLESS
        return RoundTripStatus.LOSSY


def validate_emitted_raml(emit_result: EmitResult) -> Tuple[Validator, List[Dict[str, Any]]]:
    """Validate an emitted RAML document with AMF, or with the reader when AMF is absent.

    Args:
        emit_result: The RAML emitter's output; its first file is the root document.

    Returns:
        ``(validator, violations)``: which check ran, and its ``Violation`` results — each a dict with
        ``message`` and ``file`` and, from AMF, ``line``, ``column`` and ``constraint``. Empty when the
        document is valid. Warnings and infos are not violations.

    Raises:
        ImportSourceError: When AMF ran but could not validate the set for another reason (a path
            leaving the set, a timeout).
        ValueError: When the export wrote no file.
    """
    if not emit_result.files:
        raise ValueError("The RAML export wrote no file.")
    root = emit_result.files[0].path
    members = {emitted.path: str(emitted.content) for emitted in emit_result.files}
    if raml_amf.amf_available():
        try:
            results = raml_amf.validate_raml_set_with_amf(members, root)
        except ImportSourceError as exc:
            if exc.code != "ADAPTER_UNAVAILABLE":
                raise
        else:
            violations = [
                {**result, "file": result.get("file") or root}
                for result in results
                if result.get("severity") == "Violation"
            ]
            return "amf", violations
    try:
        parse_raml(members[root], source_label=root)
    except RamlParseError as exc:
        return "reader", [{"severity": "Violation", "message": str(exc), "file": root}]
    return "reader", []


def reimport_with_reader(emit_result: EmitResult) -> CanonicalApi:
    """Import an emitted RAML document through the pure-Python reader and the RAML normalizer.

    Args:
        emit_result: The RAML emitter's output (one self-contained document).

    Returns:
        The canonical model.

    Raises:
        ImportSourceError: When the document does not parse or normalize.
    """
    root = emit_result.files[0]
    try:
        document = parse_raml(str(root.content), source_label=root.path)
        return RamlImportSource().normalize(document, include_raw=False)
    except RamlParseError as exc:
        raise ImportSourceError(str(exc)) from exc
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ImportSourceError(f"Malformed RAML document: {exc}", code="INPUT_MALFORMED") from exc


def round_trip_raml(api: CanonicalApi, *, emit_result: Optional[EmitResult] = None) -> RamlRoundTripReport:
    """Validate the RAML export of ``api``, import it again, and reconcile the difference.

    Args:
        api: The source canonical model.
        emit_result: An emission to use instead of emitting here (the export job already has one).

    Returns:
        The :class:`RamlRoundTripReport`.
    """
    emitter = RamlEmitter()
    if emit_result is None:
        emit_result = emitter.emit(api)
    predicted = list(emit_result.losses)
    try:
        validator, violations = validate_emitted_raml(emit_result)
    except (ImportSourceError, ValueError) as exc:
        root = emit_result.files[0].path if emit_result.files else None
        failure = {"severity": "Violation", "message": str(exc), "file": root}
        return RamlRoundTripReport(validator="amf", violations=[failure], predicted_losses=predicted)
    if violations:
        return RamlRoundTripReport(validator=validator, violations=violations, predicted_losses=predicted)
    try:
        reimported = reimport_emitted(RamlImportSource(), emit_result, multi_file=len(emit_result.files) > 1)
    except (ImportSourceError, ValueError) as exc:
        return RamlRoundTripReport(validator=validator, import_error=str(exc), predicted_losses=predicted)
    measured = canonical_diff(api, reimported)
    outcome = reconcile(measured, compute_lossiness_for_emitter(api, emitter))
    return RamlRoundTripReport(
        validator=validator,
        reimported=True,
        diff=measured,
        unexplained=list(outcome.unexplained),
        overclaims=[item.construct_key for item in outcome.overclaims],
        predicted_losses=predicted,
    )
