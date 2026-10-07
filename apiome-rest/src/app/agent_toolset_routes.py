"""Agent toolset endpoints — AGX-1.2 (#4530) and the AGX-1.3 (#4531) enrichment pass.

Eleven routes over agent toolsets (:mod:`app.agent_toolsets`): the curated set of a published
version's operations that agents may call, and the review of their descriptions
(:mod:`app.agent_toolset_enrichment`).

```
GET    /v1/tenants/{t}/agent-toolsets                       list (?versionId=…)
POST   /v1/tenants/{t}/agent-toolsets                       create for a published version
GET    /v1/tenants/{t}/agent-toolsets/{id}                  describe, with every tool
PATCH  /v1/tenants/{t}/agent-toolsets/{id}                  enabled / target / enrichment
DELETE /v1/tenants/{t}/agent-toolsets/{id}                  delete (credentials + agent keys too)
GET    /v1/tenants/{t}/agent-toolsets/{id}/tools            the tool rows
PATCH  /v1/tenants/{t}/agent-toolsets/{id}/tools/{toolId}   enable / disable one tool
GET    /v1/tenants/{t}/agent-toolsets/{id}/enrichment       agent-hostile flags + proposals
POST   /v1/tenants/{t}/agent-toolsets/{id}/enrichment       run the enrichment pass
PATCH  /v1/tenants/{t}/agent-toolsets/{id}/enrichment/{pid} accept (or edit) / reject a proposal
GET    /v1/tenants/{t}/agent-toolsets/{id}/compiled         the toolset as agents are served it
```

**Nothing AI-generated reaches an agent without acceptance.** The enrichment pass stores copilot
proposals as ``proposed``; only a person's ``accept`` makes ``/compiled`` serve the text, and only
while the toolset's ``descriptionEnrichment`` is on. Without a configured copilot the pass only
flags.

**Safe by default.** A new toolset exposes only its version's read operations. A write op
(``POST``/``PUT``/``PATCH``/``DELETE``…) is enabled one at a time, and only with
``confirmWriteOp: true``. Without it the request is a ``422``
``agent-toolset-write-op-unconfirmed``. Tool rows are seeded from the version and cannot be
added or removed one by one. Each represents an operation the version has.

**Scoped by the authenticated tenant**, as on every ``/v1/tenants/{t}`` surface: the tenant in the
URL is informational.

**Permissions reuse** ``api_keys``, as the AGX-2.2 upstream credentials and AGX-3.1 agent keys do,
**and no new RBAC resource is added**. A toolset, its credentials and its keys are together one
agent's access. Reading is ``api_keys:view``; create, update and delete are ``api_keys:create`` /
``edit`` / ``delete``.

**Every change is audited** in the tenant's access audit, with metadata only:
``agent.toolset.create``, ``agent.toolset.update`` (before and after), ``agent.toolset.delete``
and ``agent.toolset.tool.update``. The last records which operation, whether it is a write op,
and enabled before/after; the audit row's actor and time answer "who enabled which write op, when".
The enrichment pass adds ``agent.toolset.enrichment.run`` (what a run asked and stored) and
``agent.toolset.enrichment.review`` (which description, the decision before and after, and whether
the reviewer edited the text).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from .agent_toolset_enrichment import (
    CODE_ENRICHMENT_NOT_FOUND,
    CompiledToolsetOut,
    EnrichmentProposalOut,
    EnrichmentReport,
    EnrichmentReview,
    EnrichmentRun,
    EnrichmentRunResult,
    compile_agent_toolset,
    get_toolset_enrichment,
    review_toolset_enrichment,
    run_toolset_enrichment,
)
from .agent_toolsets import (
    AGENT_TOOLSET_SCHEMA_VERSION,
    CODE_TOOL_NOT_FOUND,
    CODE_TOOLSET_EXISTS,
    CODE_TOOLSET_NOT_FOUND,
    CODE_VERSION_NOT_FOUND,
    CODE_VERSION_UNPUBLISHED,
    AgentToolOut,
    AgentToolsetCreate,
    AgentToolsetDetail,
    AgentToolsetError,
    AgentToolsetOut,
    AgentToolsetUpdate,
    AgentToolUpdate,
    audit_tool_detail,
    create_agent_toolset,
    delete_agent_toolset,
    get_agent_toolset,
    list_agent_toolset_tools,
    list_agent_toolsets,
    update_agent_toolset,
    update_agent_toolset_tool,
)
from .auth import validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_CREATE",
    "AUDIT_DELETE",
    "AUDIT_ENRICHMENT_REVIEW",
    "AUDIT_ENRICHMENT_RUN",
    "AUDIT_TOOL_UPDATE",
    "AUDIT_UPDATE",
    "AgentToolListResponse",
    "AgentToolsetListResponse",
    "require_agent_toolset",
    "router",
]

router = APIRouter(prefix="/v1/tenants", tags=["agent-access"])

#: Audit actions this module writes to ``apiome.access_audit``.
AUDIT_CREATE = "agent.toolset.create"
AUDIT_UPDATE = "agent.toolset.update"
AUDIT_DELETE = "agent.toolset.delete"
AUDIT_TOOL_UPDATE = "agent.toolset.tool.update"
AUDIT_ENRICHMENT_RUN = "agent.toolset.enrichment.run"
AUDIT_ENRICHMENT_REVIEW = "agent.toolset.enrichment.review"

_BASE = "/{tenant_slug}/agent-toolsets"

#: HTTP status per refusal code; anything else is a 422.
_STATUS_BY_CODE = {
    CODE_TOOLSET_EXISTS: 409,
    CODE_TOOLSET_NOT_FOUND: 404,
    CODE_TOOL_NOT_FOUND: 404,
    CODE_ENRICHMENT_NOT_FOUND: 404,
    CODE_VERSION_NOT_FOUND: 404,
    CODE_VERSION_UNPUBLISHED: 409,
}

_WHAT_IT_IS = (
    "An agent toolset is Agent Access for one published version: which of its operations AI "
    "agents may call as MCP tools. Reads (`GET`/`HEAD`, GraphQL queries) are exposed by default; "
    "write operations are opt-in, one at a time, with an explicit confirmation."
)


class AgentToolsetListResponse(BaseModel):
    """A tenant's toolsets, described.

    Attributes:
        schema_version: The projection's shape.
        toolsets: One entry per toolset, newest first.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(
        default=AGENT_TOOLSET_SCHEMA_VERSION, serialization_alias="schemaVersion"
    )
    toolsets: List[AgentToolsetOut]


