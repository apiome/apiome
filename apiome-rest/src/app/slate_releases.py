"""Slate release lifecycle rules — APX-3.1 (private-suite#2456).

The decisions that must hold before routing changes, kept in one pure module so they can be
tested exhaustively without a database, and so the REST layer cannot accidentally implement
a second, subtly different copy of them.

The refusal vocabulary here matches ``designer/lib/authoring/release-actions.ts`` (UXE-2.4)
deliberately. The Release Center already renders one sentence per refusal reason and makes
``disabledReason`` the only way to disable a control; if the backend invented its own codes
the UI would fall back to a generic error and the operator would get a greyed-out dead end
instead of a sentence explaining what to do.

Three rules are worth stating outright, because they are the ones that would be easy to get
subtly wrong and expensive to discover in production:

1. **Promotion never rebuilds** (criterion 3). :func:`plan_promotion` requires an artifact
   that already exists and carries ``rebuilds=False`` as a literal, so the guarantee is
   inspectable and tested rather than documented and hoped for. A release with no artifact
   is refused with a reason that says exactly that.

2. **A stale approval blocks promotion but never a rollback.** Requiring fresh sign-off to
   *stop* serving a bad release would make the approval policy an outage amplifier. This
   asymmetry is intentional and mirrors the UI's.

3. **Absence of evidence is not evidence of a clean activation.** A lane where no region has
   reported is ``partial``, not ``complete`` — see :func:`evaluate_region_rollout`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence

__all__ = [
    "PROMOTABLE_STATUSES",
    "ROLLBACK_SOURCE_STATUSES",
    "ActivationPlan",
    "RegionRollout",
    "ReleaseRefusal",
    "SlateReleaseRefusedError",
    "evaluate_region_rollout",
    "is_approval_stale",
    "measure_activation_slo",
    "plan_promotion",
    "plan_rollback",
    "select_reapable_artifacts",
]

# A release may be routed to only from these states. `queued`/`building` have no artifact
# yet; `failed` produced none; `active` is already serving; `superseded`/`rolled-back` are
# reachable only through rollback, which has its own gate.
PROMOTABLE_STATUSES = frozenset({"ready", "review"})

# States a rollback target may be in. A rollback goes back to something that once served.
ROLLBACK_SOURCE_STATUSES = frozenset({"superseded", "rolled-back"})

#: Every reason routing can be refused. Mirrors the UI's `AuthoringReleaseRefusalReason`.
RefusalReason = Literal[
    "not-built",
    "not-promotable",
    "already-active",
    "nothing-active",
    "no-rollback-target",
    "stale-approval",
    "approval-required",
    "artifact-reaped",
    "signature-invalid",
    "partial-region",
    "concurrent-activation",
]

# One operator-facing sentence per refusal. The REST layer returns these verbatim so the
# reason a control is disabled reaches the operator as words rather than as a code.
_REFUSAL_SENTENCES: Dict[str, str] = {
    "not-built": (
        "This release has no artifact, so there is nothing to route to. Promotion changes "
        "routing to already-built bytes; it never starts a build."
    ),
    "not-promotable": (
        "This release is not in a promotable state. Only a release that finished building "
        "and passed its checks can be routed to."
    ),
    "already-active": "This release is already serving this environment.",
    "nothing-active": (
        "This environment is not serving a release, so there is nothing to roll back from."
    ),
    "no-rollback-target": (
        "No retained release is available to roll back to. Earlier artifacts fell outside "
        "the site's retention window and their bytes are no longer stored."
    ),
    "stale-approval": (
        "The approval on this release was given for different bytes than it now carries, so "
        "it no longer approves what would be promoted. Re-approve the current artifact."
    ),
    "approval-required": (
        "This environment requires an approval before routing can change, and this release "
        "has none."
    ),
    "artifact-reaped": (
        "This release's artifact has been reaped by retention, so its bytes are no longer "
        "stored and it cannot be served again."
    ),
    "signature-invalid": (
        "This artifact's signature does not verify against its digests, so it is refused "
        "activation. The stored bytes do not match what the build signed."
    ),
    "partial-region": (
        "The previous activation on this environment has not reached every region yet. "
        "Changing routing again now would leave regions serving three different releases."
    ),
    "concurrent-activation": (
        "Another activation changed this environment's routing while this one was being "
        "prepared. Re-read the environment and try again."
    ),
}


@dataclass(frozen=True)
class ReleaseRefusal:
    """A named, explained refusal to change routing."""

    reason: str
    sentence: str

    @staticmethod
    def of(reason: str) -> "ReleaseRefusal":
        """Build a refusal from its reason code.

        Args:
            reason: One of :data:`RefusalReason`.

        Returns:
            The refusal with its operator-facing sentence attached.
        """
        return ReleaseRefusal(
            reason=reason,
            sentence=_REFUSAL_SENTENCES.get(
                reason, "Routing cannot change for this release."
            ),
        )


class SlateReleaseRefusedError(Exception):
    """Routing was refused. Carries the named reason and its sentence.

    Raising rather than returning is deliberate for the REST layer: a refused promotion
    must never fall through to an activation attempt.
    """

    def __init__(self, refusal: ReleaseRefusal):
        self.refusal = refusal
        self.code = refusal.reason
        super().__init__(refusal.sentence)


@dataclass(frozen=True)
class ActivationPlan:
    """What an activation would do, decided before anything is written.

    ``rebuilds`` is a literal ``False`` rather than a computed value. Criterion 3 is that
    promotion never rebuilds, and a plan that could in principle report ``True`` would mean
    the code path exists.
    """

    action: Literal["promotion", "rollback"]
    environment_id: str
    release_id: str
    artifact_digest: str
    replaces_release_id: Optional[str]
    #: Routing token the activation must assert. Reading it into the plan is what makes the
    #: concurrency check refer to the state the decision was made against.
    expected_routing_version: int
    rebuilds: bool = False
    invalidated_pages: int = 0

    def as_dict(self) -> Dict[str, Any]:
        """Return the plan as a wire-ready mapping.

        Returns:
            A JSON-serializable dict describing the planned activation.
        """
        return {
            "action": self.action,
            "environmentId": self.environment_id,
            "releaseId": self.release_id,
            "artifactDigest": self.artifact_digest,
            "replacesReleaseId": self.replaces_release_id,
            "expectedRoutingVersion": self.expected_routing_version,
            "rebuilds": self.rebuilds,
            "invalidatedPages": self.invalidated_pages,
        }


@dataclass(frozen=True)
class RegionRollout:
    """Aggregate view of how far an activation has reached across regions."""

    state: Literal["complete", "partial", "failed", "pending"]
    total: int
    active: int
    activating: int
    failed: int
    #: Regions that have not reached the release, named so an operator can act on them.
    outstanding: Sequence[str] = field(default_factory=tuple)


def is_approval_stale(approval_digest: Optional[str], artifact_digest: Optional[str]) -> bool:
    """Report whether an approval covers bytes other than the ones that would be promoted.

    Approving a build and then promoting different bytes is a supply-chain failure, not a
    UI inconvenience, so a missing approval digest counts as stale rather than as a pass.

    Args:
        approval_digest: Digest recorded on the approval.
        artifact_digest: Digest the release currently carries.

    Returns:
        True when the approval does not cover the current artifact.
    """
    if not approval_digest or not artifact_digest:
        return True
    return approval_digest != artifact_digest


def evaluate_region_rollout(regions: Sequence[Mapping[str, Any]]) -> RegionRollout:
    """Summarize per-region activation state.

    A rollout with no region reports at all is ``pending``, and one where any region is
    still activating or has failed is ``partial`` or ``failed`` — never ``complete``.
    Reporting an unreported rollout as finished is precisely the lie the Release Center
    exists to prevent: absence of evidence is not evidence of a clean activation.

    Args:
        regions: Region records, each with a ``status`` of ``active``/``activating``/
            ``failed`` and a ``label`` or ``region_id``.

    Returns:
        The aggregated :class:`RegionRollout`.
    """
    if not regions:
        return RegionRollout(state="pending", total=0, active=0, activating=0, failed=0)

    active = [r for r in regions if r.get("status") == "active"]
    activating = [r for r in regions if r.get("status") == "activating"]
    failed = [r for r in regions if r.get("status") == "failed"]
    outstanding = tuple(
        str(r.get("label") or r.get("region_id") or r.get("regionId") or "unknown")
        for r in (*activating, *failed)
    )

    if failed:
        state: Literal["complete", "partial", "failed", "pending"] = "failed"
    elif activating:
        state = "partial"
    else:
        state = "complete"

    return RegionRollout(
        state=state,
        total=len(regions),
        active=len(active),
        activating=len(activating),
        failed=len(failed),
        outstanding=outstanding,
    )


def measure_activation_slo(
    *,
    started_at: Optional[datetime],
    completed_at: Optional[datetime],
    budget_seconds: int,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Measure an activation against its SLO budget.

    Reports a breach *while it is still happening* rather than only once it is over: an
    activation that started twelve minutes ago against a five-minute budget and has not
    completed is already breaching, and an operator needs to know that now, not after it
    eventually finishes.

    Args:
        started_at: When activation began. None when it has not started.
        completed_at: When every region finished. None while still rolling out.
        budget_seconds: The site's activation SLO budget.
        now: Current time, injectable for tests. Defaults to UTC now.

    Returns:
        A mapping with ``state`` (``not-started``/``within``/``breaching``/``breached``),
        ``elapsedSeconds``, ``budgetSeconds`` and ``inProgress``.
    """
    if started_at is None:
        return {
            "state": "not-started",
            "elapsedSeconds": None,
            "budgetSeconds": budget_seconds,
            "inProgress": False,
        }

    reference = completed_at or (now or datetime.now(timezone.utc))
    elapsed = max(0.0, (reference - started_at).total_seconds())
    breached = elapsed > budget_seconds
    in_progress = completed_at is None

    if breached:
        state = "breaching" if in_progress else "breached"
    else:
        state = "within"

    return {
        "state": state,
        "elapsedSeconds": elapsed,
        "budgetSeconds": budget_seconds,
        "inProgress": in_progress,
    }


