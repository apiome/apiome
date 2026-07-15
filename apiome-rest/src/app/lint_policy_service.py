"""
Policy pack snapshot + evaluation orchestration (CLX-1.3, #4850).

Bridges the pure :mod:`app.policy_evaluate` engine with DB accessors: ensuring a pinned
policy pack exists for the assigned style guide, loading decisions, evaluating gates, and
recording append-only ``lint_policy_evaluations`` rows.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .database import db
from .lint_evidence import (
    SUBJECT_CATALOG_REVISION,
    SUBJECT_MCP_ENDPOINT_VERSION,
    merged_findings_from_runs,
    normalize_native_finding,
)
from .models import (
    LintEvidenceFindingOut,
    LintFindingDecisionOut,
    LintPolicyAnnotatedFindingOut,
    LintPolicyEvaluationOut,
    LintPolicyResponse,
    lint_finding_decision_out_from_row,
    style_guide_policy_version_out_from_row,
)
from .policy_evaluate import (
    default_axis_gates,
    default_ci_outcomes,
    default_required_coverage,
    effective_decision_state,
    evaluate_policy,
    match_decision_for_fingerprint,
    policy_content_fingerprint,
    rules_snapshot_from_rows,
)
from .style_guide_engine import resolve_style_guide


def snapshot_style_guide_policy(
    guide_id: str,
    tenant_id: str,
    *,
    actor_user_id: Optional[str] = None,
    actor_label: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Append an immutable policy pack version from the live guide + rules.

    Args:
        guide_id: Style guide to snapshot.
        tenant_id: Owning tenant.
        actor_user_id: Optional actor user id.
        actor_label: Optional actor label for audit.

    Returns:
        The inserted policy version row, or ``None`` when the guide is missing.
    """
    guide = db.get_style_guide_by_id(guide_id, tenant_id)
    if not guide:
        return None
    rules = db.get_style_guide_rules(guide_id, tenant_id)
    rules_snapshot = rules_snapshot_from_rows(rules)
    axis_gates = default_axis_gates(guide.get("axis_gates"))
    required_coverage = default_required_coverage(guide.get("required_coverage"))
    ci_outcomes = default_ci_outcomes(guide.get("ci_outcomes"))
    fingerprint = policy_content_fingerprint(
        rules_snapshot=rules_snapshot,
        axis_gates=axis_gates,
        required_coverage=required_coverage,
        ci_outcomes=ci_outcomes,
    )
    return db.insert_style_guide_policy_version(
        guide_id=guide_id,
        tenant_id=tenant_id,
        rules_snapshot=rules_snapshot,
        axis_gates=axis_gates,
        required_coverage=required_coverage,
        ci_outcomes=ci_outcomes,
        content_fingerprint=fingerprint,
        actor_user_id=actor_user_id,
        actor_label=actor_label,
    )


