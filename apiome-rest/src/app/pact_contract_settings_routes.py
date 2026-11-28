"""``/v1/tenants/{tenant_slug}/pact-contract-settings`` — Contracts commit-status and agent switches, PFX-8.15 (#7312).

The HTTP face of :mod:`app.pact_contract_settings`, for the Contracts **Settings** page's **CI and
commit statuses** and **Agents** tabs:

* ``GET …/pact-contract-settings`` — both groups of switches and whether the caller may change them
  (``pacts:view``);
* ``PUT …/pact-contract-settings/commit-statuses`` — the three commit-status switches
  (``pacts:delete``);
* ``PUT …/pact-contract-settings/agents`` — the four agent switches (``pacts:delete``).

A ``PUT`` replaces its group; an unknown field is refused (422) with its name, never ignored. The
tenant is always the authenticated one, never the URL's.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from .auth import validate_authentication
from .consumer_contract_store import actor_from_auth
from .database import db
from .pact_contract_settings import (
    AgentSettings,
    CommitStatusSettings,
    ContractSettings,
    read_settings,
    save_agents,
    save_commit_statuses,
)
from .permissions import Action, Resource, enforce_permission, has_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pacticipants"])

_BASE = "/{tenant_slug}/pact-contract-settings"


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


@router.get(
    _BASE,
    response_model=ContractSettings,
    summary="Read the Contracts commit-status and agent switches",
    description=(
        "The **CI and commit statuses** switches — a verdict on the consumer's commit, on the provider's "
        "commit, and whether bi-directional verdicts set statuses and fire webhooks — and the **Agents** "
        "switches: what an MCP-connected agent may do with contracts (read, draft, publish, record a "
        "deployment). `configured: false` shows the defaults. `can_edit` says whether the caller may change "
        "them (`pacts:delete`).\n\nRequires `pacts:view`."
    ),
)
def read_contract_settings(
    tenant_slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> ContractSettings:
    """Read the switches.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is used).
        auth_data: The authenticated principal.

    Returns:
        Both groups of switches.

    Raises:
        HTTPException: 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    _ = tenant_slug
    can_edit = bool(has_permission(db, auth_data, Resource.PACTS, Action.DELETE))
    return read_settings(db.execute_query, _tenant_id(auth_data), can_edit=can_edit)


@router.put(
    f"{_BASE}/commit-statuses",
    response_model=ContractSettings,
    summary="Save the commit-status switches",
    description=(
        "Replace the three switches. A status a switch keeps from being written is still recorded, as "
        "`suppressed` with reason `pact-status-switched-off`, in `GET …/pact-commit-statuses`. Turning on "
        "`bidirectional` makes each new bi-directional verdict set its statuses and fire its "
        "`provider_verification_*` webhooks.\n\nRequires `pacts:delete`."
    ),
)
def save_contract_commit_statuses(
    tenant_slug: str,
    body: CommitStatusSettings,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ContractSettings:
    """Save the commit-status switches.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is used).
        body: The switches.
        auth_data: The authenticated principal.

    Returns:
        Both groups of switches as stored.

    Raises:
        HTTPException: 403 without ``pacts:delete``; 422 for an unknown field.
    """
    user_id = enforce_permission(
        db, auth_data, Resource.PACTS, Action.DELETE, target="pact-contract-settings/commit-statuses"
    )
    _ = tenant_slug
    return save_commit_statuses(db, _tenant_id(auth_data), body, actor=actor_from_auth(auth_data, user_id))


@router.put(
    f"{_BASE}/agents",
    response_model=ContractSettings,
    summary="Save what MCP agents may do with contracts",
    description=(
        "Replace the four agent switches. An MCP pact tool whose action is switched off is refused with "
        "`403 mcp-pact-agent-action-off` and the reason, and the refusal is audited (`pacts.agent.refused`). "
        "Whatever the switches say, an agent never records a deployment to an environment marked production. "
        "No agent tool drafts or publishes yet: those two switches apply when one ships.\n\nRequires `pacts:delete`."
    ),
)
def save_contract_agents(
    tenant_slug: str,
    body: AgentSettings,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ContractSettings:
    """Save the agent switches.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is used).
        body: The switches.
        auth_data: The authenticated principal.

    Returns:
        Both groups of switches as stored.

    Raises:
        HTTPException: 403 without ``pacts:delete``; 422 for an unknown field.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.DELETE, target="pact-contract-settings/agents")
    _ = tenant_slug
    return save_agents(db, _tenant_id(auth_data), body, actor=actor_from_auth(auth_data, user_id))
