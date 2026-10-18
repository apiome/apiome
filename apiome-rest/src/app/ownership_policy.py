"""Unowned-entity policy and ownership drift — CDG-2.5 (#5964).

Three things a workspace needs once ownership exists (CDG-2.1–2.4):

* **The policy** — two tenant settings (apiome-db V287): a **catch-all team** that also receives
  findings on entities with no confirmed owner (:mod:`app.owner_routing` reads it), and **require an
  owner to publish**, a publish gate with reason ``no-owner``.
* **The owner gate** — :func:`assess_owner_gate` is what the publish prechecks call after the COL-2.3
  approval gate. It always returns a verdict, including ``disabled``, so the publish dialog can say
  the gate is off rather than staying silent.
* **Ownership drift** — :func:`ownership_drift` lists what has quietly stopped working: entities whose
  owner team was deleted or has no members, and suggestions nobody has acted on for 30 days.

And the two ``owner.*`` facts GVM-1.x ladders will read through CDG-5.4: :func:`owner_facts`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .consumer_contract_store import ConsumerActor
from .database import db
from .revision_deprecation import is_uuid_string

__all__ = [
    "DRIFT_DELETED_TEAM",
    "DRIFT_EMPTY_TEAM",
    "DRIFT_STALE_SUGGESTION",
    "GATE_BLOCKED",
    "GATE_DISABLED",
    "GATE_SATISFIED",
    "REASON_NO_OWNER",
    "STALE_SUGGESTION_DAYS",
    "OwnerGateAssessment",
    "OwnershipPolicy",
    "OwnershipPolicyInput",
    "OwnershipPolicyError",
    "assess_owner_gate",
    "owner_facts",
    "ownership_drift",
    "read_policy",
    "update_policy",
]

#: The gate is off: publishing does not require an owner.
GATE_DISABLED = "disabled"
#: The gate is on and the project has a confirmed owner.
GATE_SATISFIED = "satisfied"
#: The gate is on and the project has no confirmed owner.
GATE_BLOCKED = "blocked"
#: The refusal reason a blocked publish carries.
REASON_NO_OWNER = "no-owner"

#: A suggestion this many days old with nobody confirming it is drift.
STALE_SUGGESTION_DAYS = 30

DRIFT_DELETED_TEAM = "deleted_team"
DRIFT_EMPTY_TEAM = "empty_team"
DRIFT_STALE_SUGGESTION = "stale_suggestion"

#: Most rows one drift read returns per reason.
_DRIFT_LIMIT = 200

#: An unknown team slug on update.
CODE_TEAM_NOT_FOUND = "ownership-policy-team-not-found"


class OwnershipPolicyError(ValueError):
    """A refused policy change, with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PolicyTeam(BaseModel):
    """The catch-all team."""

    model_config = ConfigDict(extra="forbid")

    id: str
    slug: str
    name: str
    deleted: bool = Field(default=False, description="True when the team was deleted: it receives nothing.")
    member_count: int = 0


class OwnershipPolicy(BaseModel):
    """The tenant's ownership policy."""

    model_config = ConfigDict(extra="forbid")

    unowned_findings_team: Optional[PolicyTeam] = Field(
        default=None,
        description="Catch-all team for findings on entities with no confirmed owner; null when none.",
    )
    require_owner_to_publish: bool = Field(
        description="When true, a version of a project with no confirmed owner cannot be published."
    )


class OwnershipPolicyInput(BaseModel):
    """A policy change. Omitted fields are left alone; ``unowned_findings_team: null`` clears it."""

    model_config = ConfigDict(extra="forbid")

    unowned_findings_team: Optional[str] = Field(default=None, max_length=128, description="A team slug.")
    require_owner_to_publish: Optional[bool] = None


def _iso(value: Any) -> Optional[str]:
    """ISO-8601 for a timestamp; strings and ``None`` pass through."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


_POLICY_SQL = """
    SELECT tn.require_owner_to_publish,
           t.id::text AS team_id, t.slug AS team_slug, t.name AS team_name,
           (t.deleted_at IS NOT NULL) AS team_deleted,
           (SELECT count(*)::int FROM apiome.team_members m WHERE m.team_id = t.id) AS team_members
    FROM apiome.tenants tn
    LEFT JOIN apiome.teams t ON t.id = tn.unowned_findings_team_id
    WHERE tn.id = %s::uuid
