"""
Policy pack snapshot + evaluation orchestration (CLX-1.3, #4850).

Bridges the pure :mod:`app.policy_evaluate` engine with DB accessors: ensuring a pinned
policy pack exists for the assigned style guide, loading decisions, evaluating gates, and
recording append-only ``lint_policy_evaluations`` rows.

GVM-1.2 (#5855): when the pack carries a maturity ladder, every evaluation also runs the pure
:func:`app.maturity_ladder.evaluate_ladder` and stores its result as
``gate_results.maturity`` (plus the ``maturity_level`` column). :func:`ladder_evidence`
gathers the evidence a ladder asks for, and :func:`evaluate_catalog_revision_level` /
:func:`evaluate_mcp_version_level` back the ``GET …/lint/level`` reads.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .database import db
from .lint_evidence import (
    SUBJECT_CATALOG_REVISION,
    SUBJECT_MCP_ENDPOINT_VERSION,
    merged_findings_from_runs,
    normalize_native_finding,
)
from .maturity_ladder import evaluate_ladder, no_ladder_result
from .models import (
    LintEvidenceFindingOut,
    LintFindingDecisionOut,
    LintLevelBlockerOut,
    LintLevelResponse,
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
from .style_guide_ladder import ladder_from_row

logger = logging.getLogger(__name__)

#: Evidence kinds a ladder level may require (GVM-1.1 vocabulary).
EVIDENCE_REVIEW_APPROVED = "review_approved"
EVIDENCE_VERIFICATION_PASSING = "verification_passing"


def snapshot_style_guide_policy(
    guide_id: str,
    tenant_id: str,
    *,
    actor_user_id: Optional[str] = None,
    actor_label: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Append an immutable policy pack version from the live guide + rules + ladder.

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
    # GVM-1.1 (#5854): the maturity ladder is frozen beside rules and gates.
    ladder = ladder_from_row(db.get_style_guide_ladder(guide_id, tenant_id))
    fingerprint = policy_content_fingerprint(
        rules_snapshot=rules_snapshot,
        axis_gates=axis_gates,
        required_coverage=required_coverage,
        ci_outcomes=ci_outcomes,
        ladder=ladder,
    )
    return db.insert_style_guide_policy_version(
        guide_id=guide_id,
        tenant_id=tenant_id,
        rules_snapshot=rules_snapshot,
        axis_gates=axis_gates,
        required_coverage=required_coverage,
        ci_outcomes=ci_outcomes,
        content_fingerprint=fingerprint,
        ladder=ladder,
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


def findings_from_evidence_or_report(
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


# Backwards-compatible alias for the pre-#4860 private name.
_findings_from_evidence_or_report = findings_from_evidence_or_report


def resolve_policy_pack(
    tenant_id: str,
    *,
    project_id: Optional[str] = None,
    policy_version_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve the policy pack an evaluation should be pinned to (CLX-4.2, #4860).

    Shared by the catalog / MCP policy evaluations and the lint gate: resolves the assigned
    style guide (project scope when given, tenant default otherwise), then either loads the
    explicitly requested historical pack or ensures the latest snapshot exists.

    Args:
        tenant_id: Caller's tenant.
        project_id: Project scope for guide resolution; ``None`` for tenant scope (MCP).
        policy_version_id: Optional historical pack id to pin instead of the latest.

    Returns:
        The policy version row.

    Raises:
        ValueError: No assignable style guide (callers map this to HTTP 409).
        LookupError: Requested pack / guide not found (callers map this to HTTP 404).
    """
    guide = resolve_style_guide(tenant_id, project_id=project_id)
    guide_id = guide.guide_id
    if not guide_id:
        scope = "project" if project_id else "tenant"
        raise ValueError(f"No assignable style guide for this {scope}")

    if policy_version_id:
        pack = db.get_style_guide_policy_version(policy_version_id, tenant_id)
        if not pack:
            raise LookupError("Policy version not found")
        return pack
    pack = ensure_latest_policy_pack(str(guide_id), tenant_id)
    if not pack:
        raise LookupError("Style guide not found")
    return pack


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


def _required_evidence(ladder: Optional[Mapping[str, Any]]) -> List[str]:
    """Every evidence kind any level of ``ladder`` requires, in first-seen order."""
    kinds: List[str] = []
    for level in (ladder or {}).get("levels") or []:
        for kind in level.get("evidence") or []:
            if kind not in kinds:
                kinds.append(kind)
    return kinds


def _review_approved(tenant_id: str, project_id: str, version_record_id: str) -> Optional[bool]:
    """Whether the revision's open review is approved, per the COL-2.3 approval gate.

    The guide's own approval policy is used when it is on; otherwise a single approval of the
    current round counts, so a ladder can ask for review evidence in a tenant that does not
    gate publishing on approvals. ``None`` when the review could not be read.
    """
    from .approval_publish_gate import (
        STATUS_BLOCKED,
        STATUS_SATISFIED,
        ApprovalPolicy,
        assess_approval_gate,
        resolve_approval_policy,
    )

    version = db.get_version_by_id(version_record_id, tenant_id)
    if not version:
        return None
    policy = resolve_approval_policy(tenant_id, project_id)
    if not policy.active:
        policy = ApprovalPolicy(required_approvals=1)
    status = assess_approval_gate(
        tenant_id=tenant_id, project_id=project_id, version=version, policy=policy
    ).status
    if status == STATUS_SATISFIED:
        return True
    if status == STATUS_BLOCKED:
        return False
    return None


