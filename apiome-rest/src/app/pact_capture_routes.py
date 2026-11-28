"""``/v1/tenants/{tenant_slug}/pact-captures`` — consumer-tagged mock capture, PFX-9.1 (#7319).

Calls to the hosted mock tagged ``X-Mock-Capture: <consumer>@<version>``, or made through a private
capture URL, are recorded by the mock runtime for that consumer and version. These routes read them
back and manage what records them:

* ``GET …/pact-captures/sessions`` — the live sessions, newest activity first (``pacts:view``);
* ``GET …/pact-captures/sessions/{id}`` — one session and a page of its calls: method, path, the
  spec's path template, status, origin (spec, scenario, session, chaos, forced, off-spec, rejected),
  and the request and response as stored after redaction (``pacts:view``);
* ``DELETE …/pact-captures/sessions/{id}`` — delete a session and its calls (``pacts:delete``);
* ``GET`` / ``POST …/pact-captures/links`` and ``DELETE …/pact-captures/links/{id}`` — private
  capture URLs for clients that cannot add a header (``pacts:view`` / ``pacts:create`` /
  ``pacts:edit``); the token is shown once, on create;
* ``GET`` / ``PUT …/pact-captures/settings`` — how many days captures are kept (``pacts:view`` /
  ``pacts:delete``), and calls refused for the whole workspace.

The tenant is always the authenticated one, never the URL's. An unknown field is refused (422).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .auth import validate_authentication
from .consumer_contract_store import actor_from_auth
from .database import db
from .keyset_pagination import cursor_query, limit_query
from .pact_capture import (
    DEFAULT_LINK_DAYS,
    MAX_CALLS_PER_SESSION,
    MAX_LINK_DAYS,
    MAX_LIVE_SESSIONS_PER_TENANT,
    MAX_NAME_CHARS,
    MAX_RETENTION_DAYS,
    MIN_RETENTION_DAYS,
    name_problem,
)
from .pact_capture_store import (
    CALLS_ORDER,
    LINKS_ORDER,
    SESSIONS_ORDER,
    CaptureNotFoundError,
    create_link,
    delete_session,
    list_calls,
    list_links,
    list_sessions,
    read_session,
    read_settings,
    revoke_link,
    save_retention,
)
from .permissions import Action, Resource, enforce_permission, has_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pacticipants"])

_BASE = "/{tenant_slug}/pact-captures"

Origin = Literal["spec", "scenario", "session", "chaos", "forced", "off-spec", "rejected"]


# ---------------------------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------------------------


class CaptureLimits(BaseModel):
    """The fixed bounds of consumer capture."""

    max_calls_per_session: int = Field(description="Calls one session stores; more are counted as `session-full`.")
    max_live_sessions: int = Field(description="Live sessions one workspace may have; more are counted on it.")
    min_retention_days: int
    max_retention_days: int
    max_link_days: int


class CaptureSettings(BaseModel):
    """How long captures are kept, and calls refused for the whole workspace."""

    retention_days: int = Field(description="Days a capture is kept after it is recorded.")
    configured: bool = Field(description="`false` while the default is in force.")
    refused_calls: int = Field(description="Tagged calls no session could take (the workspace had too many).")
    last_refused_reason: Optional[str] = None
    last_refused_at: Optional[datetime] = None
    updated_by_label: Optional[str] = None
    updated_at: Optional[datetime] = None
    can_edit: bool = Field(description="Whether the caller may change the retention (`pacts:delete`).")
    limits: CaptureLimits


class CaptureSettingsSave(BaseModel):
    """``PUT …/pact-captures/settings``."""

    model_config = ConfigDict(extra="forbid")

    retention_days: int = Field(ge=MIN_RETENTION_DAYS, le=MAX_RETENTION_DAYS, description="Days to keep captures.")


class CaptureSession(BaseModel):
    """Calls recorded for one consumer and version against one mock version."""

    id: str
    project: str
    version: str
    consumer: str
    consumer_version: str
    first_call_at: datetime
    last_call_at: datetime
    call_count: int = Field(description="Calls stored.")
    refused_count: int = Field(description="Calls that reached the writer but were not stored.")
    refused: Dict[str, int] = Field(
        description="Refused calls by reason: `session-full`, `credential-residual`.",
    )
    expires_at: datetime = Field(description="When the session goes, unless more calls arrive.")


class CaptureSessionList(BaseModel):
    """A page of sessions."""

    sessions: List[CaptureSession]
    count: int
    has_more: bool
    next_cursor: Optional[str] = None
    retention_days: int


class CaptureCall(BaseModel):
    """One recorded call, as stored after redaction."""

    id: str
    captured_at: datetime
    via: Literal["header", "url"]
    link_id: Optional[str] = None
    method: str
    path: str
    path_template: Optional[str] = Field(default=None, description="The spec's path; `null` when off-spec.")
    operation_key: Optional[str] = None
    status: int
    origin: Origin
    origin_detail: Optional[str] = Field(default=None, description="The mock's one-line account of the answer.")
    scenario: Optional[str] = None
    mock_session: Optional[str] = Field(default=None, description="Digest of the `X-Mock-Session` token.")
    request: Dict[str, Any] = Field(description="`method`, `path`, `query`, `headers`, `body`, `mediaType`.")
    response: Dict[str, Any] = Field(description="`status`, `headers`, `body`, `mediaType`.")
    redactions: List[Dict[str, str]] = Field(description="Each removal: `pointer`, `rule`, `reason`.")
    redaction_count: int


class CaptureSessionDetail(BaseModel):
    """A session and a page of its calls."""

    session: CaptureSession
    calls: List[CaptureCall]
    count: int
    has_more: bool
    next_cursor: Optional[str] = None


class CaptureLink(BaseModel):
    """A private capture URL (never its token, except right after it is created)."""

    id: str
    project: str
    version: str
    consumer: str
    consumer_version: str
    token_prefix: str
    state: Literal["live", "revoked", "expired"]
    created_by_label: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    revoked_at: Optional[datetime] = None


class CaptureLinkCreated(CaptureLink):
    """A new capture URL with its token — shown this once."""

    token: str
    path: str = Field(description="`/{tenant}/{project}/{version}/~capture/{token}`; append the API path.")
    url: str


class CaptureLinkList(BaseModel):
    """A page of capture URLs."""

    links: List[CaptureLink]
    count: int
    has_more: bool
    next_cursor: Optional[str] = None


class CaptureLinkCreate(BaseModel):
    """``POST …/pact-captures/links``."""

    model_config = ConfigDict(extra="forbid")

    project: str = Field(min_length=1, max_length=200, description="Project slug of the mocked API.")
    version: str = Field(min_length=1, max_length=200, description="Version label of the mocked API.")
    consumer: str = Field(max_length=MAX_NAME_CHARS, description="Whose calls these are (`Orders UI`).")
    consumer_version: str = Field(max_length=MAX_NAME_CHARS, description="That consumer's version (`3.4.0`).")
    expires_in_days: int = Field(default=DEFAULT_LINK_DAYS, ge=1, le=MAX_LINK_DAYS)

    @field_validator("consumer", "consumer_version")
    @classmethod
    def _name(cls, value: str, info: Any) -> str:
        problem = name_problem(value, "consumer" if info.field_name == "consumer" else "version")
        if problem:
            raise ValueError(problem)
        return value


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _not_found(exc: CaptureNotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)})


def _settings(tenant_id: str, *, can_edit: bool) -> CaptureSettings:
    return CaptureSettings(
        **read_settings(db.execute_query, tenant_id),
        can_edit=can_edit,
        limits=_LIMITS,
    )


_LIMITS = CaptureLimits(
    max_calls_per_session=MAX_CALLS_PER_SESSION,
    max_live_sessions=MAX_LIVE_SESSIONS_PER_TENANT,
    min_retention_days=MIN_RETENTION_DAYS,
    max_retention_days=MAX_RETENTION_DAYS,
    max_link_days=MAX_LINK_DAYS,
)

_PAGING = "Paged with `limit` (default 50, at most 200) and `cursor` (the previous page's `next_cursor`)."


# ---------------------------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------------------------


@router.get(
    f"{_BASE}/sessions",
    response_model=CaptureSessionList,
    summary="List mock capture sessions",
    description=(
        "The workspace's live capture sessions, newest activity first. A session holds the calls made to one "
        "mock version with `X-Mock-Capture: <consumer>@<version>`, or through a capture URL, for that consumer "
        "and version. Filter with `project`, `version` and `consumer` (exact). Expired sessions are never "
        f"listed.\n\n{_PAGING}\n\nRequires `pacts:view`."
    ),
)
def list_capture_sessions(
    tenant_slug: str,
    project: Optional[str] = Query(default=None, max_length=200),
    version: Optional[str] = Query(default=None, max_length=200),
    consumer: Optional[str] = Query(default=None, max_length=MAX_NAME_CHARS),
    limit: int = limit_query(),
    cursor: Optional[str] = cursor_query(),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CaptureSessionList:
    """List sessions.

    Raises:
        HTTPException: 400 for a malformed cursor, 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    after = SESSIONS_ORDER.parse(cursor)
    rows = list_sessions(
        db.execute_query,
        tenant_id,
        project=project,
        version=version,
        consumer=consumer,
        limit=limit + 1,
        cursor=after,
    )
    page = SESSIONS_ORDER.page(rows, limit)
    return CaptureSessionList(
        sessions=[CaptureSession(**row) for row in page.items],
        count=len(page.items),
        has_more=page.has_more,
        next_cursor=page.next_cursor,
        retention_days=read_settings(db.execute_query, tenant_id)["retention_days"],
    )


