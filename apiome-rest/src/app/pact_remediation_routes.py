"""Verification settings and re-publish requests — PFX-6.2 (#6954): the HTTP face of :mod:`app.pact_remediation`.

Outside ``…/pact-broker``, because no Pact Broker or PactFlow client knows them (the broker surface stays
the catalogued, compatible one, :mod:`app.pact_broker_compat`):

* ``GET`` / ``PUT /v1/tenants/{tenant}/pact-verification-settings`` — the workspace's cadence, stale
  threshold, concurrent-run limit, request window and whether stale pacts open re-publish requests.
* ``GET`` / ``PUT …/pact-verification-settings/overrides`` and ``DELETE …/overrides/{id}`` — a
  different cadence, threshold or verification target for one provider or one consumer ↔ provider pair.
* ``GET /v1/tenants/{tenant}/pact-republish-requests`` (``provider``, ``consumer``, ``state``,
  ``cursor``, ``limit``), ``GET …/{id}`` and ``POST …/{id}/acknowledge``.

**Permissions.** Reads need ``pacts:view``; saving settings or an override, removing an override and
acknowledging a request need ``pacts:edit``. Every write appends an ``access_audit`` row
(:func:`app.pact_audit.audited_write`). Every lookup is scoped to the authenticated tenant: another
workspace's pacticipant, target, override or request is a ``404``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .consumer_contract_store import actor_from_auth
from .database import db
from .pact_audit import audited_write
from .pact_broker_auth import validate_broker_authentication
from .pact_remediation import (
    CODE_OVERRIDE_INVALID,
    CODE_OVERRIDE_NOT_FOUND,
    CODE_REQUEST_CLOSED,
    CODE_REQUEST_CURSOR_INVALID,
    CODE_REQUEST_NOT_FOUND,
    MAX_REQUEST_PAGE,
    AcknowledgeRequest,
    OverrideInput,
    OverrideList,
    OverrideRecord,
    RemediationError,
    RepublishRequestPage,
    RepublishRequestRecord,
    VerificationSettings,
    VerificationSettingsInput,
)
from .pact_remediation_store import (
    acknowledge_request,
    delete_override,
    get_request,
    get_settings,
    list_overrides,
    list_requests,
    put_override,
    save_settings,
)
from .pacticipant import PacticipantValidationError
from .pacticipant_routes import STATUS_BY_CODE
from .permissions import Action, Resource, enforce_permission
from .verification_target import CODE_NOT_FOUND as CODE_TARGET_NOT_FOUND
from .verification_target import TargetValidationError

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_SETTINGS = "/{tenant_slug}/pact-verification-settings"
_REQUESTS = "/{tenant_slug}/pact-republish-requests"

_STATUS = {
    CODE_OVERRIDE_INVALID: 422,
    CODE_OVERRIDE_NOT_FOUND: 404,
    CODE_REQUEST_NOT_FOUND: 404,
    CODE_REQUEST_CLOSED: 409,
    CODE_REQUEST_CURSOR_INVALID: 400,
}

#: The ``state`` filter's values: a request state, or ``open`` for requested and acknowledged ones.
_STATE_FILTER = "^(open|requested|acknowledged|republished|cleared|expired)$"


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _error(exc: Exception) -> HTTPException:
    """The HTTP error for a refusal, carrying ``{"code", "message"}``.

    Args:
        exc: A :class:`RemediationError`, :class:`PacticipantValidationError` or
            :class:`TargetValidationError`.

    Returns:
        The exception to raise.
    """
    code = getattr(exc, "code", "")
    if isinstance(exc, RemediationError):
        status = _STATUS.get(code, 422)
    elif isinstance(exc, PacticipantValidationError):
        status = STATUS_BY_CODE.get(code, 400)
    elif isinstance(exc, TargetValidationError):
        status = 404 if code == CODE_TARGET_NOT_FOUND else 422
    else:  # pragma: no cover - only the three kinds above are passed
        status = 500
    return HTTPException(status_code=status, detail={"code": code, "message": str(exc)})


# =============================================================================================
# Settings
# =============================================================================================


@router.get(
    _SETTINGS,
    response_model=VerificationSettings,
    summary="Read the workspace's Pact verification settings",
    description=(
        "The workspace's verification settings (PFX-6.2): the **cadence** on which Apiome's hosted "
        "verifier runs each pair (`on-publish`, `hourly`, `nightly` or `manual-only`), the **stale "
        "threshold** in hours (a pact not verified for longer is stale and opens a re-publish request), "
        "how many scheduled verifications may run at once, how long a re-publish request stays open, and "
        "whether stale pacts open requests. A workspace that never saved any reads the defaults "
        "(`customised: false`: manual-only, 72 h, 2, 72 h, on). Requires `pacts:view`."
    ),
)
def read_settings(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> VerificationSettings:
    """Read the workspace's verification settings.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant scopes every lookup).
        auth_data: The authenticated principal.

    Returns:
        The settings.

    Raises:
        HTTPException: 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target="pact-verification-settings")
    _ = tenant_slug
    return get_settings(db, _tenant_id(auth_data))


