"""Maturity publish gate — the required level made binding at publish time (GVM-1.3, #5856).

A style guide with a maturity ladder (GVM-1.1) may name a ``required_publish_level``. This module
answers one question about a draft:

    Has this draft reached the level its guide requires before it may publish?

It runs inside :func:`app.version_publish_prechecks.enforce_publish_prechecks` after the GOV
error gate and before the COL-2.3 approval gate, and refuses with the contract the
breaking-publish and approval gates already use::

    422 {"detail": {"message": "...", "maturityGate": {level, requiredLevel, blockers, ...}}}

The level comes from :func:`app.lint_policy_service.judge_catalog_revision_maturity`, the same
judgement the deploy gate's ``maturity`` signal and the check suite's ``maturity`` component
read, so the three never disagree about one draft.

When is it armed?
-----------------
Only when the guide's latest policy pack carries **both** a ladder and a required level. A guide
without a ladder never arms it — :data:`STATUS_DISABLED`, and nothing is audited.

The escape and the audit
------------------------
The only way past a block is the GOV-2.5 force-publish (``skipPublishChecks`` +
``forcePublishReason``). Every publish an armed gate judged appends ``version.maturity_gate`` to
``workflow_audit`` with ``action`` ``satisfied`` | ``forced`` | ``unavailable``. Faults anywhere
— an unreadable pack, an evaluation that raises, a required key the frozen ladder does not
contain — degrade to :data:`STATUS_UNAVAILABLE`, which is audited and never blocks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from .maturity_gate import (
    STATUS_FAIL,
    STATUS_NOT_CONFIGURED,
    STATUS_PASS,
    MaturityJudgement,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_ACTION",
    "MaturityGateAssessment",
    "STATUS_BLOCKED",
    "STATUS_DISABLED",
    "STATUS_SATISFIED",
    "STATUS_UNAVAILABLE",
    "assess_maturity_gate",
]

#: Workflow-audit action for every publish an armed level gate judged.
AUDIT_ACTION = "version.maturity_gate"

#: No ladder, or no required level — the gate never surfaces.
STATUS_DISABLED = "disabled"
#: The draft is at or above the required level.
STATUS_SATISFIED = "satisfied"
#: The draft is below the required level — publish refused unless forced.
STATUS_BLOCKED = "blocked"
#: The gate could not be evaluated; never blocks.
STATUS_UNAVAILABLE = "unavailable"

#: ``judge(tenant_id, project_id, version_record_id) -> (judgement, context)``.
Judge = Callable[[str, str, str], Tuple[MaturityJudgement, Mapping[str, Optional[str]]]]


@dataclass(frozen=True)
class MaturityGateAssessment:
    """The gate's verdict on one candidate publish.

    Attributes:
        status: One of the ``STATUS_*`` constants.
        judgement: The level judgement behind it (``None`` when it could not be produced).
        policy_version_id: The policy pack the level was judged under.
        evaluation_id: The ``lint_policy_evaluations`` row that holds the level.
        detail: Free-text explanation for ``unavailable`` outcomes.
    """

    status: str
    judgement: Optional[MaturityJudgement] = None
    policy_version_id: Optional[str] = None
    evaluation_id: Optional[str] = None
    detail: Optional[str] = None

    @property
    def blocked(self) -> bool:
        """Whether publish must be refused unless force-published."""
        return self.status == STATUS_BLOCKED

    def message(self) -> str:
        """Human-readable one-liner for the dialog, the API error and the audit row."""
        if self.status == STATUS_DISABLED:
            return "No maturity level is required to publish this project."
        if self.status == STATUS_UNAVAILABLE:
            return (
                "The maturity level could not be evaluated for this version; publish was "
                "allowed to proceed."
            )
        return self.judgement.message() if self.judgement else ""

    def as_payload(self) -> Dict[str, Any]:
        """Serialize to the camelCase shape the 422 body and audit rows share."""
        judged = self.judgement.as_payload() if self.judgement else {}
        return {
            "status": self.status,
            "blocked": self.blocked,
            "ladderName": judged.get("ladderName"),
            "level": judged.get("level"),
            "levelLabel": judged.get("levelLabel"),
            "requiredLevel": judged.get("requiredLevel"),
            "requiredLevelLabel": judged.get("requiredLevelLabel"),
            "blockers": judged.get("blockers") or [],
            "reason": judged.get("reason"),
            "policyVersionId": self.policy_version_id,
            "evaluationId": self.evaluation_id,
            "detail": self.detail or judged.get("detail"),
            "message": self.message(),
        }


def _default_judge(
    tenant_id: str, project_id: str, version_record_id: str
) -> Tuple[MaturityJudgement, Mapping[str, Optional[str]]]:
    """Judge with :func:`app.lint_policy_service.judge_catalog_revision_maturity`."""
    from .lint_policy_service import judge_catalog_revision_maturity  # Lazy: flat import graph.

    return judge_catalog_revision_maturity(
        tenant_id=tenant_id, project_id=project_id, version_record_id=version_record_id
    )


def assess_maturity_gate(
    *,
    tenant_id: str,
    project_id: str,
    version: Mapping[str, Any],
    judge: Optional[Judge] = None,
) -> MaturityGateAssessment:
    """Assess a candidate publish against the required publish level. Never raises.

    Args:
        tenant_id: Tenant context.
        project_id: Project owning the revision.
        version: The candidate revision row (needs ``id``).
        judge: Injection point for the level judgement; defaults to
            :func:`app.lint_policy_service.judge_catalog_revision_maturity`.

    Returns:
        The :class:`MaturityGateAssessment`. ``pass`` is satisfied, ``fail`` blocked,
        ``not_configured`` disabled, and ``unknown`` — or any fault — unavailable.
    """
    version_id = str(version.get("id") or "")
    try:
        judgement, context = (judge or _default_judge)(tenant_id, project_id, version_id)
    except Exception as exc:  # noqa: BLE001 - a broken gate must not break publishing
        logger.warning(
            "Maturity gate could not be evaluated for revision %s; continuing without it",
            version_id,
            exc_info=True,
        )
        return MaturityGateAssessment(status=STATUS_UNAVAILABLE, detail=str(exc))

    status = {
        STATUS_PASS: STATUS_SATISFIED,
        STATUS_FAIL: STATUS_BLOCKED,
        STATUS_NOT_CONFIGURED: STATUS_DISABLED,
    }.get(judgement.status, STATUS_UNAVAILABLE)
    return MaturityGateAssessment(
        status=status,
        judgement=judgement,
        policy_version_id=context.get("policyVersionId"),
        evaluation_id=context.get("evaluationId"),
    )
