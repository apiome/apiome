"""
Cumulative level gates — the one judgement GVM-1.3 (#5856) arms everywhere.

GVM-1.2 (:mod:`app.maturity_ladder`) answers *what level is this API at?* This module answers the
gate's question on top of it: *is that level at least the level required?* Every surface that
refuses or reports on a level calls :func:`judge_maturity` — the publish gate
(:mod:`app.maturity_publish_gate`), the deploy gate's ``maturity`` signal
(:func:`app.deploy_gate.evaluate_maturity`), the check suite's ``maturity`` component
(:func:`app.api_check_suite.judge_maturity_component`) and the lint CI gate
(:mod:`app.lint_gate`) — so the four can never disagree about the same draft.

Five outcomes, the CTG-4.5 vocabulary:

* ``pass`` — the level reached is at or above the required level;
* ``fail`` — it is below (``blockers`` say what keeps the subject from its next level);
* ``not_configured`` — nothing to judge: the policy pack has no ladder, or no level is required;
* ``unknown`` — something to judge that could not be: the required key is not a level of the
  frozen ladder, or the level result could not be read.

There is deliberately no ``warn``: a level is met or it is not.

The module is pure — no database, no HTTP, no clock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "MaturityJudgement",
    "REASON_BELOW_REQUIRED_LEVEL",
    "REASON_LEVEL_MET",
    "REASON_NO_LADDER",
    "REASON_NO_REQUIRED_LEVEL",
    "REASON_REQUIRED_LEVEL_UNKNOWN",
    "REASON_UNREADABLE",
    "STATUS_FAIL",
    "STATUS_NOT_CONFIGURED",
    "STATUS_PASS",
    "STATUS_UNKNOWN",
    "is_level_key",
    "judge_maturity",
    "ladder_level_keys",
    "required_publish_level",
]

#: Same spellings as :mod:`app.deploy_gate` (kept local so that module can import this one).
STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_NOT_CONFIGURED = "not_configured"
STATUS_UNKNOWN = "unknown"

#: The policy pack has no maturity ladder — the gate is never armed.
REASON_NO_LADDER = "maturity-no-ladder"
#: The pack has a ladder but no level is required of this subject.
REASON_NO_REQUIRED_LEVEL = "maturity-no-required-level"
#: The required key does not name a level of the frozen ladder.
REASON_REQUIRED_LEVEL_UNKNOWN = "maturity-required-level-unknown"
#: The level result could not be read.
REASON_UNREADABLE = "maturity-unreadable"
#: The subject reached the required level.
REASON_LEVEL_MET = "maturity-level-met"
#: The subject is below the required level.
REASON_BELOW_REQUIRED_LEVEL = "maturity-below-required-level"

#: Shape of a level key (GVM-1.1 keys are short slugs such as ``bronze`` or ``tier-2``).
_LEVEL_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def is_level_key(value: Any) -> bool:
    """Whether ``value`` has the shape of a ladder level key (``bronze``, ``tier-2``)."""
    return isinstance(value, str) and bool(_LEVEL_KEY.match(value))


def ladder_level_keys(ladder: Optional[Mapping[str, Any]]) -> List[str]:
    """The level keys of ``ladder``, lowest first (empty when there is no ladder)."""
    return [str(level.get("key") or "") for level in (ladder or {}).get("levels") or []]


def required_publish_level(pack: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The level key frozen into a policy pack row, or ``None`` when the gate is not armed."""
    value = (pack or {}).get("required_publish_level")
    return str(value) if value else None


def _level_label(ladder: Optional[Mapping[str, Any]], key: Optional[str]) -> Optional[str]:
    """The display label of level ``key`` in ``ladder``, or ``None``."""
    for level in (ladder or {}).get("levels") or []:
        if str(level.get("key") or "") == key:
            return str(level.get("label") or key)
    return None


