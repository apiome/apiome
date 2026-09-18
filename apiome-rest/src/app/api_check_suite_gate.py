"""The API change check suite as a publish gate — GNC-3.1 (#4740).

A tenant can make the suite **required before publish** (``requiredForPublish`` on the suite
policy). This module answers the one question the publish prechecks then ask:

    Has the suite passed for *exactly this content*, under *exactly the policy in force*?

"Exactly" is load-bearing. An evaluation is matched to the draft by its content digest — the same
document fingerprint the suite recorded — and to the policy by both fingerprints it was judged
under: the suite's component requirements and the deploy gate's thresholds. (Not the whole suite
policy: ``requiredForPublish`` cannot change a verdict, so arming the gate does not stale every
evaluation already made.) An evaluation of an earlier edit, or one judged under requirements that
have since moved, answers for something else, and a gate that accepted it would pass a document
nobody checked. This is the provider-side "required status check" made
symmetric: whether a change starts in a pull request or in the designer, it meets the same gate,
backed by the same evidence.

How it decides
--------------
Only **evaluated** runs count — a placeholder (the branch is ahead of the draft) judged nothing. The
newest one matching the draft digest and both fingerprints decides:

* ``pass`` or ``skipped`` — **satisfied**. A skipped suite means none of the required components
  applied to this change; refusing it would be a gate no author could ever satisfy.
* ``fail`` — **blocked** (``check-suite-failed``).
* ``pending`` — **blocked** (``check-suite-pending``): a required component has no verdict yet.
* No match, though the version was evaluated before — **blocked** (``check-suite-stale``).
* Never evaluated — **blocked** (``check-suite-not-evaluated``).

The escape is the GOV-2.5 force-publish (``skipPublishChecks`` + reason), audited like every other
gate's. Everything here is **best-effort**: a fault degrades to ``unavailable``, which never blocks
and is audited — the COL-2.3 / CTG-3.4 rule that a gate failing closed on its own bugs stops more
releases than the policy it enforces.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from .api_check_suite import CheckSuitePolicyOut, requirements_fingerprint
from .api_check_suite_policy_store import load_policy
from .database import db
from .deploy_gate import DeployGatePolicyOut
from .deploy_gate_store import load_policy as load_thresholds
from .provider_checks import STATE_FAIL, STATE_PASS, STATE_PENDING, STATE_SKIPPED

logger = logging.getLogger(__name__)

__all__ = [
    "CheckSuiteGateAssessment",
    "REASON_FAILED",
    "REASON_NOT_EVALUATED",
    "REASON_PENDING",
    "REASON_STALE",
    "STATUS_BLOCKED",
    "STATUS_DISABLED",
    "STATUS_SATISFIED",
    "STATUS_UNAVAILABLE",
    "assess_check_suite_gate",
]

#: The policy does not require the suite before publish.
STATUS_DISABLED = "disabled"
#: The suite passed (or was skipped) for exactly this content under exactly this policy.
STATUS_SATISFIED = "satisfied"
#: It did not — publish refused unless forced.
STATUS_BLOCKED = "blocked"
#: The gate could not be evaluated; never blocks.
STATUS_UNAVAILABLE = "unavailable"

#: The version has never been evaluated.
REASON_NOT_EVALUATED = "check-suite-not-evaluated"
#: It was evaluated, but not in its current content under the current policy.
REASON_STALE = "check-suite-stale"
#: The matching evaluation failed.
REASON_FAILED = "check-suite-failed"
#: The matching evaluation is waiting on a required component.
REASON_PENDING = "check-suite-pending"


@dataclass(frozen=True)
class CheckSuiteGateAssessment:
    """The gate's verdict on one candidate publish.

    Attributes:
        status: One of the ``STATUS_*`` constants.
        reason: The ``REASON_*`` code when blocked, otherwise ``None``.
        required_for_publish: Whether the policy arms the gate.
        policy_source: Where the suite policy came from.
        policy_fingerprint: The suite policy's requirements fingerprint now.
        thresholds_fingerprint: The deploy-gate thresholds' fingerprint now.
        draft_digest: The draft's content digest now.
        run_id: The evaluation that decided, when one matched.
        run_state: Its state.
        run_reason: Its reason.
        failing_components: The required components that failed or are pending in it.
        detail: Free-text explanation for ``unavailable``.
    """

    status: str = STATUS_UNAVAILABLE
    reason: Optional[str] = None
    required_for_publish: bool = False
    policy_source: Optional[str] = None
    policy_fingerprint: Optional[str] = None
    thresholds_fingerprint: Optional[str] = None
    draft_digest: Optional[str] = None
    run_id: Optional[str] = None
    run_state: Optional[str] = None
    run_reason: Optional[str] = None
    failing_components: Tuple[str, ...] = ()
    detail: Optional[str] = None

    @property
    def blocked(self) -> bool:
        """Whether publish must be refused unless force-published."""
        return self.status == STATUS_BLOCKED

    def message(self) -> str:
        """Human-readable one-liner for the publish dialog, the 422 and the audit row."""
        if self.status == STATUS_DISABLED:
            return "The API change check suite is not required before publish for this project."
        if self.status == STATUS_UNAVAILABLE:
            return (
                "The API change check suite gate could not be evaluated for this version; publish "
                "was allowed to proceed."
            )
        if self.status == STATUS_SATISFIED:
            if self.run_state == STATE_SKIPPED:
                return (
                    "The API change check suite was skipped for this version's content: none of "
                    "its required checks applied."
                )
            return "The API change check suite passed for this version's content."
        failing = ", ".join(self.failing_components)
        if self.reason == REASON_FAILED:
            return f"The API change check suite failed for this version's content ({failing})."
        if self.reason == REASON_PENDING:
            return (
                "The API change check suite has no verdict yet for this version's content — "
                f"waiting on {failing}."
            )
        if self.reason == REASON_STALE:
            return (
                "This version changed, or the check-suite policy did, since the API change check "
                "suite last ran. Run it again for the current content."
            )
        return (
            "The API change check suite is required before publish and has not been run for this "
            "version."
        )

    def as_payload(self) -> Dict[str, Any]:
        """Serialize to the camelCase shape the 422 body and the audit row share."""
        return {
            "status": self.status,
            "blocked": self.blocked,
            "reason": self.reason,
            "requiredForPublish": self.required_for_publish,
            "policySource": self.policy_source,
            "policyFingerprint": self.policy_fingerprint,
            "thresholdsFingerprint": self.thresholds_fingerprint,
            "draftDigest": self.draft_digest,
            "runId": self.run_id,
            "runState": self.run_state,
            "runReason": self.run_reason,
            "failingComponents": list(self.failing_components),
            "detail": self.detail,
            "message": self.message(),
        }


def _failing(components: Any) -> Tuple[str, ...]:
    """The required components of an evaluation that failed or are pending.

    Args:
        components: The stored component dicts.

    Returns:
        Their names, in report order.
    """
    return tuple(
        str(c.get("component"))
        for c in (components or [])
        if isinstance(c, Mapping)
        and c.get("counted")
        and c.get("state") in (STATE_FAIL, STATE_PENDING)
    )


def assess_check_suite_gate(
    *,
    tenant_id: str,
    project_id: str,
    version: Mapping[str, Any],
    policy: Optional[CheckSuitePolicyOut] = None,
    thresholds: Optional[DeployGatePolicyOut] = None,
    digest_loader: Optional[Callable[[str, Mapping[str, Any]], str]] = None,
) -> CheckSuiteGateAssessment:
    """Assess a candidate publish against the suite gate. Never raises.

    Args:
        tenant_id: Tenant context.
        project_id: Project owning the revision.
        version: The candidate revision row (needs ``id``).
        policy: Pre-resolved suite policy; resolved when omitted.
        thresholds: Pre-resolved deploy-gate thresholds; resolved when omitted.
        digest_loader: Injection point for the draft's content digest; defaults to the one the
            suite records (:func:`app.spec_sync_store.read_draft_document`).

    Returns:
        The :class:`CheckSuiteGateAssessment`. Faults come back as :data:`STATUS_UNAVAILABLE` with
        ``detail`` set, never as an exception.
    """
    try:
        resolved = policy if policy is not None else load_policy(tenant_id, project_id)
        if not resolved.policy.required_for_publish:
            return CheckSuiteGateAssessment(
                status=STATUS_DISABLED,
                required_for_publish=False,
                policy_source=resolved.source,
                policy_fingerprint=requirements_fingerprint(resolved.policy),
            )
        bar = thresholds if thresholds is not None else load_thresholds(tenant_id, project_id)

        loader = digest_loader
        if loader is None:
            from .spec_sync_store import read_draft_document  # Lazy: keeps the import graph flat.

            def loader(tid: str, row: Mapping[str, Any]) -> str:
                return read_draft_document(tid, row)[1]

        digest = loader(tenant_id, version)
        observed = CheckSuiteGateAssessment(
            status=STATUS_SATISFIED,
            required_for_publish=True,
            policy_source=resolved.source,
            policy_fingerprint=requirements_fingerprint(resolved.policy),
            thresholds_fingerprint=bar.content_fingerprint,
            draft_digest=digest,
        )
        version_id = str(version.get("id") or "")
        row = db.find_current_check_suite_run(
            tenant_id=tenant_id,
            version_id=version_id,
            draft_digest=digest,
            policy_fingerprint=observed.policy_fingerprint,
            thresholds_fingerprint=bar.content_fingerprint,
        )
        if not row:
            earlier = db.list_check_suite_runs(
                tenant_id=tenant_id, version_id=version_id, evaluated=True, limit=1
            )
            return _blocked(observed, REASON_STALE if earlier else REASON_NOT_EVALUATED)
    except Exception as exc:  # noqa: BLE001 - a broken gate must not break publishing
        logger.warning(
            "Check-suite gate could not be evaluated for revision %s; continuing without it",
            version.get("id"),
            exc_info=True,
        )
        return CheckSuiteGateAssessment(status=STATUS_UNAVAILABLE, detail=str(exc))

    state = str(row.get("state") or "")
    decided = replace(
        observed,
        run_id=str(row.get("id") or "") or None,
        run_state=state,
        run_reason=str(row.get("reason") or "") or None,
        failing_components=_failing(row.get("components")),
    )
    if state in (STATE_PASS, STATE_SKIPPED):
        return decided
    return _blocked(decided, REASON_FAILED if state == STATE_FAIL else REASON_PENDING)


def _blocked(observed: CheckSuiteGateAssessment, reason: str) -> CheckSuiteGateAssessment:
    """Return an assessment marked blocked for one reason.

    Args:
        observed: What was observed so far.
        reason: The ``REASON_*`` code.

    Returns:
        The blocked assessment.
    """
    return replace(observed, status=STATUS_BLOCKED, reason=reason)
