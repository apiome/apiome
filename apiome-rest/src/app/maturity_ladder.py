"""
Maturity-level evaluation — GVM-1.2 (#5855).

:func:`evaluate_ladder` answers "what level is this API at, and what blocks the next one?" for
one subject (a catalog revision or an MCP endpoint version) under the maturity ladder frozen
into its policy pack (GVM-1.1, :mod:`app.style_guide_ladder`).

It is the **single implementation** of level judgement: the ``/lint/level`` reads, the
persisted ``lint_policy_evaluations.gate_results.maturity`` and every later gate (GVM-1.3) and
dashboard (GVM-1.4) call it, so there is no second opinion to drift from.

How a level is judged
---------------------
Levels are walked lowest first and the walk stops at the first unsatisfied level. A ladder is
cumulative, so level *n* is checked against the **accumulated** requirements of levels
``0..n`` (the strictest ``maxSeverity`` seen per rule, every axis floor, every evidence kind),
under level *n*'s own ``waiversSatisfy``:

* **Rules** — a finding of a listed rule whose severity is worse than the rule's
  ``maxSeverity`` blocks the level (``none`` means any finding blocks). A finding whose
  effective decision is ``fixed`` or ``false_positive`` never counts; one that is ``waived``
  counts unless the level's ``waiversSatisfy`` is true. Every other state (``open``,
  ``acknowledged``, ``waiver_requested``) counts.
* **Axes** — the axis must be assessed and meet ``minGrade`` / ``minScore``. An axis that was
  never assessed is a blocker with ``reason: not_assessed`` — the CLX honesty rule: an
  unassessed axis is never treated as clean.
* **Evidence** — ``True`` satisfies, ``False`` blocks (``reason: missing``) and ``None`` (could
  not be determined) blocks with ``reason: not_assessed``.

A subject with no ladder gets ``level: None, reason: "no-ladder"`` — never a level. A subject
that does not meet the first level gets ``level: None, reason: "below-first-level"``.

The module is pure: it takes plain mappings and reads no database, clock aside (waiver expiry,
injectable through ``now``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .policy_evaluate import effective_decision_state, grade_meets_minimum

__all__ = [
    "BLOCKER_AXIS",
    "BLOCKER_EVIDENCE",
    "BLOCKER_RULE",
    "REASON_BELOW_FIRST_LEVEL",
    "REASON_NO_LADDER",
    "evaluate_ladder",
    "no_ladder_result",
]

#: Blocker kinds.
BLOCKER_RULE = "rule"
BLOCKER_AXIS = "axis"
BLOCKER_EVIDENCE = "evidence"

#: Why a result carries no level.
REASON_NO_LADDER = "no-ladder"
REASON_BELOW_FIRST_LEVEL = "below-first-level"

#: Why an axis or evidence requirement blocks.
REASON_NOT_ASSESSED = "not_assessed"
REASON_BELOW_THRESHOLD = "below_threshold"
REASON_MISSING = "missing"

#: Finding severities, mildest first; ``maxSeverity`` ``none`` ranks below all of them.
_SEVERITY_RANK = {"none": 0, "hint": 1, "info": 1, "warning": 2, "error": 3}

#: Effective decision states that remove a finding from every level's count.
_RESOLVED_STATES = frozenset({"fixed", "false_positive"})

#: How many finding fingerprints a rule blocker samples.
SAMPLE_SIZE = 3


def no_ladder_result() -> Dict[str, Any]:
    """The explicit result for a subject whose policy pack has no ladder."""
    return {
        "ladderName": None,
        "level": None,
        "levelLabel": None,
        "levelIndex": None,
        "nextLevel": None,
        "nextLevelLabel": None,
        "blockers": [],
        "waiversCounted": 0,
        "unassessedAxes": [],
        "reason": REASON_NO_LADDER,
    }


def _finding_rule_id(finding: Mapping[str, Any]) -> str:
    """Rule id of a finding in envelope (``rule_id``) or native (``rule``) shape."""
    return str(finding.get("rule_id") or finding.get("rule") or "")


def _finding_fingerprint(finding: Mapping[str, Any]) -> str:
    """Stable identity of a finding: ``source_fingerprint``, else ``id``."""
    return str(finding.get("source_fingerprint") or finding.get("id") or "")


def _severity_rank(severity: Any) -> int:
    """Rank of a finding severity; an unknown severity ranks as ``info``."""
    return _SEVERITY_RANK.get(str(severity or "").lower(), 1)


def _axes_by_key(axes: Optional[Sequence[Mapping[str, Any]]]) -> Dict[str, Mapping[str, Any]]:
    """Index axis payloads (``lint_axis_evaluations.axes`` entries) by their ``axis`` key."""
    out: Dict[str, Mapping[str, Any]] = {}
    for axis in axes or []:
        if isinstance(axis, Mapping):
            key = str(axis.get("axis") or axis.get("key") or "")
            if key:
                out[key] = axis
    return out


def _accumulate(levels: Sequence[Mapping[str, Any]], upto: int) -> Dict[str, Any]:
    """Merge the requirements of ``levels[0..upto]`` into one strictest set.

    Returns:
        ``{"rules": {ruleId: maxSeverity}, "axes": {axis: {minGrade?, minScore?}},
        "evidence": [kind, ...]}``. The validator (GVM-1.1) already guarantees a higher level
        never relaxes a lower one, but the merge keeps the strictest value regardless, so a
        hand-written pack is still judged safely.
    """
    rules: Dict[str, str] = {}
    axes: Dict[str, Dict[str, Any]] = {}
    evidence: List[str] = []
    for level in levels[: upto + 1]:
        for rule in level.get("rules") or []:
            rule_id = str(rule.get("ruleId") or "")
            severity = str(rule.get("maxSeverity") or "error")
            prior = rules.get(rule_id)
            if prior is None or _SEVERITY_RANK.get(severity, 3) < _SEVERITY_RANK.get(prior, 3):
                rules[rule_id] = severity
        for axis in level.get("axes") or []:
            key = str(axis.get("axis") or "")
            floor = axes.setdefault(key, {})
            grade = axis.get("minGrade")
            if grade and (
                "minGrade" not in floor or grade_meets_minimum(floor["minGrade"], grade) is False
            ):
                floor["minGrade"] = grade
            score = axis.get("minScore")
            if score is not None and score > floor.get("minScore", -1):
                floor["minScore"] = score
        for kind in level.get("evidence") or []:
            if kind not in evidence:
                evidence.append(kind)
    return {"rules": rules, "axes": axes, "evidence": evidence}


def _rule_blockers(
    level_key: str,
    rules: Mapping[str, str],
    counted: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Blockers for every listed rule that reports a finding worse than its ``maxSeverity``."""
    by_rule: Dict[str, List[str]] = {}
    for finding in counted:
        rule_id = finding["rule_id"]
        cap = rules.get(rule_id)
        if cap is None:
            continue
        if _severity_rank(finding["severity"]) > _SEVERITY_RANK.get(cap, 3):
            by_rule.setdefault(rule_id, []).append(finding["fingerprint"])
    return [
        {
            "levelKey": level_key,
            "kind": BLOCKER_RULE,
            "ruleId": rule_id,
            "maxSeverity": rules[rule_id],
            "count": len(fps),
            "sample": sorted(fp for fp in fps if fp)[:SAMPLE_SIZE],
        }
        for rule_id, fps in sorted(by_rule.items())
    ]


