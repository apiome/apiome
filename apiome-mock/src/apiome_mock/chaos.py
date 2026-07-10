"""Latency and chaos injection for the hosted mock (#4455, SIM-4.3).

Chaos knobs let clients rehearse against a slow or flaky API. They live in
the ``versions.mock_settings`` JSONB column under the ``"chaos"`` key::

    {
      "chaos": {
        "default": {"delayMs": 800, "jitterMs": 200, "errorRate": 10},
        "operations": {
          "GET /pets": {"delayMs": 2000, "jitterMs": 500, "errorRate": 50}
        }
      }
    }

Knobs:

* ``delayMs`` — base delay in milliseconds applied before responding.
* ``jitterMs`` — uniform jitter: the applied delay is drawn from
  ``[delayMs - jitterMs, delayMs + jitterMs]`` (never below zero).
* ``errorRate`` — percent probability (0-100) that the request returns an
  injected error instead of the normal resolved response.

Each knob resolves per request with field-level fallback: a knob set on the
operation entry wins (an explicit ``0`` switches it off for that route),
an unset knob falls back to ``default``, and an unset default means zero.
A scenario (#4454, SIM-4.2) may carry its own ``"chaos"`` block; when the
request selects that scenario the scenario's block replaces the
version-level one entirely, so chaos can be confined to (or disabled
within) a single scenario.

Safety: the applied delay is capped at :data:`MAX_CHAOS_DELAY_MS` and the
number of concurrently delayed requests per tenant is capped at
:data:`MAX_CONCURRENT_DELAYS_PER_TENANT` (excess requests skip the delay and
respond immediately) so chaos cannot be used to pin service workers. Chaos
responses flow through the normal SIM-1.5 pipeline: the rate-limit token is
consumed before the delay starts and the usage rollup records the injected
status code after it ends.

Parsing here is deliberately lenient (malformed entries are skipped) to
mirror ``apiome_mock.scenarios``; author-time validation happens in
apiome-rest when the settings are saved.
"""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass, field
from typing import Any, Mapping

MAX_CHAOS_DELAY_MS = 30_000
"""Hard cap (milliseconds) on any injected delay, jitter included."""

MAX_CONCURRENT_DELAYS_PER_TENANT = 64
"""Maximum requests a tenant may hold in an injected delay at once."""

CHAOS_HEADER = "X-Mock-Chaos"
"""Response header set to ``"error"`` on chaos-injected error responses."""

CHAOS_DELAY_HEADER = "X-Mock-Chaos-Delay-Ms"
"""Response header echoing the injected delay actually applied (ms)."""

_rng = random.Random()
"""Module RNG used when callers do not supply one (seedable in tests)."""


@dataclass(frozen=True)
class ChaosKnobSettings:
    """Chaos knobs as authored for one scope; ``None`` means "not set here".

    Keeping unset and explicit-zero distinct lets a per-operation entry
    zero out one knob while still inheriting the others from ``default``.
    """

    delay_ms: int | None = None
    jitter_ms: int | None = None
    error_rate: float | None = None


@dataclass(frozen=True)
class ChaosKnobs:
    """Fully resolved chaos settings for one request.

    Attributes:
        delay_ms: Base delay in milliseconds (>= 0).
        jitter_ms: Uniform jitter half-width in milliseconds (>= 0).
        error_rate: Percent probability (0-100) of injecting an error.
    """

    delay_ms: int = 0
    jitter_ms: int = 0
    error_rate: float = 0.0

    @property
    def is_zero(self) -> bool:
        """True when the knobs change nothing (no delay, no errors)."""
        return self.delay_ms <= 0 and self.jitter_ms <= 0 and self.error_rate <= 0


@dataclass(frozen=True)
class ChaosConfig:
    """Chaos knobs for a version (or one scenario): a default plus per-operation overrides."""

    default: ChaosKnobSettings = field(default_factory=ChaosKnobSettings)
    operations: Mapping[str, ChaosKnobSettings] = field(default_factory=dict)


EMPTY_CHAOS = ChaosConfig()
"""Shared no-op config used when ``mock_settings`` defines no chaos."""


def _parse_non_negative_ms(raw: Any) -> int | None:
    """Read a millisecond knob: non-negative int capped to the max, else ``None``."""
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    if raw < 0:
        return None
    return min(raw, MAX_CHAOS_DELAY_MS)