"""


def _policy_from_row(row: Optional[Dict[str, Any]]) -> OwnershipPolicy:
    """Build the policy from a ``_POLICY_SQL`` row (no row reads as the defaults)."""
    if not row:
        return OwnershipPolicy(require_owner_to_publish=False)
    team = None
    if row.get("team_id"):
        team = PolicyTeam(
            id=str(row["team_id"]),
            slug=row["team_slug"],
            name=row["team_name"],
            deleted=bool(row.get("team_deleted")),
            member_count=int(row.get("team_members") or 0),
        )
    return OwnershipPolicy(
        unowned_findings_team=team, require_owner_to_publish=bool(row.get("require_owner_to_publish"))
    )


def read_policy(tenant_id: str) -> OwnershipPolicy:
    """The tenant's ownership policy.

    Args:
        tenant_id: The tenant.

    Returns:
        The policy; the defaults (no catch-all, gate off) for an unknown tenant.
    """
    if not is_uuid_string(tenant_id or ""):
        return OwnershipPolicy(require_owner_to_publish=False)
    rows = db.execute_query(_POLICY_SQL, (tenant_id,))
    return _policy_from_row(dict(rows[0]) if rows else None)


def update_policy(tenant_id: str, change: OwnershipPolicyInput, *, actor: ConsumerActor) -> OwnershipPolicy:
    """Change the policy, audited as ``ownership_policy.update`` in the same transaction.

    Args:
        tenant_id: The tenant.
        change: The fields to change (``model_fields_set`` decides which).
        actor: Who changed it.

    Returns:
        The policy after the change.

    Raises:
        OwnershipPolicyError: ``ownership-policy-team-not-found`` when the catch-all slug names no
            live team in the tenant.
    """
    provided = change.model_fields_set

    def work(cursor: Any) -> OwnershipPolicy:
        cursor.execute(_POLICY_SQL, (tenant_id,))
        before = _policy_from_row(cursor.fetchone())
        assignments: List[str] = []
        params: List[Any] = []
        if "unowned_findings_team" in provided:
            slug = (change.unowned_findings_team or "").strip().lower()
            team_id = None
            if slug:
                cursor.execute(
                    """
                    SELECT id::text AS id FROM apiome.teams
                    WHERE tenant_id = %s::uuid AND slug = %s AND deleted_at IS NULL
                    """,
                    (tenant_id, slug),
                )
                found = cursor.fetchone()
                if not found:
                    raise OwnershipPolicyError(CODE_TEAM_NOT_FOUND, f"no team '{slug}' in this tenant")
                team_id = found["id"]
            assignments.append("unowned_findings_team_id = %s::uuid")
            params.append(team_id)
        if "require_owner_to_publish" in provided and change.require_owner_to_publish is not None:
            assignments.append("require_owner_to_publish = %s")
            params.append(bool(change.require_owner_to_publish))
        if assignments:
            cursor.execute(
                f"UPDATE apiome.tenants SET {', '.join(assignments)} WHERE id = %s::uuid",
                (*params, tenant_id),
            )
        cursor.execute(_POLICY_SQL, (tenant_id,))
        after = _policy_from_row(cursor.fetchone())
        if after != before:
            db._append_access_audit(
                cursor,
                tenant_id=tenant_id,
                action="ownership_policy.update",
                actor_id=actor.user_id,
                actor_label=actor.label,
                target="ownership-policy",
                source="api_key" if actor.kind == "api_key" else "web",
                detail={
                    "from": before.model_dump(mode="json"),
                    "to": after.model_dump(mode="json"),
                },
            )
        return after

    return db._guarded_tx(work)


# ---------------------------------------------------------------------------------------------
# The owner gate
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class OwnerGateAssessment:
    """The owner gate's verdict for one publish.

    Attributes:
        status: ``disabled``, ``satisfied`` or ``blocked``.
        team_slug: The confirmed owner, when there is one.
        team_name: Its display name.
    """

    status: str
    team_slug: Optional[str] = None
    team_name: Optional[str] = None

    @property
    def blocked(self) -> bool:
        """True when publish must be refused."""
        return self.status == GATE_BLOCKED

    def message(self) -> str:
        """One sentence for the publish dialog and the refusal."""
        if self.status == GATE_DISABLED:
            return "The owner gate is off: publishing does not require an owner team."
        if self.status == GATE_SATISFIED:
            return f"Owned by {self.team_name or self.team_slug}."
        return "This project has no confirmed owner team, and the workspace requires one to publish."

    def as_payload(self) -> Dict[str, Any]:
        """The camelCase payload the publish response and the 422 carry."""
        payload: Dict[str, Any] = {"status": self.status, "message": self.message()}
        if self.blocked:
            payload["reason"] = REASON_NO_OWNER
        if self.team_slug:
            payload["team"] = {"slug": self.team_slug, "name": self.team_name}
        return payload


def assess_owner_gate(*, tenant_id: str, project_id: str) -> OwnerGateAssessment:
    """Assess the ``require_owner_to_publish`` gate for a project.

    A confirmed owner whose team was deleted does not count: that team receives nothing.

    Args:
        tenant_id: The tenant.
        project_id: The project being published.

    Returns:
        The verdict — ``disabled`` when the tenant has not turned the gate on.
    """
    if not is_uuid_string(tenant_id or "") or not is_uuid_string(project_id or ""):
        return OwnerGateAssessment(status=GATE_DISABLED)
    rows = db.execute_query(
        """
        SELECT tn.require_owner_to_publish, own.slug, own.name
        FROM apiome.tenants tn
        LEFT JOIN LATERAL (
            SELECT t.slug, t.name
            FROM apiome.entity_owners eo
            JOIN apiome.teams t ON t.id = eo.team_id AND t.deleted_at IS NULL
            WHERE eo.tenant_id = tn.id AND eo.entity_id = %s::uuid
              AND eo.entity_kind IN ('project', 'catalog_item') AND eo.status = 'confirmed'
            LIMIT 1
        ) own ON TRUE
        WHERE tn.id = %s::uuid
        """,
        (project_id, tenant_id),
    )
    row = dict(rows[0]) if rows else {}
    if not row.get("require_owner_to_publish"):
        return OwnerGateAssessment(status=GATE_DISABLED, team_slug=row.get("slug"), team_name=row.get("name"))
    if row.get("slug"):
        return OwnerGateAssessment(status=GATE_SATISFIED, team_slug=row["slug"], team_name=row.get("name"))
    return OwnerGateAssessment(status=GATE_BLOCKED)


# ---------------------------------------------------------------------------------------------
# Ownership drift
# ---------------------------------------------------------------------------------------------

#: The display name of an owned entity, read in the same statement.
_ENTITY_NAME_SQL = """
    COALESCE(
        CASE eo.entity_kind
            WHEN 'project' THEN (SELECT p.name FROM apiome.projects p WHERE p.id = eo.entity_id)
            WHEN 'catalog_item' THEN (SELECT p.name FROM apiome.projects p WHERE p.id = eo.entity_id)
            WHEN 'mcp_endpoint' THEN (SELECT m.name FROM apiome.mcp_endpoints m WHERE m.id = eo.entity_id)
            WHEN 'consumer' THEN (SELECT c.name FROM apiome.consumer c WHERE c.id = eo.entity_id)
            WHEN 'connector' THEN (SELECT k.name FROM apiome.catalog_connectors k WHERE k.id = eo.entity_id)
        END,
        eo.entity_id::text
    )
