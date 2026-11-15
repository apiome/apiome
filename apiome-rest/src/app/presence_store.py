"""Presence and soft-lock store — COL-4.1 (#4525).

Storage is apiome-db V375. Every function takes an already-resolved project (the routes resolve it
inside the caller's tenant and check ``projects:view``), and every liveness read filters on the
lease, so a row that has lapsed but not been swept is invisible. Sweeping is opportunistic: each
heartbeat deletes the project's lapsed rows.

Lock rules:

* **One holder per element.** Taking a free or lapsed lock, or re-taking your own session's, wins.
* **Takeover, not denial.** Taking a lock someone else holds answers ``presence-lock-held`` with the
  holder; the caller may then *request* it (the holder sees the request on their next heartbeat) and
  *force* it once ``TAKEOVER_GRACE_SECONDS`` have passed or the holder has released.
* **Notice.** A stolen lock shows up in the previous holder's next snapshot as ``lost``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from .database import db
from .presence import (
    CODE_LOCK_HELD,
    CODE_LOCK_NOT_FOUND,
    CODE_TAKEOVER_TOO_EARLY,
    LOCK_TTL_SECONDS,
    PRESENCE_TTL_SECONDS,
    TAKEOVER_GRACE_SECONDS,
    LockRecord,
    PresenceSnapshot,
    PresenceValidationError,
    TakeoverRecord,
    ViewerRecord,
    validate_element_key,
)

__all__ = [
    "acquire_lock",
    "heartbeat",
    "leave",
    "release_lock",
    "request_takeover",
    "snapshot",
    "take_over",
]


def _iso(value: Any) -> str:
    """ISO-8601 text of a timestamp column."""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _sweep(project_id: str) -> None:
    """Delete the project's lapsed presence and lock rows."""
    db.execute_query(
        "WITH p AS (DELETE FROM apiome.project_presence WHERE project_id = %s::uuid "
        "AND last_seen_at < now() - make_interval(secs => %s) RETURNING 1), "
        "l AS (DELETE FROM apiome.element_locks WHERE project_id = %s::uuid "
        "AND expires_at < now() RETURNING 1) SELECT 1 AS swept",
        (project_id, PRESENCE_TTL_SECONDS, project_id),
    )


def snapshot(project_id: str, *, session_id: Optional[str] = None, held: Sequence[str] = ()) -> PresenceSnapshot:
    """Read who is viewing and which elements are locked.

    Args:
        project_id: The project.
        session_id: The caller's tab, to compute ``lost``.
        held: Element keys the caller's tab believes it holds.

    Returns:
        The snapshot. ``lost`` lists ``held`` keys that another live session holds, or that no
        longer have a lock at all.
    """
    people = db.execute_query(
        "SELECT p.user_id::text AS user_id, u.name AS name, count(*)::int AS sessions, "
        "array_agg(DISTINCT p.view ORDER BY p.view) AS views "
        "FROM apiome.project_presence p JOIN apiome.users u ON u.id = p.user_id "
        "WHERE p.project_id = %s::uuid AND p.last_seen_at >= now() - make_interval(secs => %s) "
        "GROUP BY p.user_id, u.name ORDER BY min(p.connected_at), u.name",
        (project_id, PRESENCE_TTL_SECONDS),
    )
    rows = db.execute_query(
        "SELECT l.element_key, l.holder_user_id::text AS holder_user_id, h.name AS holder_name, "
        "l.holder_session_id, l.acquired_at, l.expires_at, l.takeover_user_id::text AS t_user_id, "
        "t.name AS t_name, l.takeover_requested_at "
        "FROM apiome.element_locks l JOIN apiome.users h ON h.id = l.holder_user_id "
        "LEFT JOIN apiome.users t ON t.id = l.takeover_user_id "
        "WHERE l.project_id = %s::uuid AND l.expires_at >= now() ORDER BY l.acquired_at",
        (project_id,),
    )
    locks: List[LockRecord] = []
    for row in rows:
        takeover = None
        if row["takeover_requested_at"] is not None:
            asked = row["takeover_requested_at"]
            takeover = TakeoverRecord(
                user_id=row["t_user_id"],
                name=row["t_name"],
                requested_at=_iso(asked),
                can_force_after=_iso(asked + timedelta(seconds=TAKEOVER_GRACE_SECONDS)),
            )
        locks.append(
            LockRecord(
                element_key=row["element_key"],
                holder_user_id=row["holder_user_id"],
                holder_name=row["holder_name"],
                holder_session_id=row["holder_session_id"],
                acquired_at=_iso(row["acquired_at"]),
                expires_at=_iso(row["expires_at"]),
                takeover=takeover,
            )
        )
    mine = {lock.element_key for lock in locks if lock.holder_session_id == session_id}
    lost = [key for key in held if key not in mine] if session_id else []
    return PresenceSnapshot(
        viewers=[
            ViewerRecord(
                user_id=p["user_id"], name=p["name"], views=list(p["views"] or []), sessions=p["sessions"]
            )
            for p in people
        ],
        locks=locks,
        lost=lost,
        server_time=datetime.now(timezone.utc).isoformat(),
        ttl_seconds=PRESENCE_TTL_SECONDS,
    )


