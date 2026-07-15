"""Lint CI gate evaluation: policy + baseline compare + provenance (CLX-4.2, #4860).

The gate turns already-recorded lint evidence (CLX-1.1) and the pinned policy pack (CLX-1.3)
into one machine-readable verdict a CI job can act on:

* **Policy** — the full :func:`app.policy_evaluate.evaluate_policy` over the subject's current
  findings (latest evidence run per scanner), persisted as a reproducible
  ``lint_policy_evaluations`` row exactly like ``GET …/lint/policy``.
* **Regressions** — a finding is *new* when its fingerprint appears in a scanner's newest run
  but not in the comparison run for that scanner: the baseline subject's latest run when a
  baseline is given, else the scanner's own previous run (CLX-4.1 semantics — a scanner's
  first run counts entirely as new).
* **New-only gating** — with ``new_only`` the CI verdict (``gate_passed``) re-evaluates the
  unwaived-errors gate over only the new findings, so pre-existing debt does not block a
  merge. Required-coverage and axis gates are properties of the head revision and are NOT
  filtered — a revision that lost coverage fails regardless of which findings are new.
* **Provenance** — the payload identifies input, scanner, policy, and report fingerprints for
  every contributing evidence run, and carries fingerprints ONLY: raw configuration, raw
  artifacts, and protected source never enter the payload.

Webhook side effects (``lint.regression.detected`` / ``lint.coverage.failed``) fire only from
gate evaluation — a deliberate CI action — never from plain policy reads.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .database import db
from .lint_evidence import (
    SUBJECT_CATALOG_REVISION,
    SUBJECT_MCP_ENDPOINT_VERSION,
    latest_runs_by_scanner,
)
from .lint_policy_service import (
    findings_from_evidence_or_report,
    resolve_policy_pack,
)
from .policy_evaluate import (
    PolicyEvaluation,
    default_ci_outcomes,
    effective_decision_state,
    evaluate_policy,
    match_decision_for_fingerprint,
)

_logger = logging.getLogger(__name__)

__all__ = [
    "GateEvaluation",
    "evaluate_lint_gate",
    "gate_payload",
    "new_fingerprints_for_runs",
]


def _finding_fingerprint(finding: Mapping[str, Any]) -> Optional[str]:
    """Stable fingerprint from an envelope (or native) finding dict."""
    fp = finding.get("source_fingerprint") or finding.get("id")
    return str(fp) if fp else None


def _run_fingerprints(run: Mapping[str, Any]) -> Set[str]:
    """The set of finding fingerprints one evidence run carries."""
    out: Set[str] = set()
    for finding in run.get("findings") or []:
        if isinstance(finding, Mapping):
            fp = _finding_fingerprint(finding)
            if fp:
                out.add(fp)
    return out


def new_fingerprints_for_runs(
    head_rows: Sequence[Mapping[str, Any]],
    baseline_rows: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Set[str]:
    """Fingerprints that are newly introduced in the head subject's evidence.

    Comparison is per scanner (CLX-4.1 semantics, shared with the lint workspace): each
    scanner's newest head run is diffed against that same scanner's comparison run — the
    baseline subject's latest run when ``baseline_rows`` is given, else the scanner's own
    previous run within ``head_rows``. A scanner with no comparison run counts entirely as
    new (a first scan can only introduce findings).

    Args:
        head_rows: Evidence rows for the head subject, newest first.
        baseline_rows: Evidence rows for the baseline subject (newest first), or ``None``
            to compare against each scanner's previous head run.

    Returns:
        The set of newly introduced ``source_fingerprint`` values.
    """
    head_latest = latest_runs_by_scanner(head_rows)
    new_fps: Set[str] = set()
    if baseline_rows is not None:
        baseline_latest = latest_runs_by_scanner(baseline_rows)
        for scanner_id, run in head_latest.items():
            head_fps = _run_fingerprints(run)
            previous = baseline_latest.get(scanner_id)
            previous_fps = _run_fingerprints(previous) if previous else set()
            new_fps |= head_fps - previous_fps
        return new_fps

    by_scanner: Dict[str, List[Mapping[str, Any]]] = {}
    for row in head_rows:
        by_scanner.setdefault(str(row.get("scanner_id") or ""), []).append(row)
    for scanner_id, runs in by_scanner.items():
        head_fps = _run_fingerprints(runs[0])
        previous_fps = _run_fingerprints(runs[1]) if len(runs) > 1 else None
        new_fps |= head_fps if previous_fps is None else head_fps - previous_fps
    return new_fps


@dataclass
class GateEvaluation:
    """One lint gate verdict with everything its artifacts need.

    Attributes:
        subject_type: ``catalog_revision`` | ``mcp_endpoint_version``.
        subject_id: The evaluated revision / snapshot id.
        project_id: Owning project (catalog subjects only).
        tenant_slug: Slug for building API links (optional).
        policy_version: The pinned policy pack row.
        evaluation: Full policy evaluation over ALL current findings (persisted).
        evaluation_id: Persisted ``lint_policy_evaluations`` row id, when recording succeeded.
        gate_evaluation: Evaluation driving the CI verdict (== ``evaluation`` unless new-only).
        gate_passed: The CI verdict.
        new_only: Whether the unwaived-errors gate was scoped to new findings.
        baseline_subject_id: The compared-against subject, when supplied.
        findings: Envelope findings annotated with scannerId / isNew / policy state.
        new_fingerprints: Newly introduced fingerprints (sorted for determinism).
        regressions: New, error-severity, unwaived findings.
        scanners: Per-scanner provenance (fingerprints + evidence run ids only).
    """

    subject_type: str
    subject_id: str
    project_id: Optional[str]
    tenant_slug: Optional[str]
    policy_version: Mapping[str, Any]
    evaluation: PolicyEvaluation
    evaluation_id: Optional[str]
    gate_evaluation: PolicyEvaluation
    gate_passed: bool
    new_only: bool
    baseline_subject_id: Optional[str]
    findings: List[Dict[str, Any]] = field(default_factory=list)
    new_fingerprints: List[str] = field(default_factory=list)
    regressions: List[Dict[str, Any]] = field(default_factory=list)
    scanners: List[Dict[str, Any]] = field(default_factory=list)


def _annotated_findings(
    evidence_rows: Sequence[Mapping[str, Any]],
    fallback_findings: Sequence[Mapping[str, Any]],
    *,
    new_fps: Set[str],
    decisions: Sequence[Mapping[str, Any]],
    project_id: Optional[str],
) -> List[Dict[str, Any]]:
    """Merge findings per scanner and annotate each with attribution + policy state.

    Walks scanners in sorted id order over each scanner's newest run — the exact ordering of
    :func:`app.lint_evidence.merged_findings_from_runs` — so the gate can never disagree with
    the policy and workspace surfaces about the current finding sequence, while keeping the
    ``scanner_id`` / evidence-run attribution the merged list drops. Falls back to the native
    report findings (no scanner attribution) when no evidence rows exist.
    """
    annotated: List[Dict[str, Any]] = []

    def annotate(
        finding: Mapping[str, Any],
        *,
        scanner_id: Optional[str],
        evidence_run_id: Optional[str],
    ) -> Dict[str, Any]:
        fp = _finding_fingerprint(finding)
        decision = match_decision_for_fingerprint(decisions, fp, project_id=project_id) if fp else None
        effective = effective_decision_state(decision, finding_present=True)
        location = finding.get("location") if isinstance(finding.get("location"), Mapping) else {}
        return {
            "rule_id": finding.get("rule_id") or finding.get("rule"),
            "message": finding.get("message"),
            "severity": finding.get("severity"),
            "confidence": finding.get("confidence"),
            "category": finding.get("category"),
            "location": dict(location),
            "remediation": finding.get("remediation"),
            "source_fingerprint": fp,
            "scanner_id": scanner_id,
            "evidence_run_id": evidence_run_id,
            "is_new": bool(fp and fp in new_fps),
            "effective_state": effective,
            "waived": effective in ("waived", "fixed", "false_positive"),
            "decision_id": str(decision["id"]) if decision and decision.get("id") else None,
            "decision_rationale": decision.get("rationale") if decision else None,
        }

    if evidence_rows:
        latest = latest_runs_by_scanner(evidence_rows)
        for scanner_id in sorted(latest):
            run = latest[scanner_id]
            run_id = str(run.get("id")) if run.get("id") else None
            for finding in run.get("findings") or []:
                if isinstance(finding, Mapping):
                    annotated.append(
                        annotate(finding, scanner_id=scanner_id, evidence_run_id=run_id)
                    )
        return annotated

    for finding in fallback_findings:
        annotated.append(annotate(finding, scanner_id=None, evidence_run_id=None))
    return annotated


def _scanner_provenance(evidence_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Per-scanner provenance from each scanner's newest run — fingerprints and ids only.

    ``raw_artifact_ref`` and any raw configuration are deliberately excluded: output artifacts
    must identify inputs without being able to leak them (#4860 AC-5).
    """
    latest = latest_runs_by_scanner(evidence_rows)
    out: List[Dict[str, Any]] = []
    for scanner_id in sorted(latest):
        run = latest[scanner_id]
        out.append(
            {
                "scanner_id": scanner_id,
                "scanner_version": run.get("scanner_version"),
                "adapter_version": run.get("adapter_version"),
                "profile": run.get("profile"),
                "outcome": run.get("outcome"),
                "evidence_run_id": str(run.get("id")) if run.get("id") else None,
                "report_fingerprint": run.get("report_fingerprint"),
                "input_fingerprint": run.get("input_fingerprint"),
                "source_fingerprint": run.get("source_fingerprint"),
                "config_fingerprint": run.get("config_fingerprint"),
                "recorded_at": str(run.get("created_at")) if run.get("created_at") else None,
            }
        )
    return out


