"""
Multi-axis score and coverage model (CLX-1.2, #4849).

Turns a native lint/score report into a transparent, versioned set of axes so a single A–F
grade no longer hides whether a defect is definition quality, protocol conformance, security,
supply chain, supportability, or compatibility — and so "not assessed" is never conflated with
a clean (zero-finding) score.

Algorithm id ``clx-axis-v1``:

* **quality** — backwards-compatible axis = the legacy ``score`` / ``grade`` when present.
* **security** (MCP only) — scored from native findings whose ``category`` is ``security``.
* **compatibility** (catalog only) — scored from findings whose ``category`` is
  ``compatibility`` when a base revision comparison produced them.
* **protocol / supply_chain / supportability** — explicit not assessed until their scanners
  exist (later CLX work).

Composite is published only when required coverage is present (v1: ``quality`` assessed).
Participating axes are assessed axes whose coverage state is not ``none``. Weights are equal
(``1.0``) for transparency. Scoring of non-quality axes reuses the same severity penalty model
as :mod:`app.schema_lint` / :mod:`app.mcp_score`.

Pure and deterministic: no DB or network access. Persistence lives with callers in
:mod:`app.database`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .lint_evidence import (
    COVERAGE_FULL,
    COVERAGE_NONE,
    SUBJECT_CATALOG_REVISION,
    SUBJECT_MCP_ENDPOINT_VERSION,
)
from .schema_lint import GRADE_THRESHOLDS, PER_RULE_PENALTY_CAP, SEVERITY_PENALTY

# --- Algorithm identity ---------------------------------------------------------------------

#: Stable scoring algorithm id stored with every evaluation. Bump when the axis set, weights,
#: mapping rules, or composite formula change in a way that requires re-interpretation.
ALGORITHM_ID = "clx-axis-v1"

#: Implementation revision of :data:`ALGORITHM_ID` (stored alongside for audit).
ALGORITHM_VERSION = "1"

#: Axes that must be assessed before a composite may be published (v1).
REQUIRED_AXES_FOR_COMPOSITE: Tuple[str, ...] = ("quality",)

#: Equal weight for every axis in the catalog (transparency for v1).
DEFAULT_AXIS_WEIGHT: float = 1.0

# --- Axis catalogue -------------------------------------------------------------------------

AXIS_QUALITY = "quality"
AXIS_PROTOCOL = "protocol"
AXIS_SECURITY = "security"
AXIS_SUPPLY_CHAIN = "supply_chain"
AXIS_SUPPORTABILITY = "supportability"
AXIS_COMPATIBILITY = "compatibility"

AXIS_KEYS: Tuple[str, ...] = (
    AXIS_QUALITY,
    AXIS_PROTOCOL,
    AXIS_SECURITY,
    AXIS_SUPPLY_CHAIN,
    AXIS_SUPPORTABILITY,
    AXIS_COMPATIBILITY,
)

AXIS_LABELS: Mapping[str, str] = {
    AXIS_QUALITY: "Quality",
    AXIS_PROTOCOL: "Protocol",
    AXIS_SECURITY: "Security",
    AXIS_SUPPLY_CHAIN: "Supply chain",
    AXIS_SUPPORTABILITY: "Supportability",
    AXIS_COMPATIBILITY: "Compatibility",
}

REASON_PROTOCOL = "No protocol-conformance scanner evidence yet"
REASON_SUPPLY_CHAIN = "No supply-chain scanner evidence yet"
REASON_SUPPORTABILITY = "No supportability scanner evidence yet"
REASON_SECURITY_CATALOG = "No security scanner evidence for catalog revisions yet"
REASON_COMPAT_MCP = "Compatibility axis applies to catalog revisions"
REASON_COMPAT_NO_BASE = "No base-revision compatibility evidence"
REASON_QUALITY_MISSING = "No quality score has been captured for this subject yet"


@dataclass(frozen=True)
class AxisEvaluation:
    """Rolled-up multi-axis evaluation for one subject under one algorithm.

    Attributes:
        algorithm_id: Stable algorithm id (``clx-axis-v1``).
        algorithm_version: Implementation revision of the algorithm.
        axes: Ordered axis payloads (canonical key order).
        composite_score: Weighted composite when required coverage is met; else ``None``.
        composite_grade: A–F grade of the composite; else ``None``.
        required_coverage_met: Whether required axes are assessed.
        source_report_fingerprint: Fingerprint of the source report, when known.
    """

    algorithm_id: str
    algorithm_version: str
    axes: Tuple[Dict[str, Any], ...]
    composite_score: Optional[int]
    composite_grade: Optional[str]
    required_coverage_met: bool
    source_report_fingerprint: Optional[str]

    def as_dict(self) -> Dict[str, Any]:
        """Return a JSON-ready dict matching the persisted ``lint_axis_evaluations`` shape."""
        return {
            "algorithm_id": self.algorithm_id,
            "algorithm_version": self.algorithm_version,
            "axes": [dict(a) for a in self.axes],
            "composite_score": self.composite_score,
            "composite_grade": self.composite_grade,
            "required_coverage_met": self.required_coverage_met,
            "source_report_fingerprint": self.source_report_fingerprint,
        }


def grade_for_score(score: int) -> str:
    """Map a 0–100 ``score`` to its A–F letter grade via the house thresholds."""
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def score_from_finding_dicts(findings: Iterable[Mapping[str, Any]]) -> int:
    """Deterministic 0–100 score from finding dicts (same penalty model as schema/MCP lint).

    Each finding contributes its severity penalty keyed by ``rule`` / ``rule_id``; per-rule
    contribution is capped at :data:`PER_RULE_PENALTY_CAP`. An empty finding set scores 100
    (clean) — callers must not use this for not-assessed axes.
    """
    penalty_by_rule: Dict[str, float] = {}
    for finding in findings:
        severity = str(finding.get("severity") or "")
        rule = str(finding.get("rule") or finding.get("rule_id") or "")
        if not rule:
            rule = "_unnamed"
        weight = SEVERITY_PENALTY.get(severity, 0.0)
        penalty_by_rule[rule] = penalty_by_rule.get(rule, 0.0) + weight
    total_penalty = sum(min(p, PER_RULE_PENALTY_CAP) for p in penalty_by_rule.values())
    return max(0, min(100, round(100.0 - total_penalty)))


def severity_counts(findings: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    """Count findings per severity; always returns error/warning/info keys."""
    counts = {"error": 0, "warning": 0, "info": 0}
    for finding in findings:
        sev = finding.get("severity")
        if sev in counts:
            counts[str(sev)] += 1
    return counts


def _not_assessed(key: str, reason: str) -> Dict[str, Any]:
    """Build one not-assessed axis payload (coverage ``none``, null score/grade)."""
    return {
        "key": key,
        "label": AXIS_LABELS[key],
        "weight": DEFAULT_AXIS_WEIGHT,
        "assessed": False,
        "score": None,
        "grade": None,
        "severity_counts": {"error": 0, "warning": 0, "info": 0},
        "coverage": {"state": COVERAGE_NONE},
        "not_assessed_reason": reason,
    }


def _assessed(
    key: str,
    score: int,
    grade: Optional[str] = None,
    *,
    findings: Sequence[Mapping[str, Any]] = (),
    coverage_state: str = COVERAGE_FULL,
) -> Dict[str, Any]:
    """Build one assessed axis payload. Empty findings ⇒ clean 100, not a gap."""
    return {
        "key": key,
        "label": AXIS_LABELS[key],
        "weight": DEFAULT_AXIS_WEIGHT,
        "assessed": True,
        "score": int(score),
        "grade": grade or grade_for_score(int(score)),
        "severity_counts": severity_counts(findings),
        "coverage": {"state": coverage_state},
        "not_assessed_reason": None,
    }


def _finding_category(finding: Mapping[str, Any]) -> str:
    return str(finding.get("category") or "").strip().lower()


def _filter_by_category(
    findings: Sequence[Mapping[str, Any]], category: str
) -> List[Mapping[str, Any]]:
    target = category.lower()
    return [f for f in findings if _finding_category(f) == target]


def _quality_axis(
    report: Mapping[str, Any],
    *,
    findings: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Map the legacy report score/grade into the backwards-compatible quality axis."""
    score = report.get("score")
    if score is None:
        return _not_assessed(AXIS_QUALITY, REASON_QUALITY_MISSING)
    grade = report.get("grade")
    # Quality severity tallies exclude findings remapped onto other axes so severity
    # counts do not double-count across axes.
    quality_findings = [
        f
        for f in findings
        if _finding_category(f) not in (AXIS_SECURITY, AXIS_COMPATIBILITY)
    ]
    report_counts = report.get("severity_counts")
    axis = _assessed(
        AXIS_QUALITY,
        int(score),
        str(grade) if grade else None,
        findings=quality_findings,
    )
    # Prefer the report's own severity_counts for quality when no remapping occurred,
    # so the axis matches the legacy report headline for typical catalog runs.
    if isinstance(report_counts, Mapping) and not any(
        _finding_category(f) in (AXIS_SECURITY, AXIS_COMPATIBILITY) for f in findings
    ):
        axis["severity_counts"] = {
            "error": int(report_counts.get("error") or 0),
            "warning": int(report_counts.get("warning") or 0),
            "info": int(report_counts.get("info") or 0),
        }
    return axis


