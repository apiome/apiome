"""OWASP MCP Top 10 catalog and coverage (CLX-3.2, #4856).

The catalog's honesty test is :func:`coverage_summary` reporting *uncovered* risks: a risk with no
rule must be reported as uncovered, never silently omitted, so a reader never infers that an
unmentioned risk is one the server does not have.
"""

from __future__ import annotations

import pytest

from app.mcp_owasp import (
    RISK_IDS,
    UnknownRiskError,
    catalog,
    coverage_summary,
    risk_titles,
    validate_risk_ids,
)


def test_catalog_has_ten_risks_in_stable_order():
    ids = [r["risk_id"] for r in catalog()]
    assert ids == sorted(ids)
    assert len(ids) == 10
    assert ids[0] == "MCP01" and ids[-1] == "MCP10"


def test_validate_rejects_unknown_risk():
    with pytest.raises(UnknownRiskError):
        validate_risk_ids(["MCP01", "MCP99"])


def test_validate_dedupes_and_sorts():
    assert validate_risk_ids(["MCP03", "MCP01", "MCP01"]) == ("MCP01", "MCP03")


def test_coverage_reports_uncovered():
    # Rules covering only two risks -> the other eight are reported uncovered, not hidden.
    summary = coverage_summary([["MCP01"], ["MCP06"]])
    assert set(summary["covered"]) == {"MCP01", "MCP06"}
    assert len(summary["uncovered"]) == 8
    assert set(summary["covered"]) | set(summary["uncovered"]) == set(RISK_IDS)


def test_coverage_counts_rules_per_risk():
    summary = coverage_summary([["MCP01"], ["MCP01"], ["MCP06"]])
    assert summary["rules_per_risk"]["MCP01"] == 2
    assert summary["rules_per_risk"]["MCP06"] == 1


def test_risk_titles_skip_unknown():
    titles = risk_titles(["MCP01", "MCP99"])
    assert len(titles) == 1