@router.put(
    _SETTINGS,
    response_model=VerificationSettings,
    summary="Save the workspace's Pact verification settings",
    description=(
        "Replace the workspace's verification settings (PFX-6.2); every field is required. A cadence "
        "other than `manual-only` runs a pair only where an override names a verification target. "
        "Out-of-range values are a `422` naming the field. Requires `pacts:edit`."
    ),
)
@audited_write("pacts.verification_settings.update", "pact-verification-settings")
def update_settings(
    tenant_slug: str,
    body: VerificationSettingsInput,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> VerificationSettings:
    """Save the workspace's verification settings.

    Args:
        tenant_slug: The tenant in the URL.
        body: The settings.
        auth_data: The authenticated principal.

    Returns:
        The stored settings.

    Raises:
        HTTPException: 403 without ``pacts:edit``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT, target="pact-verification-settings")
    _ = tenant_slug
    return save_settings(db, _tenant_id(auth_data), body, actor=actor_from_auth(auth_data, user_id))


@router.get(
    _SETTINGS + "/overrides",
    response_model=OverrideList,
    summary="List the Pact verification overrides",
    description=(
        "Every provider-wide and per-pair override of the workspace (PFX-6.2), by provider then "
        "consumer: its cadence, stale threshold and verification target (null inherits). "
        "`target_deleted` flags an override whose target was deleted. Requires `pacts:view`."
    ),
)
def read_overrides(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> OverrideList:
    """List the workspace's overrides.

    Args:
        tenant_slug: The tenant in the URL.
        auth_data: The authenticated principal.

    Returns:
        The overrides.

    Raises:
        HTTPException: 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target="pact-verification-settings")
    _ = tenant_slug
    return list_overrides(db, _tenant_id(auth_data))


@router.put(
    _SETTINGS + "/overrides",
    response_model=OverrideRecord,
    summary="Save a Pact verification override",
    description=(
        "Create or replace the override of a provider (omit `consumer`) or of one consumer ↔ provider "
        "pair (PFX-6.2). Set at least one of `cadence`, `stale_threshold_hours` and `target_ref` (the "
        "verification target scheduled runs replay against); a null field inherits — the pair's "
        "override wins over the provider's, which wins over the workspace's. A workspace has at most 500 "
        "overrides. Requires `pacts:edit`."
    ),
    responses={
        404: {"description": "`pacticipant-not-found` or `target-not-found` in this workspace."},
        422: {"description": "`pact-verification-override-invalid`, or a value out of range."},
    },
)
@audited_write("pacts.verification_override.save", "pact-verification-overrides")
def save_override(
    tenant_slug: str,
    body: OverrideInput,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> OverrideRecord:
    """Create or replace an override.

    Args:
        tenant_slug: The tenant in the URL.
        body: The override.
        auth_data: The authenticated principal.

    Returns:
        The stored override.

    Raises:
        HTTPException: 403 without ``pacts:edit``; 404 / 422 as documented.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT, target=body.provider)
    _ = tenant_slug
    try:
        return put_override(db, _tenant_id(auth_data), body, actor=actor_from_auth(auth_data, user_id))
    except (RemediationError, PacticipantValidationError, TargetValidationError) as exc:
        raise _error(exc) from exc


@router.delete(
    _SETTINGS + "/overrides/{override_id}",
    status_code=204,
    summary="Remove a Pact verification override",
    description="Remove one override (PFX-6.2); the provider or pair inherits again. Requires `pacts:edit`.",
    responses={404: {"description": "`pact-verification-override-not-found` in this workspace."}},
)
@audited_write("pacts.verification_override.delete", "pact-verification-override/{override_id}")
def remove_override(
    tenant_slug: str,
    override_id: str,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> Response:
    """Remove an override.

    Args:
        tenant_slug: The tenant in the URL.
        override_id: The override's id.
        auth_data: The authenticated principal.

    Returns:
        An empty 204.

    Raises:
        HTTPException: 403 without ``pacts:edit``; 404 for an unknown override.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT, target="pact-verification-settings")
    _ = tenant_slug
    try:
        delete_override(db, _tenant_id(auth_data), override_id)
    except RemediationError as exc:
        raise _error(exc) from exc
    return Response(status_code=204)


