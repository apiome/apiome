"""A workspace's Contracts commit-status and agent switches — PFX-8.15 (#7312).

The Contracts **Settings** page's **CI and commit statuses** and **Agents** tabs store their switches
in ``pact_contract_settings`` (apiome-db V457; no row = the defaults here):

* **Commit statuses** — whether a pact verdict is written on the consumer's commit
  (``consumer_commit``, on), on the provider's commit (``provider_commit``, on), and whether a
  bi-directional verdict sets statuses and fires its webhooks at all (``bidirectional``, off). A
  status a switch keeps from being written is still recorded, as ``suppressed`` with the reason
  (:mod:`app.pact_commit_status_store`), so nothing disappears without a trace.
* **Agents** — what an MCP-connected agent may do with contracts: ``read`` (on), ``draft`` (on),
  ``publish`` (off) and ``record`` (off). ``app.mcp_pact_routes`` refuses a switched-off action
  with the reason and audits the refusal. Whatever the switch says, an agent never records a
  deployment to an environment marked production and never publishes on a main branch.

Reading needs ``pacts:view``; changing a switch needs ``pacts:delete`` (the Contracts admin
permission: Owner and Admin). Every change appends one ``access_audit`` row in its transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from .consumer_contract_store import ConsumerActor
from .pact_cleanup_store import audit_tx
from .revision_deprecation import is_uuid_string

__all__ = [
    "AGENT_ACTIONS",
    "AgentSettings",
    "CommitStatusSettings",
    "ContractSettings",
    "read_settings",
    "save_agents",
    "save_commit_statuses",
    "settings_from_row",
]

#: The agent actions, as the switches name them, and how a refusal names each.
AGENT_ACTIONS: Dict[str, str] = {
    "read": "reading pacts, verdicts and can-i-deploy",
    "draft": "drafting a pact",
    "publish": "publishing pacts and provider contracts",
    "record": "recording deployments",
}


class CommitStatusSettings(BaseModel):
    """The **CI and commit statuses** switches (``PUT …/pact-contract-settings/commit-statuses``)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    consumer_commit: bool = Field(
        default=True,
        description="Write pact verdicts (awaiting verification, verified, failed) on the consumer's commit.",
    )
    provider_commit: bool = Field(default=True, description="Write verification verdicts on the provider's commit.")
    bidirectional: bool = Field(
        default=False,
        description="Bi-directional verdicts set commit statuses and fire their webhooks, as a verification does.",
    )


class AgentSettings(BaseModel):
    """The **Agents** switches (``PUT …/pact-contract-settings/agents``)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    read: bool = Field(default=True, description="Agents may read pacts, verdicts and can-i-deploy.")
    draft: bool = Field(
        default=True,
        examples=[True],
        description=(
            "Agents may draft a pact for a person to review. No agent tool drafts yet; it applies when one ships."
        ),
    )
    publish: bool = Field(
        default=False,
        description=(
            "Agents may publish pacts and provider contracts, never on a main branch. No agent tool publishes yet; "
            "it applies when one ships."
        ),
    )
    record: bool = Field(
        default=False, description="Agents may record deployments, never to an environment marked production."
    )


class ContractSettings(BaseModel):
    """``GET …/pact-contract-settings``: both groups of switches."""

    model_config = ConfigDict(extra="forbid")

    commit_statuses: CommitStatusSettings
    agents: AgentSettings
    configured: bool = Field(description="Whether the workspace saved any switch; `false` shows the defaults.")
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    can_edit: bool = Field(description="Whether the caller may change the switches (`pacts:delete`).")


_COLUMNS = """
    status_consumer_commit, status_provider_commit, status_bidirectional,
    agent_read, agent_draft, agent_publish, agent_record, updated_by_label, updated_at
