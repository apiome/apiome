"""Agent key endpoints — AGX-3.1 (#4537).

Five routes over agent keys (:mod:`app.agent_keys`), the MCP credential an agent holds:

```
GET    /v1/tenants/{t}/agent-keys                 list (?toolsetId=…, ?includeRevoked=true)
POST   /v1/tenants/{t}/agent-keys                 create; returns the secret once
GET    /v1/tenants/{t}/agent-keys/{id}            describe one
PUT    /v1/tenants/{t}/agent-keys/{id}/allowlist  replace the tool allowlist
DELETE /v1/tenants/{t}/agent-keys/{id}            revoke (idempotent)
```

**The secret is shown once**, in the create response. Every other response is metadata: name,
prefix, toolset, allowlist, status and timestamps, never the secret or its hash.

**Scoped by the authenticated tenant.** As on every ``/v1/tenants/{t}`` surface, the tenant in the
URL is informational; the caller's authenticated tenant scopes every read and write, so one
tenant can never address another's key by id. The toolset id is not yet checked against
``agent_toolsets``: that table is AGX-1.2 (#4530), which adds the foreign key and the check.

**Permissions reuse** ``api_keys``, **and no new RBAC resource is added**, as for the AGX-2.2
upstream credentials: listing and reading are ``api_keys:view``; create, allowlist edit and revoke
are ``api_keys:create`` / ``edit`` / ``delete``.

**Every lifecycle action is audited** in the tenant's access audit, with metadata only:
``agent.key.create``, ``agent.key.allowlist_update`` (the list before and after) and
``agent.key.revoke`` (once, however often a revoke is repeated).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from .agent_keys import (
    AGENT_KEY_SCHEMA_VERSION,
    CODE_AGENT_KEY_EXISTS,
    CODE_AGENT_KEY_NOT_FOUND,
    CODE_AGENT_KEY_REVOKED,
    AgentKeyAllowlistUpdate,
    AgentKeyCreate,
    AgentKeyCreated,
    AgentKeyError,
    AgentKeyOut,
    create_agent_key,
    get_agent_key,
    list_agent_keys,
    revoke_agent_key,
    update_agent_key_allowlist,
)
from .auth import validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_ALLOWLIST_UPDATE",
    "AUDIT_CREATE",
    "AUDIT_REVOKE",
    "AgentKeyListResponse",
    "router",
]

router = APIRouter(prefix="/v1/tenants", tags=["agent-access"])

#: Audit actions this module writes to ``apiome.access_audit``.
AUDIT_CREATE = "agent.key.create"
AUDIT_ALLOWLIST_UPDATE = "agent.key.allowlist_update"
AUDIT_REVOKE = "agent.key.revoke"

_BASE = "/{tenant_slug}/agent-keys"

#: HTTP status per refusal code; anything else is a 422.
_STATUS_BY_CODE = {
    CODE_AGENT_KEY_EXISTS: 409,
    CODE_AGENT_KEY_NOT_FOUND: 404,
    CODE_AGENT_KEY_REVOKED: 409,
}

_WHAT_IT_IS = (
    "An agent key is the credential an AI agent presents to Apiome's MCP agent runtime. It is "
    "bound to one agent toolset, may only list and call the tools named in its allowlist (and "
    "enabled in the toolset), and can expire. It is not a REST credential: the REST API refuses "
    "it on every route."
)

_METADATA_ONLY = (
    "Responses carry metadata only (name, prefix, toolset, allowlist, status, timestamps); the "
    "secret is returned once, by create, and never again."
)


class AgentKeyListResponse(BaseModel):
    """A tenant's agent keys, described.

    Attributes:
        schema_version: The projection's shape.
        keys: One entry per key, newest first.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(
        default=AGENT_KEY_SCHEMA_VERSION, serialization_alias="schemaVersion"
    )
    keys: List[AgentKeyOut]


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the authenticated tenant id, or refuse with 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this agent key.")
    return str(tenant_id)


def _refusal(exc: AgentKeyError) -> HTTPException:
    """Map a refusal onto its status, listing every problem."""
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(exc.code, 422),
        detail={"code": exc.code, "errors": list(exc.errors)},
    )