def _load_subject_evidence(
    *,
    tenant_id: str,
    subject_type: str,
    subject_id: str,
) -> Tuple[List[Dict[str, Any]], Optional[Mapping[str, Any]]]:
    """Load evidence rows + native-report fallback for one subject."""
    if subject_type == SUBJECT_CATALOG_REVISION:
        rows = db.list_lint_evidence_runs_for_version(subject_id, tenant_id)
        captured = db.get_version_quality_score(subject_id, tenant_id) or {}
        report = (
            captured.get("quality_report")
            if isinstance(captured.get("quality_report"), dict)
            else None
        )
        return rows, report
    rows = db.list_lint_evidence_runs_for_mcp_version(subject_id)
    score_row = db.get_mcp_version_score(subject_id) or {}
    report = score_row.get("report") if isinstance(score_row.get("report"), dict) else None
    return rows, report


def evaluate_lint_gate(
    *,
    tenant_id: str,
    subject_type: str,
    subject_id: str,
    project_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
    baseline_subject_id: Optional[str] = None,
    policy_version_id: Optional[str] = None,
    new_only: bool = False,
    persist: bool = True,
    notify: bool = True,
) -> GateEvaluation:
    """Evaluate the lint CI gate for one subject.

    Args:
        tenant_id: Caller's tenant.
        subject_type: ``catalog_revision`` | ``mcp_endpoint_version``.
        subject_id: Revision / snapshot to gate.
        project_id: Owning project for catalog subjects (guides + decision scoping).
        tenant_slug: Slug used only to render API links in the payload.
        baseline_subject_id: Optional subject to diff regressions against (route layer must
            validate it belongs to the same project / endpoint).
        policy_version_id: Optional historical pack to pin.
        new_only: Scope the unwaived-errors CI verdict to newly introduced findings.
        persist: Record the full evaluation as a ``lint_policy_evaluations`` row.
        notify: Fire regression / coverage-failure webhooks (best-effort).

    Returns:
        A :class:`GateEvaluation`.

    Raises:
        ValueError: No assignable style guide (HTTP 409 at the route layer).
        LookupError: Unknown policy version / style guide (HTTP 404 at the route layer).
    """
    pack = resolve_policy_pack(
        tenant_id, project_id=project_id, policy_version_id=policy_version_id
    )

    evidence_rows, report = _load_subject_evidence(
        tenant_id=tenant_id, subject_type=subject_type, subject_id=subject_id
    )
    findings, evidence_run_id, evidence_fp = findings_from_evidence_or_report(
        evidence_rows, report
    )

    baseline_rows: Optional[List[Dict[str, Any]]] = None
    if baseline_subject_id:
        baseline_rows, _ = _load_subject_evidence(
            tenant_id=tenant_id, subject_type=subject_type, subject_id=baseline_subject_id
        )
    new_fps = new_fingerprints_for_runs(evidence_rows, baseline_rows)

    if subject_type == SUBJECT_CATALOG_REVISION:
        axis_row = db.get_latest_axis_evaluation_for_version(subject_id, tenant_id)
    else:
        axis_row = db.get_latest_axis_evaluation_for_mcp_version(subject_id)
    axes = axis_row.get("axes") if axis_row else None
    axes = axes if isinstance(axes, list) else None
    axis_id = str(axis_row["id"]) if axis_row else None

    fps = [fp for fp in (_finding_fingerprint(f) for f in findings) if fp]
    decisions = db.list_lint_finding_decisions(
        tenant_id, project_id=project_id, fingerprints=fps or None
    )
    by_fp: Dict[str, Mapping[str, Any]] = {}
    for fp in fps:
        hit = match_decision_for_fingerprint(decisions, fp, project_id=project_id)
        if hit:
            by_fp[fp] = hit

    evaluation = evaluate_policy(
        findings=findings,
        decisions_by_fingerprint=by_fp,
        axes=axes,
        axis_gates=pack.get("axis_gates"),
        required_coverage=pack.get("required_coverage"),
        ci_outcomes=pack.get("ci_outcomes"),
        rules_snapshot=pack.get("rules_snapshot") or [],
        content_fingerprint=str(pack["content_fingerprint"]),
    )

    evaluation_id: Optional[str] = None
    if persist:
        row = {
            "subject_type": subject_type,
            "version_record_id": (
                subject_id if subject_type == SUBJECT_CATALOG_REVISION else None
            ),
            "mcp_version_id": (
                subject_id if subject_type == SUBJECT_MCP_ENDPOINT_VERSION else None
            ),
            "policy_version_id": str(pack["id"]),
            "policy_content_fingerprint": evaluation.policy_content_fingerprint,
            "evidence_run_id": evidence_run_id,
            "axis_evaluation_id": axis_id,
            "evidence_fingerprint": evidence_fp,
            "passed": evaluation.passed,
            "gate_results": evaluation.gate_results,
            "finding_decisions": list(evaluation.finding_decisions),
        }
        try:
            evaluation_id = db.record_lint_policy_evaluation(row)
        except Exception:  # noqa: BLE001 - persistence is best-effort, gating must not 500
            _logger.warning(
                "Failed to persist lint gate evaluation for %s %s",
                subject_type,
                subject_id,
                exc_info=True,
            )

    # New-only verdict: the unwaived-errors gate re-runs over only-new findings. Coverage and
    # axis gates come from the FULL evaluation — they describe the head revision itself.
    gate_evaluation = evaluation
    if new_only:
        new_findings = [f for f in findings if (_finding_fingerprint(f) or "") in new_fps]
        filtered = evaluate_policy(
            findings=new_findings,
            decisions_by_fingerprint=by_fp,
            axes=axes,
            axis_gates=pack.get("axis_gates"),
            required_coverage=pack.get("required_coverage"),
            ci_outcomes=pack.get("ci_outcomes"),
            rules_snapshot=pack.get("rules_snapshot") or [],
            content_fingerprint=str(pack["content_fingerprint"]),
        )
        gate_evaluation = filtered
    gate_passed = gate_evaluation.passed

    annotated = _annotated_findings(
        evidence_rows,
        findings,
        new_fps=new_fps,
        decisions=decisions,
        project_id=project_id,
    )
    regressions = [
        f
        for f in annotated
        if f["is_new"] and str(f.get("severity") or "").lower() == "error" and not f["waived"]
    ]

    gate = GateEvaluation(
        subject_type=subject_type,
        subject_id=subject_id,
        project_id=project_id,
        tenant_slug=tenant_slug,
        policy_version=pack,
        evaluation=evaluation,
        evaluation_id=evaluation_id,
        gate_evaluation=gate_evaluation,
        gate_passed=gate_passed,
        new_only=new_only,
        baseline_subject_id=baseline_subject_id,
        findings=annotated,
        new_fingerprints=sorted(new_fps),
        regressions=regressions,
        scanners=_scanner_provenance(evidence_rows),
    )

    if notify:
        _notify_gate_outcomes(gate, tenant_id=tenant_id)
    return gate


