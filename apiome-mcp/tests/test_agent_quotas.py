"""AGX-3.2 per-agent-key quotas & rate limits — unit tests (#4538).

Covers :mod:`apiome_mcp.agent_quotas`:

* reading a tenant's caps and a key's daily count through the V272 SQL functions;
* the token buckets and the daily cap, as :class:`AgentQuotaGuard` combines them (caching, tier
  changes, day rollover, database failures);
* the refusal: its retry hint, its ``isError`` MCP result, and its ``quota_rejected`` invocation row;
* :class:`AgentQuotaMiddleware` driven end to end through an in-memory FastMCP client, stacked
  behind the real :class:`~apiome_mcp.agent_access.AgentAccessMiddleware`.

The ticket's acceptance criteria, as tests:

* a key over its RPS limit or daily cap gets the MCP limit error with a retry hint, and calls under
  the cap are unaffected (``test_*_over_*``, ``test_calls_under_the_caps_*``);
* caps come from the license tier and change when it does (``test_a_tier_change_*``);
* the counter is AGX-3.3's ``agent_invocations`` count without refusals, which is what the rollup
  reports (``test_the_daily_count_*``; the SQL itself is pinned by apiome-db's
  ``agent-key-quotas.test.ts``).
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import mcp.types as mt
import pytest
from fastmcp import Client, Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext

from agent_invocation_fakes import RecordingPool
from apiome_mcp import agent_quotas
from apiome_mcp.agent_access import AgentAccessDeniedError, AgentAccessMiddleware, AgentKey
from apiome_mcp.agent_quotas import (
    AGENT_QUOTA_EXCEEDED_CODE,
    FREE_AGENT_KEY_DAILY_CALLS,
    FREE_AGENT_KEY_RPS,
    AgentQuotaGuard,
    AgentQuotaLimits,
    AgentQuotaMiddleware,
    QuotaLimit,
    QuotaReason,
    QuotaRefusal,
    QuotaRefusalResult,
    TokenBuckets,
    count_agent_key_calls,
    load_agent_quota_limits,
    record_quota_rejection,
    seconds_until_next_utc_day,
)

_TENANT = str(uuid.uuid4())
_KEY = AgentKey(
    key_id=str(uuid.uuid4()),
    tenant_id=_TENANT,
    toolset_id=str(uuid.uuid4()),
    tool_allowlist=frozenset({"listPets", "getPetById"}),
)
_NOON = datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC)
_V272 = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts" / "V272__agent_key_quotas_agx_3_2.sql"


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ============================================================================
# Database reads
# ============================================================================
@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            {"license_type": "paid", "rps": Decimal("20"), "daily_calls": 100000},
            AgentQuotaLimits(rps=20.0, daily_calls=100000, license_type="paid"),
        ),
        (
            {"license_type": "free", "rps": Decimal("0.5"), "daily_calls": 10},
            AgentQuotaLimits(rps=0.5, daily_calls=10, license_type="free"),
        ),
        # NULL is unlimited (V272 maps zero / negative seats values to NULL).
        (
            {"license_type": "sponsor", "rps": None, "daily_calls": None},
            AgentQuotaLimits(rps=None, daily_calls=None, license_type="sponsor"),
        ),
        # Defensive: a non-positive or non-numeric value is treated as unlimited, too.
        (
            {"license_type": None, "rps": 0, "daily_calls": -1},
            AgentQuotaLimits(rps=None, daily_calls=None, license_type=None),
        ),
        ({"license_type": None, "rps": True, "daily_calls": "x"}, AgentQuotaLimits(None, None, None)),
        (None, AgentQuotaLimits(FREE_AGENT_KEY_RPS, FREE_AGENT_KEY_DAILY_CALLS, None)),
    ],
)
def test_caps_are_read_through_agent_key_quota(row: Any, expected: AgentQuotaLimits) -> None:
    pool = RecordingPool(lambda sql, params: row)
    assert _run(load_agent_quota_limits(pool, _TENANT)) == expected
    [(sql, params)] = pool.statements
    assert "apiome.agent_key_quota(%s::uuid)" in sql
    assert params == (_TENANT,)


@pytest.mark.parametrize(("row", "expected"), [({"calls": 41}, 41), ({"calls": None}, 0), (None, 0)])
def test_the_daily_count_is_read_through_agent_key_call_count(row: Any, expected: int) -> None:
    pool = RecordingPool(lambda sql, params: row)
    assert _run(count_agent_key_calls(pool, _KEY.key_id, date(2026, 10, 6))) == expected
    [(sql, params)] = pool.statements
    assert "apiome.agent_key_call_count(%s::uuid, %s::date)" in sql
    assert params == (_KEY.key_id, "2026-10-06")


def test_the_free_fallback_matches_the_v272_seed() -> None:
    sql = _V272.read_text(encoding="utf-8")
    assert f"'agent_key_rps', {int(FREE_AGENT_KEY_RPS)}, 'agent_key_daily_calls', {FREE_AGENT_KEY_DAILY_CALLS})" in sql
    assert f"ELSE {int(FREE_AGENT_KEY_RPS)} END AS rps" in sql
    assert f"ELSE {FREE_AGENT_KEY_DAILY_CALLS} END AS daily_calls" in sql


# ============================================================================
# Retry hints
# ============================================================================
@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (_NOON, 12 * 3600),
        (datetime(2026, 10, 6, 0, 0, 0, tzinfo=UTC), 86400),
        (datetime(2026, 10, 6, 23, 59, 59, 500000, tzinfo=UTC), 1),
        # A non-UTC clock still counts to UTC midnight.
        (datetime(2026, 10, 6, 14, 0, 0, tzinfo=UTC).astimezone(), 10 * 3600),
    ],
)
def test_the_daily_reset_is_the_next_utc_midnight(now: datetime, expected: int) -> None:
    assert seconds_until_next_utc_day(now) == expected


# ============================================================================
# Token buckets
# ============================================================================
def test_a_bucket_allows_one_second_of_burst_then_refills_at_the_rate() -> None:
    buckets = TokenBuckets()
    assert [buckets.take("k", 3, 100.0) for _ in range(3)] == [0, 0, 0]
    assert buckets.take("k", 3, 100.0) == 1
    assert buckets.take("k", 3, 100.34) == 0  # one token back after 1/3 s
    assert buckets.take("k", 3, 100.34) == 1


def test_a_fractional_rate_has_a_burst_of_one_and_a_longer_wait() -> None:
    buckets = TokenBuckets()
    assert buckets.take("k", 0.5, 0.0) == 0
    assert buckets.take("k", 0.5, 0.0) == 2
    assert buckets.take("k", 0.5, 2.0) == 0


def test_buckets_are_per_key() -> None:
    buckets = TokenBuckets()
    assert buckets.take("a", 1, 0.0) == 0
    assert buckets.take("a", 1, 0.0) == 1
    assert buckets.take("b", 1, 0.0) == 0


def test_idle_buckets_are_evicted() -> None:
    buckets = TokenBuckets()
    buckets.take("idle", 1, 0.0)
    for i in range(1000):
        buckets.take(f"k{i % 2}", 1000, 1000.0)
    assert "idle" not in buckets._buckets


# ============================================================================
# The guard
# ============================================================================
class _Sources:
    """Controllable caps and counts for a guard, with call counters."""

    def __init__(self, limits: AgentQuotaLimits, count: int = 0) -> None:
        self.limits = limits
        self.count = count
        self.limits_reads = 0
        self.count_reads = 0
        self.fail_limits = False
        self.fail_count = False

    async def load(self, pool: Any, tenant_id: str) -> AgentQuotaLimits:
        self.limits_reads += 1
        if self.fail_limits:
            raise RuntimeError("db down")
        return self.limits

    async def counter(self, pool: Any, key_id: str, day: date) -> int:
        self.count_reads += 1
        if self.fail_count:
            raise RuntimeError("db down")
        return self.count


def _guard(
    limits: AgentQuotaLimits, count: int = 0, *, limits_ttl: float = 60.0, usage_ttl: float = 5.0
) -> tuple[AgentQuotaGuard, _Sources]:
    sources = _Sources(limits, count)
    guard = AgentQuotaGuard(
        limits_cache_seconds=limits_ttl,
        usage_cache_seconds=usage_ttl,
        load_limits=sources.load,
        count_calls=sources.counter,
    )
    return guard, sources


def _admit(guard: AgentQuotaGuard, *, at: float = 0.0, wall: datetime = _NOON, key: AgentKey = _KEY) -> Any:
    return _run(guard.admit(object(), key, wall_clock=wall, monotonic=at))  # type: ignore[arg-type]


def test_calls_under_the_caps_are_admitted() -> None:
    guard, _ = _guard(AgentQuotaLimits(rps=100, daily_calls=10), count=3)
    assert all(_admit(guard) is None for _ in range(7))


def test_a_key_over_its_daily_cap_is_refused_until_utc_midnight() -> None:
    guard, _ = _guard(AgentQuotaLimits(rps=None, daily_calls=10), count=9)
    assert _admit(guard) is None
    refusal = _admit(guard)
    assert refusal == QuotaRefusal(
        limit=QuotaLimit.DAILY_CALLS,
        cap=10,
        used=10,
        retry_after_seconds=12 * 3600,
        retry_at=datetime(2026, 10, 7, tzinfo=UTC),
    )
    assert refusal.reason is QuotaReason.DAILY_CAP_REACHED


def test_a_key_over_its_rps_limit_is_refused_with_a_seconds_hint() -> None:
    guard, _ = _guard(AgentQuotaLimits(rps=2, daily_calls=None))
    assert _admit(guard, at=10.0) is None
    assert _admit(guard, at=10.0) is None
    refusal = _admit(guard, at=10.0)
    assert refusal is not None and refusal.limit is QuotaLimit.RPS
    assert refusal.reason is QuotaReason.RATE_LIMITED
    assert (refusal.cap, refusal.used, refusal.retry_after_seconds) == (2, 2, 1)
    assert refusal.retry_at == _NOON + timedelta(seconds=1)
    assert _admit(guard, at=10.5) is None  # one token back


def test_refused_calls_are_not_counted() -> None:
    guard, _ = _guard(AgentQuotaLimits(rps=1, daily_calls=3))
    assert _admit(guard, at=0.0) is None
    for _ in range(5):  # a tight retry loop, all refused by the RPS limit
        assert _admit(guard, at=0.0).limit is QuotaLimit.RPS
    assert _admit(guard, at=1.0) is None
    assert _admit(guard, at=2.0) is None
    assert _admit(guard, at=3.0).limit is QuotaLimit.DAILY_CALLS


def test_the_daily_cap_is_checked_before_spending_an_rps_token() -> None:
    guard, _ = _guard(AgentQuotaLimits(rps=1, daily_calls=5), count=5)
    assert _admit(guard).limit is QuotaLimit.DAILY_CALLS
    assert guard._buckets._buckets == {}


def test_unlimited_caps_never_refuse_or_count() -> None:
    guard, sources = _guard(AgentQuotaLimits(rps=None, daily_calls=None))
    assert all(_admit(guard) is None for _ in range(1000))
    assert sources.count_reads == 0


def test_keys_are_limited_independently() -> None:
    other = AgentKey(
        key_id=str(uuid.uuid4()), tenant_id=_TENANT, toolset_id=_KEY.toolset_id, tool_allowlist=frozenset()
    )
    guard, _ = _guard(AgentQuotaLimits(rps=1, daily_calls=None))
    assert _admit(guard) is None
    assert _admit(guard) is not None
    assert _admit(guard, key=other) is None


def test_caps_are_cached_per_tenant() -> None:
    guard, sources = _guard(AgentQuotaLimits(rps=None, daily_calls=None), limits_ttl=60)
    for at in (0.0, 30.0, 59.9):
        _admit(guard, at=at)
    assert sources.limits_reads == 1


def test_a_tier_change_applies_once_the_cache_expires() -> None:
    guard, sources = _guard(AgentQuotaLimits(rps=None, daily_calls=1000), count=50, limits_ttl=60, usage_ttl=0)
    assert _admit(guard, at=0.0) is None
    sources.limits = AgentQuotaLimits(rps=None, daily_calls=50, license_type="free")  # downgraded
    assert _admit(guard, at=30.0) is None  # still the cached tier
    assert _admit(guard, at=61.0).cap == 50
    sources.limits = AgentQuotaLimits(rps=None, daily_calls=100000, license_type="paid")  # upgraded
    assert _admit(guard, at=122.0) is None


def test_the_daily_count_is_reread_on_each_usage_refresh() -> None:
    guard, sources = _guard(AgentQuotaLimits(rps=None, daily_calls=10), count=0, usage_ttl=5)
    for _ in range(4):
        assert _admit(guard, at=0.0) is None
    assert sources.count_reads == 1
    # Another instance made five more calls; the next refresh sees all nine recorded calls.
    sources.count = 9
    assert _admit(guard, at=5.0) is None
    assert sources.count_reads == 2
    assert _admit(guard, at=6.0).used == 10


def test_admitted_calls_count_even_before_they_are_recorded() -> None:
    # Nothing records invocations (e.g. before the AGX-2.1 call path lands): the cap still holds.
    guard, sources = _guard(AgentQuotaLimits(rps=None, daily_calls=3), count=0, usage_ttl=0)
    assert [_admit(guard, at=float(i)) is None for i in range(4)] == [True, True, True, False]
    assert sources.count_reads == 4


def test_the_count_starts_over_on_a_new_utc_day() -> None:
    guard, sources = _guard(AgentQuotaLimits(rps=None, daily_calls=2), count=0, usage_ttl=3600)
    assert _admit(guard) is None
    assert _admit(guard) is None
    assert _admit(guard) is not None
    tomorrow = _NOON + timedelta(days=1)
    assert _admit(guard, wall=tomorrow) is None
    assert sources.count_reads == 2


def test_unreadable_caps_fall_back_to_the_last_known_then_free() -> None:
    guard, sources = _guard(AgentQuotaLimits(rps=None, daily_calls=None, license_type="sponsor"), limits_ttl=10)
    sources.fail_limits = True
    assert _run(guard.limits_for(object(), "fresh-tenant", 0.0)) == AgentQuotaLimits(  # type: ignore[arg-type]
        FREE_AGENT_KEY_RPS, FREE_AGENT_KEY_DAILY_CALLS, None
    )
    sources.fail_limits = False
    assert _run(guard.limits_for(object(), _TENANT, 0.0)).license_type == "sponsor"  # type: ignore[arg-type]
    sources.fail_limits = True
    assert _run(guard.limits_for(object(), _TENANT, 11.0)).license_type == "sponsor"  # type: ignore[arg-type]


def test_an_unreadable_count_keeps_the_last_one() -> None:
    guard, sources = _guard(AgentQuotaLimits(rps=None, daily_calls=10), count=8, usage_ttl=0)
    assert _admit(guard, at=0.0) is None
    sources.fail_count = True
    assert _admit(guard, at=1.0) is None  # 8 counted + 1 admitted, then this one
    assert _admit(guard, at=2.0).used == 10


def test_from_settings_uses_the_configured_cache_lifetimes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_MCP_DATABASE_URL", "postgresql://localhost/db")
    monkeypatch.setenv("APIOME_MCP_INTERNAL_SECRET", "x" * 16)
    monkeypatch.setenv("APIOME_MCP_AGENT_QUOTA_LIMITS_CACHE_SECONDS", "15")
    monkeypatch.setenv("APIOME_MCP_AGENT_QUOTA_USAGE_CACHE_SECONDS", "2.5")
    from apiome_mcp.settings import Settings

    guard = AgentQuotaGuard.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]
    assert (guard._limits_ttl, guard._usage_ttl) == (15.0, 2.5)


def test_settings_default_cache_lifetimes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_MCP_DATABASE_URL", "postgresql://localhost/db")
    monkeypatch.setenv("APIOME_MCP_INTERNAL_SECRET", "x" * 16)
    from apiome_mcp.settings import Settings

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.agent_quota_limits_cache_seconds == 60.0
    assert settings.agent_quota_usage_cache_seconds == 5.0


# ============================================================================
# The refusal
# ============================================================================
_DAILY = QuotaRefusal(QuotaLimit.DAILY_CALLS, 1000, 1000, 3600, datetime(2026, 10, 7, tzinfo=UTC))
_RPS = QuotaRefusal(QuotaLimit.RPS, 0.5, 1, 2, datetime(2026, 10, 6, 12, 0, 2, 750000, tzinfo=UTC))


def test_the_message_leads_with_the_reason_and_says_when_to_retry() -> None:
    assert _DAILY.message() == (
        "agent_daily_cap_reached: this agent key has used its 1000 calls for today (UTC); "
        "retry after 3600 s (2026-10-07T00:00:00Z)."
    )
    assert _RPS.message() == (
        "agent_rate_limited: this agent key is limited to 0.5 calls per second; retry after 2 s (2026-10-06T12:00:02Z)."
    )


def test_the_payload_carries_429_semantics_and_no_identifiers() -> None:
    payload = _DAILY.payload()
    assert payload == {
        "error": {"code": AGENT_QUOTA_EXCEEDED_CODE, "reason": "agent_daily_cap_reached", "message": _DAILY.message()},
        "reason": "agent_daily_cap_reached",
        "limit": "daily_calls",
        "cap": 1000,
        "used": 1000,
        "retryAfterSeconds": 3600,
        "retryAt": "2026-10-07T00:00:00Z",
        "httpStatus": 429,
    }
    assert _KEY.key_id not in str(payload) and _TENANT not in str(payload)


def test_the_quota_code_sits_beside_the_agent_access_codes() -> None:
    from apiome_mcp.agent_access import AGENT_KEY_REJECTED_CODE, AGENT_TOOLSET_UNAVAILABLE_CODE

    assert AGENT_QUOTA_EXCEEDED_CODE == -32012
    assert AGENT_QUOTA_EXCEEDED_CODE not in {
        AGENT_KEY_REJECTED_CODE,
        AGENT_TOOLSET_UNAVAILABLE_CODE,
        -32000,
        -32001,
        -32002,
    }


def test_the_result_is_an_mcp_error_result_with_structured_content() -> None:
    result = QuotaRefusalResult(_RPS).to_mcp_result()
    assert isinstance(result, mt.CallToolResult)
    assert result.isError is True
    assert result.structuredContent == _RPS.payload()
    assert [block.text for block in result.content] == [_RPS.message()]  # type: ignore[union-attr]


def test_reason_codes_fit_the_invocation_error_code_grammar() -> None:
    for reason in QuotaReason:
        assert re.fullmatch(r"^[a-z][a-z0-9_.]{0,63}$", reason.value)


def _insert_id(sql: str, params: Any) -> Any:
    if "INSERT INTO apiome.agent_invocations" in sql:
        return ("inv-1",)
    if "FROM apiome.agent_toolsets" in sql:
        return {"target": "mock"}
    return None


def test_a_refusal_is_recorded_as_a_quota_rejected_invocation() -> None:
    pool = RecordingPool(_insert_id)
    _run(record_quota_rejection(pool, _KEY, "listPets", _DAILY, request_bytes=12))
    [(_, target_params)] = pool.sql_containing("FROM apiome.agent_toolsets")
    assert target_params == (_KEY.toolset_id, _KEY.tenant_id)
    [(_, params)] = pool.sql_containing("INSERT INTO apiome.agent_invocations")
    tenant, key, toolset, tool, target, _, latency, outcome, code, status, req, resp, sampled = params
    assert (tenant, key, toolset, tool, target) == (_TENANT, _KEY.key_id, _KEY.toolset_id, "listPets", "mock")
    assert (outcome, code, status, req, resp, sampled) == (
        "quota_rejected",
        "agent_daily_cap_reached",
        None,
        12,
        0,
        False,
    )
    assert latency >= 0


def test_a_refusal_record_defaults_to_prod_and_never_raises() -> None:
    pool = RecordingPool(fail_on="FROM apiome.agent_toolsets")
    _run(record_quota_rejection(pool, _KEY, "listPets", _RPS))
    [(_, params)] = pool.sql_containing("INSERT INTO apiome.agent_invocations")
    assert params[4] == "prod"

    broken = RecordingPool(fail_on="INSERT INTO apiome.agent_invocations")
    _run(record_quota_rejection(broken, _KEY, "listPets", _RPS))  # logged, not raised


# ============================================================================
# The middleware, end to end (in-memory FastMCP client)
# ============================================================================
def _agent_surface(guard: AgentQuotaGuard, pool: RecordingPool) -> FastMCP:
    """A stand-in agent surface: two tools, the access middleware, then the quota middleware."""

    async def enabled(ctx: Context, key: AgentKey) -> set[str]:
        return {"listPets", "getPetById", "deletePet"}

    app = FastMCP("AgentSurface")
    app.add_middleware(AgentAccessMiddleware(key_resolver=AsyncMock(return_value=_KEY), enabled_tools=enabled))
    app.add_middleware(AgentQuotaMiddleware(guard=guard, pool_source=lambda ctx: pool))  # type: ignore[arg-type,return-value]

    @app.tool(name="listPets")
    def list_pets() -> list[str]:
        """List pets."""
        return ["Rex", "Tom"]

    @app.tool(name="getPetById")
    def get_pet_by_id(pet_id: int) -> dict[str, Any]:
        """Get one pet."""
        return {"id": pet_id}

    @app.tool(name="deletePet")
    def delete_pet(pet_id: int) -> str:
        """Delete a pet (not on the key's allowlist)."""
        return "deleted"

    return app


_META = {"apiome_api_key": "ak_" + "0" * 64}


@pytest.fixture(autouse=True)
def _bearer_on_every_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """Present the key as an HTTP bearer, so the client's own ``tools/list`` (no ``_meta``) passes too."""
    monkeypatch.setattr(
        "apiome_mcp.agent_access.get_http_headers",
        lambda include=None: {"authorization": f"Bearer {_META['apiome_api_key']}"},
    )


async def _calls(app: FastMCP, *calls: tuple[str, dict[str, Any]]) -> list[mt.CallToolResult]:
    async with Client(app) as client:
        return [await client.call_tool_mcp(name, args, meta=_META) for name, args in calls]


def test_calls_under_the_caps_are_unaffected_end_to_end() -> None:
    guard, _ = _guard(AgentQuotaLimits(rps=100, daily_calls=100))
    pool = RecordingPool(_insert_id)
    results = _run(_calls(_agent_surface(guard, pool), ("listPets", {}), ("getPetById", {"pet_id": 7})))
    assert [r.isError for r in results] == [False, False]
    assert results[1].structuredContent == {"id": 7}
    assert pool.sql_containing("INSERT INTO apiome.agent_invocations") == []


def test_a_key_over_its_rps_limit_gets_the_limit_error_end_to_end() -> None:
    guard, _ = _guard(AgentQuotaLimits(rps=1, daily_calls=None))
    pool = RecordingPool(_insert_id)
    ok, refused = _run(_calls(_agent_surface(guard, pool), ("listPets", {}), ("getPetById", {"pet_id": 1})))
    assert ok.isError is False
    assert refused.isError is True
    assert refused.content[0].text.startswith("agent_rate_limited: ")  # type: ignore[union-attr]
    assert refused.structuredContent is not None
    assert refused.structuredContent["retryAfterSeconds"] >= 1
    assert refused.structuredContent["httpStatus"] == 429
    assert refused.structuredContent["error"]["code"] == AGENT_QUOTA_EXCEEDED_CODE
    [(_, params)] = pool.sql_containing("INSERT INTO apiome.agent_invocations")
    assert (params[3], params[7], params[8]) == ("getPetById", "quota_rejected", "agent_rate_limited")
    assert params[10] == len('{"pet_id":1}')


def test_a_key_over_its_daily_cap_gets_the_limit_error_end_to_end() -> None:
    guard, _ = _guard(AgentQuotaLimits(rps=None, daily_calls=5), count=5)
    pool = RecordingPool(_insert_id)
    [refused] = _run(_calls(_agent_surface(guard, pool), ("listPets", {})))
    assert refused.isError is True
    assert refused.structuredContent is not None
    assert refused.structuredContent["reason"] == "agent_daily_cap_reached"
    assert refused.structuredContent["limit"] == "daily_calls"
    assert (refused.structuredContent["cap"], refused.structuredContent["used"]) == (5, 5)


def test_the_client_raises_a_tool_error_carrying_the_hint() -> None:
    guard, _ = _guard(AgentQuotaLimits(rps=None, daily_calls=1), count=1)

    async def run() -> None:
        async with Client(_agent_surface(guard, RecordingPool(_insert_id))) as client:
            await client.call_tool("listPets", {}, meta=_META)

    with pytest.raises(ToolError, match=r"^agent_daily_cap_reached: .*retry after \d+ s"):
        _run(run())


def test_a_non_permitted_tool_is_still_unknown_and_never_counted() -> None:
    guard, sources = _guard(AgentQuotaLimits(rps=None, daily_calls=10))
    pool = RecordingPool(_insert_id)
    [result] = _run(_calls(_agent_surface(guard, pool), ("deletePet", {"pet_id": 1})))
    assert result.isError is True
    assert result.content[0].text == "Unknown tool: 'deletePet'"  # type: ignore[union-attr]
    assert sources.limits_reads == 0 and sources.count_reads == 0


def test_listing_tools_is_not_a_call() -> None:
    # Only tools/call is gated; tools/list, resources and prompts pass straight through.
    for hook in ("on_list_tools", "on_request", "on_read_resource", "on_get_prompt"):
        assert getattr(AgentQuotaMiddleware, hook) is getattr(Middleware, hook)


def test_the_middleware_fails_closed_without_a_verified_key() -> None:
    mw = AgentQuotaMiddleware(guard=_guard(AgentQuotaLimits(None, None))[0], pool_source=lambda ctx: RecordingPool())  # type: ignore[arg-type,return-value]
    call_next = AsyncMock()
    ctx = MiddlewareContext(message=mt.CallToolRequestParams(name="listPets", arguments={}), fastmcp_context=object())  # type: ignore[arg-type]
    with pytest.raises(AgentAccessDeniedError):
        _run(mw.on_call_tool(ctx, call_next))
    call_next.assert_not_awaited()


def test_the_default_guard_and_pool_are_the_database_ones() -> None:
    mw = AgentQuotaMiddleware()
    assert isinstance(mw._guard, AgentQuotaGuard)
    assert mw._guard._load_limits is load_agent_quota_limits
    assert mw._guard._count_calls is count_agent_key_calls
    assert mw._pool_source is agent_quotas.get_db_pool


def test_the_catalog_server_never_mounts_agent_quotas() -> None:
    from apiome_mcp.server import mcp

    assert not any(isinstance(middleware, AgentQuotaMiddleware) for middleware in mcp.middleware)
