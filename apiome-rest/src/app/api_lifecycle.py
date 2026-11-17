"""Product and plan lifecycle — the rules (APX-1.4, #6101).

Plans change: a tier is withdrawn or replaced. API products (:mod:`app.api_products`) and their plans
(:mod:`app.api_plans`) share one lifecycle, stored by apiome-db V389:

==============  ========================================================================================
State           What it means
==============  ========================================================================================
``draft``       Being written; not offered.
``published``   Offered: new subscriptions are accepted.
``deprecated``  Still served, but **new subscriptions are blocked**. It carries an optional retirement
                date (``retire_at``, its place on the sunset timeline), a message for consumers and —
                for a plan — the plan they should move to (``successor``).
``retired``     Over. A retired plan's provisioning is revoked; nothing returns from here.
==============  ========================================================================================

**Transitions** (:func:`check_transition`)::

    draft ⇄ published → deprecated → retired
                 ↑          │
                 └──────────┘  (reinstate: the deprecation is withdrawn and its dates cleared)

A new record starts as ``draft`` or ``published`` (:func:`check_initial_state`); deprecation and
retirement are things that *happen* to a record, so each stamps its time.

**Retiring waits for the date.** A deprecated record with a ``retire_at`` in the future cannot be
retired yet; one without a date can be retired whenever its owner decides (:func:`check_retire`).

**A successor keeps the key.** Migrating consumers to another plan re-provisions them into the new
plan's consumer group *without issuing new credentials*, so the successor must be a published plan of
the same product with the same auth strategy (:func:`successor_problem`).

This module is pure; :mod:`app.api_plan_store` and :mod:`app.api_product_store` apply it inside
their write transactions. Every refusal is a :class:`LifecycleError` carrying a stable
``api-lifecycle-*`` code, which the stores re-raise as their own validation errors.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

__all__ = [
    "CODE_INVALID_STATE",
    "CODE_RETIRE_EARLY",
    "CODE_SUCCESSOR_INVALID",
    "CODE_TRANSITION",
    "IMMINENT_DAYS",
    "INITIAL_STATES",
    "MAX_MESSAGE_LENGTH",
    "LifecycleError",
    "accepts_new_subscriptions",
    "check_initial_state",
    "check_retire",
    "check_transition",
    "lifecycle_changes",
    "normalize_message",
    "normalize_retire_at",
    "plan_group_name",
    "successor_problem",
    "timeline_status",
]

#: The move from the current state to the requested one is not a lifecycle step.
CODE_TRANSITION = "api-lifecycle-transition"
#: A new record asked to start as ``deprecated`` or ``retired``.
CODE_INVALID_STATE = "api-lifecycle-invalid-state"
#: The record's retirement date has not come yet.
CODE_RETIRE_EARLY = "api-lifecycle-retire-early"
#: The successor (or migration target) cannot take the plan's consumers.
CODE_SUCCESSOR_INVALID = "api-lifecycle-successor-invalid"

#: States a record may be created in.
INITIAL_STATES: Tuple[str, ...] = ("draft", "published")
#: A retirement this many days away or fewer is *imminent* (the sunset timeline's rule).
IMMINENT_DAYS = 30
#: The longest deprecation message (V389 rule 3).
MAX_MESSAGE_LENGTH = 1000

#: Where each state may go next.
_TRANSITIONS: Mapping[str, FrozenSet[str]] = {
    "draft": frozenset({"published"}),
    "published": frozenset({"draft", "deprecated"}),
    "deprecated": frozenset({"published", "retired"}),
    "retired": frozenset(),
}


class LifecycleError(ValueError):
    """A lifecycle refusal carrying a stable machine code.

    Attributes:
        code: One of the module's ``CODE_*`` constants.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def check_initial_state(state: str, noun: str) -> None:
    """Refuse creating a record that is already deprecated or retired.

    Args:
        state: The requested state.
        noun: ``plan`` or ``product``, for the message.

    Raises:
        LifecycleError: ``api-lifecycle-invalid-state``.
    """
    if state not in INITIAL_STATES:
        raise LifecycleError(
            CODE_INVALID_STATE, f"a new {noun} starts as draft or published; deprecate it once it exists"
        )


