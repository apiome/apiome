"""
Policy pack evaluation, waivers, and remediation states (CLX-1.3, #4850).

Pure, deterministic evaluation of a pinned style-guide **policy pack** against raw lint
evidence and multi-axis scores. Keeps raw evidence separate from policy decisions:

* Waivers match stable ``source_fingerprint`` values and reopen when expired or when the
  fingerprint no longer appears in evidence (material change).
* CI gates cover unwaived errors, required axis coverage, and per-axis grade/score floors.
* Historical reproducibility comes from pinning ``policy_version_id`` +
  ``content_fingerprint`` on every evaluation.

No DB or network access — persistence lives with callers in :mod:`app.database`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# --- Defaults -------------------------------------------------------------------------------

#: Default required coverage when a guide has no draft / snapshot value (CLX-1.2 compatible).
DEFAULT_REQUIRED_COVERAGE: Tuple[str, ...] = ("quality",)

#: Default CI outcome toggles — all three acceptance gates enabled.
DEFAULT_CI_OUTCOMES: Mapping[str, bool] = {
    "failOnUnwaivedErrors": True,
    "failOnRequiredCoverage": True,
    "failOnAxisGates": True,
}

#: Closed finding lifecycle vocabulary (matches V169 check constraint).
DECISION_STATES: Tuple[str, ...] = (
    "open",
    "acknowledged",
    "waived",
    "fixed",
    "false_positive",
)

#: States that suppress an error-severity finding from the unwaived-errors gate.
SUPPRESSED_FOR_ERRORS: frozenset[str] = frozenset({"waived", "fixed", "false_positive"})

#: Letter grades ordered best → worst for axis gate comparisons.
_GRADE_ORDER: Tuple[str, ...] = ("A", "B", "C", "D", "F")


# --- Fingerprints & defaults ----------------------------------------------------------------


def default_ci_outcomes(raw: Optional[Mapping[str, Any]] = None) -> Dict[str, bool]:
    """Return CI outcome toggles with plan defaults filled for missing keys.

    Args:
        raw: Partial or full ``ci_outcomes`` mapping from a guide / pack, or ``None``.

    Returns:
        A dict with ``failOnUnwaivedErrors``, ``failOnRequiredCoverage``, ``failOnAxisGates``.
    """
    out = dict(DEFAULT_CI_OUTCOMES)
    if not raw:
        return out
    for key in out:
        if key in raw:
            out[key] = bool(raw[key])
        # Accept snake_case aliases from internal callers.
        snake = {
            "failOnUnwaivedErrors": "fail_on_unwaived_errors",
            "failOnRequiredCoverage": "fail_on_required_coverage",
            "failOnAxisGates": "fail_on_axis_gates",
        }[key]
        if snake in raw:
            out[key] = bool(raw[snake])
    return out


def default_required_coverage(raw: Optional[Any] = None) -> List[str]:
    """Return the required-coverage axis list with the quality default.

    Args:
        raw: A JSON list of axis keys, or ``None``.

    Returns:
        A list of axis key strings (at least ``quality`` when empty/None).
    """
    if isinstance(raw, (list, tuple)) and raw:
        return [str(x) for x in raw if x]
    return list(DEFAULT_REQUIRED_COVERAGE)


def default_axis_gates(raw: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Return axis gates mapping (may be empty — no per-axis floors).

    Args:
        raw: Partial gates object, or ``None``.

    Returns:
        A plain dict copy of gates (empty when unset).
    """
    if not isinstance(raw, Mapping):
        return {}
    return {str(k): dict(v) if isinstance(v, Mapping) else v for k, v in raw.items()}


