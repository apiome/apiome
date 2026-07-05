"""GraphQL emitter validate + round-trip — MFX-13.4 (#3887).

The GraphQL emitter (:class:`app.graphql_emitter.GraphQlEmitter`, MFX-13.1) converts
a :class:`~app.canonical_model.CanonicalApi` *out* to GraphQL SDL, and the fidelity pack
(:class:`~app.graphql_emitter.GraphQlFidelityRulePack`, MFX-13.3) *predicts* what that
projection cannot carry — HTTP method/path/status when reframing REST operations to
Query/Mutation fields, validation constraints approximated as custom scalars. This module
closes the loop by **measuring** what actually survived: it feeds the emitted SDL back
through the matching MFI GraphQL parser and diffs the re-imported model against the source,
the GraphQL analogue of :mod:`app.openapi_roundtrip` (MFX-9.3).

It composes three pieces that already exist rather than reimplementing any of them
(the MFX-5.1 / MFX-2.6 directive — *reuse, don't rebuild*):

* **emit** — :class:`app.graphql_emitter.GraphQlEmitter` (MFX-13.1);
* **validate** — :func:`app.graphql_parser.parse_graphql` (MFI-10.1) parses the emitted
  SDL, merges when needed, builds a ``graphql-core`` schema, and runs ``validate_schema``
  — the ``build_schema`` validation the acceptance criteria names;
* **re-import** — :class:`app.graphql_import_source.GraphQlImportSource` (MFI-10.6)
  parses and :class:`app.graphql_normalizer.GraphQlNormalizer` (MFI-10.2) normalizes
  the built schema back into a canonical model — the exact path a user re-importing the
  file would hit;
* **round-trip diff** — :func:`app.diff.diff` (MFI-3.2) compares the re-imported model
  against the source, yielding the *empirical* loss list that corroborates the
  *predicted* one (the MFX-2.6 round-trip measurement).

The core statement is the **same-format round-trip is lossless**: a Graph-native source
emitted to GraphQL SDL and re-imported produces an *empty* entity diff (the fixed-point
property MFX-13.1 already proves for ``normalize ∘ emit``, here proven end to end through
the real parser). When the emitter recorded losses (a cross-paradigm REST source whose
HTTP semantics and request bodies are reframed), the round-trip diff is expected to be
non-empty — and :attr:`RoundTripReport.diverges` flags the cases where prediction and
measurement disagree (predicted lossless yet the diff is non-empty, or vice versa), the
MFX-2.6 "flagged where they diverge" acceptance criterion.

Everything here is pure and side-effect free (pure Python via ``graphql-core`` — no Node
subprocess), so the emitter's tests, the export job (MFX-EPIC-3), and the CLI/UI target
card (MFX-13.5) can share one round-trip implementation.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from .canonical_model import CanonicalApi
from .diff import ModelDiff, diff
from .emitter import EmitOptions, EmitResult, Loss
from .graphql_emitter import GraphQlEmitOptions, GraphQlEmitter
from .graphql_import_source import GraphQlImportSource
from .graphql_parser import GraphQlDiagnostic, parse_graphql
from .import_source import ImportSourceError

__all__ = [
    "RoundTripStatus",
    "RoundTripReport",
    "round_trip_graphql",
]


class RoundTripStatus(str, Enum):
    """The outcome of an emit → validate → re-import → diff round trip.

    A single ordered verdict callers can gate on, from worst to best:

    * :attr:`INVALID` — the emitted SDL failed ``build_schema`` / ``validate_schema``
      (the MFI-10.1 parser reported at least one error diagnostic); the emitter produced
      structurally illegal output.
    * :attr:`UNPARSEABLE` — the SDL validated but the GraphQL normalizer could not map
      it back into a canonical model; the artifact is not legal input for its own
      re-import path.
    * :attr:`LOSSY` — the artifact re-imported cleanly, but the re-imported model differs
      from the source (the round-trip lost or altered constructs).
    * :attr:`LOSSLESS` — the artifact re-imported cleanly and the re-imported model is
      entity-for-entity identical to the source (a perfect round trip).
    """

    INVALID = "invalid"
    UNPARSEABLE = "unparseable"
    LOSSY = "lossy"
    LOSSLESS = "lossless"


class RoundTripReport(BaseModel):
    """The result of round-tripping an emitted GraphQL SDL artifact back to canonical.

    Deterministic for a given source model and emit options, so two round trips of the
    same input compare equal. Combines the MFX-5.1 validation verdict
    (:attr:`validation_errors` + :attr:`reimported`) with the MFX-2.6 empirical loss
    measurement (:attr:`diff`) and the emitter's *predicted* losses
    (:attr:`predicted_losses`) so a caller can confirm the two agree.
    """

    model_config = ConfigDict(extra="forbid")

    validation_errors: List[Dict[str, str]] = Field(
        default_factory=list,
        description="The error-severity MFI-10.1 parser diagnostics (severity/message/"
        "source/locations) that render the emitted SDL invalid GraphQL. Empty when the "
        "document validated cleanly.",
    )
    reimported: bool = Field(
        description="Whether the emitted artifact parsed, built, and normalized back into "
        "a canonical model through the matching MFI GraphQL import path.",
    )
    import_error: Optional[str] = Field(
        default=None,
        description="The normalizer's failure message when ``reimported`` is false "
        "despite a valid schema; ``None`` on a successful re-import.",
    )
    diff: Optional[ModelDiff] = Field(
        default=None,
        description="The structured diff from the source model to the re-imported model. "
        "``None`` when re-import failed (there is nothing to diff against).",
    )
    predicted_losses: List[Loss] = Field(
        default_factory=list,
        description="The losses the emitter recorded while projecting the source to "
        "GraphQL (MFI-22.2). Empty when the emitter predicted a lossless conversion.",
    )

    @property
    def valid(self) -> bool:
        """Whether the emitted artifact is legal: validation-clean *and* re-importable.

        The MFX-5.1 acceptance criterion — "valid output passes; deliberately broken
        output is caught". A document can satisfy ``validate_schema`` yet still trip the
        normalizer, so both checks must hold.
        """
        return not self.validation_errors and self.reimported

    @property
    def empirically_lossless(self) -> bool:
        """Whether the *measured* round trip preserved every itemized entity.

        ``True`` when the artifact re-imported and the source→re-import diff records no
        service/operation/message/channel/type/field change. This is the entity-level
        round-trip guarantee; artifact-level metadata (``version`` / ``servers`` /
        ``identity``) is deliberately outside the diff's categories and does not count as
        a round-trip loss.
        """
        return self.diff is not None and self.diff.is_empty()

    @property
    def predicted_lossless(self) -> bool:
        """Whether the emitter *predicted* a lossless conversion (no recorded losses)."""
        return not self.predicted_losses

    @property
    def diverges(self) -> bool:
        """Whether prediction and measurement disagree (the MFX-2.6 divergence flag).

        For a re-importable artifact, prediction and measurement should agree: a
        predicted-lossless conversion round-trips with an empty diff, and a predicted loss
        shows up as a non-empty diff. ``True`` flags the mismatch — a silent loss
        (predicted lossless, yet the diff is non-empty) or an over-prediction (predicted
        lossy, yet the diff is empty) — so a fixture can assert the two corroborate.
        Always ``False`` when the artifact did not re-import (there is no measurement to
        compare against).
        """
        if self.diff is None:
            return False
        return self.empirically_lossless != self.predicted_lossless

    @property
    def status(self) -> RoundTripStatus:
        """The single ordered verdict for the round trip (see :class:`RoundTripStatus`)."""
        if self.validation_errors:
            return RoundTripStatus.INVALID
        if not self.reimported:
            return RoundTripStatus.UNPARSEABLE
        if self.empirically_lossless:
            return RoundTripStatus.LOSSLESS
        return RoundTripStatus.LOSSY


def _diagnostic_dict(diagnostic: GraphQlDiagnostic) -> Dict[str, str]:
    """Flatten one parser diagnostic into a serializable dict."""
    locations = (
        "; ".join(f"{loc.line}:{loc.column}" for loc in diagnostic.locations)
        if diagnostic.locations
        else ""
    )
    return {
        "severity": diagnostic.severity,
        "message": diagnostic.message,
        "source": diagnostic.source or "",
        "locations": locations,
    }


def _sdl_from_emit_result(emit_result: EmitResult) -> str:
    """Return the primary SDL text from an :class:`~app.emitter.EmitResult`."""
    if not emit_result.files:
        return ""
    content = emit_result.files[0].content
    return content if isinstance(content, str) else ""


def round_trip_graphql(
    api: CanonicalApi,
    *,
    opts: Optional[Union[GraphQlEmitOptions, EmitOptions]] = None,
    emit_result: Optional[EmitResult] = None,
) -> RoundTripReport:
    """Validate and round-trip the GraphQL emission of ``api``.

    Emits ``api`` to GraphQL SDL (unless a pre-computed ``emit_result`` is supplied),
    validates the emitted SDL through the MFI-10.1 ``build_schema`` pipeline, re-imports
    it through the GraphQL import source and normalizer, and diffs the re-imported model
    against ``api``. The returned :class:`RoundTripReport` carries the validation verdict,
    the empirical diff, and the emitter's predicted losses so a caller can confirm the
    measured loss matches the predicted one.

    Args:
        api: The source canonical model to emit and round-trip.
        opts: Optional emit options. Ignored when ``emit_result`` is supplied.
        emit_result: A pre-computed emission to round-trip instead of emitting here —
            lets a caller that already emitted (the export job) avoid emitting twice.
            When supplied, ``opts`` is not consulted.

    Returns:
        A :class:`RoundTripReport`. When the emitted SDL fails validation,
        :attr:`RoundTripReport.validation_errors` is non-empty and the status is
        :attr:`RoundTripStatus.INVALID`; when it validates but does not normalize,
        :attr:`RoundTripReport.import_error` carries the reason.
    """
    if emit_result is None:
        try:
            emit_result = GraphQlEmitter().emit(api, opts=opts)
        except ValueError as exc:
            return RoundTripReport(
                validation_errors=[
                    {"severity": "error", "message": str(exc), "source": "", "locations": ""}
                ],
                reimported=False,
                import_error=None,
                diff=None,
                predicted_losses=[],
            )

    sdl = _sdl_from_emit_result(emit_result)

    # Validate through the real MFI parser — parse → merge → build_schema → validate_schema.
    parse_result = parse_graphql(sdl)
    validation_errors = [_diagnostic_dict(d) for d in parse_result.errors]

    reimported_model: Optional[CanonicalApi] = None
    import_error: Optional[str] = None
    if parse_result.ok:
        source = GraphQlImportSource()
        try:
            schema = source.parse(sdl)
            reimported_model = source.normalize(schema, include_raw=False)
        except (ImportSourceError, ValueError, KeyError, TypeError) as exc:
            import_error = str(exc)

    round_trip_diff = (
        diff(api, reimported_model) if reimported_model is not None else None
    )

    return RoundTripReport(
        validation_errors=validation_errors,
        reimported=reimported_model is not None,
        import_error=import_error,
        diff=round_trip_diff,
        predicted_losses=list(emit_result.losses),
    )
