"""Tests for the RAML breaking-change classifier — MFI-15.4 (#3802).

Two small RAML documents are imported (through the built-in reader; the classifier grades the
canonical model, so AMF makes no difference here), diffed, and graded by the ``raml`` classifier.
"""

from __future__ import annotations

from typing import Dict, Tuple

import pytest

from app import raml_import_source as import_source_module
from app.breaking_change import classify, get_breaking_change_classifier
from app.diff import diff
from app.raml_breaking import RamlBreakingChangeClassifier
from app.raml_import_source import RamlImportSource

_RAML = """#%RAML 1.0
title: Shelter
traits:
  paged:
    queryParameters:
      page:
        type: integer
        required: false
types:
  Status:
    enum: [{enum}]
  Pet:
    type: object
    properties:
      id: string
      name: {name}
{extra}
/pets:
  get:
    is: [{traits}]
    queryParameters:
      limit:
        type: {limit_type}
        required: {limit_required}
{query}
    responses:
      200:
        body:
          application/json:
            type: Pet[]
{responses}
"""

_DEFAULTS = {
    "enum": "OPEN, CLOSED",
    "name": "string",
    "extra": "",
    "traits": "",
    "limit_type": "integer",
    "limit_required": "false",
    "query": "",
    "responses": "",
}


@pytest.fixture(autouse=True)
def _no_amf(monkeypatch):
    monkeypatch.setattr(import_source_module, "amf_available", lambda: False)


def _model(**parts: str):
    adapter = RamlImportSource()
    return adapter.normalize(adapter.parse(_RAML.format(**{**_DEFAULTS, **parts})))


def _grades(head: Dict[str, str], base: Dict[str, str] = None) -> Dict[str, Tuple[str, str, str]]:
    old, new = _model(**(base or {})), _model(**head)
    result = classify(diff(old, new), old, new)
    assert result.classifier == "raml-resources"
    return {c.key: (c.severity.value, c.rule_id, c.rationale) for c in result.classifications}


def test_the_classifier_is_registered_for_raml():
    assert get_breaking_change_classifier("raml") is RamlBreakingChangeClassifier


@pytest.mark.parametrize(
    ("head", "base", "key", "expected"),
    [
        (
            {"query": "      page:\n        type: integer\n        required: true"},
            None,
            "GET /pets",
            ("breaking", "raml.parameter-added-required"),
        ),
        (
            {"query": "      page:\n        type: integer\n        required: false"},
            None,
            "GET /pets",
            ("safe", "raml.parameter-added-optional"),
        ),
        (
            {},
            {"query": "      page:\n        type: integer\n        required: false"},
            "GET /pets",
            ("dangerous", "raml.parameter-removed"),
        ),
        ({"limit_required": "true"}, None, "GET /pets", ("breaking", "raml.parameter-made-required")),
        ({}, {"limit_required": "true"}, "GET /pets", ("safe", "raml.parameter-made-optional")),
        ({"limit_type": "string"}, None, "GET /pets", ("breaking", "raml.parameter-type-changed")),
        ({"extra": "      tag: string"}, None, "Pet.tag", ("breaking", "raml.property-added-required")),
        ({"extra": "      tag?: string"}, None, "Pet.tag", ("safe", "raml.property-added-optional")),
        ({"name": "integer"}, None, "Pet.name", ("breaking", "raml.property-type-changed")),
        ({"enum": "OPEN"}, None, "Status", ("breaking", "raml.enum-value-removed")),
        ({"enum": "OPEN, CLOSED, HELD"}, None, "Status", ("dangerous", "raml.enum-value-added")),
        ({"enum": "CLOSED, OPEN"}, None, "Status", ("safe", "raml.enum-reordered")),
    ],
)
def test_grades(head, base, key, expected):
    assert _grades(head, base)[key][:2] == expected


def test_property_required_ness_moves():
    made_optional = _grades({"extra": "      tag?: string"}, {"extra": "      tag: string"})
    assert made_optional["Pet.tag"][:2] == ("dangerous", "raml.property-made-optional")
    made_required = _grades({"extra": "      tag: string"}, {"extra": "      tag?: string"})
    assert made_required["Pet.tag"][:2] == ("breaking", "raml.property-made-required")


def test_one_method_combines_its_parameter_grades():
    severity, rule, rationale = _grades(
        {"limit_type": "string", "query": "      page:\n        type: integer\n        required: false"}
    )["GET /pets"]
    assert (severity, rule) == ("breaking", "raml.parameter-type-changed")
    assert "optional query parameter 'page' was added" in rationale


def test_applying_a_trait_grades_its_effect_and_the_reuse_itself_is_safe():
    grades = _grades({"traits": "paged"})
    severity, rule, rationale = grades["GET /pets"]
    assert severity == "safe"
    assert {rule} <= {"raml.parameter-added-optional", "raml.reuse-changed"}
    assert "resource type / traits changed" in rationale


def test_removed_and_added_resources_and_responses_keep_the_baseline():
    added = _grades({"responses": "      404:\n        body:\n          application/json:\n            type: string"})
    assert any(grade[:2] == ("safe", "added-entity") for grade in added.values())
    removed = _grades(
        {}, {"responses": "      404:\n        body:\n          application/json:\n            type: string"}
    )
    assert any(grade[:2] == ("breaking", "removed-entity") for grade in removed.values())


def test_identical_documents_have_no_changes():
    assert _grades({}) == {}
