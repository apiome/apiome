"""Review store — COL-2.1 (#4517).

The rules between the HTTP surface (:mod:`app.review_routes`) and storage (apiome-db V261):

* **Scope.** Every read and write resolves the project inside the caller's tenant first (the same
  resolution comment threads use), and every review is read back through that project, so an id
  from another tenant or project is simply "not found".
* **Only drafts.** A review can be requested, re-requested, or decided only while its version is
  unpublished (``review-version-published``). Withdrawing stays possible after a publish.
* **One open review per version** (``review-already-open``); V261's partial unique index backs it.
* **Reviewers** are tenant members (active or pending — the members a comment may mention), named
  by user id, at most :data:`app.reviews.MAX_REVIEWERS`, never the requester.
* **Spec fingerprint.** A round records the fingerprint of the content it judges — a hash of the
  version's rebuilt OpenAPI document (:func:`spec_fingerprint`). A fingerprint is used rather than
  an edit timestamp because apiome-ui writes schema edits straight to Postgres.
* **Transitions** follow :mod:`app.review_lifecycle`. A decision is recorded once, by a reviewer of
  the current round, while the review is ``in_review`` and the spec still matches the round
  (``review-spec-changed`` otherwise). A re-request needs the spec to have changed
  (``review-spec-unchanged``) and starts the next round with fresh ``pending`` rows, so stale
  approvals never carry over and past decisions stay as history.
* **Ownership.** Withdrawing is limited to the requester or a tenant administrator
  (:func:`app.comment_store.can_moderate`). Route-level permissions are checked by the routes.
* **Races.** Each write re-checks its guard under a row lock; when it loses, the review is read
  again and the refusal names what changed.

Refusals raise :class:`app.reviews.ReviewValidationError` with a stable code. The audit rows for
every transition and decision are written by the database accessors, in the same transaction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import comment_store, notification_store
from .comments import CommentValidationError
from .compatibility_engine import openapi_for_revision
from .database import db
from .review_lifecycle import (
    DECISION_PENDING,
    STATE_IN_REVIEW,
    can_re_request,
    can_record_decision,
    version_review_state,
)
from .reviews import (
    CODE_ALREADY_DECIDED,
    CODE_ALREADY_OPEN,
    CODE_CLOSED,
    CODE_CONFLICT,
    CODE_FORBIDDEN,
    CODE_INVALID_REVIEWERS,
    CODE_NOT_IN_REVIEW,
    CODE_NOT_REVIEWER,
    CODE_PROJECT_NOT_FOUND,
    CODE_REVIEW_NOT_FOUND,
    CODE_SELF_REVIEW,
    CODE_SPEC_CHANGED,
    CODE_SPEC_UNCHANGED,
    CODE_VERSION_NOT_FOUND,
    CODE_VERSION_PUBLISHED,
    MAX_REVIEWERS,
    ReviewDecisionCreate,
    ReviewDetail,
    ReviewerDecisionRecord,
    ReviewRecord,
    ReviewRequestCreate,
    ReviewReRequest,
    ReviewValidationError,
    VersionReviewStatus,
)
from .revision_deprecation import is_uuid_string
from .version_quality_capture import openapi_source_fingerprint

__all__ = [
    "ReviewFilters",
    "get_review",
    "list_reviews",
    "record_decision",
    "re_request_review",
    "request_review",
    "resolve_project",
    "resolve_version",
    "spec_fingerprint",
    "validate_reviewers",
    "version_review_status",
    "withdraw_review",
]

#: The tenant slug the fingerprint's document is rebuilt under. The generated document does not
#: depend on it today; a constant keeps the fingerprint independent of the URL a caller used.
_FINGERPRINT_TENANT_SLUG = "tenant"

#: Columns of a review row that belong on :class:`ReviewRecord`.
_REVIEW_FIELDS = tuple(ReviewRecord.model_fields)

#: Columns of a reviewer row that belong on :class:`ReviewerDecisionRecord`.
_REVIEWER_FIELDS = tuple(ReviewerDecisionRecord.model_fields)


@dataclass(frozen=True)
class ReviewFilters:
    """What a review list read narrows to.

    Attributes:
        version: Only reviews of this version (revision id or version label).
        state: Only reviews in this state.
        open: ``True`` for open reviews only, ``False`` for withdrawn ones only, ``None`` for both.
        limit: Page size.
        offset: Reviews to skip.
    """

    version: Optional[str] = None
    state: Optional[str] = None
    open: Optional[bool] = None
    limit: int = 50
    offset: int = 0


# ---------------------------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------------------------


def resolve_project(tenant_id: str, project_ref: str) -> Dict[str, Any]:
    """Resolve a project slug or id to its row, within the tenant.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or UUID.

    Returns:
        The project row.

    Raises:
        ReviewValidationError: ``review-project-not-found`` when nothing matches.
    """
    try:
        return comment_store.resolve_project(tenant_id, project_ref)
    except CommentValidationError as exc:
        raise ReviewValidationError(CODE_PROJECT_NOT_FOUND, str(exc)) from exc


def resolve_version(tenant_id: str, project_id: str, version_ref: str) -> Dict[str, Any]:
    """Resolve a revision id or version label to a version of the project.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project the version must belong to.
        version_ref: A revision UUID or a version label such as ``1.0.0``.

    Returns:
        The version row.

    Raises:
        ReviewValidationError: ``review-version-not-found`` when nothing in the project matches.
    """
    try:
        return comment_store.resolve_version(tenant_id, project_id, version_ref)
    except CommentValidationError as exc:
        raise ReviewValidationError(CODE_VERSION_NOT_FOUND, str(exc)) from exc


def spec_fingerprint(tenant_id: str, version: Mapping[str, Any]) -> str:
    """Fingerprint a version's current content.

    The version's OpenAPI document is rebuilt exactly as lint freshness and the compatibility
    engine rebuild it — classes, properties, paths, security schemes, servers, and metadata — and
    hashed with :func:`app.version_quality_capture.openapi_source_fingerprint`. Anything that
    changes that document changes the fingerprint.

    Args:
        tenant_id: The caller's tenant.
        version: The version row.

    Returns:
        ``"sha256:<hex>"``.
    """
    spec = openapi_for_revision(dict(version), _FINGERPRINT_TENANT_SLUG, tenant_id)
    return openapi_source_fingerprint(spec)


def _canonical_uuid(value: Optional[str]) -> Optional[str]:
    """Return a UUID in its canonical lower-case spelling, or ``None`` when it is not one.

    Args:
        value: The candidate id.

    Returns:
        The canonical spelling, or ``None``.
    """
    text = str(value or "").strip()
    if not is_uuid_string(text):
        return None
    return str(uuid.UUID(text))


def validate_reviewers(
    tenant_id: str, reviewer_ids: Sequence[str], requester_id: Optional[str]
) -> List[str]:
    """Check a reviewer list and return it canonical and de-duplicated.

    Args:
        tenant_id: The tenant whose members may review.
        reviewer_ids: The user ids as the client sent them.
        requester_id: The review's requester, who may not review it; ``None`` when unknown.

    Returns:
        The reviewer ids, canonical, in order of first appearance.

    Raises:
        ReviewValidationError: ``review-invalid-reviewers`` for an empty, over-long, or malformed
            list or one naming a non-member; ``review-self-review`` when it names the requester.
    """
    reviewers: List[str] = []
    malformed: List[str] = []
    for raw in reviewer_ids:
        canonical = _canonical_uuid(raw)
        if canonical is None:
            malformed.append(str(raw))
        elif canonical not in reviewers:
            reviewers.append(canonical)
    if malformed:
        raise ReviewValidationError(
            CODE_INVALID_REVIEWERS, f"reviewers must be user ids (UUIDs); not ids: {', '.join(malformed)}"
        )
    if not reviewers:
        raise ReviewValidationError(CODE_INVALID_REVIEWERS, "a review needs at least one reviewer")
    if len(reviewers) > MAX_REVIEWERS:
        raise ReviewValidationError(
            CODE_INVALID_REVIEWERS, f"a review can ask at most {MAX_REVIEWERS} reviewers"
        )
    requester = _canonical_uuid(requester_id)
    if requester is not None and requester in reviewers:
        raise ReviewValidationError(CODE_SELF_REVIEW, "the requester cannot review their own request")

    members = {
        canonical
        for canonical in (
            _canonical_uuid(row.get("user_id")) for row in db.list_comment_mention_candidates(tenant_id)
        )
        if canonical is not None
    }
    outsiders = [reviewer for reviewer in reviewers if reviewer not in members]
    if outsiders:
        raise ReviewValidationError(
            CODE_INVALID_REVIEWERS, f"not members of this tenant: {', '.join(outsiders)}"
        )
    return reviewers


# ---------------------------------------------------------------------------------------------
# Row mapping and guards
# ---------------------------------------------------------------------------------------------


def _review_record(row: Mapping[str, Any]) -> ReviewRecord:
    """Map a review row onto its record.

    Args:
        row: A row from a review read.

    Returns:
        The record.
    """
    return ReviewRecord(**{name: row.get(name) for name in _REVIEW_FIELDS if row.get(name) is not None})


def _reviewer_record(row: Mapping[str, Any]) -> ReviewerDecisionRecord:
    """Map a reviewer row onto its record.

    Args:
        row: A row from :meth:`app.database.Database.list_review_reviewers`.

    Returns:
        The record.
    """
    return ReviewerDecisionRecord(**{name: row.get(name) for name in _REVIEWER_FIELDS if name in row})


def _review_row(tenant_id: str, project_id: str, review_id: str) -> Dict[str, Any]:
    """Read a review inside a project, or refuse.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.
        review_id: The review.

    Returns:
        The review row.

    Raises:
        ReviewValidationError: ``review-not-found``.
    """
    row = db.get_review(tenant_id=tenant_id, project_id=project_id, review_id=review_id)
    if not row:
        raise ReviewValidationError(CODE_REVIEW_NOT_FOUND, f"no review '{review_id}' in this project")
    return row


def _review_version(tenant_id: str, row: Mapping[str, Any]) -> Dict[str, Any]:
    """Read the version a review is about, or refuse.

    Args:
        tenant_id: The caller's tenant.
        row: The review row.

    Returns:
        The version row.

    Raises:
        ReviewValidationError: ``review-version-not-found`` once the version has been deleted.
    """
    version = db.get_version_by_id(str(row["version_id"]), tenant_id)
    if not version:
        raise ReviewValidationError(CODE_VERSION_NOT_FOUND, "the reviewed version no longer exists")
    return version


def _refuse_closed(row: Mapping[str, Any]) -> None:
    """Refuse a change to a withdrawn review.

    Args:
        row: The review row.

    Raises:
        ReviewValidationError: ``review-closed``.
    """
    if row.get("closed_at"):
        raise ReviewValidationError(
            CODE_CLOSED, "this review was withdrawn; request a new review of the version instead"
        )


def _refuse_published(version: Mapping[str, Any]) -> None:
    """Refuse review work on a published version.

    Args:
        version: The version row.

    Raises:
        ReviewValidationError: ``review-version-published``.
    """
    if version.get("published"):
        raise ReviewValidationError(
            CODE_VERSION_PUBLISHED, "only a draft (unpublished) version can be reviewed"
        )


def _current_round_rows(row: Mapping[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split a review's reviewer rows into its current round and its earlier rounds.

    Args:
        row: The review row.

    Returns:
        ``(current round rows, earlier round rows)``, each in storage order.
    """
    current_round = int(row["round"])
    rows = db.list_review_reviewers(review_id=str(row["id"]))
    current = [item for item in rows if int(item["round"]) == current_round]
    earlier = [item for item in rows if int(item["round"]) < current_round]
    return current, earlier


