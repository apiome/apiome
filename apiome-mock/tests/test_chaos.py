"""Unit tests for latency/chaos injection parsing and helpers (#4455, SIM-4.3)."""

from __future__ import annotations

import asyncio
import random

from apiome_mock.chaos import (
    EMPTY_CHAOS,
    MAX_CHAOS_DELAY_MS,
    ChaosConfig,
    ChaosDelayGuard,
    ChaosKnobs,
    ChaosKnobSettings,
    apply_chaos_delay,
    compute_delay_ms,
    effective_knobs,
    parse_chaos,
    parse_chaos_block,
    should_inject_error,
)

# ---------------------------------------------------------------------------
# parse_chaos / parse_chaos_block
# ---------------------------------------------------------------------------


def test_parse_chaos_reads_default_and_operations() -> None:
    config = parse_chaos(
        {
            "chaos": {
                "default": {"delayMs": 800, "jitterMs": 200, "errorRate": 10},
                "operations": {"get /pets": {"delayMs": 100}},
            }
        }
    )
    assert config.default == ChaosKnobSettings(delay_ms=800, jitter_ms=200, error_rate=10.0)
    assert config.operations == {"GET /pets": ChaosKnobSettings(delay_ms=100)}


def test_parse_chaos_accepts_json_text() -> None:
    config = parse_chaos('{"chaos": {"default": {"delayMs": 5}}}')
    assert config.default.delay_ms == 5


def test_parse_chaos_tolerates_garbage() -> None:
    assert parse_chaos(None) is EMPTY_CHAOS
    assert parse_chaos("not json") is EMPTY_CHAOS
    assert parse_chaos(42) is EMPTY_CHAOS
    assert parse_chaos({"chaos": "nope"}) is EMPTY_CHAOS
    assert parse_chaos({}) is EMPTY_CHAOS


def test_parse_chaos_skips_malformed_fields_and_entries() -> None:
    config = parse_chaos(
        {
            "chaos": {
                "default": {"delayMs": True, "jitterMs": -5, "errorRate": 200},
                "operations": {
                    "not-a-key": {"delayMs": 1},
                    "GET /pets": "nope",
                    "POST /pets": {"delayMs": "fast"},
                },
            }
        }
    )
    # Malformed knob values are treated as unset, not as errors.
    assert config.default == ChaosKnobSettings()
    # Bad operation keys / non-dict entries are dropped; bad fields inside a
    # valid entry are unset.
    assert config.operations == {"POST /pets": ChaosKnobSettings()}


def test_parse_chaos_caps_millisecond_knobs() -> None:
    config = parse_chaos({"chaos": {"default": {"delayMs": 90_000, "jitterMs": 60_000}}})
    assert config.default.delay_ms == MAX_CHAOS_DELAY_MS
    assert config.default.jitter_ms == MAX_CHAOS_DELAY_MS


def test_parse_chaos_block_distinguishes_absent_from_empty() -> None:
    assert parse_chaos_block(None) is None
    assert parse_chaos_block("nope") is None
    empty = parse_chaos_block({})
    assert empty is not None
    assert empty.default == ChaosKnobSettings()
    assert empty.operations == {}


# ---------------------------------------------------------------------------
# effective_knobs
# ---------------------------------------------------------------------------


def _config(default: ChaosKnobSettings | None = None, **operations: ChaosKnobSettings) -> ChaosConfig:
    return ChaosConfig(default=default or ChaosKnobSettings(), operations=dict(operations))


def test_effective_knobs_defaults_to_zero() -> None:
    assert effective_knobs(EMPTY_CHAOS, "GET /pets") == ChaosKnobs()


def test_effective_knobs_uses_default_without_override() -> None:
    config = _config(ChaosKnobSettings(delay_ms=800, jitter_ms=200, error_rate=10.0))
    assert effective_knobs(config, "GET /pets") == ChaosKnobs(delay_ms=800, jitter_ms=200, error_rate=10.0)


