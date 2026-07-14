"""Tests for JSON / SARIF / JUnit gate emitters (CLX-2.3 / #4853)."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from app.gate_report_emit import (
    GATE_FORMAT_JUNIT,
    GATE_FORMAT_SARIF,
    has_breaking_findings,
    normalize_gate_format,
    serialize_gate,
    to_junit,
    to_normalized_json,
    to_sarif,
)


_FINDINGS = [
    {
        "rule_id": "api-path-removed-without-deprecation",
        "message": "api path removed without deprecation",
        "severity": "error",
        "change_class": "breaking",
        "location": {"path": "openapi.yaml", "start_line": 7},
        "source_fingerprint": "abc",
    },
    {
        "rule_id": "response-property-became-required",
        "message": "name became required",
        "severity": "info",
        "change_class": "informational",
        "location": {"path": "revision/openapi.yaml", "start_line": 16},
    },
]


def test_normalize_gate_format_accept_headers():
    assert normalize_gate_format("application/sarif+json") == GATE_FORMAT_SARIF
    assert normalize_gate_format("junit") == GATE_FORMAT_JUNIT
    assert normalize_gate_format(None) == "json"


def test_to_normalized_json_counts_and_overall():
    payload = to_normalized_json(
        findings=_FINDINGS,
        scanner_id="oasdiff.breaking",
        base_revision_id="base",
        head_revision_id="head",
    )
    assert payload["overall"] == "breaking"
    assert payload["counts"]["breaking"] == 1
    assert payload["counts"]["informational"] == 1
    assert payload["counts"]["total"] == 2


def test_to_sarif_preserves_rule_and_location():
    sarif = to_sarif(_FINDINGS, tool_name="oasdiff.breaking")
    assert sarif["version"] == "2.1.0"
    results = sarif["runs"][0]["results"]
    assert results[0]["ruleId"] == "api-path-removed-without-deprecation"
    assert results[0]["level"] == "error"
    assert (
        results[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        == "openapi.yaml"
    )
    assert results[0]["locations"][0]["physicalLocation"]["region"]["startLine"] == 7
    assert results[0]["properties"]["changeClass"] == "breaking"


def test_to_junit_emits_failures_for_breaking():
    xml_text = to_junit(_FINDINGS)
    root = ET.fromstring(xml_text)
    assert root.tag == "testsuite"
    failures = root.findall("testcase/failure")
    assert len(failures) >= 1
    assert "breaking" in (failures[0].get("type") or "")


def test_has_breaking_findings():
    assert has_breaking_findings(_FINDINGS) is True
    assert has_breaking_findings([_FINDINGS[1]]) is False


def test_serialize_gate_sarif_roundtrip():
    body, media = serialize_gate(
        "sarif",
        findings=_FINDINGS,
        scanner_id="oasdiff.breaking",
    )
    assert media == "application/sarif+json"
    parsed = json.loads(body)
    assert parsed["runs"][0]["tool"]["driver"]["name"] == "oasdiff.breaking"
