"""Evidence-run builders for external-linter adapter outcomes (CLX-2.1, #4851).

Maps :class:`~app.external_linter_adapter.AdapterRunResult` (and failure kinds from
:mod:`app.external_linter_runner`) onto the CLX-1.1 evidence-run column shape so
timeout / unavailable / malformed / crash become visible coverage states rather
than silent absence.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from .external_linter_runner import (
    FAILURE_BLOCKED_BY_POLICY,
    FAILURE_CRASH,
    FAILURE_FAILED,
    FAILURE_MALFORMED,
    FAILURE_TIMEOUT,
    FAILURE_UNAVAILABLE,
    AdapterFailureKind,
    failure_kind_to_outcome,
)
from .lint_evidence import (
    COVERAGE_FULL,
    COVERAGE_NONE,
    ENVELOPE_VERSION,
    OUTCOME_FINDINGS,
    OUTCOME_PASSED,
    SUBJECT_CATALOG_REVISION,
    SUBJECT_MCP_ENDPOINT_VERSION,
    redacted_config_fingerprint,
)

__all__ = [
    "adapter_evidence_run",
    "outcome_for_adapter_result",
    "coverage_for_adapter_result",
]


def outcome_for_adapter_result(
    *,
    failure_kind: Optional[AdapterFailureKind] = None,
    findings: Optional[Sequence[Mapping[str, Any]]] = None,
) -> str:
    """Derive the evidence outcome for one adapter run.

    Args:
        failure_kind: Operational failure kind when the tool did not complete cleanly.
        findings: Envelope findings when the run completed.

    Returns:
        A CLX-1.1 outcome string.
    """
    if failure_kind:
        return failure_kind_to_outcome(failure_kind)
    if findings:
        return OUTCOME_FINDINGS
    return OUTCOME_PASSED


def coverage_for_adapter_result(
    *,
    failure_kind: Optional[AdapterFailureKind] = None,
) -> Dict[str, Any]:
    """Coverage state for one adapter run.

    Successful runs (including findings) are ``full``. Unavailable / blocked /
    timeout / crash / malformed leave ``none`` so the scan is visibly incomplete.
    """
    if failure_kind in (
        FAILURE_UNAVAILABLE,
        FAILURE_TIMEOUT,
        FAILURE_CRASH,
        FAILURE_MALFORMED,
        FAILURE_FAILED,
        FAILURE_BLOCKED_BY_POLICY,
    ):
        return {"state": COVERAGE_NONE, "failure_kind": failure_kind}
    return {"state": COVERAGE_FULL}


def adapter_evidence_run(
    *,
    subject_type: str,
    subject_id: str,
    scanner_id: str,
    adapter_version: str,
    findings: Optional[Sequence[Mapping[str, Any]]] = None,
    failure_kind: Optional[AdapterFailureKind] = None,
    profile: str = "adapter-run",
    scanner_version: Optional[str] = None,
    input_fingerprint: Optional[str] = None,
    source_fingerprint: Optional[str] = None,
    config: Optional[Mapping[str, Any]] = None,
    report_fingerprint: Optional[str] = None,
    diagnostics: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a write-ready evidence-run dict for an external-linter adapter result.

    Args:
        subject_type: ``catalog_revision`` or ``mcp_endpoint_version``.
        subject_id: The scanned subject primary key.
        scanner_id: Stable scanner id (e.g. ``buf.lint``).
        adapter_version: Adapter/parser version string.
        findings: Source-neutral envelope findings (empty on operational failure).
        failure_kind: When set, stamps a failure outcome and ``coverage.none``.
        profile: Execution profile label.
        scanner_version: Optional upstream tool version.
        input_fingerprint: Fingerprint of the scanned input, when known.
        source_fingerprint: Fingerprint of the upstream source, when distinct.
        config: Non-persisted config; only its redacted fingerprint is stored.
        report_fingerprint: Optional report fingerprint.
        diagnostics: Short operational diagnostic (stored inside coverage, not as findings).

    Returns:
        Column-name → value dict matching the CLX-1.1 evidence-run shape.
    """
    if subject_type not in (SUBJECT_CATALOG_REVISION, SUBJECT_MCP_ENDPOINT_VERSION):
        raise ValueError(f"Unknown subject_type {subject_type!r}")

    envelope_findings: List[Dict[str, Any]] = [
        dict(f) for f in (findings or [])
    ]
    outcome = outcome_for_adapter_result(
        failure_kind=failure_kind, findings=envelope_findings
    )
    coverage = coverage_for_adapter_result(failure_kind=failure_kind)
    if diagnostics:
        coverage = {**coverage, "diagnostics": diagnostics[:2000]}

    subject_column = (
        "version_record_id"
        if subject_type == SUBJECT_CATALOG_REVISION
        else "mcp_version_id"
    )
    return {
        "subject_type": subject_type,
        subject_column: subject_id,
        "scanner_id": scanner_id,
        "scanner_version": scanner_version,
        "adapter_version": adapter_version,
        "profile": profile,
        "outcome": outcome,
        "input_fingerprint": input_fingerprint,
        "source_fingerprint": source_fingerprint,
        "config_fingerprint": redacted_config_fingerprint(config),
        "raw_artifact_ref": None,
        "report_fingerprint": report_fingerprint,
        "findings": [] if failure_kind else envelope_findings,
        "coverage": coverage,
        "envelope_version": ENVELOPE_VERSION,
    }
