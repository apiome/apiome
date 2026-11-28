"""Consumer-tagged capture in the hosted mock runtime — PFX-9.1 (#7319).

A call tagged ``X-Mock-Capture: <consumer>@<version>``, or made through a private capture URL
(``/{tenant}/{project}/{version}/~capture/{token}/…``), is served exactly as an untagged one and
then **queued** for that consumer and version. Nothing touches the database on the request path
(the DBP-1.24 rule): the :class:`ConsumerCaptureRecorder` redacts the queued calls and writes them
every ``APIOME_MOCK_CONSUMER_CAPTURE_FLUSH_INTERVAL_SECONDS`` (default 2 s) in **one transaction
per flush**, however many calls arrived. The one lookup a capture URL needs — which consumer its
token names — is cached (:func:`resolve_capture_link`), like the access row.

The caller is told what happened on the response itself:

* ``X-Mock-Capture: queued`` and ``X-Mock-Capture-Session: <consumer>@<version>`` — the call will
  be written with the next flush;
* ``X-Mock-Capture: not-recorded`` and ``X-Mock-Capture-Reason`` — a tag that could not be read, an
  unknown or revoked capture URL, a URL of another version, or a full queue.

What can only be known when writing — a session already holding
:data:`app.pact_capture.MAX_CALLS_PER_SESSION` calls, a workspace with
:data:`app.pact_capture.MAX_LIVE_SESSIONS_PER_TENANT` live sessions, a record that still looks
credential-bearing after redaction — is **counted with its reason** on the session (or, when no
session could be opened, on the tenant's settings row), never dropped unseen.

Bodies are stored after the mock's redaction rules (:func:`app.pact_capture.redact_call`), and
every row carries ``expires_at`` from the tenant's retention (default 7 days). The
:func:`run_capture_expiry_sweeper` deletes expired rows in batches; every read already ignores them.

Hosted only: the portable runtime has no database and never records.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence
from uuid import UUID

import structlog
from app.pact_capture import (
    CAPTURE_HEADER,
    CAPTURE_SESSION_HEADER,
    DEFAULT_RETENTION_DAYS,
    MAX_CALLS_PER_SESSION,
    MAX_LIVE_SESSIONS_PER_TENANT,
    REFUSAL_REASONS,
    CaptureHeaderProblem,
    ConsumerTag,
    RedactedCall,
    link_token_hash,
    looks_like_link_token,
    redact_call,
)
from fastapi.responses import Response
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mock.capture import CAPTURE_REASON_HEADER
from apiome_mock.ttl_cache import TtlCache

__all__ = [
    "CaptureLink",
    "ConsumerCaptureRecorder",
    "PendingCall",
    "SessionKey",
    "SessionState",
    "allocate_calls",
    "capture_recorder_for",
    "captured_now",
    "close_capture_recorder",
    "configure_capture_link_cache",
    "configure_capture_recorder",
    "mark_not_recorded",
    "mark_queued",
    "resolve_capture_link",
    "run_capture_expiry_sweeper",
    "sweep_expired_captures",
]

_log = structlog.get_logger(__name__)

DEFAULT_FLUSH_INTERVAL_SECONDS = 2.0
DEFAULT_MAX_PENDING = 10_000

#: A flush that fails puts its calls back for the next one, this many times, then drops them (logged).
MAX_FLUSH_ATTEMPTS = 3

#: ``(version_id, consumer, consumer_version)`` — one capture session.
SessionKey = tuple[UUID, str, str]


# ---------------------------------------------------------------------------------------------------
# Response headers
# ---------------------------------------------------------------------------------------------------


def mark_queued(response: Response, tag: ConsumerTag) -> None:
    """Say on the response that the call was queued for ``tag``'s session."""
    response.headers[CAPTURE_HEADER] = "queued"
    response.headers[CAPTURE_SESSION_HEADER] = tag.label


def mark_not_recorded(response: Response, code: str, message: str | None = None) -> None:
    """Say on the response that the call was not recorded, and why.

    Args:
        response: The response being returned.
        code: A :data:`app.pact_capture.REFUSAL_REASONS` key.
        message: The sentence to send; defaults to the code's own.
    """
    response.headers[CAPTURE_HEADER] = "not-recorded"
    response.headers[CAPTURE_REASON_HEADER] = message or REFUSAL_REASONS.get(code, code)


