"""AGX-3.3 invocation audit (#4539): exactly one metadata-only row per agent ``tools/call``.

Covers the acceptance criteria on the apiome-mcp side:

* every outcome — success, upstream error, validation failure, quota rejection, and failures the
  call path never classified — produces exactly one ``agent_invocations`` row;
* the row is metadata only, and bodies are absent unless the toolset explicitly opted in to
  sampled capture, which is bounded in rate, time and size;
* recording never breaks the call: a database failure is swallowed and logged, and the call's own
  exception goes through unchanged.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from agent_invocation_fakes import RecordingPool
from apiome_mcp.agent_access import AgentKey
from apiome_mcp.agent_invocations import (
    MAX_SAMPLE_BYTES,
    BodyCapturePolicy,
    InvocationOutcome,
    InvocationRecord,
    audit_invocation,
    insert_invocation,
    load_body_capture_policy,
    truncate_body,
)

KEY = AgentKey(
    key_id="00000000-0000-4000-8000-0000000000a1",
    tenant_id="00000000-0000-4000-8000-0000000000b2",
    toolset_id="00000000-0000-4000-8000-0000000000c3",
    tool_allowlist=frozenset({"listPets"}),
)
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
INVOCATION_ID = "00000000-0000-4000-8000-0000000000d4"

#: Column order of the ``agent_invocations`` INSERT.
COLUMNS = (
    "tenant_id",
    "key_id",
    "toolset_id",
    "tool_name",
    "target",
    "invoked_at",
    "latency_ms",
    "outcome",
    "error_code",
    "http_status",
    "request_bytes",
    "response_bytes",
    "sampled",
)


def _pool(**kwargs: Any) -> RecordingPool:
    """A pool whose invocation INSERT returns :data:`INVOCATION_ID`."""
    return RecordingPool(
        lambda sql, params: (INVOCATION_ID,) if "INSERT INTO apiome.agent_invocations" in sql else None,
        **kwargs,
    )


class _Clock:
    """A monotonic clock that advances by ``step`` seconds on every read."""

    def __init__(self, step: float) -> None:
        self.now = 100.0
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


def _audit(pool: RecordingPool, **kwargs: Any) -> Any:
    """``audit_invocation`` with a fixed wall clock and a 0.25 s call."""
    kwargs.setdefault("tool_name", "listPets")
    kwargs.setdefault("target", "prod")
    kwargs.setdefault("request_bytes", 42)
    return audit_invocation(pool, KEY, wall_clock=lambda: NOW, monotonic=_Clock(0.25), **kwargs)


def _rows(pool: RecordingPool) -> list[dict[str, Any]]:
    """The recorded ``agent_invocations`` INSERTs, as column → value."""
    return [dict(zip(COLUMNS, params, strict=True)) for _, params in pool.sql_containing("agent_invocations (")]


def _samples(pool: RecordingPool) -> list[Any]:
    """Parameters of the recorded ``agent_invocation_samples`` INSERTs."""
    return [params for _, params in pool.sql_containing("agent_invocation_samples")]


# ---------------------------------------------------------------------------------------------------
# Exactly one row per call, whatever the outcome.
# ---------------------------------------------------------------------------------------------------


def test_success_writes_one_metadata_row() -> None:
    pool = _pool()

    async def call() -> None:
        async with _audit(pool) as audit:
            audit.succeeded(http_status=200, response_bytes=512)

    asyncio.run(call())
    assert _rows(pool) == [
        {
            "tenant_id": KEY.tenant_id,
            "key_id": KEY.key_id,
            "toolset_id": KEY.toolset_id,
            "tool_name": "listPets",
            "target": "prod",
            "invoked_at": NOW,
            "latency_ms": 250,
            "outcome": "success",
            "error_code": None,
            "http_status": 200,
            "request_bytes": 42,
            "response_bytes": 512,
            "sampled": False,
        }
    ]
    assert _samples(pool) == []
    assert pool.transactions == 1


def test_upstream_error_is_recorded_with_status_and_code() -> None:
    pool = _pool()

    async def call() -> None:
        async with _audit(pool, target="mock") as audit:
            audit.failed(InvocationOutcome.UPSTREAM_ERROR, "upstream_http_error", http_status=502, response_bytes=31)

    asyncio.run(call())
    [row] = _rows(pool)
    assert (row["outcome"], row["error_code"], row["http_status"], row["target"]) == (
        "upstream_error",
        "upstream_http_error",
        502,
        "mock",
    )
    assert row["response_bytes"] == 31


def test_validation_failure_is_recorded_without_an_upstream_status() -> None:
    pool = _pool()

    async def call() -> None:
        async with _audit(pool) as audit:
            audit.failed(InvocationOutcome.VALIDATION_FAILURE, "invalid_arguments")

    asyncio.run(call())
    [row] = _rows(pool)
    assert (row["outcome"], row["error_code"], row["http_status"]) == (
        "validation_failure",
        "invalid_arguments",
        None,
    )


class QuotaExceededError(Exception):
    """Stand-in for AGX-3.2's limit error."""


