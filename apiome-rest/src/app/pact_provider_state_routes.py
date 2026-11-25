"""``…/pact-verifier/providers/{provider}/provider-states`` — the provider-state registry, PFX-3.3 (#6933).

A provider registers the states its pacts' interactions name, and how the hosted verifier
(PFX-3.2) sets each one up; ``…/check`` reports, before a run, every state the selected pacts
name that cannot be set up. The rules are :mod:`app.pact_provider_state`; the work is
:mod:`app.pact_provider_state_service`.

Like the verifier, these routes live beside the Pact Broker surface, not under ``…/pact-broker``:
no Pact Broker client knows them.

**Permissions** (the ``pacts`` resource, on the provider): ``view`` to list, read and check;
``create`` to register; ``edit`` to replace; ``delete`` to delete. A workspace API key is accepted
as a bearer token. Every lookup is scoped to the authenticated tenant, so a provider, state or
target of another workspace is a ``404`` (or, for an override's target, a ``422`` pointing at it).
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Response

from .consumer_contract_store import actor_from_auth
from .database import db
from .pact_broker_auth import validate_broker_authentication
from .pact_provider_state import (
    CODE_STATE_INVALID,
    CODE_STATE_NAME_TAKEN,
    CODE_STATE_NOT_FOUND,
    ProviderStateInput,
    ProviderStateRecord,
)
from .pact_provider_state_service import (
    StateCheckRequest,
    StateCheckResponse,
    check_provider_states,
    list_provider_states,
    read_provider_state,
    register_provider_state,
    remove_provider_state,
    replace_provider_state,
)
from .pact_publication import PactPublicationError
from .pact_verifier_service import PactVerifierError
from .pacticipant import CODE_NOT_FOUND as CODE_PACTICIPANT_NOT_FOUND
from .pacticipant import PacticipantValidationError
from .permissions import Action, Resource, enforce_permission
from .verification_target import CODE_NOT_FOUND as CODE_TARGET_NOT_FOUND
from .verification_target import TargetValidationError

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_BASE = "/{tenant_slug}/pact-verifier/providers/{provider}/provider-states"

_STATUS = {
    CODE_STATE_INVALID: 422,
    CODE_STATE_NOT_FOUND: 404,
    CODE_STATE_NAME_TAKEN: 409,
    CODE_PACTICIPANT_NOT_FOUND: 404,
    CODE_TARGET_NOT_FOUND: 404,
}


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _error(exc: Exception) -> HTTPException:
    """Translate a refusal into ``{"code", "message", "pointer"?}`` with its status.

    Args:
        exc: A registry, pacticipant, selector, target or verifier refusal.

    Returns:
        The ``HTTPException`` to raise (400 for anything without a mapped code, such as a malformed
        selector; 422 for an unusable target or too many pacts).
    """
    code = getattr(exc, "code", "")
    detail: Dict[str, Any] = {"code": code, "message": str(exc)}
    pointer = getattr(exc, "pointer", None)
    if pointer is not None:
        detail["pointer"] = pointer
    default = 422 if isinstance(exc, (TargetValidationError, PactVerifierError)) else 400
    return HTTPException(status_code=_STATUS.get(code, default), detail=detail)


_ERRORS = (PactPublicationError, PacticipantValidationError, TargetValidationError, PactVerifierError)

_REFUSALS = {
    403: {"description": "The credential lacks the `pacts` permission this route needs."},
    404: {"description": "`pacticipant-not-found` or `provider-state-not-found` in this workspace."},
}


@router.get(
    _BASE,
    response_model=List[ProviderStateRecord],
    summary="List a provider's registered provider states",
    description=(
        "The provider states the provider has registered (PFX-3.3), by name, each with its "
        "parameters, its default setup and its per-target overrides. Requires `pacts:view`."
    ),
    responses={404: _REFUSALS[404]},
)
def list_states_route(
    tenant_slug: str, provider: str, auth_data: Dict[str, Any] = Depends(validate_broker_authentication)
) -> List[ProviderStateRecord]:
    """List a provider's states.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant scopes every lookup).
        provider: The provider's handle, id or name.
        auth_data: The authenticated principal.

    Returns:
        The states.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target=provider)
    try:
        return list_provider_states(db, _tenant_id(auth_data), provider)
    except _ERRORS as exc:
        raise _error(exc) from exc


