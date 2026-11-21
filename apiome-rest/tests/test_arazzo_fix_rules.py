"""Unit tests for the fixable Arazzo rules — GVM-4.5 (#5880).

The one-defect fixtures and the byte-stability gates live in ``test_scanner_fix_corpus``; these
cover the rules' edges: which findings are reported, what a fix refuses to derive, how repeats
are suffixed, the plan integration, the catalogue entries and the dependency on GOV-3.2.
"""

import copy

import pytest

from app.arazzo_fix_rules import (
    arazzo_fix_rules,
    is_arazzo_document,
    lint_arazzo_fixable,
    plan_arazzo_fix,
    response_status_codes,
)
from app.lint_fix import FixOptions, apply_fix_ops
from app.lint_fix_plan import STATUS_READY, build_fix_plan
from app.lint_rule_registry import builtin_rule_descriptors

SUFFIX = "arazzo.step-id-suffix"
SCAFFOLD = "arazzo.success-criteria-scaffold"
BUMP = "arazzo.version-marker-bump"
OPT_IN = FixOptions(opt_in=frozenset({SCAFFOLD}))


def _source(responses):
    return {
        "openapi": "3.1.0",
        "info": {"title": "Pets", "version": "1"},
        "paths": {"/pets": {"get": {"operationId": "listPets", "responses": responses}}},
    }


def _document(steps, *, version="1.0.1", sources=None):
    return {
        "arazzo": version,
        "info": {"title": "Flows", "version": "1"},
        "sourceDescriptions": sources
        or [{"name": "pets", "type": "openapi", "url": "./pets.yaml", "content": _source({"200": {"description": "ok"}})}],
        "workflows": [{"workflowId": "w", "steps": steps}],
    }


def _step(step_id, **extra):
    return {"stepId": step_id, "operationId": "$sourceDescriptions.pets.listPets", **extra}


def _fixed(document, rule, options=None):
    for finding in lint_arazzo_fixable(document):
        if finding.rule == rule:
            document = apply_fix_ops(document, plan_arazzo_fix(document, finding, options))
    return document


def test_is_arazzo_document_needs_the_marker():
    assert is_arazzo_document({"arazzo": "1.1.0"})
    assert not is_arazzo_document({"openapi": "3.1.0"})
    assert not is_arazzo_document({"arazzo": " "})
    assert not is_arazzo_document([])
    assert lint_arazzo_fixable({"openapi": "3.1.0"}) == []


# --- arazzo.step-id-suffix -------------------------------------------------------------------


def test_only_repeats_are_flagged_and_the_first_declaration_is_kept():
    document = _document([_step("a"), _step("a"), _step("b")])
    findings = [f for f in lint_arazzo_fixable(document) if f.rule == SUFFIX]
    assert [f.path for f in findings] == ["workflows.0.steps.1.stepId"]
    assert _fixed(document, SUFFIX)["workflows"][0]["steps"][1]["stepId"] == "a-2"


def test_each_repeat_gets_its_own_free_suffix():
    document = _document([_step("a"), _step("a-2"), _step("a"), _step("a")])
    ids = [s["stepId"] for s in _fixed(document, SUFFIX)["workflows"][0]["steps"]]
    assert ids == ["a", "a-2", "a-3", "a-4"]
    assert [f for f in lint_arazzo_fixable(_fixed(document, SUFFIX)) if f.rule == SUFFIX] == []


def test_duplicates_in_different_workflows_are_not_repeats():
    document = _document([_step("a")])
    document["workflows"].append({"workflowId": "x", "steps": [_step("a")]})
    assert [f for f in lint_arazzo_fixable(document) if f.rule == SUFFIX] == []


# --- arazzo.success-criteria-scaffold ---------------------------------------------------------


def test_response_status_codes_lists_numeric_2xx_only():
    assert response_status_codes({"responses": {"201": {}, "200": {}, "2XX": {}, "default": {}, "404": {}}}) == ["200", "201"]
    assert response_status_codes({}) == []


def test_scaffold_is_off_by_default_and_on_when_opted_in():
    document = _document([_step("a")])
    finding = next(f for f in lint_arazzo_fixable(document) if f.rule == SCAFFOLD)
    assert plan_arazzo_fix(document, finding) == ()
    assert [op.as_dict() for op in plan_arazzo_fix(document, finding, OPT_IN)] == [
        {
            "op": "add",
            "path": "/workflows/0/steps/0/successCriteria",
            "value": [{"condition": "$statusCode == 200"}],
        }
    ]


def test_scaffold_uses_the_declared_2xx_code_and_replaces_an_empty_list():
    sources = [{"name": "pets", "content": _source({"201": {"description": "made"}, "404": {"description": "no"}})}]
    document = _document([_step("a", successCriteria=[])], sources=sources)
    after = _fixed(document, SCAFFOLD, OPT_IN)
    assert after["workflows"][0]["steps"][0]["successCriteria"] == [{"condition": "$statusCode == 201"}]