"""

_READ = f"SELECT {_COLUMNS} FROM apiome.pact_contract_settings WHERE tenant_id = %s::uuid"


def _iso(value: Any) -> Optional[str]:
    """ISO-8601 text of a timestamp column, or ``None``."""
    return value.isoformat() if isinstance(value, datetime) else (str(value) if value is not None else None)


def settings_from_row(row: Optional[Mapping[str, Any]], *, can_edit: bool = False) -> ContractSettings:
    """The settings stored in a row, or the defaults when there is none.

    Args:
        row: A ``pact_contract_settings`` row, or ``None``.
        can_edit: Copied to the answer.

    Returns:
        The settings.
    """
    if not row:
        return ContractSettings(
            commit_statuses=CommitStatusSettings(), agents=AgentSettings(), configured=False, can_edit=can_edit
        )
    return ContractSettings(
        commit_statuses=CommitStatusSettings(
            consumer_commit=bool(row.get("status_consumer_commit")),
            provider_commit=bool(row.get("status_provider_commit")),
            bidirectional=bool(row.get("status_bidirectional")),
        ),
        agents=AgentSettings(
            read=bool(row.get("agent_read")),
            draft=bool(row.get("agent_draft")),
            publish=bool(row.get("agent_publish")),
            record=bool(row.get("agent_record")),
        ),
        configured=True,
        updated_at=_iso(row.get("updated_at")),
        updated_by=row.get("updated_by_label"),
        can_edit=can_edit,
    )


def read_settings(fetch: Any, tenant_id: str, *, can_edit: bool = False) -> ContractSettings:
    """The tenant's switches, or the defaults.

    Args:
        fetch: The database's ``execute_query``, or a cursor-backed callable of that shape.
        tenant_id: The tenant.
        can_edit: Copied to the answer.

    Returns:
        The settings. A malformed tenant id reads the defaults.
    """
    if not is_uuid_string(str(tenant_id or "")):
        return settings_from_row(None, can_edit=can_edit)
    rows = fetch(_READ, (tenant_id,)) or []
    return settings_from_row(dict(rows[0]) if rows else None, can_edit=can_edit)


def _save(
    db: Any,
    tenant_id: str,
    columns: Dict[str, bool],
    *,
    actor: ConsumerActor,
    action: str,
    target: str,
) -> ContractSettings:
    """Upsert some switches of the tenant's row (the others keep their value or default)."""
    user_id = actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None
    names = list(columns)
    placeholders = ", ".join(["%s"] * len(names))
    updates = ", ".join(f"{name} = EXCLUDED.{name}" for name in names)
    query = f"""
        INSERT INTO apiome.pact_contract_settings (tenant_id, {", ".join(names)}, updated_by, updated_by_label,
                                                   updated_at)
        VALUES (%s::uuid, {placeholders}, %s::uuid, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (tenant_id) DO UPDATE SET {updates}, updated_by = EXCLUDED.updated_by,
            updated_by_label = EXCLUDED.updated_by_label, updated_at = CURRENT_TIMESTAMP
        RETURNING {_COLUMNS}
    """

    def work(cursor: Any) -> Dict[str, Any]:
        cursor.execute(query, (tenant_id, *columns.values(), user_id, actor.label))
        row = dict(cursor.fetchone())
        audit_tx(db, cursor, tenant_id, action, actor, target, dict(columns))
        return row

    return settings_from_row(db._guarded_tx(work), can_edit=True)


def save_commit_statuses(
    db: Any, tenant_id: str, body: CommitStatusSettings, *, actor: ConsumerActor
) -> ContractSettings:
    """Save the commit-status switches, audited as ``pacts.settings.commit_statuses``.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        body: The three switches.
        actor: Who is saving them.

    Returns:
        Both groups of switches as stored.
    """
    return _save(
        db,
        tenant_id,
        {
            "status_consumer_commit": body.consumer_commit,
            "status_provider_commit": body.provider_commit,
            "status_bidirectional": body.bidirectional,
        },
        actor=actor,
        action="pacts.settings.commit_statuses",
        target="pact-contract-settings/commit-statuses",
    )


def save_agents(db: Any, tenant_id: str, body: AgentSettings, *, actor: ConsumerActor) -> ContractSettings:
    """Save the agent switches, audited as ``pacts.settings.agents``.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        body: The four switches.
        actor: Who is saving them.

    Returns:
        Both groups of switches as stored.
    """
    return _save(
        db,
        tenant_id,
        {
            "agent_read": body.read,
            "agent_draft": body.draft,
            "agent_publish": body.publish,
            "agent_record": body.record,
        },
        actor=actor,
        action="pacts.settings.agents",
        target="pact-contract-settings/agents",
    )
