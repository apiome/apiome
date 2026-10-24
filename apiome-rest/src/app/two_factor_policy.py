"""Tenant two-factor policy — TFA-1.3 (#5657).

A tenant may **require two-factor authentication** for its members (apiome-db V316):

* ``require_two_factor`` — the switch, off by default.
* ``two_factor_grace_days`` — how long (0–90 days, default 7) a member without two-factor may keep
  working.
* ``two_factor_required_since`` — when the switch was last turned on. Turning it off clears it, so
  turning it on again restarts every grace period.

A member's **deadline** is the later of the policy being turned on and the member joining, plus the
grace days (:data:`DUE_AT_SQL`, shared with :meth:`app.database.Database.list_members`). Each member is
then ``enabled`` (has two-factor), ``grace`` (before the deadline), ``overdue`` (past it) or
``not_required`` (the policy is off). apiome-ui shows overdue members a blocking enrolment screen;
API keys are unaffected.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .consumer_contract_store import ConsumerActor
from .database import db
from .revision_deprecation import is_uuid_string

__all__ = [
    "DEFAULT_GRACE_DAYS",
    "DUE_AT_SQL",
    "MAX_GRACE_DAYS",
    "STATUS_SQL",
    "TwoFactorCompliance",
    "TwoFactorPolicy",
    "TwoFactorPolicyInput",
    "read_policy",
    "update_policy",
]

#: The grace period a tenant gets until an owner changes it.
DEFAULT_GRACE_DAYS = 7
#: The longest grace period (the V316 check constraint).
MAX_GRACE_DAYS = 90

#: A member's deadline, over ``apiome.tenants tn`` and ``apiome.tenant_users tu``; NULL while the
#: policy is off.
DUE_AT_SQL = (
    "CASE WHEN tn.require_two_factor AND tn.two_factor_required_since IS NOT NULL "
    "THEN GREATEST(tn.two_factor_required_since, tu.created_at) "
    "+ make_interval(days => tn.two_factor_grace_days) END"
)

#: A member's compliance (``not_required``, ``enabled``, ``grace`` or ``overdue``), over the same
#: aliases plus ``apiome.users u``.
STATUS_SQL = (
    "CASE WHEN NOT tn.require_two_factor THEN 'not_required' "
    "WHEN COALESCE(u.\"twoFactorEnabled\", FALSE) THEN 'enabled' "
    f"WHEN now() < ({DUE_AT_SQL}) THEN 'grace' "
    "ELSE 'overdue' END"
)


class TwoFactorCompliance(BaseModel):
    """How many active members are in each state."""

    model_config = ConfigDict(extra="forbid")

    enabled: int = Field(default=0, description="Active members with two-factor on.")
    grace: int = Field(default=0, description="Active members without it, before their deadline.")
    overdue: int = Field(default=0, description="Active members without it, past their deadline.")


class TwoFactorPolicy(BaseModel):
    """The tenant's two-factor policy."""

    model_config = ConfigDict(extra="forbid")

    require_two_factor: bool = Field(description="When true, every member must turn on two-factor.")
    grace_days: int = Field(
        description="Days a member without two-factor may keep working after the policy is on or they join."
    )
    required_since: Optional[str] = Field(
        default=None, description="When the policy was last turned on (ISO-8601); null while off."
    )
    compliance: TwoFactorCompliance = Field(
        default_factory=TwoFactorCompliance,
        description="Active members by state; all zero while the policy is off.",
    )


class TwoFactorPolicyInput(BaseModel):
    """A policy change. Omitted fields are left alone."""

    model_config = ConfigDict(extra="forbid")

    require_two_factor: Optional[bool] = None
    grace_days: Optional[int] = Field(default=None, ge=0, le=MAX_GRACE_DAYS)


def _iso(value: Any) -> Optional[str]:
    """ISO-8601 for a timestamp; strings and ``None`` pass through."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


_POLICY_SQL = """
    SELECT tn.require_two_factor, tn.two_factor_grace_days, tn.two_factor_required_since
    FROM apiome.tenants tn
    WHERE tn.id = %s::uuid
"""

_COMPLIANCE_SQL = f"""
    SELECT ({STATUS_SQL}) AS status, count(*)::int AS members
    FROM apiome.tenant_users tu
    JOIN apiome.tenants tn ON tn.id = tu.tenant_id
    JOIN apiome.users u ON u.id = tu.user_id
    WHERE tu.tenant_id = %s::uuid AND tu.status = 'active' AND u.deleted_at IS NULL
      AND tn.require_two_factor
    GROUP BY 1