# ---------------------------------------------------------------------------------------------------
# Private capture URLs
# ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CaptureLink:
    """A live private capture URL as the runtime sees it.

    Attributes:
        id: The link id (stored on each call made through it).
        version_id: The mock version it records against.
        tag: The consumer and version its calls are recorded for.
        expires_at: When it stops working.
    """

    id: UUID
    version_id: UUID
    tag: ConsumerTag
    expires_at: datetime


_LINK_CACHE: TtlCache[CaptureLink] = TtlCache(ttl_seconds=30.0)

_SELECT_LINK = """
    SELECT id, version_id, consumer, consumer_version, expires_at
    FROM apiome.mock_consumer_capture_link
    WHERE token_hash = %(token_hash)s
      AND revoked_at IS NULL
      AND expires_at > CURRENT_TIMESTAMP
"""


def configure_capture_link_cache(ttl_seconds: float) -> None:
    """Set how long a resolved link is cached (startup); a revoked link stops within it."""
    global _LINK_CACHE
    _LINK_CACHE = TtlCache(ttl_seconds=ttl_seconds)


async def resolve_capture_link(pool: AsyncConnectionPool, token: str) -> CaptureLink | None:
    """The live link a capture URL token names, or ``None``.

    A token without the link shape is refused before any lookup, and only its digest is ever sent
    to the database. Unknown tokens are cached too, so probing does not repeat the query.

    Args:
        pool: Database pool used on a cache miss.
        token: The token from the URL.

    Returns:
        The link, or ``None`` when it is unknown, revoked or expired.
    """
    if not looks_like_link_token(token):
        return None
    digest = link_token_hash(token)

    async def _load() -> CaptureLink | None:
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(_SELECT_LINK, {"token_hash": digest})
                row = await cur.fetchone()
        if row is None:
            return None
        return CaptureLink(
            id=row["id"],
            version_id=row["version_id"],
            tag=ConsumerTag(row["consumer"], row["consumer_version"]),
            expires_at=row["expires_at"],
        )

    link = await _LINK_CACHE.get_or_load(digest, _load)
    if link is not None and link.expires_at <= datetime.now(timezone.utc):
        return None
    return link


# ---------------------------------------------------------------------------------------------------
# Queued calls and how a flush places them
# ---------------------------------------------------------------------------------------------------


@dataclass
class PendingCall:
    """One served call waiting to be written, exactly as it was served (not yet redacted).

    Attributes:
        version_id: The mock version that served it.
        project_slug: Project slug of the URL.
        version_label: Version label of the URL.
        tag: Whose call it is.
        via: ``header`` or ``url``.
        link_id: The capture URL it came through, when ``via`` is ``url``.
        api_key_id: The caller's API key, when it sent one.
        captured_at: When it was served (UTC).
        method: Request method.
        path: Request path relative to the version prefix.
        query: Query parameters as ordered pairs.
        request_headers: Request headers as sent.
        request_body: Raw request body.
        request_media_type: Request ``Content-Type``.
        status: Response status.
        response_headers: Response headers as served (before the capture headers were added).
        response_body: Raw response body (``None`` for a streamed one).
        response_media_type: Response ``Content-Type``.
        path_template: The spec's path template the request matched.
        operation_key: The matched operation (``"GET /invoices/{id}"``).
        origin: Where the answer came from (:data:`app.pact_capture.ORIGINS`).
        origin_detail: The serving pass's one-sentence explanation.
        scenario: The scenario in effect, if any.
        mock_session: Digest of the ``X-Mock-Session`` token, if any.
        policy: The version's capture policy, whose redaction rules apply.
        attempts: Flushes this call has already failed in.
    """

    version_id: UUID
    project_slug: str
    version_label: str
    tag: ConsumerTag
    via: str
    link_id: UUID | None
    api_key_id: UUID | None
    captured_at: datetime
    method: str
    path: str
    query: Sequence[tuple[str, str]]
    request_headers: Mapping[str, str]
    request_body: bytes | None
    request_media_type: str | None
    status: int
    response_headers: Mapping[str, str]
    response_body: bytes | None
    response_media_type: str | None
    path_template: str | None
    operation_key: str | None
    origin: str
    origin_detail: str | None
    scenario: str | None
    mock_session: str | None
    policy: Mapping[str, Any] = field(default_factory=dict)
    attempts: int = 0

    @property
    def session_key(self) -> SessionKey:
        """The session this call belongs to."""
        return (self.version_id, self.tag.consumer, self.tag.version)


