"""Exponential backoff for the MCP re-discovery sweep's failure handling (MCAT-5.3, #3675).

A flaky or dead MCP endpoint must not be retried every sweep tick — that would spam the
server (and our logs) and let one bad endpoint starve healthy ones of sweep slots. After a
failed discovery the sweep defers the endpoint's next attempt by a delay that grows
exponentially with the number of consecutive failures, capped at a ceiling so the endpoint is
still re-checked periodically (and can recover) rather than being abandoned.

This module is the single, dependency-free home for that delay calculation so both the
persistence layer (:meth:`app.database.Database.record_mcp_discovery_failure`, which stamps the
``next_discovery_after`` anchor) and any caller that wants to *report* the delay compute it the
same way. Keeping it import-free avoids a cycle with :mod:`app.database` /
:mod:`app.mcp_discovery_engine`.
"""

from __future__ import annotations


def compute_backoff_seconds(
    consecutive_failures: int,
    *,
    base_seconds: float,
    max_seconds: float,
    retry_after_seconds: float | None = None,
) -> float:
    """Compute how long to defer the next discovery after ``consecutive_failures`` failures.

    The delay is exponential in the failure count and clamped to ``max_seconds``:
    ``base_seconds * 2 ** (consecutive_failures - 1)``, so the first failure waits
    ``base_seconds``, the second ``2 * base_seconds``, the third ``4 * base_seconds``, … up to
    the ceiling. A ``consecutive_failures`` of 0 or less yields ``base_seconds`` (a single
    base delay) rather than zero, so a failure always defers the endpoint by at least the base.

    Rate-limit pacing (MCAT-5.3): when the server asked us to slow down via a ``Retry-After``
    (passed as ``retry_after_seconds``), the result is the *larger* of the computed exponential
    delay and that hint, so we never retry sooner than the server permits. The exponential
    component is clamped to ``max_seconds`` first; the ``Retry-After`` floor is then applied
    *after* the ceiling and can exceed it, because honouring an explicit server pacing request
    takes precedence over our own cap.

    Args:
        consecutive_failures: Number of back-to-back failed attempts *including* the one just
            recorded (i.e. 1 on the first failure).
        base_seconds: The first-failure delay and the exponential's unit; clamped up to 1.0.
        max_seconds: Upper bound on the returned delay; clamped to be at least ``base_seconds``.
        retry_after_seconds: Optional server-supplied minimum delay (from a 429 ``Retry-After``);
            ``None`` when absent. A negative value is ignored.

    Returns:
        The backoff delay in seconds. The exponential component is bounded to
        ``base_seconds <= delay <= max_seconds``; a positive ``retry_after_seconds`` is then
        applied as a floor and may push the result above ``max_seconds``.
    """
    base = max(1.0, float(base_seconds))
    ceiling = max(base, float(max_seconds))

    # Exponential growth, but cap the exponent first so a large failure count cannot overflow
    # float math before the min() clamp brings it back to the ceiling.
    steps = max(0, int(consecutive_failures) - 1)
    capped_steps = min(steps, 60)  # 2**60 already dwarfs any realistic ceiling.
    delay = min(base * (2.0 ** capped_steps), ceiling)

    if retry_after_seconds is not None and retry_after_seconds > 0:
        # Honour the server's pacing request even when it exceeds our own ceiling.
        delay = max(delay, float(retry_after_seconds))

    return delay
