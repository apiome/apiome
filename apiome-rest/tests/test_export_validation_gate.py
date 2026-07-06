"""Emitted-artifact validation gating & report — MFX-5.3 (#3854).

Exercises :mod:`app.export_validation_gate`, the gate/report layer on top of MFX-5.1 that
blocks delivery on an invalid artifact, warns when validation was skipped, and surfaces
structured findings alongside the fidelity envelope.
"""

from __future__ import annotations

from app.export_validation import EmittedArtifactValidation, ValidationFinding
from app.export_validation_gate import (
    EmittedValidationReport,
    ValidationVerdict,
    build_validation_report,
)


def test_valid_verdict_does_not_block_or_warn() -> None:
    """A passing re-parse yields ``valid`` with no gate."""
    validation = EmittedArtifactValidation(
        target="openapi-3.1", applicable=True, validated=True, valid=True
    )
    report = build_validation_report(validation)

    assert report.verdict is ValidationVerdict.VALID
    assert report.blocks_delivery is False
    assert report.warns is False
    assert report.tool == "OpenAPI meta-schema + OpenAPI import"
    assert report.headline == "Valid"
    assert "re-parsed cleanly" in report.message


def test_invalid_verdict_blocks_delivery_with_findings() -> None:
    """A rejected artifact blocks delivery and carries structured findings."""
    validation = EmittedArtifactValidation(
        target="openapi-3.1",
        applicable=True,
        validated=True,
        valid=False,
        errors=["'info' is a required property (/)"],
        findings=[ValidationFinding(message="'info' is a required property", path="/")],
    )
    report = build_validation_report(validation)

    assert report.verdict is ValidationVerdict.INVALID
    assert report.blocks_delivery is True
    assert report.warns is False
    assert report.headline == "Invalid — export blocked"
    assert report.findings[0].path == "/"


def test_skipped_verdict_warns_but_does_not_block() -> None:
    """A toolchain skip warns; delivery may proceed."""
    validation = EmittedArtifactValidation(
        target="asyncapi-3",
        applicable=True,
        validated=False,
        valid=True,
        detail="The 'asyncapi-parser' toolchain is unavailable in this runtime.",
    )
    report = build_validation_report(validation)

    assert report.verdict is ValidationVerdict.SKIPPED
    assert report.blocks_delivery is False
    assert report.warns is True
    assert report.tool == "asyncapi-parser"
    assert "asyncapi-parser" in report.message


def test_not_applicable_verdict_stays_out_of_the_way() -> None:
    """The sample no-op target is not applicable and never blocks."""
    validation = EmittedArtifactValidation(
        target="sample-noop",
        applicable=False,
        validated=False,
        valid=True,
        detail="No import parser matches the 'sample-noop' target.",
    )
    report = build_validation_report(validation)

    assert report.verdict is ValidationVerdict.NOT_APPLICABLE
    assert report.blocks_delivery is False
    assert report.warns is False
    assert report.tool is None


def test_report_is_a_stable_pydantic_model() -> None:
    """The report round-trips through ``model_dump`` for poll payloads."""
    validation = EmittedArtifactValidation(
        target="graphql", applicable=True, validated=True, valid=True
    )
    report = build_validation_report(validation)
    restored = EmittedValidationReport.model_validate(report.model_dump())

    assert restored == report
