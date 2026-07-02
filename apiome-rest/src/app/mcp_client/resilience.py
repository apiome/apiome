"""Resilience primitives for MCP discovery (V2-MCP-16.6, #3662).

Two dependency-free building blocks the rest of the discovery client layers on
to stay trustworthy and diagnosable when reaching out to untrusted, remote MCP
servers:

* :class:`TimeBudget` — a monotonic wall-clock budget. Remote discovery walks an
  arbitrary number of paginated endpoints; a single per-call timeout (the
  transport's ``timeout``) bounds one request but not the *job*. A ``TimeBudget``
  bounds the whole run: the pagination loop calls :meth:`TimeBudget.check`
  between pages so a slow-drip server (each page just under the per-call timeout)
  cannot keep a job running indefinitely. It also derives a per-call timeout that
  never exceeds the time left (:meth:`TimeBudget.call_timeout`).
* :func:`private_address_reason` — classifies an IP literal as belonging to a
  non-globally-routable range (loopback, RFC 1918 private, link-local, reserved,
  multicast, unspecified). This is the core predicate behind the transport's SSRF
  guard, which refuses to let a tenant-supplied endpoint URL point the discovery
  worker at internal infrastructure. See the MCP
  `security best practices <https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices>`_.

This module imports nothing from the rest of the package so both the transport
(:mod:`app.mcp_client.transport_http`) and the error taxonomy
(:mod:`app.mcp_client.errors`) can depend on it without an import cycle.
"""

from __future__ import annotations

import time
from ipaddress import ip_address
from typing import Callable, Optional

# Default per-request timeout (seconds) for a single JSON-RPC call. Mirrors the
# transport's own default so callers that pair the two stay consistent.
DEFAULT_PER_CALL_TIMEOUT = 30.0

# Default total wall-clock budget (seconds) for one discovery job across every
# endpoint and page. Generous enough for a large, slow surface yet bounded.
DEFAULT_TOTAL_BUDGET = 120.0


# ===========================================================================
# Time budget
# ===========================================================================


class BudgetExceededError(Exception):
    """The discovery job ran past its total wall-clock budget.

    Raised by :meth:`TimeBudget.check` / :meth:`TimeBudget.call_timeout` once the
    elapsed time reaches the configured total. Carries the timing so the failure
    can be reported precisely (it maps to a stable
    :class:`~app.mcp_client.errors.DiscoveryErrorCode` for the job record).

    Attributes:
        elapsed: Seconds elapsed when the budget was found exhausted.
        total: The total budget in seconds that was exceeded.
    """

    def __init__(self, elapsed: float, total: float) -> None:
        self.elapsed = elapsed
        self.total = total
        super().__init__(
            f"discovery time budget of {total:.3f}s exhausted after {elapsed:.3f}s"
        )


class TimeBudget:
    """A monotonic wall-clock budget for a single discovery job.

    The clock starts when the budget is constructed. Long-running loops call
    :meth:`check` between units of work to fail fast once the budget is spent, and
    :meth:`call_timeout` to size the next per-call timeout so no single request
    can outlast the remaining budget.

    The clock function is injectable purely so tests can advance time
    deterministically without sleeping; production uses :func:`time.monotonic`.

    Args:
        total_seconds: The total budget. ``None`` or a non-positive value means
            *unbounded* — :meth:`check` never raises and :meth:`remaining` is
            infinite (useful for local/manual runs).
        clock: A zero-argument callable returning a monotonically increasing
            seconds value; defaults to :func:`time.monotonic`.
    """

    def __init__(
        self,
        total_seconds: Optional[float] = DEFAULT_TOTAL_BUDGET,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._start = clock()
        # A None/<=0 total disables the budget (treated as unbounded).
        self._total: Optional[float] = total_seconds if total_seconds and total_seconds > 0 else None

    @property
    def total(self) -> Optional[float]:
        """The total budget in seconds, or ``None`` when unbounded."""
        return self._total

    @property
    def bounded(self) -> bool:
        """True when a finite budget is in force (so :meth:`check` can raise)."""
        return self._total is not None

    def elapsed(self) -> float:
        """Seconds elapsed since the budget started."""
        return self._clock() - self._start

    def remaining(self) -> float:
        """Seconds left before the budget is exhausted.

        Returns ``float('inf')`` when unbounded and never returns a negative
        number (a spent budget reports ``0.0``).
        """
        if self._total is None:
            return float("inf")
        return max(0.0, self._total - self.elapsed())

    def expired(self) -> bool:
        """True when a bounded budget has no time left."""
        return self.bounded and self.remaining() <= 0.0

    def check(self) -> None:
        """Raise :class:`BudgetExceededError` if a bounded budget is spent.

        A no-op when unbounded or when time remains. Call this between units of
        work (e.g. before fetching each page) to abort promptly.
        """
        if self.bounded and self.remaining() <= 0.0:
            raise BudgetExceededError(self.elapsed(), self._total or 0.0)

    def call_timeout(self, per_call: float = DEFAULT_PER_CALL_TIMEOUT) -> float:
        """Return the timeout to use for the next call: ``min(per_call, remaining)``.

        First enforces the budget (raises :class:`BudgetExceededError` if already
        spent), then clamps ``per_call`` down to whatever time is left so a single
        request cannot run past the job's deadline. With an unbounded budget the
        unmodified ``per_call`` is returned.
        """
        self.check()
        remaining = self.remaining()
        return per_call if remaining == float("inf") else min(per_call, remaining)


# ===========================================================================
# SSRF address classification
# ===========================================================================

# Each predicate on an ``ip_address`` result, paired with the human/stable reason
# reported when it matches. Checked in order; the first match wins, so the more
# specific ranges precede the broad ``private`` bucket (which, on modern Python,
# also subsumes link-local/reserved — those are listed first to keep the reason
# precise).
_PRIVATE_RANGE_CHECKS = (
    ("is_loopback", "loopback"),
    ("is_link_local", "link-local"),
    ("is_multicast", "multicast"),
    ("is_unspecified", "unspecified"),
    ("is_reserved", "reserved"),
    ("is_private", "private"),
)


def private_address_reason(host: str) -> Optional[str]:
    """Classify ``host`` as a non-public IP range, or ``None`` if it is safe.

    When ``host`` is an IP literal in a non-globally-routable range, returns a
    short stable reason (e.g. ``"loopback"``, ``"private"``, ``"link-local"``,
    ``"reserved"``, ``"multicast"``, ``"unspecified"``). Returns ``None`` for a
    publicly routable IP literal.

    A non-literal hostname (anything that is not a valid IPv4/IPv6 address) also
    returns ``None`` here: this predicate deliberately does **no** DNS resolution,
    so callers that must guard against a hostname resolving into a private range
    resolve it first and pass each resulting IP literal through this function. An
    IPv4-mapped IPv6 literal (``::ffff:10.0.0.1``) is classified by its embedded
    IPv4 address so it cannot smuggle a private target past the check.

    Args:
        host: The URL host component (an IP literal, or a hostname which yields
            ``None``).

    Returns:
        A stable reason string when the literal is in a blocked range, else
        ``None``.
    """
    if not host:
        return None
    try:
        addr = ip_address(host)
    except ValueError:
        # Not an IP literal (a hostname): nothing to classify without DNS.
        return None

    # Unwrap IPv4-mapped IPv6 (``::ffff:a.b.c.d``) to its real IPv4 target.
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped

    for attribute, reason in _PRIVATE_RANGE_CHECKS:
        if getattr(addr, attribute, False):
            return reason
    return None