# =============================================================================================
# Re-publish requests
# =============================================================================================


@router.get(
    _REQUESTS,
    response_model=RepublishRequestPage,
    summary="List re-publish requests",
    description=(
        "The workspace's re-publish requests (PFX-6.2), newest first: each stale pact the sweep asked its "
        "consumer to re-publish, its state (`requested`, `acknowledged`, `republished`, `cleared` — "
        "verified meanwhile — or `expired`, escalated), its window, and what notifying the consumer's "
        "owners did. Narrow by `provider`, `consumer` and `state` (`open` for requested and acknowledged); "
        "pass `next_cursor` as `cursor` for the next page. Requires `pacts:view`."
    ),
    responses={
        400: {"description": "`pact-republish-request-cursor-invalid`."},
        404: {"description": "`pacticipant-not-found` for the `provider` or `consumer` filter."},
    },
)
def read_requests(
    tenant_slug: str,
    provider: Optional[str] = Query(None, min_length=1, max_length=255, description="Only this provider's."),
    consumer: Optional[str] = Query(None, min_length=1, max_length=255, description="Only this consumer's."),
    state: Optional[str] = Query(None, pattern=_STATE_FILTER, description="A state, or `open`."),
    cursor: Optional[str] = Query(None, max_length=32, description="The `next_cursor` of the previous page."),
    limit: int = Query(25, ge=1, le=MAX_REQUEST_PAGE, description="Page size."),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> RepublishRequestPage:
    """List re-publish requests.

    Args:
        tenant_slug: The tenant in the URL.
        provider: Only this provider's.
        consumer: Only this consumer's.
        state: A state, or ``open``.
        cursor: The previous page's ``next_cursor``.
        limit: Page size.
        auth_data: The authenticated principal.

    Returns:
        The page.

    Raises:
        HTTPException: 403 without ``pacts:view``; 400 / 404 as documented.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target="pact-republish-requests")
    _ = tenant_slug
    try:
        return list_requests(
            db,
            _tenant_id(auth_data),
            provider_ref=provider,
            consumer_ref=consumer,
            state=state,
            cursor=cursor,
            limit=limit,
        )
    except (RemediationError, PacticipantValidationError) as exc:
        raise _error(exc) from exc


@router.get(
    _REQUESTS + "/{request_id}",
    response_model=RepublishRequestRecord,
    summary="Read one re-publish request",
    description="One re-publish request of the workspace (PFX-6.2). Requires `pacts:view`.",
    responses={404: {"description": "`pact-republish-request-not-found` in this workspace."}},
)
def read_request(
    tenant_slug: str,
    request_id: str,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> RepublishRequestRecord:
    """Read one re-publish request.

    Args:
        tenant_slug: The tenant in the URL.
        request_id: The request's id.
        auth_data: The authenticated principal.

    Returns:
        The request.

    Raises:
        HTTPException: 403 without ``pacts:view``; 404 for an unknown request.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target="pact-republish-requests")
    _ = tenant_slug
    try:
        return get_request(db, _tenant_id(auth_data), request_id)
    except RemediationError as exc:
        raise _error(exc) from exc


@router.post(
    _REQUESTS + "/{request_id}/acknowledge",
    response_model=RepublishRequestRecord,
    summary="Acknowledge a re-publish request",
    description=(
        "The consumer acknowledges an open re-publish request (PFX-6.2), optionally with a `note` (what it "
        "will do, and when; at most 1000 characters). Acknowledging again updates the note. The request "
        "still expires at the end of its window unless the consumer re-publishes the pact or the provider "
        "verifies it. A request that is no longer open is a `409` (`pact-republish-request-closed`). "
        "Requires `pacts:edit`."
    ),
    responses={
        404: {"description": "`pact-republish-request-not-found` in this workspace."},
        409: {"description": "`pact-republish-request-closed`."},
    },
)
@audited_write("pacts.republish_request.acknowledge", "pact-republish-request/{request_id}")
def acknowledge(
    tenant_slug: str,
    request_id: str,
    body: AcknowledgeRequest,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> RepublishRequestRecord:
    """Acknowledge a re-publish request.

    Args:
        tenant_slug: The tenant in the URL.
        request_id: The request's id.
        body: The optional note.
        auth_data: The authenticated principal.

    Returns:
        The request.

    Raises:
        HTTPException: 403 without ``pacts:edit``; 404 / 409 as documented.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT, target="pact-republish-requests")
    _ = tenant_slug
    try:
        return acknowledge_request(
            db, _tenant_id(auth_data), request_id, body.note, actor=actor_from_auth(auth_data, user_id)
        )
    except RemediationError as exc:
        raise _error(exc) from exc
