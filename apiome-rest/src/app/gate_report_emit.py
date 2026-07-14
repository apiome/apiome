"""Normalized CI gate emitters: JSON / SARIF / JUnit (CLX-2.3 / #4853).

Consumers emit from Apiome-normalized findings (envelope shape), not raw tool
stdout, so SARIF/JUnit stay consistent across scanners.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Mapping, Optional, Sequence
from xml.dom import minidom

__all__ = [
    "GATE_FORMAT_JSON",
    "GATE_FORMAT_SARIF",
    "GATE_FORMAT_JUNIT",
    "normalize_gate_format",
    "to_normalized_json",
    "to_sarif",
    "to_junit",
    "media_type_for_format",
    "has_breaking_findings",
]

GATE_FORMAT_JSON = "json"
GATE_FORMAT_SARIF = "sarif"
GATE_FORMAT_JUNIT = "junit"

_SARIF_LEVEL = {
    "error": "error",
    "warning": "warning",
    "info": "note",
    "note": "note",
}


def normalize_gate_format(value: Optional[str]) -> str:
    """Normalize a format query/Accept token to json|sarif|junit."""
    if not value:
        return GATE_FORMAT_JSON
    lowered = value.strip().lower()
    if lowered in ("application/sarif+json", "sarif+json", "sarif"):
        return GATE_FORMAT_SARIF
    if lowered in (
        "application/junit+xml",
        "application/xml",
        "text/xml",
        "junit",
        "junit+xml",
    ):
        return GATE_FORMAT_JUNIT
    if lowered in ("application/json", "json"):
        return GATE_FORMAT_JSON
    return GATE_FORMAT_JSON


def media_type_for_format(fmt: str) -> str:
    """HTTP media type for a gate format."""
    resolved = normalize_gate_format(fmt)
    if resolved == GATE_FORMAT_SARIF:
        return "application/sarif+json"
    if resolved == GATE_FORMAT_JUNIT:
        return "application/junit+xml"
    return "application/json"


def _finding_severity(finding: Mapping[str, Any]) -> str:
    change_class = str(finding.get("change_class") or finding.get("changeClass") or "").lower()
    if change_class == "breaking":
        return "error"
    if change_class == "dangerous":
        return "warning"
    sev = str(finding.get("severity") or "info").lower()
    if sev in ("error", "warning", "info"):
        return sev
    return "info"


def has_breaking_findings(findings: Sequence[Mapping[str, Any]]) -> bool:
    """True when any finding is breaking / error-severity with change_class breaking."""
    for finding in findings:
        change_class = str(
            finding.get("change_class") or finding.get("changeClass") or ""
        ).lower()
        if change_class == "breaking":
            return True
        if change_class:
            continue
        if _finding_severity(finding) == "error":
            return True
    return False


def to_normalized_json(
    *,
    findings: Sequence[Mapping[str, Any]],
    scanner_id: str,
    base_revision_id: Optional[str] = None,
    head_revision_id: Optional[str] = None,
    outcome: Optional[str] = None,
    changelog_markdown: Optional[str] = None,
    coverage: Optional[Mapping[str, Any]] = None,
    evidence_run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the Apiome normalized compatibility evidence JSON envelope."""
    breaking = 0
    dangerous = 0
    informational = 0
    for finding in findings:
        cc = str(finding.get("change_class") or finding.get("changeClass") or "").lower()
        if cc == "breaking":
            breaking += 1
        elif cc == "dangerous":
            dangerous += 1
        else:
            informational += 1
    overall = "breaking" if breaking else ("dangerous" if dangerous else "safe")
    payload: Dict[str, Any] = {
        "schemaVersion": 1,
        "scannerId": scanner_id,
        "baseRevisionId": base_revision_id,
        "headRevisionId": head_revision_id,
        "outcome": outcome,
        "overall": overall,
        "counts": {
            "breaking": breaking,
            "dangerous": dangerous,
            "informational": informational,
            "total": len(list(findings)),
        },
        "findings": [dict(f) for f in findings],
        "coverage": dict(coverage) if coverage else {},
        "evidenceRunId": evidence_run_id,
    }
    if changelog_markdown is not None:
        payload["changelogMarkdown"] = changelog_markdown
    return payload