@dataclass
class SessionState:
    """A session as the flush found (or opened) it.

    Attributes:
        id: Session id.
        tenant_id: Owning tenant.
        call_count: Calls already stored.
        refused: Refusals already counted, by reason.
    """

    id: UUID
    tenant_id: UUID
    call_count: int
    refused: dict[str, int]


@dataclass
class Allocation:
    """What one flush does with its calls.

    Attributes:
        stored: ``(session id, call, redacted record)`` for each call to insert.
        session_refusals: Per session id, refusals to add, by reason.
        tenant_refusals: Per tenant id, refusals to add for calls no session could take, by reason.
    """

    stored: list[tuple[UUID, PendingCall, RedactedCall]] = field(default_factory=list)
    session_refusals: dict[UUID, Counter[str]] = field(default_factory=dict)
    tenant_refusals: dict[UUID, Counter[str]] = field(default_factory=dict)


def allocate_calls(
    calls: Iterable[tuple[PendingCall, RedactedCall | CaptureHeaderProblem]],
    *,
    sessions: Mapping[SessionKey, SessionState],
    tenant_of: Mapping[UUID, UUID],
    unopened_reason: str = "too-many-sessions",
    max_calls_per_session: int | None = None,
) -> Allocation:
    """Place each redacted call in its session, counting everything that does not fit.

    Pure: the flush loads the sessions and decides nothing in SQL, so every rule is tested here.

    Args:
        calls: Each queued call with its redaction result (a record, or a refusal).
        sessions: The open session for each key the flush could open or found.
        tenant_of: Tenant id per version id (a version missing here was deleted meanwhile).
        unopened_reason: The reason counted for a call whose session could not be opened.
        max_calls_per_session: The session cap; :data:`MAX_CALLS_PER_SESSION` when ``None``.

    Returns:
        The :class:`Allocation`. Calls of a deleted version appear nowhere (logged by the caller).
    """
    cap = MAX_CALLS_PER_SESSION if max_calls_per_session is None else max_calls_per_session
    allocation = Allocation()
    room: dict[UUID, int] = {}
    for call, result in calls:
        tenant_id = tenant_of.get(call.version_id)
        if tenant_id is None:
            continue
        session = sessions.get(call.session_key)
        if session is None:
            allocation.tenant_refusals.setdefault(tenant_id, Counter())[unopened_reason] += 1
            continue
        refusals = allocation.session_refusals.setdefault(session.id, Counter())
        if isinstance(result, CaptureHeaderProblem):
            refusals[result.code] += 1
            continue
        left = room.setdefault(session.id, max(0, cap - session.call_count))
        if left <= 0:
            refusals["session-full"] += 1
            continue
        room[session.id] = left - 1
        allocation.stored.append((session.id, call, result))
    allocation.session_refusals = {sid: counts for sid, counts in allocation.session_refusals.items() if counts}
    return allocation


# ---------------------------------------------------------------------------------------------------
# SQL of one flush (one transaction)
# ---------------------------------------------------------------------------------------------------

_SELECT_VERSIONS = """
    SELECT v.id AS version_id, p.tenant_id,
           COALESCE(s.retention_days, %(default_days)s) AS retention_days
    FROM apiome.versions v
    INNER JOIN apiome.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
    LEFT JOIN apiome.mock_consumer_capture_settings s ON s.tenant_id = p.tenant_id
    WHERE v.id = ANY(%(version_ids)s::uuid[])
      AND v.deleted_at IS NULL
"""