@router.get(
    f"{_BASE}/sessions/{{session_id}}",
    response_model=CaptureSessionDetail,
    summary="Read a mock capture session and its calls",
    description=(
        "One session and a page of its calls in the order they were made. Each call has its method, path, the "
        "spec's path template (`null` when nothing in the spec matched), status, and `origin`: `spec`, "
        "`scenario`, `session` (stateful `X-Mock-Session` CRUD), `chaos` (an injected error), `forced` "
        "(`Prefer: code=`), `off-spec` or `rejected` (the mock refused the request). Request and response are "
        "stored after the mock's redaction rules; `redactions` says what was removed and why. An expired or "
        f"unknown session is `404 capture-session-not-found`.\n\n{_PAGING}\n\nRequires `pacts:view`."
    ),
)
def read_capture_session(
    tenant_slug: str,
    session_id: str,
    limit: int = limit_query(),
    cursor: Optional[str] = cursor_query(),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CaptureSessionDetail:
    """Read a session and its calls.

    Raises:
        HTTPException: 400 for a malformed cursor, 403 without ``pacts:view``, 404 for an unknown,
            expired or other workspace's session.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    after = CALLS_ORDER.parse(cursor)
    try:
        session = read_session(db.execute_query, tenant_id, session_id)
    except CaptureNotFoundError as exc:
        raise _not_found(exc) from exc
    rows = list_calls(db.execute_query, tenant_id, session_id, limit=limit + 1, cursor=after)
    page = CALLS_ORDER.page(rows, limit)
    return CaptureSessionDetail(
        session=CaptureSession(**session),
        calls=[CaptureCall(**{**row, "id": str(row["id"])}) for row in page.items],
        count=len(page.items),
        has_more=page.has_more,
        next_cursor=page.next_cursor,
    )


@router.delete(
    f"{_BASE}/sessions/{{session_id}}",
    status_code=204,
    summary="Delete a mock capture session",
    description=(
        "Delete the session and every call in it, so the next tagged call starts a new one. Audited as "
        "`pacts.capture.session.delete`.\n\nRequires `pacts:delete`."
    ),
)
def delete_capture_session(
    tenant_slug: str,
    session_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Delete a session.

    Raises:
        HTTPException: 403 without ``pacts:delete``; 404 for an unknown or other workspace's session.
    """
    user_id = enforce_permission(
        db, auth_data, Resource.PACTS, Action.DELETE, target=f"pact-captures/sessions/{session_id}"
    )
    _ = tenant_slug
    try:
        delete_session(db, _tenant_id(auth_data), session_id, actor=actor_from_auth(auth_data, user_id))
    except CaptureNotFoundError as exc:
        raise _not_found(exc) from exc
    return Response(status_code=204)


# ---------------------------------------------------------------------------------------------
# Capture URLs
# ---------------------------------------------------------------------------------------------


@router.get(
    f"{_BASE}/links",
    response_model=CaptureLinkList,
    summary="List mock capture URLs",
    description=(
        "The workspace's private capture URLs, newest first, with `state` `live`, `revoked` or `expired`. The "
        f"token is never shown again after creation; `token_prefix` identifies it.\n\n{_PAGING}\n\n"
        "Requires `pacts:view`."
    ),
)
def list_capture_links(
    tenant_slug: str,
    limit: int = limit_query(),
    cursor: Optional[str] = cursor_query(),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CaptureLinkList:
    """List capture URLs.

    Raises:
        HTTPException: 400 for a malformed cursor, 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    _ = tenant_slug
    after = LINKS_ORDER.parse(cursor)
    rows = list_links(db.execute_query, _tenant_id(auth_data), limit=limit + 1, cursor=after)
    page = LINKS_ORDER.page(rows, limit)
    return CaptureLinkList(
        links=[CaptureLink(**row) for row in page.items],
        count=len(page.items),
        has_more=page.has_more,
        next_cursor=page.next_cursor,
    )


@router.post(
    f"{_BASE}/links",
    response_model=CaptureLinkCreated,
    status_code=201,
    summary="Create a mock capture URL",
    description=(
        "A private URL for clients that cannot add the `X-Mock-Capture` header: every call made under "
        "`{url}/<API path>` is served by the mock version and recorded for `consumer` at `consumer_version`. "
        "The token in it is shown **once**, in this response; only its digest is stored. The URL tags calls "
        "only — it does not open a private mock, which still needs its API key. It lasts `expires_in_days` "
        f"(default {DEFAULT_LINK_DAYS}, at most {MAX_LINK_DAYS}). Audited as `pacts.capture.link.create`.\n\n"
        "Requires `pacts:create`."
    ),
)
def create_capture_link(
    tenant_slug: str,
    body: CaptureLinkCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CaptureLinkCreated:
    """Create a capture URL.

    Raises:
        HTTPException: 403 without ``pacts:create``; 404 ``capture-version-not-found``; 422 for an
            invalid consumer or version, or an unknown field.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE, target="pact-captures/links")
    _ = tenant_slug
    try:
        link = create_link(
            db,
            _tenant_id(auth_data),
            project=body.project,
            version=body.version,
            consumer=body.consumer,
            consumer_version=body.consumer_version,
            expires_in_days=body.expires_in_days,
            actor=actor_from_auth(auth_data, user_id),
        )
    except CaptureNotFoundError as exc:
        raise _not_found(exc) from exc
    return CaptureLinkCreated(**link)


@router.delete(
    f"{_BASE}/links/{{link_id}}",
    response_model=CaptureLink,
    summary="Revoke a mock capture URL",
    description=(
        "Stop recording through the URL. Calls made through it are still served; within 30 seconds (the "
        "mock's link cache) they are answered `X-Mock-Capture: not-recorded`. Revoking twice is harmless. "
        "Audited as `pacts.capture.link.revoke`.\n\nRequires `pacts:edit`."
    ),
)
def revoke_capture_link(
    tenant_slug: str,
    link_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CaptureLink:
    """Revoke a capture URL.

    Raises:
        HTTPException: 403 without ``pacts:edit``; 404 for an unknown or other workspace's link.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT, target=f"pact-captures/links/{link_id}")
    _ = tenant_slug
    try:
        return CaptureLink(**revoke_link(db, _tenant_id(auth_data), link_id, actor=actor_from_auth(auth_data, user_id)))
    except CaptureNotFoundError as exc:
        raise _not_found(exc) from exc


# ---------------------------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------------------------


@router.get(
    f"{_BASE}/settings",
    response_model=CaptureSettings,
    summary="Read the mock capture settings",
    description=(
        "How many days captures are kept (default 7), the fixed limits, and how many tagged calls were refused "
        "because the workspace already had the most live sessions it may. `can_edit` is `pacts:delete`.\n\n"
        "Requires `pacts:view`."
    ),
)
def read_capture_settings(
    tenant_slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> CaptureSettings:
    """Read the settings.

    Raises:
        HTTPException: 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    _ = tenant_slug
    can_edit = bool(has_permission(db, auth_data, Resource.PACTS, Action.DELETE))
    return _settings(_tenant_id(auth_data), can_edit=can_edit)


@router.put(
    f"{_BASE}/settings",
    response_model=CaptureSettings,
    summary="Save the mock capture retention",
    description=(
        f"Keep captures `retention_days` ({MIN_RETENTION_DAYS}–{MAX_RETENTION_DAYS}). The new value applies to "
        "calls recorded from now on; captures already stored keep the expiry they were written with. Audited "
        "as `pacts.capture.settings`.\n\nRequires `pacts:delete`."
    ),
)
def save_capture_settings(
    tenant_slug: str,
    body: CaptureSettingsSave,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CaptureSettings:
    """Save the retention.

    Raises:
        HTTPException: 403 without ``pacts:delete``; 422 outside the bounds or for an unknown field.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.DELETE, target="pact-captures/settings")
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    save_retention(db, tenant_id, body.retention_days, actor=actor_from_auth(auth_data, user_id))
    return _settings(tenant_id, can_edit=True)