def _detail(
    tenant_id: str, row: Mapping[str, Any], *, fingerprint: Optional[str] = None
) -> ReviewDetail:
    """Build a review's detail, working out whether its content is stale.

    Args:
        tenant_id: The caller's tenant.
        row: The review row.
        fingerprint: The version's current fingerprint when the caller already computed it, so the
            document is not rebuilt twice in one request.

    Returns:
        The detail. ``spec_changed`` is ``None`` for a withdrawn review or a deleted version.
    """
    current, earlier = _current_round_rows(row)
    spec_changed: Optional[bool] = None
    if not row.get("closed_at"):
        if fingerprint is None:
            version = db.get_version_by_id(str(row["version_id"]), tenant_id)
            fingerprint = spec_fingerprint(tenant_id, version) if version else None
        if fingerprint is not None:
            spec_changed = fingerprint != row["spec_fingerprint"]
    return ReviewDetail(
        review=_review_record(row),
        reviewers=[_reviewer_record(item) for item in current],
        history=[_reviewer_record(item) for item in earlier],
        spec_changed=spec_changed,
    )


def _require_actor(actor_id: str) -> str:
    """Require an attributable acting user.

    Args:
        actor_id: The acting user.

    Returns:
        The canonical user id.

    Raises:
        ReviewValidationError: ``review-forbidden`` when the actor is not a user id.
    """
    actor = _canonical_uuid(actor_id)
    if actor is None:
        raise ReviewValidationError(CODE_FORBIDDEN, "review actions must be attributable to a user")
    return actor


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


