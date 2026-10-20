"""Deterministic 0–100 security score for catalog revisions (ASP-1.3, #5921).

:mod:`app.axis_score` reserves a ``security`` axis. Until ``clx-axis-v1`` revision 3 that axis
was assessed for MCP snapshots only; for an API description it always read *not assessed*,
even when the lint report carried security findings. This module is the scoring half of the
revision-3 change: it turns the ``security``-category findings of a revision's newest native
lint run into one published, reproducible number — the score 42Crunch sells as its
differentiator, computed from constants anyone can read here.

Formula
-------

::

    score = 100 − Σ_rule min(PER_RULE_PENALTY_CAP, Σ_findings SEVERITY_PENALTY[severity] × weight(rule))

clamped to ``[0, 100]`` and rounded to an integer. The severity penalties (``error`` 10,
``warning`` 4, ``info`` 1) and the per-rule cap (20) are the house constants every other
Apiome score uses (:mod:`app.schema_lint`); what is new is the per-rule **weight**
(:data:`SECURITY_RULE_WEIGHTS`, default :data:`DEFAULT_SECURITY_RULE_WEIGHT`). The weight
multiplies a rule's penalty *before* the cap, so one ``error`` from a weight-2 rule costs the
full 20 points of its cap at once: a revision whose only finding is one such error scores
exactly 80 and grades B. The grade uses the house A–F bands.

Every weight is public: ``GET /v1/lint/rules`` publishes ``weight`` (and ``owasp``) per rule,
and the docs table on the *Axis score algorithm* page is generated from
:func:`published_weights` by ``scripts/generate_lint_rule_docs.py`` — never typed by hand.

OWASP sub-scores
----------------

Beside the headline the evaluation stores one entry per OWASP API Security Top 10 category
(:mod:`app.owasp_api`): the same formula over the findings whose rule cites that category,
the finding count, and a **coverage** state. Coverage is ``full`` when at least one registered
rule citing the category evaluated for the revision and ``none`` when every such rule was
skipped for the format (or no rule cites the category at all) — a ``none`` category renders
*not assessed*, never 100. A rule that cites two categories counts in both: sub-scores are
per-category views of the same findings, not a partition of them.

What does **not** score the axis: the external Spectral OWASP ruleset the ``spectral.oas``
adapter can run as its ``owasp`` profile (ASP-1.1). Its findings are parity evidence in the
evidence substrate; scoring them as well as the native pack would count one defect twice.

Pure and deterministic: no DB or network access. :func:`rule_owasp_ids` reads the built-in
rule catalog (module constants) lazily and caches it for the process.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .lint_evidence import COVERAGE_FULL, COVERAGE_NONE, COVERAGE_PARTIAL
from .owasp_api import RISK_IDS, RISKS, validate_risk_ids
from .schema_lint import GRADE_THRESHOLDS, PER_RULE_PENALTY_CAP, SEVERITY_PENALTY

__all__ = [
    "DEFAULT_SECURITY_RULE_WEIGHT",
    "SECURITY_CATEGORY",
    "SECURITY_RULESET_ID",
    "SECURITY_RULE_WEIGHTS",
    "OwaspSubScore",
    "SecurityEvaluation",
    "evaluate_security_findings",
    "grade_for_score",
    "owasp_subscores",
    "published_weights",
    "rule_owasp_ids",
    "rules_by_owasp_risk",
    "security_rule_weight",
    "security_score_from_finding_dicts",
    "weighted_penalty_by_rule",
]

#: The lint category whose findings score the security axis. Rules of the native
#: ``security`` pack carry it; a style guide that disables every rule of the pack withdraws the
#: category bar from the report, which is how the axis reads *not assessed* rather than 100.
SECURITY_CATEGORY = "security"

#: Stable id of the native rule pack that feeds the axis, recorded on the axis payload so a
#: reader can tell *which* ruleset assessed it (mirrors ``data-contract`` on supportability).
SECURITY_RULESET_ID = "security"

#: Weight of every ``security`` rule that :data:`SECURITY_RULE_WEIGHTS` does not list.
DEFAULT_SECURITY_RULE_WEIGHT: float = 1.0

#: Published per-rule weights. A weight multiplies the rule's severity penalty before the
#: per-rule cap. The four weight-2 rules are the ones whose single violation is a credential
#: or an unauthenticated write — the defects the brief treats as outright failures. Keyed by
#: stable rule id; a rule not yet in the catalog keeps its reserved weight until it ships.
SECURITY_RULE_WEIGHTS: Mapping[str, float] = {
    "security.write-operation-missing-auth": 2.0,
    "security.credentials-in-server-url": 2.0,
    "security.secret-in-document": 2.0,
    "security.pii-exposed-without-auth": 2.0,
}

_UNNAMED_RULE = "_unnamed"


def grade_for_score(score: int) -> str:
    """Map a 0–100 ``score`` to its A–F letter grade via the house thresholds."""
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def security_rule_weight(rule_id: str) -> float:
    """Return the published weight of ``rule_id`` (default :data:`DEFAULT_SECURITY_RULE_WEIGHT`).

    Args:
        rule_id: A rule's stable id.

    Returns:
        The weight its severity penalty is multiplied by before the per-rule cap.
    """
    return float(SECURITY_RULE_WEIGHTS.get(rule_id, DEFAULT_SECURITY_RULE_WEIGHT))


def _finding_rule(finding: Mapping[str, Any]) -> str:
    """Return the rule id a finding dict carries (``rule`` or ``rule_id``), or a placeholder."""
    return str(finding.get("rule") or finding.get("rule_id") or "") or _UNNAMED_RULE


def weighted_penalty_by_rule(findings: Iterable[Mapping[str, Any]]) -> Dict[str, float]:
    """Sum each rule's weighted severity penalty over ``findings``, before the per-rule cap.

    Args:
        findings: Finding dicts carrying ``severity`` and ``rule`` / ``rule_id``.

    Returns:
        ``{rule_id: Σ SEVERITY_PENALTY[severity] × weight(rule_id)}``, uncapped, so a caller can
        show how much each rule contributed before the cap clipped it.
    """
    penalty_by_rule: Dict[str, float] = {}
    for finding in findings:
        rule = _finding_rule(finding)
        penalty = SEVERITY_PENALTY.get(str(finding.get("severity") or ""), 0.0)
        penalty_by_rule[rule] = penalty_by_rule.get(rule, 0.0) + penalty * security_rule_weight(rule)
    return penalty_by_rule


def security_score_from_finding_dicts(findings: Iterable[Mapping[str, Any]]) -> int:
    """Score ``findings`` with the weighted, per-rule-capped formula (see module docstring).

    An empty finding set scores 100 (clean). Callers decide *whether* the axis is assessed —
    this function must not be used for a not-assessed axis.

    Args:
        findings: ``security``-category finding dicts.

    Returns:
        The 0–100 score.
    """
    total_penalty = sum(
        min(penalty, PER_RULE_PENALTY_CAP) for penalty in weighted_penalty_by_rule(findings).values()
    )
    return max(0, min(100, round(100.0 - total_penalty)))


@dataclass(frozen=True)
class OwaspSubScore:
    """The security axis seen through one OWASP API Top 10 category.

    Attributes:
        risk_id: The category id (``API1`` … ``API10``).
        title: The category's title, for rendering without a catalog lookup.
        score: 0–100 over the findings whose rule cites the category; ``None`` when
            ``coverage`` is ``none`` (nothing evaluated, so there is no score to show).
        finding_count: Number of security findings whose rule cites the category.
        coverage: ``full`` when at least one registered rule citing the category evaluated for
            the revision; ``none`` when every such rule was skipped for the format or no rule
            cites the category — rendered *not assessed*, never 100.
    """

    risk_id: str
    title: str
    score: Optional[int]
    finding_count: int
    coverage: str

    def as_dict(self) -> Dict[str, Any]:
        """Return the sub-score as the JSON-ready dict stored inside the axis payload."""
        return {
            "risk_id": self.risk_id,
            "title": self.title,
            "score": self.score,
            "finding_count": self.finding_count,
            "coverage": self.coverage,
        }


@lru_cache(maxsize=1)
def rule_owasp_ids() -> Mapping[str, Tuple[str, ...]]:
    """Return ``{rule_id: owasp category ids}`` for every registered rule that cites any.

    Read lazily from the built-in rule catalog (:mod:`app.lint_rule_registry`), which is
    assembled from module constants, and cached for the process: the catalog cannot change
    while the server runs.
    """
    from .lint_rule_registry import builtin_rule_descriptors  # Lazy: avoids an import cycle.

    return {
        descriptor.rule_id: validate_risk_ids(descriptor.owasp_ids)
        for descriptor in builtin_rule_descriptors()
        if descriptor.owasp_ids
    }


def rules_by_owasp_risk(
    rule_owasp: Mapping[str, Sequence[str]],
) -> Dict[str, Tuple[str, ...]]:
    """Invert a ``{rule_id: category ids}`` mapping into ``{category id: rule ids}``.

    Args:
        rule_owasp: Which categories each rule cites.

    Returns:
        Every catalog category (in catalog order) mapped to the sorted rule ids citing it —
        an empty tuple for a category no rule cites.
    """
    inverted: Dict[str, List[str]] = {risk_id: [] for risk_id in RISK_IDS}
    for rule_id, risk_ids in rule_owasp.items():
        for risk_id in risk_ids:
            if risk_id in inverted:
                inverted[risk_id].append(rule_id)
    return {risk_id: tuple(sorted(rules)) for risk_id, rules in inverted.items()}


def owasp_subscores(
    findings: Sequence[Mapping[str, Any]],
    *,
    skipped_rules: Iterable[str] = (),
    rule_owasp: Optional[Mapping[str, Sequence[str]]] = None,
) -> List[OwaspSubScore]:
    """Compute one :class:`OwaspSubScore` per OWASP API category, in catalog order.

    Args:
        findings: The revision's ``security``-category finding dicts.
        skipped_rules: Rule ids the newest run skipped for the revision's format (a rule that
            needs a fact the format cannot express). A category all of whose rules were skipped
            has coverage ``none``.
        rule_owasp: ``{rule_id: category ids}`` to score against; defaults to the built-in
            catalog's mapping (:func:`rule_owasp_ids`). Injectable so the scoring can be pinned
            in tests independently of which rules the catalog ships.

    Returns:
        Ten sub-scores, ``API1`` through ``API10``.
    """
    mapping = rule_owasp if rule_owasp is not None else rule_owasp_ids()
    skipped = {str(rule_id) for rule_id in skipped_rules}
    by_risk = rules_by_owasp_risk(mapping)
    out: List[OwaspSubScore] = []
    for risk_id in RISK_IDS:
        rules = by_risk[risk_id]
        evaluated = [rule_id for rule_id in rules if rule_id not in skipped]
        cited = [f for f in findings if risk_id in mapping.get(_finding_rule(f), ())]
        if not evaluated:
            out.append(
                OwaspSubScore(
                    risk_id=risk_id,
                    title=RISKS[risk_id].title,
                    score=None,
                    finding_count=len(cited),
                    coverage=COVERAGE_NONE,
                )
            )
            continue
        out.append(
            OwaspSubScore(
                risk_id=risk_id,
                title=RISKS[risk_id].title,
                score=security_score_from_finding_dicts(cited),
                finding_count=len(cited),
                coverage=COVERAGE_FULL,
            )
        )
    return out


@dataclass(frozen=True)
class SecurityEvaluation:
    """The security axis of one API-paradigm revision, before it is shaped into an axis payload.

    Attributes:
        score: The weighted 0–100 headline.
        grade: Its A–F grade.
        coverage: ``full`` when every registered security rule evaluated; ``partial`` when the
            newest run skipped some for the revision's format.
        owasp: One sub-score per OWASP API category, in catalog order.
        skipped_rules: The security rule ids the run skipped, sorted.
    """

    score: int
    grade: str
    coverage: str
    owasp: Tuple[OwaspSubScore, ...]
    skipped_rules: Tuple[str, ...]


def evaluate_security_findings(
    findings: Sequence[Mapping[str, Any]],
    *,
    skipped_rules: Iterable[str] = (),
    rule_owasp: Optional[Mapping[str, Sequence[str]]] = None,
) -> SecurityEvaluation:
    """Score a revision's ``security`` findings: headline, grade, coverage and OWASP sub-scores.

    Args:
        findings: The ``security``-category finding dicts of the newest native run.
        skipped_rules: Rule ids that run skipped for the revision's format. Only ids that are
            registered security rules affect coverage; anything else is ignored.
        rule_owasp: ``{rule_id: category ids}`` override for the sub-scores (see
            :func:`owasp_subscores`).

    Returns:
        The evaluation. Whether the axis is *assessed at all* is the caller's decision
        (:mod:`app.axis_score` requires the report to carry the ``security`` category bar).
    """
    mapping = rule_owasp if rule_owasp is not None else rule_owasp_ids()
    skipped = tuple(sorted({str(r) for r in skipped_rules if str(r) in mapping}))
    score = security_score_from_finding_dicts(findings)
    return SecurityEvaluation(
        score=score,
        grade=grade_for_score(score),
        coverage=COVERAGE_PARTIAL if skipped else COVERAGE_FULL,
        owasp=tuple(owasp_subscores(findings, skipped_rules=skipped, rule_owasp=mapping)),
        skipped_rules=skipped,
    )


def published_weights() -> List[Dict[str, Any]]:
    """Return the weight table the docs and the rule catalog publish, one row per rule.

    Rows cover every registered ``security``-category rule plus every id in
    :data:`SECURITY_RULE_WEIGHTS` that the catalog does not (yet) register, flagged
    ``registered: False`` so the reserved weight is public before the rule ships. Sorted by rule
    id for a stable rendering.

    Returns:
        ``[{"rule_id", "weight", "owasp": [...], "registered": bool}, ...]``.
    """
    from .lint_rule_registry import builtin_rule_descriptors  # Lazy: avoids an import cycle.

    rows: Dict[str, Dict[str, Any]] = {}
    for descriptor in builtin_rule_descriptors():
        if descriptor.category != SECURITY_CATEGORY:
            continue
        rows[descriptor.rule_id] = {
            "rule_id": descriptor.rule_id,
            "weight": security_rule_weight(descriptor.rule_id),
            "owasp": list(validate_risk_ids(descriptor.owasp_ids)),
            "registered": True,
        }
    for rule_id, weight in SECURITY_RULE_WEIGHTS.items():
        rows.setdefault(
            rule_id,
            {"rule_id": rule_id, "weight": float(weight), "owasp": [], "registered": False},
        )
    return [rows[rule_id] for rule_id in sorted(rows)]
