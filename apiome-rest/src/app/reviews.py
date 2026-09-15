"""Review requests and decisions — the shared vocabulary of COL-2.1 (#4517).

A **review** asks named reviewers whether one draft (unpublished) version is ready. It is decided in
**rounds**: requesting starts round 1 with a ``pending`` row per reviewer, each reviewer records
``approve`` or ``request_changes`` once, and the review moves to ``approved`` when every reviewer
approved or to ``changes_requested`` as soon as one did not. Once the spec changes, a re-request
starts the next round with fresh ``pending`` rows; the earlier rows stay as history. The state
machine itself lives in :mod:`app.review_lifecycle`.

This module holds only data: the stable refusal codes, the refusal exception, the bounds, and the
request/response models the routes (:mod:`app.review_routes`) and the store
(:mod:`app.review_store`) share. The storage lives in apiome-db V261.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CODE_ALREADY_DECIDED",
    "CODE_ALREADY_OPEN",
    "CODE_CLOSED",
    "CODE_CONFLICT",
    "CODE_FORBIDDEN",
    "CODE_INVALID_REVIEWERS",
    "CODE_NOT_IN_REVIEW",
    "CODE_NOT_REVIEWER",
    "CODE_PROJECT_NOT_FOUND",
    "CODE_REVIEW_NOT_FOUND",
    "CODE_SELF_REVIEW",
    "CODE_SPEC_CHANGED",
    "CODE_SPEC_UNCHANGED",
    "CODE_VERSION_NOT_FOUND",
    "CODE_VERSION_PUBLISHED",
    "MAX_NOTE_LENGTH",
    "MAX_REVIEWERS",
    "RecordableDecision",
    "ReviewDecision",
    "ReviewDecisionCreate",
    "ReviewDetail",
    "ReviewReRequest",
    "ReviewRecord",
    "ReviewRequestCreate",
    "ReviewState",
    "ReviewValidationError",
    "ReviewerDecisionRecord",
    "VersionReviewState",
    "VersionReviewStatus",
]

#: The most reviewers one round may ask.
MAX_REVIEWERS = 20

#: The longest decision note, in characters. Mirrors ``review_reviewers_note_check``.
MAX_NOTE_LENGTH = 5_000

ReviewState = Literal["in_review", "approved", "changes_requested"]
VersionReviewState = Literal["draft", "in_review", "approved", "changes_requested"]
ReviewDecision = Literal["approve", "request_changes", "pending"]
RecordableDecision = Literal["approve", "request_changes"]

# Stable refusal codes. A client branches on the code, never on the message.
CODE_PROJECT_NOT_FOUND = "review-project-not-found"
CODE_VERSION_NOT_FOUND = "review-version-not-found"
CODE_REVIEW_NOT_FOUND = "review-not-found"
#: Only a draft (unpublished) version can be reviewed or decided on.
CODE_VERSION_PUBLISHED = "review-version-published"
#: The version already has an open review.
CODE_ALREADY_OPEN = "review-already-open"
#: The reviewer list is empty, too long, malformed, or names someone who is not a tenant member.
CODE_INVALID_REVIEWERS = "review-invalid-reviewers"
#: The requester named themself as a reviewer.
CODE_SELF_REVIEW = "review-self-review"
#: Withdrawing is limited to the requester or a tenant administrator.
CODE_FORBIDDEN = "review-forbidden"
#: Only a reviewer of the current round may record a decision.
CODE_NOT_REVIEWER = "review-not-reviewer"
#: The reviewer already decided in this round; decisions are immutable.
CODE_ALREADY_DECIDED = "review-already-decided"
#: A decision needs the review to be ``in_review``.
CODE_NOT_IN_REVIEW = "review-not-in-review"
#: The review was withdrawn.
CODE_CLOSED = "review-closed"
#: A re-request needs the spec to have changed since the current round was requested.
CODE_SPEC_UNCHANGED = "review-spec-unchanged"
#: The spec changed since the current round was requested; re-request before deciding.
CODE_SPEC_CHANGED = "review-spec-changed"
#: Someone else changed the review between the read and the write; read it again and retry.
CODE_CONFLICT = "review-conflict"


class ReviewValidationError(Exception):
    """A refusal from the review store, carrying a stable code.

    Attributes:
        code: One of the ``CODE_*`` constants in this module.
    """

    def __init__(self, code: str, message: str) -> None:
        """Create the refusal.

        Args:
            code: The stable refusal code.
            message: A human-readable explanation.
        """
        super().__init__(message)
        self.code = code


class ReviewerDecisionRecord(BaseModel):
    """One reviewer's row in one round of a review."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The reviewer row id.")
    review_id: str
    round: int = Field(ge=1, description="The round this row belongs to.")
    user_id: Optional[str] = Field(
        default=None, description="The reviewer; null once that user has been deleted."
    )
    user_name: Optional[str] = Field(default=None, description="The reviewer's display name.")
    decision: ReviewDecision = Field(
        description=(
            "`approve`, `request_changes`, or `pending`. A pending row in an earlier round was "
            "superseded by a re-request before the reviewer decided."
        )
    )
    note: Optional[str] = Field(default=None, description="The note recorded with the decision.")
    decided_at: Optional[datetime] = Field(
        default=None, description="When the decision was recorded; null while pending."
    )
    created_at: datetime = Field(description="When the reviewer was asked (the round's request time).")


