"""Agent and model entities — REST — CDG-5.2 (#5980).

Under ``/v1/tenants/{tenant_slug}``:

* ``GET|POST /catalog-agents`` · ``GET|PATCH|DELETE /catalog-agents/{slug}``
* ``PUT|DELETE /catalog-agents/{slug}/keys/{key_id}`` — link or unlink an agent key (AGX-3.1)
* ``GET|POST /catalog-models`` · ``GET|PATCH|DELETE /catalog-models/{slug}``

An agent is a consumer, so the routes use the ``consumer_contracts`` RBAC resource: ``view`` to
read, ``create`` / ``edit`` / ``delete`` to change. Linking a key also needs ``api_keys:view``.
Responses carry an agent key's name, prefix and status — never its secret or hash. Every write is
audited on the tenant's access audit (``catalog.agent.*`` / ``catalog.model.*``).
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Response

from . import catalog_agent_store as store
from .auth import validate_authentication
from .catalog_agents import (
    CODE_AGENT_NOT_FOUND,
    CODE_AGENT_SLUG_TAKEN,
    CODE_KEY_NOT_LINKED,
    CODE_KEY_TAKEN,
    CODE_MODEL_NOT_FOUND,
    CODE_MODEL_SLUG_TAKEN,
    AgentInput,
    AgentList,
    AgentOut,
    AgentPatch,
    CatalogAgentError,
    ModelInput,
    ModelList,
    ModelOut,
    ModelPatch,
)
from .consumer_contract_store import ConsumerValidationError, actor_from_auth
from .database import db
from .permissions import Action, Resource, enforce_permission

router = APIRouter(prefix="/v1/tenants", tags=["catalog-agents"])

_AGENTS = "/{tenant_slug}/catalog-agents"
_MODELS = "/{tenant_slug}/catalog-models"

#: Refusal code → HTTP status (anything else is a 400).
_STATUS = {
    CODE_AGENT_NOT_FOUND: 404,
    CODE_MODEL_NOT_FOUND: 404,
    CODE_KEY_NOT_LINKED: 404,
    CODE_AGENT_SLUG_TAKEN: 409,
    CODE_MODEL_SLUG_TAKEN: 409,
    CODE_KEY_TAKEN: 409,
}


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _http(exc: Exception) -> HTTPException:
    """Translate a refusal into ``{code, message}`` with its status."""
    code = getattr(exc, "code", "agent-invalid")
    return HTTPException(status_code=_STATUS.get(code, 400), detail={"code": code, "message": str(exc)})


def _permit(auth_data: Dict[str, Any], action: str, target: str) -> Any:
    """Require ``consumer_contracts:<action>`` and return the actor."""
    user_id = enforce_permission(db, auth_data, Resource.CONSUMER_CONTRACTS, action, target=target)
    return actor_from_auth(auth_data, user_id)


# ---------------------------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------------------------


@router.get(_AGENTS, response_model=AgentList, response_model_by_alias=True, summary="List agents")
async def list_catalog_agents(
    tenant_slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> AgentList:
    """The tenant's live agents with their model (and its deprecation) and owner (`consumer_contracts:view`)."""
    _ = tenant_slug
    _permit(auth_data, Action.VIEW, "catalog-agents")
    return AgentList(agents=store.list_agents(_tenant_id(auth_data)))