def list_reviews(
    tenant_id: str, project_ref: str, filters: ReviewFilters
) -> Tuple[List[ReviewRecord], int]:
    """List a project's reviews, most recently active first.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        filters: What to narrow to.

    Returns:
        The page of records and the total matching the filters.

    Raises:
        ReviewValidationError: For an unknown project or version.
    """
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    version_id = None
    if filters.version:
        version_id = str(resolve_version(tenant_id, project_id, filters.version)["id"])
    scope = {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "version_id": version_id,
        "state": filters.state,
        "open_only": filters.open,
    }
    rows = db.list_reviews(**scope, limit=filters.limit, offset=filters.offset)
    total = db.count_reviews(**scope)
    return [_review_record(row) for row in rows], total


def get_review(tenant_id: str, project_ref: str, review_id: str) -> ReviewDetail:
    """Read a review with its reviewers and decision history.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        review_id: The review.

    Returns:
        The detail.

    Raises:
        ReviewValidationError: For an unknown project or review.
    """
    project = resolve_project(tenant_id, project_ref)
    return _detail(tenant_id, _review_row(tenant_id, str(project["id"]), review_id))


def version_review_status(tenant_id: str, project_ref: str, version_ref: str) -> VersionReviewStatus:
    """Report where a version stands in review: ``draft`` or its open review's state.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.

    Returns:
        The status, with the open review's detail when there is one.

    Raises:
        ReviewValidationError: For an unknown project or version.
    """
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    version = resolve_version(tenant_id, project_id, version_ref)
    version_id = str(version["id"])
    row = db.get_open_review_for_version(tenant_id=tenant_id, project_id=project_id, version_id=version_id)
    return VersionReviewStatus(
        version_id=version_id,
        version_label=version.get("version_id"),
        published=bool(version.get("published")),
        state=version_review_state(row.get("state") if row else None),
        review=_detail(tenant_id, row) if row else None,
    )


