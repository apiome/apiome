"""Policy-aware lint gate emitters: SARIF 2.1.0 / JUnit / Markdown (CLX-4.2, #4860).

These emitters consume the **gate payload** built by :func:`app.lint_gate.gate_payload` —
findings already annotated with policy state (``effectiveState`` / ``waived`` / ``isNew``) and
per-scanner provenance fingerprints — so every artifact carries both the raw scanner facts and
the Apiome policy verdict:

* SARIF preserves the scanner's verbatim ``ruleId`` and location, adds the policy state under
  ``result.properties.apiome``, marks waived findings with standard ``suppressions``, and
  records input/scanner/policy/report fingerprints in run-level ``properties.apiome``.
* JUnit maps unwaived error/warning findings to failures and waived findings to skipped cases,
  with provenance in the ``<properties>`` block.
* Markdown renders a human-readable gate summary for PR comments / job summaries.

Format tokens and media types are shared with :mod:`app.gate_report_emit` so ``?format=`` and
``Accept`` behave identically on the compatibility and lint gate endpoints. Payloads carry
fingerprints only — never raw configuration, raw artifacts, or protected source text.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Mapping, Optional, Sequence
from xml.dom import minidom

from .gate_report_emit import (
    GATE_FORMAT_ATTESTATION,
    GATE_FORMAT_JUNIT,
    GATE_FORMAT_MARKDOWN,
    GATE_FORMAT_SARIF,
    media_type_for_format,
    normalize_gate_format,
)

__all__ = [
    "to_policy_sarif",
    "to_gate_junit",
    "to_gate_markdown",
    "serialize_lint_gate",
]

_SARIF_LEVEL = {
    "error": "error",
    "warning": "warning",
    "info": "note",
}


def _severity(finding: Mapping[str, Any]) -> str:
    """Normalize a payload finding's severity to error|warning|info."""
    sev = str(finding.get("severity") or "info").strip().lower()
    return sev if sev in ("error", "warning", "info") else "info"


def _gate_findings(gate: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    """Return the payload findings list (tolerating absent/None)."""
    findings = gate.get("findings")
    return [f for f in findings if isinstance(f, Mapping)] if isinstance(findings, list) else []


def _provenance(gate: Mapping[str, Any]) -> Dict[str, Any]:
    """Run-level provenance block: subject, policy, per-scanner fingerprints, evaluation.

    This is the machine-readable answer to "exactly which input, scanner, policy, and report
    produced this artifact" (#4860 AC: artifacts identify input, scanner, policy, and report
    fingerprints). Values are fingerprints and ids only — nothing here can carry source text
    or credentials.
    """
    return {
        "subjectType": gate.get("subjectType"),
        "subjectId": gate.get("subjectId"),
        "projectId": gate.get("projectId"),
        "baselineSubjectId": gate.get("baselineSubjectId"),
        "newOnly": bool(gate.get("newOnly")),
        "policy": dict(gate.get("policy") or {}),
        "scanners": [dict(s) for s in gate.get("scanners") or []],
        "evaluation": dict(gate.get("evaluation") or {}),
        "gate": dict(gate.get("gate") or {}),
        "links": dict(gate.get("links") or {}),
    }


def to_policy_sarif(gate: Mapping[str, Any], *, tool_version: str = "1") -> Dict[str, Any]:
    """Emit SARIF 2.1.0 from a lint gate payload, preserving policy status.

    Scanner rule ids and locations pass through verbatim; the Apiome policy layer rides in
    ``properties.apiome`` per result plus standard ``suppressions`` for waived / fixed /
    false-positive findings, so SARIF viewers show them as suppressed rather than hiding them.

    Args:
        gate: Payload from :func:`app.lint_gate.gate_payload`.
        tool_version: Version string for the SARIF ``tool.driver``.

    Returns:
        A SARIF 2.1.0 document as a plain dict.
    """
    rules: Dict[str, Dict[str, Any]] = {}
    results: List[Dict[str, Any]] = []
    for finding in _gate_findings(gate):
        rule_id = str(finding.get("ruleId") or "unknown")
        if rule_id not in rules:
            rule: Dict[str, Any] = {
                "id": rule_id,
                "shortDescription": {"text": rule_id},
            }
            if finding.get("scannerId"):
                rule["properties"] = {"scannerId": finding["scannerId"]}
            rules[rule_id] = rule

        location = finding.get("location") if isinstance(finding.get("location"), Mapping) else {}
        phys: Dict[str, Any] = {
            "artifactLocation": {"uri": str(location.get("path") or "openapi.yaml")}
        }
        region: Dict[str, Any] = {}
        if isinstance(location.get("startLine"), int):
            region["startLine"] = location["startLine"]
        if isinstance(location.get("startColumn"), int):
            region["startColumn"] = location["startColumn"]
        if region:
            phys["region"] = region

        apiome_props: Dict[str, Any] = {
            "policyState": finding.get("effectiveState"),
            "waived": bool(finding.get("waived")),
            "isNew": bool(finding.get("isNew")),
            "scannerId": finding.get("scannerId"),
            "sourceFingerprint": finding.get("sourceFingerprint"),
        }
        if finding.get("decisionId"):
            apiome_props["decisionId"] = finding["decisionId"]

        result: Dict[str, Any] = {
            "ruleId": rule_id,
            "level": _SARIF_LEVEL.get(_severity(finding), "note"),
            "message": {"text": str(finding.get("message") or "")},
            "locations": [{"physicalLocation": phys}],
            "properties": {"apiome": apiome_props},
        }
        fp = finding.get("sourceFingerprint")
        if fp:
            result["fingerprints"] = {"primaryLocationLineHash": str(fp)}
        if finding.get("waived"):
            suppression: Dict[str, Any] = {"kind": "external", "status": "accepted"}
            if finding.get("decisionRationale"):
                suppression["justification"] = str(finding["decisionRationale"])
            result["suppressions"] = [suppression]
        results.append(result)

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "automationDetails": {"id": f"apiome/lint-gate/{gate.get('subjectId')}"},
                "tool": {
                    "driver": {
                        "name": "apiome-lint-gate",
                        "version": tool_version,
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
                "properties": {"apiome": _provenance(gate)},
            }
        ],
    }


