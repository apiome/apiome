"""Server-to-server write path into the ``auth_events`` ledger (EID-1.1, #5011).

Since the Better Auth cutover the sign-in flow runs in apiome-ui, but the hash-chained
``auth_events`` ledger (V193) is written only here, in REST. Enterprise SSO (EID-1.1) must record
every attempt — success and failure — with ``provider = sso:<slug>``, so apiome-ui's BFF posts each
outcome to ``POST /v1/internal/auth-events``.

Security posture:

* **Service-token gated** with the shared ``INTERNAL_SERVICE_TOKEN``, exactly like the resolved
  provider read paths (:func:`require_internal_service`); never proxied to a browser.
* **Narrow vocabulary.** Only the sign-in outcomes (``sign_in`` / ``sign_up`` / ``link``) are
  accepted — the admin-only event types (``two_factor_reset``, ``sso_provider``) cannot be forged
  through this endpoint — and every string is shape-checked against the ledger's column limits.
* **No raw network PII.** The caller sends the client IP and User-Agent; they are reduced to
  SHA-256 digests (:func:`app.auth_events.hash_client_value`) before anything is stored.
* **Best-effort.** The ledger write never fails the sign-in it records, so this answers ``202``
  once the request is valid, whatever the database does.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from .auth_events import (
    AUTH_EVENT_OUTCOMES,
    EVENT_LINK,
    EVENT_SIGN_IN,
    EVENT_SIGN_UP,
    hash_client_value,
)
from .auth_provider_resolved_routes import require_internal_service
from .database import db

router = APIRouter(prefix="/v1/internal/auth-events", tags=["internal-auth-events"])

#: Event types an outside caller may record: sign-in outcomes only.
CALLER_EVENT_TYPES = frozenset({EVENT_SIGN_IN, EVENT_SIGN_UP, EVENT_LINK})

_PROVIDER_RE = re.compile(r"^(?:sso:[a-z0-9][a-z0-9-]{1,27}|[a-z0-9][a-z0-9_-]{0,31})$")
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
#: The serialized ``detail`` may not exceed this: it is context, not a payload.
MAX_DETAIL_BYTES = 2048


class AuthEventCreateRequest(BaseModel):
    """Body of ``POST /v1/internal/auth-events``."""

    model_config = {"extra": "forbid"}

    event_type: str = Field(..., description="`sign_in`, `sign_up` or `link`.")
    outcome: str = Field(..., description="`success` or `failure`.")
    provider: Optional[str] = Field(None, description="`sso:<slug>` or an OAuth provider slug.")
    user_id: Optional[str] = Field(None, description="The resolved user, when there is one.")
    user_label: Optional[str] = Field(None, max_length=320, description="The email the attempt carried.")
    error_code: Optional[str] = Field(None, description="Stable error code on failure.")
    ip: Optional[str] = Field(None, max_length=128, description="Client IP; hashed, never stored.")
    user_agent: Optional[str] = Field(None, max_length=1024, description="Client User-Agent; hashed, never stored.")
    detail: Optional[Dict[str, Any]] = Field(None, description="Small structured context, no secrets.")

    @field_validator("event_type")
    @classmethod
    def _event_type(cls, value: str) -> str:
        if value not in CALLER_EVENT_TYPES:
            raise ValueError(f"event_type must be one of {sorted(CALLER_EVENT_TYPES)}")
        return value

    @field_validator("outcome")
    @classmethod
    def _outcome(cls, value: str) -> str:
        if value not in AUTH_EVENT_OUTCOMES:
            raise ValueError("outcome must be success or failure")
        return value

    @field_validator("provider")
    @classmethod
    def _provider(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not _PROVIDER_RE.match(value):
            raise ValueError("provider must be sso:<slug> or a provider slug of at most 32 characters")
        return value

    @field_validator("error_code")
    @classmethod
    def _error_code(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not _CODE_RE.match(value):
            raise ValueError("error_code must be 1–64 letters, digits, hyphens or underscores")
        return value

    @field_validator("user_id")
    @classmethod
    def _user_id(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not _UUID_RE.match(value):
            raise ValueError("user_id must be a uuid")
        return value

    @field_validator("detail")
    @classmethod
    def _detail(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if value is not None and len(json.dumps(value, default=str)) > MAX_DETAIL_BYTES:
            raise ValueError(f"detail must serialize to at most {MAX_DETAIL_BYTES} bytes")
        return value


class AuthEventAccepted(BaseModel):
    """Payload of a recorded event."""

    accepted: bool = True


@router.post(
    "",
    response_model=AuthEventAccepted,
    status_code=202,
    responses={
        401: {"description": "No internal service token presented."},
        403: {"description": "Internal service token invalid."},
        422: {"description": "The event is outside the accepted vocabulary or limits."},
        503: {"description": "Disabled: no INTERNAL_SERVICE_TOKEN configured."},
    },
)
async def record_auth_event(
    payload: AuthEventCreateRequest, _: None = Depends(require_internal_service)
) -> AuthEventAccepted:
    """Append one sign-in outcome to ``auth_events`` (best-effort; hashes the IP and User-Agent)."""
    db.write_auth_event(
        event_type=payload.event_type,
        outcome=payload.outcome,
        provider=payload.provider,
        user_id=payload.user_id,
        user_label=(payload.user_label or "").strip().lower() or None,
        error_code=payload.error_code,
        ip_hash=hash_client_value(payload.ip),
        user_agent_hash=hash_client_value(payload.user_agent),
        detail=payload.detail,
    )
    return AuthEventAccepted()