# ---------------------------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------------------------


def request_review(
    tenant_id: str, project_ref: str, request: ReviewRequestCreate, actor_id: str
) -> ReviewDetail:
    """Request a review of a draft version: ``draft → in_review``, round 1.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        request: The version and the reviewers to ask.
        actor_id: The requesting user.

    Returns:
        The new review, every reviewer ``pending``.

    Raises:
        ReviewValidationError: For an unknown project or version, a published version, an invalid
            reviewer list, or a version that already has an open review.
    """
    actor = _require_actor(actor_id)
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    version = resolve_version(tenant_id, project_id, request.version)
    version_id = str(version["id"])
    _refuse_published(version)
    reviewers = validate_reviewers(tenant_id, request.reviewers, actor)
    already_open = ReviewValidationError(
        CODE_ALREADY_OPEN, "this version already has an open review; withdraw it or re-request it instead"
    )
    if db.get_open_review_for_version(tenant_id=tenant_id, project_id=project_id, version_id=version_id):
        raise already_open

    fingerprint = spec_fingerprint(tenant_id, version)
    review_id = db.insert_review(
        tenant_id=tenant_id,
        project_id=project_id,
        version_id=version_id,
        requested_by=actor,
        reviewer_ids=reviewers,
        spec_fingerprint=fingerprint,
        notify=notification_store.review_requested_notifier(
            project=project, version=version, actor_id=actor, reviewers=reviewers
        ),
    )
    if not review_id:
        # The partial unique index turned the insert away: another request landed first.
        raise already_open
    return _detail(tenant_id, _review_row(tenant_id, project_id, review_id), fingerprint=fingerprint)


