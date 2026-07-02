"""
Scoring, grading & fingerprint roll-up over the MCP lint surface (V2-MCP-21.4).

Where :mod:`app.mcp_lint` produces the ordered, deterministic *findings* for a normalized
:class:`~app.mcp_client.normalize.DiscoverySurface`, this module rolls those findings up
into the three persisted quality signals a version snapshot carries:

* a weighted **0-100 score** — 100 minus capped per-rule severity penalties, so a MUST
  failure (``error``) costs more than a SHOULD failure (``warning``), which costs more than
  an advisory (``info``);
* an **A-F letter grade** from the house thresholds (A≥90 … F<60, the same V124 bands the
  OpenAPI lint score uses), so an MCP grade reads the same as a schema grade; and
* a stable **report fingerprint** — a hash over the score, grade, and sorted findings — that
  lets a caller detect when a re-scored surface has actually changed.

It is the MCP counterpart to the scoring half of :func:`app.schema_lint.lint_openapi_spec`
and intentionally mirrors its structure (same penalty model, same grade bands, same
fingerprint shape) so the two linters stay on one comparable 0-100 scale. The split between
*finding* (``mcp_lint``) and *scoring* (here) is deliberate — see the module docstring of
:mod:`app.mcp_lint`, which reserves scoring for this module.

Like the engine it consumes, scoring is **pure** and **deterministic**: no DB or network
access, and the same surface always yields the same score, grade, and fingerprint. Persisting
the result to ``mcp_version_scores`` (and the best-effort capture at version creation) lives
with the callers in :mod:`app.database` / :mod:`app.mcp_discovery_engine`, not here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from .mcp_client.normalize import DiscoverySurface
from .mcp_lint import (
    SEVERITY_PENALTY,
    LintFinding,
    finding_dicts,
    lint_mcp_surface,
)

# --- Scoring model --------------------------------------------------------------------------

#: Maximum total penalty a single rule may contribute to the score, so one noisy rule cannot
#: tank the whole grade on a large surface. Mirrors :data:`app.schema_lint.PER_RULE_PENALTY_CAP`
#: so the MCP score behaves like the OpenAPI lint score for the same shape of defect.
PER_RULE_PENALTY_CAP: float = 20.0

#: Letter-grade thresholds, evaluated high-to-low. These are the house bands first established
#: for the per-revision OpenAPI quality score (V124: A≥90, B≥80, C≥70, D≥60, else F); reused
#: verbatim here so an MCP grade and a schema grade mean the same thing.
GRADE_THRESHOLDS: Tuple[Tuple[int, str], ...] = (
    (90, "A"),
    (80, "B"),
    (70, "C"),
    (60, "D"),
    (0, "F"),
)


@dataclass(frozen=True)
class MCPScoreResult:
    """Rolled-up MCP lint score for one discovery surface.

    The MCP analogue of :class:`app.schema_lint.LintResult`: a numeric score, its letter
    grade, the ordered findings the score was computed from, per-rule and per-severity
    tallies for drill-down, and a stable fingerprint over the whole report.

    Attributes:
        score: Deterministic 0-100 quality score (100 minus capped per-rule penalties).
        grade: A-F letter grade derived from ``score`` via :data:`GRADE_THRESHOLDS`.
        findings: The ordered, deterministic findings (already sorted by the engine).
        rule_hits: Count of findings per rule id, in sorted rule-id order.
        severity_counts: Count of findings per severity (``error``/``warning``/``info``).
        report_fingerprint: Stable hash over ``score``, ``grade``, and the sorted findings.
    """

    score: int
    grade: str
    findings: Tuple[LintFinding, ...]
    rule_hits: Mapping[str, int]
    severity_counts: Mapping[str, int]
    report_fingerprint: str

    def finding_dicts(self) -> List[Dict[str, str]]:
        """Return the findings as a list of JSON-ready dicts (stable key set, sorted order)."""
        return finding_dicts(self.findings)

    def report_dict(self) -> Dict[str, object]:
        """Return the full scoring report as a JSON-ready dict.

        This is the payload persisted into ``mcp_version_scores.report`` and rendered by the
        lint UI: the headline score/grade, the per-rule and per-severity tallies, the stable
        fingerprint, and every itemized finding. Key set and ordering are stable so the JSON
        (and therefore the fingerprint computed elsewhere over the same data) is reproducible.
        """
        return {
            "score": self.score,
            "grade": self.grade,
            "report_fingerprint": self.report_fingerprint,
            "rule_hits": dict(self.rule_hits),
            "severity_counts": dict(self.severity_counts),
            "findings": self.finding_dicts(),
        }


def _score_from_findings(findings: Iterable[LintFinding]) -> int:
    """Deterministic 0-100 score: 100 minus capped per-rule severity penalties.

    Each finding adds its severity weight (:data:`app.mcp_lint.SEVERITY_PENALTY`) to a running
    total *per rule*; each rule's contribution is then capped at :data:`PER_RULE_PENALTY_CAP`
    before summing, so a single chatty rule cannot dominate the grade. Because MUST failures
    register as ``error`` (weight 10) and SHOULD failures as ``warning`` (weight 4), MUST
    failures are weighted heavier than SHOULD failures by construction.

    Args:
        findings: The findings to score; order does not affect the result.

    Returns:
        An integer in ``[0, 100]``.
    """
    penalty_by_rule: Dict[str, float] = {}
    for finding in findings:
        weight = SEVERITY_PENALTY.get(finding.severity, 0.0)
        penalty_by_rule[finding.rule] = penalty_by_rule.get(finding.rule, 0.0) + weight
    total_penalty = sum(min(p, PER_RULE_PENALTY_CAP) for p in penalty_by_rule.values())
    return max(0, min(100, round(100.0 - total_penalty)))


def _grade_for_score(score: int) -> str:
    """Map a 0-100 ``score`` to its A-F letter grade via :data:`GRADE_THRESHOLDS`."""
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def _rule_hits(findings: Iterable[LintFinding]) -> Dict[str, int]:
    """Count findings per rule id, returned in sorted rule-id order (stable for rendering)."""
    hits: Dict[str, int] = {}
    for finding in findings:
        hits[finding.rule] = hits.get(finding.rule, 0) + 1
    return dict(sorted(hits.items()))


def _severity_counts(findings: Iterable[LintFinding]) -> Dict[str, int]:
    """Count findings per severity, always returning all three keys (zero when unhit)."""
    counts = {"error": 0, "warning": 0, "info": 0}
    for finding in findings:
        if finding.severity in counts:
            counts[finding.severity] += 1
    return counts


def _report_fingerprint(
    score: int, grade: str, finding_dicts_: List[Dict[str, str]]
) -> str:
    """Stable hash over score, grade, and sorted findings for staleness detection / identity.

    Mirrors :func:`app.schema_lint._report_fingerprint`: the findings are re-sorted by
    ``(path, rule, id)`` inside the payload so the hash is independent of input order, and the
    JSON is emitted with sorted keys and no whitespace so equal reports always hash equal.

    Args:
        score: The computed score.
        grade: The derived letter grade.
        finding_dicts_: The findings as JSON-ready dicts.

    Returns:
        A hex SHA-256 digest of the canonicalized report.
    """
    payload = {
        "score": score,
        "grade": grade,
        "findings": sorted(
            finding_dicts_,
            key=lambda x: (x.get("path", ""), x.get("rule", ""), x.get("id", "")),
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def score_mcp_surface(
    surface: DiscoverySurface,
    extra_findings: Optional[Iterable[LintFinding]] = None,
) -> MCPScoreResult:
    """Lint and score an MCP discovery ``surface`` into a deterministic :class:`MCPScoreResult`.

    Runs the full registered rule set (:func:`app.mcp_lint.lint_mcp_surface`) over the surface,
    then rolls the findings up into a weighted 0-100 score, an A-F grade, per-rule/per-severity
    tallies, and a stable report fingerprint. Pure and deterministic: the same surface (and the
    same ``extra_findings``) always yields the same result.

    Args:
        surface: The normalized MCP capability surface to score. Not mutated.
        extra_findings: Optional pre-built findings to fold into the report and the score
            (e.g. findings derived out of band). They participate in scoring and ordering.

    Returns:
        The rolled-up :class:`MCPScoreResult` for the surface.
    """
    findings = lint_mcp_surface(surface, extra_findings)
    score = _score_from_findings(findings)
    grade = _grade_for_score(score)
    fingerprint = _report_fingerprint(score, grade, finding_dicts(findings))
    return MCPScoreResult(
        score=score,
        grade=grade,
        findings=findings,
        rule_hits=_rule_hits(findings),
        severity_counts=_severity_counts(findings),
        report_fingerprint=fingerprint,
    )
