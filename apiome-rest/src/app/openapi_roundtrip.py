"""OpenAPI emitter validate + round-trip — MFX-9.3 (#3868).

The OpenAPI emitter (:class:`app.openapi_emitter.OpenApiEmitter`, MFX-9.1) converts
a :class:`~app.canonical_model.CanonicalApi` *out* to an OpenAPI 3.1 document (or a
3.0 / Swagger 2.0 downgrade), and the fidelity pack (MFX-9.2) *predicts* what that
projection cannot carry. This module closes the loop by **measuring** what actually
survived: it feeds the emitted artifact back through the matching MFI import parser
and diffs the re-imported model against the source.

It composes three pieces that already exist rather than reimplementing any of them
(the MFX-5.1 / MFX-2.6 directive — *reuse, don't rebuild*):

* **emit** — :class:`app.openapi_emitter.OpenApiEmitter` (MFX-9.1);
* **validate** — :func:`app.openapi_validator.validate_openapi_document` confirms
  an emitted 3.x document is schema-valid against the bundled OpenAPI meta-schema
  (MFI-22.1); *and* a genuine re-parse through
  :class:`app.openapi_import_source.OpenApiImportSource` (MFI-1.1) proves the
  artifact is legal input for its own format — the MFX-5.1 "validate emitted
  artifact" check that catches a buggy emitter's illegal output;
* **round-trip diff** — :func:`app.diff.diff` (MFI-3.2) compares the re-imported
  model against the source, yielding the *empirical* loss list that corroborates
  the *predicted* one (the MFX-2.6 round-trip measurement).

The core statement is the **same-format round-trip is lossless**: a REST /
OpenAPI source emitted to OpenAPI 3.1 and re-imported produces an *empty* entity
diff. When the emitter recorded losses (a downgrade, or a cross-paradigm source
whose constructs OpenAPI cannot carry), the round-trip diff is expected to be
non-empty — and :attr:`RoundTripReport.diverges` flags the cases where prediction
and measurement disagree (predicted lossless yet the diff is non-empty, or vice
versa), the MFX-2.6 "flagged where they diverge" acceptance criterion.

Everything here is pure and side-effect free, so the emitter's tests, the export
job (MFX-EPIC-3), and the CLI/UI target card (MFX-9.4) can share one round-trip
implementation.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from .canonical_model import CanonicalApi
from .diff import ModelDiff, diff
from .emitter import EmitResult, Loss
from .import_source import ImportSourceError
from .openapi_emitter import OpenApiEmitOptions, OpenApiEmitter
from .openapi_import_source import OpenApiImportSource
from .openapi_validator import validate_openapi_document

__all__ = [
    "RoundTripStatus",
    "RoundTripReport",
    "round_trip_openapi",
]


class RoundTripStatus(str, Enum):
    """The outcome of an emit → validate → re-import → diff round trip.

    A single ordered verdict callers can gate on, from worst to best:

    * :attr:`INVALID` — the emitted document failed OpenAPI meta-schema
      validation; the emitter produced structurally illegal output.
    * :attr:`UNPARSEABLE` — the document passed (or skipped) meta-schema
      validation but the matching MFI parser could not re-import it; the artifact
      is not legal input for its own format.
    * :attr:`LOSSY` — the artifact re-imported cleanly, but the re-imported model
      differs from the source (the round-trip lost or altered constructs).
    * :attr:`LOSSLESS` — the artifact re-imported cleanly and the re-imported
      model is entity-for-entity identical to the source (a perfect round trip).
    """

    INVALID = "invalid"
    UNPARSEABLE = "unparseable"
    LOSSY = "lossy"
    LOSSLESS = "lossless"


class RoundTripReport(BaseModel):
    """The result of round-tripping an emitted OpenAPI artifact back to canonical.

    Deterministic for a given source model and emit options, so two round trips of
    the same input compare equal. Combines the MFX-5.1 validation verdict
    (:attr:`schema_errors` + :attr:`reimported`) with the MFX-2.6 empirical loss
    measurement (:attr:`diff`) and the emitter's *predicted* losses
    (:attr:`predicted_losses`) so a caller can confirm the two agree.
    """

    model_config = ConfigDict(extra="forbid")

    openapi_version: str = Field(
        description="The declared version of the emitted document — ``3.1.0`` / "
        "``3.0.3`` for OpenAPI, ``2.0`` for a Swagger downgrade.",
    )
    schema_checked: bool = Field(
        description="Whether OpenAPI meta-schema validation was applicable and run "
        "(true for OpenAPI 3.1 / 3.2, which ship a bundled meta-schema; false for a "
        "3.0 or Swagger 2.0 downgrade — their validation is the re-import parse alone).",
    )
    schema_errors: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Meta-schema validation errors (path/message/keyword). Empty "
        "when the document is schema-valid or when no meta-schema applied.",
    )
    reimported: bool = Field(
        description="Whether the emitted artifact parsed and normalized back into a "
        "canonical model through the matching MFI OpenAPI import parser.",
    )
    import_error: Optional[str] = Field(
        default=None,
        description="The parser's failure message when ``reimported`` is false; "
        "``None`` on a successful re-import.",
    )
    diff: Optional[ModelDiff] = Field(
        default=None,
        description="The structured diff from the source model to the re-imported "
        "model. ``None`` when re-import failed (there is nothing to diff against).",
    )
    predicted_losses: List[Loss] = Field(
        default_factory=list,
        description="The losses the emitter recorded while projecting the source to "
        "OpenAPI (MFI-22.2). Empty when the emitter predicted a lossless conversion.",
    )

    @property
    def valid(self) -> bool:
        """Whether the emitted artifact is legal: schema-clean *and* re-importable.

        The MFX-5.1 acceptance criterion — "valid output passes; deliberately broken
        output is caught". Meta-schema validity alone is insufficient (a document can
        satisfy the meta-schema yet trip the parser), so both checks must hold.
        """
        return not self.schema_errors and self.reimported

    @property
    def empirically_lossless(self) -> bool:
        """Whether the *measured* round trip preserved every itemized entity.

        ``True`` when the artifact re-imported and the source→re-import diff records
        no service/operation/message/channel/type/field change. This is the
        entity-level round-trip guarantee; artifact-level metadata (``version`` /
        ``servers`` / ``identity``) is deliberately outside the diff's categories and
        does not count as a round-trip loss.
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
        predicted-lossless conversion round-trips with an empty diff, and a predicted
        loss shows up as a non-empty diff. ``True`` flags the mismatch — a silent loss
        (predicted lossless, yet the diff is non-empty) or an over-prediction
        (predicted lossy, yet the diff is empty) — so a fixture can assert the two
        corroborate. Always ``False`` when the artifact did not re-import (there is no
        measurement to compare against).
        """
        if self.diff is None:
            return False
        return self.empirically_lossless != self.predicted_lossless

    @property
    def status(self) -> RoundTripStatus:
        """The single ordered verdict for the round trip (see :class:`RoundTripStatus`)."""
        if self.schema_errors:
            return RoundTripStatus.INVALID
        if not self.reimported:
            return RoundTripStatus.UNPARSEABLE
        if self.empirically_lossless:
            return RoundTripStatus.LOSSLESS
        return RoundTripStatus.LOSSY


def _document_version(document: Dict[str, Any]) -> str:
    """Return the declared OpenAPI/Swagger version string of an emitted document."""
    version = document.get("openapi")
    if isinstance(version, str):
        return version
    swagger = document.get("swagger")
    if isinstance(swagger, str):
        return swagger
    return ""


def _has_bundled_meta_schema(document: Dict[str, Any]) -> bool:
    """Whether a bundled OpenAPI meta-schema genuinely covers ``document``.

    Only OpenAPI **3.1** and **3.2** ship a meta-schema
    (:mod:`app.openapi_validator`). A 3.0 downgrade uses draft-4 spellings the
    validator would (incorrectly) judge against the 3.1 meta-schema — boolean
    ``exclusiveMinimum``, ``nullable`` — so it is *not* meta-schema-checked here; nor
    is a Swagger 2.0 downgrade (``swagger: "2.0"``, no OpenAPI meta-schema at all).
    For both older dialects the re-import parse through their own normalizer is the
    validation, matching the MFX-9.1 "re-imports cleanly through its own normalizer"
    round-trip guarantee.
    """
    version = document.get("openapi")
    return isinstance(version, str) and (
        version.startswith("3.1") or version.startswith("3.2")
    )


def round_trip_openapi(
    api: CanonicalApi,
    *,
    opts: Optional[Union[OpenApiEmitOptions, Any]] = None,
    emit_result: Optional[EmitResult] = None,
) -> RoundTripReport:
    """Validate and round-trip the OpenAPI emission of ``api``.

    Emits ``api`` to OpenAPI (unless a pre-computed ``emit_result`` is supplied),
    validates the emitted document, re-imports it through the matching MFI OpenAPI
    parser, and diffs the re-imported model against ``api``. The returned
    :class:`RoundTripReport` carries the validation verdict, the empirical diff, and
    the emitter's predicted losses so a caller can confirm the measured loss matches
    the predicted one.

    Args:
        api: The source canonical model to emit and round-trip.
        opts: Optional emit options selecting the target dialect (``3.1`` default /
            ``3.0`` / ``2.0``). Ignored when ``emit_result`` is supplied.
        emit_result: A pre-computed emission to round-trip instead of emitting here —
            lets a caller that already emitted (the export job) avoid emitting twice.
            When supplied, ``opts`` is not consulted.

    Returns:
        A :class:`RoundTripReport`. When re-import fails, :attr:`RoundTripReport.diff`
        is ``None`` and :attr:`RoundTripReport.import_error` carries the reason.
    """
    if emit_result is None:
        emit_result = OpenApiEmitter().emit(api, opts=opts)

    document = emit_result.document

    schema_checked = _has_bundled_meta_schema(document)
    schema_errors = validate_openapi_document(document) if schema_checked else []

    # Re-import through the real MFI parser via the serialized wire format, so the
    # round trip exercises exactly the path a user re-importing the file would hit
    # (and catches any non-JSON-serializable content the emitter should never emit).
    source = OpenApiImportSource()
    reimported_model: Optional[CanonicalApi] = None
    import_error: Optional[str] = None
    try:
        parsed = source.parse(json.dumps(document))
        reimported_model = source.normalize(parsed, include_raw=False)
    except (ImportSourceError, ValueError, TypeError) as exc:
        import_error = str(exc)

    round_trip_diff = diff(api, reimported_model) if reimported_model is not None else None

    return RoundTripReport(
        openapi_version=_document_version(document),
        schema_checked=schema_checked,
        schema_errors=schema_errors,
        reimported=reimported_model is not None,
        import_error=import_error,
        diff=round_trip_diff,
        predicted_losses=list(emit_result.losses),
    )