def _classify(exc: BaseException) -> tuple[InvocationOutcome, str] | None:
    if isinstance(exc, QuotaExceededError):
        return InvocationOutcome.QUOTA_REJECTED, "quota_daily_exceeded"
    return None


def test_quota_rejection_raised_by_the_call_is_classified_and_reraised() -> None:
    pool = _pool()

    async def call() -> None:
        async with _audit(pool, classify=_classify):
            raise QuotaExceededError("daily cap")

    with pytest.raises(QuotaExceededError):
        asyncio.run(call())
    [row] = _rows(pool)
    assert (row["outcome"], row["error_code"]) == ("quota_rejected", "quota_daily_exceeded")


def test_quota_rejection_reported_explicitly() -> None:
    pool = _pool()

    async def call() -> None:
        async with _audit(pool) as audit:
            audit.failed(InvocationOutcome.QUOTA_REJECTED, "quota_rps_exceeded")

    asyncio.run(call())
    assert [row["outcome"] for row in _rows(pool)] == ["quota_rejected"]


def test_unclassified_exception_is_an_internal_error_and_propagates() -> None:
    pool = _pool()

    async def call() -> None:
        async with _audit(pool, classify=_classify):
            raise KeyError("boom")

    with pytest.raises(KeyError):
        asyncio.run(call())
    [row] = _rows(pool)
    assert (row["outcome"], row["error_code"]) == ("internal_error", "unhandled_exception")


def test_exception_after_a_reported_success_is_not_recorded_as_success() -> None:
    pool = _pool()

    async def call() -> None:
        async with _audit(pool) as audit:
            audit.succeeded(http_status=200, response_bytes=10)
            raise RuntimeError("result mapping failed")

    with pytest.raises(RuntimeError):
        asyncio.run(call())
    [row] = _rows(pool)
    assert (row["outcome"], row["error_code"], row["http_status"]) == (
        "internal_error",
        "unhandled_exception",
        200,
    )


def test_reported_failure_survives_a_following_exception() -> None:
    pool = _pool()

    async def call() -> None:
        async with _audit(pool) as audit:
            audit.failed(InvocationOutcome.UPSTREAM_ERROR, "upstream_timeout")
            raise TimeoutError

    with pytest.raises(TimeoutError):
        asyncio.run(call())
    assert [(r["outcome"], r["error_code"]) for r in _rows(pool)] == [("upstream_error", "upstream_timeout")]


def test_unreported_outcome_is_still_one_row() -> None:
    pool = _pool()

    async def call() -> None:
        async with _audit(pool):
            pass

    asyncio.run(call())
    [row] = _rows(pool)
    assert (row["outcome"], row["error_code"]) == ("internal_error", "outcome_not_reported")


def test_cancelled_call_is_recorded() -> None:
    pool = _pool()

    async def call() -> None:
        async with _audit(pool):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(call())
    assert [row["outcome"] for row in _rows(pool)] == ["internal_error"]