@router.post(
    _BASE,
    response_model=ProviderStateRecord,
    status_code=201,
    summary="Register a provider state",
    description=(
        "Register a state the provider's pacts name, and how the hosted verifier sets it up "
        "(PFX-3.3).\n\n"
        "**Name** — exactly as consumers write it (`an invoice 1042 exists`); unique per provider.\n\n"
        "**Parameters** — `[{name, required, default, description}]`. An interaction that leaves out "
        "a required parameter without a default is held back with `provider-state-param-missing`; "
        "one that passes an undeclared parameter is reported, and the parameter passed on.\n\n"
        '**Setup** — `{kind: "state_change", url, teardown}` posts the Pact state-change body '
        "`{state, params, action}` to `url`: a path is sent to the verification target with its "
        "credential, an absolute http(s) URL through the SSRF guard with none. "
        '`{kind: "fixture", requests, teardown_requests}` sends recorded requests to the target, '
        "`${param}` substituted; empty `requests` means the target already holds the data. "
        "Credentials are never stored in a fixture.\n\n"
        "**Overrides** — `[{target_ref, setup}]`: a different setup on one verification target.\n\n"
        "Requires `pacts:create`."
    ),
    responses={
        **_REFUSALS,
        409: {"description": "`provider-state-name-taken`."},
        422: {"description": "`provider-state-invalid`, with a JSON Pointer to the place."},
    },
)
def create_state_route(
    tenant_slug: str,
    provider: str,
    body: ProviderStateInput,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> ProviderStateRecord:
    """Register a state.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        body: The state.
        auth_data: The authenticated principal.

    Returns:
        The stored state.
    """
    _ = tenant_slug
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE, target=provider)
    try:
        return register_provider_state(
            db, _tenant_id(auth_data), provider, body, actor=actor_from_auth(auth_data, user_id)
        )
    except _ERRORS as exc:
        raise _error(exc) from exc


@router.post(
    f"{_BASE}/check",
    response_model=StateCheckResponse,
    summary="Check a provider's pacts against its provider states",
    description=(
        "Before a hosted verification (PFX-3.3): select the pacts a run would (`selection`, as on "
        "`…/verify`), and report every provider state their interactions name — registered or not, "
        "the setup it would use on `target_ref`, and each problem: `provider-state-not-registered`, "
        "`provider-state-param-missing`, `provider-state-setup-blocked` (blocking — the run holds "
        "the interaction back) and `provider-state-param-undeclared` (a warning). `ready` is true "
        "when nothing blocks. Nothing is sent to the target. Requires `pacts:view`."
    ),
    responses={
        **_REFUSALS,
        400: {"description": "`pact-selector-invalid`."},
        422: {"description": "`pact-verify-too-many-pacts`."},
    },
)
def check_states_route(
    tenant_slug: str,
    provider: str,
    body: StateCheckRequest,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> StateCheckResponse:
    """Check the selected pacts' states.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        body: The selection and the target.
        auth_data: The authenticated principal.

    Returns:
        The report.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target=provider)
    try:
        return check_provider_states(db, _tenant_id(auth_data), provider, body)
    except _ERRORS as exc:
        raise _error(exc) from exc


@router.get(
    f"{_BASE}/{{state_id}}",
    response_model=ProviderStateRecord,
    summary="Read a provider state",
    description="One registered provider state (PFX-3.3). Requires `pacts:view`.",
    responses={404: _REFUSALS[404]},
)
def get_state_route(
    tenant_slug: str,
    provider: str,
    state_id: str,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> ProviderStateRecord:
    """Read one state.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        state_id: The state's id.
        auth_data: The authenticated principal.

    Returns:
        The state.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target=provider)
    try:
        return read_provider_state(db, _tenant_id(auth_data), provider, state_id)
    except _ERRORS as exc:
        raise _error(exc) from exc


@router.put(
    f"{_BASE}/{{state_id}}",
    response_model=ProviderStateRecord,
    summary="Replace a provider state",
    description=(
        "Replace a registered state's name, parameters, setup and overrides (PFX-3.3); the body is "
        "the one `POST` takes, and the overrides it lists replace the stored ones. Requires `pacts:edit`."
    ),
    responses={
        **_REFUSALS,
        409: {"description": "`provider-state-name-taken`."},
        422: {"description": "`provider-state-invalid`, with a JSON Pointer to the place."},
    },
)
def replace_state_route(
    tenant_slug: str,
    provider: str,
    state_id: str,
    body: ProviderStateInput,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> ProviderStateRecord:
    """Replace one state.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        state_id: The state's id.
        body: The state.
        auth_data: The authenticated principal.

    Returns:
        The stored state.
    """
    _ = tenant_slug
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT, target=provider)
    try:
        return replace_provider_state(
            db, _tenant_id(auth_data), provider, state_id, body, actor=actor_from_auth(auth_data, user_id)
        )
    except _ERRORS as exc:
        raise _error(exc) from exc


@router.delete(
    f"{_BASE}/{{state_id}}",
    status_code=204,
    summary="Delete a provider state",
    description=(
        "Delete a registered state and its overrides (PFX-3.3). Interactions that name it are then "
        "held back with `provider-state-not-registered`. Requires `pacts:delete`."
    ),
    responses={404: _REFUSALS[404]},
)
def delete_state_route(
    tenant_slug: str,
    provider: str,
    state_id: str,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> Response:
    """Delete one state.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        state_id: The state's id.
        auth_data: The authenticated principal.

    Returns:
        An empty 204.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.PACTS, Action.DELETE, target=provider)
    try:
        remove_provider_state(db, _tenant_id(auth_data), provider, state_id)
    except _ERRORS as exc:
        raise _error(exc) from exc
    return Response(status_code=204)