@pytest.mark.parametrize(
    "responses",
    [{"default": {"description": "x"}}, {"404": {"description": "x"}}, {"2XX": {"description": "x"}}],
)
def test_no_scaffold_without_a_declared_2xx_code(responses):
    sources = [{"name": "pets", "content": _source(responses)}]
    assert lint_arazzo_fixable(_document([_step("a")], sources=sources)) == []


def test_no_scaffold_without_an_embedded_source_or_with_criteria():
    no_content = [{"name": "pets", "type": "openapi", "url": "./pets.yaml"}]
    assert lint_arazzo_fixable(_document([_step("a")], sources=no_content)) == []
    with_criteria = _document([_step("a", successCriteria=[{"condition": "$statusCode == 200"}])])
    assert lint_arazzo_fixable(with_criteria) == []


def test_an_unqualified_operation_id_must_match_exactly_one_source():
    other = {"name": "other", "content": _source({"200": {"description": "ok"}})}
    sources = [{"name": "pets", "content": _source({"200": {"description": "ok"}})}, other]
    step = {"stepId": "a", "operationId": "listPets"}
    assert lint_arazzo_fixable(_document([step], sources=sources)) == []  # ambiguous: two sources


# --- arazzo.version-marker-bump ---------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["sourceDescriptions"].append({"name": "e", "type": "asyncapi", "url": "./e.yaml"}),
        lambda d: d["workflows"][0]["steps"][0].update({"channelPath": "$sourceDescriptions.e#/channels/x"}),
        lambda d: d["workflows"][0]["steps"][0].update({"parameters": [{"name": "q", "in": "querystring", "value": "x"}]}),
    ],
)
def test_each_1_1_feature_bumps_a_1_0_marker(mutate):
    document = _document([_step("a", successCriteria=[{"condition": "$statusCode == 200"}])])
    mutate(document)
    assert _fixed(document, BUMP)["arazzo"] == "1.1.0"


def test_a_1_1_document_or_a_plain_1_0_document_is_clean():
    plain = _document([_step("a")])
    assert [f for f in lint_arazzo_fixable(plain) if f.rule == BUMP] == []
    modern = copy.deepcopy(plain)
    modern["arazzo"] = "1.1.0"
    modern["sourceDescriptions"].append({"name": "e", "type": "asyncapi", "url": "./e.yaml"})
    assert [f for f in lint_arazzo_fixable(modern) if f.rule == BUMP] == []


# --- plan, catalogue -------------------------------------------------------------------------


def test_the_plan_composes_every_arazzo_fix_and_leaves_the_input_alone():
    document = _document([_step("a"), _step("a")])
    document["sourceDescriptions"].append({"name": "e", "type": "asyncapi", "url": "./e.yaml"})
    original = copy.deepcopy(document)
    plan = build_fix_plan(document, rules=[SUFFIX, BUMP])
    assert document == original
    ready = {e.rule_id for e in plan.entries if e.status == STATUS_READY}
    assert ready == {SUFFIX, BUMP}  # the unselected scaffold is listed as excluded
    assert plan.fixed_document["arazzo"] == "1.1.0"
    assert plan.fixed_document["workflows"][0]["steps"][1]["stepId"] == "a-2"
    assert "a/arazzo.json" in plan.unified_diff()


def test_the_scaffold_is_excluded_from_a_default_plan():
    plan = build_fix_plan(_document([_step("a")]))
    assert [(e.rule_id, e.status) for e in plan.entries] == [(SCAFFOLD, "excluded")]


def test_the_catalogue_publishes_the_arazzo_fixes():
    by_id = {d.rule_id: d for d in builtin_rule_descriptors()}
    for rule in arazzo_fix_rules():
        assert by_id[rule.rule_id].fixable
    assert by_id[SUFFIX].fix_class == "rename" and not by_id[SUFFIX].wire_visible
    assert by_id[SCAFFOLD].fix_class == "fill-in" and not by_id[SCAFFOLD].fix_default
    assert by_id[BUMP].fix_class == "structural"


@pytest.mark.xfail(
    strict=True,
    reason="GOV-3.2 (#4439): a ladder level carries `formats` only once format-conditional rules land.",
)
def test_a_ladder_level_can_be_scoped_to_arazzo_and_overlay():
    from app.axis_score import AXIS_KEYS
    from app.style_guide_ladder import validate_ladder

    raw = {
        "name": "Workflows",
        "levels": [
            {
                "key": "bronze",
                "label": "Bronze",
                "formats": ["arazzo", "overlay"],
                "rules": [{"ruleId": SUFFIX, "maxSeverity": "warning"}],
                "axes": [],
                "evidence": [],
                "waiversSatisfy": False,
            }
        ],
    }
    ladder = validate_ladder(raw, registered_rule_ids=(SUFFIX,), axis_keys=AXIS_KEYS)
    assert ladder["levels"][0]["formats"] == ["arazzo", "overlay"]
