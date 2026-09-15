"""Approval gate — review outcomes made binding at publish time (COL-2.3, #4519).

COL-2.1 (#4517) made review decisions *recordable*; this module makes them *consequential*.
It answers one question about a draft version:

    Has this version collected the approvals its tenant's policy requires?

The policy (:mod:`app.approval_policy`) is two style-guide settings resolved through the
GOV-1.4 chain (project assignment → tenant assignment → tenant default): how many approvals a
draft needs, and — optionally — a role slug at least one of those approvals must come from.
``required_approvals = 0`` is the default and means no gate, so a tenant that never opts in
publishes exactly as it did before.

How it decides
--------------
Only the **open** review of the version counts, and only its **current round**:

* **No open review** — nothing has approved this version. Blocked.
* **Changes requested** — a reviewer of the current round said no. Blocked, whatever the
  count says, because "2 approvals and a rejection" is not an approved version.
* **Stale approvals** — the version's content no longer matches the fingerprint the round was
  requested against (COL-2.1's ``spec_changed``). The approvals were given to a different
  document, so they do not count; the review must be re-requested. Blocked.
* **Too few approvals** — fewer current-round ``approve`` decisions than the policy requires.
  Blocked.
* **Nobody with the required role** — the count is met, but no approver holds
  ``required_reviewer_role``. Blocked. A reviewer's role is their *effective* RBAC slug
  (:meth:`app.database.Database.get_effective_role_slug`), resolved exactly as permissions
  are, so a tenant administrator resolves to ``owner``.

Anything else is satisfied, and the publish proceeds.

The escape
----------
Blocking is a 422 from the publish prechecks, and the only way past it is the GOV-2.5
force-publish (``skipPublishChecks`` + ``forcePublishReason``), which is recorded in the
workflow audit trail by :mod:`app.versions_routes`. The escape is kept on purpose: an
approval policy that cannot be overridden during an incident is a policy teams route around.

Everything here is **best-effort**: a fault anywhere — an unreadable review, a spec that will
not rebuild, a DB error — degrades to :data:`STATUS_UNAVAILABLE`, which never blocks a
publish, and is audited so the degradation is visible rather than silent. This matches the
CTG-3.4 guardrail: a gate that fails closed on its own bugs stops more releases than the
policy it enforces.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from .approval_policy import (
    DEFAULT_REQUIRED_APPROVALS,
    normalize_required_approvals,
    normalize_required_reviewer_role,
)
from .database import db
from .review_lifecycle import DECISION_APPROVE, DECISION_REQUEST_CHANGES

logger = logging.getLogger(__name__)

__all__ = [
    "ApprovalGateAssessment",
    "ApprovalPolicy",
    "MAX_LISTED_APPROVERS",
    "REASON_CHANGES_REQUESTED",
    "REASON_INSUFFICIENT_APPROVALS",
    "REASON_MISSING_REQUIRED_ROLE",
    "REASON_NO_REVIEW",
    "REASON_SPEC_CHANGED",
    "STATUS_BLOCKED",
    "STATUS_DISABLED",
    "STATUS_SATISFIED",
    "STATUS_UNAVAILABLE",
    "assess_approval_gate",
    "resolve_approval_policy",
]

#: The tenant requires no approvals — the gate never surfaces.
STATUS_DISABLED = "disabled"
#: The policy is armed and the version meets it.
STATUS_SATISFIED = "satisfied"
#: The policy is armed and the version does not meet it — publish refused unless forced.
STATUS_BLOCKED = "blocked"
#: The gate could not be evaluated; never blocks.
STATUS_UNAVAILABLE = "unavailable"

#: The version has no open review, so nothing has approved it.
REASON_NO_REVIEW = "no-review"
#: A reviewer of the current round requested changes.
REASON_CHANGES_REQUESTED = "changes-requested"
#: The content changed since the round was requested; its approvals are stale.
REASON_SPEC_CHANGED = "spec-changed"
#: Fewer current-round approvals than the policy requires.
REASON_INSUFFICIENT_APPROVALS = "insufficient-approvals"
#: Enough approvals, but none from a holder of the required role.
REASON_MISSING_REQUIRED_ROLE = "missing-required-role"

#: Cap on the approvers carried in a payload. ``approvals`` always reports the true total; the
#: list exists so a dialog and an audit row can name who signed off, not to page a round.
MAX_LISTED_APPROVERS = 20


@dataclass(frozen=True)
class ApprovalPolicy:
    """The resolved approval settings of the guide governing a project.

    Attributes:
        required_approvals: Approvals the current review round must carry, ``0`` for no gate.
        required_reviewer_role: Role slug at least one approval must come from, or ``None``.
    """

    required_approvals: int = DEFAULT_REQUIRED_APPROVALS
    required_reviewer_role: Optional[str] = None

    @property
    def active(self) -> bool:
        """Whether the policy gates anything.

        A required role alone never gates a publish: "no approvals, one of them from a release
        manager" is not a policy a version can satisfy.
        """
        return self.required_approvals >= 1

    def as_payload(self) -> Dict[str, Any]:
        """Serialize to the camelCase shape the 422 body and audit rows share."""
        return {
            "requiredApprovals": self.required_approvals,
            "requiredReviewerRole": self.required_reviewer_role,
        }


@dataclass(frozen=True)
class ApprovalGateAssessment:
    """The gate's verdict on one candidate publish.

    Attributes:
        policy: The resolved policy the verdict was reached under.
        status: One of the ``STATUS_*`` constants.
        reason: The ``REASON_*`` code when blocked, otherwise ``None``.
        review_id: The open review that was judged, when there is one.
        review_state: That review's state (``in_review`` / ``approved`` /
            ``changes_requested``).
        round: The round whose decisions were counted.
        spec_changed: Whether the version's content has moved since the round was requested;
            ``None`` when it could not be determined.
        approvals: Current-round ``approve`` decisions.
        changes_requested: Current-round ``request_changes`` decisions.
        pending: Current-round reviewers who have not decided.
        role_approvals: Approvals from a holder of ``required_reviewer_role``; ``0`` when no
            role is required.
        approvers: Up to :data:`MAX_LISTED_APPROVERS` entries, each
            ``{userId, userName, roleSlug}``, in the order the round lists them.
        detail: Free-text explanation for ``unavailable`` outcomes.
    """

    policy: ApprovalPolicy = field(default_factory=ApprovalPolicy)
    status: str = STATUS_UNAVAILABLE
    reason: Optional[str] = None
    review_id: Optional[str] = None
    review_state: Optional[str] = None
    round: Optional[int] = None
    spec_changed: Optional[bool] = None
    approvals: int = 0
    changes_requested: int = 0
    pending: int = 0
    role_approvals: int = 0
    approvers: Tuple[Dict[str, Optional[str]], ...] = ()
    detail: Optional[str] = None

    @property
    def blocked(self) -> bool:
        """Whether publish must be refused unless force-published."""
        return self.status == STATUS_BLOCKED

    @property
    def evaluated(self) -> bool:
        """Whether the policy was armed and actually judged — the auditable cases."""
        return self.status in (STATUS_SATISFIED, STATUS_BLOCKED, STATUS_UNAVAILABLE)

    def message(self) -> str:
        """Human-readable one-liner for dialogs, API errors, and audit rows."""
        required = self.policy.required_approvals
        role = self.policy.required_reviewer_role
        if self.status == STATUS_DISABLED:
            return "No approval policy applies to this project."
        if self.status == STATUS_UNAVAILABLE:
            return (
                "The approval policy could not be evaluated for this version; publish was "
                "allowed to proceed."
            )
        if self.status == STATUS_SATISFIED:
            return f"{self.approvals} of {required} required approval(s) recorded."
        if self.reason == REASON_NO_REVIEW:
            return (
                f"This version has no open review, and {required} approval(s) are required "
                "before it can be published."
            )
        if self.reason == REASON_CHANGES_REQUESTED:
            return (
                f"{self.changes_requested} reviewer(s) requested changes on this version. "
                "Address the feedback and re-request the review."
            )
        if self.reason == REASON_SPEC_CHANGED:
            return (
                "This version changed after its review round was requested, so its "
                f"{self.approvals} approval(s) no longer apply. Re-request the review."
            )
        if self.reason == REASON_MISSING_REQUIRED_ROLE:
            return (
                f"None of the {self.approvals} approval(s) came from a reviewer with the "
                f"'{role}' role, which this project's approval policy requires."
            )
        return (
            f"{self.approvals} of {required} required approval(s) recorded on this version."
        )

    def as_payload(self) -> Dict[str, Any]:
        """Serialize to the camelCase shape the 422 body and audit rows share."""
        return {
            "policy": self.policy.as_payload(),
            "status": self.status,
            "blocked": self.blocked,
            "reason": self.reason,
            "reviewId": self.review_id,
            "reviewState": self.review_state,
            "round": self.round,
            "specChanged": self.spec_changed,
            "approvals": self.approvals,
            "requiredApprovals": self.policy.required_approvals,
            "requiredReviewerRole": self.policy.required_reviewer_role,
            "roleApprovals": self.role_approvals,
            "changesRequested": self.changes_requested,
            "pending": self.pending,
            "approvers": [dict(approver) for approver in self.approvers],
            "detail": self.detail,
            "message": self.message(),
        }


def resolve_approval_policy(
    tenant_id: str, project_id: Optional[str] = None
) -> ApprovalPolicy:
    """Resolve the approval policy from the assigned style guide (GOV-1.4 chain).

    Args:
        tenant_id: The tenant whose guide chain applies.
        project_id: The owning project, enabling a project-level guide to override.

    Returns:
        The :class:`ApprovalPolicy`. Any fault — no guide, DB error, unusable value — yields
        the inactive default, so the gate can never arm itself because a lookup misbehaved.
    """
    try:
        guide = db.get_assigned_style_guide(tenant_id, project_id)
        if not isinstance(guide, dict):
            return ApprovalPolicy()
        return ApprovalPolicy(
            required_approvals=normalize_required_approvals(guide.get("required_approvals")),
            required_reviewer_role=normalize_required_reviewer_role(
                guide.get("required_reviewer_role")
            ),
        )
    except Exception:  # noqa: BLE001 - policy resolution must never break a publish
        logger.warning(
            "Approval policy resolution failed for tenant %s (project %s); the gate stays off",
            tenant_id,
            project_id,
            exc_info=True,
        )
        return ApprovalPolicy()


def _current_round_decisions(
    review: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """The reviewer rows of a review's current round.

    Args:
        review: The open review row.

    Returns:
        Its current-round rows, in storage order.
    """
    current_round = int(review.get("round") or 1)
    rows = db.list_review_reviewers(review_id=str(review.get("id") or "")) or []
    return [row for row in rows if int(row.get("round") or 0) == current_round]


def _approver_entries(
    tenant_id: str, rows: List[Dict[str, Any]], required_role: Optional[str]
) -> Tuple[Tuple[Dict[str, Optional[str]], ...], int]:
    """Describe the round's approvers and count those holding the required role.

    Args:
        tenant_id: The tenant the roles are resolved within.
        rows: The current round's reviewer rows.
        required_role: The role slug the policy requires, or ``None``.

    Returns:
        ``(listed approvers, role approval count)``. The role of each approver is resolved
        only when a role is required, so the common policy costs no extra queries.
    """
    approvers: List[Dict[str, Optional[str]]] = []
    role_approvals = 0
    for row in rows:
        if str(row.get("decision") or "") != DECISION_APPROVE:
            continue
        user_id = str(row.get("user_id") or "") or None
        role_slug: Optional[str] = None
        if required_role and user_id:
            role_slug = normalize_required_reviewer_role(
                db.get_effective_role_slug(tenant_id, user_id)
            )
            if role_slug == required_role:
                role_approvals += 1
        if len(approvers) < MAX_LISTED_APPROVERS:
            approvers.append(
                {
                    "userId": user_id,
                    "userName": row.get("user_name"),
                    "roleSlug": role_slug,
                }
            )
    return tuple(approvers), role_approvals


def assess_approval_gate(
    *,
    tenant_id: str,
    project_id: str,
    version: Mapping[str, Any],
    policy: Optional[ApprovalPolicy] = None,
    fingerprint_loader: Optional[Callable[[str, Mapping[str, Any]], str]] = None,
) -> ApprovalGateAssessment:
    """Assess a candidate publish against the approval policy. Never raises.

    Args:
        tenant_id: Tenant context.
        project_id: Project owning the revision.
        version: The candidate revision row (needs ``id``).
        policy: Pre-resolved policy; resolved from the guide chain when omitted.
        fingerprint_loader: Injection point for fingerprinting the version's content;
            defaults to :func:`app.review_store.spec_fingerprint`.

    Returns:
        The :class:`ApprovalGateAssessment`. Faults come back as :data:`STATUS_UNAVAILABLE`
        with ``detail`` set, never as an exception.
    """
    resolved = policy if policy is not None else resolve_approval_policy(tenant_id, project_id)
    if not resolved.active:
        return ApprovalGateAssessment(policy=resolved, status=STATUS_DISABLED)

    version_id = str(version.get("id") or "")

    try:
        review = db.get_open_review_for_version(
            tenant_id=tenant_id, project_id=project_id, version_id=version_id
        )
        if not isinstance(review, dict) or not review:
            return ApprovalGateAssessment(
                policy=resolved, status=STATUS_BLOCKED, reason=REASON_NO_REVIEW
            )

        rows = _current_round_decisions(review)
        approvals = sum(
            1 for row in rows if str(row.get("decision") or "") == DECISION_APPROVE
        )
        changes_requested = sum(
            1 for row in rows if str(row.get("decision") or "") == DECISION_REQUEST_CHANGES
        )
        pending = len(rows) - approvals - changes_requested
        approvers, role_approvals = _approver_entries(
            tenant_id, rows, resolved.required_reviewer_role
        )

        # Stale approvals are not approvals: COL-2.1 records the fingerprint of the document
        # each round judged, precisely so this gate can tell "approved" from "approved
        # something else". The document is rebuilt here rather than reusing the one the
        # publish prechecks already built: the recorded fingerprint was taken under
        # `review_store`'s own constant tenant slug, and a fingerprint compared against a
        # differently-built document would read every publish as stale.
        loader = fingerprint_loader
        if loader is None:
            from .review_store import spec_fingerprint  # Lazy: keeps the import graph flat.

            loader = spec_fingerprint
        spec_changed = loader(tenant_id, version) != str(review.get("spec_fingerprint") or "")
    except Exception as exc:  # noqa: BLE001 - a broken gate must not break publishing
        logger.warning(
            "Approval gate could not be evaluated for revision %s; continuing without it",
            version_id,
            exc_info=True,
        )
        return ApprovalGateAssessment(
            policy=resolved, status=STATUS_UNAVAILABLE, detail=str(exc)
        )

    observed = ApprovalGateAssessment(
        policy=resolved,
        status=STATUS_SATISFIED,
        review_id=str(review.get("id") or "") or None,
        review_state=str(review.get("state") or "") or None,
        round=int(review.get("round") or 1),
        spec_changed=spec_changed,
        approvals=approvals,
        changes_requested=changes_requested,
        pending=pending,
        role_approvals=role_approvals,
        approvers=approvers,
    )

    reason = _refusal_reason(observed)
    if reason is None:
        return observed
    return replace(observed, status=STATUS_BLOCKED, reason=reason)


def _refusal_reason(observed: ApprovalGateAssessment) -> Optional[str]:
    """The first rule the observed round fails, or ``None`` when it satisfies the policy.

    The order is the order a reviewer would explain it in: a rejection outranks a shortfall,
    and a stale round outranks both, because re-requesting it is the only way forward.

    Args:
        observed: The tallied round, carrying the policy it is judged against.

    Returns:
        A ``REASON_*`` code, or ``None``.
    """
    if observed.changes_requested > 0:
        return REASON_CHANGES_REQUESTED
    if observed.spec_changed:
        return REASON_SPEC_CHANGED
    if observed.approvals < observed.policy.required_approvals:
        return REASON_INSUFFICIENT_APPROVALS
    if observed.policy.required_reviewer_role and observed.role_approvals < 1:
        return REASON_MISSING_REQUIRED_ROLE
    return None
