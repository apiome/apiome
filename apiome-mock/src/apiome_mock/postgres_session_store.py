"""Postgres-backed session store for multi-replica mock deployments (#4453, #7209).

Tables (V430, DBP-1.26):

* ``apiome.mock_session`` — one row per session namespace: sliding expiry, last activity,
  resource count and total bytes. The expiry lives only here, so a read touches at most this one
  row, and only when the last touch is older than :func:`touch_interval_seconds`.
* ``apiome.mock_session_resource`` — the stored resources (cascade with their session).
* ``apiome.mock_session_counter`` — the last allocated integer id per (session, collection).
* ``apiome.mock_session_slots`` — a trigger-kept count of ``mock_session`` rows; a new session
  compares it with ``max_sessions`` while holding the row's lock, so the cap holds under
  concurrency without counting the table.

Every write runs in one transaction that locks its session row first, so writes to one session are
serialized and concurrent creates get distinct ids. No statement on the request path reads another
session's rows; expired sessions are removed by :func:`run_session_expiry_sweeper`, in batches.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import structlog
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mock.session_store import (
    CreateBuilder,
    SeedCollections,
    SessionCapacityError,
    SessionCaps,
    SessionKey,
    UpdateBuilder,
    resource_byte_size,
)

_log = structlog.get_logger(__name__)

MAX_TOUCH_INTERVAL_SECONDS = 60.0
"""A session's expiry is extended at most once per this many seconds (or a tenth of the TTL)."""

_SESSION_KEY_WHERE = """
    tenant_slug = %(tenant)s
    AND project_slug = %(project)s
    AND version_label = %(version)s
    AND session_token = %(token)s
"""

# Finds the live session and, when its last touch is stale, extends its expiry. The touch skips a
# row that a writer holds (the writer extends it anyway), so a read never waits on a write.
_LIVE_SESSION_CTE = f"""
WITH live AS (
    SELECT id, last_activity_at
    FROM apiome.mock_session
    WHERE {_SESSION_KEY_WHERE}
      AND expires_at > %(now)s
), touched AS (
    UPDATE apiome.mock_session m
    SET expires_at = %(expires)s, last_activity_at = %(now)s
    WHERE m.id IN (
        SELECT s.id
        FROM apiome.mock_session s
        JOIN live ON live.id = s.id
        WHERE live.last_activity_at <= %(stale_before)s
        FOR UPDATE OF s SKIP LOCKED
    )
    RETURNING m.id
)
"""

_LIST_SQL = (
    _LIVE_SESSION_CTE
    + """
SELECT r.resource
FROM apiome.mock_session_resource r
JOIN live ON r.session_id = live.id
WHERE r.collection_path = %(collection)s
ORDER BY r.resource_id
"""
)

_GET_SQL = (
    _LIVE_SESSION_CTE
    + """
SELECT r.resource
FROM apiome.mock_session_resource r
JOIN live ON r.session_id = live.id
WHERE r.collection_path = %(collection)s
  AND r.resource_id = %(resource_id)s
"""
)

_LOCK_SESSION_SQL = f"""
SELECT id, expires_at, last_activity_at, resource_count, total_bytes
FROM apiome.mock_session
WHERE {_SESSION_KEY_WHERE}
FOR UPDATE
"""

_INSERT_SESSION_SQL = """
INSERT INTO apiome.mock_session (
    tenant_slug, project_slug, version_label, session_token, expires_at, last_activity_at
) VALUES (%(tenant)s, %(project)s, %(version)s, %(token)s, %(expires)s, %(now)s)
ON CONFLICT ON CONSTRAINT mock_session_namespace_unique DO NOTHING
RETURNING id
"""

_UPSERT_RESOURCE_SQL = """
INSERT INTO apiome.mock_session_resource (session_id, collection_path, resource_id, resource, byte_size)
VALUES (%s, %s, %s, %s::jsonb, %s)
ON CONFLICT (session_id, collection_path, resource_id)
DO UPDATE SET resource = EXCLUDED.resource, byte_size = EXCLUDED.byte_size
"""

_SEED_RESOURCES_SQL = """
INSERT INTO apiome.mock_session_resource (session_id, collection_path, resource_id, resource, byte_size)
SELECT %s, seed.collection_path, seed.resource_id, seed.resource::jsonb, seed.byte_size
FROM unnest(%s::text[], %s::text[], %s::text[], %s::int[])
    AS seed (collection_path, resource_id, resource, byte_size)
"""