def heartbeat(
    project_id: str,
    tenant_id: str,
    user_id: str,
    session_id: str,
    view: str,
    held: Sequence[str] = (),
) -> PresenceSnapshot:
    """Record a tab as present, renew the locks it holds, and return the current snapshot.

    Locks are renewed only for the keys the tab names *and* still holds, so a tab that lost a lock
    cannot revive it by heartbeating.

    Args:
        project_id: The project.
        tenant_id: The caller's tenant.
        user_id: The caller.
        session_id: The tab.
        view: The view the tab is on.
        held: Element keys the tab believes it holds.

    Returns:
        The snapshot, with ``lost`` filled in for the tab.
    """
    keys = [validate_element_key(k) for k in held]
    db.execute_query(
        "INSERT INTO apiome.project_presence (project_id, session_id, tenant_id, user_id, view) "
        "VALUES (%s::uuid, %s, %s::uuid, %s::uuid, %s) "
        "ON CONFLICT (project_id, session_id) DO UPDATE SET last_seen_at = now(), view = EXCLUDED.view "
        "WHERE apiome.project_presence.user_id = EXCLUDED.user_id RETURNING 1",
        (project_id, session_id, tenant_id, user_id, view),
    )
    if keys:
        db.execute_query(
            "UPDATE apiome.element_locks SET expires_at = now() + make_interval(secs => %s) "
            "WHERE project_id = %s::uuid AND holder_session_id = %s AND element_key = ANY(%s) "
            "AND expires_at >= now() RETURNING 1",
            (LOCK_TTL_SECONDS, project_id, session_id, keys),
        )
    _sweep(project_id)
    return snapshot(project_id, session_id=session_id, held=keys)


def leave(project_id: str, session_id: str) -> None:
    """Remove a tab's presence and every lock it holds (a clean disconnect)."""
    db.execute_query(
        "WITH p AS (DELETE FROM apiome.project_presence WHERE project_id = %s::uuid "
        "AND session_id = %s RETURNING 1), l AS (DELETE FROM apiome.element_locks "
        "WHERE project_id = %s::uuid AND holder_session_id = %s RETURNING 1) SELECT 1 AS done",
        (project_id, session_id, project_id, session_id),
    )


def _held_by_other(project_id: str, element_key: str, session_id: str) -> Optional[LockRecord]:
    """The live lock on ``element_key`` when a session other than ``session_id`` holds it."""
    for lock in snapshot(project_id).locks:
        if lock.element_key == element_key and lock.holder_session_id != session_id:
            return lock
    return None


def acquire_lock(
    project_id: str, tenant_id: str, user_id: str, session_id: str, element_key: str
) -> PresenceSnapshot:
    """Mark an element as being edited by this tab.

    Raises:
        PresenceValidationError: ``presence-lock-held`` when another live session holds it —
            request or force a takeover instead.
    """
    key = validate_element_key(element_key)
    rows = db.execute_query(
        "INSERT INTO apiome.element_locks (project_id, element_key, tenant_id, holder_user_id, "
        "holder_session_id, expires_at) VALUES (%s::uuid, %s, %s::uuid, %s::uuid, %s, "
        "now() + make_interval(secs => %s)) ON CONFLICT (project_id, element_key) DO UPDATE SET "
        "holder_user_id = EXCLUDED.holder_user_id, holder_session_id = EXCLUDED.holder_session_id, "
        "tenant_id = EXCLUDED.tenant_id, "
        "acquired_at = CASE WHEN apiome.element_locks.holder_session_id = EXCLUDED.holder_session_id "
        "AND apiome.element_locks.expires_at >= now() THEN apiome.element_locks.acquired_at ELSE now() END, "
        "expires_at = EXCLUDED.expires_at, takeover_user_id = NULL, takeover_session_id = NULL, "
        "takeover_requested_at = NULL "
        "WHERE apiome.element_locks.holder_session_id = EXCLUDED.holder_session_id "
        "OR apiome.element_locks.expires_at < now() RETURNING element_key",
        (project_id, key, tenant_id, user_id, session_id, LOCK_TTL_SECONDS),
    )
    if not rows:
        holder = _held_by_other(project_id, key, session_id)
        name = holder.holder_name if holder else "someone else"
        raise PresenceValidationError(CODE_LOCK_HELD, f"{name} is editing this element")
    return snapshot(project_id, session_id=session_id)