def _verification_passing(tenant_id: str, version_record_id: str) -> Optional[bool]:
    """Whether the revision's latest verification-policy evaluation (ECA-1.4) passed.

    Read, never re-run: evaluating the verification policy records its own audit row. ``None``
    when the revision has no evaluation or the policy judged no gate (nothing was verified).
    """
    rows = db.list_verification_policy_evaluations(
        tenant_id, version_record_id=version_record_id, limit=1
    )
    if not rows:
        return None
    latest = rows[0]
    if not latest.get("gate_results"):
        return None
    return bool(latest.get("passed"))


def ladder_evidence(
    *,
    tenant_id: str,
    subject_type: str,
    subject_id: str,
    project_id: Optional[str],
    ladder: Optional[Mapping[str, Any]],
) -> Dict[str, Optional[bool]]:
    """Gather the evidence ``ladder`` requires for one subject. Never raises.

    Only the kinds some level asks for are read. Review and verification evidence exist for
    catalog revisions; for an MCP endpoint version they are ``None`` (not assessed), so a level
    that requires them is blocked with ``reason: not_assessed`` rather than passed.

    Args:
        tenant_id: The subject's tenant.
        subject_type: ``catalog_revision`` or ``mcp_endpoint_version``.
        subject_id: The revision or MCP version id.
        project_id: The revision's project (``None`` for MCP).
        ladder: The pack's ``{name, levels}`` ladder, or ``None``.

    Returns:
        ``{kind: True | False | None}`` for each required kind.
    """
    out: Dict[str, Optional[bool]] = {}
    for kind in _required_evidence(ladder):
        value: Optional[bool] = None
        if subject_type == SUBJECT_CATALOG_REVISION and project_id:
            try:
                if kind == EVIDENCE_REVIEW_APPROVED:
                    value = _review_approved(tenant_id, project_id, subject_id)
                elif kind == EVIDENCE_VERIFICATION_PASSING:
                    value = _verification_passing(tenant_id, subject_id)
            except Exception:  # noqa: BLE001 - unreadable evidence is not assessed, not a 500
                logger.warning(
                    "Could not read %s evidence for %s %s", kind, subject_type, subject_id,
                    exc_info=True,
                )
                value = None
        out[kind] = value
    return out