def test_a_misbehaving_classifier_falls_back_to_internal_error() -> None:
    pool = _pool()

    def broken(exc: BaseException) -> tuple[InvocationOutcome, str] | None:
        raise ValueError("bug")

    def bad_code(exc: BaseException) -> tuple[InvocationOutcome, str] | None:
        return InvocationOutcome.UPSTREAM_ERROR, "Not A Code"

    async def call(classify: Any) -> None:
        async with _audit(pool, classify=classify):
            raise RuntimeError

    for classify in (broken, bad_code):
        with pytest.raises(RuntimeError):
            asyncio.run(call(classify))
    assert [r["error_code"] for r in _rows(pool)] == ["unhandled_exception", "unhandled_exception"]


def test_last_report_wins() -> None:
    pool = _pool()

    async def call() -> None:
        async with _audit(pool) as audit:
            audit.failed(InvocationOutcome.UPSTREAM_ERROR, "upstream_timeout")
            audit.succeeded(http_status=200)

    asyncio.run(call())
    assert [r["outcome"] for r in _rows(pool)] == ["success"]


def test_out_of_range_http_status_is_dropped() -> None:
    pool = _pool()

    async def call() -> None:
        async with _audit(pool) as audit:
            audit.succeeded(http_status=999, response_bytes=-5)

    asyncio.run(call())
    [row] = _rows(pool)
    assert (row["http_status"], row["response_bytes"]) == (None, 0)


def test_negative_request_size_is_clamped() -> None:
    pool = _pool()

    async def call() -> None:
        async with _audit(pool, request_bytes=-1) as audit:
            audit.succeeded()

    asyncio.run(call())
    assert _rows(pool)[0]["request_bytes"] == 0


# ---------------------------------------------------------------------------------------------------
# Misuse is refused up front rather than failing the V271 CHECKs later.
# ---------------------------------------------------------------------------------------------------


def test_failed_refuses_success_and_non_machine_codes() -> None:
    pool = _pool()

    async def call() -> None:
        async with _audit(pool) as audit:
            with pytest.raises(ValueError):
                audit.failed(InvocationOutcome.SUCCESS, "ok")
            with pytest.raises(ValueError):
                audit.failed(InvocationOutcome.UPSTREAM_ERROR, "Upstream said: secret token abc")
            with pytest.raises(ValueError):
                audit.failed(InvocationOutcome.UPSTREAM_ERROR, "")
            audit.succeeded()

    asyncio.run(call())
    assert [r["outcome"] for r in _rows(pool)] == ["success"]


# ---------------------------------------------------------------------------------------------------
# Recording never breaks the call.
# ---------------------------------------------------------------------------------------------------


def test_database_failure_is_swallowed() -> None:
    pool = _pool(fail_on="agent_invocations")

    async def call() -> str:
        async with _audit(pool) as audit:
            audit.succeeded(http_status=200)
        return "result"

    assert asyncio.run(call()) == "result"
    assert pool.rollbacks == 1


def test_database_failure_does_not_mask_the_calls_exception() -> None:
    pool = _pool(fail_on="agent_invocations")

    async def call() -> None:
        async with _audit(pool):
            raise LookupError("original")

    with pytest.raises(LookupError, match="original"):
        asyncio.run(call())


# ---------------------------------------------------------------------------------------------------
# Bodies: absent by default; opt-in sampling is bounded.
# ---------------------------------------------------------------------------------------------------


def test_bodies_are_absent_by_default() -> None:
    pool = _pool()

    async def call() -> None:
        async with _audit(pool) as audit:
            assert audit.sampled is False
            audit.attach_bodies(request_body='{"secret": "s3"}', response_body='{"pii": "x"}')
            audit.succeeded(http_status=200)

    asyncio.run(call())
    assert _samples(pool) == []
    assert _rows(pool)[0]["sampled"] is False
    for sql, params in pool.statements:
        assert "body" not in sql
        assert all("s3" not in str(value) and "pii" not in str(value) for value in params)