def check_transition(current: str, target: str, noun: str) -> None:
    """Refuse a state change that is not a lifecycle step. Staying in the same state is allowed.

    Args:
        current: The stored state.
        target: The requested state.
        noun: ``plan`` or ``product``, for the message.

    Raises:
        LifecycleError: ``api-lifecycle-transition`` — e.g. publishing a retired plan, or retiring a
            published one without deprecating it first.
    """
    if current == target or target in _TRANSITIONS.get(current, frozenset()):
        return
    if current == "retired":
        raise LifecycleError(CODE_TRANSITION, f"a retired {noun} cannot change state")
    if target == "retired":
        raise LifecycleError(CODE_TRANSITION, f"deprecate the {noun} before retiring it")
    raise LifecycleError(CODE_TRANSITION, f"a {current} {noun} cannot become {target}")


def normalize_message(message: Optional[str]) -> Optional[str]:
    """Return a trimmed deprecation message, ``None`` for a blank one.

    Args:
        message: The message sent.

    Returns:
        The message, or ``None``.

    Raises:
        LifecycleError: ``api-lifecycle-invalid-state`` for a message over :data:`MAX_MESSAGE_LENGTH`.
    """
    trimmed = (message or "").strip()
    if len(trimmed) > MAX_MESSAGE_LENGTH:
        raise LifecycleError(CODE_INVALID_STATE, f"a deprecation message is at most {MAX_MESSAGE_LENGTH} characters")
    return trimmed or None


