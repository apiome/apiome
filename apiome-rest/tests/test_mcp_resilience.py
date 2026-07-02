"""Unit tests for the MCP discovery resilience primitives (V2-MCP-16.6, #3662).

Covers the two dependency-free building blocks in
:mod:`app.mcp_client.resilience`:

* :class:`TimeBudget` — driven by an injected deterministic clock (no sleeping)
  so every branch (unbounded, remaining, spent, clamped per-call timeout) is
  exercised exactly.
* :func:`private_address_reason` — the SSRF-guard predicate, across loopback,
  RFC 1918 private, link-local, reserved, multicast, unspecified, IPv6
  unique-local, IPv4-mapped IPv6, public literals, and plain hostnames.
"""

import pytest

from app.mcp_client.resilience import (
    DEFAULT_PER_CALL_TIMEOUT,
    BudgetExceededError,
    TimeBudget,
    private_address_reason,
)


class FakeClock:
    """A monotonic clock returning scripted timestamps; repeats the last value."""

    def __init__(self, *times: float) -> None:
        self._times = list(times)
        self._index = 0

    def __call__(self) -> float:
        value = self._times[min(self._index, len(self._times) - 1)]
        self._index += 1
        return value


# ===========================================================================
# TimeBudget
# ===========================================================================


def test_budget_reports_elapsed_and_remaining():
    # init=0, then 4s elapsed against a 10s budget.
    budget = TimeBudget(10.0, clock=FakeClock(0.0, 4.0, 4.0))
    assert budget.bounded is True
    assert budget.total == 10.0
    assert budget.elapsed() == 4.0
    assert budget.remaining() == 6.0
    assert budget.expired() is False


def test_budget_check_raises_once_spent():
    budget = TimeBudget(5.0, clock=FakeClock(0.0, 9.0))
    with pytest.raises(BudgetExceededError) as exc:
        budget.check()
    assert exc.value.total == 5.0
    assert exc.value.elapsed == 9.0


def test_budget_remaining_never_negative():
    budget = TimeBudget(5.0, clock=FakeClock(0.0, 12.0))
    assert budget.remaining() == 0.0
    assert budget.expired() is True


@pytest.mark.parametrize("total", [None, 0, -1])
def test_unbounded_budget_never_trips(total):
    budget = TimeBudget(total, clock=FakeClock(0.0, 10_000.0))
    assert budget.bounded is False
    assert budget.total is None
    assert budget.remaining() == float("inf")
    budget.check()  # never raises
    assert budget.call_timeout(7.5) == 7.5  # per-call timeout passes through


def test_call_timeout_clamps_to_remaining():
    # 2s left against an 8s budget; a 30s per-call request is clamped to 2s.
    budget = TimeBudget(8.0, clock=FakeClock(0.0, 6.0, 6.0))
    assert budget.call_timeout(30.0) == 2.0


def test_call_timeout_keeps_smaller_per_call():
    budget = TimeBudget(100.0, clock=FakeClock(0.0, 1.0, 1.0))
    assert budget.call_timeout(5.0) == 5.0


def test_call_timeout_raises_when_spent():
    budget = TimeBudget(3.0, clock=FakeClock(0.0, 9.0))
    with pytest.raises(BudgetExceededError):
        budget.call_timeout(DEFAULT_PER_CALL_TIMEOUT)


# ===========================================================================
# private_address_reason (SSRF predicate)
# ===========================================================================


@pytest.mark.parametrize(
    "host, reason",
    [
        ("127.0.0.1", "loopback"),
        ("::1", "loopback"),
        ("10.1.2.3", "private"),
        ("172.16.0.1", "private"),
        ("192.168.0.1", "private"),
        ("fd00::1", "private"),  # IPv6 unique-local
        ("169.254.169.254", "link-local"),  # cloud metadata service
        ("fe80::1", "link-local"),
        ("0.0.0.0", "unspecified"),
        ("224.0.0.1", "multicast"),
        ("240.0.0.1", "reserved"),
        ("::ffff:10.0.0.1", "private"),  # IPv4-mapped IPv6 → judged by inner v4
    ],
)
def test_private_addresses_are_classified(host, reason):
    assert private_address_reason(host) == reason


@pytest.mark.parametrize("host", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_literals_are_not_flagged(host):
    assert private_address_reason(host) is None


@pytest.mark.parametrize("host", ["mcp.example.com", "localhost", "", "not-an-ip"])
def test_hostnames_are_not_classified_without_dns(host):
    # No DNS resolution happens here, so any non-literal host returns None.
    assert private_address_reason(host) is None
