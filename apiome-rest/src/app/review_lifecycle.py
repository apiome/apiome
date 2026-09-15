"""The review state machine — COL-2.1 (#4517).

A pure module with no storage and no HTTP: the vocabularies, the allowed transitions, and the one
rule that turns a round's decisions into a review state. :mod:`app.review_store` applies these
rules before it writes, and :class:`app.database.Database` applies :func:`state_after_decisions`
again inside the transaction that records a decision, so the state it stores is always computed
from the decisions it can see under the row lock.

The lifecycle, as the issue draws it::

    draft ──request──▶ in_review ──all approve──────▶ approved
                          │                              │
                          └──any request_changes──▶ changes_requested
                                                         │
    approved / changes_requested ──re-request (spec changed)──▶ in_review

* ``draft`` is never stored. A version with no open review *is* a draft for review purposes.
* A **round** is one request for decisions. Requesting starts round 1; every re-request starts the
  next round with fresh ``pending`` rows, so earlier decisions stay as immutable history.
* A re-request is allowed only when the spec changed since the current round was requested. That
  is also why ``in_review → in_review`` is allowed: when the spec changes while a round is still
  open, the approvals already given are stale, and a re-request is the only way to discard them.
"""

from __future__ import annotations

from typing import Iterable, Optional

__all__ = [
    "AUDIT_DECISION",
    "AUDIT_REQUESTED",
    "AUDIT_RE_REQUESTED",
    "AUDIT_STATE_CHANGED",
    "AUDIT_WITHDRAWN",
    "DECISIONS",
    "DECISION_APPROVE",
    "DECISION_PENDING",
    "DECISION_REQUEST_CHANGES",
    "RECORDABLE_DECISIONS",
    "REVIEW_STATES",
    "STATE_APPROVED",
    "STATE_CHANGES_REQUESTED",
    "STATE_DRAFT",
    "STATE_IN_REVIEW",
    "TRANSITIONS",
    "VERSION_REVIEW_STATES",
    "can_re_request",
    "can_record_decision",
    "is_allowed_transition",
    "state_after_decisions",
    "version_review_state",
]

#: A version with no open review. Never stored on a review row.
STATE_DRAFT = "draft"
#: Reviewers have been asked, and the current round is not yet decided.
STATE_IN_REVIEW = "in_review"
#: Every reviewer of the current round approved.
STATE_APPROVED = "approved"
#: At least one reviewer of the current round requested changes.
STATE_CHANGES_REQUESTED = "changes_requested"

#: The states a review row can hold. Mirrors ``reviews_state_check``.
REVIEW_STATES = (STATE_IN_REVIEW, STATE_APPROVED, STATE_CHANGES_REQUESTED)

#: The review states a version can be in, ``draft`` included.
VERSION_REVIEW_STATES = (STATE_DRAFT, *REVIEW_STATES)

DECISION_APPROVE = "approve"
DECISION_REQUEST_CHANGES = "request_changes"
DECISION_PENDING = "pending"

#: Every value a reviewer row's ``decision`` can hold. Mirrors ``review_reviewers_decision_check``.
DECISIONS = (DECISION_APPROVE, DECISION_REQUEST_CHANGES, DECISION_PENDING)

#: The decisions a reviewer can record; ``pending`` is only ever the starting value.
RECORDABLE_DECISIONS = (DECISION_APPROVE, DECISION_REQUEST_CHANGES)

#: Every ``(from, to)`` edge the lifecycle allows.
TRANSITIONS = frozenset(
    {
        (STATE_DRAFT, STATE_IN_REVIEW),
        (STATE_IN_REVIEW, STATE_APPROVED),
        (STATE_IN_REVIEW, STATE_CHANGES_REQUESTED),
        (STATE_APPROVED, STATE_IN_REVIEW),
        (STATE_CHANGES_REQUESTED, STATE_IN_REVIEW),
        (STATE_IN_REVIEW, STATE_IN_REVIEW),
    }
)

# ``workflow_audit.action`` values. Every row also carries the review id and round in ``detail``.
#: A review was requested: ``draft → in_review``, round 1.
AUDIT_REQUESTED = "review.requested"
#: A review was re-requested after a spec change: ``* → in_review``, next round.
AUDIT_RE_REQUESTED = "review.re_requested"
#: A reviewer recorded a decision.
AUDIT_DECISION = "review.decision"
#: A decision moved the review out of ``in_review``.
AUDIT_STATE_CHANGED = "review.state_changed"
#: The requester or a tenant administrator withdrew the review, closing it.
AUDIT_WITHDRAWN = "review.withdrawn"


def state_after_decisions(decisions: Iterable[str]) -> str:
    """Compute a review's state from the decisions of its current round.

    Args:
        decisions: The ``decision`` of every reviewer row in the current round.

    Returns:
        ``changes_requested`` when any reviewer requested changes; otherwise ``approved`` when
        there is at least one reviewer and every one approved; otherwise ``in_review``.
    """
    values = list(decisions)
    if DECISION_REQUEST_CHANGES in values:
        return STATE_CHANGES_REQUESTED
    if values and all(value == DECISION_APPROVE for value in values):
        return STATE_APPROVED
    return STATE_IN_REVIEW


def is_allowed_transition(from_state: str, to_state: str) -> bool:
    """Whether the lifecycle has an edge from one state to another.

    Args:
        from_state: The current state (``draft`` for a version with no open review).
        to_state: The state to move to.

    Returns:
        ``True`` when ``(from_state, to_state)`` is in :data:`TRANSITIONS`.
    """
    return (from_state, to_state) in TRANSITIONS


def can_record_decision(state: str) -> bool:
    """Whether a reviewer may record a decision on a review in this state.

    Once a round is decided either way, only a re-request opens it again.

    Args:
        state: The review's state.

    Returns:
        ``True`` only for ``in_review``.
    """
    return state == STATE_IN_REVIEW


def can_re_request(state: str) -> bool:
    """Whether an open review in this state may be re-requested.

    The spec must also have changed since the current round; that is checked by the store,
    because it needs the version's content.

    Args:
        state: The review's state.

    Returns:
        ``True`` for every stored review state that has an edge back to ``in_review``.
    """
    return is_allowed_transition(state, STATE_IN_REVIEW) and state != STATE_DRAFT


def version_review_state(open_review_state: Optional[str]) -> str:
    """The review state a version is in.

    Args:
        open_review_state: The state of the version's open review, or ``None`` when it has none.

    Returns:
        That state, or ``draft`` when there is no open review.
    """
    return open_review_state or STATE_DRAFT
