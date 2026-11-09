"""Periodic MCP endpoint reachability / latency probe (V2-MCP-27.3 / MCAT-13.3, #3713).

The discovery sweep (:mod:`app.mcp_discovery_sweep`) re-handshakes *and* re-lists an endpoint's whole
surface about once an hour — too heavy and too infrequent to tell whether a server is up. This sweep
is its lightweight counterpart: a background loop (wired in :mod:`app.main`) that, every tick, probes
the endpoints whose health cadence has elapsed with the MCP ``initialize`` handshake **only** — no
``*/list`` pagination, no surface diff, no version — and records one ``mcp_endpoint_health_checks``
row per probe: ``up`` or ``down``, the wall-clock latency, and for a failure the stable discovery
error code (:class:`app.mcp_client.errors.DiscoveryErrorCode`). :mod:`app.mcp_health` folds those
rows into the uptime summary and the health badge.

Design rules:

* **Cheap and bounded.** Each probe is capped by ``mcp_health_timeout_seconds``, at most
  ``mcp_health_max_concurrency`` run at once, and a tick probes at most ``mcp_health_max_per_tick``
  endpoints (least recently probed first, so a backlog drains fairly across ticks).
* **Never disruptive.** A probe failure is a ``down`` row, never an exception; one endpoint failing
  to record never stops the others; the probe never touches discovery state (failure counters,
  backoff, quarantine) so monitoring cannot change how discovery treats an endpoint.
* **Same safety guards as discovery.** The probe goes through
  :func:`app.mcp_client.connect.open_session`, so the SSRF guard, the plaintext-HTTP refusal and the
  legacy-SSE fallback all apply, and it sends the endpoint's stored credentials exactly as discovery
  does (:func:`app.mcp_credentials.load_endpoint_auth_headers`).
* **Kill switch.** ``mcp_health_enabled = False`` halts the sweep: nothing is selected or probed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .mcp_client import classify_exception, open_session
from .mcp_client.errors import DiscoveryErrorCode
from .mcp_credentials import load_endpoint_auth_headers
from .mcp_health import CHECK_DOWN, CHECK_UP

_logger = logging.getLogger(__name__)

#: How long probe rows are kept. At the default 5-minute cadence that is ~8,600 rows per endpoint;
#: older rows are pruned at the start of each tick.
HEALTH_CHECK_RETENTION_DAYS = 30


@dataclass(frozen=True)
class ProbeResult:
    """The outcome of one reachability probe.

    Attributes:
        status: ``up`` when the initialize handshake completed, else ``down``.
        latency_ms: Wall-clock milliseconds from starting the connect to the end of the handshake
            (or to the failure).
        error_code: The stable discovery error code for a ``down`` probe; ``None`` when ``up``.
    """

    status: str
    latency_ms: int
    error_code: Optional[str] = None


# Test seam: monkeypatch to an async callable(endpoint_row, headers, timeout_seconds) -> ProbeResult
# to bypass the network. When None, :func:`_probe_with_mcp_client` performs the live probe.
_probe_runner: Optional[
    Callable[[Dict[str, Any], Dict[str, str], float], Awaitable[ProbeResult]]
] = None


def _elapsed_ms(started: float) -> int:
    """Milliseconds since ``started`` (a :func:`time.perf_counter` reading), never negative."""
    return max(0, int(round((time.perf_counter() - started) * 1000)))


async def _probe_with_mcp_client(
    endpoint: Dict[str, Any], headers: Dict[str, str], timeout_seconds: float
) -> ProbeResult:
    """Run the ``initialize`` handshake against the endpoint and time it.

    Args:
        endpoint: The ``mcp_endpoints`` row (``endpoint_url`` and ``transport`` are used).
        headers: Auth headers to send (empty when the endpoint has no credentials).
        timeout_seconds: Wall-clock ceiling for the whole probe.

    Returns:
        ``up`` with the handshake latency, or ``down`` with the classified error code — a failure
        is a result, never an exception.
    """
    started = time.perf_counter()
    try:
        transport, _initialize = await asyncio.wait_for(
            open_session(
                str(endpoint["endpoint_url"]),
                transport=endpoint.get("transport"),
                headers=headers,
                timeout=timeout_seconds,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        return ProbeResult(CHECK_DOWN, _elapsed_ms(started), DiscoveryErrorCode.TIMEOUT.value)
    except Exception as exc:  # noqa: BLE001 - every failure is mapped to the stable taxonomy
        return ProbeResult(CHECK_DOWN, _elapsed_ms(started), classify_exception(exc).code.value)
    latency_ms = _elapsed_ms(started)
    try:
        await transport.aclose()
    except Exception:  # noqa: BLE001 - the server answered; a messy close does not make it down
        _logger.debug("health probe: closing the session for %s failed", endpoint.get("id"))
    return ProbeResult(CHECK_UP, latency_ms)


async def probe_endpoint(endpoint: Dict[str, Any], timeout_seconds: float) -> ProbeResult:
    """Probe one endpoint's reachability with its stored credentials.

    Args:
        endpoint: The ``mcp_endpoints`` row to probe.
        timeout_seconds: Wall-clock ceiling for the probe.

    Returns:
        The probe result. Never raises: an unexpected error (including in the credential read)
        becomes a ``down`` result with the ``unknown`` code.
    """
    started = time.perf_counter()
    try:
        headers = await asyncio.to_thread(load_endpoint_auth_headers, str(endpoint["id"]))
        if _probe_runner is not None:
            return await _probe_runner(endpoint, headers, timeout_seconds)
        return await _probe_with_mcp_client(endpoint, headers, timeout_seconds)
    except Exception:  # noqa: BLE001 - a probe must never fail the tick
        _logger.exception("health probe for endpoint %s raised", endpoint.get("id"))
        return ProbeResult(CHECK_DOWN, _elapsed_ms(started), DiscoveryErrorCode.UNKNOWN.value)


async def process_mcp_health_sweep(db: Any) -> int:
    """Run one health-sweep tick: probe every due endpoint, bounded, and record each result.

    Prunes probe rows older than :data:`HEALTH_CHECK_RETENTION_DAYS`, selects the due endpoints
    (:meth:`Database.list_due_mcp_health_endpoints`), probes them under the concurrency cap and the
    per-probe timeout, and records one row per probe. Blocking DB calls run in worker threads.

    Args:
        db: The database handle the tick reads and writes through (a dedicated connection).

    Returns:
        How many probes were recorded (0 when halted by the kill switch or nothing was due).
    """
    from .config import settings

    if not settings.mcp_health_enabled:
        return 0

    try:
        await asyncio.to_thread(
            db.prune_mcp_health_checks, retention_days=HEALTH_CHECK_RETENTION_DAYS
        )
    except Exception:  # noqa: BLE001 - pruning is housekeeping; never stop probing for it
        _logger.exception("health sweep: pruning old probes failed")

    due: List[Dict[str, Any]] = await asyncio.to_thread(
        db.list_due_mcp_health_endpoints,
        cadence_seconds=int(settings.mcp_health_cadence_seconds),
        limit=max(1, int(settings.mcp_health_max_per_tick)),
    )
    if not due:
        return 0

    semaphore = asyncio.Semaphore(max(1, int(settings.mcp_health_max_concurrency)))
    timeout_seconds = float(max(1, int(settings.mcp_health_timeout_seconds)))
    # Writes share one connection, so they are serialized; probes still overlap on the network.
    write_lock = asyncio.Lock()

    async def _probe_and_record(endpoint: Dict[str, Any]) -> bool:
        async with semaphore:
            result = await probe_endpoint(endpoint, timeout_seconds)
        try:
            async with write_lock:
                await asyncio.to_thread(
                    db.record_mcp_health_check,
                    str(endpoint["id"]),
                    status=result.status,
                    latency_ms=result.latency_ms,
                    error_code=result.error_code,
                )
        except Exception:  # noqa: BLE001 - one failed write never stops the others
            _logger.exception("health sweep: recording the probe of %s failed", endpoint.get("id"))
            return False
        return True

    recorded = await asyncio.gather(*(_probe_and_record(endpoint) for endpoint in due))
    count = sum(1 for ok in recorded if ok)
    _logger.info("mcp health sweep: probed=%d recorded=%d", len(due), count)
    return count