def maturity_gate_result(
    *,
    policy_version: Mapping[str, Any],
    findings: Sequence[Mapping[str, Any]],
    axes: Optional[Sequence[Mapping[str, Any]]],
    decisions_by_fingerprint: Mapping[str, Mapping[str, Any]],
    evidence: Optional[Mapping[str, Optional[bool]]],
) -> Optional[Dict[str, Any]]:
    """Judge the pack's ladder, or return ``None`` when the pack has no ladder.

    The one call every evaluation path makes (``build_lint_policy_response`` and the lint
    gate), so ``gate_results.maturity`` is always produced by :func:`evaluate_ladder`.
    """
    ladder = ladder_from_row(policy_version.get("ladder"))
    if ladder is None:
        return None
    return evaluate_ladder(
        findings, axes, decisions_by_fingerprint, ladder, evidence=evidence
    )


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
    evidence: Optional[Mapping[str, Optional[bool]]] = None,
) -> LintPolicyResponse:
    """Evaluate policy, optionally persist, and shape the API response.

    When the pack carries a ladder, ``gate_results.maturity`` holds the level result
    (GVM-1.2) judged with ``evidence`` (see :func:`ladder_evidence`). Persisting unchanged
    inputs returns the stored evaluation's id and time.
    """
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
    gate_results = dict(evaluation.gate_results)
    maturity = maturity_gate_result(
        policy_version=policy_version,
        findings=findings,
        axes=axes,
        decisions_by_fingerprint=by_fp,
        evidence=evidence,
    )
    if maturity is not None:
        gate_results["maturity"] = maturity

    eval_id: Optional[str] = None
    evaluated_at: Optional[str] = None
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
            "gate_results": gate_results,
            "finding_decisions": list(evaluation.finding_decisions),
            "maturity_level": maturity.get("level") if maturity else None,
        }
        try:
            stored = db.record_lint_policy_evaluation_row(row)
        except Exception:  # noqa: BLE001 - persistence is best-effort on read path
            stored = None
        if stored:
            eval_id = str(stored["id"])
            stamp = stored.get("evaluated_at")
            evaluated_at = stamp.isoformat() if hasattr(stamp, "isoformat") else stamp

    policy_out = style_guide_policy_version_out_from_row(policy_version)
    eval_out = LintPolicyEvaluationOut(
        id=eval_id,
        subject_type=subject_type,
        subject_id=subject_id,
        policy_version_id=str(policy_version["id"]),
        policy_content_fingerprint=evaluation.policy_content_fingerprint,
        passed=evaluation.passed,
        gate_results=gate_results,
        evaluated_at=evaluated_at,
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
    pack = resolve_policy_pack(
        tenant_id, project_id=project_id, policy_version_id=policy_version_id
    )

    evidence_rows = db.list_lint_evidence_runs_for_version(version_record_id, tenant_id)
    captured = db.get_version_quality_score(version_record_id, tenant_id) or {}
    report = (
        captured.get("quality_report")
        if isinstance(captured.get("quality_report"), dict)
        else {}
    )
    findings, evidence_run_id, evidence_fp = findings_from_evidence_or_report(
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
    evidence = ladder_evidence(
        tenant_id=tenant_id,
        subject_type=SUBJECT_CATALOG_REVISION,
        subject_id=version_record_id,
        project_id=project_id,
        ladder=ladder_from_row(pack.get("ladder")),
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
        evidence=evidence,
    )


def evaluate_mcp_version_policy(
    *,
    tenant_id: str,
    version_id: str,
    policy_version_id: Optional[str] = None,
) -> LintPolicyResponse:
    """Full MCP endpoint-version policy evaluation for GET …/lint/policy."""
    # MCP uses the tenant default / assigned guide (no project scope).
    pack = resolve_policy_pack(tenant_id, policy_version_id=policy_version_id)

    evidence_rows = db.list_lint_evidence_runs_for_mcp_version(version_id)
    score_row = db.get_mcp_version_score(version_id) or {}
    report = score_row.get("report") if isinstance(score_row.get("report"), dict) else {}
    findings, evidence_run_id, evidence_fp = findings_from_evidence_or_report(
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
    evidence = ladder_evidence(
        tenant_id=tenant_id,
        subject_type=SUBJECT_MCP_ENDPOINT_VERSION,
        subject_id=version_id,
        project_id=None,
        ladder=ladder_from_row(pack.get("ladder")),
    )

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
        evidence=evidence,
    )


def level_response(policy: LintPolicyResponse) -> LintLevelResponse:
    """Project a policy evaluation onto the ``GET …/lint/level`` response (GVM-1.2).

    The level comes from the evaluation's ``gate_results.maturity``; a pack without a ladder
    carries none, and the response says ``level: null, reason: no-ladder``.
    """
    evaluation = policy.evaluation
    maturity = evaluation.gate_results.get("maturity")
    result = dict(maturity) if isinstance(maturity, Mapping) else no_ladder_result()
    return LintLevelResponse(
        subject_type=evaluation.subject_type,
        subject_id=evaluation.subject_id,
        evaluation_id=evaluation.id,
        evaluated_at=evaluation.evaluated_at,
        policy_version_id=evaluation.policy_version_id,
        policy_content_fingerprint=evaluation.policy_content_fingerprint,
        ladder_name=result.get("ladderName"),
        level=result.get("level"),
        level_label=result.get("levelLabel"),
        level_index=result.get("levelIndex"),
        next_level=result.get("nextLevel"),
        next_level_label=result.get("nextLevelLabel"),
        blockers=[LintLevelBlockerOut.model_validate(b) for b in result.get("blockers") or []],
        waivers_counted=int(result.get("waiversCounted") or 0),
        unassessed_axes=list(result.get("unassessedAxes") or []),
        reason=result.get("reason"),
    )


def evaluate_catalog_revision_level(
    *,
    tenant_id: str,
    project_id: str,
    version_record_id: str,
    policy_version_id: Optional[str] = None,
) -> LintLevelResponse:
    """The maturity level of a catalog revision for ``GET …/lint/level`` (GVM-1.2).

    Stored-first: the policy evaluation is recomputed from current evidence, and when nothing
    changed the stored row is returned with its original id and time; only a changed input
    (evidence, axes, a decision, the pack) records a new evaluation.
    """
    return level_response(
        evaluate_catalog_revision_policy(
            tenant_id=tenant_id,
            project_id=project_id,
            version_record_id=version_record_id,
            policy_version_id=policy_version_id,
        )
    )


def evaluate_mcp_version_level(
    *,
    tenant_id: str,
    version_id: str,
    policy_version_id: Optional[str] = None,
) -> LintLevelResponse:
    """The maturity level of an MCP endpoint version for ``GET …/lint/level`` (GVM-1.2)."""
    return level_response(
        evaluate_mcp_version_policy(
            tenant_id=tenant_id,
            version_id=version_id,
            policy_version_id=policy_version_id,
        )
    )


__all__ = [
    "build_lint_policy_response",
    "ensure_latest_policy_pack",
    "evaluate_catalog_revision_level",
    "evaluate_catalog_revision_policy",
    "evaluate_mcp_version_level",
    "evaluate_mcp_version_policy",
    "ladder_evidence",
    "level_response",
    "maturity_gate_result",
    "snapshot_style_guide_policy",
]
