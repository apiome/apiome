"""Draft branches and merge requests — the shared vocabulary of COL-4.3 (#4527).

A **draft branch** is a named branch drafted off a **version line** — an existing branch such as
``main``. Creating it copies the line's tip into a new draft revision that becomes the branch's
tip, so editing the branch never touches the line.

A **merge request** proposes merging a draft branch back into a line. It owns no review or merge
logic of its own; it composes the three pieces that already exist:

* the **review** (COL-2.1) of the branch's tip revision — reviewers decide there;
* the **merge session** (``merge_sessions``) — the merge runs through the existing three-way merge
  path, and conflicts are the session's conflict rows;
* the **classified diff** (CTG-1.x) — the Changes tab compares the merge base with the branch tip.

This module holds only data: the stable refusal codes, the refusal exception, and the models the
routes (:mod:`app.merge_request_routes`) and the store (:mod:`app.merge_request_store`) share.
The storage lives in apiome-db V377.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .reviews import MAX_REVIEWERS, ReviewDetail

__all__ = [
    "BLOCKER_APPROVAL_POLICY",
    "BLOCKER_CHANGES_REQUESTED",
    "BLOCKER_CONFLICTS",
    "BLOCKER_NO_REVIEW",
    "BLOCKER_REVIEW_OUTDATED",
    "BLOCKER_REVIEW_PENDING",
    "BLOCKER_REVIEW_STALE",
    "BLOCKER_TARGET_IMMUTABLE",
    "CODE_BRANCH_EXISTS",
    "CODE_BRANCH_NOT_FOUND",
    "CODE_CONFLICTS",
    "CODE_INVALID_BRANCH_NAME",
    "CODE_INVALID_LABEL",
    "CODE_LABEL_TAKEN",
    "CODE_MERGE_REQUEST_NOT_FOUND",
    "CODE_NOT_DRAFT_BRANCH",
    "CODE_NOT_OPEN",
    "CODE_NOT_READY",
    "CODE_ALREADY_OPEN",
    "CODE_PROJECT_NOT_FOUND",
    "CODE_SAME_BRANCH",
    "CODE_FORBIDDEN",
    "DraftBranchCreate",
    "DraftBranchRecord",
    "MAX_DESCRIPTION_LENGTH",
    "MAX_TITLE_LENGTH",
    "MergeBlocker",
    "MergeConflict",
    "MergeReadiness",
    "MergeRequestCreate",
    "MergeRequestDetail",
    "MergeRequestMerge",
    "MergeRequestRecord",
    "MergeRequestReviewRequest",
    "MergeRequestState",
    "MergeRequestValidationError",
]

#: The longest merge request title, in characters. Mirrors ``merge_requests.title``.
MAX_TITLE_LENGTH = 200

#: The longest merge request description. Mirrors ``merge_requests_description_check``.
MAX_DESCRIPTION_LENGTH = 5_000

MergeRequestState = Literal["open", "merged", "closed"]

# Stable refusal codes. A client branches on the code, never on the message.
CODE_PROJECT_NOT_FOUND = "mr-project-not-found"
CODE_MERGE_REQUEST_NOT_FOUND = "mr-not-found"
#: A named branch (source, target, or the line a draft is drafted off) does not exist.
CODE_BRANCH_NOT_FOUND = "mr-branch-not-found"
#: A branch with that name already exists in the project.
CODE_BRANCH_EXISTS = "mr-branch-exists"
#: The branch name is not a valid branch label.
CODE_INVALID_BRANCH_NAME = "mr-invalid-branch-name"
#: The draft revision's version label is not semantic-versioned.
CODE_INVALID_LABEL = "mr-invalid-label"
#: The draft revision's version label is already used by another revision of the project.
CODE_LABEL_TAKEN = "mr-label-taken"
#: Only a draft branch can be the source of a merge request.
CODE_NOT_DRAFT_BRANCH = "mr-not-draft-branch"
#: Source and target are the same branch.
CODE_SAME_BRANCH = "mr-same-branch"
#: The source branch already has an open merge request.
CODE_ALREADY_OPEN = "mr-already-open"
#: The merge request is merged or closed, so it cannot change.
CODE_NOT_OPEN = "mr-not-open"
#: The merge request is not ready to merge; ``blockers`` says why.
CODE_NOT_READY = "mr-not-ready"
#: The merge session found conflicts; the branch must be updated before it can merge.
CODE_CONFLICTS = "mr-conflicts"
#: The action needs an attributable user.
CODE_FORBIDDEN = "mr-forbidden"

# Merge blockers — why a merge request cannot merge yet. Reported on every read, so the page can
# say what is missing before anyone presses Merge.
#: No open review is attached (never requested, or withdrawn).
BLOCKER_NO_REVIEW = "no-review"
#: The review judged an older tip of the branch; request a review of the current tip.
BLOCKER_REVIEW_OUTDATED = "review-outdated"
#: Reviewers have not all decided.
BLOCKER_REVIEW_PENDING = "review-pending"
#: A reviewer requested changes.
BLOCKER_CHANGES_REQUESTED = "changes-requested"
#: The branch changed after the review round was requested; re-request it.
BLOCKER_REVIEW_STALE = "review-stale"
#: The project's approval policy (COL-2.3) is not satisfied.
BLOCKER_APPROVAL_POLICY = "approval-policy"
#: The latest merge session of the current tips has conflicts.
BLOCKER_CONFLICTS = "conflicts"
#: The line's tip is published and immutable; only a tenant administrator may merge, with a reason.
BLOCKER_TARGET_IMMUTABLE = "target-immutable"


class MergeRequestValidationError(Exception):
    """A refusal from the merge request store, carrying a stable code.

    Attributes:
        code: One of the ``CODE_*`` constants in this module.
        extra: Additional fields for the error body (e.g. ``blockers``, ``conflicts``).
    """

    def __init__(self, code: str, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        """Create the refusal.

        Args:
            code: The stable refusal code.
            message: A human-readable explanation.
            extra: Additional machine-readable fields for the error body.
        """
        super().__init__(message)
        self.code = code
        self.extra = dict(extra or {})


class DraftBranchCreate(BaseModel):
    """Create a draft branch off a version line.

    Attributes:
        name: The new branch's name (letters, digits, ``. _ - /``; starts with a letter).
        base_branch: The version line to draft off — a branch name or id. Omit for the project's
            default branch.
        version_label: The draft revision's version label. Omit to take the next patch version.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    base_branch: Optional[str] = Field(default=None, min_length=1, max_length=255)
    version_label: Optional[str] = Field(default=None, min_length=1, max_length=255)


