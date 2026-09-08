"""Persistence for deploy-gate threshold policy — CTG-4.5 (#4502).

:mod:`app.deploy_gate` decides what a threshold *means*; this module is the only place one is read
or written, so V254's two rules are applied once rather than at each call site.

**Two scopes, one lookup.** ``project_id IS NULL`` is the tenant-wide policy and a row naming a
project overrides it for that project. Resolution is a single query with the override sorting first
— the gate is on a pipeline's hot path and does not deserve two round trips to find out where the
bar is.

**An unreadable policy still answers.** A gate that returned ``503`` because a policy row could not
be read would be worse than useless: every pipeline in the tenant would stop. :func:`load_policy`
therefore falls back to the documented default and marks the result ``degraded``, so the caller can
tell "nothing is configured" from "I could not read what is" without having to guess.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional

from .database import db
from .deploy_gate import (
    DEFAULT_THRESHOLDS,
    POLICY_SOURCE_DEFAULT,
    POLICY_SOURCE_PROJECT,
    POLICY_SOURCE_TENANT,
    DeployGatePolicyOut,
    DeployGateThresholds,
    GateThresholdError,
    canonical_thresholds_body,
    thresholds_content_fingerprint,
    thresholds_from_body,
)

logger = logging.getLogger(__name__)

__all__ = [
    "audit_detail",
    "clear_policy",
    "default_policy",
    "load_policy",
    "policy_from_row",
    "save_policy",
]


def default_policy(*, degraded: bool = False) -> DeployGatePolicyOut:
    """The policy a scope with nothing saved is judged under.

    Args:
        degraded: True when this default is standing in for a policy that could not be read.

    Returns:
        The documented default, fingerprinted so a response always carries one.
    """
    return DeployGatePolicyOut(
        source=POLICY_SOURCE_DEFAULT,
        policy_id=None,
        content_fingerprint=thresholds_content_fingerprint(DEFAULT_THRESHOLDS),
        thresholds=DEFAULT_THRESHOLDS,
        degraded=degraded,
    )


def policy_from_row(row: Mapping[str, Any]) -> DeployGatePolicyOut:
    """Adapt a stored ``deploy_gate_policy`` row into its wire model.

    A row whose body this version of the code cannot parse is *not* an error: the row may have
    been written by a newer release. It reads as the default, marked ``degraded``, which keeps the
    gate answering while making the substitution visible.

    Args:
        row: The stored row.

    Returns:
        The resolved policy.
    """
    scoped = row.get("project_id") is not None
    try:
        thresholds = thresholds_from_body(row.get("thresholds"))
    except GateThresholdError:
        logger.warning(
            "Stored deploy-gate policy %s is not readable by this release; using the default",
            row.get("id"),
            exc_info=True,
        )
        degraded = default_policy(degraded=True)
        return degraded.model_copy(
            update={
                "source": POLICY_SOURCE_PROJECT if scoped else POLICY_SOURCE_TENANT,
                "policy_id": str(row["id"]) if row.get("id") else None,
                "updated_at": row.get("updated_at"),
                "updated_by": row.get("updated_by"),
            }
        )

    return DeployGatePolicyOut(
        source=POLICY_SOURCE_PROJECT if scoped else POLICY_SOURCE_TENANT,
        policy_id=str(row["id"]) if row.get("id") else None,
        content_fingerprint=str(row.get("content_fingerprint") or "")
        or thresholds_content_fingerprint(thresholds),
        thresholds=thresholds,
        updated_at=row.get("updated_at"),
        updated_by=str(row["updated_by"]) if row.get("updated_by") else None,
    )


def load_policy(
    tenant_id: str, project_id: Optional[str] = None
) -> DeployGatePolicyOut:
    """Return the deploy-gate policy in force for a scope.

    Never raises. A store failure degrades to the documented default rather than failing the
    gate — every pipeline in the tenant reads this, and an infrastructure fault must not stop
    all of them.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project to resolve for; ``None`` reads only the tenant-wide policy.

    Returns:
        The resolved policy, with ``source`` saying which scope supplied it.
    """
    if not tenant_id:
        return default_policy()
    try:
        row = db.get_deploy_gate_policy(tenant_id, project_id)
    except Exception:  # noqa: BLE001 - a gate must answer even when its policy cannot be read
        logger.warning(
            "Could not load the deploy-gate policy for tenant %s; using the default",
            tenant_id,
            exc_info=True,
        )
        return default_policy(degraded=True)
    if not row:
        return default_policy()
    return policy_from_row(row)


def save_policy(
    tenant_id: str,
    *,
    project_id: Optional[str] = None,
    body: Optional[Mapping[str, Any]],
    actor_id: Optional[str] = None,
) -> DeployGatePolicyOut:
    """Save the thresholds for one scope, replacing whatever it held.

    Args:
        tenant_id: Owning tenant.
        project_id: The project this policy governs, or ``None`` for the tenant-wide policy.
        body: The ``ctg.gate-policy.v1`` threshold body. Absent keys take their documented
            defaults, so a body naming one threshold configures exactly that one.
        actor_id: The user making the change.

    Returns:
        The stored policy.

    Raises:
        GateThresholdError: When the body is not a valid threshold set.
        RuntimeError: When the write returned no row (a malformed tenant id).
    """
    thresholds: DeployGateThresholds = thresholds_from_body(body)
    fingerprint = thresholds_content_fingerprint(thresholds)
    row = db.upsert_deploy_gate_policy(
        tenant_id=tenant_id,
        project_id=project_id,
        thresholds=canonical_thresholds_body(thresholds),
        content_fingerprint=fingerprint,
        actor_id=actor_id,
    )
    if not row:
        raise RuntimeError("The deploy-gate policy could not be stored for this tenant.")
    return policy_from_row(row)


def clear_policy(tenant_id: str, *, project_id: Optional[str] = None) -> bool:
    """Remove the policy saved for one scope, falling back to the next one up.

    A project override is dropped in favour of the tenant policy; the tenant policy is dropped in
    favour of the documented default. Nothing cascades: clearing a tenant policy leaves its
    projects' overrides in place, because those were configured deliberately.

    Args:
        tenant_id: Owning tenant.
        project_id: The project override to drop, or ``None`` for the tenant-wide policy.

    Returns:
        True when a policy was saved for that exact scope and has now been removed.
    """
    return db.delete_deploy_gate_policy(tenant_id, project_id) > 0


def audit_detail(policy: DeployGatePolicyOut) -> Dict[str, Any]:
    """Build the audit payload for a policy change.

    Args:
        policy: The policy that was saved.

    Returns:
        The thresholds and their fingerprint, so a later reader can see the exact bar that was set
        without joining back to a row that may since have changed again.
    """
    return {
        "policyId": policy.policy_id,
        "source": policy.source,
        "contentFingerprint": policy.content_fingerprint,
        "thresholds": canonical_thresholds_body(policy.thresholds),
    }