def _artifact_guard(release: Mapping[str, Any]) -> Optional[ReleaseRefusal]:
    """Refuse a release whose bytes are missing, reaped or unverified.

    Args:
        release: The release record, including artifact fields.

    Returns:
        The refusal, or None when the artifact is routable.
    """
    digest = release.get("artifact_digest")
    if not digest:
        return ReleaseRefusal.of("not-built")
    if release.get("artifact_reaped_at") is not None:
        return ReleaseRefusal.of("artifact-reaped")
    if release.get("signature_verified") is False:
        return ReleaseRefusal.of("signature-invalid")
    return None


def plan_promotion(
    *,
    release: Mapping[str, Any],
    environment: Mapping[str, Any],
    approvals: Sequence[Mapping[str, Any]] = (),
    active_regions: Sequence[Mapping[str, Any]] = (),
    require_approval: bool = False,
) -> ActivationPlan:
    """Decide whether a release may be promoted, and to what.

    Every gate is checked before anything is written, so a refused promotion leaves no
    trace beyond the audit entry the caller records.

    Args:
        release: The release to route to, with ``id``, ``status``, ``artifact_digest``,
            ``artifact_reaped_at``, ``signature_verified`` and ``page_count``.
        environment: The target lane, with ``id``, ``active_release_id`` and
            ``routing_version``.
        approvals: Approvals recorded against the release.
        active_regions: Region records for the currently active release, used to refuse a
            promotion on top of a rollout that has not finished.
        require_approval: Whether this lane's policy demands an approval.

    Returns:
        The :class:`ActivationPlan` describing the routing change.

    Raises:
        SlateReleaseRefusedError: With a named reason when any gate refuses.
    """
    if environment.get("active_release_id") == release.get("id"):
        raise SlateReleaseRefusedError(ReleaseRefusal.of("already-active"))

    artifact_refusal = _artifact_guard(release)
    if artifact_refusal is not None:
        raise SlateReleaseRefusedError(artifact_refusal)

    if release.get("status") not in PROMOTABLE_STATUSES:
        raise SlateReleaseRefusedError(ReleaseRefusal.of("not-promotable"))

    # Promoting on top of an unfinished rollout would leave regions serving three different
    # releases, which no rollback can then cleanly undo.
    if environment.get("active_release_id") is not None:
        rollout = evaluate_region_rollout(active_regions)
        if rollout.state in {"partial", "failed"}:
            raise SlateReleaseRefusedError(ReleaseRefusal.of("partial-region"))

    if require_approval:
        if not approvals:
            raise SlateReleaseRefusedError(ReleaseRefusal.of("approval-required"))
        fresh = [
            approval
            for approval in approvals
            if not is_approval_stale(approval.get("digest"), release.get("artifact_digest"))
        ]
        if not fresh:
            raise SlateReleaseRefusedError(ReleaseRefusal.of("stale-approval"))

    return ActivationPlan(
        action="promotion",
        environment_id=str(environment["id"]),
        release_id=str(release["id"]),
        artifact_digest=str(release["artifact_digest"]),
        replaces_release_id=(
            str(environment["active_release_id"])
            if environment.get("active_release_id")
            else None
        ),
        expected_routing_version=int(environment.get("routing_version", 0)),
        invalidated_pages=int(release.get("page_count") or 0),
    )