def re_request_review(
    tenant_id: str, project_ref: str, review_id: str, request: ReviewReRequest, actor_id: str
) -> ReviewDetail:
    """Re-request a review after its spec changed: ``* → in_review``, next round.

    The new round gets fresh ``pending`` rows; every earlier row is left exactly as it was.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        review_id: The review.
        request: The reviewers for the new round; ``None`` asks the current round's reviewers
            again (minus any whose account has since been deleted).
        actor_id: The re-requesting user.

    Returns:
        The review in its new round.

    Raises:
        ReviewValidationError: ``review-closed``, ``review-version-published``,
            ``review-spec-unchanged``, reviewer-list codes, ``review-conflict`` when another write
            won the race, and not-found codes.
    """
    actor = _require_actor(actor_id)
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    row = _review_row(tenant_id, project_id, review_id)
    _refuse_closed(row)
    version = _review_version(tenant_id, row)
    _refuse_published(version)
    if not can_re_request(str(row["state"])):
        raise ReviewValidationError(CODE_CONFLICT, f"a review in state '{row['state']}' cannot be re-requested")

    fingerprint = spec_fingerprint(tenant_id, version)
    if fingerprint == row["spec_fingerprint"]:
        raise ReviewValidationError(
            CODE_SPEC_UNCHANGED,
            "the spec has not changed since this round was requested, so its decisions still stand",
        )

    if request.reviewers is not None:
        requested = list(request.reviewers)
    else:
        current, _earlier = _current_round_rows(row)
        requested = [str(item["user_id"]) for item in current if item.get("user_id")]
    reviewers = validate_reviewers(tenant_id, requested, row.get("requested_by"))

    outcome = db.re_request_review(
        tenant_id=tenant_id,
        project_id=project_id,
        review_id=str(row["id"]),
        expected_round=int(row["round"]),
        reviewer_ids=reviewers,
        spec_fingerprint=fingerprint,
        actor_id=actor,
        notify=notification_store.review_requested_notifier(
            project=project, version=version, actor_id=actor, reviewers=reviewers
        ),
    )
    fresh = _review_row(tenant_id, project_id, str(row["id"]))
    if not outcome:
        _refuse_closed(fresh)
        raise ReviewValidationError(
            CODE_CONFLICT, "the review changed while it was being re-requested; read it again and retry"
        )
    return _detail(tenant_id, fresh, fingerprint=fingerprint)