def ensure_latest_policy_pack(
    guide_id: str,
    tenant_id: str,
    *,
    actor_user_id: Optional[str] = None,
    actor_label: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return the latest pack for a guide, creating an initial snapshot when none exists."""
    latest = db.get_latest_style_guide_policy_version(guide_id, tenant_id)
    if latest:
        return latest
    return snapshot_style_guide_policy(
        guide_id,
        tenant_id,
        actor_user_id=actor_user_id,
        actor_label=actor_label,
    )


def _findings_from_evidence_or_report(
    evidence_rows: Sequence[Mapping[str, Any]],
    report: Optional[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[str]]:
    """Gather the findings policy is evaluated against: latest evidence run **per scanner**.

    A subject can be scanned by several scanners — an MCP snapshot is covered by both the
    surface lint (``apiome.mcp-lint``) and the protocol-conformance engine
    (``apiome.mcp-conformance``, CLX-3.1); a catalog revision may add Buf or GraphQL ESLint on
    top of the native lint. Each writes its own evidence run.

    Taking only ``evidence_rows[0]`` — the single newest run — would therefore evaluate policy
    against whichever scanner happened to run *last* and silently discard every other scanner's
    findings, so an unwaived error could pass the gate simply because a different scanner ran
    after the one that found it. Instead, the newest run of *each* scanner contributes, which is
    what "the current evidence for this subject" actually means.

    Rows arrive newest-first (``ORDER BY created_at DESC``), so the first row seen for a scanner
    is that scanner's latest run. Scanners are merged in sorted id order for a deterministic
    finding sequence (the shared :func:`app.lint_evidence.merged_findings_from_runs`, also used
    by the CLX-4.1 workspace so the two surfaces can never disagree about "current findings").
    The run id and fingerprint reported alongside remain those of the newest run overall,
    preserving the existing single-scanner behaviour.

    Falls back to the native report when no evidence exists at all.

    Returns:
        (findings, evidence_run_id, evidence_fingerprint)
    """
    if evidence_rows:
        findings = merged_findings_from_runs(evidence_rows)
        newest = evidence_rows[0]
        return findings, str(newest["id"]), newest.get("report_fingerprint")
    if report and isinstance(report.get("findings"), list):
        findings = [
            normalize_native_finding(f) if isinstance(f, Mapping) else {}
            for f in report["findings"]
        ]
        return findings, None, report.get("report_fingerprint")
    return [], None, None


def _decisions_map(
    decisions: Sequence[Mapping[str, Any]],
    fingerprints: Sequence[str],
    *,
    project_id: Optional[str],
) -> Dict[str, Mapping[str, Any]]:
    """Build fingerprint -> best decision for evaluate_policy."""
    out: Dict[str, Mapping[str, Any]] = {}
    for fp in fingerprints:
        hit = match_decision_for_fingerprint(decisions, fp, project_id=project_id)
        if hit:
            out[fp] = hit
    return out


def build_lint_policy_response(
    *,
    tenant_id: str,
    subject_type: str,
    subject_id: str,
    project_id: Optional[str],
    policy_version: Mapping[str, Any],
    findings: Sequence[Mapping[str, Any]],
    axes: Optional[Sequence[Mapping[str, Any]]],
    evidence_run_id: Optional[str],
    axis_evaluation_id: Optional[str],
    evidence_fingerprint: Optional[str],
    decisions: Sequence[Mapping[str, Any]],
    persist: bool = True,
) -> LintPolicyResponse:
    """Evaluate policy, optionally persist, and shape the API response."""
    fps = [
        str(f.get("source_fingerprint") or f.get("id") or "")
        for f in findings
        if (f.get("source_fingerprint") or f.get("id"))
    ]
    by_fp = _decisions_map(decisions, fps, project_id=project_id)
    evaluation = evaluate_policy(
        findings=findings,
        decisions_by_fingerprint=by_fp,
        axes=axes,
        axis_gates=policy_version.get("axis_gates"),
        required_coverage=policy_version.get("required_coverage"),
        ci_outcomes=policy_version.get("ci_outcomes"),
        rules_snapshot=policy_version.get("rules_snapshot") or [],
        content_fingerprint=str(policy_version["content_fingerprint"]),
    )

    eval_id: Optional[str] = None
    if persist:
        row = {
            "subject_type": subject_type,
            "version_record_id": (
                subject_id if subject_type == SUBJECT_CATALOG_REVISION else None
            ),
            "mcp_version_id": (
                subject_id if subject_type == SUBJECT_MCP_ENDPOINT_VERSION else None
            ),
            "policy_version_id": str(policy_version["id"]),
            "policy_content_fingerprint": evaluation.policy_content_fingerprint,
            "evidence_run_id": evidence_run_id,
            "axis_evaluation_id": axis_evaluation_id,
            "evidence_fingerprint": evidence_fingerprint,
            "passed": evaluation.passed,
            "gate_results": evaluation.gate_results,
            "finding_decisions": list(evaluation.finding_decisions),
        }
        try:
            eval_id = db.record_lint_policy_evaluation(row)
        except Exception:  # noqa: BLE001 - persistence is best-effort on read path
            eval_id = None

    policy_out = style_guide_policy_version_out_from_row(policy_version)
    eval_out = LintPolicyEvaluationOut(
        id=eval_id,
        subject_type=subject_type,
        subject_id=subject_id,
        policy_version_id=str(policy_version["id"]),
        policy_content_fingerprint=evaluation.policy_content_fingerprint,
        passed=evaluation.passed,
        gate_results=evaluation.gate_results,
        evaluated_at=None,
    )

    annotated: List[LintPolicyAnnotatedFindingOut] = []
    for finding in findings:
        fp = str(finding.get("source_fingerprint") or finding.get("id") or "")
        decision_row = by_fp.get(fp)
        decision_out: Optional[LintFindingDecisionOut] = (
            lint_finding_decision_out_from_row(decision_row) if decision_row else None
        )
        effective = effective_decision_state(
            decision_row,
            finding_present=True,
        )
        # Rebuild evidence in envelope shape when given native fields.
        if "rule_id" in finding or "source_fingerprint" in finding:
            evidence = LintEvidenceFindingOut(
                rule_id=finding.get("rule_id"),
                message=finding.get("message"),
                severity=finding.get("severity"),
                confidence=finding.get("confidence"),
                category=finding.get("category"),
                location=finding.get("location")
                if isinstance(finding.get("location"), dict)
                else {},
                remediation=finding.get("remediation"),
                source_fingerprint=finding.get("source_fingerprint"),
            )
        else:
            norm = normalize_native_finding(finding)
            evidence = LintEvidenceFindingOut(**norm)
        annotated.append(
            LintPolicyAnnotatedFindingOut(
                evidence=evidence,
                decision=decision_out,
                effective_state=effective,
                waived=effective in ("waived", "fixed", "false_positive"),
            )
        )

    return LintPolicyResponse(
        policy_version=policy_out,
        evaluation=eval_out,
        findings=annotated,
    )


def evaluate_catalog_revision_policy(
    *,
    tenant_id: str,
    project_id: str,
    version_record_id: str,
    policy_version_id: Optional[str] = None,
) -> LintPolicyResponse:
    """Full catalog-revision policy evaluation for GET …/lint/policy."""
    guide = resolve_style_guide(tenant_id, project_id=project_id)
    guide_id = guide.guide_id
    if not guide_id:
        # Fallback guide has no DB id — snapshot is impossible; synthesize ephemeral pack.
        raise ValueError("No assignable style guide for this project")

    if policy_version_id:
        pack = db.get_style_guide_policy_version(policy_version_id, tenant_id)
        if not pack:
            raise LookupError("Policy version not found")
    else:
        pack = ensure_latest_policy_pack(str(guide_id), tenant_id)
        if not pack:
            raise LookupError("Style guide not found")

    evidence_rows = db.list_lint_evidence_runs_for_version(version_record_id, tenant_id)
    captured = db.get_version_quality_score(version_record_id, tenant_id) or {}
    report = (
        captured.get("quality_report")
        if isinstance(captured.get("quality_report"), dict)
        else {}
    )
    findings, evidence_run_id, evidence_fp = _findings_from_evidence_or_report(
        evidence_rows, report
    )

    axis_row = db.get_latest_axis_evaluation_for_version(version_record_id, tenant_id)
    axes = axis_row.get("axes") if axis_row else None
    axis_id = str(axis_row["id"]) if axis_row else None

    fps = [
        str(f.get("source_fingerprint") or "")
        for f in findings
        if f.get("source_fingerprint")
    ]
    decisions = db.list_lint_finding_decisions(
        tenant_id, project_id=project_id, fingerprints=fps or None
    )

    return build_lint_policy_response(
        tenant_id=tenant_id,
        subject_type=SUBJECT_CATALOG_REVISION,
        subject_id=version_record_id,
        project_id=project_id,
        policy_version=pack,
        findings=findings,
        axes=axes if isinstance(axes, list) else None,
        evidence_run_id=evidence_run_id,
        axis_evaluation_id=axis_id,
        evidence_fingerprint=evidence_fp,
        decisions=decisions,
    )


def evaluate_mcp_version_policy(
    *,
    tenant_id: str,
    version_id: str,
    policy_version_id: Optional[str] = None,
) -> LintPolicyResponse:
    """Full MCP endpoint-version policy evaluation for GET …/lint/policy."""
    # MCP uses the tenant default / assigned guide (no project) via resolve without project.
    guide = resolve_style_guide(tenant_id, project_id=None)
    guide_id = guide.guide_id
    if not guide_id:
        raise ValueError("No assignable style guide for this tenant")

    if policy_version_id:
        pack = db.get_style_guide_policy_version(policy_version_id, tenant_id)
        if not pack:
            raise LookupError("Policy version not found")
    else:
        pack = ensure_latest_policy_pack(str(guide_id), tenant_id)
        if not pack:
            raise LookupError("Style guide not found")

    evidence_rows = db.list_lint_evidence_runs_for_mcp_version(version_id)
    score_row = db.get_mcp_version_score(version_id) or {}
    report = score_row.get("report") if isinstance(score_row.get("report"), dict) else {}
    findings, evidence_run_id, evidence_fp = _findings_from_evidence_or_report(
        evidence_rows, report
    )

    axis_row = db.get_latest_axis_evaluation_for_mcp_version(version_id)
    axes = axis_row.get("axes") if axis_row else None
    axis_id = str(axis_row["id"]) if axis_row else None

    fps = [
        str(f.get("source_fingerprint") or "")
        for f in findings
        if f.get("source_fingerprint")
    ]
    decisions = db.list_lint_finding_decisions(tenant_id, fingerprints=fps or None)

    return build_lint_policy_response(
        tenant_id=tenant_id,
        subject_type=SUBJECT_MCP_ENDPOINT_VERSION,
        subject_id=version_id,
        project_id=None,
        policy_version=pack,
        findings=findings,
        axes=axes if isinstance(axes, list) else None,
        evidence_run_id=evidence_run_id,
        axis_evaluation_id=axis_id,
        evidence_fingerprint=evidence_fp,
        decisions=decisions,
    )


__all__ = [
    "build_lint_policy_response",
    "ensure_latest_policy_pack",
    "evaluate_catalog_revision_policy",
    "evaluate_mcp_version_policy",
    "snapshot_style_guide_policy",
]
