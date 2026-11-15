"""Tests for the JSON Schema open/closed compatibility classifier — XPC-4.2 (#5746).

Every fixture pair in ``fixtures/jsonschema_compatibility/cases.json`` names the rules it must fire
and whether it passes ``BACKWARD``, ``FORWARD`` and ``FULL``; the classifier's overall grade under
each mode must follow (breaking when the mode is failed, dangerous when only another mode is, safe
when every mode passes).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from app.breaking_change import Severity, classify, classify_models, get_breaking_change_classifier
from app.canonical_model import CanonicalApi
from app.diff import diff
from app.jsonschema_breaking import JsonSchemaBreakingChangeClassifier, compatibility_findings, type_schemas
from app.jsonschema_compatibility import (
    COMPATIBILITY_MODES,
    compare_schemas,
    content_model,
    is_compatible,
    mode_directions,
)
from app.jsonschema_import_source import JsonSchemaImportSource

_CASES = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "jsonschema_compatibility" / "cases.json").read_text()
)["cases"]
_SOURCE = JsonSchemaImportSource()
_MODES = ("BACKWARD", "FORWARD", "FULL")


def _model(schema: Dict[str, Any], *, include_raw: bool = True) -> CanonicalApi:
    return _SOURCE.normalize(_SOURCE.parse(json.dumps(schema)), include_raw=include_raw)


def _findings(old: Dict[str, Any], new: Dict[str, Any]):
    findings, _ = compatibility_findings(_model(old), _model(new))
    return [finding for _, finding in findings]


def _expected_severity(case: Dict[str, Any], mode: str) -> Severity:
    if not case["compatible"][mode]:
        return Severity.BREAKING
    if not all(case["compatible"].values()):
        return Severity.DANGEROUS
    return Severity.SAFE


@pytest.mark.parametrize("format_key", ["json-schema", "jsonschema", "json-schema-2020-12"])
def test_the_classifier_is_registered_for_every_json_schema_format_key(format_key: str):
    classifier = get_breaking_change_classifier(format_key)
    assert classifier is not None and issubclass(classifier, JsonSchemaBreakingChangeClassifier)


def test_an_imported_json_schema_dispatches_to_the_classifier():
    model = _model(_CASES[0]["old"])
    assert classify_models(model, model).classifier == "jsonschema-compatibility"


@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_each_fixture_pair_fires_its_rules(case: Dict[str, Any]):
    assert sorted(f.rule_id for f in _findings(case["old"], case["new"])) == sorted(case["rule_ids"])


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_each_fixture_pair_passes_or_fails_every_mode(case: Dict[str, Any], mode: str):
    assert is_compatible(_findings(case["old"], case["new"]), mode) is case["compatible"][mode]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_the_overall_grade_follows_the_mode(case: Dict[str, Any], mode: str):
    base, target = _model(case["old"]), _model(case["new"])
    result = JsonSchemaBreakingChangeClassifier(mode=mode).classify(diff(base, target), base, target)
    assert result.overall_severity is _expected_severity(case, mode)


def test_open_and_closed_models_grade_the_same_addition_differently():
    open_old = {"title": "User", "type": "object", "properties": {"id": {"type": "integer"}}}
    closed_old = {**open_old, "additionalProperties": False}
    added = {"nick": {"type": "string"}}
    open_new = {**open_old, "properties": {**open_old["properties"], **added}}
    closed_new = {**closed_old, "properties": {**closed_old["properties"], **added}}

    (open_graded,) = classify_models(_model(open_old), _model(open_new)).classifications
    (closed_graded,) = classify_models(_model(closed_old), _model(closed_new)).classifications

    assert (open_graded.key, closed_graded.key) == ("User.nick", "User.nick")
    assert open_graded.severity is Severity.BREAKING
    assert closed_graded.severity is Severity.DANGEROUS
    assert "open content model" in open_graded.rationale
    assert "closed content model" in closed_graded.rationale
    assert open_graded.rule_id == "jsonschema.backward.open-property-added"
    assert closed_graded.rule_id == "jsonschema.forward.closed-property-added"


def test_the_default_mode_is_backward_and_can_be_overridden():
    assert JsonSchemaBreakingChangeClassifier().mode == "BACKWARD"
    assert JsonSchemaBreakingChangeClassifier(mode="full_transitive").mode == "FULL_TRANSITIVE"
    with pytest.raises(ValueError):
        JsonSchemaBreakingChangeClassifier(mode="NONE")


def test_transitive_modes_check_the_same_directions_as_their_plain_form():
    for mode in ("BACKWARD", "FORWARD", "FULL"):
        assert mode_directions(f"{mode}_TRANSITIVE") == COMPATIBILITY_MODES[mode]


def test_a_rationale_names_the_mode_it_was_graded_under():
    case = next(c for c in _CASES if c["id"] == "required-added")
    base, target = _model(case["old"]), _model(case["new"])
    result = JsonSchemaBreakingChangeClassifier(mode="FORWARD").classify(diff(base, target), base, target)
    (graded,) = [c for c in result.classifications if c.key == "User.nick"]
    assert graded.severity is Severity.DANGEROUS
    assert graded.rationale.startswith("[FORWARD] breaks BACKWARD and FULL")


def test_a_content_model_flip_the_canonical_diff_misses_is_kept_unattributed():
    old = {"title": "User", "type": "object", "properties": {"id": {"type": "integer"}}}
    new = {**old, "additionalProperties": False}
    result = classify_models(_model(old), _model(new))
    assert result.classifications == []
    (finding,) = result.unattributed
    assert finding.rule_id == "jsonschema.backward.additional-properties-closed"
    assert finding.severity is Severity.BREAKING and result.breaking
    assert "open to closed" in finding.rationale


def test_a_nested_change_joins_nothing_and_stays_unattributed():
    nested = lambda props: {  # noqa: E731
        "title": "User",
        "type": "object",
        "properties": {"address": {"type": "object", "properties": props, "additionalProperties": False}},
    }
    result = classify_models(_model(nested({"city": {"type": "string"}})), _model(nested({})))
    (finding,) = result.unattributed
    assert finding.rule_id == "jsonschema.backward.closed-property-removed"
    assert finding.shape == "User/properties/address/properties/city"


def test_a_covered_change_without_findings_is_graded_safe():
    case = next(c for c in _CASES if c["id"] == "partially-open-property-added-covered")
    (graded,) = classify_models(_model(case["old"]), _model(case["new"])).classifications
    assert (graded.severity, graded.rule_id) == (Severity.SAFE, "jsonschema.compatible")


def test_a_type_only_one_version_defines_keeps_the_baseline_grade():
    old = {"$defs": {"A": {"type": "object", "properties": {"x": {"type": "string"}}}}}
    new = {"$defs": {**old["$defs"], "B": {"type": "string"}}}
    (graded,) = classify_models(_model(old), _model(new)).classifications
    assert (graded.key, graded.rule_id) == ("B", "added-entity")


def test_a_shared_definition_change_is_reported_once_on_the_definition():
    case = next(c for c in _CASES if c["id"] == "ref-shared-definition")
    findings, _ = compatibility_findings(_model(case["old"]), _model(case["new"]))
    assert [(t, f.path) for t, f in findings] == [("Address", ("properties", "zip"))]


def test_a_moved_ref_is_resolved_and_compared_at_the_referencing_field():
    case = next(c for c in _CASES if c["id"] == "ref-target-moved")
    findings, _ = compatibility_findings(_model(case["old"]), _model(case["new"]))
    assert [(t, f.property_name) for t, f in findings] == [("Order", "ship_to")]


def test_without_a_raw_document_the_schemas_are_rebuilt_from_the_canonical_model():
    old = {"title": "User", "type": "object", "properties": {"nick": {"type": "string"}}}
    new = {**old, "required": ["nick"]}
    base, target = _model(old, include_raw=False), _model(new, include_raw=False)
    document, schemas = type_schemas(base)
    assert "$defs" in document and set(schemas) == {"User"}
    result = classify_models(base, target)
    (graded,) = result.classifications
    assert graded.rule_id == "jsonschema.backward.required-added"


def test_an_unmodeled_keyword_is_flagged_for_review_in_every_mode():
    old = {"type": "object", "properties": {"a": {"type": "string"}}}
    new = {**old, "not": {"required": ["a"]}}
    (finding,) = compare_schemas(old, new)
    assert finding.rule_id == "jsonschema.review.unmodeled-keyword-changed"
    for mode in _MODES:
        assert is_compatible([finding], mode)


def test_an_external_ref_that_changes_is_flagged_for_review():
    (finding,) = compare_schemas({"$ref": "https://acme.test/a.json"}, {"$ref": "https://acme.test/b.json"})
    assert finding.rule_id == "jsonschema.review.ref-changed"


def test_boolean_schemas():
    assert [f.rule_id for f in compare_schemas(True, False)] == ["jsonschema.backward.schema-rejects-all"]
    assert [f.rule_id for f in compare_schemas(False, {"type": "string"})] == [
        "jsonschema.forward.schema-accepts-values"
    ]
    assert compare_schemas(True, {}) == []


def test_draft4_boolean_exclusive_bounds():
    old, new = {"type": "number", "maximum": 5}, {"type": "number", "maximum": 5, "exclusiveMaximum": True}
    assert [f.rule_id for f in compare_schemas(old, new)] == ["jsonschema.backward.exclusive-maximum-tightened"]


def test_content_model_names():
    assert content_model({"type": "object"}) == "open"
    assert content_model({"additionalProperties": False}) == "closed"
    assert content_model({"unevaluatedProperties": False}) == "closed"
    assert content_model({"additionalProperties": {"type": "string"}}) == "partially open"


def test_classify_is_deterministic():
    case = next(c for c in _CASES if c["id"] == "type-changed")
    base, target = _model(case["old"]), _model(case["new"])
    model_diff = diff(base, target)
    assert classify(model_diff, base, target) == classify(model_diff, base, target)