# One past the last allocated id, and at least one past the highest numeric id in the collection
# (bounded by the session's resource cap; read through the primary key).
_ALLOCATE_ID_SQL = """
INSERT INTO apiome.mock_session_counter (session_id, collection_path, last_id)
VALUES (
    %(session_id)s,
    %(collection)s,
    (
        SELECT COALESCE(MAX(resource_id::numeric), 0) + 1
        FROM apiome.mock_session_resource
        WHERE session_id = %(session_id)s
          AND collection_path = %(collection)s
          AND resource_id ~ '^[0-9]{1,18}$'
    )
)
ON CONFLICT (session_id, collection_path)
DO UPDATE SET last_id = GREATEST(apiome.mock_session_counter.last_id + 1, EXCLUDED.last_id)
RETURNING last_id
"""

# ``id = ANY(ARRAY(...))`` keeps the delete on the primary key; a join to the batch lets the
# planner hash-join a sequential scan of every session instead.
_PURGE_SQL = """
DELETE FROM apiome.mock_session
WHERE id = ANY (
    ARRAY(
        SELECT id
        FROM apiome.mock_session
        WHERE expires_at <= %s
        ORDER BY expires_at
        LIMIT %s
        FOR UPDATE SKIP LOCKED
    )
)
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def touch_interval_seconds(ttl_seconds: float) -> float:
    """Return how stale a session's last touch must be before a request extends its expiry.

    Args:
        ttl_seconds: The configured sliding TTL.

    Returns:
        ``min(60, ttl / 10)`` seconds, so a session idle for its TTL still expires within ten
        per cent (at most a minute) of the time it would with a touch on every request.
    """
    return min(MAX_TOUCH_INTERVAL_SECONDS, ttl_seconds / 10.0)


def _as_resource(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        return dict(parsed) if isinstance(parsed, dict) else None
    return None


def _session_limit_error(max_sessions: int) -> SessionCapacityError:
    return SessionCapacityError(
        f"Session limit of {max_sessions} reached; retry later or reuse an existing X-Mock-Session token.",
    )


@dataclass
class _LockedSession:
    """A ``mock_session`` row locked ``FOR UPDATE`` by the current transaction."""

    id: int
    resource_count: int
    total_bytes: int
    last_activity_at: datetime


class PostgresSessionStore:
    """Durable session CRUD store on ``apiome.mock_session`` and its child tables."""

    def __init__(
        self,
        pool: AsyncConnectionPool,
        caps: SessionCaps,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Create the store.

        Args:
            pool: The mock runtime's (autocommit) connection pool.
            caps: Session TTL and abuse limits.
            clock: Returns the current UTC time; tests inject one to move past expiry.
        """
        self._pool = pool
        self._caps = caps
        self._clock = clock if clock is not None else _utcnow
        self._touch_interval = timedelta(seconds=touch_interval_seconds(caps.ttl_seconds))

    def _key_params(self, key: SessionKey, now: datetime) -> dict[str, Any]:
        """Named parameters shared by the session statements."""
        return {
            "tenant": key.tenant,
            "project": key.project,
            "version": key.version,
            "token": key.session_token,
            "now": now,
            "expires": now + timedelta(seconds=self._caps.ttl_seconds),
            "stale_before": now - self._touch_interval,
        }

    # -- session row helpers (call inside a transaction) -------------------------------------

    async def _lock_session(
        self,
        cur: Any,
        key: SessionKey,
        now: datetime,
        *,
        create: bool,
    ) -> _LockedSession | None:
        """Lock the session's row, creating it (within the session cap) when asked.

        An expired session that the sweep has not removed yet is emptied and reused, keeping its
        slot. A new session's insert bumps ``mock_session_slots`` (trigger), which this transaction
        then holds locked, so concurrent new sessions are checked against the cap one at a time.

        Args:
            cur: A cursor inside an open transaction.
            key: The session namespace.
            now: This operation's time.
            create: Create the session when it is missing or expired.

        Returns:
            The locked session, or ``None`` when it is missing or expired and ``create`` is false.

        Raises:
            SessionCapacityError: A new session would exceed ``max_sessions``.
        """
        params = self._key_params(key, now)
        for _ in range(2):
            await cur.execute(_LOCK_SESSION_SQL, params)
            row = await cur.fetchone()
            if row is not None:
                if row["expires_at"] > now:
                    return _LockedSession(
                        id=int(row["id"]),
                        resource_count=int(row["resource_count"]),
                        total_bytes=int(row["total_bytes"]),
                        last_activity_at=row["last_activity_at"],
                    )
                if not create:
                    return None
                return await self._reset_expired(cur, int(row["id"]), now)
            if not create:
                return None
            await cur.execute(_INSERT_SESSION_SQL, params)
            inserted = await cur.fetchone()
            if inserted is None:
                # Another transaction created it first; lock that row instead.
                continue
            await cur.execute(
                "SELECT session_count FROM apiome.mock_session_slots WHERE slot_id = 1",
            )
            slots = await cur.fetchone()
            if slots is not None and int(slots["session_count"]) > self._caps.max_sessions:
                raise _session_limit_error(self._caps.max_sessions)
            return _LockedSession(id=int(inserted["id"]), resource_count=0, total_bytes=0, last_activity_at=now)
        raise RuntimeError("mock session row vanished while it was being created")

    async def _reset_expired(self, cur: Any, session_id: int, now: datetime) -> _LockedSession:
        """Empty an expired, locked session so it starts again from nothing."""
        await cur.execute("DELETE FROM apiome.mock_session_resource WHERE session_id = %s", (session_id,))
        await cur.execute("DELETE FROM apiome.mock_session_counter WHERE session_id = %s", (session_id,))
        await self._save_session(cur, _LockedSession(session_id, 0, 0, now), now)
        return _LockedSession(id=session_id, resource_count=0, total_bytes=0, last_activity_at=now)

    async def _save_session(self, cur: Any, session: _LockedSession, now: datetime) -> None:
        """Write the session's totals and extend its expiry (one row)."""
        await cur.execute(
            """
            UPDATE apiome.mock_session
            SET resource_count = %s, total_bytes = %s, expires_at = %s, last_activity_at = %s
            WHERE id = %s
            """,
            (
                session.resource_count,
                session.total_bytes,
                now + timedelta(seconds=self._caps.ttl_seconds),
                now,
                session.id,
            ),
        )

    async def _touch_if_stale(self, cur: Any, session: _LockedSession, now: datetime) -> None:
        """Extend a locked session's expiry when its last touch is older than the interval."""
        if session.last_activity_at <= now - self._touch_interval:
            await self._save_session(cur, session, now)

    async def _store(
        self,
        cur: Any,
        session: _LockedSession,
        collection_path: str,
        resource_id: str,
        resource: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        """Cap-check and upsert one resource, then save the session totals.

        Raises:
            SessionCapacityError: The write would exceed the resource or byte cap.
        """
        payload = dict(resource)
        new_size = resource_byte_size(payload)
        await cur.execute(
            """
            SELECT byte_size
            FROM apiome.mock_session_resource
            WHERE session_id = %s AND collection_path = %s AND resource_id = %s
            """,
            (session.id, collection_path, resource_id),
        )
        existing = await cur.fetchone()
        old_size = int(existing["byte_size"]) if existing is not None else 0
        projected_count = session.resource_count + (0 if existing is not None else 1)
        projected_bytes = session.total_bytes - old_size + new_size
        if projected_count > self._caps.max_resources:
            raise SessionCapacityError(
                f"Session resource limit of {self._caps.max_resources} exceeded.",
            )
        if projected_bytes > self._caps.max_bytes:
            raise SessionCapacityError(
                f"Session size limit of {self._caps.max_bytes} bytes exceeded.",
            )
        await cur.execute(
            _UPSERT_RESOURCE_SQL,
            (session.id, collection_path, resource_id, json.dumps(payload), new_size),
        )
        session.resource_count = projected_count
        session.total_bytes = projected_bytes
        await self._save_session(cur, session, now)
        return payload

    async def _allocate_id(self, cur: Any, session_id: int, collection_path: str) -> int:
        """Persist and return the next integer id of the collection (one upsert)."""
        await cur.execute(_ALLOCATE_ID_SQL, {"session_id": session_id, "collection": collection_path})
        row = await cur.fetchone()
        return int(row["last_id"])

    # -- SessionStore -------------------------------------------------------------------------

    async def list_resources(
        self,
        key: SessionKey,
        collection_path: str,
    ) -> list[dict[str, Any]]:
        """Return the collection's resources in one statement (touching the session if stale)."""
        params = {**self._key_params(key, self._clock()), "collection": collection_path}
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(_LIST_SQL, params)
                rows = await cur.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            resource = _as_resource(row["resource"])
            if resource is not None:
                out.append(resource)
        return out

    async def get_resource(
        self,
        key: SessionKey,
        collection_path: str,
        resource_id: str,
    ) -> dict[str, Any] | None:
        """Return one resource in one statement (touching the session if stale)."""
        params = {
            **self._key_params(key, self._clock()),
            "collection": collection_path,
            "resource_id": resource_id,
        }
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(_GET_SQL, params)
                row = await cur.fetchone()
        if row is None:
            return None
        return _as_resource(row["resource"])

    async def put_resource(
        self,
        key: SessionKey,
        collection_path: str,
        resource_id: str,
        resource: dict[str, Any],
        *,
        replace: bool,
    ) -> dict[str, Any]:
        """Create or overwrite one resource in one transaction."""
        del replace  # create and replace store the same way (an existing id is overwritten)
        now = self._clock()
        async with self._pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor(row_factory=dict_row) as cur:
                    session = await self._lock_session(cur, key, now, create=True)
                    assert session is not None
                    return await self._store(cur, session, collection_path, resource_id, resource, now)

    async def create_resource(
        self,
        key: SessionKey,
        collection_path: str,
        build: CreateBuilder,
    ) -> dict[str, Any]:
        """Allocate an id and store the built resource in one transaction (#7209)."""
        now = self._clock()
        async with self._pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor(row_factory=dict_row) as cur:
                    session = await self._lock_session(cur, key, now, create=True)
                    assert session is not None
                    next_int = await self._allocate_id(cur, session.id, collection_path)
                    resource_id, resource = build(next_int)
                    return await self._store(cur, session, collection_path, resource_id, resource, now)

    async def update_resource(
        self,
        key: SessionKey,
        collection_path: str,
        resource_id: str,
        build: UpdateBuilder,
    ) -> dict[str, Any]:
        """Read, rebuild and store one resource in one transaction (#7209)."""
        now = self._clock()
        async with self._pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor(row_factory=dict_row) as cur:
                    session = await self._lock_session(cur, key, now, create=True)
                    assert session is not None
                    await cur.execute(
                        """
                        SELECT resource
                        FROM apiome.mock_session_resource
                        WHERE session_id = %s AND collection_path = %s AND resource_id = %s
                        """,
                        (session.id, collection_path, resource_id),
                    )
                    row = await cur.fetchone()
                    current = _as_resource(row["resource"]) if row is not None else None
                    resource = build(current)
                    return await self._store(cur, session, collection_path, resource_id, resource, now)

    async def delete_resource(
        self,
        key: SessionKey,
        collection_path: str,
        resource_id: str,
    ) -> bool:
        """Delete one resource in one transaction; return whether it existed."""
        now = self._clock()
        async with self._pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor(row_factory=dict_row) as cur:
                    session = await self._lock_session(cur, key, now, create=False)
                    if session is None:
                        return False
                    await cur.execute(
                        """
                        DELETE FROM apiome.mock_session_resource
                        WHERE session_id = %s AND collection_path = %s AND resource_id = %s
                        RETURNING byte_size
                        """,
                        (session.id, collection_path, resource_id),
                    )
                    deleted = await cur.fetchone()
                    if deleted is None:
                        await self._touch_if_stale(cur, session, now)
                        return False
                    session.resource_count = max(0, session.resource_count - 1)
                    session.total_bytes = max(0, session.total_bytes - int(deleted["byte_size"]))
                    await self._save_session(cur, session, now)
                    return True

    async def replace_session(
        self,
        key: SessionKey,
        collections: SeedCollections,
    ) -> tuple[int, int]:
        """Replace the session's rows in one transaction; see the protocol for semantics (#4745)."""
        # Serialize and cap-check the seed before touching the database, so a failed seed
        # aborts before the DELETE and the previous state survives (the transaction would
        # roll back anyway, but failing early avoids pointless writes).
        deduped: dict[tuple[str, str], tuple[str, int]] = {}
        for collection_path, items in collections.items():
            for resource_id, resource in items:
                payload = dict(resource)
                # Last occurrence wins on a duplicate id, matching put semantics.
                deduped[(collection_path, resource_id)] = (
                    json.dumps(payload),
                    resource_byte_size(payload),
                )
        total_bytes = sum(size for _, size in deduped.values())
        if len(deduped) > self._caps.max_resources:
            raise SessionCapacityError(
                f"Session resource limit of {self._caps.max_resources} exceeded.",
            )
        if total_bytes > self._caps.max_bytes:
            raise SessionCapacityError(
                f"Session size limit of {self._caps.max_bytes} bytes exceeded.",
            )

        now = self._clock()
        async with self._pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor(row_factory=dict_row) as cur:
                    if not deduped:
                        # Reset to nothing: the session row goes (and frees its slot); its
                        # resources and counters cascade.
                        await cur.execute(
                            f"DELETE FROM apiome.mock_session WHERE {_SESSION_KEY_WHERE}",
                            self._key_params(key, now),
                        )
                        return 0, 0
                    session = await self._lock_session(cur, key, now, create=True)
                    assert session is not None
                    await cur.execute(
                        "DELETE FROM apiome.mock_session_resource WHERE session_id = %s",
                        (session.id,),
                    )
                    await cur.execute(
                        "DELETE FROM apiome.mock_session_counter WHERE session_id = %s",
                        (session.id,),
                    )
                    await cur.execute(
                        _SEED_RESOURCES_SQL,
                        (
                            session.id,
                            [collection for collection, _ in deduped],
                            [resource_id for _, resource_id in deduped],
                            [payload_json for payload_json, _ in deduped.values()],
                            [size for _, size in deduped.values()],
                        ),
                    )
                    session.resource_count = len(deduped)
                    session.total_bytes = total_bytes
                    await self._save_session(cur, session, now)
                    return len(deduped), total_bytes

    async def next_integer_id(
        self,
        key: SessionKey,
        collection_path: str,
    ) -> int:
        """Allocate and persist the next integer id (sequence scenarios count calls with it)."""
        now = self._clock()
        async with self._pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor(row_factory=dict_row) as cur:
                    session = await self._lock_session(cur, key, now, create=True)
                    assert session is not None
                    allocated = await self._allocate_id(cur, session.id, collection_path)
                    await self._touch_if_stale(cur, session, now)
                    return allocated

    # -- expiry sweep -------------------------------------------------------------------------

    async def purge_expired(self, batch_size: int) -> int:
        """Delete up to ``batch_size`` expired sessions (and, by cascade, their rows).

        Sessions another transaction holds are skipped (``SKIP LOCKED``), so replicas sweeping at
        the same time share the work instead of waiting on each other.

        Args:
            batch_size: The most sessions one statement deletes.

        Returns:
            How many sessions were deleted.
        """
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_PURGE_SQL, (self._clock(), batch_size))
                return max(0, cur.rowcount)


