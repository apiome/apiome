"""Tests for the RAML lint pack — MFI-15.3 (#3801).

AMF is a JVM tool the CI runtime does not install, so the SHACL tests replay output recorded from
the real ``amf`` 5.7.1 CLI (``tests/fixtures/raml_amf/recordings``): ``lint-parse`` / ``lint-validate``
on the self-contained ``tests/fixtures/raml_amf/lint/api.raml`` (``amf parse`` refuses it; ``amf
validate`` exits 1 with two example violations) and ``petstore-validate`` (the petstore set
conforms). :func:`test_live_amf_validation_matches_the_recording` runs the real tool when it is
available.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app import raml_amf
from app.fileset import IntakeFileset
from app.import_source import ImportSourceError
from app.lint_engine import lint_canonical_model
from app.raml_amf import read_validation_report, validate_raml_set_with_amf
from app.raml_hygiene import MAX_REPORTED_ISSUES, hygiene_issues, raml_lint_issues, shacl_issues
from app.raml_import_source import RamlImportSource
from app.raml_parser import parse_raml
from app.toolchain_runner import ToolNotAvailableError, ToolRunResult
from tests.test_raml_amf import _petstore_members, _recording, _replay, with_amf, without_amf  # noqa: F401

_LINT_DIR = Path(__file__).resolve().parent / "fixtures" / "raml_amf" / "lint"
_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "raml"

_EXPECTED_SHACL = [
    {
        "severity": "Violation",
        "constraint": "example-validation-error",
        "message": "/id expected type: Integer, found: String; /name expected minLength: 2, actual: 1",
        "file": "api.raml",
        "line": 21,
        "column": 1,
    },
    {
        "severity": "Violation",
        "constraint": "example-validation-error",
        "message": "expected type: Integer, found: String",
        "file": "api.raml",
        "line": 29,
        "column": 18,
    },
]


def _lint_text() -> str:
    return (_LINT_DIR / "api.raml").read_text(encoding="utf-8")


def _rules(issues: List[Dict[str, str]]) -> List[str]:
    return [issue["rule"] for issue in issues]


def _findings(model: Any) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for finding in lint_canonical_model(model).findings:
        payload = finding.as_dict()
        if payload["rule"].startswith("raml."):
            out.setdefault(payload["rule"], []).append(payload)
    return out


# ===========================================================================
# Reading AMF's SHACL report
# ===========================================================================


def test_the_recorded_report_reads_into_located_results():
    recorded = _recording("lint-validate")
    staging = Path("/tmp/staging-x")
    results = read_validation_report(recorded["stdout"].replace("/__STAGING__", str(staging)), staging)
    assert results == _EXPECTED_SHACL


def test_a_conforming_report_has_no_results():
    assert read_validation_report(_recording("petstore-validate")["stdout"], Path("/x")) == []


def test_a_single_unlocated_warning_reads_too():
    report = {
        "@type": "http://www.w3.org/ns/shacl#ValidationReport",
        "http://www.w3.org/ns/shacl#conforms": True,
        "http://www.w3.org/ns/shacl#result": {
            "http://www.w3.org/ns/shacl#resultSeverity": {"@id": "http://www.w3.org/ns/shacl#Warning"},
            "http://www.w3.org/ns/shacl#sourceShape": {"@id": "http://a.ml/vocabularies/amf/parser#some-warning"},
            "http://www.w3.org/ns/shacl#resultMessage": "line one\nline two\n",
        },
    }
    assert read_validation_report(json.dumps(report), Path("/x")) == [
        {"severity": "Warning", "constraint": "some-warning", "message": "line one; line two"}
    ]


@pytest.mark.parametrize("stdout", ["", "not json", '{"@graph": []}'])
def test_output_that_is_not_a_report_reads_as_none(stdout: str):
    assert read_validation_report(stdout, Path("/x")) is None


def test_validate_runs_the_profile_of_the_document(monkeypatch):
    calls = _replay(monkeypatch, "petstore")
    assert validate_raml_set_with_amf(_petstore_members(), "api.raml") == []
    assert calls[0]["args"][0] == "validate"
    assert calls[0]["args"][-2:] == ["-p", "RAML 1.0"]


def test_validate_failures_map_to_intake_codes(monkeypatch):
    def _missing(*_args: Any, **_kwargs: Any) -> ToolRunResult:
        raise ToolNotAvailableError("amf", "amf")

    monkeypatch.setattr(raml_amf, "run_tool_blocking", _missing)
    with pytest.raises(ImportSourceError) as exc:
        validate_raml_set_with_amf({"api.raml": _lint_text()}, "api.raml")
    assert exc.value.code == "ADAPTER_UNAVAILABLE"

    def _garbage(key: str, args: List[str], **_kwargs: Any) -> ToolRunResult:
        return ToolRunResult(key=key, argv=[key, *args], exit_code=0, stdout="nope", stderr="Boom\n", duration_ms=1)

    monkeypatch.setattr(raml_amf, "run_tool_blocking", _garbage)
    with pytest.raises(ImportSourceError) as exc:
        validate_raml_set_with_amf({"api.raml": _lint_text()}, "api.raml")
    assert exc.value.code == "INPUT_MALFORMED"
    assert "Boom" in str(exc.value)


# ===========================================================================
# The import flow with AMF
# ===========================================================================


def test_a_self_contained_document_amf_refuses_imports_with_its_violations(monkeypatch, with_amf):  # noqa: F811
    calls = _replay(monkeypatch, "lint-parse", validate="lint-validate")
    adapter = RamlImportSource()
    document = adapter.parse(_lint_text(), source_label="api.raml")
    assert [call["args"][0] for call in calls] == ["parse", "validate"]
    assert list(document.shacl_results) == _EXPECTED_SHACL
    assert document.model_sha256 is None  # read by the YAML reader
    findings = _findings(adapter.normalize(document))
    assert [(f["path"], f["severity"]) for f in findings["raml.shacl-violation"]] == [
        ("raml:api.raml:21:1", "error"),
        ("raml:api.raml:29:18", "error"),
    ]
    assert findings["raml.shacl-violation"][0]["message"].startswith("example-validation-error: /id expected type")


def test_a_set_amf_parses_is_validated_too(monkeypatch, with_amf):  # noqa: F811
    calls = _replay(monkeypatch, "petstore")
    adapter = RamlImportSource()
    document = adapter.parse_fileset(IntakeFileset.from_members(_petstore_members(), root="api.raml"))
    assert [call["args"][0] for call in calls] == ["parse", "validate"]
    assert document.shacl_results == ()
    assert document.model_sha256 is not None
    assert "raml_lint_issues" not in adapter.normalize(document).extras


def test_a_multi_file_set_amf_refuses_is_still_refused(monkeypatch, with_amf):  # noqa: F811
    calls = _replay(monkeypatch, "missing-title")
    with pytest.raises(ImportSourceError) as exc:
        RamlImportSource().parse_fileset(IntakeFileset.from_members(_petstore_members(), root="api.raml"))
    assert exc.value.code == "INPUT_SEMANTIC_INVALID"
    assert [call["args"][0] for call in calls] == ["parse"]


def test_a_refused_document_the_yaml_reader_cannot_read_keeps_the_amf_error(monkeypatch, with_amf):  # noqa: F811
    _replay(monkeypatch, "missing-title", validate="lint-validate")
    with pytest.raises(ImportSourceError) as exc:
        RamlImportSource().parse("#%RAML 1.0\nversion: v1\n/a:\n  get:\n", source_label="api.raml")
    assert exc.value.code == "INPUT_SEMANTIC_INVALID"
    assert "API title is mandatory" in str(exc.value)


def test_without_amf_only_hygiene_is_reported(without_amf):  # noqa: F811
    adapter = RamlImportSource()
    findings = _findings(adapter.normalize(adapter.parse(_lint_text(), source_label="api.raml")))
    assert not [rule for rule in findings if rule.startswith("raml.shacl")]
    assert set(findings) == {
        "raml.undeclared-security-scheme",
        "raml.unused-base-uri-parameter",
        "raml.unused-uri-parameter",
        "raml.method-without-responses",
    }


# ===========================================================================
# Hygiene
# ===========================================================================


def test_the_lint_fixture_hygiene_issues():
    issues = hygiene_issues(parse_raml(_lint_text()))
    assert [(i["rule"], i["path"]) for i in issues] == [
        ("raml.unused-base-uri-parameter", "baseUriParameters/region"),
        ("raml.undeclared-security-scheme", "/pets/get"),
        ("raml.unused-uri-parameter", "/pets/{petId}/uriParameters/ownerId"),
        ("raml.method-without-responses", "/pets/{petId}/delete"),
    ]
    assert "`oauth`" in issues[1]["message"]


@pytest.mark.parametrize("path", sorted(_EXAMPLES.glob("*.raml")), ids=lambda p: p.name)
def test_the_corpus_has_no_hygiene_issues(path: Path):
    assert hygiene_issues(parse_raml(path.read_text(encoding="utf-8"))) == []


@pytest.mark.parametrize(
    ("schemes", "secured_by", "expected"),
    [
        ("securitySchemes:\n  basic:\n    type: Basic Authentication\n", "[ basic, null ]", []),
        ("", "[ oauth ]", ["oauth"]),
        ("securitySchemes: !include schemes.raml\n", "[ oauth ]", []),
        ("securitySchemes:\n  - basic:\n      type: Basic Authentication\n", "[ basic ]", []),
        ("", "[ lib.oauth ]", []),
        ("securitySchemes:\n  oauth:\n    type: OAuth 2.0\n", "[ oauth: { scopes: [ read ] } ]", []),
    ],
)
def test_security_scheme_resolution(schemes: str, secured_by: str, expected: List[str]):
    text = f"#%RAML 1.0\ntitle: X\n{schemes}securedBy: {secured_by}\n/a:\n  get:\n    responses:\n      200:\n"
    # The hygiene rules read the root as written (`raw`), `!include` values and all; the parsed
    # model here only supplies the operations, so a document the YAML reader refuses still works.
    model = parse_raml("#%RAML 1.0\ntitle: X\n/a:\n  get:\n    responses:\n      200:\n")
    issues = [i for i in hygiene_issues(replace(model, raw=text)) if i["rule"] == "raml.undeclared-security-scheme"]
    assert [i["message"].split("`")[1] for i in issues] == expected


def test_base_uri_parameters_used_in_the_template_are_fine():
    text = (
        "#%RAML 1.0\ntitle: X\nbaseUri: https://{region}.example.com/{+path}\n"
        "baseUriParameters:\n  region: string\n  path: string\n/a:\n  get:\n    responses:\n      204:\n"
    )
    assert hygiene_issues(parse_raml(text)) == []


def test_shacl_issue_paths_and_rules():
    issues = shacl_issues(
        [
            {"severity": "Warning", "constraint": "c", "message": "m", "file": "a.raml", "line": 3, "column": 2},
            {"severity": "Info", "constraint": "", "message": "only", "file": "b.raml"},
            {"severity": "Odd", "message": "x"},
        ]
    )
    assert issues == [
        {"rule": "raml.shacl-warning", "path": "a.raml:3:2", "message": "c: m"},
        {"rule": "raml.shacl-info", "path": "b.raml", "message": "only"},
        {"rule": "raml.shacl-violation", "path": "", "message": "x"},
    ]


def test_issues_are_capped_and_the_overflow_reported(without_amf):  # noqa: F811
    adapter = RamlImportSource()
    document = adapter.parse(_lint_text(), source_label="api.raml")
    many = tuple({"severity": "Violation", "constraint": "c", "message": f"m{i}"} for i in range(MAX_REPORTED_ISSUES))
    model = adapter.normalize(replace(document, shacl_results=many))
    total = len(raml_lint_issues(replace(document, shacl_results=many)))
    assert len(model.extras["raml_lint_issues"]) == MAX_REPORTED_ISSUES
    assert model.extras["raml_lint_issue_count"] == total
    messages = [f["message"] for f in _findings(model)["raml.shacl-violation"]]
    assert f"{total - MAX_REPORTED_ISSUES} more RAML lint issue(s) not listed." in messages


# ===========================================================================
# Live AMF
# ===========================================================================


@pytest.mark.skipif(not raml_amf.amf_available(), reason="AMF (amf) is not installed in this runtime")
def test_live_amf_validation_matches_the_recording():
    assert validate_raml_set_with_amf({"api.raml": _lint_text()}, "api.raml") == _EXPECTED_SHACL
    assert validate_raml_set_with_amf(_petstore_members(), "api.raml") == []
