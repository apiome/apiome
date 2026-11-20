"""Arazzo change rules and breaking-change depth — COA-1.6 (#7042).

Acceptance criteria pinned here:

* **each rule has a golden fixture pair** — ``tests/fixtures/arazzo_breaking/<case>/old.arazzo.yaml``
  and ``new.arazzo.yaml``; the graded changes of every pair are recorded in ``expected.json``
  (regenerate with ``APIOME_REGEN_ARAZZO_BREAKING=1``), and every rule in
  :data:`app.arazzo_change_rules.ARAZZO_RULES` is the headline rule of at least one pair;
* **unknown kinds default to breaking (fail-safe)** — a change no rule claims is graded breaking
  under ``ctg.unclassified``;
* the rules are in the CTG classifier registry, and Arazzo revisions are graded canonically by the
  classified diff and catalog change reports (``grades_classified_diff``).

Models are built with the real Arazzo importer, so keys match production exactly.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.arazzo_breaking_change import ArazzoBreakingChangeClassifier
from app.arazzo_change_rules import (
    ARAZZO_RULES,
    ArazzoChange,
    grade,
    root_changes,
    step_changes,
    steps_reordered,
    workflow_changes,
)
from app.arazzo_import_source import ArazzoImportSource
from app.breaking_change import Severity, classify_models, get_breaking_change_classifier
from app.change_taxonomy import classify_raw_changes, get_rule
from app.change_taxonomy_enum import RawChange
from app.change_taxonomy_rules import UNCLASSIFIED_RULE_ID
from app.compatibility_modes import ctg_changes, graded_changes, is_mode_graded_format

_FIXTURES = Path(__file__).parent / "fixtures" / "arazzo_breaking"
_EXPECTED = _FIXTURES / "expected.json"
_CASES = sorted(p.name for p in _FIXTURES.iterdir() if p.is_dir())

#: Cases whose headline rule is not named after the folder.
_HEADLINE = {
    "referenced-input-required-added": "arazzo.input-required-added",
    "component-parameter-changed": "arazzo.parameter-changed",
    "unclassified-fail-safe": UNCLASSIFIED_RULE_ID,
}


def _model(path: Path):
    source = ArazzoImportSource()
    return source.normalize(source.parse(path.read_text(), source_label=path.name))


def _graded(case: str) -> List[Dict[str, Any]]:
    folder = _FIXTURES / case
    result = classify_models(_model(folder / "old.arazzo.yaml"), _model(folder / "new.arazzo.yaml"))
    return [
        {
            "pointer": g.pointer,
            "kind": g.change_kind,
            "rule_id": g.rule_id,
            "severity": g.severity,
            "rationale": g.rationale,
        }
        for g in graded_changes(result)
    ]


def _expected() -> Dict[str, Any]:
    if os.environ.get("APIOME_REGEN_ARAZZO_BREAKING"):
        _EXPECTED.write_text(json.dumps({case: _graded(case) for case in _CASES}, indent=2) + "\n")
    return json.loads(_EXPECTED.read_text())


# ===========================================================================
# Golden fixture pairs
# ===========================================================================


@pytest.mark.parametrize("case", _CASES)
def test_fixture_pair_matches_its_golden(case: str) -> None:
    assert _graded(case) == _expected()[case]


@pytest.mark.parametrize("case", _CASES)
def test_fixture_pair_fires_its_headline_rule(case: str) -> None:
    headline = _HEADLINE.get(case, f"arazzo.{case}")
    assert headline in {g["rule_id"] for g in _graded(case)} | {
        rule for g in _graded(case) for rule in _rules_in_rationale(g["rationale"])
    }


def _rules_in_rationale(rationale: str) -> List[str]:
    """Rule ids a multi-rule rationale lists as ``[rule.id]``."""
    return [part.split("]")[0] for part in rationale.split("[")[1:]]


def test_every_rule_has_a_fixture_pair() -> None:
    covered = {_HEADLINE.get(case, f"arazzo.{case}") for case in _CASES}
    assert {rule.rule_id for rule in ARAZZO_RULES} <= covered
    assert set(_expected()) == set(_CASES)


def test_each_pair_is_graded_at_its_rule_severity() -> None:
    by_id = {rule.rule_id: rule for rule in ARAZZO_RULES}
    for case in _CASES:
        headline = _HEADLINE.get(case, f"arazzo.{case}")
        if headline not in by_id:
            continue
        severities = {g["severity"] for g in _graded(case) if g["rule_id"] == headline}
        assert severities <= {by_id[headline].severity.value}, case


# ===========================================================================
# Fail-safe and the CTG registry
# ===========================================================================


def test_unknown_kind_is_breaking_and_unclassified() -> None:
    severity, rule_id, rationale = grade(
        ArazzoChange("timeout_changed", "/workflows/w/steps/s/timeout", "step changed")
    )
    assert severity is Severity.BREAKING
    assert rule_id == UNCLASSIFIED_RULE_ID
    assert "fail-safe" in rationale


def test_unknown_step_key_falls_through_to_fail_safe() -> None:
    changes = step_changes("w#s", {"stepId": "s"}, {"stepId": "s", "correlationId": "$message.id"})
    assert [c.kind for c in changes] == ["correlationId_changed"]
    assert grade(changes[0])[1] == UNCLASSIFIED_RULE_ID


def test_unknown_root_key_and_component_section_fail_safe() -> None:
    changes = root_changes({"components": {"widgets": {}}}, {"novel": 1, "components": {"widgets": {"a": 1}}})
    assert {grade(c)[1] for c in changes} == {UNCLASSIFIED_RULE_ID}
    assert len(changes) == 2


def test_rules_are_in_the_ctg_registry() -> None:
    for rule in ARAZZO_RULES:
        registered = get_rule(rule.rule_id)
        assert registered is not None
        assert registered.change_kind == rule.change_kind
        assert registered.severity == rule.ctg_severity


def test_ctg_classifier_grades_arazzo_kinds_and_fails_safe_on_unknown_ones() -> None:
    classified = classify_raw_changes(
        [
            RawChange(kind="arazzo_output_removed", pointer="/workflows/w/outputs/x"),
            RawChange(kind="arazzo_success_criteria_added", pointer="/workflows/w/steps/s/successCriteria"),
            RawChange(kind="arazzo_docs_changed", pointer="/workflows/w/summary"),
            RawChange(kind="arazzo_something_new", pointer="/workflows/w"),
        ]
    )
    assert [(c.rule_id, c.severity, c.unclassified) for c in classified.changes] == [
        ("arazzo.output-removed", "breaking", False),
        ("arazzo.success-criteria-added", "non-breaking", False),
        ("arazzo.docs-changed", "docs-only", False),
        (UNCLASSIFIED_RULE_ID, "breaking", True),
    ]


# ===========================================================================
# Enumerator details
# ===========================================================================


def test_reorder_and_shift_are_told_apart() -> None:
    assert steps_reordered(["a", "b", "c"], ["b", "a", "c"])
    assert not steps_reordered(["a", "b", "c"], ["a", "x", "b", "c"])
    assert not steps_reordered(["a", "b", "c"], ["a", "c"])


def test_inputs_are_compared_resolved_through_components() -> None:
    ref = {"$ref": "#/components/inputs/i"}
    base = {"inputs": {"i": {"type": "object", "properties": {"x": {"type": "string"}}}}}
    target = {"inputs": {"i": {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}}}
    changes = workflow_changes("w", {"inputs": ref}, {"inputs": ref}, base_components=base, target_components=target)
    assert [c.kind for c in changes] == ["arazzo_input_required_added"]
    assert changes[0].pointer == "/workflows/w/inputs/properties/x"


def test_input_docs_only_change_is_docs_only() -> None:
    before = {"inputs": {"properties": {"x": {"type": "string", "description": "old"}}}}
    after = {"inputs": {"properties": {"x": {"type": "string", "description": "new"}}}}
    changes = workflow_changes("w", before, after, base_components={}, target_components={})
    assert [c.kind for c in changes] == ["arazzo_docs_changed"]


def test_parameters_pair_by_reference_and_location() -> None:
    before = {
        "parameters": [{"reference": "$components.parameters.p", "value": 1}, {"name": "q", "in": "query", "value": 1}]
    }
    after = {
        "parameters": [{"name": "q", "in": "header", "value": 1}, {"reference": "$components.parameters.p", "value": 2}]
    }
    kinds = sorted(c.kind for c in step_changes("w#s", before, after))
    assert kinds == ["arazzo_parameter_added", "arazzo_parameter_changed", "arazzo_parameter_removed"]


def test_criteria_compare_as_a_multiset() -> None:
    same = [{"condition": "$statusCode == 200"}, {"condition": "$statusCode == 200"}]
    assert step_changes("w#s", {"successCriteria": same}, {"successCriteria": list(reversed(same))}) == []
    changes = step_changes("w#s", {"successCriteria": same}, {"successCriteria": same[:1]})
    assert [c.kind for c in changes] == ["arazzo_success_criteria_removed"]


def test_a_derived_step_field_never_grades_on_its_own() -> None:
    assert (
        step_changes("w#s", {"stepIndex": 0, "sourceType": "openapi"}, {"stepIndex": 2, "sourceType": "asyncapi"}) == []
    )


# ===========================================================================
# Surfaces: the classifier registry, classified diff and change reports
# ===========================================================================


def test_arazzo_is_graded_canonically() -> None:
    assert get_breaking_change_classifier("arazzo") is ArazzoBreakingChangeClassifier
    assert ArazzoBreakingChangeClassifier.grades_classified_diff is True
    assert is_mode_graded_format("arazzo")


def test_ctg_changes_carry_the_arazzo_rule_and_rationale() -> None:
    folder = _FIXTURES / "source-removed"
    result = classify_models(_model(folder / "old.arazzo.yaml"), _model(folder / "new.arazzo.yaml"))
    assert result.breaking
    rows = [(change.rule_id, change.severity, change.rationale) for change, _ in ctg_changes(result)]
    assert ("arazzo.source-removed", "breaking", "source description 'billing' was removed") in rows


def test_catalog_change_report_uses_the_arazzo_rules() -> None:
    from app.catalog_revision_change_report import _classify

    folder = _FIXTURES / "output-removed"
    classified = _classify(_model(folder / "old.arazzo.yaml"), _model(folder / "new.arazzo.yaml"), {}, {})
    assert classified.max_severity == "breaking"
    assert [c.rule_id for c in classified.changes] == ["arazzo.output-removed"]
    assert classified.changes[0].rationale == "output 'petId' was removed"


def test_catalog_change_report_keeps_the_openapi_taxonomy_for_other_formats() -> None:
    from types import SimpleNamespace

    from app.catalog_revision_change_report import _classify

    base = {
        "openapi": "3.1.0",
        "info": {"title": "t", "version": "1"},
        "paths": {"/a": {"get": {"responses": {"200": {"description": "ok"}}}}},
    }
    head = {"openapi": "3.1.0", "info": {"title": "t", "version": "1"}, "paths": {}}
    classified = _classify(SimpleNamespace(format="kong"), SimpleNamespace(format="kong"), base, head)
    assert classified.changes[0].rule_id.startswith("ctg.")


def test_classified_diff_endpoint_grades_stored_arazzo_revisions_with_the_rules() -> None:
    """``POST /v1/diff/{tenant}/classified`` (what ``apiome diff`` and the diff Action call)."""
    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient

    from app.auth import validate_authentication
    from app.main import app

    folder = _FIXTURES / "input-required-added"
    sources = {"base-rev": folder / "old.arazzo.yaml", "head-rev": folder / "new.arazzo.yaml"}
    rows = {"1.0.0": {"id": "base-rev", "project_id": "p", "version_id": "1.0.0"}}
    rows["1.1.0"] = {"id": "head-rev", "project_id": "p", "version_id": "1.1.0"}
    db = MagicMock()
    db.user_has_permission.return_value = True
    db.get_project_by_slug.return_value = {"id": "p", "slug": "adopt", "tenant_id": "t", "metadata": "{}"}
    db.get_version_by_version_id.side_effect = lambda pid, ver, tid: rows.get(ver)
    db.get_assigned_style_guide.return_value = None
    db.get_revision_source_row.side_effect = lambda rid, tid: {
        "source_format": "arazzo",
        "protocol": "http",
        "format_metadata": {"sourceContent": sources[rid].read_text(), "sourceLabel": "adopt.arazzo.yaml"},
        "metadata": {},
    }
    app.dependency_overrides[validate_authentication] = lambda: {"tenant_id": "t", "user_id": "u", "auth_method": "jwt"}
    try:
        with patch("app.classified_diff_routes.db", db):
            response = TestClient(app).post(
                "/v1/diff/acme/classified",
                json={"base": {"project": "adopt", "version": "1.0.0"}, "head": {"project": "adopt", "version": "1.1.0"}},
            )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["maxSeverity"] == "breaking"
    assert [(c["ruleId"], c["severity"]) for c in data["changes"]] == [("arazzo.input-required-added", "breaking")]
    assert data["changes"][0]["rationale"] == "input 'maxPrice' is now required"


def test_the_docs_list_every_rule_at_its_severity() -> None:
    """``ship/api-changelog.mdx`` has one table row per rule, with its CTG severity."""
    page = (Path(__file__).resolve().parents[2] / "apiome-docs" / "docs" / "ship" / "api-changelog.mdx").read_text()
    words = {"breaking": "Breaking", "docs-only": "Docs-only"}
    for rule in ARAZZO_RULES:
        rows = [line for line in page.splitlines() if line.startswith(f"| `{rule.rule_id}` |")]
        assert len(rows) == 1, rule.rule_id
        cell = rows[0].split("|")[2].strip()
        if rule.severity is Severity.DANGEROUS:
            assert cell == "Non-breaking (review)", rule.rule_id
        else:
            assert cell == words.get(rule.ctg_severity, "Non-breaking"), rule.rule_id