def plan_rollback(
    *,
    environment: Mapping[str, Any],
    target: Optional[Mapping[str, Any]],
) -> ActivationPlan:
    """Decide whether a lane may be rolled back, and to what.

    Deliberately does *not* consult approval freshness. Requiring fresh sign-off to stop
    serving a bad release would make the approval policy an outage amplifier — the same
    asymmetry the Release Center implements.

    Args:
        environment: The lane, with ``id``, ``active_release_id`` and ``routing_version``.
        target: The retained release to roll back to, or None when none is available.

    Returns:
        The :class:`ActivationPlan` describing the rollback.

    Raises:
        SlateReleaseRefusedError: When the lane serves nothing, no retained target exists,
            or the target's bytes are gone.
    """
    if not environment.get("active_release_id"):
        raise SlateReleaseRefusedError(ReleaseRefusal.of("nothing-active"))
    if target is None:
        raise SlateReleaseRefusedError(ReleaseRefusal.of("no-rollback-target"))

    artifact_refusal = _artifact_guard(target)
    if artifact_refusal is not None:
        # A target with no stored bytes is a missing rollback target, not a failed build:
        # say so in the words that describe the operator's actual situation.
        raise SlateReleaseRefusedError(
            ReleaseRefusal.of(
                "no-rollback-target"
                if artifact_refusal.reason in {"not-built", "artifact-reaped"}
                else artifact_refusal.reason
            )
        )

    return ActivationPlan(
        action="rollback",
        environment_id=str(environment["id"]),
        release_id=str(target["id"]),
        artifact_digest=str(target["artifact_digest"]),
        replaces_release_id=str(environment["active_release_id"]),
        expected_routing_version=int(environment.get("routing_version", 0)),
        invalidated_pages=int(target.get("page_count") or 0),
    )


