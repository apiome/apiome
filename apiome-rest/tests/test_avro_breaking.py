"""Tests for the Avro breaking-change classifier — MFI-12.4 (#3785).

The classifier's overall grade for a diff must agree with a live Confluent Schema Registry
(``fixtures/avro_compatibility/recordings.json``): breaking when the change fails ``BACKWARD``,
dangerous when it fails only ``FORWARD``, safe when it passes ``FULL``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from app.avro_breaking import AvroBreakingChangeClassifier, compatibility_findings
from app.avro_import_source import AvroImportSource
from app.breaking_change import Severity, classify_models, get_breaking_change_classifier
from app.canonical_model import CanonicalApi

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "avro_compatibility"
_CASES = json.loads((_FIXTURES / "cases.json").read_text())["cases"]
_RECORDED = json.loads((_FIXTURES / "recordings.json").read_text())["recordings"]
_SOURCE = AvroImportSource()


def _model(schema: Any, label: str = "schema.avsc") -> CanonicalApi:
    text = schema if isinstance(schema, str) else json.dumps(schema)
    return _SOURCE.normalize(_SOURCE.parse(text, source_label=label))


def _mode_cases():
    return [
        pytest.param(case, id=case["id"])
        for case in _CASES
        if {"BACKWARD", "FORWARD"} <= set(case["levels"])
    ]


def test_the_classifier_is_registered_for_avro():
    assert get_breaking_change_classifier("avro") is AvroBreakingChangeClassifier


@pytest.mark.parametrize("case", _mode_cases())
def test_the_overall_grade_follows_the_registrys_modes(case: Dict[str, Any]):
    recorded = _RECORDED[case["id"]]
    backward, forward = recorded["BACKWARD"]["is_compatible"], recorded["FORWARD"]["is_compatible"]
    expected = Severity.BREAKING if not backward else Severity.DANGEROUS if not forward else Severity.SAFE
    result = classify_models(_model(case["versions"][-1]), _model(case["candidate"]))
    assert result.classifier == "avro-compatibility"
    assert result.overall_severity is expected


_USER = {"type": "record", "name": "User", "namespace": "com.example", "fields": [{"name": "id", "type": "long"}]}


def _user(*fields: Dict[str, Any]) -> Dict[str, Any]:
    return {**_USER, "fields": _USER["fields"] + list(fields)}


@pytest.mark.parametrize(
    "old, new, key, severity, rule",
    [
        (_user(), _user({"name": "email", "type": "string"}), "com.example.User.email", Severity.BREAKING,
         "avro-compatibility.reader-field-missing-default-value"),
        (_user(), _user({"name": "email", "type": "string", "default": ""}), "com.example.User.email", Severity.SAFE,
         "avro-compatibility.compatible"),
        (_user({"name": "email", "type": "string"}), _user(), "com.example.User.email", Severity.DANGEROUS,
         "avro-compatibility.reader-field-missing-default-value"),
        (_user({"name": "email", "type": "string", "default": ""}), _user(), "com.example.User.email", Severity.SAFE,
         "avro-compatibility.compatible"),
    ],
    ids=["add-required", "add-optional", "remove-required", "remove-optional"],
)
def test_add_and_remove_field_grades(old, new, key, severity, rule):
    result = classify_models(_model(old), _model(new))
    (graded,) = [c for c in result.classifications if c.key == key]
    assert (graded.severity, graded.rule_id) == (severity, rule)


def test_the_rationale_names_the_modes_and_confluents_message():
    result = classify_models(_model(_user()), _model(_user({"name": "email", "type": "string"})))
    rationale = result.classifications[0].rationale
    assert rationale.startswith("breaks BACKWARD and FULL")
    assert "errorType:'READER_FIELD_MISSING_DEFAULT_VALUE'" in rationale


def test_an_enum_problem_joins_the_enum_type():
    old = _user({"name": "s", "type": {"type": "enum", "name": "Status", "symbols": ["A", "B"]}})
    new = _user({"name": "s", "type": {"type": "enum", "name": "Status", "symbols": ["A"]}})
    result = classify_models(_model(old), _model(new))
    (graded,) = result.classifications
    assert (graded.key, graded.severity) == ("com.example.Status", Severity.BREAKING)


_PROTOCOL = """@namespace("com.example")
protocol Orders {
  record Order { string id; %s }
  record Audit { string who; }
  Order get(string id);
}
"""


def test_protocol_types_are_compared_by_name():
    old = _model(_PROTOCOL % "", "orders.avdl")
    new = _model(_PROTOCOL % "long total;", "orders.avdl")
    findings, shared = compatibility_findings(old, new)
    assert shared == {"com.example.Order", "com.example.Audit"}
    assert [(d, f.type, f.field) for d, f in findings] == [("backward", "READER_FIELD_MISSING_DEFAULT_VALUE", "total")]
    result = classify_models(old, new)
    assert result.classifier == "avro-compatibility" and result.breaking


def test_without_the_schema_text_the_baseline_stands():
    old, new = _model(_user()), _model(_user({"name": "email", "type": "string"}))
    old.raw, new.raw = None, None
    assert compatibility_findings(old, new) is None
    result = classify_models(old, new)
    assert all(not c.rule_id.startswith("avro-compatibility.") for c in result.classifications)


def test_a_problem_no_change_carries_is_unattributed(monkeypatch: pytest.MonkeyPatch):
    from app import avro_breaking
    from app.avro_compatibility import Incompatibility

    found = Incompatibility("NAME_MISMATCH", "/name", "expected: x.Gone", schema="x.Elsewhere")
    monkeypatch.setattr(avro_breaking, "compatibility_findings", lambda base, target: ([("backward", found)], None))
    result = classify_models(_model(_user()), _model(_user({"name": "email", "type": "string", "default": ""})))
    (unattributed,) = result.unattributed
    assert unattributed.rule_id == "avro-compatibility.name-mismatch" and unattributed.shape == "x.Elsewhere"
    assert result.breaking