def test_effective_knobs_operation_overrides_field_by_field() -> None:
    config = ChaosConfig(
        default=ChaosKnobSettings(delay_ms=800, jitter_ms=200, error_rate=10.0),
        operations={"GET /pets": ChaosKnobSettings(error_rate=50.0)},
    )
    knobs = effective_knobs(config, "GET /pets")
    # errorRate comes from the override; unset delay/jitter inherit the default.
    assert knobs == ChaosKnobs(delay_ms=800, jitter_ms=200, error_rate=50.0)


def test_effective_knobs_explicit_zero_beats_default() -> None:
    config = ChaosConfig(
        default=ChaosKnobSettings(delay_ms=800),
        operations={"GET /pets": ChaosKnobSettings(delay_ms=0)},
    )
    assert effective_knobs(config, "GET /pets").delay_ms == 0


# ---------------------------------------------------------------------------
# compute_delay_ms / should_inject_error
# ---------------------------------------------------------------------------


def test_compute_delay_zero_knobs() -> None:
    assert compute_delay_ms(ChaosKnobs()) == 0


def test_compute_delay_without_jitter_is_exact() -> None:
    assert compute_delay_ms(ChaosKnobs(delay_ms=800), random.Random(1)) == 800


def test_compute_delay_jitter_stays_in_range() -> None:
    rng = random.Random(42)
    knobs = ChaosKnobs(delay_ms=800, jitter_ms=200)
    draws = {compute_delay_ms(knobs, rng) for _ in range(500)}
    assert min(draws) >= 600
    assert max(draws) <= 1000
    assert len(draws) > 1  # jitter actually varies the delay


def test_compute_delay_never_negative() -> None:
    rng = random.Random(7)
    knobs = ChaosKnobs(delay_ms=50, jitter_ms=500)
    assert all(compute_delay_ms(knobs, rng) >= 0 for _ in range(200))


def test_compute_delay_caps_at_thirty_seconds() -> None:
    rng = random.Random(3)
    knobs = ChaosKnobs(delay_ms=MAX_CHAOS_DELAY_MS, jitter_ms=MAX_CHAOS_DELAY_MS)
    assert all(compute_delay_ms(knobs, rng) <= MAX_CHAOS_DELAY_MS for _ in range(200))


def test_should_inject_error_edges() -> None:
    assert should_inject_error(ChaosKnobs(error_rate=0)) is False
    assert should_inject_error(ChaosKnobs(error_rate=100)) is True


def test_should_inject_error_statistically_honors_rate() -> None:
    rng = random.Random(1234)
    knobs = ChaosKnobs(error_rate=30.0)
    hits = sum(1 for _ in range(2000) if should_inject_error(knobs, rng))
    assert 500 <= hits <= 700  # ~600 expected at 30%


# ---------------------------------------------------------------------------
# ChaosDelayGuard / apply_chaos_delay
# ---------------------------------------------------------------------------


def test_delay_guard_caps_concurrency_per_tenant() -> None:
    guard = ChaosDelayGuard(max_concurrent=2)
    assert guard.try_acquire("acme") is True
    assert guard.try_acquire("acme") is True
    assert guard.try_acquire("acme") is False
    # Other tenants have their own budget.
    assert guard.try_acquire("other") is True
    guard.release("acme")
    assert guard.try_acquire("acme") is True


def test_apply_chaos_delay_sleeps_and_reports_applied() -> None:
    async def _run() -> None:
        guard = ChaosDelayGuard(max_concurrent=2)
        applied = await apply_chaos_delay(20, tenant="acme", guard=guard)
        assert applied == 20
        # The slot is released after the sleep.
        assert guard.try_acquire("acme") is True

    asyncio.run(_run())


def test_apply_chaos_delay_skips_when_zero_or_saturated() -> None:
    async def _run() -> None:
        guard = ChaosDelayGuard(max_concurrent=1)
        assert await apply_chaos_delay(0, tenant="acme", guard=guard) == 0
        assert guard.try_acquire("acme") is True  # saturate the only slot
        assert await apply_chaos_delay(20, tenant="acme", guard=guard) == 0
        guard.release("acme")

    asyncio.run(_run())
