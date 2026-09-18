"""Persistence for the API change check suite policy — GNC-3.1 (#4740).

:mod:`app.api_check_suite` decides what a policy *means*; this module is the only place one is read
or written. It follows CTG-4.5's :mod:`app.deploy_gate_store` deliberately, because the two answer
the same kind of question for neighbouring gates:

**Two scopes, one lookup.** ``project_id IS NULL`` is the tenant-wide policy and a row naming a
project overrides it. Resolution is one query with the override sorting first.

**An unreadable policy still answers.** A suite that refused to run because a policy row could not
be read would stop every pull request in the tenant. :func:`load_policy` falls back to the
documented default and marks the result ``degraded``, so "nothing is configured" and "I could not
read what is" stay distinguishable.

**The row is mutable, and that is safe here too.** A suite *does* store verdicts, unlike the deploy
gate — but every evaluation snapshots the policy body and fingerprint it was judged under (V267
rule 3), so no stored verdict ever has to be explained by a policy row that has since moved.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional

from .api_check_suite import (
    DEFAULT_POLICY,
    POLICY_SOURCE_DEFAULT,
    POLICY_SOURCE_PROJECT,
    POLICY_SOURCE_TENANT,
    CheckSuitePolicy,
    CheckSuitePolicyError,
    CheckSuitePolicyOut,
    canonical_policy_body,
    policy_fingerprint,
    policy_from_body,
)
from .database import db

logger = logging.getLogger(__name__)

__all__ = [
    "audit_detail",
    "clear_policy",
    "default_policy",
    "load_policy",
    "policy_from_row",
    "save_policy",
]


def default_policy(*, degraded: bool = False) -> CheckSuitePolicyOut:
    """The policy a scope with nothing saved is judged under.

    Args:
        degraded: True when this default stands in for a policy that could not be read.

    Returns:
        The documented default, fingerprinted so every evaluation carries one.
    """
    return CheckSuitePolicyOut(
        source=POLICY_SOURCE_DEFAULT,
        policy_id=None,
        content_fingerprint=policy_fingerprint(DEFAULT_POLICY),
        policy=DEFAULT_POLICY,
        degraded=degraded,
    )


def policy_from_row(row: Mapping[str, Any]) -> CheckSuitePolicyOut:
    """Adapt a stored ``api_check_suite_policy`` row into its wire model.

    A body this release cannot parse (a newer release may have written it) reads as the default,
    marked ``degraded`` — the suite keeps answering and the substitution stays visible.

    Args:
        row: The stored row.

    Returns:
        The resolved policy.
    """
    scoped = row.get("project_id") is not None
    source = POLICY_SOURCE_PROJECT if scoped else POLICY_SOURCE_TENANT
    try:
        policy: CheckSuitePolicy = policy_from_body(row.get("policy"))
    except CheckSuitePolicyError:
        logger.warning(
            "Stored check-suite policy %s is not readable by this release; using the default",
            row.get("id"),
            exc_info=True,
        )
        return default_policy(degraded=True).model_copy(
            update={
                "source": source,
                "policy_id": str(row["id"]) if row.get("id") else None,
                "updated_at": row.get("updated_at"),
                "updated_by": str(row["updated_by"]) if row.get("updated_by") else None,
            }
        )
    return CheckSuitePolicyOut(
        source=source,
        policy_id=str(row["id"]) if row.get("id") else None,
        content_fingerprint=policy_fingerprint(policy),
        policy=policy,
        updated_at=row.get("updated_at"),
        updated_by=str(row["updated_by"]) if row.get("updated_by") else None,
    )


def load_policy(tenant_id: str, project_id: Optional[str] = None) -> CheckSuitePolicyOut:
    """Return the suite policy in force for a scope. Never raises.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project to resolve for; ``None`` reads only the tenant-wide policy.

    Returns:
        The resolved policy, with ``source`` saying which scope supplied it.
    """
    if not tenant_id:
        return default_policy()
    try:
        row = db.get_check_suite_policy(tenant_id, project_id)
    except Exception:  # noqa: BLE001 - the suite must answer even when its policy cannot be read
        logger.warning(
            "Could not load the check-suite policy for tenant %s; using the default",
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
) -> CheckSuitePolicyOut:
    """Save the policy for one scope, replacing whatever it held.

    Args:
        tenant_id: Owning tenant.
        project_id: The project this policy governs, or ``None`` for the tenant-wide policy.
        body: The ``gnc.check-suite-policy.v1`` body. Absent components take their defaults.
        actor_id: The administrator making the change.

    Returns:
        The stored policy.

    Raises:
        CheckSuitePolicyError: When the body is not a valid policy.
        RuntimeError: When the write returned no row (a malformed tenant id).
    """
    policy = policy_from_body(body)
    row = db.upsert_check_suite_policy(
        tenant_id=tenant_id,
        project_id=project_id,
        policy=canonical_policy_body(policy),
        content_fingerprint=policy_fingerprint(policy),
        actor_id=actor_id,
    )
    if not row:
        raise RuntimeError("The check-suite policy could not be stored for this tenant.")
    return policy_from_row(row)


def clear_policy(tenant_id: str, *, project_id: Optional[str] = None) -> bool:
    """Remove the policy saved for one scope, falling back to the next one up.

    Nothing cascades: clearing a tenant policy leaves its projects' overrides in place, because
    those were configured deliberately.

    Args:
        tenant_id: Owning tenant.
        project_id: The project override to drop, or ``None`` for the tenant-wide policy.

    Returns:
        True when a policy was saved for that exact scope and has now been removed.
    """
    return db.delete_check_suite_policy(tenant_id, project_id) > 0


def audit_detail(policy: CheckSuitePolicyOut) -> Dict[str, Any]:
    """Build the audit payload for a policy change.

    Args:
        policy: The policy now in force.

    Returns:
        The whole body and its fingerprint, so a later reader sees the exact policy that was set
        without joining back to a row that may since have changed again.
    """
    return {
        "policyId": policy.policy_id,
        "source": policy.source,
        "contentFingerprint": policy.content_fingerprint,
        "policy": canonical_policy_body(policy.policy),
    }