@dataclass(frozen=True)
class MaturityJudgement:
    """A subject's level judged against a required level.

    Attributes:
        status: ``pass`` | ``fail`` | ``not_configured`` | ``unknown``.
        reason: One of the ``REASON_*`` codes — branch on this, not on ``detail``.
        ladder_name: The frozen ladder's name, when there is one.
        level: Key of the highest level reached, ``None`` when none is.
        level_label: Its label.
        level_index: Its position in the ladder (0 = lowest).
        required_level: The key required, when one is.
        required_level_label: Its label in the ladder.
        required_level_index: Its position in the ladder, ``None`` when it is not a level.
        blockers: GVM-1.2 blockers of the subject's next level (only carried when ``fail``).
        detail: Free-text explanation (the read failure, for ``unknown``).
    """

    status: str
    reason: str
    ladder_name: Optional[str] = None
    level: Optional[str] = None
    level_label: Optional[str] = None
    level_index: Optional[int] = None
    required_level: Optional[str] = None
    required_level_label: Optional[str] = None
    required_level_index: Optional[int] = None
    blockers: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    detail: Optional[str] = None

    @property
    def armed(self) -> bool:
        """Whether there was something to judge (a ladder and a required level)."""
        return self.status != STATUS_NOT_CONFIGURED

    def message(self) -> str:
        """One human sentence for dialogs, gate details and audit rows."""
        reached = self.level_label or self.level
        required = self.required_level_label or self.required_level
        if self.reason == REASON_NO_LADDER:
            return "The style guide has no maturity ladder, so no level is required."
        if self.reason == REASON_NO_REQUIRED_LEVEL:
            at = f" (currently {reached})" if reached else ""
            return f"No maturity level is required{at}."
        if self.reason == REASON_REQUIRED_LEVEL_UNKNOWN:
            name = f" {self.ladder_name!r}" if self.ladder_name else ""
            return (
                f"The required level {self.required_level!r} is not a level of the "
                f"ladder{name}, so the level cannot be judged."
            )
        if self.reason == REASON_UNREADABLE:
            return "The maturity level could not be read, so it cannot be judged."
        if self.status == STATUS_PASS:
            return f"Maturity level {reached} meets the required level {required}."
        current = f"at {reached}" if reached else "below the first level"
        count = len(self.blockers)
        tail = f" ({count} blocker{'s' if count != 1 else ''} to the next level)" if count else ""
        return f"This version is {current}; {required} is required{tail}."

    def as_payload(self) -> Dict[str, Any]:
        """The camelCase shape shared by the 422 body, audit rows and gate payloads."""
        return {
            "status": self.status,
            "reason": self.reason,
            "ladderName": self.ladder_name,
            "level": self.level,
            "levelLabel": self.level_label,
            "levelIndex": self.level_index,
            "requiredLevel": self.required_level,
            "requiredLevelLabel": self.required_level_label,
            "requiredLevelIndex": self.required_level_index,
            "blockers": [dict(b) for b in self.blockers],
            "detail": self.detail,
            "message": self.message(),
        }


def judge_maturity(
    result: Optional[Mapping[str, Any]],
    *,
    ladder: Optional[Mapping[str, Any]],
    required_level: Optional[str],
    detail: Optional[str] = None,
) -> MaturityJudgement:
    """Judge a GVM-1.2 level result against a required level.

    Args:
        result: The :func:`app.maturity_ladder.evaluate_ladder` result for the subject (as
            stored in ``gate_results.maturity``), or ``None`` when it could not be read.
        ladder: The frozen ``{name, levels}`` ladder of the policy pack, or ``None``.
        required_level: The level key required, or ``None`` when no level is required.
        detail: Why ``result`` is missing, when it is (carried on the ``unknown`` judgement).

    Returns:
        The :class:`MaturityJudgement`. A pack without a ladder is always ``not_configured`` —
        whatever is required — so a guide without a ladder never arms a gate.
    """
    keys = ladder_level_keys(ladder)
    ladder_name = (ladder or {}).get("name") if keys else None
    if not keys:
        return MaturityJudgement(status=STATUS_NOT_CONFIGURED, reason=REASON_NO_LADDER)

    base: Dict[str, Any] = {"ladder_name": ladder_name}
    if isinstance(result, Mapping):
        level = result.get("level")
        base.update(
            level=level,
            level_label=result.get("levelLabel") or _level_label(ladder, level),
            level_index=result.get("levelIndex"),
        )
    if not required_level:
        return MaturityJudgement(
            status=STATUS_NOT_CONFIGURED, reason=REASON_NO_REQUIRED_LEVEL, **base
        )

    base["required_level"] = required_level
    if required_level not in keys:
        return MaturityJudgement(
            status=STATUS_UNKNOWN, reason=REASON_REQUIRED_LEVEL_UNKNOWN, detail=detail, **base
        )
    required_index = keys.index(required_level)
    base.update(
        required_level_label=_level_label(ladder, required_level),
        required_level_index=required_index,
    )
    if not isinstance(result, Mapping):
        return MaturityJudgement(
            status=STATUS_UNKNOWN, reason=REASON_UNREADABLE, detail=detail, **base
        )

    reached = result.get("levelIndex")
    if isinstance(reached, int) and reached >= required_index:
        return MaturityJudgement(status=STATUS_PASS, reason=REASON_LEVEL_MET, **base)
    blockers: Sequence[Any] = result.get("blockers") or []
    return MaturityJudgement(
        status=STATUS_FAIL,
        reason=REASON_BELOW_REQUIRED_LEVEL,
        blockers=tuple(dict(b) for b in blockers if isinstance(b, Mapping)),
        **base,
    )