def _notify_gate_outcomes(gate: GateEvaluation, *, tenant_id: str) -> None:
    """Fire regression / coverage-failure webhooks for one gate run (best-effort)."""
    # Local import: lint_notifications imports nothing from here, but keeping the dependency
    # at call time makes the gate importable in webhook-less test contexts.
    from .lint_notifications import notify_lint_coverage_failed, notify_lint_regression

    links = _links(gate)
    try:
        if gate.regressions:
            notify_lint_regression(
                db,
                tenant_id=tenant_id,
                subject_type=gate.subject_type,
                subject_id=gate.subject_id,
                project_id=gate.project_id,
                baseline_subject_id=gate.baseline_subject_id,
                new_fingerprints=[f["source_fingerprint"] for f in gate.regressions],
                regression_count=len(gate.regressions),
                policy_version_id=str(gate.policy_version.get("id")),
                policy_content_fingerprint=gate.evaluation.policy_content_fingerprint,
                evaluation_id=gate.evaluation_id,
                links=links,
            )
    except Exception:  # noqa: BLE001 - notifications never break gating
        _logger.warning("lint.regression.detected notification failed", exc_info=True)

    try:
        coverage_gate = gate.evaluation.gate_results.get("required_coverage") or {}
        ci_outcomes = default_ci_outcomes(gate.policy_version.get("ci_outcomes"))
        if coverage_gate and coverage_gate.get("passed") is False and ci_outcomes.get(
            "failOnRequiredCoverage"
        ):
            detail = coverage_gate.get("detail") or {}
            notify_lint_coverage_failed(
                db,
                tenant_id=tenant_id,
                subject_type=gate.subject_type,
                subject_id=gate.subject_id,
                project_id=gate.project_id,
                missing_axes=list(detail.get("missing") or []),
                required_axes=list(detail.get("required") or []),
                policy_version_id=str(gate.policy_version.get("id")),
                evaluation_id=gate.evaluation_id,
                links=links,
            )
    except Exception:  # noqa: BLE001 - notifications never break gating
        _logger.warning("lint.coverage.failed notification failed", exc_info=True)


