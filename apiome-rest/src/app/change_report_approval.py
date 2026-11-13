"""
Change-report approval: the states, the transitions and who may make them (#2705, CR-V2-01).

A publication change report moves through three states::

    draft --submit--> pending_review --approve--> approved
                            |
                            +--reject--> draft

Only an **approved** report can be exported as PDF. Changing the report's content (an edit or
a regeneration) returns it to ``draft``, so what was approved is always what is exported.

This module holds the rules only — no database, no HTTP — so they can be tested on their own
and so the routes (``change_report_enterprise_routes.py``) cannot word them differently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

STATE_DRAFT = "draft"
STATE_PENDING_REVIEW = "pending_review"
STATE_APPROVED = "approved"

#: Every approval state, in the order a report moves through them.
APPROVAL_STATES = (STATE_DRAFT, STATE_PENDING_REVIEW, STATE_APPROVED)

TRANSITION_SUBMIT = "submit"
TRANSITION_APPROVE = "approve"
TRANSITION_REJECT = "reject"

#: transition -> (state it starts from, state it ends in)
_TRANSITIONS = {
    TRANSITION_SUBMIT: (STATE_DRAFT, STATE_PENDING_REVIEW),
    TRANSITION_APPROVE: (STATE_PENDING_REVIEW, STATE_APPROVED),
    TRANSITION_REJECT: (STATE_PENDING_REVIEW, STATE_DRAFT),
}

#: Longest reviewer note accepted on approve / reject.
MAX_REVIEW_NOTE_LENGTH = 1000


@dataclass(frozen=True)
class TransitionRefusal:
    """Why a transition is not allowed.

    Attributes:
        status_code: The HTTP status the route answers with — 403 for the wrong person, 409 for
            the wrong state.
        detail: The message for the caller.
    """

    status_code: int
    detail: str


def normalize_state(raw: Optional[str]) -> str:
    """Read a stored approval state, treating a missing or unknown value as ``draft``.

    Args:
        raw: The ``approval_state`` column as read (absent on rows read before V370).

    Returns:
        One of :data:`APPROVAL_STATES`.
    """
    return raw if raw in APPROVAL_STATES else STATE_DRAFT


def target_state(transition: str) -> str:
    """Return the state a transition ends in.

    Args:
        transition: ``submit``, ``approve`` or ``reject``.

    Returns:
        The resulting approval state.
    """
    return _TRANSITIONS[transition][1]


def check_transition(
    transition: str,
    *,
    current_state: Optional[str],
    actor_id: str,
    actor_is_tenant_admin: bool,
    actor_can_edit_report: bool,
    submitted_by: Optional[str],
) -> Optional[TransitionRefusal]:
    """Decide whether one person may make one transition on a report right now.

    The rules:

    * **submit** — whoever may edit the report (the version's creator or a tenant
      administrator), from ``draft``.
    * **approve** — a tenant administrator who did **not** submit it, from ``pending_review``.
      The second pair of eyes is the point of the review.
    * **reject** — a tenant administrator, from ``pending_review``. The submitter may reject
      (withdraw) their own submission.

    Args:
        transition: ``submit``, ``approve`` or ``reject``.
        current_state: The report's stored approval state.
        actor_id: The acting user's id.
        actor_is_tenant_admin: Whether the actor administers the tenant.
        actor_can_edit_report: Whether the actor may edit this report (creator or admin).
        submitted_by: Who submitted the report for review, when someone has.

    Returns:
        ``None`` when the transition is allowed, otherwise the refusal to answer with.
    """
    if transition not in _TRANSITIONS:
        return TransitionRefusal(400, f"Unknown transition: {transition}")

    # Who, before what state: a caller who may not act learns nothing about the report's state.
    if transition == TRANSITION_SUBMIT:
        if not actor_can_edit_report:
            return TransitionRefusal(
                403,
                "Only the version creator or a tenant administrator can submit this change "
                "report for review",
            )
    elif not actor_is_tenant_admin:
        return TransitionRefusal(
            403, f"Only a tenant administrator can {transition} a change report"
        )

    required, _ = _TRANSITIONS[transition]
    state = normalize_state(current_state)
    if state != required:
        return TransitionRefusal(
            409,
            f"Cannot {transition} a change report that is '{state}'; it must be '{required}'",
        )

    if (
        transition == TRANSITION_APPROVE
        and submitted_by is not None
        and str(submitted_by) == str(actor_id)
    ):
        return TransitionRefusal(
            403, "A change report must be approved by someone other than its submitter"
        )
    return None


def pdf_export_refusal(current_state: Optional[str]) -> Optional[TransitionRefusal]:
    """Say why a report cannot be exported as PDF, if it cannot.

    Args:
        current_state: The report's stored approval state.

    Returns:
        ``None`` for an approved report, otherwise a 409 refusal.
    """
    state = normalize_state(current_state)
    if state == STATE_APPROVED:
        return None
    return TransitionRefusal(
        409,
        f"Only an approved change report can be exported as PDF; this one is '{state}'",
    )


def normalize_review_note(note: Optional[str]) -> Optional[str]:
    """Trim a reviewer's note; an empty or whitespace-only one is no note.

    Args:
        note: The note as the caller sent it.

    Returns:
        The trimmed note, or ``None``.
    """
    trimmed = (note or "").strip()
    return trimmed or None
