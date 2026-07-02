"""Tests for MCP re-discovery failure handling: backoff math, rate-limit parsing, classification.

V2-MCP-19.3 / MCAT-5.3 (#3675). DB-free; three layers:

* **Backoff math** — ``compute_backoff_seconds`` grows exponentially with the failure count,
  clamps to the ceiling, floors a single failure at the base, and honours a 429 ``Retry-After``
  even above the ceiling.
* **Retry-After parsing** — ``parse_retry_after_seconds`` accepts only the non-negative
  delta-seconds form and rejects HTTP-date / negative / malformed values.
* **Classification** — a 429 ``McpRateLimitedError`` classifies to ``RATE_LIMITED`` carrying the
  parsed ``retry_after`` in its detail, ahead of the generic HTTP-status bucket.
"""

from app.mcp_client.errors import DiscoveryErrorCode, classify_exception
from app.mcp_client.transport_http import (
    McpHttpStatusError,
    McpRateLimitedError,
    parse_retry_after_seconds,
)
from app.mcp_discovery_backoff import compute_backoff_seconds

_BASE = 60.0
_MAX = 21600.0


# ===========================================================================
# Exponential backoff
# ===========================================================================


def test_backoff_grows_exponentially_with_failure_count():
    # Nth failure waits base * 2**(N-1): 60, 120, 240, 480, ...
    assert compute_backoff_seconds(1, base_seconds=_BASE, max_seconds=_MAX) == 60.0
    assert compute_backoff_seconds(2, base_seconds=_BASE, max_seconds=_MAX) == 120.0
    assert compute_backoff_seconds(3, base_seconds=_BASE, max_seconds=_MAX) == 240.0
    assert compute_backoff_seconds(4, base_seconds=_BASE, max_seconds=_MAX) == 480.0


def test_backoff_first_failure_and_zero_count_floor_at_base():
    # A 0 / negative count still defers by a single base delay rather than zero.
    assert compute_backoff_seconds(0, base_seconds=_BASE, max_seconds=_MAX) == _BASE
    assert compute_backoff_seconds(-5, base_seconds=_BASE, max_seconds=_MAX) == _BASE


def test_backoff_clamps_to_ceiling():
    # A long failure streak is capped so the endpoint is still re-checked periodically.
    big = compute_backoff_seconds(40, base_seconds=_BASE, max_seconds=_MAX)
    assert big == _MAX


def test_backoff_huge_count_does_not_overflow():
    # The exponent is capped before the math so a pathological count cannot raise/overflow.
    assert compute_backoff_seconds(10_000, base_seconds=_BASE, max_seconds=_MAX) == _MAX


def test_backoff_base_floored_to_one_second():
    # A non-positive base is clamped up so the delay is never zero/negative.
    assert compute_backoff_seconds(1, base_seconds=0, max_seconds=_MAX) == 1.0


def test_backoff_max_at_least_base():
    # A max below the base is raised to the base so the ceiling never inverts the floor.
    assert compute_backoff_seconds(1, base_seconds=100, max_seconds=10) == 100.0


# ===========================================================================
# Rate-limit pacing
# ===========================================================================


def test_retry_after_floor_lengthens_a_short_backoff():
    # First failure would wait 60s, but the server asked for 300s — honour the longer one.
    delay = compute_backoff_seconds(
        1, base_seconds=_BASE, max_seconds=_MAX, retry_after_seconds=300
    )
    assert delay == 300.0


def test_retry_after_ignored_when_backoff_is_already_longer():
    # Computed exponential (480s) exceeds the server hint (100s); keep the longer computed delay.
    delay = compute_backoff_seconds(
        4, base_seconds=_BASE, max_seconds=_MAX, retry_after_seconds=100
    )
    assert delay == 480.0


def test_retry_after_can_exceed_ceiling():
    # An explicit server pacing request wins even over our own max ceiling.
    delay = compute_backoff_seconds(
        1, base_seconds=_BASE, max_seconds=_MAX, retry_after_seconds=_MAX + 1000
    )
    assert delay == _MAX + 1000


def test_negative_retry_after_ignored():
    delay = compute_backoff_seconds(
        1, base_seconds=_BASE, max_seconds=_MAX, retry_after_seconds=-10
    )
    assert delay == _BASE


# ===========================================================================
# Retry-After header parsing
# ===========================================================================


def test_parse_retry_after_accepts_delta_seconds():
    assert parse_retry_after_seconds("120") == 120
    assert parse_retry_after_seconds("0") == 0
    assert parse_retry_after_seconds("  42 ") == 42


def test_parse_retry_after_rejects_http_date_and_garbage():
    assert parse_retry_after_seconds("Wed, 21 Oct 2026 07:28:00 GMT") is None
    assert parse_retry_after_seconds("soon") is None
    assert parse_retry_after_seconds("-5") is None
    assert parse_retry_after_seconds("12.5") is None
    assert parse_retry_after_seconds("") is None
    assert parse_retry_after_seconds(None) is None


# ===========================================================================
# 429 classification
# ===========================================================================


def test_rate_limited_classifies_with_retry_after():
    err = classify_exception(McpRateLimitedError(retry_after=90))
    assert err.code is DiscoveryErrorCode.RATE_LIMITED
    assert err.detail["status"] == 429
    assert err.detail["retry_after"] == 90


def test_rate_limited_without_retry_after():
    err = classify_exception(McpRateLimitedError())
    assert err.code is DiscoveryErrorCode.RATE_LIMITED
    assert err.detail["retry_after"] is None


def test_rate_limited_is_distinct_from_generic_http_status():
    # A 429 is RATE_LIMITED; any other failing status stays in the generic bucket.
    assert classify_exception(McpRateLimitedError()).code is DiscoveryErrorCode.RATE_LIMITED
    assert classify_exception(McpHttpStatusError(503)).code is DiscoveryErrorCode.HTTP_STATUS