"""


def _policy_from_rows(row: Optional[Dict[str, Any]], counts: List[Dict[str, Any]]) -> TwoFactorPolicy:
    """Build the policy from a ``_POLICY_SQL`` row and ``_COMPLIANCE_SQL`` rows.

    Args:
        row: The tenant's row; ``None`` reads as the defaults.
        counts: ``{status, members}`` rows.

    Returns:
        The policy.
    """
    if not row:
        return TwoFactorPolicy(require_two_factor=False, grace_days=DEFAULT_GRACE_DAYS)
    by_status = {str(entry["status"]): int(entry["members"]) for entry in counts}
    return TwoFactorPolicy(
        require_two_factor=bool(row.get("require_two_factor")),
        grace_days=int(row.get("two_factor_grace_days") or 0),
        required_since=_iso(row.get("two_factor_required_since")),
        compliance=TwoFactorCompliance(
            enabled=by_status.get("enabled", 0),
            grace=by_status.get("grace", 0),
            overdue=by_status.get("overdue", 0),
        ),
    )


def read_policy(tenant_id: str) -> TwoFactorPolicy:
    """The tenant's two-factor policy and its members' compliance.

    Args:
        tenant_id: The tenant.

    Returns:
        The policy; the defaults (off, 7 days) for an unknown tenant.
    """
    if not is_uuid_string(tenant_id or ""):
        return TwoFactorPolicy(require_two_factor=False, grace_days=DEFAULT_GRACE_DAYS)
    rows = db.execute_query(_POLICY_SQL, (tenant_id,))
    counts = db.execute_query(_COMPLIANCE_SQL, (tenant_id,)) if rows else []
    return _policy_from_rows(dict(rows[0]) if rows else None, [dict(entry) for entry in counts or []])


def update_policy(tenant_id: str, change: TwoFactorPolicyInput, *, actor: ConsumerActor) -> TwoFactorPolicy:
    """Change the policy, audited as ``two_factor_policy.update`` in the same transaction.

    Turning the policy on stamps ``two_factor_required_since`` (starting every grace period);
    turning it off clears it. Saving it on while it is already on keeps the original stamp, so a
    grace-days edit never restarts anyone's clock.

    Args:
        tenant_id: The tenant.
        change: The fields to change (``model_fields_set`` decides which).
        actor: Who changed it.

    Returns:
        The policy after the change.
    """
    provided = change.model_fields_set

    def read(cursor: Any) -> TwoFactorPolicy:
        cursor.execute(_POLICY_SQL, (tenant_id,))
        row = cursor.fetchone()
        cursor.execute(_COMPLIANCE_SQL, (tenant_id,))
        return _policy_from_rows(dict(row) if row else None, [dict(entry) for entry in cursor.fetchall()])

    def work(cursor: Any) -> TwoFactorPolicy:
        before = read(cursor)
        assignments: List[str] = []
        params: List[Any] = []
        if "require_two_factor" in provided and change.require_two_factor is not None:
            assignments.append("require_two_factor = %s")
            params.append(bool(change.require_two_factor))
            if change.require_two_factor:
                assignments.append("two_factor_required_since = COALESCE(two_factor_required_since, now())")
            else:
                assignments.append("two_factor_required_since = NULL")
        if "grace_days" in provided and change.grace_days is not None:
            assignments.append("two_factor_grace_days = %s")
            params.append(int(change.grace_days))
        if assignments:
            cursor.execute(
                f"UPDATE apiome.tenants SET {', '.join(assignments)} WHERE id = %s::uuid",
                (*params, tenant_id),
            )
        after = read(cursor)
        audited = ("require_two_factor", "grace_days", "required_since")
        if before.model_dump(include=set(audited)) != after.model_dump(include=set(audited)):
            db._append_access_audit(
                cursor,
                tenant_id=tenant_id,
                action="two_factor_policy.update",
                actor_id=actor.user_id,
                actor_label=actor.label,
                target="two-factor-policy",
                source="api_key" if actor.kind == "api_key" else "web",
                detail={
                    "from": before.model_dump(mode="json", include=set(audited)),
                    "to": after.model_dump(mode="json", include=set(audited)),
                },
            )
        return after

    return db._guarded_tx(work)
