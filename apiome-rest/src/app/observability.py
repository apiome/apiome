"""Request observability for apiome-rest (RC1-3.2, #3617).

Three concerns, one module:

1. **Request correlation + structured access logs.** :class:`ObservabilityMiddleware` assigns (or
   reuses) a ``request_id`` for every HTTP request, binds it — along with method/path — into
   structlog's contextvars so *all* log lines emitted while serving the request carry it, echoes it
   back in the response header, and logs one structured access line per request with the final
   status and wall-clock latency. This is what makes a failing request diagnosable from logs alone.

2. **In-process metrics.** :class:`MetricsRegistry` accumulates request counts (overall and by HTTP
   status class), an error count (5xx) and a bounded rolling window of latencies, so the ops
   dashboard can report request rate, error rate and latency percentiles without an external metrics
   backend. It is a single, thread-safe, per-process instance (this is "minimal ops visibility", not
   a Prometheus deployment — counters reset on restart and are per-replica).

3. **Consistent error envelope.** :func:`build_error_envelope` produces the additive error shape
   used by the app's exception handlers (see ``app.main``). It deliberately *preserves* FastAPI's
   ``detail`` field (existing clients and tests read it) while adding a uniform ``error`` object
   (``status``/``message``/``type``/``request_id``) and a top-level ``request_id`` so every error
   response — 4xx or 5xx — has the same diagnosable shape.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from .config import settings
from .logging_config import bind_contextvars, clear_contextvars, get_logger

# Max latency samples retained for percentile math. Bounded so a long-lived process cannot grow
# memory without limit; a few thousand samples is ample for p50/p95/p99 on a single replica.
_MAX_LATENCY_SAMPLES = 4096

_log = get_logger("app.access")


def new_request_id() -> str:
    """Mint a fresh, URL-safe request id."""
    return uuid.uuid4().hex


def _status_class(status_code: int) -> str:
    """Bucket a status code into its class label (``"2xx"``, ``"4xx"`` …) for coarse metrics."""
    return f"{status_code // 100}xx"


@dataclass
class MetricsSnapshot:
    """Immutable view of the registry at one instant (what the ops dashboard renders)."""

    uptime_seconds: float
    total_requests: int
    requests_by_status_class: Dict[str, int]
    error_count: int
    error_rate: float
    requests_per_second: float
    latency_ms: Dict[str, float]
    in_flight: int


@dataclass
class MetricsRegistry:
    """Thread-safe, in-process accumulator of request metrics.

    Counters are monotonic for the life of the process and reset on restart — this is intentionally
    a *minimal* ops surface (per-replica, no persistence), matching the ticket's "minimal ops
    visibility" scope rather than a full metrics pipeline.
    """

    _start_monotonic: float
    _lock: threading.Lock = field(default_factory=threading.Lock)
    total_requests: int = 0
    error_count: int = 0
    in_flight: int = 0
    _by_status_class: Dict[str, int] = field(default_factory=dict)
    _latencies_ms: Deque[float] = field(
        default_factory=lambda: deque(maxlen=_MAX_LATENCY_SAMPLES)
    )

    def request_started(self) -> None:
        """Record that a request entered the pipeline (increments the in-flight gauge)."""
        with self._lock:
            self.in_flight += 1

    def request_finished(self, *, status_code: int, latency_ms: float) -> None:
        """Record a completed request's status and latency, and decrement the in-flight gauge."""
        with self._lock:
            self.in_flight = max(0, self.in_flight - 1)
            self.total_requests += 1
            cls = _status_class(status_code)
            self._by_status_class[cls] = self._by_status_class.get(cls, 0) + 1
            if status_code >= 500:
                self.error_count += 1
            self._latencies_ms.append(latency_ms)

    def snapshot(self, *, now_monotonic: Optional[float] = None) -> MetricsSnapshot:
        """Capture a consistent snapshot for reporting (computes rates and latency percentiles)."""
        now = now_monotonic if now_monotonic is not None else time.monotonic()
        with self._lock:
            uptime = max(0.0, now - self._start_monotonic)
            total = self.total_requests
            errors = self.error_count
            by_class = dict(self._by_status_class)
            samples = sorted(self._latencies_ms)
            in_flight = self.in_flight

        return MetricsSnapshot(
            uptime_seconds=round(uptime, 3),
            total_requests=total,
            requests_by_status_class=by_class,
            error_count=errors,
            error_rate=round(errors / total, 6) if total else 0.0,
            requests_per_second=round(total / uptime, 4) if uptime > 0 else 0.0,
            latency_ms=_latency_percentiles(samples),
            in_flight=in_flight,
        )