def to_sarif(
    findings: Sequence[Mapping[str, Any]],
    *,
    tool_name: str = "apiome",
    tool_version: str = "1",
    rule_prefix: str = "",
) -> Dict[str, Any]:
    """Emit SARIF 2.1.0 from normalized envelope findings."""
    rules: Dict[str, Dict[str, Any]] = {}
    results: List[Dict[str, Any]] = []
    for finding in findings:
        rule_id = str(finding.get("rule_id") or finding.get("ruleId") or "unknown")
        if rule_prefix and not rule_id.startswith(rule_prefix):
            sarif_rule = f"{rule_prefix}{rule_id}"
        else:
            sarif_rule = rule_id
        if sarif_rule not in rules:
            rules[sarif_rule] = {
                "id": sarif_rule,
                "shortDescription": {"text": sarif_rule},
            }
        location = finding.get("location") if isinstance(finding.get("location"), Mapping) else {}
        uri = str(location.get("path") or finding.get("path") or "openapi.yaml")
        region: Dict[str, Any] = {}
        if isinstance(location.get("start_line"), int) or isinstance(
            location.get("startLine"), int
        ):
            region["startLine"] = int(
                location.get("start_line")
                if location.get("start_line") is not None
                else location["startLine"]
            )
        if isinstance(location.get("start_column"), int) or isinstance(
            location.get("startColumn"), int
        ):
            region["startColumn"] = int(
                location.get("start_column")
                if location.get("start_column") is not None
                else location["startColumn"]
            )
        phys: Dict[str, Any] = {"artifactLocation": {"uri": uri}}
        if region:
            phys["region"] = region
        level = _SARIF_LEVEL.get(_finding_severity(finding), "note")
        properties: Dict[str, Any] = {}
        cc = finding.get("change_class") or finding.get("changeClass")
        if cc:
            properties["changeClass"] = cc
        result: Dict[str, Any] = {
            "ruleId": sarif_rule,
            "level": level,
            "message": {"text": str(finding.get("message") or "")},
            "locations": [{"physicalLocation": phys}],
        }
        if properties:
            result["properties"] = properties
        fp = finding.get("source_fingerprint") or finding.get("sourceFingerprint")
        if fp:
            result["fingerprints"] = {"primaryLocationLineHash": str(fp)}
        results.append(result)

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": tool_name,
                        "version": tool_version,
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
            }
        ],
    }


def to_junit(
    findings: Sequence[Mapping[str, Any]],
    *,
    suite_name: str = "apiome.compatibility",
) -> str:
    """Emit JUnit XML from normalized envelope findings (one failure per finding)."""
    suite = ET.Element(
        "testsuite",
        {
            "name": suite_name,
            "tests": str(len(list(findings))),
            "failures": str(
                sum(1 for f in findings if _finding_severity(f) in ("error", "warning"))
            ),
            "errors": "0",
        },
    )
    if not findings:
        case = ET.SubElement(
            suite,
            "testcase",
            {"classname": suite_name, "name": "no-changes"},
        )
        _ = case
    for finding in findings:
        rule_id = str(finding.get("rule_id") or finding.get("ruleId") or "unknown")
        location = finding.get("location") if isinstance(finding.get("location"), Mapping) else {}
        path = str(location.get("path") or finding.get("path") or "")
        name = f"{rule_id}:{path}" if path else rule_id
        case = ET.SubElement(
            suite,
            "testcase",
            {"classname": suite_name, "name": name[:240]},
        )
        sev = _finding_severity(finding)
        if sev in ("error", "warning"):
            failure = ET.SubElement(
                case,
                "failure",
                {
                    "type": str(
                        finding.get("change_class")
                        or finding.get("changeClass")
                        or sev
                    ),
                    "message": str(finding.get("message") or rule_id)[:500],
                },
            )
            failure.text = str(finding.get("message") or "")
    rough = ET.tostring(suite, encoding="utf-8")
    parsed = minidom.parseString(rough)
    return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def serialize_gate(
    fmt: str,
    *,
    findings: Sequence[Mapping[str, Any]],
    scanner_id: str,
    base_revision_id: Optional[str] = None,
    head_revision_id: Optional[str] = None,
    outcome: Optional[str] = None,
    changelog_markdown: Optional[str] = None,
    coverage: Optional[Mapping[str, Any]] = None,
    evidence_run_id: Optional[str] = None,
    tool_version: str = "1",
) -> tuple[str, str]:
    """Return ``(body, media_type)`` for the requested gate format."""
    resolved = normalize_gate_format(fmt)
    media = media_type_for_format(resolved)
    if resolved == GATE_FORMAT_SARIF:
        body = json.dumps(
            to_sarif(
                findings,
                tool_name=scanner_id,
                tool_version=tool_version,
            ),
            indent=2,
            sort_keys=True,
        )
        return body, media
    if resolved == GATE_FORMAT_JUNIT:
        return to_junit(findings, suite_name=scanner_id), media
    payload = to_normalized_json(
        findings=findings,
        scanner_id=scanner_id,
        base_revision_id=base_revision_id,
        head_revision_id=head_revision_id,
        outcome=outcome,
        changelog_markdown=changelog_markdown,
        coverage=coverage,
        evidence_run_id=evidence_run_id,
    )
    return json.dumps(payload, indent=2, sort_keys=True), media