class DraftBranchRecord(BaseModel):
    """A draft branch, with the line it was drafted off."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The branch id.")
    project_id: str
    name: str
    tip_revision_id: str = Field(description="The branch's tip — the draft revision edits land on.")
    tip_version_label: Optional[str] = Field(default=None, description="The tip's version label.")
    base_branch_id: Optional[str] = Field(
        default=None, description="The version line (branch) it was drafted off; null once that branch is gone."
    )
    base_branch_name: Optional[str] = Field(default=None, description="That line's name.")
    branched_from_revision_id: Optional[str] = Field(
        default=None, description="The line's tip when the draft was created."
    )
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None


class MergeRequestCreate(BaseModel):
    """Open a merge request from a draft branch, asking reviewers to review its tip.

    Attributes:
        source_branch: The draft branch — name or id.
        target_branch: The line to merge into — name or id. Omit for the line the draft was
            drafted off.
        title: A one-line summary.
        description: Optional detail.
        reviewers: User ids of the tenant members to ask; the requester cannot be one of them.
            Required unless the branch tip already has an open review, which is then attached.
    """

    model_config = ConfigDict(extra="forbid")

    source_branch: str = Field(min_length=1, max_length=255)
    target_branch: Optional[str] = Field(default=None, min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    description: Optional[str] = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    reviewers: Optional[List[str]] = Field(default=None, min_length=1, max_length=MAX_REVIEWERS)


class MergeRequestReviewRequest(BaseModel):
    """Request a review of the source branch's current tip.

    Used when the branch moved on after the review was requested (``review-outdated``) or the
    review was withdrawn. Any open review of an older tip is withdrawn first.

    Attributes:
        reviewers: The reviewers to ask; omit to ask the previous review's reviewers again.
    """

    model_config = ConfigDict(extra="forbid")

    reviewers: Optional[List[str]] = Field(default=None, min_length=1, max_length=MAX_REVIEWERS)


class MergeRequestMerge(BaseModel):
    """Merge an approved merge request.

    Attributes:
        override_published_immutability: Tenant administrators only — merge into a line whose tip
            is published and immutable (forwarded to the merge path, which audits it).
        override_reason: The audit text for that override.
    """

    model_config = ConfigDict(extra="forbid")

    override_published_immutability: bool = False
    override_reason: Optional[str] = Field(default=None, max_length=2000)


class MergeRequestRecord(BaseModel):
    """One stored merge request."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The merge request id.")
    tenant_id: str
    project_id: str
    title: str
    description: Optional[str] = None
    state: MergeRequestState = Field(description="`open`, `merged`, or `closed`.")
    source_branch_id: Optional[str] = Field(default=None, description="The draft branch; null once deleted.")
    source_branch_name: str
    target_branch_id: Optional[str] = Field(default=None, description="The line; null once deleted.")
    target_branch_name: str
    review_id: Optional[str] = Field(default=None, description="The review of the branch tip.")
    merge_session_id: Optional[str] = Field(default=None, description="The latest merge session run for this request.")
    merged_version_id: Optional[str] = Field(default=None, description="The revision the merge produced on the line.")
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    merged_by: Optional[str] = None
    merged_at: Optional[datetime] = None
    closed_by: Optional[str] = None
    closed_at: Optional[datetime] = None


