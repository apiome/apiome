"""``/v1/tenants/{tenant_slug}/projects/{project_ref}/presence`` — COL-4.1 (#4525).

Who has a project open, and which elements are being edited. Two transports over one store
(:mod:`app.presence_store`):

* **HTTP** — ``POST …/presence/heartbeat`` (renew + snapshot), ``GET …/presence`` (snapshot),
  ``POST …/presence/leave``, and per-element lock routes ``PUT|DELETE …/presence/locks/{key}`` plus
  ``POST …/locks/{key}/request-takeover`` and ``…/take-over``. The UI uses these through its BFF.
* **WebSocket** — ``…/presence/ws``: the push channel. The first client message must be
  ``{"type":"auth","authorization":"Bearer <jwt>"}``; after that the client sends ``heartbeat``,
  ``lock``, ``unlock``, ``request_takeover`` and ``take_over`` messages and receives a
  ``snapshot`` after each, plus one every ``PUSH_INTERVAL_SECONDS`` so others' changes arrive
  without polling. Closing the socket releases the tab's presence and locks immediately. API keys
  use the HTTP routes.

**Authorization.** Having a project open is what ``projects:view`` grants, so every route requires
it (a Viewer shows up in the avatars). Locks are advisory and need no further right; the write
routes of the project still enforce their own permissions.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from starlette.requests import HTTPConnection

from . import presence_store
from .auth import validate_authentication
from .comment_store import resolve_project
from .comments import CommentValidationError
from .config import settings
from .database import db
from .permissions import Action, Resource, enforce_permission
from .presence import (
    CODE_INVALID,
    CODE_LOCK_HELD,
    CODE_LOCK_NOT_FOUND,
    CODE_PROJECT_NOT_FOUND,
    CODE_TAKEOVER_TOO_EARLY,
    HeartbeatRequest,
    PresenceSnapshot,
    PresenceValidationError,
    validate_session_id,
    validate_view,
)
from .rate_limit import FixedWindowRateLimiter

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["presence"])

_BASE = "/{tenant_slug}/projects/{project_ref}/presence"

#: How often the socket pushes a fresh snapshot to a connected tab.
PUSH_INTERVAL_SECONDS = 5.0
#: Largest client frame accepted on the socket.
MAX_FRAME_BYTES = 8192

_STATUS_BY_CODE = {
    CODE_PROJECT_NOT_FOUND: 404,
    CODE_LOCK_NOT_FOUND: 404,
    CODE_LOCK_HELD: 409,
    CODE_TAKEOVER_TOO_EARLY: 409,
}

_limiter = FixedWindowRateLimiter()


def _http_error(exc: PresenceValidationError) -> HTTPException:
    """Translate a refusal into an ``HTTPException`` carrying ``{"code", "message"}``."""
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(exc.code, 400),
        detail={"code": exc.code, "message": str(exc)},
    )


def _enforce_rate(tenant_id: str, user_id: str) -> None:
    """Count one presence call against the user's budget (heartbeats are frequent but bounded).

    Raises:
        HTTPException: 429 over ``presence_rate_limit_per_minute``.
    """
    if not settings.rate_limit_enabled:
        return
    limit = max(1, settings.presence_rate_limit_per_minute)
    window = max(1, settings.rate_limit_window_seconds)
    allowed, _remaining, _reset, retry_after = _limiter.check(
        f"presence:{tenant_id}:{user_id}", limit, window, time.monotonic()
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"code": "presence-rate-limited", "message": "Too many presence updates."},
            headers={"Retry-After": str(retry_after)},
        )


def _context(auth_data: Dict[str, Any], project_ref: str) -> Tuple[str, str, str]:
    """Require ``projects:view``, resolve the project, and rate-limit the call.

    Returns:
        ``(tenant_id, user_id, project_id)``.

    Raises:
        HTTPException: 403 without access or tenant, 404 for an unknown project, 429 over budget.
    """
    user_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    try:
        project = resolve_project(str(tenant_id), project_ref)
    except CommentValidationError as exc:
        raise HTTPException(
            status_code=404, detail={"code": CODE_PROJECT_NOT_FOUND, "message": str(exc)}
        ) from exc
    _enforce_rate(str(tenant_id), user_id)
    return str(tenant_id), user_id, str(project["id"])


def _session(value: str) -> str:
    try:
        return validate_session_id(value)
    except PresenceValidationError as exc:
        raise _http_error(exc) from exc


@router.get(_BASE, response_model=PresenceSnapshot, summary="Who is viewing a project, and what is locked")
def get_presence(
    tenant_slug: str, project_ref: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> PresenceSnapshot:
    """Read the project's live viewers and element locks without announcing the caller."""
    _tenant, _user, project_id = _context(auth_data, project_ref)
    return presence_store.snapshot(project_id)