def to_gate_junit(gate: Mapping[str, Any], *, suite_name: str = "apiome.lint-gate") -> str:
    """Emit JUnit XML from a lint gate payload.

    Unwaived error/warning findings become failures; waived / fixed / false-positive findings
    become skipped cases (visible but not failing, matching how the policy gate treats them).
    An empty findings list emits one passing placeholder case so the suite is never empty.
    Provenance fingerprints ride in the ``<properties>`` block.

    Args:
        gate: Payload from :func:`app.lint_gate.gate_payload`.
        suite_name: JUnit ``testsuite``/``classname`` label.

    Returns:
        Pretty-printed JUnit XML.
    """
    findings = _gate_findings(gate)
    failures = [
        f for f in findings if not f.get("waived") and _severity(f) in ("error", "warning")
    ]
    skipped = [f for f in findings if f.get("waived")]
    suite = ET.Element(
        "testsuite",
        {
            "name": suite_name,
            "tests": str(max(len(findings), 1)),
            "failures": str(len(failures)),
            "skipped": str(len(skipped)),
            "errors": "0",
        },
    )

    properties = ET.SubElement(suite, "properties")
    provenance = _provenance(gate)
    flat: Dict[str, Any] = {
        "apiome.subjectType": provenance["subjectType"],
        "apiome.subjectId": provenance["subjectId"],
        "apiome.policyVersionId": (provenance["policy"] or {}).get("policyVersionId"),
        "apiome.policyContentFingerprint": (provenance["policy"] or {}).get(
            "contentFingerprint"
        ),
        "apiome.gatePassed": (provenance["gate"] or {}).get("passed"),
        "apiome.newOnly": provenance["newOnly"],
    }
    for scanner in provenance["scanners"]:
        sid = str(scanner.get("scannerId") or "")
        flat[f"apiome.scanner.{sid}.reportFingerprint"] = scanner.get("reportFingerprint")
        flat[f"apiome.scanner.{sid}.inputFingerprint"] = scanner.get("inputFingerprint")
        flat[f"apiome.scanner.{sid}.evidenceRunId"] = scanner.get("evidenceRunId")
    for key, value in flat.items():
        if value is not None:
            ET.SubElement(properties, "property", {"name": key, "value": str(value)})

    if not findings:
        ET.SubElement(suite, "testcase", {"classname": suite_name, "name": "no-findings"})
    for finding in findings:
        rule_id = str(finding.get("ruleId") or "unknown")
        location = finding.get("location") if isinstance(finding.get("location"), Mapping) else {}
        path = str(location.get("path") or "")
        name = f"{rule_id}:{path}" if path else rule_id
        case = ET.SubElement(suite, "testcase", {"classname": suite_name, "name": name[:240]})
        if finding.get("waived"):
            ET.SubElement(
                case,
                "skipped",
                {"message": f"waived ({finding.get('effectiveState')})"},
            )
        elif _severity(finding) in ("error", "warning"):
            failure = ET.SubElement(
                case,
                "failure",
                {
                    "type": _severity(finding),
                    "message": str(finding.get("message") or rule_id)[:500],
                },
            )
            failure.text = str(finding.get("message") or "")
    rough = ET.tostring(suite, encoding="utf-8")
    return minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def _md_escape(value: Any) -> str:
    """Escape pipe/newline for a Markdown table cell."""
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def to_gate_markdown(gate: Mapping[str, Any]) -> str:
    """Emit a human-readable Markdown gate summary (PR comments, CI job summaries).

    Args:
        gate: Payload from :func:`app.lint_gate.gate_payload`.

    Returns:
        Markdown text: verdict, gates table, counts, findings table, provenance fingerprints.
    """
    gate_block = gate.get("gate") or {}
    evaluation = gate.get("evaluation") or {}
    policy = gate.get("policy") or {}
    counts = gate.get("counts") or {}
    passed = bool(gate_block.get("passed"))
    lines: List[str] = []
    lines.append(f"# Apiome lint gate: {'✅ PASSED' if passed else '❌ FAILED'}")
    lines.append("")
    lines.append(
        f"Subject `{gate.get('subjectId')}` ({gate.get('subjectType')})"
        + (f", baseline `{gate.get('baselineSubjectId')}`" if gate.get("baselineSubjectId") else "")
        + (" — gating **new findings only**." if gate.get("newOnly") else ".")
    )
    lines.append("")

    ci_outcomes = policy.get("ciOutcomes") or {}
    gate_results = (gate_block.get("gateResults") or evaluation.get("gateResults")) or {}
    configured = {
        "unwaived_errors": ci_outcomes.get("failOnUnwaivedErrors", True),
        "required_coverage": ci_outcomes.get("failOnRequiredCoverage", True),
        "axis_gates": ci_outcomes.get("failOnAxisGates", True),
    }
    lines.append("| Gate | Configured | Result |")
    lines.append("| --- | --- | --- |")
    for key, label in (
        ("unwaived_errors", "Unwaived errors"),
        ("required_coverage", "Required coverage"),
        ("axis_gates", "Axis thresholds"),
    ):
        result = gate_results.get(key) or {}
        status = "✅ pass" if result.get("passed") else "❌ fail"
        lines.append(
            f"| {label} | {'on' if configured[key] else 'off'} | "
            f"{status if result else 'n/a'} |"
        )
    lines.append("")
    lines.append(
        f"**Findings:** {counts.get('total', 0)} total, {counts.get('new', 0)} new, "
        f"{counts.get('unwaivedErrors', 0)} unwaived errors, {counts.get('waived', 0)} waived."
    )
    lines.append("")

    findings = _gate_findings(gate)
    if findings:
        lines.append("| Rule | Severity | State | New | Location | Message |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for finding in findings:
            location = (
                finding.get("location") if isinstance(finding.get("location"), Mapping) else {}
            )
            where = str(location.get("path") or "")
            if isinstance(location.get("startLine"), int):
                where = f"{where}:{location['startLine']}"
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md_escape(finding.get("ruleId")),
                        _md_escape(finding.get("severity")),
                        _md_escape(finding.get("effectiveState")),
                        "yes" if finding.get("isNew") else "",
                        _md_escape(where),
                        _md_escape(str(finding.get("message") or "")[:160]),
                    ]
                )
                + " |"
            )
        lines.append("")

    lines.append("## Provenance")
    lines.append("")
    lines.append(
        f"- Policy pack `{policy.get('policyVersionId')}` "
        f"(fingerprint `{policy.get('contentFingerprint')}`)"
    )
    if evaluation.get("evaluationId"):
        lines.append(f"- Evaluation `{evaluation['evaluationId']}`")
    for scanner in gate.get("scanners") or []:
        lines.append(
            f"- Scanner `{scanner.get('scannerId')}`: report `{scanner.get('reportFingerprint')}`, "
            f"input `{scanner.get('inputFingerprint')}`, evidence run `{scanner.get('evidenceRunId')}`"
        )
    links = gate.get("links") or {}
    if links:
        lines.append("")
        lines.append("## Links")
        lines.append("")
        for name, href in links.items():
            if href:
                lines.append(f"- {name}: `{href}`")
    lines.append("")
    return "\n".join(lines)


def serialize_lint_gate(
    fmt: str,
    gate: Mapping[str, Any],
    *,
    secret: Optional[str] = None,
    tool_version: str = "1",
) -> tuple[str, str]:
    """Return ``(body, media_type)`` for a lint gate payload in the requested format.

    Args:
        fmt: Format or Accept token (json | sarif | junit | markdown | attestation).
        gate: Payload from :func:`app.lint_gate.gate_payload`.
        secret: HMAC signing secret for the attestation format (unsigned when ``None``).
        tool_version: SARIF tool version string.

    Returns:
        Serialized body text and its HTTP media type.
    """
    resolved = normalize_gate_format(fmt)
    media = media_type_for_format(resolved)
    if resolved == GATE_FORMAT_SARIF:
        return (
            json.dumps(to_policy_sarif(gate, tool_version=tool_version), indent=2, sort_keys=True),
            media,
        )
    if resolved == GATE_FORMAT_JUNIT:
        return to_gate_junit(gate), media
    if resolved == GATE_FORMAT_MARKDOWN:
        return to_gate_markdown(gate), media
    if resolved == GATE_FORMAT_ATTESTATION:
        # Local import: lint_attestation pulls in app config; keep this module import-light.
        from .lint_attestation import attestation_envelope, build_attestation_statement

        statement = build_attestation_statement(gate)
        return (
            json.dumps(attestation_envelope(statement, secret=secret), indent=2, sort_keys=True),
            media,
        )
    return json.dumps(dict(gate), indent=2, sort_keys=True, default=str), media
