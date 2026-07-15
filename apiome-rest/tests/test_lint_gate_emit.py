"""Unit tests for the policy-aware lint gate emitters (CLX-4.2, #4860)."""

from app.gate_report_emit import (
    GATE_FORMAT_ATTESTATION,
    GATE_FORMAT_JSON,
    GATE_FORMAT_MARKDOWN,
    media_type_for_format,
    normalize_gate_format,
)
from app.lint_gate_emit import (
    serialize_lint_gate,
    to_gate_junit,
    to_gate_markdown,
    to_policy_sarif,
)

GATE = {
    "schemaVersion": 1,
    "subjectType": "catalog_revision",
    "subjectId": "v1",
    "projectId": "p1",
    "baselineSubjectId": "v0",
    "newOnly": False,
    "policy": {
        "policyVersionId": "pv1",
        "contentFingerprint": "packfp",
        "ciOutcomes": {
            "failOnUnwaivedErrors": True,
            "failOnRequiredCoverage": False,
            "failOnAxisGates": True,
        },
    },
    "evaluation": {
        "evaluationId": "e1",
        "passed": False,
        "gateResults": {
            "unwaived_errors": {"passed": False, "detail": {}},
            "required_coverage": {"passed": True, "detail": {}},
            "axis_gates": {"passed": True, "detail": {}},
        },
    },
    "gate": {
        "passed": False,
        "newOnly": False,
        "gateResults": {
            "unwaived_errors": {"passed": False, "detail": {}},
            "required_coverage": {"passed": True, "detail": {}},
            "axis_gates": {"passed": True, "detail": {}},
        },
    },
    "counts": {"total": 2, "new": 1, "unwaivedErrors": 1, "waived": 1},
    "newFingerprints": ["fp-1"],
    "findings": [
        {
            "ruleId": "naming.pipe|rule",
            "message": "bad | name",
            "severity": "error",
            "location": {"path": "openapi.yaml", "startLine": 7, "startColumn": 2},
            "sourceFingerprint": "fp-1",
            "scannerId": "apiome.lint",
            "evidenceRunId": "r1",
            "isNew": True,
            "effectiveState": "open",
            "waived": False,
        },
        {
            "ruleId": "docs.rule",
            "message": "missing docs",
            "severity": "warning",
            "location": {"path": "openapi.yaml"},
            "sourceFingerprint": "fp-2",
            "scannerId": "apiome.lint",
            "evidenceRunId": "r1",
            "isNew": False,
            "effectiveState": "waived",
            "waived": True,
            "decisionRationale": "known",
        },
    ],
    "scanners": [
        {
            "scannerId": "apiome.lint",
            "evidenceRunId": "r1",
            "reportFingerprint": "rf1",
            "inputFingerprint": "if1",
            "sourceFingerprint": "sf1",
            "configFingerprint": "cf1",
        }
    ],
    "links": {"evidence": "/e", "policy": "/p", "workspace": "/w"},
}


def test_normalize_format_recognizes_new_tokens():
    assert normalize_gate_format("markdown") == GATE_FORMAT_MARKDOWN
    assert normalize_gate_format("md") == GATE_FORMAT_MARKDOWN
    assert normalize_gate_format("text/markdown") == GATE_FORMAT_MARKDOWN
    assert normalize_gate_format("attestation") == GATE_FORMAT_ATTESTATION
    assert normalize_gate_format("application/vnd.in-toto+json") == GATE_FORMAT_ATTESTATION
    # Existing tokens unaffected (shared with compatibility routes).
    assert normalize_gate_format("sarif") == "sarif"
    assert normalize_gate_format(None) == GATE_FORMAT_JSON
    assert normalize_gate_format("unknown/thing") == GATE_FORMAT_JSON


def test_media_types_for_new_formats():
    assert media_type_for_format("markdown") == "text/markdown; charset=utf-8"
    assert media_type_for_format("attestation") == "application/vnd.in-toto+json"


def test_sarif_result_mapping():
    sarif = to_policy_sarif(GATE, tool_version="9")
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "apiome-lint-gate"
    assert run["tool"]["driver"]["version"] == "9"
    # Verbatim rule ids, even with unusual characters.
    assert {r["id"] for r in run["tool"]["driver"]["rules"]} == {"naming.pipe|rule", "docs.rule"}
    open_result, waived_result = run["results"]
    assert open_result["level"] == "error"
    assert open_result["properties"]["apiome"]["isNew"] is True
    assert "suppressions" not in open_result
    assert waived_result["level"] == "warning"
    assert waived_result["suppressions"][0]["justification"] == "known"
    prov = run["properties"]["apiome"]
    assert prov["policy"]["policyVersionId"] == "pv1"
    assert prov["scanners"][0]["configFingerprint"] == "cf1"


def test_junit_failures_and_skips():
    xml = to_gate_junit(GATE)
    assert 'tests="2"' in xml
    assert 'failures="1"' in xml
    assert 'skipped="1"' in xml
    assert "<skipped" in xml and "waived" in xml
    assert 'name="apiome.subjectId" value="v1"' in xml
    assert 'name="apiome.scanner.apiome.lint.reportFingerprint" value="rf1"' in xml


def test_junit_empty_findings_emits_placeholder():
    empty = {**GATE, "findings": [], "counts": {"total": 0}}
    xml = to_gate_junit(empty)
    assert 'name="no-findings"' in xml
    assert 'failures="0"' in xml


def test_markdown_summary():
    md = to_gate_markdown(GATE)
    assert md.startswith("# Apiome lint gate: ❌ FAILED")
    assert "baseline `v0`" in md
    assert "| Unwaived errors | on | ❌ fail |" in md
    assert "| Required coverage | off | ✅ pass |" in md
    # Pipes in cell values are escaped so the table stays intact.
    assert "naming.pipe\\|rule" in md
    assert "packfp" in md and "rf1" in md
    assert "- evidence: `/e`" in md


def test_serialize_lint_gate_dispatch():
    body, media = serialize_lint_gate("sarif", GATE)
    assert media == "application/sarif+json"
    assert '"apiome-lint-gate"' in body
    body, media = serialize_lint_gate("junit", GATE)
    assert media == "application/junit+xml"
    body, media = serialize_lint_gate("markdown", GATE)
    assert media == "text/markdown; charset=utf-8"
    body, media = serialize_lint_gate("json", GATE)
    assert media == "application/json"
    body, media = serialize_lint_gate("attestation", GATE, secret="s")
    assert media == "application/vnd.in-toto+json"
    assert '"signatures"' in body