class MergeBlocker(BaseModel):
    """One reason a merge request cannot merge yet."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="One of the `BLOCKER_*` codes, e.g. `review-pending`.")
    message: str


class MergeConflict(BaseModel):
    """One conflicting path of the merge session, as the merge-session conflict list reports it."""

    model_config = ConfigDict(extra="forbid")

    path: str
    kinds: List[str] = Field(default_factory=list, description="`threeWay`, `blend`, and/or `twoWay`.")


class MergeReadiness(BaseModel):
    """Whether the merge request can merge now, and if not, why."""

    model_config = ConfigDict(extra="forbid")

    can_merge: bool
    blockers: List[MergeBlocker] = Field(default_factory=list)
    approval: Optional[Dict[str, Any]] = Field(
        default=None, description="The COL-2.3 approval-policy assessment, when a policy applies."
    )


class MergeRequestDetail(BaseModel):
    """A merge request with its branches, review, merge session, and readiness."""

    model_config = ConfigDict(extra="forbid")

    merge_request: MergeRequestRecord
    source_tip_revision_id: Optional[str] = Field(default=None, description="The branch's current tip.")
    source_tip_version_label: Optional[str] = None
    target_tip_revision_id: Optional[str] = Field(default=None, description="The line's current tip.")
    target_tip_version_label: Optional[str] = None
    merge_base_revision_id: Optional[str] = Field(
        default=None,
        description="The common ancestor the Changes tab compares the branch tip with.",
    )
    merge_base_version_label: Optional[str] = None
    review: Optional[ReviewDetail] = Field(default=None, description="The attached review, when there is one.")
    review_outdated: bool = Field(
        default=False, description="True when the review judged an older tip than the branch's current one."
    )
    merge_session: Optional[Dict[str, Any]] = Field(
        default=None, description="The latest merge session (`status`, tips, merge base)."
    )
    conflicts: List[MergeConflict] = Field(
        default_factory=list, description="That session's conflicts, when its tips are still current."
    )
    readiness: MergeReadiness
