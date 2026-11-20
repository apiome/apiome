"""Tests for suggested lint fixes in CI summaries — GVM-3.4 (#5872).

Covers the plan summary (per-rule counts, fix class, first-hunk snippet), the Markdown section, and
where it is embedded: the lint gate's Markdown artifact and the check-suite summary that GNC-2.2
publishes as the provider check run's summary.
"""

from __future__ import annotations

import copy
from typing import Any, Dict
from unittest.mock import patch

from app.api_check_suite import (
    COMPONENT_LINT,
    REASON_REQUIRED_FAILED,
    REQUIREMENT_REQUIRED,
    STATE_FAIL,
    LintFacts,
    judge_lint,
    render_summary,
)
from app.deploy_gate import DEFAULT_THRESHOLDS
from app.lint_fix_plan import build_fix_plan
from app.lint_fix_routes import fix_plan_links, suggest_revision_fixes
from app.lint_fix_suggestions import (
    MAX_SNIPPET_LINES,
    MAX_SUGGESTED_RULES,
    first_hunk,
    fix_suggestions_markdown,
    summarize_fix_plan,
)
from app.lint_gate_emit import serialize_lint_gate, to_gate_markdown

from test_lint_fix_plan import MULTI_DEFECT

LINKS = fix_plan_links("acme", "p1", "v1")


def _summary() -> Dict[str, Any]:
    return summarize_fix_plan(build_fix_plan(copy.deepcopy(MULTI_DEFECT)))


# ---------------------------------------------------------------------------------------------
# The plan summary
# ---------------------------------------------------------------------------------------------


def test_the_summary_counts_ready_fixes_per_rule_in_plan_order():
    plan = build_fix_plan(copy.deepcopy(MULTI_DEFECT))
    summary = summarize_fix_plan(plan)
    ready = [entry for entry in plan.entries if entry.status == "ready"]
    assert summary["ready"] == len(ready) > 0
    assert sum(rule["count"] for rule in summary["rules"]) == summary["ready"]
    assert [rule["ruleId"] for rule in summary["rules"]] == list(dict.fromkeys(e.rule_id for e in ready))
    for rule in summary["rules"]:
        assert rule["fixClass"] == next(e.fix_class for e in ready if e.rule_id == rule["ruleId"])
        assert rule["snippet"].startswith("@@ ")


def test_the_summary_counts_what_is_left_for_a_person():
    plan = build_fix_plan(copy.deepcopy(MULTI_DEFECT))
    counts = plan.counts()
    summary = summarize_fix_plan(plan)
    assert summary["conflict"] == counts["conflict"] >= 1
    assert summary["breaking"] == counts["breaking"]


def test_the_summary_is_deterministic():
    assert _summary() == _summary()


def test_a_document_without_defects_suggests_nothing():
    plan = build_fix_plan(build_fix_plan(copy.deepcopy(MULTI_DEFECT)).fixed_document)
    summary = summarize_fix_plan(plan)
    assert summary["ready"] == 0 and summary["rules"] == []


def test_first_hunk_is_only_the_first_hunk_and_capped():
    before = {"a": 1, "filler": list(range(40)), "z": 1}
    after = {"a": 2, "filler": list(range(40)), "z": 2}
    hunk = first_hunk(before, after)
    assert hunk.count("@@") == 2  # one header: "@@ … @@"
    assert '-  "a": 1,' in hunk and '"z"' not in hunk
    long_after = {"a": 1, "filler": list(range(100, 140)), "z": 1}
    capped = first_hunk(before, long_after).splitlines()
    assert len(capped) == MAX_SNIPPET_LINES + 1 and capped[-1] == "…"
    assert first_hunk(before, before) == ""


# ---------------------------------------------------------------------------------------------
# The Markdown section
# ---------------------------------------------------------------------------------------------


def test_the_section_lists_each_rule_with_its_class_and_a_diff_snippet():
    summary = _summary()
    lines = fix_suggestions_markdown(summary, heading="## Suggested fixes", links=LINKS)
    text = "\n".join(lines)
    assert lines[0] == "## Suggested fixes"
    assert f"{summary['ready']} mechanical fixes ready to apply" in text
    for rule in summary["rules"]:
        assert f"- `{rule['ruleId']}` — {rule['count']} fix" in text
        assert f"({rule['fixClass']})" in text
    assert "```diff" in text
    assert "conflicting fixes need a person" in text
    assert "patch `GET /v1/versions/acme/p1/v1/lint/fixes?format=patch`" in text
    assert "overlay `GET /v1/versions/acme/p1/v1/lint/fixes?format=overlay`" in text


def test_nothing_to_suggest_renders_no_section():
    assert fix_suggestions_markdown(None, heading="h") == []
    assert fix_suggestions_markdown({"ready": 0, "breaking": 0, "conflict": 0, "rules": []}, heading="h") == []


def test_only_remaining_fixes_still_render_without_links():
    lines = fix_suggestions_markdown(
        {"ready": 0, "breaking": 1, "conflict": 0, "rules": []}, heading="h", links=LINKS
    )
    text = "\n".join(lines)
    assert "No fix is ready to apply." in text
    assert "1 breaking and 0 conflicting" in text
    assert "GET" not in text