def select_reapable_artifacts(
    releases: Sequence[Mapping[str, Any]],
    *,
    retained_releases: int,
    active_release_id: Optional[str] = None,
) -> List[str]:
    """Choose which artifacts retention may reap for one environment.

    Retention and rollback capability are the same setting: an artifact that is reaped is no
    longer a rollback target, so this is deliberately conservative.

    * The active release is never reaped, whatever the count says.
    * Only releases that once served (``superseded``/``rolled-back``) are candidates —
      reaping a release that is still awaiting approval would destroy work in progress.
    * The newest ``retained_releases`` candidates are kept, so the rollback window is the
      most recent history rather than an arbitrary slice.

    Args:
        releases: Releases for one environment, newest first, each with ``id``, ``status``
            and ``artifact_reaped_at``.
        retained_releases: How many superseded releases keep their bytes.
        active_release_id: The release currently serving, which is always exempt.

    Returns:
        Ids of releases whose artifacts may be reaped, oldest first.
    """
    candidates = [
        release
        for release in releases
        if release.get("status") in ROLLBACK_SOURCE_STATUSES
        and str(release.get("id")) != str(active_release_id)
        and release.get("artifact_reaped_at") is None
    ]
    # `releases` arrives newest first; everything past the retention count is reapable.
    reapable = candidates[retained_releases:]
    return [str(release["id"]) for release in reversed(reapable)]