def normalize_retire_at(value: Optional[datetime]) -> Optional[datetime]:
    """Return a retirement date in UTC (a naive value is read as UTC).

    Args:
        value: The date sent, or ``None``.

    Returns:
        The aware UTC datetime, or ``None``.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def check_retire(retire_at: Optional[datetime], now: datetime, noun: str) -> None:
    """Refuse retiring before the retirement date.

    Args:
        retire_at: The stored retirement date, or ``None`` (retire whenever the owner decides).
        now: The current time (aware).
        noun: ``plan`` or ``product``, for the message.

    Raises:
        LifecycleError: ``api-lifecycle-retire-early`` while ``retire_at`` is in the future.
    """
    when = normalize_retire_at(retire_at)
    if when is not None and when > now:
        raise LifecycleError(
            CODE_RETIRE_EARLY,
            f"this {noun} retires on {when.date().isoformat()}; retire it on or after that date, or move the date",
        )


def lifecycle_changes(
    row: Mapping[str, Any],
    *,
    target: str,
    sent: FrozenSet[str],
    retire_at: Optional[datetime],
    message: Optional[str],
    now: datetime,
    noun: str,
) -> Dict[str, Any]:
    """The lifecycle columns a write changes, after checking the step is allowed.

    * **published → deprecated** stamps ``deprecated_at`` and takes ``retire_at`` and the message.
    * **deprecated → deprecated** may move ``retire_at`` or change the message.
    * **deprecated → published** (reinstate) clears the deprecation columns (the plan store also
      clears the successor and the owners-notified marker, so a later deprecation notifies again).
    * **deprecated → retired** checks the date (:func:`check_retire`) and stamps ``retired_at``.
    * Sending ``retire_at`` or ``deprecation_message`` to a record that will not be deprecated is
      refused: they describe a deprecation.

    Args:
        row: The stored record (``state``, ``retire_at`` …).
        target: The state after the write (the stored one when the write does not change it).
        sent: The patch fields sent (``retire_at``, ``deprecation_message``).
        retire_at: The ``retire_at`` sent (meaningful only when in ``sent``).
        message: The ``deprecation_message`` sent (meaningful only when in ``sent``).
        now: The current time (aware).
        noun: ``plan`` or ``product``, for messages.

    Returns:
        ``{column: value}`` — only the columns that change.

    Raises:
        LifecycleError: ``api-lifecycle-transition`` for a step that is not allowed or deprecation
            fields on a record that is not deprecated, ``api-lifecycle-retire-early`` before the date,
            ``api-lifecycle-invalid-state`` for a message that is too long.
    """
    current = str(row["state"])
    check_transition(current, target, noun)
    describes_deprecation = bool({"retire_at", "deprecation_message"} & sent)
    if describes_deprecation and target != "deprecated":
        raise LifecycleError(
            CODE_TRANSITION, f"a retirement date and deprecation message belong to a deprecated {noun}"
        )
    changes: Dict[str, Any] = {}
    if target == "deprecated":
        if current != "deprecated":
            changes["deprecated_at"] = now
        if "retire_at" in sent:
            changes["retire_at"] = normalize_retire_at(retire_at)
        if "deprecation_message" in sent:
            changes["deprecation_message"] = normalize_message(message)
    elif current == "deprecated" and target == "published":
        changes.update(deprecated_at=None, retire_at=None, deprecation_message=None)
    elif current == "deprecated" and target == "retired":
        check_retire(row.get("retire_at"), now, noun)
        changes["retired_at"] = now
    return changes


def accepts_new_subscriptions(state: str) -> bool:
    """Whether a plan in this state takes new subscriptions — only a published one does.

    The access-request engine (APX-2.2) asks this before it accepts a request; a deprecated plan
    keeps its subscribers but takes no new ones.

    Args:
        state: The plan's state.

    Returns:
        True for ``published``.
    """
    return state == "published"


def successor_problem(plan: Mapping[str, Any], candidate: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Why ``candidate`` cannot take ``plan``'s consumers, or ``None`` when it can.

    The candidate must be another plan of the same product (the caller looks it up there), be
    published — it has to accept the consumers — and use the same auth strategy, so a consumer's
    credential still works after the move.

    Args:
        plan: The plan being replaced (``id``, ``auth_strategy``).
        candidate: The successor (``id``, ``slug``, ``state``, ``auth_strategy``), or ``None`` when
            no live plan of the product has that slug.

    Returns:
        A sentence saying what is wrong, or ``None``.
    """
    if candidate is None:
        return "the product has no such plan"
    if str(candidate["id"]) == str(plan["id"]):
        return "a plan cannot replace itself"
    if candidate["state"] != "published":
        return f"'{candidate['slug']}' is {candidate['state']}; consumers can only move to a published plan"
    if candidate["auth_strategy"] != plan["auth_strategy"]:
        return (
            f"'{candidate['slug']}' uses {candidate['auth_strategy']} and this plan uses {plan['auth_strategy']}; "
            "consumers keep their credentials, so both plans need the same auth strategy"
        )
    return None


def plan_group_name(product_slug: str, plan_slug: str) -> str:
    """The gateway consumer group a plan's consumers are provisioned into (``plan:payments-standard``).

    Args:
        product_slug: The product's slug.
        plan_slug: The plan's slug.

    Returns:
        The group name.
    """
    return f"plan:{product_slug}-{plan_slug}"


def timeline_status(state: str, retire_at: Optional[datetime], today: date) -> Tuple[str, str]:
    """Where a deprecated or retired record sits on the sunset timeline.

    Uses the version timeline's words (:func:`app.revision_deprecation.sunset_timeline_fields`) so
    one legend covers both: ``past``, ``imminent`` (≤ :data:`IMMINENT_DAYS` days) or ``announced``.

    Args:
        state: ``deprecated`` or ``retired``.
        retire_at: The retirement date, or ``None``.
        today: The current UTC day.

    Returns:
        ``(timeline_status, lifecycle_phase)`` — the phase is ``retired`` for a retired record,
        ``sunset_reached`` once a deprecated record's date has passed, ``deprecated`` before.
    """
    when = normalize_retire_at(retire_at)
    if state == "retired":
        return ("past", "retired")
    if when is None:
        return ("announced", "deprecated")
    day = when.date()
    if day < today:
        return ("past", "sunset_reached")
    if (day - today).days <= IMMINENT_DAYS:
        return ("imminent", "deprecated")
    return ("announced", "deprecated")