@router.post(
    f"{_BASE}/heartbeat",
    response_model=PresenceSnapshot,
    summary="Announce a tab and renew its locks",
)
def post_heartbeat(
    tenant_slug: str,
    project_ref: str,
    body: HeartbeatRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PresenceSnapshot:
    """Mark the tab present for the lease, renew the locks it holds, and read the snapshot.

    ``lost`` in the answer names held keys that another tab now holds — the notice a takeover
    happened. Clients heartbeat at least twice per ``ttl_seconds``.
    """
    tenant_id, user_id, project_id = _context(auth_data, project_ref)
    try:
        return presence_store.heartbeat(
            project_id, tenant_id, user_id, validate_session_id(body.session_id),
            validate_view(body.view), body.held,
        )
    except PresenceValidationError as exc:
        raise _http_error(exc) from exc


@router.post(f"{_BASE}/leave", status_code=204, summary="Leave a project (release presence and locks)")
def post_leave(
    tenant_slug: str,
    project_ref: str,
    body: HeartbeatRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> None:
    """Drop the tab's presence and every lock it holds. Safe to repeat."""
    _tenant, _user, project_id = _context(auth_data, project_ref)
    presence_store.leave(project_id, _session(body.session_id))


def _lock_action(name: str, auth_data: Dict[str, Any], project_ref: str, session_id: str, key: str):
    """Run one lock action of the store for the caller and return its snapshot."""
    tenant_id, user_id, project_id = _context(auth_data, project_ref)
    session = _session(session_id)
    try:
        if name == "acquire":
            return presence_store.acquire_lock(project_id, tenant_id, user_id, session, key)
        if name == "release":
            return presence_store.release_lock(project_id, session, key)
        if name == "request":
            return presence_store.request_takeover(project_id, user_id, session, key)
        return presence_store.take_over(project_id, tenant_id, user_id, session, key)
    except PresenceValidationError as exc:
        raise _http_error(exc) from exc


@router.put(f"{_BASE}/locks/{{element_key:path}}", response_model=PresenceSnapshot, summary="Lock an element")
def put_lock(
    tenant_slug: str, project_ref: str, element_key: str, session_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PresenceSnapshot:
    """Mark an element as being edited by ``session_id``. ``409 presence-lock-held`` if another live tab holds it."""
    return _lock_action("acquire", auth_data, project_ref, session_id, element_key)


@router.delete(f"{_BASE}/locks/{{element_key:path}}", response_model=PresenceSnapshot, summary="Unlock an element")
def delete_lock(
    tenant_slug: str, project_ref: str, element_key: str, session_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PresenceSnapshot:
    """Release a lock the tab holds."""
    return _lock_action("release", auth_data, project_ref, session_id, element_key)


@router.post(
    f"{_BASE}/request-takeover/{{element_key:path}}",
    response_model=PresenceSnapshot,
    summary="Ask the holder to hand an element over",
)
def post_request_takeover(
    tenant_slug: str, project_ref: str, element_key: str, session_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PresenceSnapshot:
    """Notify the holder (on their next heartbeat) that the caller wants the element."""
    return _lock_action("request", auth_data, project_ref, session_id, element_key)


@router.post(
    f"{_BASE}/take-over/{{element_key:path}}",
    response_model=PresenceSnapshot,
    summary="Take an element over after asking",
)
def post_take_over(
    tenant_slug: str, project_ref: str, element_key: str, session_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PresenceSnapshot:
    """Steal a lock once the grace period since the caller's request has passed; the previous holder sees it in ``lost``."""
    return _lock_action("takeover", auth_data, project_ref, session_id, element_key)


# ---------------------------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------------------------


class _WsRequest:
    """The slice of a request ``validate_authentication`` reads; a socket is always JWT here."""

    method = "GET"


async def _ws_auth(websocket: WebSocket, tenant_slug: str) -> Dict[str, Any]:
    """Read the first frame, which must authenticate, and return the principal.

    Raises:
        HTTPException: when the frame is not an auth frame or the token is refused.
    """
    raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
    if len(raw) > MAX_FRAME_BYTES:
        raise HTTPException(status_code=400, detail="frame too large")
    frame = json.loads(raw)
    token = frame.get("authorization") if frame.get("type") == "auth" else None
    if not isinstance(token, str) or not token:
        raise HTTPException(status_code=401, detail="first frame must be an auth frame")
    return await run_in_threadpool(
        validate_authentication, _WsRequest(), tenant_slug, token, None  # type: ignore[arg-type]
    )


async def _send(websocket: WebSocket, kind: str, payload: Any) -> None:
    await websocket.send_text(json.dumps({"type": kind, **payload}))


@router.websocket(f"{_BASE}/ws")
async def presence_socket(websocket: WebSocket, tenant_slug: str, project_ref: str) -> None:
    """The push channel for one tab. See the module docstring for the frame protocol."""
    await websocket.accept()
    session_id = None
    project_id = None
    try:
        auth_data = await _ws_auth(websocket, tenant_slug)
        tenant_id, user_id, project_id = await run_in_threadpool(_context, auth_data, project_ref)
        held: list = []
        view = "project"

        async def current() -> PresenceSnapshot:
            return await run_in_threadpool(
                presence_store.heartbeat, project_id, tenant_id, user_id, session_id, view, held
            )

        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=PUSH_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                if session_id:
                    await _send(websocket, "snapshot", (await current()).model_dump())
                continue
            if len(raw) > MAX_FRAME_BYTES:
                await websocket.close(code=1009)
                return
            frame = json.loads(raw)
            kind = frame.get("type")
            try:
                if kind == "heartbeat":
                    session_id = validate_session_id(frame.get("session_id", ""))
                    view = validate_view(frame.get("view"))
                    held = list(frame.get("held") or [])[:100]
                    await _send(websocket, "snapshot", (await current()).model_dump())
                    continue
                if not session_id:
                    raise PresenceValidationError(CODE_INVALID, "send a heartbeat first")
                key = frame.get("element_key", "")
                actions = {
                    "lock": lambda: presence_store.acquire_lock(project_id, tenant_id, user_id, session_id, key),
                    "unlock": lambda: presence_store.release_lock(project_id, session_id, key),
                    "request_takeover": lambda: presence_store.request_takeover(project_id, user_id, session_id, key),
                    "take_over": lambda: presence_store.take_over(project_id, tenant_id, user_id, session_id, key),
                }
                if kind not in actions:
                    raise PresenceValidationError(CODE_INVALID, f"unknown frame type '{kind}'")
                snap = await run_in_threadpool(actions[kind])
                if kind in ("lock", "take_over") and key not in held:
                    held.append(key)
                if kind == "unlock" and key in held:
                    held.remove(key)
                await _send(websocket, "snapshot", snap.model_dump())
            except PresenceValidationError as exc:
                await _send(websocket, "error", {"code": exc.code, "message": str(exc)})
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except HTTPException as exc:
        await websocket.close(code=1008, reason=str(exc.detail)[:100])
    except (ValueError, AttributeError):
        await websocket.close(code=1003)
    finally:
        if session_id and project_id:
            await run_in_threadpool(presence_store.leave, project_id, session_id)