def _parse_error_rate(raw: Any) -> float | None:
    """Read an error-rate knob: number in [0, 100], else ``None``."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    return value if 0.0 <= value <= 100.0 else None


def _parse_knob_settings(raw: Any) -> ChaosKnobSettings | None:
    """Build one :class:`ChaosKnobSettings`; ``None`` when the entry is not a mapping.

    Individual malformed fields are treated as unset rather than
    invalidating the whole entry.
    """
    if not isinstance(raw, dict):
        return None
    return ChaosKnobSettings(
        delay_ms=_parse_non_negative_ms(raw.get("delayMs")),
        jitter_ms=_parse_non_negative_ms(raw.get("jitterMs")),
        error_rate=_parse_error_rate(raw.get("errorRate")),
    )


def parse_chaos_block(raw: Any) -> ChaosConfig | None:
    """Parse one ``"chaos"`` block (``{"default": ..., "operations": ...}``).

    Returns ``None`` when ``raw`` is not a mapping, so callers can tell "no
    chaos block" apart from "an empty chaos block" (a scenario uses the
    latter to switch chaos off).
    """
    # Imported here to avoid a module cycle: scenarios.py imports this module.
    from apiome_mock.scenarios import normalize_operation_key

    if not isinstance(raw, dict):
        return None
    default = _parse_knob_settings(raw.get("default")) or ChaosKnobSettings()
    operations: dict[str, ChaosKnobSettings] = {}
    operations_raw = raw.get("operations")
    if isinstance(operations_raw, dict):
        for op_key_raw, knobs_raw in operations_raw.items():
            op_key = normalize_operation_key(op_key_raw)
            knobs = _parse_knob_settings(knobs_raw)
            if op_key is not None and knobs is not None:
                operations[op_key] = knobs
    return ChaosConfig(default=default, operations=operations)


def parse_chaos(mock_settings: Any) -> ChaosConfig:
    """Parse the version-level ``mock_settings.chaos`` block.

    Accepts the raw JSONB value (dict, JSON text, or ``None``) and never
    raises; anything unusable yields :data:`EMPTY_CHAOS`.
    """
    settings: Any = mock_settings
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except json.JSONDecodeError:
            return EMPTY_CHAOS
    if not isinstance(settings, dict):
        return EMPTY_CHAOS
    return parse_chaos_block(settings.get("chaos")) or EMPTY_CHAOS


def effective_knobs(config: ChaosConfig, operation_key: str) -> ChaosKnobs:
    """Resolve the knobs for one operation with field-level fallback.

    Each knob falls back from the operation entry to ``default`` to zero, so
    a version can set a broad default and a route can override (or zero out)
    only the knob it cares about.
    """
    override = config.operations.get(operation_key) or ChaosKnobSettings()
    default = config.default

    def _resolve(op_value: float | None, default_value: float | None) -> float:
        if op_value is not None:
            return op_value
        if default_value is not None:
            return default_value
        return 0

    return ChaosKnobs(
        delay_ms=int(_resolve(override.delay_ms, default.delay_ms)),
        jitter_ms=int(_resolve(override.jitter_ms, default.jitter_ms)),
        error_rate=float(_resolve(override.error_rate, default.error_rate)),
    )


def compute_delay_ms(knobs: ChaosKnobs, rng: random.Random | None = None) -> int:
    """Draw the delay to apply: ``delay_ms`` ± uniform jitter, clamped to the cap.

    Returns ``0`` when the knobs configure no delay.
    """
    if knobs.delay_ms <= 0 and knobs.jitter_ms <= 0:
        return 0
    generator = rng or _rng
    delay = knobs.delay_ms
    if knobs.jitter_ms > 0:
        delay += generator.randint(-knobs.jitter_ms, knobs.jitter_ms)
    return max(0, min(delay, MAX_CHAOS_DELAY_MS))


def should_inject_error(knobs: ChaosKnobs, rng: random.Random | None = None) -> bool:
    """Roll the error-rate dice once for a request."""
    if knobs.error_rate <= 0:
        return False
    if knobs.error_rate >= 100:
        return True
    generator = rng or _rng
    return generator.uniform(0.0, 100.0) < knobs.error_rate


class ChaosDelayGuard:
    """Per-tenant cap on concurrently delayed requests.

    asyncio is single-threaded, so plain counter updates (no awaits between
    check and increment) are race-free without a lock.
    """

    def __init__(self, max_concurrent: int = MAX_CONCURRENT_DELAYS_PER_TENANT) -> None:
        self._max_concurrent = max_concurrent
        self._active: dict[str, int] = {}

    def try_acquire(self, tenant: str) -> bool:
        """Reserve a delay slot for ``tenant``; ``False`` when saturated."""
        count = self._active.get(tenant, 0)
        if count >= self._max_concurrent:
            return False
        self._active[tenant] = count + 1
        return True

    def release(self, tenant: str) -> None:
        """Return a slot taken by :meth:`try_acquire`."""
        count = self._active.get(tenant, 0)
        if count <= 1:
            self._active.pop(tenant, None)
        else:
            self._active[tenant] = count - 1


_delay_guard = ChaosDelayGuard()


async def apply_chaos_delay(delay_ms: int, *, tenant: str, guard: ChaosDelayGuard | None = None) -> int:
    """Sleep for ``delay_ms`` (capped), honoring the per-tenant concurrency guard.

    Returns the delay actually applied in milliseconds: ``0`` when no delay
    was configured or the tenant's delay slots are saturated.
    """
    if delay_ms <= 0:
        return 0
    active_guard = guard or _delay_guard
    if not active_guard.try_acquire(tenant):
        return 0
    applied = min(delay_ms, MAX_CHAOS_DELAY_MS)
    try:
        await asyncio.sleep(applied / 1000.0)
    finally:
        active_guard.release(tenant)
    return applied