"""

DriftReason = Literal["deleted_team", "empty_team", "stale_suggestion"]


def ownership_drift(tenant_id: str) -> Dict[str, Any]:
    """Entities whose ownership has quietly stopped working.

    * ``deleted_team`` — the confirmed owner is a team that was deleted (without ``reassign_to``
      moving its entities, e.g. one deleted before CDG-2.2's guard), so findings reach nobody;
    * ``empty_team`` — the confirmed owner team has no members, so its notifications reach nobody;
    * ``stale_suggestion`` — a suggested owner nobody has confirmed for :data:`STALE_SUGGESTION_DAYS`
      days, on an entity that still has no confirmed owner.

    Args:
        tenant_id: The tenant.

    Returns:
        ``{"items": [...], "counts": {reason: n}, "stale_after_days": 30}``; each item has
        ``reason``, ``entity_kind``, ``entity_id``, ``entity_name``, ``team`` (slug, name) and
        ``since``.
    """
    if not is_uuid_string(tenant_id or ""):
        return {"items": [], "counts": {}, "stale_after_days": STALE_SUGGESTION_DAYS}
    rows = db.execute_query(
        f"""
        WITH drift AS (
            SELECT CASE WHEN t.deleted_at IS NOT NULL THEN 'deleted_team' ELSE 'empty_team' END AS reason,
                   eo.entity_kind, eo.entity_id, t.slug AS team_slug, t.name AS team_name,
                   COALESCE(t.deleted_at, eo.confirmed_at) AS since,
                   {_ENTITY_NAME_SQL} AS entity_name
            FROM apiome.entity_owners eo
            JOIN apiome.teams t ON t.id = eo.team_id
            WHERE eo.tenant_id = %s::uuid AND eo.status = 'confirmed'
              AND (t.deleted_at IS NOT NULL
                   OR NOT EXISTS (SELECT 1 FROM apiome.team_members m WHERE m.team_id = t.id))
            UNION ALL
            SELECT 'stale_suggestion', eo.entity_kind, eo.entity_id, t.slug, t.name, eo.created_at,
                   {_ENTITY_NAME_SQL}
            FROM apiome.entity_owners eo
            JOIN apiome.teams t ON t.id = eo.team_id AND t.deleted_at IS NULL
            WHERE eo.tenant_id = %s::uuid AND eo.status = 'suggested'
              AND eo.created_at < CURRENT_TIMESTAMP - make_interval(days => %s)
              AND NOT EXISTS (
                  SELECT 1 FROM apiome.entity_owners c
                  WHERE c.tenant_id = eo.tenant_id AND c.entity_kind = eo.entity_kind
                    AND c.entity_id = eo.entity_id AND c.status = 'confirmed'
              )
        ),
        ranked AS (
            SELECT drift.*, row_number() OVER (PARTITION BY reason ORDER BY since, entity_id) AS rn,
                   count(*) OVER (PARTITION BY reason) AS reason_total
            FROM drift
        )
        SELECT reason, entity_kind, entity_id::text AS entity_id, entity_name, team_slug, team_name,
               since, reason_total
        FROM ranked
        WHERE rn <= %s
        ORDER BY reason, since, entity_id
        """,
        (tenant_id, tenant_id, STALE_SUGGESTION_DAYS, _DRIFT_LIMIT),
    )
    counts: Dict[str, int] = {}
    items = []
    for row in rows:
        counts[row["reason"]] = int(row.get("reason_total") or 0)
        items.append(
            {
                "reason": row["reason"],
                "entity_kind": row["entity_kind"],
                "entity_id": row["entity_id"],
                "entity_name": row.get("entity_name"),
                "team": {"slug": row.get("team_slug"), "name": row.get("team_name")},
                "since": _iso(row.get("since")),
            }
        )
    return {"items": items, "counts": counts, "stale_after_days": STALE_SUGGESTION_DAYS}


# ---------------------------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------------------------


def owner_facts(tenant_id: str, kind: str, entity_id: str) -> Dict[str, bool]:
    """The ``owner.*`` facts GVM-1.x ladders read (through CDG-5.4 once it lands).

    * ``owner.present`` — the entity has a confirmed owner team that has not been deleted;
    * ``owner.contactable`` — that team has an ``oncall_url`` or a ``chat_url``.

    Args:
        tenant_id: The tenant.
        kind: The entity kind (a projects row may be named ``project`` or ``catalog_item``).
        entity_id: The entity.

    Returns:
        ``{"owner.present": bool, "owner.contactable": bool}``.
    """
    facts = {"owner.present": False, "owner.contactable": False}
    if not is_uuid_string(tenant_id or "") or not is_uuid_string(entity_id or ""):
        return facts
    kinds = ["project", "catalog_item"] if kind in ("project", "catalog_item") else [kind]
    rows = db.execute_query(
        """
        SELECT (t.oncall_url IS NOT NULL OR t.chat_url IS NOT NULL) AS contactable
        FROM apiome.entity_owners eo
        JOIN apiome.teams t ON t.id = eo.team_id AND t.deleted_at IS NULL
        WHERE eo.tenant_id = %s::uuid AND eo.entity_id = %s::uuid
          AND eo.entity_kind = ANY(%s::text[]) AND eo.status = 'confirmed'
        LIMIT 1
        """,
        (tenant_id, entity_id, kinds),
    )
    if rows:
        facts["owner.present"] = True
        facts["owner.contactable"] = bool(rows[0].get("contactable"))
    return facts
