"""`apiome login` routes — browser-approved CLI sign-in (#5501).

The CLI half (no credentials yet):

* ``POST /v1/cli/login`` — start a login: a secret device code, a user code and the approve page.
* ``POST /v1/cli/login/token`` — poll with the device code. Answers ``400`` with an RFC 8628 error
  (``authorization_pending``, ``slow_down``, ``access_denied``, ``expired_token``,
  ``invalid_grant``) in ``detail.error`` until the login is approved; then ``200`` with a new API
  key, once.

The browser half (apiome-ui, signed in — a session **JWT** is required; an API key is refused, so a
key can never approve a login that mints another key):

* ``GET /v1/cli/login/requests/{user_code}`` — the pending login and the workspaces the person
  could approve it for.
* ``POST /v1/cli/login/requests/{user_code}/approve`` — approve for one workspace. Requires
  ``api_keys:create`` there, as creating a key on the API Keys page does. Audited as
  ``cli_login.approve``.
* ``POST /v1/cli/login/requests/{user_code}/deny`` — refuse it.

And ``DELETE /v1/cli/login/key`` — `apiome logout`: the presenting key revokes itself, if it is a
CLI login key. Audited as ``cli_login.key_revoke``.

The anonymous routes carry the per-IP auth budget (:func:`enforce_auth_ip_rate_limit`); the
approve and deny routes the per-account budget.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from . import cli_login_store as store
from .auth import decode_jwt, get_user_tenants, validate_authentication
from .auth_rate_limit import enforce_auth_account_rate_limit, enforce_auth_ip_rate_limit
from .cli_login import (
    CLI_LOGIN_KEY_TTL,
    CLI_LOGIN_POLL_INTERVAL_SECONDS,
    CLI_LOGIN_REQUEST_TTL,
    POLL_ACCESS_DENIED,
    POLL_EXPIRED_TOKEN,
    POLL_INVALID_GRANT,
    POLL_PENDING,
    POLL_SLOW_DOWN,
    CliLoginApproved,
    CliLoginApproveRequest,
    CliLoginKeyIssued,
    CliLoginRequestView,
    CliLoginStarted,
    CliLoginStartRequest,
    CliLoginTokenRequest,
    CliLoginWorkspace,
    cli_login_key_name,
    generate_device_code,
    generate_user_code,
    hash_device_code,
    mint_workspace_key_secret,
    normalize_user_code,
    verification_uris,
)
from .config import settings
from .database import db
from .permissions import Action, Resource

logger = logging.getLogger(__name__)

__all__ = ["AUDIT_APPROVE", "AUDIT_KEY_REVOKE", "router"]

router = APIRouter(prefix="/v1/cli/login", tags=["cli-login"])

#: Access-audit actions this module writes.
AUDIT_APPROVE = "cli_login.approve"
AUDIT_KEY_REVOKE = "cli_login.key_revoke"

#: How many user codes to try before giving up on a start (a collision is ~1 in 10^10).
_USER_CODE_ATTEMPTS = 5

_POLL_MESSAGES = {
    POLL_PENDING: "Waiting for the login to be approved in the browser.",
    POLL_SLOW_DOWN: f"Polling too fast; wait {CLI_LOGIN_POLL_INTERVAL_SECONDS} seconds between polls.",
    POLL_ACCESS_DENIED: "The login was denied in the browser.",
    POLL_EXPIRED_TOKEN: "The login expired before it was approved. Run `apiome login` again.",
    POLL_INVALID_GRANT: "Unknown login, or its key was already collected. Run `apiome login` again.",
}

_NOT_PENDING = (
    "This login code is not waiting for approval. It may have expired, been used, or been typed "
    "wrong — run `apiome login` again for a new one."
)


def _now() -> datetime:
    """The current UTC time (a seam for tests)."""
    return datetime.now(timezone.utc)


def _poll_error(code: str) -> HTTPException:
    """A poll answer in the RFC 8628 shape, under ``detail``."""
    return HTTPException(status_code=400, detail={"error": code, "message": _POLL_MESSAGES[code]})


def _session_user_id(authorization: Optional[str]) -> str:
    """The signed-in user behind a session JWT; API keys are not accepted.

    Args:
        authorization: The ``Authorization`` header.

    Returns:
        The user id.

    Raises:
        HTTPException: 401 without a valid session JWT.
    """
    payload = decode_jwt(authorization) if authorization else None
    user_id = (payload or {}).get("user_id") or (payload or {}).get("sub")
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Sign in to Apiome to approve a CLI login (a session token is required).",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return str(user_id)


def _user_code_or_404(raw: str) -> str:
    """Canonicalize a user code from the path, or answer 404."""
    code = normalize_user_code(raw)
    if code is None:
        raise HTTPException(status_code=404, detail=_NOT_PENDING)
    return code


@router.post(
    "",
    status_code=201,
    response_model=CliLoginStarted,
    summary="Start a CLI login",
    description=(
        "Starts `apiome login`. Returns a secret `device_code` for the CLI to poll with, a "
        "`user_code` to show the person, and the apiome-ui page where they approve it. The login "
        f"expires after {int(CLI_LOGIN_REQUEST_TTL.total_seconds() // 60)} minutes. No "
        "authentication; rate-limited per client IP."
    ),
    dependencies=[Depends(enforce_auth_ip_rate_limit)],
)
def start_cli_login(body: Optional[CliLoginStartRequest] = None) -> CliLoginStarted:
    """Start a login.

    Args:
        body: Optional client name.

    Returns:
        The device code, user code and approve page.

    Raises:
        HTTPException: 503 when no free user code could be found (practically never).
    """
    store.purge_stale_requests(db)
    client_name = (body.client_name if body else None) or None
    if client_name:
        client_name = client_name.strip()[:255] or None
    expires_at = _now() + CLI_LOGIN_REQUEST_TTL
    for _ in range(_USER_CODE_ATTEMPTS):
        device_code = generate_device_code()
        user_code = generate_user_code()
        row = store.create_request(
            db,
            device_code_hash=hash_device_code(device_code),
            user_code=user_code,
            client_name=client_name,
            expires_at=expires_at,
        )
        if row:
            uri, uri_complete = verification_uris(settings.ui_public_url, user_code)
            return CliLoginStarted(
                device_code=device_code,
                user_code=user_code,
                verification_uri=uri,
                verification_uri_complete=uri_complete,
                expires_in=int(CLI_LOGIN_REQUEST_TTL.total_seconds()),
                interval=CLI_LOGIN_POLL_INTERVAL_SECONDS,
            )
    raise HTTPException(status_code=503, detail="Could not start a login. Try again.")


@router.post(
    "/token",
    response_model=CliLoginKeyIssued,
    summary="Collect a CLI login key",
    description=(
        "Polled by `apiome login` with its `device_code`. Until the login is approved this answers "
        "`400` with `detail.error` set to `authorization_pending` (keep polling), `slow_down` "
        "(polling faster than `interval`), `access_denied`, `expired_token` or `invalid_grant`. "
        "Once approved it mints a workspace API key for the approving user, valid for "
        f"{CLI_LOGIN_KEY_TTL.days} days, and returns it **once**; the login is then used up."
    ),
    dependencies=[Depends(enforce_auth_ip_rate_limit)],
)
def collect_cli_login_key(body: CliLoginTokenRequest) -> CliLoginKeyIssued:
    """Answer one poll.

    Args:
        body: The device code.

    Returns:
        The new key, once the login is approved.

    Raises:
        HTTPException: 400 with an RFC 8628 error code otherwise.
    """
    device_code_hash = hash_device_code(body.device_code)
    row = store.record_poll(db, device_code_hash)
    if row is None:
        raise _poll_error(POLL_INVALID_GRANT)
    now = _now()
    status = row["status"]
    if status == "consumed":
        raise _poll_error(POLL_INVALID_GRANT)
    if status == "denied":
        raise _poll_error(POLL_ACCESS_DENIED)
    if row["expires_at"] <= now:
        raise _poll_error(POLL_EXPIRED_TOKEN)
    if status == "pending":
        previous = row.get("previous_poll_at")
        # One second of grace for network jitter.
        if previous is not None and (now - previous).total_seconds() < CLI_LOGIN_POLL_INTERVAL_SECONDS - 1:
            raise _poll_error(POLL_SLOW_DOWN)
        raise _poll_error(POLL_PENDING)

    secret, key_prefix, key_hash = mint_workspace_key_secret()
    issued = store.collect_key(
        db,
        device_code_hash=device_code_hash,
        key_id=str(uuid.uuid4()),
        key_name=cli_login_key_name(row.get("client_name"), row["id"]),
        key_hash=key_hash,
        key_prefix=key_prefix,
        key_expires_at=now + CLI_LOGIN_KEY_TTL,
    )
    if issued is None:
        # Another poll collected it first, or the workspace went away since approval.
        raise _poll_error(POLL_INVALID_GRANT)
    return CliLoginKeyIssued(api_key=secret, **issued)


@router.get(
    "/requests/{user_code}",
    response_model=CliLoginRequestView,
    summary="Read a pending CLI login",
    description=(
        "For the apiome-ui approve page: the pending login with this user code, and the signed-in "
        "person's workspaces with whether they may approve it there (`api_keys:create`). Requires "
        "a session token; 404 when no such login is waiting."
    ),
)
def read_cli_login(user_code: str, authorization: Optional[str] = Header(None)) -> CliLoginRequestView:
    """Describe a pending login to the person approving it.

    Args:
        user_code: The code shown in the terminal.
        authorization: Session bearer token.

    Returns:
        The login and the person's workspaces.
    """
    user_id = _session_user_id(authorization)
    row = store.find_live_request(db, _user_code_or_404(user_code))
    if row is None:
        raise HTTPException(status_code=404, detail=_NOT_PENDING)
    workspaces = [
        CliLoginWorkspace(
            slug=tenant["slug"],
            name=tenant["name"],
            can_approve=db.user_has_permission(
                str(tenant["id"]), user_id, Resource.API_KEYS, Action.CREATE
            ),
        )
        for tenant in get_user_tenants(user_id)
    ]
    return CliLoginRequestView(
        user_code=row["user_code"],
        client_name=row.get("client_name"),
        status=row["status"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        workspaces=workspaces,
    )


@router.post(
    "/requests/{user_code}/approve",
    response_model=CliLoginApproved,
    summary="Approve a CLI login",
    description=(
        "Approves the pending login for one workspace. The CLI's next poll then receives a "
        f"{CLI_LOGIN_KEY_TTL.days}-day API key for that workspace, created by you. Requires a "
        "session token and `api_keys:create` in the workspace. 404 when the login is no longer "
        "waiting."
    ),
)
def approve_cli_login(
    request: Request,
    user_code: str,
    body: CliLoginApproveRequest,
    authorization: Optional[str] = Header(None),
) -> CliLoginApproved:
    """Approve a login.

    Args:
        request: The incoming request (tenant authorization).
        user_code: The code shown in the terminal.
        body: The workspace to approve it for.
        authorization: Session bearer token.

    Returns:
        The approved login.
    """
    user_id = _session_user_id(authorization)
    enforce_auth_account_rate_limit(user_id)
    code = _user_code_or_404(user_code)
    # Membership of the workspace, through the same check every tenant route uses (JWT only).
    auth_data = validate_authentication(request, body.tenant_slug, authorization=authorization, x_api_key=None)
    if not db.user_has_permission(auth_data["tenant_id"], user_id, Resource.API_KEYS, Action.CREATE):
        raise HTTPException(
            status_code=403,
            detail=(
                "You need permission to create API keys in this workspace to approve a CLI login. "
                "Ask a workspace administrator, or choose another workspace."
            ),
        )
    row = store.approve_request(db, user_code=code, user_id=user_id, tenant_id=str(auth_data["tenant_id"]))
    if row is None:
        raise HTTPException(status_code=404, detail=_NOT_PENDING)
    _audit(
        tenant_id=str(auth_data["tenant_id"]),
        action=AUDIT_APPROVE,
        actor_id=user_id,
        actor_label=auth_data.get("user_email") or auth_data.get("user_name"),
        target=row["id"],
        detail={"userCode": code, "clientName": row.get("client_name")},
    )
    return CliLoginApproved(user_code=code, status=row["status"], tenant_slug=auth_data["tenant_slug"])


@router.post(
    "/requests/{user_code}/deny",
    response_model=CliLoginApproved,
    summary="Deny a CLI login",
    description=(
        "Refuses the pending login; the CLI stops with `access_denied`. Requires a session token. "
        "404 when the login is no longer waiting."
    ),
)
def deny_cli_login(user_code: str, authorization: Optional[str] = Header(None)) -> CliLoginApproved:
    """Deny a login.

    Args:
        user_code: The code shown in the terminal.
        authorization: Session bearer token.

    Returns:
        The denied login.
    """
    user_id = _session_user_id(authorization)
    enforce_auth_account_rate_limit(user_id)
    code = _user_code_or_404(user_code)
    row = store.deny_request(db, user_code=code, user_id=user_id)
    if row is None:
        raise HTTPException(status_code=404, detail=_NOT_PENDING)
    return CliLoginApproved(user_code=code, status=row["status"])


@router.delete(
    "/key",
    status_code=204,
    summary="Revoke this CLI login key",
    description=(
        "Used by `apiome logout`: revokes the API key presented in `X-API-Key`, if `apiome login` "
        "created it. Any other key is refused with 409 — revoke it from the API Keys page."
    ),
)
def revoke_cli_login_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> Response:
    """Revoke the presenting CLI login key.

    Args:
        x_api_key: The key to revoke.

    Returns:
        204 once revoked.
    """
    key = db.validate_api_key(x_api_key) if x_api_key else None
    if not key:
        raise HTTPException(
            status_code=401, detail="Invalid or expired API key", headers={"WWW-Authenticate": "API-Key"}
        )
    revoked = store.revoke_cli_login_key(db, str(key["id"]))
    if revoked is None:
        raise HTTPException(status_code=401, detail="Invalid or expired API key")
    if not revoked:
        raise HTTPException(
            status_code=409,
            detail="This key was not created by `apiome login`. Revoke it from the API Keys page.",
        )
    _audit(
        tenant_id=str(key["tenant_id"]),
        action=AUDIT_KEY_REVOKE,
        actor_id=key.get("created_by_user_id"),
        actor_label=None,
        target=str(key["id"]),
        detail={"source": "apiome logout"},
    )
    return Response(status_code=204)


def _audit(
    *,
    tenant_id: str,
    action: str,
    actor_id: Optional[Any],
    actor_label: Optional[str],
    target: str,
    detail: Dict[str, Any],
) -> None:
    """Write one metadata-only access-audit row; a failure is logged, never raised.

    Args:
        tenant_id: The workspace.
        action: :data:`AUDIT_APPROVE` or :data:`AUDIT_KEY_REVOKE`.
        actor_id: The acting user.
        actor_label: Their email or name, when known.
        target: The login request or key id.
        detail: Metadata (never a secret).
    """
    try:
        db.write_access_audit(
            tenant_id=tenant_id,
            action=action,
            actor_id=str(actor_id) if actor_id else None,
            actor_label=actor_label,
            target=target,
            source="api",
            detail=detail,
        )
    except Exception:  # noqa: BLE001 - auditing never fails the action
        logger.warning("Failed to audit %s for tenant %s", action, tenant_id, exc_info=True)
