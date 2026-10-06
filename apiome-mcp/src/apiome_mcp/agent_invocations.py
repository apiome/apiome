"""AGX-3.3 invocation audit — one metadata-only row per agent ``tools/call`` (#4539).

Tenants must be able to answer *which agent called which tool, when, how fast, with what outcome*
without Apiome keeping request or response bodies. Every agent ``tools/call`` therefore writes
exactly one ``apiome.agent_invocations`` row (V271) holding only metadata: key, toolset, tool,
target, start time, latency, outcome, upstream HTTP status, a machine reason code, and the
request/response sizes.

**How the call path uses it.** The AGX-2.1 invocation proxy (#4533) wraps each call in
:func:`audit_invocation` and reports how it ended::

    access = current_agent_access()
    async with audit_invocation(pool, access.key, tool_name=name, target="prod",
                                request_bytes=len(raw_args), capture=policy) as audit:
        if not valid(args):
            audit.failed(InvocationOutcome.VALIDATION_FAILURE, "invalid_arguments")
            return error_result
        response = await call_upstream(...)
        audit.attach_bodies(request_body=raw_args, response_body=response.text)
        if response.is_error:
            audit.failed(InvocationOutcome.UPSTREAM_ERROR, "upstream_http_error",
                         http_status=response.status_code, response_bytes=len(response.content))
        else:
            audit.succeeded(http_status=response.status_code, response_bytes=len(response.content))

The row is written when the block exits, whatever happens inside it: an outcome that was never
reported is recorded as ``internal_error`` (``outcome_not_reported``, or ``unhandled_exception``
when the block raised — or what the ``classify`` hook maps the exception to, e.g. AGX-3.2's quota
error to ``quota_rejected``). Recording never raises into the call: a database failure is logged and
the call's own result or exception goes through unchanged.

**Bodies are opt-in.** Nothing is captured unless the toolset's ``body_capture_rate`` is above zero
and ``body_capture_until`` is in the future (:func:`load_body_capture_policy`). The sampling
decision is made once, when the block is entered; a sampled call's bodies go to
``apiome.agent_invocation_samples``, each truncated to :data:`MAX_SAMPLE_BYTES` UTF-8 bytes. Headers
are never captured.

Calls refused before they reach the tool (unknown or non-permitted tool, a rejected key) are not
invocations: the key may be unknown and the tool name is caller-chosen. Those refusals are logged
by :mod:`apiome_mcp.agent_access`.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from types import TracebackType
from typing import Literal

import structlog
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.agent_access import AgentKey

_log = structlog.get_logger(__name__)

__all__ = [
    "MAX_SAMPLE_BYTES",
    "BodyCapturePolicy",
    "InvocationAudit",
    "InvocationOutcome",
    "InvocationRecord",
    "InvocationSample",
    "OutcomeClassifier",
    "Target",
    "audit_invocation",
    "insert_invocation",
    "load_body_capture_policy",
    "truncate_body",
]

#: Where a toolset sends calls (``agent_toolsets.target``).
Target = Literal["prod", "mock"]

#: Per-body cap on a captured sample, in UTF-8 bytes. Mirrors the V271 CHECK.
MAX_SAMPLE_BYTES = 16384

#: The ``agent_invocations.error_code`` grammar (V271 CHECK): a lower-case machine code, never prose.
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")


class InvocationOutcome(str, Enum):
    """How a ``tools/call`` ended (``agent_invocations.outcome``)."""

    SUCCESS = "success"
    #: The upstream answered with an error, or could not be reached (timeout, connection refused).
    UPSTREAM_ERROR = "upstream_error"
    #: The arguments were refused before anything was sent upstream.
    VALIDATION_FAILURE = "validation_failure"
    #: An AGX-3.2 rate or quota limit refused the call.
    QUOTA_REJECTED = "quota_rejected"
    #: Anything else, including a failure the call path did not classify.
    INTERNAL_ERROR = "internal_error"


#: Maps an exception that escaped the audited block to an outcome and reason code, or ``None`` to
#: fall back to ``internal_error`` / ``unhandled_exception``.
OutcomeClassifier = Callable[[BaseException], tuple[InvocationOutcome, str] | None]


@dataclass(frozen=True)
class InvocationRecord:
    """One ``agent_invocations`` row. Metadata only.

    Attributes:
        tenant_id: The key's tenant.
        key_id: The agent key (``api_keys.id``).
        toolset_id: The key's toolset.
        tool_name: The MCP tool called.
        target: ``prod`` or ``mock``.
        invoked_at: When the call started (timezone-aware).
        latency_ms: Wall-clock duration in milliseconds.
        outcome: How it ended.
        error_code: Machine reason code; ``None`` exactly when ``outcome`` is success.
        http_status: The upstream HTTP status, when the upstream answered.
        request_bytes: UTF-8 size of the arguments sent.
        response_bytes: UTF-8 size of the result returned.
        sampled: Whether a body sample accompanies the row.
    """

    tenant_id: str
    key_id: str
    toolset_id: str
    tool_name: str
    target: Target
    invoked_at: datetime
    latency_ms: int
    outcome: InvocationOutcome
    error_code: str | None
    http_status: int | None
    request_bytes: int
    response_bytes: int
    sampled: bool = False


@dataclass(frozen=True)
class InvocationSample:
    """Captured bodies of a sampled invocation, already truncated (:func:`truncate_body`).

    Attributes:
        request_body: The arguments sent, or ``None``.
        response_body: The result returned, or ``None``.
        request_truncated: Whether ``request_body`` was cut to :data:`MAX_SAMPLE_BYTES`.
        response_truncated: Whether ``response_body`` was cut to :data:`MAX_SAMPLE_BYTES`.
    """

    request_body: str | None
    response_body: str | None
    request_truncated: bool = False
    response_truncated: bool = False


@dataclass(frozen=True)
class BodyCapturePolicy:
    """A toolset's opt-in body capture (``agent_toolsets.body_capture_rate`` / ``_until``).

    Attributes:
        rate: Fraction of calls to sample, 0..1. ``0`` captures nothing.
        until: Capture stops at this time; ``None`` captures nothing.
    """

    rate: float = 0.0
    until: datetime | None = None

    def samples(self, now: datetime, draw: float) -> bool:
        """Return whether a call starting at ``now`` is sampled.

        Args:
            now: The call's start time (timezone-aware).
            draw: A uniform random number in ``[0, 1)``.

        Returns:
            ``True`` only while the window is open and ``draw`` falls under the rate.
        """
        if self.rate <= 0 or self.until is None or now >= self.until:
            return False
        return draw < self.rate


#: No capture — what every toolset has unless an operator opts in.
_NO_CAPTURE = BodyCapturePolicy()


def truncate_body(body: str | None, limit: int = MAX_SAMPLE_BYTES) -> tuple[str | None, bool]:
    """Cut ``body`` to at most ``limit`` UTF-8 bytes without splitting a character.

    Args:
        body: The text to keep, or ``None``.
        limit: The byte cap.

    Returns:
        The (possibly shortened) text and whether it was shortened.
    """
    if body is None:
        return None, False
    encoded = body.encode("utf-8")
    if len(encoded) <= limit:
        return body, False
    return encoded[:limit].decode("utf-8", errors="ignore"), True


_BODY_CAPTURE_POLICY = """
    SELECT body_capture_rate, body_capture_until
    FROM apiome.agent_toolsets
    WHERE id = %s::uuid AND tenant_id = %s::uuid
"""


async def load_body_capture_policy(pool: AsyncConnectionPool, tenant_id: str, toolset_id: str) -> BodyCapturePolicy:
    """Read a toolset's body-capture opt-in.

    Args:
        pool: The shared Postgres pool.
        tenant_id: The key's tenant; a toolset of another tenant captures nothing.
        toolset_id: The key's toolset.

    Returns:
        The toolset's policy, or a no-capture policy when the toolset is not found.
    """
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_BODY_CAPTURE_POLICY, (toolset_id, tenant_id))
            row = await cur.fetchone()
    if row is None:
        return _NO_CAPTURE
    rate = row.get("body_capture_rate") or 0
    return BodyCapturePolicy(
        rate=float(rate) if isinstance(rate, (int, float, Decimal)) else 0.0,
        until=row.get("body_capture_until"),
    )


_INSERT_INVOCATION = """
    INSERT INTO apiome.agent_invocations (
        tenant_id, key_id, toolset_id, tool_name, target, invoked_at, latency_ms,
        outcome, error_code, http_status, request_bytes, response_bytes, sampled
    )
    VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id::text
"""

_INSERT_SAMPLE = """
    INSERT INTO apiome.agent_invocation_samples (
        invocation_id, tenant_id, request_body, response_body, request_truncated, response_truncated
    )
    VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s)
"""


async def insert_invocation(
    pool: AsyncConnectionPool,
    record: InvocationRecord,
    sample: InvocationSample | None = None,
) -> str:
    """Write one invocation row (and its sample, if any) in a single transaction.

    Args:
        pool: The shared Postgres pool.
        record: The row. The stored ``sampled`` flag is whether ``sample`` is given.
        sample: Captured bodies, only for a sampled call.

    Returns:
        The new ``agent_invocations.id``.

    Raises:
        Exception: Database errors propagate; :class:`InvocationAudit` catches and logs them.
    """
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                _INSERT_INVOCATION,
                (
                    record.tenant_id,
                    record.key_id,
                    record.toolset_id,
                    record.tool_name,
                    record.target,
                    record.invoked_at,
                    record.latency_ms,
                    record.outcome.value,
                    record.error_code,
                    record.http_status,
                    record.request_bytes,
                    record.response_bytes,
                    sample is not None,
                ),
            )
            row = await cur.fetchone()
            invocation_id = str(row[0]) if row else ""
            if sample is not None:
                await conn.execute(
                    _INSERT_SAMPLE,
                    (
                        invocation_id,
                        record.tenant_id,
                        sample.request_body,
                        sample.response_body,
                        sample.request_truncated,
                        sample.response_truncated,
                    ),
                )
    return invocation_id


def _checked_code(code: str) -> str:
    """Return ``code`` if it fits the reason-code grammar, else raise (it would fail the CHECK)."""
    if not _ERROR_CODE.match(code):
        raise ValueError(f"error_code must match {_ERROR_CODE.pattern}: {code!r}")
    return code


class InvocationAudit:
    """Records exactly one invocation row for the ``async with`` block it guards.

    Create it with :func:`audit_invocation`. Inside the block, report the outcome once with
    :meth:`succeeded` or :meth:`failed`, and optionally hand over bodies with
    :meth:`attach_bodies` (kept only when the call was sampled). The row is written on exit.
    """

    def __init__(
        self,
        pool: AsyncConnectionPool,
        key: AgentKey,
        *,
        tool_name: str,
        target: Target,
        request_bytes: int,
        sampled: bool,
        classify: OutcomeClassifier | None,
        wall_clock: Callable[[], datetime],
        monotonic: Callable[[], float],
    ) -> None:
        """Hold the call's identity; see :func:`audit_invocation` for the arguments."""
        self._pool = pool
        self._key = key
        self._tool_name = tool_name
        self._target: Target = target
        self._request_bytes = max(0, request_bytes)
        self._sampled = sampled
        self._classify = classify
        self._wall_clock = wall_clock
        self._monotonic = monotonic
        self._invoked_at: datetime | None = None
        self._started = 0.0
        self._outcome: InvocationOutcome | None = None
        self._error_code: str | None = None
        self._http_status: int | None = None
        self._response_bytes = 0
        self._sample: InvocationSample | None = None
        self._recorded = False

    @property
    def sampled(self) -> bool:
        """Whether this call's bodies will be captured (decided on entry)."""
        return self._sampled

    @property
    def outcome(self) -> InvocationOutcome | None:
        """The outcome reported so far, if any."""
        return self._outcome

    def succeeded(self, *, http_status: int | None = None, response_bytes: int = 0) -> None:
        """Report that the call succeeded.

        Args:
            http_status: The upstream HTTP status.
            response_bytes: UTF-8 size of the result returned to the agent.
        """
        self._report(InvocationOutcome.SUCCESS, None, http_status, response_bytes)

    def failed(
        self,
        outcome: InvocationOutcome,
        error_code: str,
        *,
        http_status: int | None = None,
        response_bytes: int = 0,
    ) -> None:
        """Report that the call failed.

        Args:
            outcome: Any outcome but :attr:`InvocationOutcome.SUCCESS`.
            error_code: Machine reason code (``^[a-z][a-z0-9_.]{0,63}$``), e.g. ``upstream_timeout``.
            http_status: The upstream HTTP status, when the upstream answered.
            response_bytes: UTF-8 size of the error result returned to the agent.

        Raises:
            ValueError: ``outcome`` is success, or ``error_code`` is not a machine code.
        """
        if outcome is InvocationOutcome.SUCCESS:
            raise ValueError("failed() needs a failure outcome; use succeeded()")
        self._report(outcome, _checked_code(error_code), http_status, response_bytes)

    def attach_bodies(self, *, request_body: str | None = None, response_body: str | None = None) -> None:
        """Hand over the call's bodies; kept (truncated) only when the call was sampled.

        Args:
            request_body: The arguments sent upstream, as text.
            response_body: The result returned, as text.
        """
        if not self._sampled:
            return
        request, request_cut = truncate_body(request_body)
        response, response_cut = truncate_body(response_body)
        self._sample = InvocationSample(request, response, request_cut, response_cut)

    def _report(
        self,
        outcome: InvocationOutcome,
        error_code: str | None,
        http_status: int | None,
        response_bytes: int,
    ) -> None:
        """Store the reported outcome. A second report replaces the first (the last word wins)."""
        if http_status is not None and not 100 <= http_status <= 599:
            http_status = None
        self._outcome = outcome
        self._error_code = error_code
        self._http_status = http_status
        self._response_bytes = max(0, response_bytes)

    async def __aenter__(self) -> InvocationAudit:
        """Start the clock."""
        self._invoked_at = self._wall_clock()
        self._started = self._monotonic()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Write the row (once). Never raises and never swallows the block's exception."""
        if self._recorded or self._invoked_at is None:
            return
        self._recorded = True
        latency_ms = max(0, int(round((self._monotonic() - self._started) * 1000)))
        if exc is not None and (self._outcome is None or self._outcome is InvocationOutcome.SUCCESS):
            self._report(*self._exception_outcome(exc), self._http_status, self._response_bytes)
        elif self._outcome is None:
            self._report(InvocationOutcome.INTERNAL_ERROR, "outcome_not_reported", None, 0)
        outcome = self._outcome or InvocationOutcome.INTERNAL_ERROR
        # Set by attach_bodies() only on a sampled call; a sampled call that never handed over
        # its bodies (e.g. refused before the upstream) has nothing to keep.
        sample = self._sample
        record = InvocationRecord(
            tenant_id=self._key.tenant_id,
            key_id=self._key.key_id,
            toolset_id=self._key.toolset_id,
            tool_name=self._tool_name,
            target=self._target,
            invoked_at=self._invoked_at,
            latency_ms=latency_ms,
            outcome=outcome,
            error_code=self._error_code,
            http_status=self._http_status,
            request_bytes=self._request_bytes,
            response_bytes=self._response_bytes,
            sampled=sample is not None,
        )
        try:
            await insert_invocation(self._pool, record, sample)
        except Exception:
            _log.warning(
                "agent_invocation_record_failed",
                key_id=record.key_id,
                tenant_id=record.tenant_id,
                tool=record.tool_name,
                outcome=record.outcome.value,
                exc_info=True,
            )

    def _exception_outcome(self, exc: BaseException) -> tuple[InvocationOutcome, str]:
        """Classify an exception that escaped the block (hook first, then ``internal_error``)."""
        if self._classify is not None:
            try:
                mapped = self._classify(exc)
            except Exception:
                _log.warning("agent_invocation_classify_failed", exc_info=True)
                mapped = None
            if mapped is not None:
                outcome, code = mapped
                if outcome is not InvocationOutcome.SUCCESS and _ERROR_CODE.match(code):
                    return outcome, code
        return InvocationOutcome.INTERNAL_ERROR, "unhandled_exception"


def _utc_now() -> datetime:
    """The current time, timezone-aware (UTC)."""
    return datetime.now(UTC)


def audit_invocation(
    pool: AsyncConnectionPool,
    key: AgentKey,
    *,
    tool_name: str,
    target: Target,
    request_bytes: int,
    capture: BodyCapturePolicy | None = None,
    classify: OutcomeClassifier | None = None,
    wall_clock: Callable[[], datetime] = _utc_now,
    monotonic: Callable[[], float] = time.monotonic,
    draw: Callable[[], float] = random.random,
) -> InvocationAudit:
    """Guard one agent ``tools/call``: ``async with audit_invocation(...) as audit: ...``.

    Args:
        pool: The shared Postgres pool.
        key: The calling agent key (``current_agent_access().key``).
        tool_name: The tool being called.
        target: ``prod`` or ``mock`` (the toolset's target).
        request_bytes: UTF-8 size of the arguments.
        capture: The toolset's :class:`BodyCapturePolicy` (default: capture nothing).
        classify: Maps an escaping exception to an outcome (e.g. AGX-3.2 quota errors).
        wall_clock: Source of the start time (tests).
        monotonic: Source of elapsed time (tests).
        draw: Uniform ``[0, 1)`` source for the sampling decision (tests).

    Returns:
        The audit context; it writes one row when the block exits.
    """
    policy = capture or _NO_CAPTURE
    sampled = policy.rate > 0 and policy.samples(wall_clock(), draw())
    return InvocationAudit(
        pool,
        key,
        tool_name=tool_name,
        target=target,
        request_bytes=request_bytes,
        sampled=sampled,
        classify=classify,
        wall_clock=wall_clock,
        monotonic=monotonic,
    )