_KEYS = "(SELECT * FROM unnest(%(k_version)s::uuid[], %(k_consumer)s::text[], %(k_cversion)s::text[]))"

#: An expired session is closed before its key is used again, so a new recording starts empty.
_DELETE_EXPIRED_KEYS = f"""
    DELETE FROM apiome.mock_consumer_capture_session
    WHERE (version_id, consumer, consumer_version) IN {_KEYS}
      AND expires_at <= CURRENT_TIMESTAMP
"""

_SELECT_SESSIONS = f"""
    SELECT id, tenant_id, version_id, consumer, consumer_version, call_count, refused
    FROM apiome.mock_consumer_capture_session
    WHERE (version_id, consumer, consumer_version) IN {_KEYS}
    FOR UPDATE
"""

_COUNT_LIVE_SESSIONS = """
    SELECT tenant_id, COUNT(*) AS live
    FROM apiome.mock_consumer_capture_session
    WHERE tenant_id = ANY(%(tenant_ids)s::uuid[])
      AND expires_at > CURRENT_TIMESTAMP
    GROUP BY tenant_id
"""

_INSERT_SESSIONS = """
    INSERT INTO apiome.mock_consumer_capture_session
      (tenant_id, version_id, project_slug, version_label, consumer, consumer_version,
       first_call_at, last_call_at, expires_at)
    SELECT u.tenant_id, u.version_id, u.project_slug, u.version_label, u.consumer, u.consumer_version,
           u.first_at, u.first_at, u.first_at + make_interval(days => u.retention)
    FROM unnest(%(tenant_id)s::uuid[], %(version_id)s::uuid[], %(project_slug)s::text[],
                %(version_label)s::text[], %(consumer)s::text[], %(consumer_version)s::text[],
                %(first_at)s::timestamptz[], %(retention)s::int[])
         AS u(tenant_id, version_id, project_slug, version_label, consumer, consumer_version, first_at, retention)
    ON CONFLICT ON CONSTRAINT mock_consumer_capture_session_key DO NOTHING
"""

_INSERT_CALLS = """
    INSERT INTO apiome.mock_consumer_capture_call
      (session_id, tenant_id, captured_at, via, link_id, api_key_id, method, path, path_template,
       operation_key, status, origin, origin_detail, scenario, mock_session, request, response,
       redactions, redaction_count, expires_at)
    SELECT u.session_id, u.tenant_id, u.captured_at, u.via, u.link_id, u.api_key_id, u.method, u.path,
           u.path_template, u.operation_key, u.status, u.origin, u.origin_detail, u.scenario,
           u.mock_session, u.request::jsonb, u.response::jsonb, u.redactions::jsonb,
           u.redaction_count, u.captured_at + make_interval(days => u.retention)
    FROM unnest(%(session_id)s::uuid[], %(tenant_id)s::uuid[], %(captured_at)s::timestamptz[],
                %(via)s::text[], %(link_id)s::uuid[], %(api_key_id)s::uuid[], %(method)s::text[],
                %(path)s::text[], %(path_template)s::text[], %(operation_key)s::text[],
                %(status)s::int[], %(origin)s::text[], %(origin_detail)s::text[], %(scenario)s::text[],
                %(mock_session)s::text[], %(request)s::text[], %(response)s::text[],
                %(redactions)s::text[], %(redaction_count)s::int[], %(retention)s::int[])
         AS u(session_id, tenant_id, captured_at, via, link_id, api_key_id, method, path, path_template,
              operation_key, status, origin, origin_detail, scenario, mock_session, request, response,
              redactions, redaction_count, retention)
"""

_UPDATE_SESSIONS = """
    UPDATE apiome.mock_consumer_capture_session AS s
    SET call_count = s.call_count + u.stored,
        refused_count = s.refused_count + u.refused,
        refused = u.reasons::jsonb,
        first_call_at = LEAST(s.first_call_at, u.first_at),
        last_call_at = GREATEST(s.last_call_at, u.last_at),
        expires_at = GREATEST(s.expires_at, u.last_at + make_interval(days => u.retention))
    FROM unnest(%(id)s::uuid[], %(stored)s::int[], %(refused)s::int[], %(reasons)s::text[],
                %(first_at)s::timestamptz[], %(last_at)s::timestamptz[], %(retention)s::int[])
         AS u(id, stored, refused, reasons, first_at, last_at, retention)
    WHERE s.id = u.id
"""

_UPSERT_TENANT_REFUSALS = """
    INSERT INTO apiome.mock_consumer_capture_settings
      (tenant_id, refused_calls, last_refused_reason, last_refused_at)
    SELECT u.tenant_id, u.refused, u.reason, CURRENT_TIMESTAMP
    FROM unnest(%(tenant_id)s::uuid[], %(refused)s::bigint[], %(reason)s::text[]) AS u(tenant_id, refused, reason)
    ON CONFLICT (tenant_id) DO UPDATE
    SET refused_calls = apiome.mock_consumer_capture_settings.refused_calls + EXCLUDED.refused_calls,
        last_refused_reason = EXCLUDED.last_refused_reason,
        last_refused_at = EXCLUDED.last_refused_at
"""


def _keys_params(keys: Sequence[SessionKey]) -> dict[str, list[Any]]:
    return {
        "k_version": [key[0] for key in keys],
        "k_consumer": [key[1] for key in keys],
        "k_cversion": [key[2] for key in keys],
    }


def _session_from_row(row: Mapping[str, Any]) -> tuple[SessionKey, SessionState]:
    refused = row["refused"] if isinstance(row["refused"], dict) else json.loads(row["refused"] or "{}")
    return (
        (row["version_id"], row["consumer"], row["consumer_version"]),
        SessionState(
            id=row["id"],
            tenant_id=row["tenant_id"],
            call_count=int(row["call_count"]),
            refused={str(k): int(v) for k, v in refused.items()},
        ),
    )


# ---------------------------------------------------------------------------------------------------
# The recorder
# ---------------------------------------------------------------------------------------------------


class ConsumerCaptureRecorder:
    """Queues tagged calls and writes them in batches — the process's one writer for ``pool``.

    Args:
        pool: The pool the flushes write through.
        flush_interval_seconds: Seconds between flushes.
        max_pending: Calls held between flushes; :meth:`submit` refuses beyond it.
    """

    def __init__(
        self,
        pool: AsyncConnectionPool,
        *,
        flush_interval_seconds: float = DEFAULT_FLUSH_INTERVAL_SECONDS,
        max_pending: int = DEFAULT_MAX_PENDING,
    ) -> None:
        self.pool = pool
        self.flush_interval_seconds = flush_interval_seconds
        self.max_pending = max_pending
        self._pending: deque[PendingCall] = deque()
        self._task: asyncio.Task[None] | None = None
        self._task_loop: asyncio.AbstractEventLoop | None = None
        self._flush_lock: asyncio.Lock | None = None
        self._closed = False

    def pending(self) -> int:
        """Calls queued and not yet written (tests and diagnostics)."""
        return len(self._pending)

    def submit(self, call: PendingCall) -> bool:
        """Queue one call. ``False`` when the queue is full (the caller says ``queue-full``).

        Costs no I/O: the call is appended and the periodic flush started if it is not running.
        """
        if len(self._pending) >= self.max_pending:
            _log.warning("mock_consumer_capture_queue_full", pending=len(self._pending))
            return False
        self._pending.append(call)
        self._ensure_running()
        return True

    async def flush(self) -> None:
        """Redact and write every queued call in one transaction.

        A failed write puts the calls back (up to :data:`MAX_FLUSH_ATTEMPTS` times each) so a short
        database outage loses nothing; calls that keep failing are dropped with a warning.
        """
        if self._flush_lock is None:
            self._flush_lock = asyncio.Lock()
        async with self._flush_lock:
            if not self._pending:
                return
            batch = list(self._pending)
            self._pending.clear()
            try:
                await self._write(batch)
            except Exception:
                retry = [call for call in batch if call.attempts + 1 < MAX_FLUSH_ATTEMPTS]
                for call in retry:
                    call.attempts += 1
                room = max(0, self.max_pending - len(self._pending))
                self._pending.extendleft(reversed(retry[:room]))
                _log.warning(
                    "mock_consumer_capture_flush_failed",
                    calls=len(batch),
                    requeued=min(len(retry), room),
                    dropped=len(batch) - min(len(retry), room),
                    exc_info=True,
                )

    async def _write(self, batch: list[PendingCall]) -> None:
        """One flush: redact (CPU), then one transaction of at most seven statements."""
        redacted = [
            (
                call,
                redact_call(
                    policy=call.policy,
                    method=call.method,
                    path=call.path,
                    query_params=call.query,
                    request_headers=call.request_headers,
                    request_body=call.request_body,
                    request_media_type=call.request_media_type,
                    status=call.status,
                    response_headers=call.response_headers,
                    response_body=call.response_body,
                    response_media_type=call.response_media_type,
                ),
            )
            for call in batch
        ]
        version_ids = sorted({call.version_id for call in batch}, key=str)
        keys = sorted({call.session_key for call in batch}, key=lambda k: (str(k[0]), k[1], k[2]))
        async with self.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        _SELECT_VERSIONS,
                        {"version_ids": version_ids, "default_days": DEFAULT_RETENTION_DAYS},
                    )
                    versions = {row["version_id"]: row for row in await cur.fetchall()}
                    tenant_of = {vid: row["tenant_id"] for vid, row in versions.items()}
                    retention_of = {vid: int(row["retention_days"]) for vid, row in versions.items()}
                    dropped = [call for call in batch if call.version_id not in versions]
                    if dropped:
                        _log.info("mock_consumer_capture_version_gone", calls=len(dropped))
                    keys = [key for key in keys if key[0] in versions]
                    if not keys:
                        return

                    await cur.execute(_DELETE_EXPIRED_KEYS, _keys_params(keys))
                    await cur.execute(_SELECT_SESSIONS, _keys_params(keys))
                    sessions = dict(_session_from_row(row) for row in await cur.fetchall())

                    missing = [key for key in keys if key not in sessions]
                    if missing:
                        await self._open_sessions(cur, missing, batch, tenant_of, retention_of)
                        await cur.execute(_SELECT_SESSIONS, _keys_params(missing))
                        sessions.update(_session_from_row(row) for row in await cur.fetchall())

                    allocation = allocate_calls(redacted, sessions=sessions, tenant_of=tenant_of)
                    await self._insert_calls(cur, allocation, sessions, tenant_of, retention_of)
                    await self._update_sessions(cur, allocation, batch, sessions, retention_of)
                    await self._count_tenant_refusals(cur, allocation)

    async def _open_sessions(
        self,
        cur: Any,
        missing: Sequence[SessionKey],
        batch: Sequence[PendingCall],
        tenant_of: Mapping[UUID, UUID],
        retention_of: Mapping[UUID, int],
    ) -> None:
        """Open a session for each missing key the tenant has room for."""
        tenants = sorted({tenant_of[key[0]] for key in missing}, key=str)
        await cur.execute(_COUNT_LIVE_SESSIONS, {"tenant_ids": tenants})
        room = {tenant: MAX_LIVE_SESSIONS_PER_TENANT for tenant in tenants}
        for row in await cur.fetchall():
            room[row["tenant_id"]] = MAX_LIVE_SESSIONS_PER_TENANT - int(row["live"])
        first: dict[SessionKey, PendingCall] = {}
        for call in batch:
            if call.session_key in missing and call.session_key not in first:
                first[call.session_key] = call
        opened: list[SessionKey] = []
        for key in missing:
            tenant = tenant_of[key[0]]
            if room[tenant] > 0:
                room[tenant] -= 1
                opened.append(key)
        if not opened:
            return
        await cur.execute(
            _INSERT_SESSIONS,
            {
                "tenant_id": [tenant_of[key[0]] for key in opened],
                "version_id": [key[0] for key in opened],
                "project_slug": [first[key].project_slug for key in opened],
                "version_label": [first[key].version_label for key in opened],
                "consumer": [key[1] for key in opened],
                "consumer_version": [key[2] for key in opened],
                "first_at": [first[key].captured_at for key in opened],
                "retention": [retention_of[key[0]] for key in opened],
            },
        )

    async def _insert_calls(
        self,
        cur: Any,
        allocation: Allocation,
        sessions: Mapping[SessionKey, SessionState],
        tenant_of: Mapping[UUID, UUID],
        retention_of: Mapping[UUID, int],
    ) -> None:
        """Insert the stored calls in one statement."""
        rows = allocation.stored
        if not rows:
            return
        await cur.execute(
            _INSERT_CALLS,
            {
                "session_id": [sid for sid, _, _ in rows],
                "tenant_id": [tenant_of[call.version_id] for _, call, _ in rows],
                "captured_at": [call.captured_at for _, call, _ in rows],
                "via": [call.via for _, call, _ in rows],
                "link_id": [call.link_id for _, call, _ in rows],
                "api_key_id": [call.api_key_id for _, call, _ in rows],
                "method": [call.method.upper() for _, call, _ in rows],
                "path": [call.path for _, call, _ in rows],
                "path_template": [call.path_template for _, call, _ in rows],
                "operation_key": [call.operation_key for _, call, _ in rows],
                "status": [call.status for _, call, _ in rows],
                "origin": [call.origin for _, call, _ in rows],
                "origin_detail": [call.origin_detail for _, call, _ in rows],
                "scenario": [call.scenario for _, call, _ in rows],
                "mock_session": [call.mock_session for _, call, _ in rows],
                "request": [json.dumps(record.request) for _, _, record in rows],
                "response": [json.dumps(record.response) for _, _, record in rows],
                "redactions": [json.dumps(record.redactions) for _, _, record in rows],
                "redaction_count": [len(record.redactions) for _, _, record in rows],
                "retention": [retention_of[call.version_id] for _, call, _ in rows],
            },
        )

    async def _update_sessions(
        self,
        cur: Any,
        allocation: Allocation,
        batch: Sequence[PendingCall],
        sessions: Mapping[SessionKey, SessionState],
        retention_of: Mapping[UUID, int],
    ) -> None:
        """Add this flush's counts, refusals and time span to each touched session."""
        by_id = {state.id: (key, state) for key, state in sessions.items()}
        stored = Counter(sid for sid, _, _ in allocation.stored)
        touched = sorted(set(stored) | set(allocation.session_refusals), key=str)
        if not touched:
            return
        spans: dict[SessionKey, tuple[datetime, datetime]] = {}
        for call in batch:
            low, high = spans.get(call.session_key, (call.captured_at, call.captured_at))
            spans[call.session_key] = (min(low, call.captured_at), max(high, call.captured_at))
        ids, stored_n, refused_n, reasons, first_at, last_at, retention = [], [], [], [], [], [], []
        for sid in touched:
            key, state = by_id[sid]
            added = allocation.session_refusals.get(sid, Counter())
            merged = Counter(state.refused)
            merged.update(added)
            ids.append(sid)
            stored_n.append(stored.get(sid, 0))
            refused_n.append(sum(added.values()))
            reasons.append(json.dumps(dict(sorted(merged.items()))))
            first_at.append(spans[key][0])
            last_at.append(spans[key][1])
            retention.append(retention_of[key[0]])
        await cur.execute(
            _UPDATE_SESSIONS,
            {
                "id": ids,
                "stored": stored_n,
                "refused": refused_n,
                "reasons": reasons,
                "first_at": first_at,
                "last_at": last_at,
                "retention": retention,
            },
        )

    async def _count_tenant_refusals(self, cur: Any, allocation: Allocation) -> None:
        """Count, on each tenant's settings row, calls no session could take."""
        if not allocation.tenant_refusals:
            return
        tenants = sorted(allocation.tenant_refusals, key=str)
        await cur.execute(
            _UPSERT_TENANT_REFUSALS,
            {
                "tenant_id": tenants,
                "refused": [sum(allocation.tenant_refusals[t].values()) for t in tenants],
                "reason": [allocation.tenant_refusals[t].most_common(1)[0][0] for t in tenants],
            },
        )
        _log.warning(
            "mock_consumer_capture_tenant_refused",
            tenants=len(tenants),
            calls=sum(sum(c.values()) for c in allocation.tenant_refusals.values()),
        )

    def _ensure_running(self) -> None:
        """Start the periodic flush task on the running loop (once per loop)."""
        if self._closed:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._task is not None and not self._task.done() and self._task_loop is loop:
            return
        self._task_loop = loop
        self._flush_lock = None
        self._task = loop.create_task(self._run())

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.flush_interval_seconds)
            await self.flush()

    async def close(self) -> None:
        """Stop the periodic task and write whatever is still queued (shutdown)."""
        self._closed = True
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self.flush()


_RECORDERS: dict[int, ConsumerCaptureRecorder] = {}


def capture_recorder_for(pool: AsyncConnectionPool) -> ConsumerCaptureRecorder:
    """Return the recorder that writes captures for ``pool``, creating it on first use."""
    recorder = _RECORDERS.get(id(pool))
    if recorder is None or recorder.pool is not pool:
        recorder = ConsumerCaptureRecorder(pool)
        _RECORDERS[id(pool)] = recorder
    return recorder


def configure_capture_recorder(
    pool: AsyncConnectionPool, *, flush_interval_seconds: float, max_pending: int
) -> ConsumerCaptureRecorder:
    """Create (or retune) the recorder for ``pool``; called once at startup."""
    recorder = capture_recorder_for(pool)
    recorder.flush_interval_seconds = flush_interval_seconds
    recorder.max_pending = max_pending
    recorder._closed = False
    return recorder


async def close_capture_recorder(pool: AsyncConnectionPool) -> None:
    """Flush and forget ``pool``'s recorder; call before the pool closes."""
    recorder = _RECORDERS.pop(id(pool), None)
    if recorder is not None and recorder.pool is pool:
        await recorder.close()


# ---------------------------------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------------------------------

_PURGE_CALLS = """
    DELETE FROM apiome.mock_consumer_capture_call
    WHERE id = ANY(ARRAY(
      SELECT id FROM apiome.mock_consumer_capture_call
      WHERE expires_at <= CURRENT_TIMESTAMP
      LIMIT %(batch)s
    ))
"""

_PURGE_SESSIONS = """
    DELETE FROM apiome.mock_consumer_capture_session
    WHERE id = ANY(ARRAY(
      SELECT id FROM apiome.mock_consumer_capture_session
      WHERE expires_at <= CURRENT_TIMESTAMP
      LIMIT %(batch)s
    ))
"""


async def sweep_expired_captures(pool: AsyncConnectionPool, *, batch_size: int, max_batches: int = 100) -> int:
    """Delete expired calls, then expired sessions, a batch per statement.

    Args:
        pool: The pool (autocommit: each batch is its own statement and transaction).
        batch_size: Rows per statement.
        max_batches: Most statements per table in one sweep, so one tick cannot run forever.

    Returns:
        Rows deleted.
    """
    total = 0
    for statement in (_PURGE_CALLS, _PURGE_SESSIONS):
        for _ in range(max_batches):
            async with pool.connection() as conn:
                cur = await conn.execute(statement, {"batch": batch_size})
                deleted = cur.rowcount or 0
            total += deleted
            if deleted < batch_size:
                break
    return total


async def run_capture_expiry_sweeper(
    pool: AsyncConnectionPool,
    stop_event: asyncio.Event,
    *,
    interval_seconds: float,
    batch_size: int,
) -> None:
    """Sweep expired captures every ``interval_seconds`` until ``stop_event`` is set.

    The first sweep runs one interval after start-up, so a starting replica does no capture work
    before it serves. A failed sweep is logged and retried on the next tick; it never stops the loop.
    """
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            return
        except asyncio.TimeoutError:
            pass
        try:
            deleted = await sweep_expired_captures(pool, batch_size=batch_size)
            if deleted:
                _log.info("mock_consumer_capture_sweep", deleted=deleted)
        except Exception as exc:  # noqa: BLE001 - keep sweeping after a transient failure
            _log.warning("mock_consumer_capture_sweep_failed", error=str(exc))


def captured_now() -> datetime:
    """The UTC instant a call is stamped with."""
    return datetime.now(timezone.utc)