def _audit(
    *,
    tenant_id: str,
    action: str,
    auth_data: Dict[str, Any],
    actor_id: str,
    key: AgentKeyOut,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Write one metadata-only access-audit row (best-effort).

    An audit failure is logged and swallowed: a mutation that succeeded must not be reported as
    a failure because its audit row could not be appended.

    Args:
        tenant_id: The tenant the action belongs to.
        action: One of the ``AUDIT_*`` actions.
        auth_data: The authenticated principal.
        actor_id: The acting user id :func:`enforce_permission` resolved.
        key: The key acted on. Only its metadata is recorded; there is no secret on it to leak.
        extra: Action-specific detail merged into the row (e.g. the allowlist before and after).
    """
    detail: Dict[str, Any] = {
        "name": key.name,
        "keyPrefix": key.key_prefix,
        "toolsetId": key.toolset_id,
    }
    detail.update(extra or {})
    try:
        db.write_access_audit(
            tenant_id=tenant_id,
            action=action,
            actor_id=actor_id,
            actor_label=auth_data.get("user_email") or auth_data.get("user_name"),
            target=key.id,
            source="api",
            detail=detail,
        )
    except Exception:  # noqa: BLE001 - auditing never fails the governed action
        logger.warning("Failed to audit %s for tenant %s", action, tenant_id, exc_info=True)


@router.get(
    _BASE,
    response_model=AgentKeyListResponse,
    summary="List agent keys",
    description=(
        _WHAT_IT_IS + "\n\n" + _METADATA_ONLY + "\n\nNewest first. `toolsetId` narrows the list "
        "to one toolset's keys; revoked keys are left out unless `includeRevoked=true`.\n\n"
        "Requires `api_keys:view`."
    ),
)
async def list_agent_keys_route(
    tenant_slug: str,
    toolset_id: Optional[UUID] = Query(default=None, alias="toolsetId"),
    include_revoked: bool = Query(default=False, alias="includeRevoked"),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> AgentKeyListResponse:
    """List the tenant's agent keys.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is what scopes it).
        toolset_id: Optional toolset filter.
        include_revoked: Whether to include revoked keys.
        auth_data: The authenticated principal.

    Returns:
        The keys, as metadata.

    Raises:
        HTTPException: 403 without ``api_keys:view``.
    """
    enforce_permission(db, auth_data, Resource.API_KEYS, Action.VIEW)
    _ = tenant_slug
    return AgentKeyListResponse(
        keys=list_agent_keys(
            _tenant_id(auth_data),
            toolset_id=str(toolset_id) if toolset_id is not None else None,
            include_revoked=include_revoked,
        )
    )


@router.post(
    _BASE,
    response_model=AgentKeyCreated,
    status_code=201,
    summary="Create an agent key",
    description=(
        _WHAT_IT_IS + "\n\nThe body names the key, the `toolsetId` it is bound to, its "
        "`toolAllowlist` (MCP tool names, `^[A-Za-z0-9_-]{1,64}$`, at most 1024; no wildcard, and "
        "an empty list permits nothing) and an optional future `expiresAt`.\n\nThe response "
        "includes `secret` (`ak_…`): **it is shown only once**. Present it to the MCP agent runtime "
        "as `Authorization: Bearer <secret>`.\n\nRequires `api_keys:create`. Audited as "
        "`agent.key.create`."
    ),
    responses={
        409: {"description": "The tenant already has an API key with that name."},
        422: {"description": "A tool name, the name or the expiry is not acceptable."},
    },
)
async def create_agent_key_route(
    tenant_slug: str,
    body: AgentKeyCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> AgentKeyCreated:
    """Mint an agent key, then audit it.

    Args:
        tenant_slug: The tenant in the URL.
        body: The name, toolset, allowlist and optional expiry.
        auth_data: The authenticated principal.

    Returns:
        The key's metadata and its one-time secret.

    Raises:
        HTTPException: 403 without ``api_keys:create``; 409 when the name is taken; 422 on an
            invalid request.
    """
    actor_id = enforce_permission(db, auth_data, Resource.API_KEYS, Action.CREATE)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        created = create_agent_key(tenant_id, body, actor_id=actor_id)
    except AgentKeyError as exc:
        raise _refusal(exc) from exc
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_CREATE,
        auth_data=auth_data,
        actor_id=actor_id,
        key=created,
        extra={
            "toolAllowlist": list(created.tool_allowlist),
            "expiresAt": created.expires_at.isoformat() if created.expires_at else None,
        },
    )
    return created


@router.get(
    _BASE + "/{key_id}",
    response_model=AgentKeyOut,
    summary="Describe an agent key",
    description=(
        _METADATA_ONLY + " Revoked keys are described too, with `status: revoked`.\n\n"
        "Requires `api_keys:view`."
    ),
    responses={404: {"description": "No such agent key in this tenant."}},
)
async def get_agent_key_route(
    tenant_slug: str,
    key_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> AgentKeyOut:
    """Describe one agent key.

    Args:
        tenant_slug: The tenant in the URL.
        key_id: The key.
        auth_data: The authenticated principal.

    Returns:
        The key's metadata.

    Raises:
        HTTPException: 403 without ``api_keys:view``; 404 when it does not exist.
    """
    enforce_permission(db, auth_data, Resource.API_KEYS, Action.VIEW)
    _ = tenant_slug
    try:
        return get_agent_key(_tenant_id(auth_data), str(key_id))
    except AgentKeyError as exc:
        raise _refusal(exc) from exc


@router.put(
    _BASE + "/{key_id}/allowlist",
    response_model=AgentKeyOut,
    summary="Replace an agent key's tool allowlist",
    description=(
        "Replace the whole allowlist with `toolAllowlist`. The MCP runtime reads it on every "
        "request, so the agent's next `tools/list` shows the new set and its next `tools/call` "
        "is judged against it.\n\nRequires `api_keys:edit`. Audited as "
        "`agent.key.allowlist_update`, with the list before and after."
    ),
    responses={
        404: {"description": "No such agent key in this tenant."},
        409: {"description": "The key is revoked; its allowlist can no longer change."},
        422: {"description": "An entry is not an MCP tool name."},
    },
)
async def update_agent_key_allowlist_route(
    tenant_slug: str,
    key_id: UUID,
    body: AgentKeyAllowlistUpdate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> AgentKeyOut:
    """Replace a key's allowlist, then audit the change.

    Args:
        tenant_slug: The tenant in the URL.
        key_id: The key.
        body: The new allowlist.
        auth_data: The authenticated principal.

    Returns:
        The key's metadata after the change.

    Raises:
        HTTPException: 403 without ``api_keys:edit``; 404 when it does not exist; 409 when it is
            revoked; 422 on an invalid entry.
    """
    actor_id = enforce_permission(db, auth_data, Resource.API_KEYS, Action.EDIT)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        before, updated = update_agent_key_allowlist(tenant_id, str(key_id), body)
    except AgentKeyError as exc:
        raise _refusal(exc) from exc
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_ALLOWLIST_UPDATE,
        auth_data=auth_data,
        actor_id=actor_id,
        key=updated,
        extra={"before": before, "after": list(updated.tool_allowlist)},
    )
    return updated


@router.delete(
    _BASE + "/{key_id}",
    status_code=204,
    response_class=Response,
    summary="Revoke an agent key",
    description=(
        "Revoke the key. The MCP runtime checks the key on every request, so the agent's next "
        "request is refused. Revoking a revoked key is a no-op `204`; the key stays listable "
        "with `includeRevoked=true`.\n\nRequires `api_keys:delete`. Audited once as "
        "`agent.key.revoke`."
    ),
    responses={404: {"description": "No such agent key in this tenant."}},
)
async def revoke_agent_key_route(
    tenant_slug: str,
    key_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Revoke a key, then audit it (only the first time).

    Args:
        tenant_slug: The tenant in the URL.
        key_id: The key.
        auth_data: The authenticated principal.

    Returns:
        An empty ``204``.

    Raises:
        HTTPException: 403 without ``api_keys:delete``; 404 when it does not exist.
    """
    actor_id = enforce_permission(db, auth_data, Resource.API_KEYS, Action.DELETE)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        revoked, revoked_now = revoke_agent_key(tenant_id, str(key_id))
    except AgentKeyError as exc:
        raise _refusal(exc) from exc
    if revoked_now:
        _audit(
            tenant_id=tenant_id,
            action=AUDIT_REVOKE,
            auth_data=auth_data,
            actor_id=actor_id,
            key=revoked,
        )
    return Response(status_code=204)