def release_lock(project_id: str, session_id: str, element_key: str) -> PresenceSnapshot:
    """Release a lock this tab holds. Releasing a lock you do not hold is a no-op."""
    key = validate_element_key(element_key)
    db.execute_query(
        "DELETE FROM apiome.element_locks WHERE project_id = %s::uuid AND element_key = %s "
        "AND holder_session_id = %s RETURNING 1",
        (project_id, key, session_id),
    )
    return snapshot(project_id, session_id=session_id)


def request_takeover(
    project_id: str, user_id: str, session_id: str, element_key: str
) -> PresenceSnapshot:
    """Ask the holder to hand an element over; the holder sees it on their next heartbeat.

    Raises:
        PresenceValidationError: ``presence-lock-not-found`` when nobody live holds the element
            (just acquire it), or when the caller already holds it.
    """
    key = validate_element_key(element_key)
    rows = db.execute_query(
        "UPDATE apiome.element_locks SET takeover_user_id = %s::uuid, takeover_session_id = %s, "
        "takeover_requested_at = now() WHERE project_id = %s::uuid AND element_key = %s "
        "AND expires_at >= now() AND holder_session_id <> %s "
        "AND (takeover_session_id IS NULL OR takeover_session_id = %s) RETURNING element_key",
        (user_id, session_id, project_id, key, session_id, session_id),
    )
    if not rows and _held_by_other(project_id, key, session_id) is None:
        raise PresenceValidationError(CODE_LOCK_NOT_FOUND, "nobody else holds this element")
    return snapshot(project_id, session_id=session_id)


def take_over(
    project_id: str, tenant_id: str, user_id: str, session_id: str, element_key: str
) -> PresenceSnapshot:
    """Steal a lock the caller has asked for, once the grace period has passed.

    The previous holder is told through ``lost`` in their next snapshot. A lock that has lapsed or
    been released is simply acquired.

    Raises:
        PresenceValidationError: ``presence-takeover-too-early`` before ``TAKEOVER_GRACE_SECONDS``
            have passed since the caller's request (or with no request), and
            ``presence-lock-held`` when someone else has since requested it first.
    """
    key = validate_element_key(element_key)
    rows = db.execute_query(
        "UPDATE apiome.element_locks SET holder_user_id = %s::uuid, holder_session_id = %s, "
        "tenant_id = %s::uuid, acquired_at = now(), expires_at = now() + make_interval(secs => %s), "
        "takeover_user_id = NULL, takeover_session_id = NULL, takeover_requested_at = NULL "
        "WHERE project_id = %s::uuid AND element_key = %s AND expires_at >= now() "
        "AND takeover_session_id = %s "
        "AND takeover_requested_at <= now() - make_interval(secs => %s) RETURNING element_key",
        (user_id, session_id, tenant_id, LOCK_TTL_SECONDS, project_id, key, session_id, TAKEOVER_GRACE_SECONDS),
    )
    if rows:
        return snapshot(project_id, session_id=session_id)
    other = _held_by_other(project_id, key, session_id)
    if other is None:
        return acquire_lock(project_id, tenant_id, user_id, session_id, key)
    if other.takeover is not None and other.takeover.user_id != user_id:
        raise PresenceValidationError(CODE_LOCK_HELD, f"{other.takeover.name or 'someone'} asked first")
    raise PresenceValidationError(
        CODE_TAKEOVER_TOO_EARLY,
        f"{other.holder_name} has {TAKEOVER_GRACE_SECONDS} seconds from your request to release it",
    )
