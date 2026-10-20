"""Security score for catalog revisions — ASP-1.3 (#5921).

Pins :mod:`app.security_score`: the weighted, per-rule-capped formula and its published
constants, the per-rule weight table (public through the rule catalog and generated into the
docs), and the per-OWASP-category sub-scores whose coverage reads ``none`` — never 100 —
when no rule of a category evaluated.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app import security_score
from app.axis_score import ALGORITHM_DOCS_PAGE
from app.owasp_api import RISK_IDS, UnknownRiskError
from app.schema_lint import PER_RULE_PENALTY_CAP, SEVERITY_PENALTY
from app.security_score import (
    DEFAULT_SECURITY_RULE_WEIGHT,
    SECURITY_RULE_WEIGHTS,
    OwaspSubScore,
    evaluate_security_findings,
    grade_for_score,
    owasp_subscores,
    published_weights,
    rule_owasp_ids,
    rules_by_owasp_risk,
    security_rule_weight,
    security_score_from_finding_dicts,
    weighted_penalty_by_rule,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

WRITE_AUTH = "security.write-operation-missing-auth"
CREDS_IN_URL = "security.credentials-in-server-url"
UNWEIGHTED = "security.http-server-url"


def _finding(rule: str, severity: str = "error") -> dict:
    return {"rule": rule, "category": "security", "severity": severity, "message": rule}


# --- Constants and weights ----------------------------------------------------------------------


def test_house_constants_are_the_published_ones():
    assert SEVERITY_PENALTY == {"error": 10.0, "warning": 4.0, "info": 1.0}
    assert PER_RULE_PENALTY_CAP == 20.0
    assert DEFAULT_SECURITY_RULE_WEIGHT == 1.0


def test_weight_two_rules_are_exactly_the_four_published_ones():
    assert SECURITY_RULE_WEIGHTS == {
        "security.write-operation-missing-auth": 2.0,
        "security.credentials-in-server-url": 2.0,
        "security.secret-in-document": 2.0,
        "security.pii-exposed-without-auth": 2.0,
    }
    for rule_id in SECURITY_RULE_WEIGHTS:
        assert security_rule_weight(rule_id) == 2.0
    assert security_rule_weight(UNWEIGHTED) == DEFAULT_SECURITY_RULE_WEIGHT
    assert security_rule_weight("naming.schema-pascal-case") == DEFAULT_SECURITY_RULE_WEIGHT


# --- The formula --------------------------------------------------------------------------------


def test_one_error_from_a_weight_two_rule_scores_exactly_80_and_grades_b():
    """Acceptance criterion: 100 − min(20, 10 × 2) = 80 → B."""
    score = security_score_from_finding_dicts([_finding(WRITE_AUTH)])
    assert score == 80
    assert grade_for_score(score) == "B"


def test_default_weight_rules_use_the_plain_severity_penalties():
    assert security_score_from_finding_dicts([_finding(UNWEIGHTED, "error")]) == 90
    assert security_score_from_finding_dicts([_finding(UNWEIGHTED, "warning")]) == 96
    assert security_score_from_finding_dicts([_finding(UNWEIGHTED, "info")]) == 99


def test_weight_multiplies_before_the_per_rule_cap():
    # Three errors of one weight-2 rule: 60 raw, capped to 20 — same as one.
    assert security_score_from_finding_dicts([_finding(WRITE_AUTH)] * 3) == 80
    # Two warnings of a weight-2 rule: 2 × 4 × 2 = 16, under the cap.
    assert security_score_from_finding_dicts([_finding(WRITE_AUTH, "warning")] * 2) == 84
    # The cap is per rule: two different weight-2 rules each cost their full 20.
    assert security_score_from_finding_dicts([_finding(WRITE_AUTH), _finding(CREDS_IN_URL)]) == 60


def test_weighted_penalty_by_rule_is_the_uncapped_contribution():
    penalties = weighted_penalty_by_rule(
        [_finding(WRITE_AUTH), _finding(WRITE_AUTH), _finding(UNWEIGHTED, "warning")]
    )
    assert penalties == {WRITE_AUTH: 40.0, UNWEIGHTED: 4.0}


def test_score_is_clamped_at_zero_and_reads_rule_id_too():
    findings = [{"rule_id": f"security.r{i}", "severity": "error"} for i in range(12)]
    assert security_score_from_finding_dicts(findings) == 0


def test_empty_finding_set_scores_clean_100():
    assert security_score_from_finding_dicts([]) == 100


def test_unknown_severity_costs_nothing_and_unnamed_rules_share_one_bucket():
    assert security_score_from_finding_dicts([{"rule": "security.x", "severity": "note"}]) == 100
    assert weighted_penalty_by_rule([{"severity": "error"}, {"severity": "error"}]) == {
        "_unnamed": 20.0
    }


# --- OWASP sub-scores ---------------------------------------------------------------------------

MAPPING = {
    WRITE_AUTH: ("API2",),
    CREDS_IN_URL: ("API2", "API8"),
    UNWEIGHTED: ("API8",),
    "security.deprecated-without-sunset": ("API9",),
}


def test_rules_by_owasp_risk_inverts_the_mapping_in_catalog_order():
    by_risk = rules_by_owasp_risk(MAPPING)
    assert list(by_risk) == list(RISK_IDS)
    assert by_risk["API2"] == (CREDS_IN_URL, WRITE_AUTH)
    assert by_risk["API8"] == (CREDS_IN_URL, UNWEIGHTED)
    assert by_risk["API1"] == ()


def test_subscores_cover_every_category_and_score_only_cited_findings():
    subs = owasp_subscores(
        [_finding(WRITE_AUTH), _finding(UNWEIGHTED, "warning")], rule_owasp=MAPPING
    )
    assert [s.risk_id for s in subs] == list(RISK_IDS)
    by_id = {s.risk_id: s for s in subs}
    api2 = by_id["API2"]
    assert (api2.coverage, api2.score, api2.finding_count) == ("full", 80, 1)
    api8 = by_id["API8"]
    assert (api8.coverage, api8.score, api8.finding_count) == ("full", 96, 1)
    api9 = by_id["API9"]  # a rule cites it and evaluated: clean 100, not a gap
    assert (api9.coverage, api9.score, api9.finding_count) == ("full", 100, 0)
    api1 = by_id["API1"]  # no rule cites it: not assessed, never 100
    assert (api1.coverage, api1.score, api1.finding_count) == ("none", None, 0)
    assert api1.title == "Broken object level authorization"


def test_a_rule_citing_two_categories_counts_in_both():
    subs = {s.risk_id: s for s in owasp_subscores([_finding(CREDS_IN_URL)], rule_owasp=MAPPING)}
    assert subs["API2"].finding_count == 1 and subs["API2"].score == 80
    assert subs["API8"].finding_count == 1 and subs["API8"].score == 80


def test_category_whose_every_rule_was_skipped_is_not_assessed():
    subs = {
        s.risk_id: s
        for s in owasp_subscores(
            [], skipped_rules=["security.deprecated-without-sunset"], rule_owasp=MAPPING
        )
    }
    assert subs["API9"].coverage == "none" and subs["API9"].score is None
    # One of API8's two rules still evaluated, so the category is covered.
    assert subs["API8"].coverage == "full" and subs["API8"].score == 100


def test_subscore_as_dict_is_the_stored_shape():
    sub = OwaspSubScore(risk_id="API2", title="t", score=80, finding_count=1, coverage="full")
    assert sub.as_dict() == {
        "risk_id": "API2",
        "title": "t",
        "score": 80,
        "finding_count": 1,
        "coverage": "full",
    }


# --- evaluate_security_findings ------------------------------------------------------------------


def test_evaluation_is_full_coverage_when_nothing_registered_was_skipped():
    ev = evaluate_security_findings([_finding(WRITE_AUTH)], rule_owasp=MAPPING)
    assert (ev.score, ev.grade, ev.coverage) == (80, "B", "full")
    assert ev.skipped_rules == ()
    assert len(ev.owasp) == 10


def test_evaluation_is_partial_when_a_registered_rule_was_skipped():
    ev = evaluate_security_findings(
        [], skipped_rules=["security.deprecated-without-sunset", "not.a.security.rule"],
        rule_owasp=MAPPING,
    )
    assert (ev.score, ev.grade, ev.coverage) == (100, "A", "partial")
    # Only registered security rules count as skipped; anything else is ignored.
    assert ev.skipped_rules == ("security.deprecated-without-sunset",)


def test_evaluation_defaults_to_the_catalog_mapping(monkeypatch):
    monkeypatch.setattr(security_score, "rule_owasp_ids", lambda: MAPPING)
    ev = evaluate_security_findings([_finding(CREDS_IN_URL)])
    assert ev.score == 80
    assert {s.risk_id: s.coverage for s in ev.owasp}["API8"] == "full"


# --- Catalog integration -------------------------------------------------------------------------


def test_rule_owasp_ids_reads_the_registry_and_only_valid_ids():
    rule_owasp_ids.cache_clear()
    mapping = rule_owasp_ids()
    for rule_id, ids in mapping.items():
        assert rule_id and ids
        assert set(ids) <= set(RISK_IDS)


def test_registry_rejects_a_rule_citing_an_unknown_category():
    from app.lint_rule_registry import _descriptor

    with pytest.raises(UnknownRiskError):
        _descriptor("security.bogus", "security", "security", "warning", "x", ("API42",))


def test_published_weights_cover_every_security_rule_and_every_reserved_weight():
    rows = published_weights()
    ids = [row["rule_id"] for row in rows]
    assert ids == sorted(ids)
    by_id = {row["rule_id"]: row for row in rows}
    for rule_id, weight in SECURITY_RULE_WEIGHTS.items():
        assert by_id[rule_id]["weight"] == weight
    from app.lint_rule_registry import builtin_rule_descriptors

    for descriptor in builtin_rule_descriptors():
        if descriptor.category == "security":
            row = by_id[descriptor.rule_id]
            assert row["registered"] is True
            assert row["weight"] == security_rule_weight(descriptor.rule_id)
            assert row["owasp"] == list(descriptor.owasp_ids)
    for row in rows:
        assert set(row) == {"rule_id", "weight", "owasp", "registered"}
        if not row["registered"]:
            assert row["rule_id"] in SECURITY_RULE_WEIGHTS and row["owasp"] == []


# --- Docs: the weights table on the axis-score page is generated, not typed ---------------------


def _load_docs_generator():
    path = REPO_ROOT / "apiome-rest" / "scripts" / "generate_lint_rule_docs.py"
    spec = importlib.util.spec_from_file_location("generate_lint_rule_docs", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_axis_score_docs_carry_the_generated_security_block():
    generator = _load_docs_generator()
    page = (REPO_ROOT / ALGORITHM_DOCS_PAGE).read_text(encoding="utf-8")
    begin, end = generator.SECURITY_BLOCK_BEGIN, generator.SECURITY_BLOCK_END
    assert begin in page and end in page
    committed = page[page.index(begin) : page.index(end) + len(end)]
    assert committed == generator.render_security_score_block()
    # The block is the published policy, verbatim: every weight and every category.
    for rule_id, weight in SECURITY_RULE_WEIGHTS.items():
        assert f"`{rule_id}` | {weight:.1f}" in committed
    for risk_id in RISK_IDS:
        assert f"| {risk_id} |" in committed