def _latency_percentiles(sorted_samples: list[float]) -> Dict[str, float]:
    """Compute avg/p50/p95/p99/max from an already-sorted latency sample list."""
    if not sorted_samples:
        return {"count": 0, "avg": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}

    def _pct(p: float) -> float:
        # Nearest-rank percentile: index = ceil(p * N) - 1, clamped into range.
        idx = max(0, min(len(sorted_samples) - 1, int(round(p * len(sorted_samples) + 0.5)) - 1))
        return round(sorted_samples[idx], 3)

    return {
        "count": len(sorted_samples),
        "avg": round(sum(sorted_samples) / len(sorted_samples), 3),
        "p50": _pct(0.50),
        "p95": _pct(0.95),
        "p99": _pct(0.99),
        "max": round(sorted_samples[-1], 3),
    }


# Single process-wide registry. Imported by the ops routes to render the dashboard.
metrics = MetricsRegistry(_start_monotonic=time.monotonic())


def build_error_envelope(
    *,
    status_code: int,
    message: str,
    detail: Any,
    error_type: str,
    request_id: Optional[str],
) -> Dict[str, Any]:
    """Build the consistent REST error envelope (additive over FastAPI's ``detail``).

    Args:
        status_code: HTTP status code being returned.
        message: Human-readable summary safe to surface to the caller.
        detail: The original FastAPI ``detail`` payload, preserved verbatim for backward
            compatibility (string, list of validation errors, or structured dict).
        error_type: Stable machine label for the error category
            (``http_error`` / ``validation_error`` / ``internal_error``).
        request_id: Correlation id for the request, echoed so a caller can quote it in a bug report.

    Returns:
        A dict with ``detail`` (unchanged), an ``error`` object, and a top-level ``request_id``.
    """
    return {
        "detail": detail,
        "error": {
            "status": status_code,
            "message": message,
            "type": error_type,
            "request_id": request_id,
        },
        "request_id": request_id,
    }


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Assign a request id, bind log context, time the request, and record metrics.

    Placed as the outermost middleware so it observes every response (including those produced by
    inner middleware such as the rate limiter and CORS) and so the ``request_id`` is bound before any
    handler — or any other middleware — runs.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        header_name = settings.request_id_header
        # Reuse an upstream/proxy-provided id when present so a request can be traced across hops;
        # otherwise mint one. Trim to a sane length to bound log/header size from hostile input.
        incoming = (request.headers.get(header_name) or "").strip()
        request_id = incoming[:128] if incoming else new_request_id()

        # Expose to downstream handlers (e.g. exception handlers) via request state.
        request.state.request_id = request_id

        clear_contextvars()
        bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        metrics.request_started()
        start = time.monotonic()
        status_code = 500  # Assume failure until proven otherwise (covers unhandled exceptions).
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[header_name] = request_id
            return response
        finally:
            latency_ms = (time.monotonic() - start) * 1000.0
            metrics.request_finished(status_code=status_code, latency_ms=latency_ms)
            # One structured access line per request. At INFO so it is on by default; demote noisy
            # liveness probes to DEBUG so health-check polling does not flood the log.
            event = "http_request"
            log = _log.bind(
                status_code=status_code,
                duration_ms=round(latency_ms, 3),
                client=request.client.host if request.client else None,
            )
            if request.url.path in _LOW_NOISE_PATHS:
                log.debug(event)
            elif status_code >= 500:
                log.error(event)
            elif status_code >= 400:
                log.warning(event)
            else:
                log.info(event)
            clear_contextvars()


# Liveness/readiness probes are polled frequently; log them at DEBUG to keep the access log signal
# high. They are still counted in metrics.
_LOW_NOISE_PATHS = frozenset({"/health", "/livez", "/readyz"})