def _links(gate: GateEvaluation) -> Dict[str, Optional[str]]:
    """API links a CI consumer can follow from the artifact to full evidence."""
    if gate.subject_type == SUBJECT_CATALOG_REVISION and gate.tenant_slug and gate.project_id:
        base = f"/v1/versions/{gate.tenant_slug}/{gate.project_id}/{gate.subject_id}/lint"
        workspace = f"/v1/lint/workspace/findings?tenant_slug={gate.tenant_slug}"
        if gate.project_id:
            workspace += f"&projectId={gate.project_id}"
        return {
            "evidence": f"{base}/evidence",
            "policy": f"{base}/policy",
            "workspace": workspace,
        }
    if gate.subject_type == SUBJECT_MCP_ENDPOINT_VERSION and gate.tenant_slug:
        workspace = f"/v1/lint/workspace/findings?tenant_slug={gate.tenant_slug}"
        return {"evidence": None, "policy": None, "workspace": workspace}
    return {"evidence": None, "policy": None, "workspace": None}


def _camel_finding(finding: Mapping[str, Any]) -> Dict[str, Any]:
    """Project one annotated finding into the camelCase payload shape."""
    location = finding.get("location") if isinstance(finding.get("location"), Mapping) else {}
    camel_location: Dict[str, Any] = {}
    if location.get("path") is not None:
        camel_location["path"] = location.get("path")
    start_line = location.get("start_line", location.get("startLine"))
    start_column = location.get("start_column", location.get("startColumn"))
    if isinstance(start_line, int):
        camel_location["startLine"] = start_line
    if isinstance(start_column, int):
        camel_location["startColumn"] = start_column
    return {
        "ruleId": finding.get("rule_id"),
        "message": finding.get("message"),
        "severity": finding.get("severity"),
        "confidence": finding.get("confidence"),
        "category": finding.get("category"),
        "location": camel_location,
        "remediation": finding.get("remediation"),
        "sourceFingerprint": finding.get("source_fingerprint"),
        "scannerId": finding.get("scanner_id"),
        "evidenceRunId": finding.get("evidence_run_id"),
        "isNew": bool(finding.get("is_new")),
        "effectiveState": finding.get("effective_state"),
        "waived": bool(finding.get("waived")),
        "decisionId": finding.get("decision_id"),
        "decisionRationale": finding.get("decision_rationale"),
    }


