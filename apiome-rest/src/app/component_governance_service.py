"""Component governance service — DCW-3.4 (private-suite#2364).

The storage-touching half of :mod:`app.component_governance`: it resolves the tenant's
component-library policy from the governing style guide and assesses a revision's recorded
decisions against it. Both :mod:`app.component_library_routes` (the publish gate) and
:mod:`app.component_governance_routes` (the governance API) use it, so neither router imports
the other.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .component_governance import (
    ComponentApprovalAssessment,
    ComponentGovernancePolicy,
    assess_component_approval,
)
from .database import db

logger = logging.getLogger(__name__)

__all__ = ["assess_revision_approval", "find_revision", "resolve_component_policy"]


def resolve_component_policy(tenant_id: str) -> ComponentGovernancePolicy:
    """Resolve the component-library policy of the tenant's governing style guide.

    The library is tenant-scoped, so the GOV-1.4 chain is resolved without a project: the
    tenant-assigned guide, else the tenant's default guide.

    Args:
        tenant_id: The tenant.

    Returns:
        The policy. A missing guide yields the inactive default (no approval gate, no notice
        window).

    Raises:
        Exception: A database fault propagates. Unlike the COL-2.3 version gate, the component
            gate does not open when the policy cannot be read: the library is a shared
            dependency of many projects, so a publish that skipped its approvals would reach
            every consumer.
    """
    guide = db.get_assigned_style_guide(tenant_id, None)
    return ComponentGovernancePolicy.from_guide(guide if isinstance(guide, dict) else None)


def find_revision(tenant_id: str, component_id: str, revision_id: str) -> Optional[Dict[str, Any]]:
    """The tenant-scoped revision row of a component, or ``None``.

    Args:
        tenant_id: The tenant.
        component_id: The component.
        revision_id: The revision.

    Returns:
        The row from :meth:`app.database.Database.get_component_revisions`, or ``None``.
    """
    rows: List[Dict[str, Any]] = db.get_component_revisions(tenant_id, component_id) or []
    return next((row for row in rows if str(row.get("id")) == str(revision_id)), None)


def assess_revision_approval(
    tenant_id: str,
    revision: Dict[str, Any],
    policy: Optional[ComponentGovernancePolicy] = None,
) -> ComponentApprovalAssessment:
    """Assess one revision's recorded decisions against the policy.

    Args:
        tenant_id: The tenant.
        revision: The revision row (``id``, ``payload_digest``).
        policy: The policy, when the caller already resolved it.

    Returns:
        The assessment. Roles are resolved with the RBAC effective-role lookup, so a tenant
        administrator counts as ``owner`` exactly as in the COL-2.3 gate.
    """
    resolved = policy if policy is not None else resolve_component_policy(tenant_id)
    if not resolved.approval_active:
        return assess_component_approval(resolved, [], str(revision.get("payload_digest") or ""), str)
    decisions = db.list_component_revision_approvals(tenant_id, str(revision["id"])) or []
    roles: Dict[str, Optional[str]] = {}

    def role_of(user_id: str) -> Optional[str]:
        if user_id not in roles:
            roles[user_id] = db.get_effective_role_slug(tenant_id, user_id)
        return roles[user_id]

    return assess_component_approval(
        resolved, decisions, str(revision.get("payload_digest") or ""), role_of
    )