def _security_axis(
    subject_type: str, findings: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    if subject_type != SUBJECT_MCP_ENDPOINT_VERSION:
        return _not_assessed(AXIS_SECURITY, REASON_SECURITY_CATALOG)
    security_findings = _filter_by_category(findings, AXIS_SECURITY)
    # Assessed whenever the MCP subject has a native lint report — empty set is clean.
    score = score_from_finding_dicts(security_findings)
    return _assessed(AXIS_SECURITY, score, findings=security_findings)


def _compatibility_axis(
    subject_type: str,
    findings: Sequence[Mapping[str, Any]],
    *,
    compatibility_compared: bool,
) -> Dict[str, Any]:
    if subject_type != SUBJECT_CATALOG_REVISION:
        return _not_assessed(AXIS_COMPATIBILITY, REASON_COMPAT_MCP)
    if not compatibility_compared:
        return _not_assessed(AXIS_COMPATIBILITY, REASON_COMPAT_NO_BASE)
    compat_findings = _filter_by_category(findings, AXIS_COMPATIBILITY)
    score = score_from_finding_dicts(compat_findings)
    return _assessed(AXIS_COMPATIBILITY, score, findings=compat_findings)


def _composite(
    axes: Sequence[Mapping[str, Any]],
) -> Tuple[Optional[int], Optional[str], bool]:
    """Compute composite when required coverage is met; otherwise ``(None, None, False)``."""
    by_key = {str(a.get("key")): a for a in axes}
    required_met = all(
        bool(by_key.get(key, {}).get("assessed")) for key in REQUIRED_AXES_FOR_COMPOSITE
    )
    if not required_met:
        return None, None, False

    weighted_sum = 0.0
    weight_total = 0.0
    for axis in axes:
        if not axis.get("assessed"):
            continue
        coverage = axis.get("coverage") or {}
        state = coverage.get("state") if isinstance(coverage, Mapping) else None
        if state == COVERAGE_NONE:
            continue
        score = axis.get("score")
        if score is None:
            continue
        weight = float(axis.get("weight") or DEFAULT_AXIS_WEIGHT)
        weighted_sum += float(score) * weight
        weight_total += weight

    if weight_total <= 0:
        return None, None, True

    composite = max(0, min(100, round(weighted_sum / weight_total)))
    return composite, grade_for_score(composite), True


def evaluate_axes(
    report: Mapping[str, Any],
    *,
    subject_type: str,
    compatibility_compared: Optional[bool] = None,
) -> AxisEvaluation:
    """Evaluate the CLX-1.2 axis model for one native lint/score report.

    Args:
        report: Native report dict (``score``, ``grade``, ``findings``, optional
            ``severity_counts``, ``report_fingerprint``, optional ``base_revision_id`` /
            ``compatibility_overall``).
        subject_type: ``catalog_revision`` or ``mcp_endpoint_version``.
        compatibility_compared: When set, overrides whether the compatibility axis is
            considered assessed for catalog subjects. Defaults to True when the report
            carries ``base_revision_id`` or ``compatibility_overall``.

    Returns:
        A frozen :class:`AxisEvaluation` ready to persist or serialize.
    """
    findings: List[Mapping[str, Any]] = list(report.get("findings") or [])

    if compatibility_compared is None:
        compatibility_compared = bool(
            report.get("base_revision_id") or report.get("compatibility_overall")
        )

    axes: List[Dict[str, Any]] = [
        _quality_axis(report, findings=findings),
        _not_assessed(AXIS_PROTOCOL, REASON_PROTOCOL),
        _security_axis(subject_type, findings),
        _not_assessed(AXIS_SUPPLY_CHAIN, REASON_SUPPLY_CHAIN),
        _not_assessed(AXIS_SUPPORTABILITY, REASON_SUPPORTABILITY),
        _compatibility_axis(
            subject_type, findings, compatibility_compared=compatibility_compared
        ),
    ]

    composite_score, composite_grade, required_met = _composite(axes)
    return AxisEvaluation(
        algorithm_id=ALGORITHM_ID,
        algorithm_version=ALGORITHM_VERSION,
        axes=tuple(axes),
        composite_score=composite_score,
        composite_grade=composite_grade,
        required_coverage_met=required_met,
        source_report_fingerprint=(
            str(report["report_fingerprint"])
            if report.get("report_fingerprint") is not None
            else None
        ),
    )


def catalog_axis_evaluation(report: Mapping[str, Any], **kwargs: Any) -> AxisEvaluation:
    """Evaluate axes for a catalog revision report."""
    return evaluate_axes(report, subject_type=SUBJECT_CATALOG_REVISION, **kwargs)


def mcp_axis_evaluation(report: Mapping[str, Any], **kwargs: Any) -> AxisEvaluation:
    """Evaluate axes for an MCP endpoint version report."""
    return evaluate_axes(report, subject_type=SUBJECT_MCP_ENDPOINT_VERSION, **kwargs)


def evaluation_row(
    evaluation: AxisEvaluation,
    *,
    subject_type: str,
    subject_id: str,
) -> Dict[str, Any]:
    """Build a column-name -> value dict ready for ``record_axis_evaluation``."""
    subject_column = (
        "version_record_id"
        if subject_type == SUBJECT_CATALOG_REVISION
        else "mcp_version_id"
    )
    payload = evaluation.as_dict()
    return {
        "subject_type": subject_type,
        subject_column: subject_id,
        "algorithm_id": payload["algorithm_id"],
        "algorithm_version": payload["algorithm_version"],
        "axes": payload["axes"],
        "composite_score": payload["composite_score"],
        "composite_grade": payload["composite_grade"],
        "required_coverage_met": payload["required_coverage_met"],
        "source_report_fingerprint": payload["source_report_fingerprint"],
    }