def test_open_capture_window_samples_and_stores_bodies() -> None:
    pool = _pool()
    policy = BodyCapturePolicy(rate=1.0, until=NOW + timedelta(days=1))

    async def call() -> None:
        async with _audit(pool, capture=policy, draw=lambda: 0.5) as audit:
            assert audit.sampled is True
            audit.attach_bodies(request_body='{"id": 1}', response_body="é" * MAX_SAMPLE_BYTES)
            audit.succeeded(http_status=200)

    asyncio.run(call())
    assert _rows(pool)[0]["sampled"] is True
    [(invocation_id, tenant_id, request, response, request_cut, response_cut)] = _samples(pool)
    assert (invocation_id, tenant_id, request, request_cut) == (INVOCATION_ID, KEY.tenant_id, '{"id": 1}', False)
    assert response_cut is True
    assert len(response.encode("utf-8")) <= MAX_SAMPLE_BYTES


def test_sampled_call_without_bodies_stores_no_sample() -> None:
    pool = _pool()
    policy = BodyCapturePolicy(rate=1.0, until=NOW + timedelta(days=1))

    async def call() -> None:
        async with _audit(pool, capture=policy, draw=lambda: 0.0) as audit:
            audit.failed(InvocationOutcome.VALIDATION_FAILURE, "invalid_arguments")

    asyncio.run(call())
    assert _samples(pool) == []
    assert _rows(pool)[0]["sampled"] is False


@pytest.mark.parametrize(
    ("policy", "draw", "expected"),
    [
        (BodyCapturePolicy(), 0.0, False),
        (BodyCapturePolicy(rate=0.0, until=NOW + timedelta(days=1)), 0.0, False),
        (BodyCapturePolicy(rate=1.0, until=None), 0.0, False),
        (BodyCapturePolicy(rate=1.0, until=NOW), 0.0, False),
        (BodyCapturePolicy(rate=1.0, until=NOW - timedelta(seconds=1)), 0.0, False),
        (BodyCapturePolicy(rate=0.1, until=NOW + timedelta(days=1)), 0.1, False),
        (BodyCapturePolicy(rate=0.1, until=NOW + timedelta(days=1)), 0.09, True),
        (BodyCapturePolicy(rate=1.0, until=NOW + timedelta(days=1)), 0.999, True),
    ],
)
def test_sampling_decision(policy: BodyCapturePolicy, draw: float, expected: bool) -> None:
    assert policy.samples(NOW, draw) is expected


def test_truncate_body_keeps_whole_characters() -> None:
    assert truncate_body(None) == (None, False)
    assert truncate_body("abc", 3) == ("abc", False)
    text, cut = truncate_body("aé€", 4)
    assert (text, cut) == ("aé", True)
    assert truncate_body("€€", 2) == ("", True)


def test_load_body_capture_policy_reads_the_toolset() -> None:
    until = NOW + timedelta(days=2)
    pool = RecordingPool(lambda sql, params: {"body_capture_rate": Decimal("0.2500"), "body_capture_until": until})
    policy = asyncio.run(load_body_capture_policy(pool, KEY.tenant_id, KEY.toolset_id))
    assert policy == BodyCapturePolicy(rate=0.25, until=until)
    [(sql, params)] = pool.statements
    assert "tenant_id = %s::uuid" in sql
    assert params == (KEY.toolset_id, KEY.tenant_id)


def test_missing_toolset_captures_nothing() -> None:
    pool = RecordingPool()
    assert asyncio.run(load_body_capture_policy(pool, KEY.tenant_id, KEY.toolset_id)) == BodyCapturePolicy()


def test_insert_invocation_writes_row_and_sample_in_one_transaction() -> None:
    pool = _pool()
    record = InvocationRecord(
        tenant_id=KEY.tenant_id,
        key_id=KEY.key_id,
        toolset_id=KEY.toolset_id,
        tool_name="listPets",
        target="prod",
        invoked_at=NOW,
        latency_ms=5,
        outcome=InvocationOutcome.SUCCESS,
        error_code=None,
        http_status=200,
        request_bytes=1,
        response_bytes=2,
    )
    assert asyncio.run(insert_invocation(pool, record)) == INVOCATION_ID
    assert pool.transactions == 1
    assert len(pool.statements) == 1
