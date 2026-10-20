"""
Multi-axis score and coverage model (CLX-1.2, #4849).

Turns a native lint/score report into a transparent, versioned set of axes so a single A–F
grade no longer hides whether a defect is definition quality, protocol conformance, security,
supply chain, supportability, or compatibility — and so "not assessed" is never conflated with
a clean (zero-finding) score.

Algorithm id ``clx-axis-v1``:

* **quality** — backwards-compatible axis = the legacy ``score`` / ``grade`` when present.
* **security** — scored from native findings whose ``category`` is ``security``. For an MCP
  snapshot that is the surface lint's security rules under the plain house formula. For an
  API-paradigm catalog revision (revision 3, ASP-1.3) it is the native ``security`` rule
  pack's findings under the weighted formula of :mod:`app.security_score`, with one
  sub-score per OWASP API Top 10 category; the axis is assessed only when the report carries
  the pack's ``security`` category bar, so a revision no security pack evaluated — or whose
  style guide disables the whole pack — reads *not assessed*, never 100.
* **compatibility** (catalog only) — scored from findings whose ``category`` is
  ``compatibility`` when a base revision comparison produced them.
* **supportability** — scored from a data-schema artifact's ``governance`` findings when
  FMT-5.5's data-contract ruleset produced them (ownership, SLA, freshness, retention,
  serving location); explicit not assessed for every other subject.
* **protocol / supply_chain** — explicit not assessed until their scanners exist (later
  CLX work).

Composite is published only when required coverage is present (v1: ``quality`` assessed).
Participating axes are assessed axes whose coverage state is not ``none``. Weights are equal
(``1.0``) for transparency. Scoring of non-quality axes reuses the same severity penalty model
as :mod:`app.schema_lint` / :mod:`app.mcp_score`.

Pure and deterministic: no DB or network access. Persistence lives with callers in
:mod:`app.database`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .docs_site import guide_page
from .lint_evidence import (
    COVERAGE_FULL,
    COVERAGE_NONE,
    COVERAGE_PARTIAL,
    SUBJECT_CATALOG_REVISION,
    SUBJECT_MCP_ENDPOINT_VERSION,
)
from .schema_lint import PER_RULE_PENALTY_CAP, SEVERITY_PENALTY
from .security_score import (
    SECURITY_RULESET_ID,
    evaluate_security_findings,
    grade_for_score,  # noqa: F401 - re-exported: the house A–F bands, shared with the axis model
)

# --- Algorithm identity ---------------------------------------------------------------------

#: Stable scoring algorithm id stored with every evaluation. Bump when the axis set, weights,
#: mapping rules, or composite formula change in a way that requires re-interpretation.
ALGORITHM_ID = "clx-axis-v1"

#: Implementation revision of :data:`ALGORITHM_ID` (stored alongside for audit).
#:
#: ``2`` (FMT-5.5, #5443): the supportability axis became assessable. The axis *set*, the
#: weights and the composite formula are unchanged — which is why the algorithm id stays
#: ``clx-axis-v1`` — but a data contract's governance findings now score their own axis
#: instead of quality, so an evaluation stored before this revision and one stored after
#: are not directly comparable for a ``data_schema`` subject. Every other subject is
#: byte-identical.
#:
#: ``3`` (ASP-1.3, #5921): the security axis became assessable for API-paradigm catalog
#: revisions. The axis set, the equal composite weights and the composite formula are
#: unchanged — which is why the algorithm id stays ``clx-axis-v1`` — but an API revision's
#: ``security`` findings now score their own axis under the published per-rule weights of
#: :mod:`app.security_score` (with OWASP API Top 10 sub-scores) instead of leaving it *not
#: assessed*, so an evaluation stored before this revision and one stored after are not
#: directly comparable for an API subject's security axis. The quality axis of every subject,
#: and every axis of every MCP snapshot and data contract, is byte-identical.
ALGORITHM_VERSION = "3"

#: Repository-relative guide documenting :data:`ALGORITHM_ID` / :data:`ALGORITHM_VERSION`
#: (CLX-4.3, #4861). Displayed algorithm chips in the UI link here.
ALGORITHM_DOCS_PAGE = guide_page("build", "axis-score")

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
#: Why an API-paradigm revision's security axis is not assessed: no security rule pack
#: published its category bar on the report — none ran for the revision, or the style guide
#: it was scored under disables every rule of the pack. Same constant name as before revision
#: 3 so existing callers keep importing it.
REASON_SECURITY_CATALOG = (
    "No security rule pack evaluated this revision (none ran, or its style guide disables the pack)"
)
REASON_COMPAT_MCP = "Compatibility axis applies to catalog revisions"
REASON_COMPAT_NO_BASE = "No base-revision compatibility evidence"
REASON_QUALITY_MISSING = "No quality score has been captured for this subject yet"

#: The lint category FMT-5.5's data-contract rule pack scores under. Its presence in a
#: report's ``categories`` rollup is how this module tells a report that *was* scored by
#: that pack from one that was not: the pack publishes the bar as a base category, so a
#: clean data contract still carries it while an API-paradigm report never does.
GOVERNANCE_CATEGORY = "governance"

#: Stable id of the data-schema-paradigm ruleset that feeds the supportability axis.
#: Recorded on the axis so a reader can tell *which* ruleset assessed it.
DATA_CONTRACT_RULESET_ID = "data-contract"


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
            "algorithm_docs_page": ALGORITHM_DOCS_PAGE,
            "axes": [dict(a) for a in self.axes],
            "composite_score": self.composite_score,
            "composite_grade": self.composite_grade,
            "required_coverage_met": self.required_coverage_met,
            "source_report_fingerprint": self.source_report_fingerprint,
        }


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


#: Finding categories scored on an axis of their own, and therefore excluded from the
#: quality axis's severity tallies so no finding is counted twice.
_REMAPPED_CATEGORIES: Tuple[str, ...] = (
    AXIS_SECURITY,
    AXIS_COMPATIBILITY,
    GOVERNANCE_CATEGORY,
)


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
        if _finding_category(f) not in _REMAPPED_CATEGORIES
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
        _finding_category(f) in _REMAPPED_CATEGORIES for f in findings
    ):
        axis["severity_counts"] = {
            "error": int(report_counts.get("error") or 0),
            "warning": int(report_counts.get("warning") or 0),
            "info": int(report_counts.get("info") or 0),
        }
    return axis


def _protocol_axis(
    subject_type: str, conformance_report: Optional[Mapping[str, Any]]
) -> Dict[str, Any]:
    """Assess the protocol axis from an MCP conformance report (CLX-3.1, #4855).

    This axis was declared by CLX-1.2 but has always read *not assessed* — there was no scanner
    that could speak to a server's protocol behaviour. :mod:`app.mcp_conformance` is that
    scanner, and its report is what fills the axis in.

    The axis takes the conformance report's own score and grade rather than recomputing from its
    findings, so the axis and the conformance report can never disagree about the same run.

    Two states never collapse into "clean":

    * **No conformance report** (``None``) — the snapshot has not been conformance-scanned, so
      the axis stays *not assessed* with :data:`REASON_PROTOCOL`. It contributes nothing to the
      composite, which is exactly right: an unscanned axis is not a passing one.
    * **A report with skipped rules** — the transcript-backed rules could not be evaluated
      because no protocol transcript was captured for the snapshot. The axis is assessed (the
      surface-derived rules genuinely did run) but its coverage is :data:`COVERAGE_PARTIAL`, so
      a consumer can tell a fully-observed pass from a partially-observed one.

    Args:
        subject_type: Only MCP snapshots have a protocol surface; a catalog revision is a
            document and has none.
        conformance_report: A ``ConformanceReport.report_dict()`` payload, or ``None``.

    Returns:
        The axis payload.
    """
    if subject_type != SUBJECT_MCP_ENDPOINT_VERSION or not conformance_report:
        return _not_assessed(AXIS_PROTOCOL, REASON_PROTOCOL)

    score = conformance_report.get("score")
    if score is None:
        return _not_assessed(AXIS_PROTOCOL, REASON_PROTOCOL)

    grade = conformance_report.get("grade")
    findings = [
        f for f in (conformance_report.get("findings") or []) if isinstance(f, Mapping)
    ]
    coverage_state = (
        COVERAGE_PARTIAL if conformance_report.get("skipped_rules") else COVERAGE_FULL
    )
    return _assessed(
        AXIS_PROTOCOL,
        int(score),
        str(grade) if grade else None,
        findings=findings,
        coverage_state=coverage_state,
    )


def _report_categories(report: Mapping[str, Any]) -> Set[str]:
    """Return the category names a report's per-category rollup carries."""
    names: Set[str] = set()
    for entry in report.get("categories") or []:
        if isinstance(entry, Mapping):
            name = entry.get("name")
            if isinstance(name, str) and name.strip():
                names.add(name.strip().lower())
    return names


def _supportability_axis(
    report: Mapping[str, Any], *, findings: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    """Assess the supportability axis from the FMT-5.5 data-contract ruleset (#5443).

    This axis was declared by CLX-1.2 and has always read *not assessed* — nothing scored
    whether an artifact could actually be operated and supported. For a **data-schema**
    artifact that is exactly what the data-contract rule pack asks: is there a reachable
    owner, a stated service level, a freshness promise, a documented retention window, a
    support channel, a serving location. So when a report was scored by that ruleset, its
    ``governance`` findings fill the axis in.

    The signal is the report's own ``governance`` category bar rather than a caller-supplied
    flag, so every existing entry point (import scoring, the lint routes, the repository
    sweep) gets the axis without threading a new argument through — and an API-paradigm
    report, which never carries that bar, is untouched.

    Args:
        report: The native lint report dict.
        findings: The report's findings.

    Returns:
        The axis payload: assessed from the governance findings when the ruleset ran,
        otherwise the pre-FMT-5.5 *not assessed* state.
    """
    if GOVERNANCE_CATEGORY not in _report_categories(report):
        return _not_assessed(AXIS_SUPPORTABILITY, REASON_SUPPORTABILITY)
    governance = _filter_by_category(findings, GOVERNANCE_CATEGORY)
    axis = _assessed(
        AXIS_SUPPORTABILITY,
        score_from_finding_dicts(governance),
        findings=governance,
    )
    axis["ruleset"] = DATA_CONTRACT_RULESET_ID
    return axis


def _supply_chain_axis(
    subject_type: str, posture_report: Optional[Mapping[str, Any]]
) -> Dict[str, Any]:
    """Assess the supply-chain axis from an MCP trust-posture report (CLX-3.2, #4856).

    This axis was declared by CLX-1.2 and, like the protocol axis before CLX-3.1, has always read
    *not assessed* — there was no scanner that could speak to a server's source, dependencies, or
    configuration. :mod:`app.mcp_trust_posture` is that scanner, and its report is what fills the
    axis in. It mirrors :func:`_protocol_axis` deliberately, so the two reserved axes are filled the
    same way and a reader who understands one understands the other.

    The axis takes the posture report's own score and grade rather than recomputing from its
    findings, so the axis and the posture report can never disagree about the same run.

    Two states never collapse into "clean", which matters more here than for any other axis because
    most endpoints will have no linked source:

    * **No posture report** (``None``) — the snapshot has not been posture-scanned at all, so the
      axis stays *not assessed* with :data:`REASON_SUPPLY_CHAIN`. It contributes nothing to the
      composite: an unscanned axis is not a passing one.
    * **A report with skipped rules** — source- or dependency-derived rules could not be evaluated
      because no source was linked (or no SBOM / vulnerability lookup was available). The axis is
      assessed (the metadata-derived rules genuinely did run) but its coverage is
      :data:`COVERAGE_PARTIAL`, so a consumer can tell a server whose *supply chain* was actually
      reviewed from one where only its advertised metadata was.

    Args:
        subject_type: Only MCP snapshots have a source lane; a catalog revision is a document.
        posture_report: A ``PostureReport.report_dict()`` payload, or ``None``.

    Returns:
        The axis payload.
    """
    if subject_type != SUBJECT_MCP_ENDPOINT_VERSION or not posture_report:
        return _not_assessed(AXIS_SUPPLY_CHAIN, REASON_SUPPLY_CHAIN)

    score = posture_report.get("score")
    if score is None:
        return _not_assessed(AXIS_SUPPLY_CHAIN, REASON_SUPPLY_CHAIN)

    grade = posture_report.get("grade")
    findings = [
        f for f in (posture_report.get("findings") or []) if isinstance(f, Mapping)
    ]
    coverage_state = (
        COVERAGE_PARTIAL if posture_report.get("skipped_rules") else COVERAGE_FULL
    )
    return _assessed(
        AXIS_SUPPLY_CHAIN,
        int(score),
        str(grade) if grade else None,
        findings=findings,
        coverage_state=coverage_state,
    )


def _security_axis(
    subject_type: str,
    report: Mapping[str, Any],
    findings: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Assess the security axis from the report's ``security``-category findings.

    **MCP snapshot** — unchanged since CLX-1.2: the surface lint's security rules score the
    axis under the plain house formula, and the axis is assessed whenever the snapshot has a
    native lint report (an empty set is clean).

    **Catalog revision** (revision 3, ASP-1.3, #5921) — the axis is assessed only when the
    report's per-category rollup carries the ``security`` bar, which the native ``security``
    rule pack publishes as a base category when it runs for an API-paradigm artifact. That is
    the same signal :func:`_supportability_axis` reads for the data-contract pack, and it
    keeps three states apart that must never collapse into "clean":

    * **No bar** — no security pack evaluated the revision: it predates the pack, the artifact
      is not an API description, or the style guide it was scored under disables every rule
      of the pack (:class:`app.style_guide_engine.CompiledStyleGuide` withdraws the bar in
      that case). The axis stays *not assessed* with :data:`REASON_SECURITY_CATALOG`.
    * **Bar, every rule evaluated** — assessed under the weighted formula of
      :mod:`app.security_score`, coverage ``full``; an empty finding set is a clean 100.
    * **Bar, some rules skipped** — the run reported security rules it could not evaluate for
      the revision's format (``skipped_rules`` on the report, the key the MCP engines already
      use). The axis is assessed but its coverage is ``partial``, and each OWASP category all
      of whose rules were skipped carries coverage ``none`` in the stored ``owasp`` list.

    Args:
        subject_type: ``catalog_revision`` or ``mcp_endpoint_version``.
        report: The native report dict (read for its ``categories`` and ``skipped_rules``).
        findings: The report's findings.

    Returns:
        The axis payload. For an assessed API subject it additionally carries ``ruleset``
        (:data:`app.security_score.SECURITY_RULESET_ID`), ``owasp`` (one sub-score dict per
        OWASP API category) and ``skipped_rules``.
    """
    security_findings = _filter_by_category(findings, AXIS_SECURITY)
    if subject_type == SUBJECT_MCP_ENDPOINT_VERSION:
        # Assessed whenever the MCP subject has a native lint report — empty set is clean.
        score = score_from_finding_dicts(security_findings)
        return _assessed(AXIS_SECURITY, score, findings=security_findings)

    if AXIS_SECURITY not in _report_categories(report):
        return _not_assessed(AXIS_SECURITY, REASON_SECURITY_CATALOG)

    skipped = report.get("skipped_rules") or []
    evaluation = evaluate_security_findings(
        security_findings,
        skipped_rules=[str(r) for r in skipped] if isinstance(skipped, (list, tuple)) else [],
    )
    axis = _assessed(
        AXIS_SECURITY,
        evaluation.score,
        evaluation.grade,
        findings=security_findings,
        coverage_state=evaluation.coverage,
    )
    axis["ruleset"] = SECURITY_RULESET_ID
    axis["owasp"] = [sub.as_dict() for sub in evaluation.owasp]
    axis["skipped_rules"] = list(evaluation.skipped_rules)
    return axis


def security_headline(
    axes: Iterable[Mapping[str, Any]],
) -> Tuple[Optional[int], Optional[str]]:
    """Return ``(score, grade)`` of an evaluation's security axis, or ``(None, None)``.

    The stored-first read every list surface uses (ASP-1.3): a versions list renders
    ``securityScore`` / ``securityGrade`` from the newest persisted evaluation's axes without
    re-linting, exactly as ``qualityScore`` is read from the version record. A not-assessed
    axis yields ``(None, None)`` — never ``0`` / ``F``.

    Args:
        axes: The ``axes`` payload of a stored or computed evaluation.

    Returns:
        The security score and grade when the axis is assessed; otherwise ``(None, None)``.
    """
    for axis in axes:
        if not isinstance(axis, Mapping) or axis.get("key") != AXIS_SECURITY:
            continue
        if not axis.get("assessed") or axis.get("score") is None:
            return None, None
        score = int(axis["score"])
        grade = axis.get("grade")
        return score, (str(grade) if grade else grade_for_score(score))
    return None, None


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
    conformance_report: Optional[Mapping[str, Any]] = None,
    posture_report: Optional[Mapping[str, Any]] = None,
) -> AxisEvaluation:
    """Evaluate the CLX-1.2 axis model for one native lint/score report.

    Args:
        report: Native report dict (``score``, ``grade``, ``findings``, optional
            ``severity_counts``, ``report_fingerprint``, optional ``base_revision_id`` /
            ``compatibility_overall``, optional ``categories`` — the per-category rollup
            whose ``security`` / ``governance`` bars gate the security and supportability
            axes — and optional ``skipped_rules``, the rule ids the run could not evaluate
            for the artifact's format).
        subject_type: ``catalog_revision`` or ``mcp_endpoint_version``.
        compatibility_compared: When set, overrides whether the compatibility axis is
            considered assessed for catalog subjects. Defaults to True when the report
            carries ``base_revision_id`` or ``compatibility_overall``.
        conformance_report: An MCP conformance report
            (:meth:`app.mcp_conformance.ConformanceReport.report_dict`), when the subject has
            been conformance-scanned (CLX-3.1). It is passed *separately* from ``report``
            rather than merged into it because the two are distinct scans with distinct scores
            and fingerprints — folding conformance findings into the surface lint report would
            change that report's persisted score. Omitting it leaves the protocol axis *not
            assessed*, which is the pre-CLX-3.1 behaviour and the correct reading for a snapshot
            nothing has conformance-scanned.
        posture_report: An MCP trust-posture report
            (:meth:`app.mcp_trust_posture.PostureReport.report_dict`), when the subject has been
            source / supply-chain scanned (CLX-3.2). Passed *separately* from ``report`` for the same
            reason ``conformance_report`` is: it is a distinct scan with its own score and
            fingerprint, and folding its findings into the surface lint report would change that
            report's persisted score. Omitting it leaves the supply-chain axis *not assessed*, the
            correct reading for a snapshot nothing has posture-scanned.

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
        _protocol_axis(subject_type, conformance_report),
        _security_axis(subject_type, report, findings),
        _supply_chain_axis(subject_type, posture_report),
        _supportability_axis(report, findings=findings),
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


#: Scanners whose findings belong wholly to one non-quality axis (CLX-4.1, #4859).
_SCANNER_AXIS: Mapping[str, str] = {
    "apiome.mcp-conformance": AXIS_PROTOCOL,
    "apiome.mcp-trust-posture": AXIS_SUPPLY_CHAIN,
}


def axis_key_for_finding(
    category: Optional[str],
    *,
    scanner_id: Optional[str] = None,
) -> str:
    """Map one evidence finding onto the axis it is scored under (CLX-4.1, #4859).

    Mirrors how :func:`evaluate_axes` distributes findings across axes so a workspace
    queue filtered by axis matches the axis severity tallies:

    * The conformance and trust-posture scanners feed the ``protocol`` and ``supply_chain``
      axes wholesale (their ``category`` values — ``readiness``, ``metadata``, ``source`` …
      — are scanner-internal vocabularies, and ``protocol`` appears in both).
    * Surface-lint findings split by category: ``security`` and ``compatibility`` map to
      their axes, FMT-5.5's ``governance`` findings map to ``supportability``, and
      everything else is definition quality.

    Args:
        category: The finding's envelope ``category`` value, if any.
        scanner_id: The evidence run's ``scanner_id``, when known.

    Returns:
        One of :data:`AXIS_KEYS`.
    """
    scanner_axis = _SCANNER_AXIS.get(str(scanner_id or ""))
    if scanner_axis:
        return scanner_axis
    normalized = str(category or "").strip().lower()
    if normalized == AXIS_SECURITY:
        return AXIS_SECURITY
    if normalized == AXIS_COMPATIBILITY:
        return AXIS_COMPATIBILITY
    if normalized == GOVERNANCE_CATEGORY:
        return AXIS_SUPPORTABILITY
    return AXIS_QUALITY


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
