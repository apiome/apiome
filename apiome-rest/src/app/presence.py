"""Project presence and element soft locks — COL-4.1 (#4525): models, codes, and validation.

Presence answers "who else has this project open, and where"; a soft lock answers "who is editing
this element right now". Both are **leases**: a client heartbeats to keep them alive and a crashed
tab simply stops renewing, so nothing can stay stuck. Locks are advisory — they inform and ask,
they never deny a write (full co-editing is a later epic).
"""

from __future__ import annotations

import re
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CODE_FORBIDDEN",
    "CODE_INVALID",
    "CODE_LOCK_NOT_FOUND",
    "CODE_LOCK_HELD",
    "CODE_PROJECT_NOT_FOUND",
    "CODE_TAKEOVER_TOO_EARLY",
    "ELEMENT_KEY_PATTERN",
    "LOCK_TTL_SECONDS",
    "PRESENCE_TTL_SECONDS",
    "TAKEOVER_GRACE_SECONDS",
    "HeartbeatRequest",
    "LockRecord",
    "PresenceSnapshot",
    "PresenceValidationError",
    "TakeoverRecord",
    "ViewerRecord",
    "validate_element_key",
    "validate_session_id",
    "validate_view",
]

CODE_PROJECT_NOT_FOUND = "presence-project-not-found"
CODE_INVALID = "presence-invalid"
CODE_FORBIDDEN = "presence-forbidden"
CODE_LOCK_NOT_FOUND = "presence-lock-not-found"
CODE_LOCK_HELD = "presence-lock-held"
CODE_TAKEOVER_TOO_EARLY = "presence-takeover-too-early"

#: A tab with no heartbeat for this long is no longer "viewing".
PRESENCE_TTL_SECONDS = 45
#: A lock is held this long past its holder's last heartbeat; a disconnect frees it by lapse.
LOCK_TTL_SECONDS = 60
#: How long a takeover request waits for the holder to release before it may be forced.
TAKEOVER_GRACE_SECONDS = 15

#: ``<kind>:<id>`` — e.g. ``class:3f2a…`` or ``path:/pets``. Anchors elements the way comment
#: threads do, but as an opaque key: a lock never needs the element to exist.
ELEMENT_KEY_PATTERN = re.compile(r"^[a-z][a-z_]{0,31}:[A-Za-z0-9._~:/{}\-]{1,160}$")
_SESSION_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")
_VIEW_PATTERN = re.compile(r"^[a-z][a-z0-9_\-]{0,63}$")


class PresenceValidationError(ValueError):
    """A presence or lock request refused, carrying a stable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_element_key(value: str) -> str:
    """Return a well-formed element key or refuse.

    Raises:
        PresenceValidationError: ``presence-invalid`` when the key is not ``<kind>:<id>``.
    """
    key = (value or "").strip()
    if not ELEMENT_KEY_PATTERN.match(key):
        raise PresenceValidationError(CODE_INVALID, "element key must look like '<kind>:<id>'")
    return key


def validate_session_id(value: str) -> str:
    """Return a well-formed client session id (8-64 URL-safe characters) or refuse."""
    session = (value or "").strip()
    if not _SESSION_PATTERN.match(session):
        raise PresenceValidationError(CODE_INVALID, "session_id must be 8-64 URL-safe characters")
    return session


def validate_view(value: Optional[str]) -> str:
    """Return the view name (``project``, ``studio``, …) or refuse; defaults to ``project``."""
    view = (value or "project").strip().lower()
    if not _VIEW_PATTERN.match(view):
        raise PresenceValidationError(CODE_INVALID, "view must be a short lowercase identifier")
    return view


class ViewerRecord(BaseModel):
    """One person with the project open (their tabs collapsed into one avatar)."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(description="The viewer's user id.")
    name: str = Field(description="Display name.")
    views: List[str] = Field(default_factory=list, description="Views their tabs are on.")
    sessions: int = Field(description="How many live tabs they have open.")


class TakeoverRecord(BaseModel):
    """A pending request to take a lock over."""

    model_config = ConfigDict(extra="forbid")

    user_id: Optional[str] = Field(description="Who asked.")
    name: Optional[str] = Field(description="Their display name.")
    requested_at: str = Field(description="When they asked (ISO 8601).")
    can_force_after: str = Field(description="When the request may be forced (ISO 8601).")


class LockRecord(BaseModel):
    """A live advisory lock."""

    model_config = ConfigDict(extra="forbid")

    element_key: str = Field(description="The locked element, ``<kind>:<id>``.")
    holder_user_id: str = Field(description="Who is editing it.")
    holder_name: str = Field(description="Their display name.")
    holder_session_id: str = Field(description="The tab holding it.")
    acquired_at: str = Field(description="When it was taken (ISO 8601).")
    expires_at: str = Field(description="When it lapses without a heartbeat (ISO 8601).")
    takeover: Optional[TakeoverRecord] = Field(default=None, description="A pending takeover request.")


class PresenceSnapshot(BaseModel):
    """Everything a client needs to draw avatars and lock adornments."""

    model_config = ConfigDict(extra="forbid")

    viewers: List[ViewerRecord] = Field(default_factory=list)
    locks: List[LockRecord] = Field(default_factory=list)
    lost: List[str] = Field(
        default_factory=list,
        description=(
            "Element keys the caller's session claimed to hold that another session now holds — "
            "the previous holder's notice that a takeover happened."
        ),
    )
    server_time: str = Field(description="Server clock (ISO 8601), for client skew.")
    ttl_seconds: int = Field(description="Heartbeat at least twice per this many seconds.")


class HeartbeatRequest(BaseModel):
    """Renew a tab's presence and the locks it holds."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(description="Client-generated id of this tab (8-64 URL-safe chars).")
    view: Optional[str] = Field(default="project", description="Which view the tab is on.")
    held: List[str] = Field(
        default_factory=list, max_length=100, description="Element keys this tab believes it holds."
    )