def rules_snapshot_from_rows(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Project live ``style_guide_rules`` rows into a stable snapshot list.

    Args:
        rows: Rule rows with ``rule_id`` / ``enabled`` / ``severity`` / optional ``custom_def``.

    Returns:
        Sorted list of snapshot dicts suitable for packing into ``rules_snapshot``.
    """
    out: List[Dict[str, Any]] = []
    for row in rows:
        item: Dict[str, Any] = {
            "rule_id": str(row.get("rule_id") or ""),
            "enabled": bool(row.get("enabled")),
            "severity": str(row.get("severity") or "warning"),
        }
        custom = row.get("custom_def")
        if custom is not None:
            item["custom_def"] = custom
        out.append(item)
    out.sort(key=lambda r: r["rule_id"])
    return out


def policy_content_fingerprint(
    *,
    rules_snapshot: Sequence[Mapping[str, Any]],
    axis_gates: Mapping[str, Any],
    required_coverage: Sequence[str],
    ci_outcomes: Mapping[str, Any],
) -> str:
    """SHA-256 hex digest of a canonicalized policy pack body.

    Args:
        rules_snapshot: Frozen rule rows.
        axis_gates: Frozen axis gates.
        required_coverage: Frozen required axes.
        ci_outcomes: Frozen CI toggles.

    Returns:
        Hex SHA-256 of the canonical JSON body.
    """
    body = {
        "rules_snapshot": list(rules_snapshot),
        "axis_gates": default_axis_gates(axis_gates),
        "required_coverage": list(required_coverage),
        "ci_outcomes": default_ci_outcomes(ci_outcomes),
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- Decision effective state ---------------------------------------------------------------


def _parse_dt(value: Optional[Any]) -> Optional[datetime]:
    """Parse a datetime or ISO string into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def effective_decision_state(
    decision: Optional[Mapping[str, Any]],
    *,
    now: Optional[datetime] = None,
    finding_present: bool = True,
) -> str:
    """Resolve the effective lifecycle state for gating (evaluate-on-read).

    A stored ``waived`` decision reopens to ``open`` when:
    * ``expires_at`` is in the past, or
    * the finding fingerprint is no longer present in current evidence (material change).

    Args:
        decision: Decision row / mapping, or ``None`` (defaults to ``open``).
        now: Evaluation clock (UTC); defaults to ``datetime.now(timezone.utc)``.
        finding_present: Whether a current evidence finding still carries this fingerprint.

    Returns:
        One of :data:`DECISION_STATES`.
    """
    if not decision:
        return "open"
    state = str(decision.get("state") or "open")
    if state not in DECISION_STATES:
        return "open"
    if state != "waived":
        return state
    if not finding_present:
        return "open"
    expires = _parse_dt(decision.get("expires_at"))
    clock = now or datetime.now(timezone.utc)
    if expires is not None and expires <= clock:
        return "open"
    return "waived"


def _grade_rank(grade: Optional[str]) -> int:
    """Return rank of a letter grade (0 = best). Unknown grades rank worst."""
    g = (grade or "").strip().upper()
    return _GRADE_ORDER.index(g) if g in _GRADE_ORDER else len(_GRADE_ORDER)


def grade_meets_minimum(grade: Optional[str], minimum: Optional[str]) -> bool:
    """True when ``grade`` is at least as good as ``minimum`` (A best, F worst)."""
    if not minimum:
        return True
    return _grade_rank(grade) <= _grade_rank(minimum)


def _finding_fingerprint(finding: Mapping[str, Any]) -> Optional[str]:
    """Extract the stable fingerprint from an envelope or native finding dict."""
    fp = finding.get("source_fingerprint") or finding.get("sourceFingerprint")
    if fp:
        return str(fp)
    # Native findings use ``id`` as the envelope source_fingerprint.
    native_id = finding.get("id")
    if native_id:
        return str(native_id)
    return None


def _finding_severity(finding: Mapping[str, Any]) -> str:
    """Normalize severity to error|warning|info (lowercase)."""
    return str(finding.get("severity") or "").strip().lower()


def _finding_rule_id(finding: Mapping[str, Any]) -> Optional[str]:
    """Extract rule id from envelope (``rule_id``) or native (``rule``) shapes."""
    rid = finding.get("rule_id") or finding.get("ruleId") or finding.get("rule")
    return str(rid) if rid else None


def _axes_by_key(axes: Optional[Sequence[Mapping[str, Any]]]) -> Dict[str, Mapping[str, Any]]:
    """Index axis payloads by ``key``."""
    out: Dict[str, Mapping[str, Any]] = {}
    for axis in axes or []:
        if isinstance(axis, Mapping) and axis.get("key"):
            out[str(axis["key"])] = axis
    return out


# --- Evaluation result ----------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyEvaluation:
    """Rolled-up policy evaluation keeping raw findings separate from decisions.

    Attributes:
        passed: True when every *enabled* CI gate passed.
        gate_results: Per-gate ``{passed, detail}`` for the three acceptance gates.
        finding_decisions: Per-finding projections (fingerprint, raw severity, effective state).
        policy_content_fingerprint: Fingerprint of the pack body used.
    """

    passed: bool
    gate_results: Dict[str, Any]
    finding_decisions: Tuple[Dict[str, Any], ...]
    policy_content_fingerprint: str

    def as_dict(self) -> Dict[str, Any]:
        """Return a JSON-ready dict matching the persisted evaluation shape."""
        return {
            "passed": self.passed,
            "gate_results": dict(self.gate_results),
            "finding_decisions": [dict(f) for f in self.finding_decisions],
            "policy_content_fingerprint": self.policy_content_fingerprint,
        }


def evaluate_policy(
    *,
    findings: Sequence[Mapping[str, Any]],
    decisions_by_fingerprint: Mapping[str, Mapping[str, Any]],
    axes: Optional[Sequence[Mapping[str, Any]]] = None,
    axis_gates: Optional[Mapping[str, Any]] = None,
    required_coverage: Optional[Sequence[str]] = None,
    ci_outcomes: Optional[Mapping[str, Any]] = None,
    rules_snapshot: Optional[Sequence[Mapping[str, Any]]] = None,
    now: Optional[datetime] = None,
    content_fingerprint: Optional[str] = None,
) -> PolicyEvaluation:
    """Evaluate a policy pack against raw findings, decisions, and axis scores.

    Args:
        findings: Evidence findings (envelope or native dicts).
        decisions_by_fingerprint: Map of ``source_fingerprint`` -> decision row.
        axes: Axis payloads from a ``lint_axis_evaluations`` row (or on-the-fly evaluation).
        axis_gates: Per-axis ``{minGrade?, minScore?}`` floors.
        required_coverage: Axes that must be assessed.
        ci_outcomes: Which gates fail the evaluation when violated.
        rules_snapshot: Frozen rules (used only for fingerprint when not supplied).
        now: Clock for waiver expiry (UTC).
        content_fingerprint: Precomputed pack fingerprint; computed when omitted.

    Returns:
        A :class:`PolicyEvaluation` with gate results and per-finding decisions.
    """
    gates = default_axis_gates(axis_gates)
    coverage_axes = default_required_coverage(required_coverage)
    outcomes = default_ci_outcomes(ci_outcomes)
    fp = content_fingerprint or policy_content_fingerprint(
        rules_snapshot=rules_snapshot or [],
        axis_gates=gates,
        required_coverage=coverage_axes,
        ci_outcomes=outcomes,
    )
    clock = now or datetime.now(timezone.utc)

    present_fps = {
        f for f in (_finding_fingerprint(find) for find in findings) if f
    }

    annotated: List[Dict[str, Any]] = []
    unwaived_errors: List[Dict[str, Any]] = []
    for finding in findings:
        source_fp = _finding_fingerprint(finding)
        decision = decisions_by_fingerprint.get(source_fp or "") if source_fp else None
        effective = effective_decision_state(
            decision,
            now=clock,
            finding_present=bool(source_fp and source_fp in present_fps),
        )
        raw_severity = _finding_severity(finding)
        waived = effective in SUPPRESSED_FOR_ERRORS
        row = {
            "source_fingerprint": source_fp,
            "rule_id": _finding_rule_id(finding),
            "raw_severity": raw_severity or None,
            "effective_state": effective,
            "waived": waived,
        }
        annotated.append(row)
        if raw_severity == "error" and not waived:
            unwaived_errors.append(row)

    # --- Gate: unwaived errors --------------------------------------------------------------
    unwaived_gate = {
        "passed": len(unwaived_errors) == 0,
        "detail": {
            "unwaived_error_count": len(unwaived_errors),
            "fingerprints": [e["source_fingerprint"] for e in unwaived_errors],
        },
    }

    # --- Gate: required coverage ------------------------------------------------------------
    by_key = _axes_by_key(axes)
    missing = [
        key
        for key in coverage_axes
        if not (by_key.get(key) and by_key[key].get("assessed") is True)
    ]
    coverage_gate = {
        "passed": len(missing) == 0,
        "detail": {
            "required": list(coverage_axes),
            "missing": missing,
        },
    }

    # --- Gate: axis thresholds --------------------------------------------------------------
    axis_failures: List[Dict[str, Any]] = []
    for axis_key, gate in gates.items():
        if not isinstance(gate, Mapping):
            continue
        axis = by_key.get(str(axis_key))
        if not axis or axis.get("assessed") is not True:
            axis_failures.append(
                {
                    "axis": str(axis_key),
                    "reason": "not_assessed",
                    "gate": dict(gate),
                }
            )
            continue
        min_grade = gate.get("minGrade") or gate.get("min_grade")
        min_score = gate.get("minScore") if "minScore" in gate else gate.get("min_score")
        grade_ok = grade_meets_minimum(axis.get("grade"), min_grade if min_grade else None)
        score_ok = True
        if min_score is not None:
            try:
                score_ok = int(axis.get("score") or 0) >= int(min_score)
            except (TypeError, ValueError):
                score_ok = False
        if not grade_ok or not score_ok:
            axis_failures.append(
                {
                    "axis": str(axis_key),
                    "reason": "below_threshold",
                    "grade": axis.get("grade"),
                    "score": axis.get("score"),
                    "gate": dict(gate),
                }
            )
    axis_gate = {
        "passed": len(axis_failures) == 0,
        "detail": {"failures": axis_failures},
    }

    gate_results = {
        "unwaived_errors": unwaived_gate,
        "required_coverage": coverage_gate,
        "axis_gates": axis_gate,
    }

    enabled_pass = True
    if outcomes["failOnUnwaivedErrors"] and not unwaived_gate["passed"]:
        enabled_pass = False
    if outcomes["failOnRequiredCoverage"] and not coverage_gate["passed"]:
        enabled_pass = False
    if outcomes["failOnAxisGates"] and not axis_gate["passed"]:
        enabled_pass = False

    return PolicyEvaluation(
        passed=enabled_pass,
        gate_results=gate_results,
        finding_decisions=tuple(annotated),
        policy_content_fingerprint=fp,
    )


def match_decision_for_fingerprint(
    decisions: Iterable[Mapping[str, Any]],
    fingerprint: str,
    *,
    project_id: Optional[str] = None,
) -> Optional[Mapping[str, Any]]:
    """Pick the best matching decision for a fingerprint (project scope beats tenant).

    Args:
        decisions: Candidate decision rows (same fingerprint may appear twice with different scopes).
        fingerprint: Finding ``source_fingerprint``.
        project_id: Optional project id for preferring project-scoped rows.

    Returns:
        The matching decision mapping, or ``None``.
    """
    tenant_hit: Optional[Mapping[str, Any]] = None
    for d in decisions:
        if str(d.get("source_fingerprint") or "") != fingerprint:
            continue
        d_project = d.get("project_id")
        if project_id and d_project and str(d_project) == str(project_id):
            return d
        if d_project is None:
            tenant_hit = d
    return tenant_hit


__all__ = [
    "DEFAULT_CI_OUTCOMES",
    "DEFAULT_REQUIRED_COVERAGE",
    "DECISION_STATES",
    "SUPPRESSED_FOR_ERRORS",
    "PolicyEvaluation",
    "default_axis_gates",
    "default_ci_outcomes",
    "default_required_coverage",
    "effective_decision_state",
    "evaluate_policy",
    "grade_meets_minimum",
    "match_decision_for_fingerprint",
    "policy_content_fingerprint",
    "rules_snapshot_from_rows",
]
