"""Tests for the conversion result formatter (MFI-22.6).

Pins the pure presentation helpers the ``convert`` command uses: the fidelity headline + the
mandatory warning, the gap listing, the commit ids line, and the low-tier detection that drives the
command's non-zero exit hint. No HTTP, no typer.
"""

from __future__ import annotations

from apiome_cli.client.conversion_output import (
    CONVERSION_WARNING_SENTENCE,
    format_conversion_summary,
    is_low_tier,
    report_tier,
)


def _report(tier: str = "medium", *, items=None, losses=None) -> dict:
    return {
        "score": 74,
        "grade": "C",
        "tier": tier,
        "items": items or [],
        "losses": losses or [],
        "coverage_counts": {},
        "penalty": 26,
    }


def test_report_tier_and_low_tier_detection():
    assert report_tier({"tier": "LOW"}) == "low"
    assert is_low_tier(_report("low")) is True
    assert is_low_tier(_report("medium")) is False
    assert is_low_tier({}) is False


def test_summary_headline_and_warning_for_dry_run():
    lines = format_conversion_summary(
        {"report": _report(), "target": "openapi", "sourceFormat": "graphql"},
        committed=False,
    )
    assert any("fidelity C (74/100), tier medium" in line for line in lines)
    assert CONVERSION_WARNING_SENTENCE in lines
    # A dry-run never claims a project was created.
    assert not any("into project" in line for line in lines)


def test_summary_lists_gap_constructs_only():
    report = _report(
        items=[
            {"title": "Responses", "coverage": "present", "reason": "carried"},
            {"title": "Servers", "coverage": "missing", "reason": "source declares no servers"},
            {"title": "Security", "coverage": "n/a", "reason": "no OpenAPI form"},
        ],
    )
    lines = format_conversion_summary({"report": report, "target": "openapi"}, committed=False)
    text = "\n".join(lines)
    assert "Servers [missing]" in text
    assert "Security [n/a]" in text
    # 'present' constructs are not listed as gaps.
    assert "Responses" not in text


def test_summary_reports_projection_losses_count():
    report = _report(losses=[{"kind": "n/a", "subject": "graphql-subscription", "detail": "x"}])
    lines = format_conversion_summary({"report": report, "target": "openapi"}, committed=False)
    assert any("Projection losses: 1" in line for line in lines)


def test_summary_commit_reports_created_ids():
    response = {
        "report": _report(),
        "projectId": "proj-9",
        "versionId": "1.0.0",
        "reconverted": False,
    }
    lines = format_conversion_summary(response, committed=True)
    assert any("Converted into project proj-9 version 1.0.0" in line for line in lines)


def test_summary_commit_reconvert_wording():
    response = {"report": _report(), "projectId": "p", "versionId": "1.0.1", "reconverted": True}
    lines = format_conversion_summary(response, committed=True)
    assert any(line.startswith("Re-converted into project") for line in lines)


def test_summary_low_tier_adds_force_hint():
    lines = format_conversion_summary({"report": _report("low"), "target": "openapi"}, committed=False)
    assert any("Low fidelity" in line and "--force" in line for line in lines)


def test_summary_without_report_is_graceful():
    lines = format_conversion_summary({"projectId": "p"}, committed=True)
    assert lines == ["Conversion completed, but no fidelity report was returned."]