def record_decision(
    tenant_id: str, project_ref: str, review_id: str, request: ReviewDecisionCreate, actor_id: str
) -> ReviewDetail:
    """Record the caller's decision on the current round of a review.

    Any ``request_changes`` moves the review to ``changes_requested`` at once; the last outstanding
    ``approve`` moves it to ``approved``.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        review_id: The review.
        request: The decision and its optional note.
        actor_id: The deciding user.

    Returns:
        The review after the decision.

    Raises:
        ReviewValidationError: ``review-closed``, ``review-version-published``,
            ``review-not-reviewer``, ``review-already-decided``, ``review-not-in-review``,
            ``review-spec-changed``, and not-found codes.
    """
    actor = _require_actor(actor_id)
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    row = _review_row(tenant_id, project_id, review_id)
    _refuse_closed(row)
    version = _review_version(tenant_id, row)
    _refuse_published(version)

    current, _earlier = _current_round_rows(row)
    mine = next((item for item in current if _canonical_uuid(item.get("user_id")) == actor), None)
    if mine is None:
        raise ReviewValidationError(CODE_NOT_REVIEWER, "only a reviewer of the current round can decide")
    already_decided = ReviewValidationError(
        CODE_ALREADY_DECIDED, "you already decided in this round; decisions are immutable"
    )
    if mine.get("decision") != DECISION_PENDING:
        raise already_decided
    not_in_review = ReviewValidationError(
        CODE_NOT_IN_REVIEW, "this round is already decided; the review must be re-requested first"
    )
    if not can_record_decision(str(row["state"])):
        raise not_in_review

    fingerprint = spec_fingerprint(tenant_id, version)
    if fingerprint != row["spec_fingerprint"]:
        raise ReviewValidationError(
            CODE_SPEC_CHANGED,
            "the spec changed since this round was requested; re-request the review before deciding",
        )

    note = request.note if request.note and request.note.strip() else None
    outcome = db.record_review_decision(
        tenant_id=tenant_id,
        project_id=project_id,
        review_id=str(row["id"]),
        expected_round=int(row["round"]),
        user_id=actor,
        decision=request.decision,
        note=note,
        notify=notification_store.review_decision_notifier(
            project=project, version=version, actor_id=actor, requested_by=row.get("requested_by")
        ),
    )
    fresh = _review_row(tenant_id, project_id, str(row["id"]))
    if not outcome:
        _refuse_closed(fresh)
        if int(fresh["round"]) != int(row["round"]) or fresh["state"] != STATE_IN_REVIEW:
            raise not_in_review
        raise already_decided
    return _detail(tenant_id, fresh, fingerprint=fingerprint)


def withdraw_review(tenant_id: str, project_ref: str, review_id: str, actor_id: str) -> ReviewDetail:
    """Withdraw an open review, closing it. Its state and decisions stay as they were.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        review_id: The review.
        actor_id: The withdrawing user.

    Returns:
        The closed review.

    Raises:
        ReviewValidationError: ``review-forbidden`` unless the actor requested the review or is a
            tenant administrator; ``review-closed``; not-found codes.
    """
    actor = _require_actor(actor_id)
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    row = _review_row(tenant_id, project_id, review_id)
    _refuse_closed(row)
    if not comment_store.can_moderate(tenant_id, actor, row.get("requested_by")):
        raise ReviewValidationError(
            CODE_FORBIDDEN, "only the member who requested a review or a tenant administrator can withdraw it"
        )
    withdrawn = db.withdraw_review(
        tenant_id=tenant_id, project_id=project_id, review_id=str(row["id"]), actor_id=actor
    )
    fresh = _review_row(tenant_id, project_id, str(row["id"]))
    if not withdrawn:
        _refuse_closed(fresh)
        raise ReviewValidationError(CODE_CONFLICT, "the review changed while it was being withdrawn")
    return _detail(tenant_id, fresh)
