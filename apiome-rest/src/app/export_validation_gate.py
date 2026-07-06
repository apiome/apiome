"""Emitted-artifact validation gating & report — MFX-5.3 (#3854).

MFX-5.1 (:mod:`app.export_validation`) re-parses an emitted artifact through its matching
MFI import parser and records whether it is legal in its target format. This module is the
**gate and report** layer on top of that verdict — the export UX surface (MFX-6.4, MFX-42.x)
reads :class:`EmittedValidationReport` alongside the fidelity envelope to decide whether
delivery may proceed and to render parser/toolchain detail.

**The four verdicts** (:class:`ValidationVerdict`):

* ``valid`` — the artifact re-parsed cleanly; delivery proceeds;
* ``invalid`` — a validator ran and rejected the artifact; delivery is **blocked**;
* ``skipped`` — a matching parser exists but its toolchain was unavailable, so the artifact
  was not re-validated here; delivery proceeds but the report **warns** (a possibly-valid
  export ships without this guarantee);
* ``not_applicable`` — no importer matches the format (the sample no-op target); the gate
  stays out of the way.

The report carries structured :class:`~app.export_validation.ValidationFinding` rows (message,
JSON-pointer path, bundle file, line/column when the validator provides them, tool identity)
so UIs can render actionable errors without scraping free-form strings. Everything is derived
purely from the MFX-5.1 :class:`~app.export_validation.EmittedArtifactValidation`, so the
report a completed job poll carries and the gate the pipeline enforces agree for the same
inputs.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .export_validation import EmittedArtifactValidation, ValidationFinding

__all__ = [
    "ValidationVerdict",
    "EmittedValidationReport",
    "build_validation_report",
    "TOOL_BY_TARGET",
]


class ValidationVerdict(str, Enum):
    """The band an emitted-artifact validation falls into (MFX-5.3).

    Ordered from safest to worst for UI gating: ``valid`` needs no attention,
    ``invalid`` blocks delivery, ``skipped`` warns but does not block,
    ``not_applicable`` means there was nothing to validate.
    """

    VALID = "valid"
    INVALID = "invalid"
    SKIPPED = "skipped"
    NOT_APPLICABLE = "not_applicable"


# Human-facing tool identity per emitter ``format`` key — what actually ran (or would have).
TOOL_BY_TARGET: Dict[str, str] = {
    "openapi-3.1": "OpenAPI meta-schema + OpenAPI import",
    "graphql": "graphql-core",
    "asyncapi-3": "asyncapi-parser",
    "avro": "fastavro",
    "proto3": "buf build",
}


class EmittedValidationReport(BaseModel):
    """The validation gate + structured report for one emitted artifact (MFX-5.3).

    Pairs the coarse :class:`ValidationVerdict` with structured findings and ready-to-render
    :attr:`headline` / :attr:`message` copy. The single gate export surfaces read is
    :attr:`blocks_delivery` (``True`` only for ``invalid``) and :attr:`warns` (``True`` only
    for ``skipped``).
    """

    model_config = ConfigDict(extra="forbid")

    verdict: ValidationVerdict = Field(
        description="The validation band: valid / invalid / skipped / not_applicable.",
    )
    target: str = Field(
        description="The resolved target format key that was validated (e.g. ``openapi-3.1``).",
    )
    tool: Optional[str] = Field(
        default=None,
        description="The validator identity that ran (or would have run) for this target.",
    )
    applicable: bool = Field(
        description="Whether a matching MFI import parser is registered for this format.",
    )
    validated: bool = Field(
        description="Whether validation actually ran in this runtime.",
    )
    valid: bool = Field(
        description="Whether the emitted artifact re-parsed cleanly when validation ran.",
    )
    blocks_delivery: bool = Field(
        description="Whether the export job must fail before packaging/delivery. "
        "``True`` only when a validator ran and rejected the artifact.",
    )
    warns: bool = Field(
        description="Whether the report should surface a warning (toolchain unavailable). "
        "``True`` only for a ``skipped`` verdict.",
    )
    findings: List[ValidationFinding] = Field(
        default_factory=list,
        description="Structured parser/toolchain failures. Empty on a passing or skipped run.",
    )
    detail: Optional[str] = Field(
        default=None,
        description="Why validation did not run (not applicable, or toolchain unavailable).",
    )
    headline: str = Field(description="Short banner heading for the validation gate.")
    message: str = Field(
        description="The full, ready-to-display validation sentence. Render verbatim.",
    )


def _verdict_for(validation: EmittedArtifactValidation) -> ValidationVerdict:
    """Map an MFX-5.1 validation into the MFX-5.3 verdict band."""
    if not validation.applicable:
        return ValidationVerdict.NOT_APPLICABLE
    if not validation.validated:
        return ValidationVerdict.SKIPPED
    if validation.valid:
        return ValidationVerdict.VALID
    return ValidationVerdict.INVALID


def _headline_and_message(
    verdict: ValidationVerdict, target: str, *, detail: Optional[str], error_count: int
) -> tuple[str, str]:
    """Ready-to-render copy for each validation band."""
    label = target
    if verdict is ValidationVerdict.VALID:
        return (
            "Valid",
            f"The emitted {label!r} artifact re-parsed cleanly through its matching import parser.",
        )
    if verdict is ValidationVerdict.INVALID:
        noun = "error" if error_count == 1 else "errors"
        return (
            "Invalid — export blocked",
            f"The emitted {label!r} artifact failed re-validation ({error_count} {noun}). "
            "The export was blocked before delivery.",
        )
    if verdict is ValidationVerdict.SKIPPED:
        reason = detail or f"The {label!r} validator could not run in this runtime."
        return (
            "Validation skipped",
            f"{reason} The export proceeded without an emitted-artifact guarantee.",
        )
    return (
        "Not applicable",
        detail
        or f"No import parser matches the {label!r} target; the emitted artifact was not re-validated.",
    )


def build_validation_report(validation: EmittedArtifactValidation) -> EmittedValidationReport:
    """Build the validation gate + report from an MFX-5.1 verdict (MFX-5.3).

    Args:
        validation: The uniform emitted-artifact validation the export job computed after emit.

    Returns:
        An :class:`EmittedValidationReport` whose :attr:`blocks_delivery` mirrors
        :attr:`~app.export_validation.EmittedArtifactValidation.failed`.
    """
    verdict = _verdict_for(validation)
    headline, message = _headline_and_message(
        verdict,
        validation.target,
        detail=validation.detail,
        error_count=len(validation.findings) or len(validation.errors),
    )
    return EmittedValidationReport(
        verdict=verdict,
        target=validation.target,
        tool=TOOL_BY_TARGET.get(validation.target),
        applicable=validation.applicable,
        validated=validation.validated,
        valid=validation.valid,
        blocks_delivery=validation.failed,
        warns=verdict is ValidationVerdict.SKIPPED,
        findings=list(validation.findings),
        detail=validation.detail,
        headline=headline,
        message=message,
    )