def test_a_snippet_with_backticks_gets_a_longer_fence():
    summary = {
        "ready": 1,
        "breaking": 0,
        "conflict": 0,
        "rules": [{"ruleId": "r", "fixClass": "fill-in", "count": 1, "snippet": '+ "x": "```"'}],
    }
    text = "\n".join(fix_suggestions_markdown(summary, heading="h"))
    assert "````diff" in text and text.count("````") == 2


def test_many_rules_are_capped():
    rules = [{"ruleId": f"r{i}", "fixClass": "removal", "count": 1, "snippet": ""} for i in range(15)]
    summary = {"ready": 15, "breaking": 0, "conflict": 0, "rules": rules}
    text = "\n".join(fix_suggestions_markdown(summary, heading="h"))
    assert "`r9`" in text and "`r10`" not in text
    assert f"… and {15 - MAX_SUGGESTED_RULES} more rules." in text


# ---------------------------------------------------------------------------------------------
# Where the section is embedded
# ---------------------------------------------------------------------------------------------

GATE: Dict[str, Any] = {
    "subjectId": "v1",
    "subjectType": "catalog_revision",
    "gate": {"passed": False, "gateResults": {}},
    "evaluation": {},
    "policy": {"policyVersionId": "pv", "contentFingerprint": "fp"},
    "counts": {"total": 1},
    "findings": [],
}


def test_the_gate_markdown_embeds_the_section_before_provenance():
    md = to_gate_markdown(GATE, fix_suggestions=_summary(), fix_links=LINKS)
    assert "## Suggested fixes" in md
    assert md.index("## Suggested fixes") < md.index("## Provenance")
    assert "## Suggested fixes" not in to_gate_markdown(GATE)


def test_serialize_lint_gate_passes_suggestions_only_to_markdown():
    body, _ = serialize_lint_gate("markdown", GATE, fix_suggestions=_summary(), fix_links=LINKS)
    assert "## Suggested fixes" in body
    body, _ = serialize_lint_gate("junit", GATE, fix_suggestions=_summary(), fix_links=LINKS)
    assert "Suggested fixes" not in body


def _render(components) -> str:
    return render_summary(
        run_id="run-1",
        state=STATE_FAIL,
        reason=REASON_REQUIRED_FAILED,
        components=components,
        version_label="2.0.0",
        commit_sha=None,
        draft_digest="sha256:d",
        policy_source="tenant",
        policy_fingerprint_value="sha256:p",
        thresholds_source="default",
        thresholds_fingerprint="sha256:t",
        drill_down=None,
    )


def _lint_component(fix_suggestions):
    facts = LintFacts(grade="B", score=85, severity_counts={"warning": 2}, error_findings=[])
    return judge_lint(
        facts,
        thresholds=DEFAULT_THRESHOLDS.lint,
        requirement=REQUIREMENT_REQUIRED,
        link="/lint",
        fix_suggestions=fix_suggestions,
    )


def test_the_check_suite_summary_carries_the_fix_count_and_the_patch_link():
    suggestions = {**_summary(), "links": LINKS}
    component = _lint_component(suggestions)
    assert component.component == COMPONENT_LINT
    assert component.evidence["fixSuggestions"]["ready"] == suggestions["ready"]
    summary = _render([component])
    assert "**Suggested fixes**" in summary
    assert f"{suggestions['ready']} mechanical fixes ready to apply" in summary
    assert "lint/fixes?format=patch" in summary
    # Stored components are dicts; the summary renders the same text from them.
    assert _render([component.model_dump(mode="json")]) == summary


def test_the_check_suite_summary_has_no_section_without_suggestions():
    assert "Suggested fixes" not in _render([_lint_component(None)])
    assert "fixSuggestions" not in _lint_component(None).evidence


# ---------------------------------------------------------------------------------------------
# Planning a stored revision
# ---------------------------------------------------------------------------------------------


class _Guide:
    guide_id = None
    name = "default"

    @staticmethod
    def is_enabled(rule_id: str) -> bool:
        return True


def test_a_revision_is_planned_with_the_default_options():
    with patch("app.lint_fix_routes.openapi_for_revision", return_value=copy.deepcopy(MULTI_DEFECT)), patch(
        "app.lint_fix_routes.resolve_style_guide", return_value=_Guide()
    ):
        summary = suggest_revision_fixes({"id": "v1"}, tenant_slug="acme", tenant_id="t", project_id="p1")
    assert summary is not None and summary["ready"] > 0


def test_a_revision_that_cannot_be_planned_has_no_suggestions():
    with patch("app.lint_fix_routes.openapi_for_revision", return_value={"swagger": "2.0"}), patch(
        "app.lint_fix_routes.resolve_style_guide", return_value=_Guide()
    ):
        assert suggest_revision_fixes({"id": "v1"}, tenant_slug="acme", tenant_id="t", project_id="p1") is None
    with patch("app.lint_fix_routes.openapi_for_revision", side_effect=RuntimeError("db down")):
        assert suggest_revision_fixes({"id": "v1"}, tenant_slug="acme", tenant_id="t", project_id="p1") is None