class AgentToolListResponse(BaseModel):
    """A toolset's tool rows.

    Attributes:
        schema_version: The projection's shape.
        toolset_id: The toolset addressed.
        tools: One entry per callable operation, ordered by operation key.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(
        default=AGENT_TOOLSET_SCHEMA_VERSION, serialization_alias="schemaVersion"
    )
    toolset_id: str = Field(serialization_alias="toolsetId")
    tools: List[AgentToolOut]


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the authenticated tenant id, or refuse with 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this agent toolset.")
    return str(tenant_id)


def _refusal(exc: AgentToolsetError) -> HTTPException:
    """Map a refusal onto its status, listing every problem."""
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(exc.code, 422),
        detail={"code": exc.code, "errors": list(exc.errors)},
    )


def require_agent_toolset(tenant_id: str, toolset_id: str) -> None:
    """Refuse with ``404`` unless the tenant has this toolset.

    The route-level check the AGX-2.2 upstream-credential and AGX-3.1 agent-key routes run before
    binding anything to a toolset. Another tenant's toolset is indistinguishable from a missing one.

    Args:
        tenant_id: The caller's tenant.
        toolset_id: The toolset.

    Raises:
        HTTPException: 404 ``agent-toolset-not-found``.
    """
    if not db.agent_toolset_exists(tenant_id, toolset_id):
        raise HTTPException(
            status_code=404,
            detail={"code": CODE_TOOLSET_NOT_FOUND, "errors": ["no such agent toolset"]},
        )


def _audit(
    *,
    tenant_id: str,
    action: str,
    auth_data: Dict[str, Any],
    actor_id: str,
    target: str,
    detail: Dict[str, Any],
) -> None:
    """Write one metadata-only access-audit row (best-effort).

    An audit failure is logged and swallowed: a change that succeeded must not be reported as a
    failure because its audit row could not be appended.

    Args:
        tenant_id: The tenant the action belongs to.
        action: One of the ``AUDIT_*`` actions.
        auth_data: The authenticated principal.
        actor_id: The acting user id :func:`enforce_permission` resolved.
        target: The toolset (or tool row) acted on.
        detail: Action-specific metadata.
    """
    try:
        db.write_access_audit(
            tenant_id=tenant_id,
            action=action,
            actor_id=actor_id,
            actor_label=auth_data.get("user_email") or auth_data.get("user_name"),
            target=target,
            source="api",
            detail=detail,
        )
    except Exception:  # noqa: BLE001 - auditing never fails the governed action
        logger.warning("Failed to audit %s for tenant %s", action, tenant_id, exc_info=True)


def _settings(toolset: AgentToolsetOut) -> Dict[str, Any]:
    """The toolset settings an audit row quotes."""
    return {
        "enabled": toolset.enabled,
        "target": toolset.target,
        "descriptionEnrichment": toolset.description_enrichment,
    }


@router.get(
    _BASE,
    response_model=AgentToolsetListResponse,
    summary="List agent toolsets",
    description=(
        _WHAT_IT_IS + "\n\nNewest first, with tool counts. `versionId` narrows the list to one "
        "version's toolset.\n\nRequires `api_keys:view`."
    ),
)
async def list_agent_toolsets_route(
    tenant_slug: str,
    version_id: Optional[UUID] = Query(default=None, alias="versionId"),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> AgentToolsetListResponse:
    """List the tenant's toolsets.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is what scopes it).
        version_id: Optional version filter.
        auth_data: The authenticated principal.

    Returns:
        The toolsets.

    Raises:
        HTTPException: 403 without ``api_keys:view``.
    """
    enforce_permission(db, auth_data, Resource.API_KEYS, Action.VIEW)
    _ = tenant_slug
    return AgentToolsetListResponse(
        toolsets=list_agent_toolsets(
            _tenant_id(auth_data), version_id=str(version_id) if version_id else None
        )
    )


@router.post(
    _BASE,
    response_model=AgentToolsetDetail,
    status_code=201,
    summary="Create an agent toolset for a published version",
    description=(
        _WHAT_IT_IS + "\n\nCreates the toolset for `versionId`, which must be a published, "
        "undeleted version in this tenant, and seeds one tool per callable operation: reads "
        "enabled (deprecated ones excepted), write operations disabled. `target` is `prod` "
        "(default) or `mock`; `enabled` defaults to `true`.\n\nRequires `api_keys:create`. "
        "Audited as `agent.toolset.create`."
    ),
    responses={
        404: {"description": "No such version in this tenant."},
        409: {"description": "The version is unpublished or deleted, or already has a toolset."},
        422: {"description": "The version's operations could not be read."},
    },
)
async def create_agent_toolset_route(
    tenant_slug: str,
    body: AgentToolsetCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> AgentToolsetDetail:
    """Create and seed a toolset, then audit it.

    Args:
        tenant_slug: The tenant in the URL.
        body: The version, and optional ``enabled`` / ``target``.
        auth_data: The authenticated principal.

    Returns:
        The toolset with its tools.

    Raises:
        HTTPException: 403 without ``api_keys:create``; 404 / 409 / 422 as documented.
    """
    actor_id = enforce_permission(db, auth_data, Resource.API_KEYS, Action.CREATE)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        created = create_agent_toolset(tenant_id, body, actor_id=actor_id)
    except AgentToolsetError as exc:
        raise _refusal(exc) from exc
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_CREATE,
        auth_data=auth_data,
        actor_id=actor_id,
        target=created.id,
        detail={
            "versionId": created.version_id,
            **_settings(created),
            "toolCount": created.tool_count,
            "enabledToolCount": created.enabled_tool_count,
        },
    )
    return created


@router.get(
    _BASE + "/{toolset_id}",
    response_model=AgentToolsetDetail,
    summary="Describe an agent toolset",
    description="The toolset's settings and every tool row.\n\nRequires `api_keys:view`.",
    responses={404: {"description": "No such agent toolset in this tenant."}},
)
async def get_agent_toolset_route(
    tenant_slug: str,
    toolset_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> AgentToolsetDetail:
    """Describe one toolset.

    Args:
        tenant_slug: The tenant in the URL.
        toolset_id: The toolset.
        auth_data: The authenticated principal.

    Returns:
        The toolset with its tools.

    Raises:
        HTTPException: 403 without ``api_keys:view``; 404 when it does not exist.
    """
    enforce_permission(db, auth_data, Resource.API_KEYS, Action.VIEW)
    _ = tenant_slug
    try:
        return get_agent_toolset(_tenant_id(auth_data), str(toolset_id))
    except AgentToolsetError as exc:
        raise _refusal(exc) from exc


@router.patch(
    _BASE + "/{toolset_id}",
    response_model=AgentToolsetOut,
    summary="Change an agent toolset's settings",
    description=(
        "Switch the whole toolset on or off (`enabled`; a disabled toolset exposes no tools) "
        "and/or change its `target` (`prod` | `mock`), and/or opt out of description "
        "enrichment (`descriptionEnrichment: false` serves the spec-derived descriptions even "
        "where a proposal was accepted). Tool selections are untouched.\n\n"
        "Requires `api_keys:edit`. Audited as `agent.toolset.update`, before and after."
    ),
    responses={
        404: {"description": "No such agent toolset in this tenant."},
        422: {"description": "The body changes nothing."},
    },
)
async def update_agent_toolset_route(
    tenant_slug: str,
    toolset_id: UUID,
    body: AgentToolsetUpdate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> AgentToolsetOut:
    """Change a toolset's settings, then audit the change.

    Args:
        tenant_slug: The tenant in the URL.
        toolset_id: The toolset.
        body: The fields to change.
        auth_data: The authenticated principal.

    Returns:
        The toolset after the change.

    Raises:
        HTTPException: 403 without ``api_keys:edit``; 404 when it does not exist; 422 when the
            body changes nothing.
    """
    actor_id = enforce_permission(db, auth_data, Resource.API_KEYS, Action.EDIT)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        before, after = update_agent_toolset(tenant_id, str(toolset_id), body, actor_id=actor_id)
    except AgentToolsetError as exc:
        raise _refusal(exc) from exc
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_UPDATE,
        auth_data=auth_data,
        actor_id=actor_id,
        target=after.id,
        detail={"versionId": after.version_id, "before": _settings(before), "after": _settings(after)},
    )
    return after


@router.delete(
    _BASE + "/{toolset_id}",
    status_code=204,
    response_class=Response,
    summary="Delete an agent toolset",
    description=(
        "Delete the toolset and its tool selections. **Its upstream credentials and agent keys "
        "are deleted with it**: an agent holding one of its keys is refused on its next request.\n\n"
        "Requires `api_keys:delete`. Audited as `agent.toolset.delete`."
    ),
    responses={404: {"description": "No such agent toolset in this tenant."}},
)
async def delete_agent_toolset_route(
    tenant_slug: str,
    toolset_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Delete a toolset, then audit it.

    Args:
        tenant_slug: The tenant in the URL.
        toolset_id: The toolset.
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
        removed = delete_agent_toolset(tenant_id, str(toolset_id))
    except AgentToolsetError as exc:
        raise _refusal(exc) from exc
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_DELETE,
        auth_data=auth_data,
        actor_id=actor_id,
        target=removed.id,
        detail={
            "versionId": removed.version_id,
            **_settings(removed),
            "enabledToolCount": removed.enabled_tool_count,
            "enabledWriteOpCount": removed.enabled_write_op_count,
        },
    )
    return Response(status_code=204)


@router.get(
    _BASE + "/{toolset_id}/tools",
    response_model=AgentToolListResponse,
    summary="List an agent toolset's tools",
    description=(
        "One row per callable operation of the toolset's version, ordered by operation key: the "
        "MCP tool name, whether it is a write op, and whether it is exposed.\n\n"
        "Requires `api_keys:view`."
    ),
    responses={404: {"description": "No such agent toolset in this tenant."}},
)
async def list_agent_toolset_tools_route(
    tenant_slug: str,
    toolset_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> AgentToolListResponse:
    """List a toolset's tool rows.

    Args:
        tenant_slug: The tenant in the URL.
        toolset_id: The toolset.
        auth_data: The authenticated principal.

    Returns:
        The tool rows.

    Raises:
        HTTPException: 403 without ``api_keys:view``; 404 when the toolset does not exist.
    """
    enforce_permission(db, auth_data, Resource.API_KEYS, Action.VIEW)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    require_agent_toolset(tenant_id, str(toolset_id))
    return AgentToolListResponse(
        toolset_id=str(toolset_id), tools=list_agent_toolset_tools(tenant_id, str(toolset_id))
    )


@router.patch(
    _BASE + "/{toolset_id}/tools/{tool_id}",
    response_model=AgentToolOut,
    summary="Enable or disable one tool",
    description=(
        "Set `enabled` on one tool. **Enabling a write operation requires "
        "`confirmWriteOp: true`**; without it the request is refused with "
        "`agent-toolset-write-op-unconfirmed` and nothing changes. The confirmation is recorded "
        "on the tool (`writeConfirmedBy`, `writeConfirmedAt`) and cleared when the tool is "
        "disabled, so re-enabling needs a fresh one.\n\nRequires `api_keys:edit`. Audited as "
        "`agent.toolset.tool.update`."
    ),
    responses={
        404: {"description": "No such tool in this tenant's agent toolset."},
        422: {"description": "A write operation was enabled without `confirmWriteOp: true`."},
    },
)
async def update_agent_toolset_tool_route(
    tenant_slug: str,
    toolset_id: UUID,
    tool_id: UUID,
    body: AgentToolUpdate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> AgentToolOut:
    """Enable or disable one tool, then audit the change.

    Args:
        tenant_slug: The tenant in the URL.
        toolset_id: The toolset.
        tool_id: The tool row.
        body: The new state and the write-op confirmation.
        auth_data: The authenticated principal.

    Returns:
        The tool after the change.

    Raises:
        HTTPException: 403 without ``api_keys:edit``; 404 when the tool does not exist; 422 for an
            unconfirmed write op.
    """
    actor_id = enforce_permission(db, auth_data, Resource.API_KEYS, Action.EDIT)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        before, after = update_agent_toolset_tool(
            tenant_id, str(toolset_id), str(tool_id), body, actor_id=actor_id
        )
    except AgentToolsetError as exc:
        raise _refusal(exc) from exc
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_TOOL_UPDATE,
        auth_data=auth_data,
        actor_id=actor_id,
        target=after.id,
        detail={"toolsetId": str(toolset_id), **audit_tool_detail(before, after)},
    )
    return after


# ============================================================================
# Description enrichment — AGX-1.3 (#4531)
# ============================================================================

_ENRICHMENT_WHAT_IT_IS = (
    "The enrichment pass looks for tools an agent will struggle with. Each flag lists "
    "machine-readable reasons: `missing-description`, `thin-description`, `missing-examples`, "
    "`undocumented-errors`, `missing-parameter-description`, `thin-parameter-description`. When "
    "the copilot (an Ollama model, `APIOME_AGENT_ENRICHMENT_MODEL`) is configured, it also "
    "proposes descriptions for the thin ones, written only from the spec's own documentation. "
    "**Proposals are never served until a person accepts them.** Without the copilot, `mode` is "
    "`flag-only`."
)


@router.get(
    _BASE + "/{toolset_id}/enrichment",
    response_model=EnrichmentReport,
    summary="Describe an agent toolset's enrichment",
    description=_ENRICHMENT_WHAT_IT_IS + "\n\nRequires `api_keys:view`.",
    responses={
        404: {"description": "No such agent toolset in this tenant."},
        422: {"description": "The version's operations could not be read."},
    },
)
async def get_agent_toolset_enrichment_route(
    tenant_slug: str,
    toolset_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> EnrichmentReport:
    """Report a toolset's agent-hostile tools and description proposals.

    Args:
        tenant_slug: The tenant in the URL.
        toolset_id: The toolset.
        auth_data: The authenticated principal.

    Returns:
        The flags and proposals.

    Raises:
        HTTPException: 403 without ``api_keys:view``; 404 when the toolset does not exist; 422 when
            its version cannot be read.
    """
    enforce_permission(db, auth_data, Resource.API_KEYS, Action.VIEW)
    _ = tenant_slug
    try:
        return get_toolset_enrichment(_tenant_id(auth_data), str(toolset_id))
    except AgentToolsetError as exc:
        raise _refusal(exc) from exc


@router.post(
    _BASE + "/{toolset_id}/enrichment",
    response_model=EnrichmentRunResult,
    summary="Run the enrichment pass",
    description=(
        _ENRICHMENT_WHAT_IT_IS + "\n\nThe pass is idempotent: a description that already has a "
        "proposal, whatever its status, is not asked about again. Each run asks the copilot about "
        "at most 20 operations and reports `remainingOperations`; run it again to continue, or "
        "pass `operations` to choose which.\n\nRequires `api_keys:edit`. Audited as "
        "`agent.toolset.enrichment.run`."
    ),
    responses={
        404: {"description": "No such agent toolset in this tenant."},
        422: {
            "description": (
                "The version's operations could not be read, or `operations` names an operation "
                "the toolset does not have."
            )
        },
    },
)
async def run_agent_toolset_enrichment_route(
    tenant_slug: str,
    toolset_id: UUID,
    body: Optional[EnrichmentRun] = Body(default=None),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> EnrichmentRunResult:
    """Run the enrichment pass, then audit what it did.

    The pass makes blocking calls to the copilot (up to one per operation), so it runs on a worker
    thread: one slow model must not stall every other request.

    Args:
        tenant_slug: The tenant in the URL.
        toolset_id: The toolset.
        body: Optionally, the operations to ask about.
        auth_data: The authenticated principal.

    Returns:
        What the run did and the report after it.

    Raises:
        HTTPException: 403 without ``api_keys:edit``; 404 when the toolset does not exist; 422 when
            its version cannot be read or ``operations`` is invalid.
    """
    actor_id = enforce_permission(db, auth_data, Resource.API_KEYS, Action.EDIT)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        result = await run_in_threadpool(
            run_toolset_enrichment, tenant_id, str(toolset_id), body
        )
    except AgentToolsetError as exc:
        raise _refusal(exc) from exc
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_ENRICHMENT_RUN,
        auth_data=auth_data,
        actor_id=actor_id,
        target=str(toolset_id),
        detail={
            "mode": result.mode,
            "model": result.model,
            "generated": result.generated,
            "attemptedOperations": result.attempted_operations,
            "failedOperations": result.failed_operations,
            "remainingOperations": result.remaining_operations,
            "flagged": result.counts.get("flagged", 0),
        },
    )
    return result


@router.patch(
    _BASE + "/{toolset_id}/enrichment/{proposal_id}",
    response_model=EnrichmentProposalOut,
    summary="Accept or reject a description proposal",
    description=(
        "`decision: accept` serves the proposal in the compiled toolset; pass `description` to "
        "serve an edited text instead. `decision: reject` withdraws it, including a previously "
        "accepted one. The reviewer and time are recorded on the proposal.\n\nRequires "
        "`api_keys:edit`. Audited as `agent.toolset.enrichment.review`."
    ),
    responses={
        404: {"description": "No such proposal in this tenant's agent toolset."},
        422: {"description": "A blank or over-long edit, or an edit with `reject`."},
    },
)
async def review_agent_toolset_enrichment_route(
    tenant_slug: str,
    toolset_id: UUID,
    proposal_id: UUID,
    body: EnrichmentReview,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> EnrichmentProposalOut:
    """Record a decision on one proposal, then audit it.

    Args:
        tenant_slug: The tenant in the URL.
        toolset_id: The toolset.
        proposal_id: The proposal.
        body: The decision and an optional edit.
        auth_data: The authenticated principal.

    Returns:
        The proposal after the review.

    Raises:
        HTTPException: 403 without ``api_keys:edit``; 404 when the proposal does not exist; 422 for
            an invalid edit.
    """
    actor_id = enforce_permission(db, auth_data, Resource.API_KEYS, Action.EDIT)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        before, after = review_toolset_enrichment(
            tenant_id, str(toolset_id), str(proposal_id), body, actor_id=actor_id
        )
    except AgentToolsetError as exc:
        raise _refusal(exc) from exc
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_ENRICHMENT_REVIEW,
        auth_data=auth_data,
        actor_id=actor_id,
        target=after.id,
        detail={
            "toolsetId": str(toolset_id),
            "operation": after.operation,
            "targetKey": after.target_key,
            "statusBefore": before.status,
            "statusAfter": after.status,
            "edited": after.status == "accepted"
            and after.accepted_description != after.proposed_description,
        },
    )
    return after


@router.get(
    _BASE + "/{toolset_id}/compiled",
    response_model=CompiledToolsetOut,
    summary="Compile an agent toolset",
    description=(
        "The toolset as agents are served it: the enabled tools as MCP `tools/list` entries. "
        "While `descriptionEnrichment` is on, accepted description proposals replace the "
        "spec-derived text (`enrichedTargets` lists which); proposed and rejected ones never do. "
        "A disabled toolset compiles to no tools.\n\nRequires `api_keys:view`."
    ),
    responses={
        404: {"description": "No such agent toolset in this tenant."},
        422: {"description": "The version's operations could not be read or compiled."},
    },
)
async def compile_agent_toolset_route(
    tenant_slug: str,
    toolset_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CompiledToolsetOut:
    """Compile a toolset with its accepted descriptions.

    Args:
        tenant_slug: The tenant in the URL.
        toolset_id: The toolset.
        auth_data: The authenticated principal.

    Returns:
        The compiled toolset.

    Raises:
        HTTPException: 403 without ``api_keys:view``; 404 when the toolset does not exist; 422 when
            its version cannot be read or compiled.
    """
    enforce_permission(db, auth_data, Resource.API_KEYS, Action.VIEW)
    _ = tenant_slug
    try:
        return compile_agent_toolset(_tenant_id(auth_data), str(toolset_id))
    except AgentToolsetError as exc:
        raise _refusal(exc) from exc