def _axis_blockers(
    level_key: str,
    floors: Mapping[str, Mapping[str, Any]],
    axes: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Blockers for every axis floor that is unassessed or not met."""
    out: List[Dict[str, Any]] = []
    for key in sorted(floors):
        floor = floors[key]
        axis = axes.get(key)
        blocker: Dict[str, Any] = {
            "levelKey": level_key,
            "kind": BLOCKER_AXIS,
            "axis": key,
            "count": 1,
            "sample": [],
            **{k: floor[k] for k in ("minGrade", "minScore") if k in floor},
        }
        if not axis or axis.get("assessed") is not True:
            out.append({**blocker, "reason": REASON_NOT_ASSESSED})
            continue
        grade_ok = grade_meets_minimum(axis.get("grade"), floor.get("minGrade"))
        score_ok = True
        if "minScore" in floor:
            try:
                score_ok = float(axis.get("score") or 0) >= float(floor["minScore"])
            except (TypeError, ValueError):
                score_ok = False
        if not (grade_ok and score_ok):
            out.append(
                {
                    **blocker,
                    "reason": REASON_BELOW_THRESHOLD,
                    "grade": axis.get("grade"),
                    "score": axis.get("score"),
                }
            )
    return out


def _evidence_blockers(
    level_key: str,
    required: Iterable[str],
    evidence: Mapping[str, Optional[bool]],
) -> List[Dict[str, Any]]:
    """Blockers for every required evidence kind that is missing or undetermined."""
    out: List[Dict[str, Any]] = []
    for kind in sorted(required):
        value = evidence.get(kind)
        if value is True:
            continue
        out.append(
            {
                "levelKey": level_key,
                "kind": BLOCKER_EVIDENCE,
                "evidence": kind,
                "count": 1,
                "sample": [],
                "reason": REASON_MISSING if value is False else REASON_NOT_ASSESSED,
            }
        )
    return out


def evaluate_ladder(
    findings: Sequence[Mapping[str, Any]],
    axes: Optional[Sequence[Mapping[str, Any]]],
    decisions: Mapping[str, Mapping[str, Any]],
    ladder: Optional[Mapping[str, Any]],
    *,
    evidence: Optional[Mapping[str, Optional[bool]]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Return the highest level a subject satisfies and what blocks the next one.

    Args:
        findings: The subject's current findings (envelope ``rule_id`` / native ``rule``,
            ``severity``, ``source_fingerprint`` or ``id``).
        axes: Axis payloads (``{axis, assessed, grade, score}``), or ``None`` when no axis
            evaluation exists.
        decisions: ``source_fingerprint`` → finding decision row (effective state is resolved
            here, so an expired waiver counts as open).
        ladder: The frozen ``{name, levels}`` ladder, or ``None``.
        evidence: ``{"review_approved": bool|None, "verification_passing": bool|None}``; a
            kind that is absent is ``None`` (not assessed).
        now: Clock for waiver expiry (UTC); defaults to the current time.

    Returns:
        ``{ladderName, level, levelLabel, levelIndex, nextLevel, nextLevelLabel, blockers,
        waiversCounted, unassessedAxes, reason}``. ``level`` / ``levelIndex`` are the highest
        satisfied level (``None`` when none is); ``blockers`` explain ``nextLevel`` (empty when
        the top level is reached); ``waiversCounted`` is how many waived findings were excused
        by the satisfied levels; ``unassessedAxes`` lists every axis the ladder names that was
        not assessed; ``reason`` is ``no-ladder`` / ``below-first-level`` / ``None``.
    """
    levels = list((ladder or {}).get("levels") or [])
    if not levels:
        return no_ladder_result()

    present = {_finding_fingerprint(f) for f in findings if _finding_fingerprint(f)}
    prepared: List[Dict[str, Any]] = []
    for finding in findings:
        fp = _finding_fingerprint(finding)
        state = effective_decision_state(
            decisions.get(fp) if fp else None, now=now, finding_present=fp in present
        )
        if state in _RESOLVED_STATES:
            continue
        prepared.append(
            {
                "rule_id": _finding_rule_id(finding),
                "severity": finding.get("severity"),
                "fingerprint": fp,
                "waived": state == "waived",
            }
        )

    axis_index = _axes_by_key(axes)
    named_axes = {
        str(axis.get("axis") or "") for level in levels for axis in level.get("axes") or []
    }
    unassessed = sorted(
        key
        for key in named_axes
        if not (axis_index.get(key) and axis_index[key].get("assessed") is True)
    )
    evidence_map = dict(evidence or {})

    reached = -1
    excused: set = set()
    blockers: List[Dict[str, Any]] = []
    for index, level in enumerate(levels):
        required = _accumulate(levels, index)
        waivers_satisfy = bool(level.get("waiversSatisfy"))
        counted = [f for f in prepared if not (f["waived"] and waivers_satisfy)]
        key = str(level.get("key") or "")
        blockers = (
            _rule_blockers(key, required["rules"], counted)
            + _axis_blockers(key, required["axes"], axis_index)
            + _evidence_blockers(key, required["evidence"], evidence_map)
        )
        if blockers:
            break
        reached = index
        if waivers_satisfy:
            excused.update(
                f["fingerprint"]
                for f in prepared
                if f["waived"]
                and f["rule_id"] in required["rules"]
                and _severity_rank(f["severity"])
                > _SEVERITY_RANK.get(required["rules"][f["rule_id"]], 3)
            )

    top = levels[reached] if reached >= 0 else None
    upcoming = levels[reached + 1] if reached + 1 < len(levels) else None
    return {
        "ladderName": (ladder or {}).get("name"),
        "level": top.get("key") if top else None,
        "levelLabel": top.get("label") if top else None,
        "levelIndex": reached if reached >= 0 else None,
        "nextLevel": upcoming.get("key") if upcoming else None,
        "nextLevelLabel": upcoming.get("label") if upcoming else None,
        "blockers": blockers if upcoming else [],
        "waiversCounted": len(excused),
        "unassessedAxes": unassessed,
        "reason": None if top else REASON_BELOW_FIRST_LEVEL,
    }