def gate_payload(gate: GateEvaluation) -> Dict[str, Any]:
    """Shape one gate evaluation into the camelCase JSON envelope all emitters consume.

    This is the ``format=json`` response body, the input to the SARIF / JUnit / Markdown
    emitters, and the source of the attestation predicate. It contains ids and fingerprints
    only — never raw scanner configuration, raw artifacts, or source text.
    """
    findings = [_camel_finding(f) for f in gate.findings]
    counts = {
        "total": len(findings),
        "new": sum(1 for f in findings if f["isNew"]),
        "unwaivedErrors": sum(
            1
            for f in findings
            if not f["waived"] and str(f.get("severity") or "").lower() == "error"
        ),
        "waived": sum(1 for f in findings if f["waived"]),
    }
    scanners = [
        {
            "scannerId": s.get("scanner_id"),
            "scannerVersion": s.get("scanner_version"),
            "adapterVersion": s.get("adapter_version"),
            "profile": s.get("profile"),
            "outcome": s.get("outcome"),
            "evidenceRunId": s.get("evidence_run_id"),
            "reportFingerprint": s.get("report_fingerprint"),
            "inputFingerprint": s.get("input_fingerprint"),
            "sourceFingerprint": s.get("source_fingerprint"),
            "configFingerprint": s.get("config_fingerprint"),
            "recordedAt": s.get("recorded_at"),
        }
        for s in gate.scanners
    ]
    return {
        "schemaVersion": 1,
        "subjectType": gate.subject_type,
        "subjectId": gate.subject_id,
        "projectId": gate.project_id,
        "baselineSubjectId": gate.baseline_subject_id,
        "newOnly": gate.new_only,
        "policy": {
            "policyVersionId": str(gate.policy_version.get("id")),
            "contentFingerprint": gate.evaluation.policy_content_fingerprint,
            "ciOutcomes": default_ci_outcomes(gate.policy_version.get("ci_outcomes")),
        },
        "evaluation": {
            "evaluationId": gate.evaluation_id,
            "passed": gate.evaluation.passed,
            "gateResults": dict(gate.evaluation.gate_results),
        },
        "gate": {
            "passed": gate.gate_passed,
            "newOnly": gate.new_only,
            "gateResults": dict(gate.gate_evaluation.gate_results),
        },
        "counts": counts,
        "newFingerprints": list(gate.new_fingerprints),
        "findings": findings,
        "scanners": scanners,
        "links": _links(gate),
    }
