"""Evidence exports — JSON, JUnit and SARIF — ECA-1.3 (#4731), XPC-3.2 (#5742).

Stored evidence has to leave the platform in three shapes, for three audiences:

* **JSON** — the whole record, for a gate, a diff between two runs, or an auditor's archive. It is
  the stored record verbatim (timestamps in ISO-8601, keys sorted), so "the export" and "the
  evidence" are never two different truths. That includes the run's mock attestation (PMR-3.2) when
  it recorded one — bundle digest, runtime, corpus, and result — which is what makes the export
  consumable by self-hosted release-proof tooling.
* **JUnit XML** — the lingua franca every CI system already renders. GitHub Actions, GitLab,
  Jenkins, and Buildkite all display it natively, which is what lets contract verification appear
  in a build's test tab without anyone writing a reporter.
* **SARIF 2.1.0** — what code-scanning dashboards ingest (GitHub Code Scanning, Azure DevOps).
  One result per failed or errored case, rendered by :mod:`app.gate_report_emit` like the lint
  and compatibility gates, with a ``partialFingerprints`` entry derived from the case id so
  repeated runs of the same contract de-duplicate rather than pile up.

The acceptance criterion both exporters answer is *reproducibility*: an export must state exactly
what the stored rows state. So neither exporter recomputes a verdict, filters a case, or shortens a
list — :func:`export_junit` emits one ``<testcase>`` per stored case in stored order, and its
counters come from the stored counts, not from re-tallying. If a run says three cases failed, so
does its JUnit.

Both formats are derived from :class:`app.verification_evidence.VerificationRunRecord`, so anything
that has already been redacted stays redacted: an exporter is a rendering, never a second path to
the data.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree

from .gate_report_emit import to_sarif
from .verification_evidence import (
    CODE_EXPORT_FORMAT,
    OPERATION_OUTCOME_ERRORED,
    OPERATION_OUTCOME_FAILED,
    OPERATION_OUTCOME_SKIPPED,
    EvidenceValidationError,
    OperationRecord,
    VerificationRunRecord,
)

__all__ = [
    "EXPORT_EXTENSIONS",
    "EXPORT_FORMATS",
    "EXPORT_SCHEMA_VERSION",
    "EXPORT_FORMAT_JSON",
    "EXPORT_FORMAT_JUNIT",
    "EXPORT_FORMAT_SARIF",
    "EXPORT_MEDIA_TYPES",
    "SARIF_CASE_FINGERPRINT",
    "SARIF_RULE_PREFIX",
    "export_junit",
    "export_sarif",
    "export_json",
    "export_run",
    "run_export_document",
]

EXPORT_FORMAT_JSON = "json"
EXPORT_FORMAT_JUNIT = "junit"
EXPORT_FORMAT_SARIF = "sarif"

#: The formats :func:`export_run` understands.
EXPORT_FORMATS = (EXPORT_FORMAT_JSON, EXPORT_FORMAT_JUNIT, EXPORT_FORMAT_SARIF)

#: Media type each format is served as.
EXPORT_MEDIA_TYPES = {
    EXPORT_FORMAT_JSON: "application/json",
    EXPORT_FORMAT_JUNIT: "application/xml",
    EXPORT_FORMAT_SARIF: "application/sarif+json",
}

#: File extension each format is saved with.
EXPORT_EXTENSIONS = {
    EXPORT_FORMAT_JSON: "json",
    EXPORT_FORMAT_JUNIT: "xml",
    EXPORT_FORMAT_SARIF: "sarif",
}

#: Prefix of every SARIF rule id: the case's stable failure code follows it.
SARIF_RULE_PREFIX = "apiome-contract/"

#: The ``partialFingerprints`` key a SARIF result carries its case id under.
SARIF_CASE_FINGERPRINT = "apiomeContractCase/v1"

#: The envelope version of the JSON export. A consumer that pinned a shape can tell when it moved.
EXPORT_SCHEMA_VERSION = 1

# Characters XML 1.0 cannot represent at all. A runner's failure message may quote a raw response
# body, which can carry a stray control byte; leaving it in produces a file no CI parser will read.
_XML_ILLEGAL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _iso(value: Optional[datetime]) -> Optional[str]:
    """Render a timestamp in ISO-8601, preserving ``None``.

    Args:
        value: The timestamp.

    Returns:
        The ISO-8601 string, or ``None``.
    """
    return value.isoformat() if isinstance(value, datetime) else None


def run_export_document(record: VerificationRunRecord) -> Dict[str, Any]:
    """The JSON-ready document for one run — the stored record, nothing added or dropped.

    Args:
        record: The stored evidence.

    Returns:
        A plain dict: the run, its cases (each with its assertions and artifact references), and
        its run-level artifacts, with every timestamp in ISO-8601.
    """
    document = record.model_dump(mode="json")
    document["export_schema_version"] = EXPORT_SCHEMA_VERSION
    return document


def export_json(record: VerificationRunRecord) -> str:
    """Render one run as JSON.

    Keys are sorted so two exports of the same run are byte-identical — which is what lets a
    consumer store the export and compare it later without a semantic differ.

    Args:
        record: The stored evidence.

    Returns:
        The JSON text.
    """
    return json.dumps(run_export_document(record), sort_keys=True, indent=2, ensure_ascii=False)


def _xml_text(value: Optional[str]) -> str:
    """Make a value safe to place in XML character data.

    ``ElementTree`` escapes ``&``, ``<``, and ``>`` on its own; what it will not do is remove
    control characters that XML 1.0 forbids outright, and a runner message that quotes a raw
    response body can contain them.

    Args:
        value: The text, or ``None``.

    Returns:
        The text with illegal characters stripped; ``""`` for ``None``.
    """
    if value is None:
        return ""
    return _XML_ILLEGAL_RE.sub("", str(value))


def _seconds(duration_ms: int) -> str:
    """Render a millisecond duration as JUnit's fractional seconds.

    Args:
        duration_ms: Duration in milliseconds.

    Returns:
        Seconds with millisecond precision (``"1.250"``).
    """
    return f"{max(0, int(duration_ms)) / 1000:.3f}"


def _failure_detail(operation: OperationRecord) -> str:
    """The body of a JUnit ``<failure>``/``<error>``: the failure plus every assertion that failed.

    A CI viewer shows this text under the test, so it has to answer "what broke" without a trip
    back to the API: the stored failure message first, then one line per failed assertion naming
    what was checked, what was expected, and what came back.

    Args:
        operation: The stored case record.

    Returns:
        The detail text; empty when the case recorded no explanation at all.
    """
    lines: List[str] = []
    if operation.failure_message:
        lines.append(operation.failure_message)
    if operation.expected_status or operation.actual_status is not None:
        lines.append(
            f"expected status {operation.expected_status or '(undeclared)'}, "
            f"got {operation.actual_status if operation.actual_status is not None else '(none)'}"
        )
    for assertion in operation.assertions:
        if assertion.outcome != "failed":
            continue
        subject = f" {assertion.subject}" if assertion.subject else ""
        detail = (
            f"[{assertion.kind}{subject}] {assertion.code or 'assertion-failed'}: "
            f"{assertion.message or ''}".rstrip()
        )
        if assertion.expected is not None or assertion.actual is not None:
            detail += (
                f" (expected: {assertion.expected!r}, actual: {assertion.actual!r})"
            )
        lines.append(detail)
    return "\n".join(lines)


def _mock_properties(record: VerificationRunRecord) -> Dict[str, Optional[str]]:
    """The mock attestation properties a JUnit export carries (PMR-3.2, #4749).

    A CI viewer showing a green contract run should not have to open the JSON export to learn
    whether the mock behind it was verified — and, crucially, should see it when it was **not**.
    So ``apiome.mock.status`` is emitted for every run that recorded a mock, including one whose
    status is ``missing``; a run with no mock at all emits nothing, because it has nothing to say.

    Args:
        record: The stored evidence.

    Returns:
        Property name/value pairs; empty when the run recorded no mock.
    """
    mock = record.mock
    if mock is None:
        return {}
    values: Dict[str, Optional[str]] = {
        "apiome.mock.status": mock.status,
        "apiome.mock.reason_code": mock.reason_code,
    }
    if mock.bundle is not None:
        values["apiome.mock.bundle_digest"] = mock.bundle.digest
    if mock.runtime is not None:
        values["apiome.mock.runtime_version"] = mock.runtime.version
    if mock.conformance is not None:
        values["apiome.mock.corpus_digest"] = mock.conformance.corpus_digest
        values["apiome.mock.conformance"] = (
            f"{mock.conformance.passed}/{mock.conformance.total} passed"
        )
    return values


def _properties_element(record: VerificationRunRecord) -> ElementTree.Element:
    """The ``<properties>`` block carrying what identifies the run.

    JUnit has no place for "which contract, against which target" — so the identity that makes the
    evidence meaningful travels as properties, which every CI viewer displays.

    Args:
        record: The stored evidence.

    Returns:
        The ``<properties>`` element.
    """
    properties = ElementTree.Element("properties")
    values: Dict[str, Optional[str]] = {
        "apiome.run_id": record.id,
        "apiome.suite_digest": record.suite_digest,
        "apiome.outcome": record.outcome,
        "apiome.target_slug": record.target_slug,
        "apiome.target_environment": record.target_environment,
        "apiome.target_network_class": record.target_network_class,
        "apiome.target_base_url": record.target_base_url,
        "apiome.protocol": record.protocol,
        "apiome.runner": record.runner_name,
        "apiome.runner_version": record.runner_version,
        "apiome.started_at": _iso(record.started_at),
        "apiome.finished_at": _iso(record.finished_at),
    }
    values.update(_mock_properties(record))
    for name, value in values.items():
        if value is None:
            continue
        ElementTree.SubElement(
            properties, "property", {"name": name, "value": _xml_text(value)}
        )
    return properties


def export_junit(record: VerificationRunRecord) -> str:
    """Render one run as JUnit XML.

    The mapping is deliberately literal, so a reader of the XML and a reader of the stored record
    reach the same conclusions:

    * ``<testsuite>`` counters come from the **stored counts**, never from re-tallying the cases —
      an export cannot disagree with the run it exports;
    * one ``<testcase>`` per stored case, in stored order, with ``classname`` the operation key and
      ``name`` the case id, so a CI viewer groups by operation;
    * ``failed`` becomes ``<failure>`` and ``errored`` becomes ``<error>``, because JUnit already
      draws the distinction contract verification needs — the implementation contradicted the
      contract, versus the runner never got an answer to judge;
    * ``skipped`` becomes ``<skipped>``; a passing case is an empty ``<testcase>``.

    Args:
        record: The stored evidence.

    Returns:
        The XML text, with an ``<?xml?>`` declaration.
    """
    counts = record.counts or {}
    root = ElementTree.Element(
        "testsuites",
        {
            "name": _xml_text(f"apiome-verification-{record.suite_digest}"),
            "tests": str(counts.get("total", 0)),
            "failures": str(counts.get("failed", 0)),
            "errors": str(counts.get("errored", 0)),
            "skipped": str(counts.get("skipped", 0)),
            "time": _seconds(record.duration_ms),
        },
    )
    suite_attributes = {
        "name": _xml_text(record.target_slug or "verification"),
        "tests": str(counts.get("total", 0)),
        "failures": str(counts.get("failed", 0)),
        "errors": str(counts.get("errored", 0)),
        "skipped": str(counts.get("skipped", 0)),
        "time": _seconds(record.duration_ms),
        "hostname": _xml_text(record.target_base_url),
    }
    timestamp = _iso(record.started_at)
    if timestamp:
        suite_attributes["timestamp"] = timestamp
    suite = ElementTree.SubElement(root, "testsuite", suite_attributes)
    suite.append(_properties_element(record))

    for operation in record.operations:
        case = ElementTree.SubElement(
            suite,
            "testcase",
            {
                "name": _xml_text(operation.case_id),
                "classname": _xml_text(operation.operation_key),
                "time": _seconds(operation.duration_ms),
            },
        )
        if operation.outcome == OPERATION_OUTCOME_SKIPPED:
            ElementTree.SubElement(
                case,
                "skipped",
                {"message": _xml_text(operation.failure_message or operation.failure_code or "")},
            )
            continue
        if operation.outcome not in (OPERATION_OUTCOME_FAILED, OPERATION_OUTCOME_ERRORED):
            continue
        tag = "failure" if operation.outcome == OPERATION_OUTCOME_FAILED else "error"
        element = ElementTree.SubElement(
            case,
            tag,
            {
                "message": _xml_text(
                    operation.failure_message or operation.failure_code or operation.outcome
                ),
                "type": _xml_text(operation.failure_code or operation.outcome),
            },
        )
        element.text = _xml_text(_failure_detail(operation))

    body = ElementTree.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}'


def _sarif_location(record: VerificationRunRecord, operation: OperationRecord) -> str:
    """The artifact URI a SARIF result points at: the contract version, then the operation.

    Evidence is about a contract, not a file in the repository, so the URI names the version
    reference the suite was compiled from (``project/orders/1.0.0``) when the run recorded one,
    followed by the operation key.
    """
    version_ref = record.source.get("version_ref") if isinstance(record.source, dict) else None
    base = str(version_ref) if version_ref else f"suite/{record.suite_digest}"
    return f"{base}/{operation.operation_key}"


def export_sarif(record: VerificationRunRecord) -> str:
    """Render one run as SARIF 2.1.0: one result per failed or errored case.

    A failed case (the deployment disagreed with the contract) is an ``error``; an errored one
    (the case could not be executed) is a ``warning``. Passed and skipped cases are not results —
    SARIF lists problems, not tests. Each result's rule id is the case's stable failure code, its
    message names the operation and the first located violation, and its ``partialFingerprints``
    carry the case id, so the same failure in the next run is the same alert.

    Args:
        record: The stored evidence.

    Returns:
        The SARIF JSON text, keys sorted.
    """
    findings: List[Dict[str, Any]] = []
    for operation in record.operations:
        if operation.outcome not in (OPERATION_OUTCOME_FAILED, OPERATION_OUTCOME_ERRORED):
            continue
        pointer = next(
            (
                item.subject
                for item in operation.assertions
                if item.outcome == "failed" and (item.subject or "").startswith("/")
            ),
            None,
        )
        message = f"{operation.operation_key}: {operation.failure_message or operation.outcome}"
        if pointer:
            message += f" (at {pointer})"
        properties: Dict[str, Any] = {
            "caseId": operation.case_id,
            "operationKey": operation.operation_key,
            "outcome": operation.outcome,
            "protocol": record.protocol,
            "runId": record.id,
        }
        if operation.case_source:
            properties["caseSource"] = operation.case_source
        if pointer:
            properties["pointer"] = pointer
        findings.append(
            {
                "rule_id": operation.failure_code or f"case-{operation.outcome}",
                "severity": "error" if operation.outcome == OPERATION_OUTCOME_FAILED else "warning",
                "message": message,
                "location": {"path": _sarif_location(record, operation)},
                "partial_fingerprints": {SARIF_CASE_FINGERPRINT: operation.case_id},
                "properties": properties,
            }
        )
    document = to_sarif(
        findings,
        tool_name="apiome-contract-verification",
        tool_version=str(record.runner_version or "1"),
        rule_prefix=SARIF_RULE_PREFIX,
    )
    document["runs"][0]["properties"] = {
        "runId": record.id,
        "suiteDigest": record.suite_digest,
        "outcome": record.outcome,
        "protocol": record.protocol,
        "targetSlug": record.target_slug,
    }
    return json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False)


def export_run(record: VerificationRunRecord, export_format: str) -> str:
    """Render one run in the requested format.

    Args:
        record: The stored evidence.
        export_format: ``json``, ``junit``, or ``sarif``.

    Returns:
        The rendered text.

    Raises:
        EvidenceValidationError: ``evidence-export-format-unsupported`` for any other format.
    """
    if export_format == EXPORT_FORMAT_JSON:
        return export_json(record)
    if export_format == EXPORT_FORMAT_JUNIT:
        return export_junit(record)
    if export_format == EXPORT_FORMAT_SARIF:
        return export_sarif(record)
    raise EvidenceValidationError(
        CODE_EXPORT_FORMAT,
        f"export format must be one of {', '.join(EXPORT_FORMATS)}",
    )
