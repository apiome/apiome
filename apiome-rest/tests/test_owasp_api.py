"""OWASP API Security Top 10 (2023) catalog — ASP-1.3 (#5921).

Pins :mod:`app.owasp_api`: the ten category ids in published order (``API10`` last, not
lexically second), validation that fails loudly on an unknown id, and the coverage summary
that names uncovered categories instead of implying they are clean.
"""

from __future__ import annotations

import pytest

from app.owasp_api import (
    CATALOG_REFERENCE,
    CATALOG_REVISION,
    RISK_IDS,
    RISKS,
    UnknownRiskError,
    catalog,
    coverage_summary,
    risk_titles,
    validate_risk_ids,
)


def test_catalog_has_the_ten_categories_in_published_order():
    assert RISK_IDS == tuple(f"API{n}" for n in range(1, 11))
    assert RISK_IDS[-1] == "API10"  # published order, not lexical order
    assert CATALOG_REVISION == "2023"
    assert CATALOG_REFERENCE.startswith("https://owasp.org/API-Security/editions/2023/")


def test_every_category_is_fully_described_with_an_edition_reference():
    for risk_id in RISK_IDS:
        risk = RISKS[risk_id]
        assert risk.risk_id == risk_id
        assert risk.title.strip()
        assert risk.description.strip()
        assert risk.reference.startswith("https://owasp.org/API-Security/editions/2023/en/0xa")
        assert risk.as_dict() == {
            "risk_id": risk_id,
            "title": risk.title,
            "description": risk.description,
            "reference": risk.reference,
        }


def test_catalog_payload_follows_catalog_order():
    assert [entry["risk_id"] for entry in catalog()] == list(RISK_IDS)


def test_validate_risk_ids_dedupes_and_orders_by_catalog():
    assert validate_risk_ids(["API8", "API2", "API8", "API10", "API1"]) == (
        "API1",
        "API2",
        "API8",
        "API10",
    )
    assert validate_risk_ids([]) == ()


def test_validate_risk_ids_rejects_unknown_ids_loudly():
    with pytest.raises(UnknownRiskError) as excinfo:
        validate_risk_ids(["API2", "API11"])
    assert excinfo.value.risk_id == "API11"
    assert "API11" in str(excinfo.value)


def test_risk_titles_skip_unknown_ids_and_follow_catalog_order():
    assert risk_titles(["API10", "nope", "API1"]) == [
        RISKS["API1"].title,
        RISKS["API10"].title,
    ]


def test_coverage_summary_names_the_gaps():
    summary = coverage_summary([("API2",), ("API2", "API8"), ("API10",), ("nope",)])
    assert summary["revision"] == CATALOG_REVISION
    assert summary["reference"] == CATALOG_REFERENCE
    assert summary["covered"] == ["API2", "API8", "API10"]
    assert summary["uncovered"] == ["API1", "API3", "API4", "API5", "API6", "API7", "API9"]
    assert summary["rules_per_risk"] == {"API2": 2, "API8": 1, "API10": 1}


def test_coverage_summary_with_no_rules_covers_nothing():
    summary = coverage_summary([])
    assert summary["covered"] == []
    assert summary["uncovered"] == list(RISK_IDS)
    assert summary["rules_per_risk"] == {}