class ReviewRecord(BaseModel):
    """One stored review, with the tally of its current round."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The review id.")
    tenant_id: str
    project_id: str
    version_id: str = Field(description="The version (revision) under review.")
    version_label: Optional[str] = Field(default=None, description="The version's label, e.g. `1.2.0`.")
    requested_by: Optional[str] = Field(default=None, description="Who requested the review.")
    requested_by_name: Optional[str] = Field(default=None, description="Their display name.")
    state: ReviewState = Field(description="`in_review`, `approved`, or `changes_requested`.")
    round: int = Field(ge=1, description="The current round; each re-request starts the next one.")
    spec_fingerprint: str = Field(
        description="Fingerprint of the content the current round judges (sha256 of the rebuilt OpenAPI document)."
    )
    reviewer_count: int = Field(default=0, ge=0, description="Reviewers in the current round.")
    approved_count: int = Field(default=0, ge=0, description="Current-round approvals.")
    changes_requested_count: int = Field(default=0, ge=0, description="Current-round change requests.")
    pending_count: int = Field(default=0, ge=0, description="Current-round reviewers yet to decide.")
    closed_at: Optional[datetime] = Field(
        default=None, description="When the review was withdrawn; null while it is open."
    )
    closed_by: Optional[str] = Field(default=None, description="Who withdrew it.")
    created_at: datetime
    updated_at: datetime = Field(description="The latest request, re-request, decision, or withdrawal.")


class ReviewDetail(BaseModel):
    """A review with its reviewers, its decision history, and whether its content is stale."""

    model_config = ConfigDict(extra="forbid")

    review: ReviewRecord
    reviewers: List[ReviewerDecisionRecord] = Field(
        default_factory=list, description="The current round's reviewers and their decisions."
    )
    history: List[ReviewerDecisionRecord] = Field(
        default_factory=list,
        description="Every earlier round's rows, unchanged since they were recorded; oldest round first.",
    )
    spec_changed: Optional[bool] = Field(
        default=None,
        description=(
            "True when the version's content no longer matches the current round's "
            "`spec_fingerprint` — its decisions are stale and the review should be re-requested. "
            "Null for a withdrawn review."
        ),
    )


class VersionReviewStatus(BaseModel):
    """Where one version stands in review."""

    model_config = ConfigDict(extra="forbid")

    version_id: str
    version_label: Optional[str] = None
    published: bool = Field(description="Whether the version is published; published versions cannot be reviewed.")
    state: VersionReviewState = Field(
        description="The open review's state, or `draft` when the version has no open review."
    )
    review: Optional[ReviewDetail] = Field(default=None, description="The open review, when there is one.")


class ReviewRequestCreate(BaseModel):
    """Request a review of a draft version.

    Attributes:
        version: The version — its revision id or its version label.
        reviewers: User ids of the tenant members to ask; the requester cannot be one of them.
    """

    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=255)
    reviewers: List[str] = Field(min_length=1, max_length=MAX_REVIEWERS)


class ReviewReRequest(BaseModel):
    """Re-request a review after the spec changed.

    Attributes:
        reviewers: The reviewers to ask in the new round; omit to ask the current round's
            reviewers again.
    """

    model_config = ConfigDict(extra="forbid")

    reviewers: Optional[List[str]] = Field(default=None, min_length=1, max_length=MAX_REVIEWERS)


class ReviewDecisionCreate(BaseModel):
    """Record a reviewer's decision.

    Attributes:
        decision: ``approve`` or ``request_changes``.
        note: An optional explanation.
    """

    model_config = ConfigDict(extra="forbid")

    decision: RecordableDecision
    note: Optional[str] = Field(default=None, max_length=MAX_NOTE_LENGTH)