@router.post(
    _AGENTS, response_model=AgentOut, response_model_by_alias=True, status_code=201, summary="Register an agent"
)
async def create_catalog_agent(
    tenant_slug: str, body: AgentInput, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> AgentOut:
    """Register an agent, optionally with its agent keys (`consumer_contracts:create`, plus `api_keys:view` for keys).

    The agent becomes a consumer of every project its keys' toolsets reach, with a contract (source
    `agent`) holding the operations those keys may call; the graph derives one `consumes` edge per
    operation. `slug` is derived from `name` when omitted. A key must be a live agent key of the
    workspace that no other agent uses (409 `agent-key-taken`).
    """
    _ = tenant_slug
    actor = _permit(auth_data, Action.CREATE, body.slug or body.name)
    if body.key_ids:
        enforce_permission(db, auth_data, Resource.API_KEYS, Action.VIEW, target="catalog-agents")
    try:
        return store.create_agent(_tenant_id(auth_data), body, actor=actor)
    except (CatalogAgentError, ConsumerValidationError) as exc:
        raise _http(exc) from exc


@router.get(_AGENTS + "/{slug}", response_model=AgentOut, response_model_by_alias=True, summary="Read an agent")
async def read_catalog_agent(
    tenant_slug: str, slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> AgentOut:
    """One agent: model, owner, keys (prefix and status only), and the consumer it is per project."""
    _ = tenant_slug
    _permit(auth_data, Action.VIEW, f"agent:{slug}")
    try:
        return store.get_agent(_tenant_id(auth_data), slug)
    except CatalogAgentError as exc:
        raise _http(exc) from exc


@router.patch(_AGENTS + "/{slug}", response_model=AgentOut, response_model_by_alias=True, summary="Change an agent")
async def update_catalog_agent(
    tenant_slug: str, slug: str, body: AgentPatch, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> AgentOut:
    """Change an agent's name, description, runtime, model (`null` clears it) or status (`consumer_contracts:edit`).

    Retiring an agent (`status: retired`) records empty contracts, so its `consumes` edges go stale.
    """
    _ = tenant_slug
    actor = _permit(auth_data, Action.EDIT, f"agent:{slug}")
    try:
        return store.update_agent(_tenant_id(auth_data), slug, body, actor=actor)
    except (CatalogAgentError, ConsumerValidationError) as exc:
        raise _http(exc) from exc


@router.delete(_AGENTS + "/{slug}", status_code=204, summary="Delete an agent")
async def delete_catalog_agent(
    tenant_slug: str, slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Response:
    """Soft-delete an agent (`consumer_contracts:delete`); its contracts are emptied and its edges go stale."""
    _ = tenant_slug
    actor = _permit(auth_data, Action.DELETE, f"agent:{slug}")
    try:
        store.delete_agent(_tenant_id(auth_data), slug, actor=actor)
    except (CatalogAgentError, ConsumerValidationError) as exc:
        raise _http(exc) from exc
    return Response(status_code=204)


@router.put(
    _AGENTS + "/{slug}/keys/{key_id}",
    response_model=AgentOut,
    response_model_by_alias=True,
    summary="Link an agent key",
)
async def link_catalog_agent_key(
    tenant_slug: str, slug: str, key_id: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> AgentOut:
    """Add an agent key to the agent and re-derive its consumers (`consumer_contracts:edit` + `api_keys:view`)."""
    _ = tenant_slug
    actor = _permit(auth_data, Action.EDIT, f"agent:{slug}")
    enforce_permission(db, auth_data, Resource.API_KEYS, Action.VIEW, target=f"agent:{slug}")
    try:
        return store.link_key(_tenant_id(auth_data), slug, key_id, actor=actor)
    except (CatalogAgentError, ConsumerValidationError) as exc:
        raise _http(exc) from exc


@router.delete(
    _AGENTS + "/{slug}/keys/{key_id}",
    response_model=AgentOut,
    response_model_by_alias=True,
    summary="Unlink an agent key",
)
async def unlink_catalog_agent_key(
    tenant_slug: str, slug: str, key_id: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> AgentOut:
    """Remove an agent key from the agent (`consumer_contracts:edit`); what only it allowed goes stale."""
    _ = tenant_slug
    actor = _permit(auth_data, Action.EDIT, f"agent:{slug}")
    try:
        return store.unlink_key(_tenant_id(auth_data), slug, key_id, actor=actor)
    except (CatalogAgentError, ConsumerValidationError) as exc:
        raise _http(exc) from exc


# ---------------------------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------------------------


@router.get(_MODELS, response_model=ModelList, response_model_by_alias=True, summary="List models")
async def list_catalog_models(
    tenant_slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> ModelList:
    """The tenant's live models with their deprecation and owner (`consumer_contracts:view`)."""
    _ = tenant_slug
    _permit(auth_data, Action.VIEW, "catalog-models")
    return ModelList(models=store.list_models(_tenant_id(auth_data)))


@router.post(
    _MODELS, response_model=ModelOut, response_model_by_alias=True, status_code=201, summary="Register a model"
)
async def create_catalog_model(
    tenant_slug: str, body: ModelInput, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> ModelOut:
    """Register a model: provider, name and version, hosting (`api` or `self_hosted`), data handling, deprecation."""
    _ = tenant_slug
    actor = _permit(auth_data, Action.CREATE, body.slug or body.model_name)
    try:
        return store.create_model(_tenant_id(auth_data), body, actor=actor)
    except CatalogAgentError as exc:
        raise _http(exc) from exc


@router.get(_MODELS + "/{slug}", response_model=ModelOut, response_model_by_alias=True, summary="Read a model")
async def read_catalog_model(
    tenant_slug: str, slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> ModelOut:
    """One model with the live agents that run on it."""
    _ = tenant_slug
    _permit(auth_data, Action.VIEW, f"model:{slug}")
    try:
        return store.get_model(_tenant_id(auth_data), slug)
    except CatalogAgentError as exc:
        raise _http(exc) from exc


@router.patch(_MODELS + "/{slug}", response_model=ModelOut, response_model_by_alias=True, summary="Change a model")
async def update_catalog_model(
    tenant_slug: str, slug: str, body: ModelPatch, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> ModelOut:
    """Change a model (`consumer_contracts:edit`); `deprecatedAt` shows on every agent that runs on it."""
    _ = tenant_slug
    actor = _permit(auth_data, Action.EDIT, f"model:{slug}")
    try:
        return store.update_model(_tenant_id(auth_data), slug, body, actor=actor)
    except CatalogAgentError as exc:
        raise _http(exc) from exc


@router.delete(_MODELS + "/{slug}", status_code=204, summary="Delete a model")
async def delete_catalog_model(
    tenant_slug: str, slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Response:
    """Soft-delete a model (`consumer_contracts:delete`); agents that ran on it show no model."""
    _ = tenant_slug
    actor = _permit(auth_data, Action.DELETE, f"model:{slug}")
    try:
        store.delete_model(_tenant_id(auth_data), slug, actor=actor)
    except CatalogAgentError as exc:
        raise _http(exc) from exc
    return Response(status_code=204)