async def sweep_expired_sessions(
    store: PostgresSessionStore,
    *,
    batch_size: int,
    max_batches: int,
) -> int:
    """Run purge batches until one deletes less than a full batch, or ``max_batches`` ran.

    Args:
        store: The Postgres session store.
        batch_size: Sessions per batch (each batch is its own statement and transaction).
        max_batches: Upper bound on batches in one sweep, so one tick cannot run forever.

    Returns:
        The number of sessions deleted.
    """
    total = 0
    for _ in range(max_batches):
        deleted = await store.purge_expired(batch_size)
        total += deleted
        if deleted < batch_size:
            break
    return total


async def run_session_expiry_sweeper(
    store: PostgresSessionStore,
    stop_event: asyncio.Event,
    *,
    interval_seconds: float,
    batch_size: int,
    max_batches: int = 100,
) -> None:
    """Sweep expired sessions every ``interval_seconds`` until ``stop_event`` is set.

    A failed sweep is logged and retried on the next tick; it never stops the loop.

    Args:
        store: The Postgres session store.
        stop_event: Set on shutdown.
        interval_seconds: Seconds between sweeps.
        batch_size: Sessions per purge statement.
        max_batches: Most purge statements per sweep.
    """
    while not stop_event.is_set():
        try:
            deleted = await sweep_expired_sessions(store, batch_size=batch_size, max_batches=max_batches)
            if deleted:
                _log.info("mock_session_sweep", deleted=deleted)
        except Exception as exc:  # noqa: BLE001 - keep sweeping after a transient failure
            _log.warning("mock_session_sweep_failed", error=str(exc))
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue
