"""Contracts publish gate — block a version publish on failing contracts (PFX-7.3, #6963).

A project bound to a Pact pacticipant carries consumer/provider contracts. This module answers
one question about a draft that is about to publish:

    Does the Pact ``can-i-deploy`` verdict for this revision say it breaks a contract?

It is the CTG-3.4 guardrail pattern applied to contracts: a three-level policy
(``off`` / ``warn`` / ``block``), a read-only preflight the publish dialog calls, a 422 refusal
inside :func:`app.version_publish_prechecks.enforce_publish_prechecks`, and the GOV-2.5
force-publish (``skipPublishChecks`` + ``forcePublishReason``) as the only way past a block —
audited as ``version.contracts_gate``::

    422 {"detail": {"message": "...", "contractsPublishGate": {policy, status, blocked, ...}}}

The verdict is the deploy gate's ``contracts`` signal (PFX-7.2), which is itself the shared
:func:`app.pact_matrix.deployment_verdict` behind ``GET …/can-i-deploy``; the publish gate, the
deploy gate and the broker route therefore cannot disagree about one revision.

Status vocabulary (``blocked`` is the only one that refuses):

* ``disabled``    — the policy is ``off``; nothing surfaces and nothing is audited.
* ``no-contracts``— no bound pacticipant, version or pacts: there is nothing to judge.
* ``ok``          — deployable, no warnings.
* ``warning``     — a failing contract under ``warn``, or a pass that leans on an unverified
  provider contract under any level.
* ``blocked``     — a failing contract under ``block``.
* ``pending``     — a verification result is missing: "not verified yet" is not "failed", so it
  never blocks.
* ``unavailable`` — the gate could not be evaluated (a fault, or the caller may not read pacts);
  never blocks.

Faults anywhere degrade to ``unavailable``: a broken gate must never break publishing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional

from .breaking_publish_policy import (
    BREAKING_PUBLISH_POLICY_BLOCK,
    BREAKING_PUBLISH_POLICY_OFF,
    DEFAULT_BREAKING_PUBLISH_POLICY,
    normalize_breaking_publish_policy,
)
from .deploy_gate import (
    REASON_CONTRACTS_PENDING_RESULTS,
    STATUS_FAIL,
    STATUS_NOT_CONFIGURED,
    STATUS_PASS,
    STATUS_UNKNOWN,
    STATUS_WARN,
    GateSignal,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_ACTION",
    "ContractsPublishAssessment",
    "MAX_REASONS",
    "STATUS_BLOCKED",
    "STATUS_DISABLED",
    "STATUS_NO_CONTRACTS",
    "STATUS_OK",
    "STATUS_PENDING",
    "STATUS_UNAVAILABLE",
    "STATUS_WARNING",
    "assess_contracts_publish_gate",
    "resolve_contracts_publish_policy",
]

#: Workflow-audit action for every publish the gate warned about or that was forced past it.
AUDIT_ACTION = "version.contracts_gate"

STATUS_DISABLED = "disabled"
STATUS_NO_CONTRACTS = "no-contracts"
STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_BLOCKED = "blocked"
STATUS_PENDING = "pending"
STATUS_UNAVAILABLE = "unavailable"

#: Most per-row reasons carried in a payload — a pacticipant with a wide matrix must not bloat the
#: 422 body, the preflight or the audit row. ``reasonCount`` still reports the true total.
MAX_REASONS = 50

#: ``read_signal(tenant_id, project_id, version_label, environment, permitted) -> GateSignal``.
SignalReader = Callable[[str, str, Optional[str], Optional[str], bool], GateSignal]


@dataclass(frozen=True)
class ContractsPublishAssessment:
    """The gate's verdict on one candidate publish.

    Attributes:
        policy: The resolved level — ``off`` / ``warn`` / ``block``.
        status: One of the ``STATUS_*`` constants.
        signal: The deploy gate ``contracts`` signal behind it (``None`` when disabled or the
            gate could not read it). Carries the pacticipant, version and per-row reasons.
        detail: Free-text explanation for ``unavailable`` outcomes.
    """

    policy: str = DEFAULT_BREAKING_PUBLISH_POLICY
    status: str = STATUS_NO_CONTRACTS
    signal: Optional[GateSignal] = None
    detail: Optional[str] = None

    @property
    def triggered(self) -> bool:
        """Whether the gate has a warning or a block to report (audited, shown in the dialog)."""
        return self.status in (STATUS_WARNING, STATUS_BLOCKED)

    @property
    def blocked(self) -> bool:
        """Whether publish must be refused unless force-published."""
        return self.status == STATUS_BLOCKED

    def message(self) -> str:
        """Human-readable one-liner for the dialog, the API error and the audit row."""
        if self.status == STATUS_DISABLED:
            return "Contract checks are off for publishing."
        if self.status == STATUS_UNAVAILABLE:
            return self.detail or (
                "The contract verdict could not be read for this version; publish was "
                "allowed to proceed."
            )
        if self.signal is None:
            return self.detail or ""
        if self.status == STATUS_BLOCKED:
            return f"Publishing is blocked by failing contracts: {self.signal.detail}"
        if self.status == STATUS_WARNING:
            return f"Contracts need attention before publishing: {self.signal.detail}"
        return self.signal.detail

    def as_payload(self) -> Dict[str, Any]:
        """Serialize to the camelCase shape the 422 body, the preflight and the audit share."""
        data: Mapping[str, Any] = self.signal.data if self.signal else {}
        return {
            "policy": self.policy,
            "status": self.status,
            "triggered": self.triggered,
            "blocked": self.blocked,
            "pacticipant": data.get("pacticipant"),
            "version": data.get("version"),
            "environment": data.get("environment"),
            "deployable": data.get("deployable"),
            "reasons": list(data.get("reasons") or [])[:MAX_REASONS],
            "reasonCount": len(data.get("reasons") or []),
            "counts": dict(data.get("counts") or {}),
            "reason": self.signal.reason if self.signal else None,
            "link": (self.signal.link or None) if self.signal else None,
            "detail": self.detail or (self.signal.detail if self.signal else None),
            "message": self.message(),
        }


def resolve_contracts_publish_policy(tenant_id: str, project_id: Optional[str] = None) -> str:
    """Resolve the publish policy and the destination environment from the deploy-gate policy.

    Args:
        tenant_id: The tenant whose deploy-gate policy applies.
        project_id: The project, enabling a project-level policy to override the tenant's.

    Returns:
        ``off`` / ``warn`` / ``block``. Any fault yields the default level, so a lookup that
        misbehaves can never escalate a tenant to ``block``.
    """
    return _policy_and_environment(tenant_id, project_id)[0]


def _policy_and_environment(
    tenant_id: str, project_id: Optional[str]
) -> "tuple[str, Optional[str]]":
    """Read ``contracts.publishPolicy`` and ``contracts.environment`` from the policy in force."""
    try:
        from .deploy_gate_store import load_policy  # Lazy: flat import graph.

        contracts = load_policy(tenant_id, project_id).thresholds.contracts
        return normalize_breaking_publish_policy(contracts.publish_policy), contracts.environment
    except Exception:  # noqa: BLE001 - policy resolution must never break a publish
        logger.warning(
            "Contracts publish policy resolution failed for tenant %s (project %s); "
            "falling back to %r",
            tenant_id,
            project_id,
            DEFAULT_BREAKING_PUBLISH_POLICY,
            exc_info=True,
        )
        return DEFAULT_BREAKING_PUBLISH_POLICY, None


def _default_reader(
    tenant_id: str,
    project_id: str,
    version_label: Optional[str],
    environment: Optional[str],
    permitted: bool,
) -> GateSignal:
    """Read the signal with the deploy gate's ``_contracts_signal`` (one verdict, one code path)."""
    from .deploy_gate import ContractThresholds
    from .deploy_gate_service import _contracts_signal  # Lazy: flat import graph.

    return _contracts_signal(
        tenant_id,
        project_id,
        version_label,
        thresholds=ContractThresholds(environment=environment),
        link="",
        permitted=permitted,
    )


def assess_contracts_publish_gate(
    *,
    tenant_id: str,
    project_id: str,
    version: Mapping[str, Any],
    permitted: bool = False,
    policy: Optional[str] = None,
    reader: Optional[SignalReader] = None,
) -> ContractsPublishAssessment:
    """Assess a candidate publish against the project's contract verdict. Never raises.

    Args:
        tenant_id: Tenant context; every read is scoped to it.
        project_id: Project owning the revision.
        version: The candidate revision row (needs ``version_id``, the label).
        permitted: Whether the caller holds ``pacts:view``. Without it the verdict is not read
            and the gate reports ``unavailable`` — never ``blocked`` — so a publish cannot
            disclose, or be refused on, pacts the caller may not see.
        policy: Pre-resolved level; resolved from the deploy-gate policy when omitted.
        reader: Injection point for the signal read.

    Returns:
        The :class:`ContractsPublishAssessment`.
    """
    resolved, environment = _policy_and_environment(tenant_id, project_id)
    if policy is not None:
        resolved = normalize_breaking_publish_policy(policy)
    if resolved == BREAKING_PUBLISH_POLICY_OFF:
        return ContractsPublishAssessment(policy=resolved, status=STATUS_DISABLED)

    label = str(version.get("version_id") or "") or None
    try:
        signal = (reader or _default_reader)(tenant_id, project_id, label, environment, permitted)
    except Exception as exc:  # noqa: BLE001 - a broken gate must not break publishing
        logger.warning(
            "Contracts publish gate could not be evaluated for revision %s; continuing without it",
            str(version.get("id") or "?"),
            exc_info=True,
        )
        return ContractsPublishAssessment(
            policy=resolved, status=STATUS_UNAVAILABLE, detail=f"Contract gate fault: {exc}"
        )

    if signal.status == STATUS_NOT_CONFIGURED:
        status = STATUS_NO_CONTRACTS
    elif signal.status == STATUS_PASS:
        status = STATUS_OK
    elif signal.status == STATUS_WARN:
        status = STATUS_WARNING
    elif signal.status == STATUS_FAIL:
        status = (
            STATUS_BLOCKED if resolved == BREAKING_PUBLISH_POLICY_BLOCK else STATUS_WARNING
        )
    elif signal.status == STATUS_UNKNOWN and signal.reason == REASON_CONTRACTS_PENDING_RESULTS:
        status = STATUS_PENDING
    else:
        status = STATUS_UNAVAILABLE
    return ContractsPublishAssessment(policy=resolved, status=status, signal=signal)
