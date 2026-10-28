"""Export job health for the gate opening — X8 (#6229).

Before Export studio is opened to everyone, operators need to see whether exports are working:
how many jobs succeed and fail, which targets fail, how long a job takes, and a signal when the
failure rate jumps. The counts already exist in :mod:`app.import_export_metrics` (IXH-6.6); this
module adds the two things they cannot answer, and the summary that reads both:

* a **whole-job duration histogram** for exports, with buckets up to the 30-minute job cap
  (``APIOME_EXPORT_JOB_TIMEOUT_SECONDS``) — the IXH-6.6 stage buckets stop at 60 s, so a job p95
  could not be read from them;
* a **rolling window** of recent terminal export jobs, and the **failure-rate alert** it drives.

Same posture as the rest of the metrics plane: in-process, per replica, reset on restart. No tag
here is per tenant, job or user — the window keeps only a timestamp and whether the job failed.

The alert is evaluated over the last ``APIOME_EXPORT_FAILURE_ALERT_WINDOW_SECONDS`` (default
900 s). It **fires** when that window holds at least ``APIOME_EXPORT_FAILURE_ALERT_MIN_JOBS``
(default 10) completed-or-failed jobs and at least ``APIOME_EXPORT_FAILURE_ALERT_RATE`` (default
0.2) of them failed. Canceled jobs are a user's choice, not a failure, so they count in neither.
Each change of state writes one ``export.failure_rate_alert`` log line (``warning`` when it fires,
``info`` when it clears), which a log pipeline can page on; ``/v1/ops/dashboard`` shows the state.
A rate of ``0`` or less turns the alert off.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Mapping, Optional, Tuple

from .import_export_metrics import KIND_EXPORT, OUTCOME_CANCELED, OUTCOME_COMPLETED, OUTCOME_FAILED
from .logging_config import get_logger

_log = get_logger("app.export_job_health")

__all__ = [
    "ALERT_FIRING",
    "ALERT_NO_DATA",
    "ALERT_OFF",
    "ALERT_OK",
    "JOB_DURATION_BUCKET_UPPER_MS",
    "MAX_WINDOW_JOBS",
    "ExportJobHealth",
    "export_job_health",
]

#: Whole-job duration bucket upper bounds in milliseconds (inclusive); an ``inf`` bucket follows.
#: The last bound is the default job cap (30 min), so only a job past the cap lands in ``inf``.
JOB_DURATION_BUCKET_UPPER_MS = (1000, 2500, 5000, 10000, 30000, 60000, 120000, 300000, 600000, 1800000)

#: Most terminal jobs the rolling window keeps, so a burst cannot grow it without bound.
MAX_WINDOW_JOBS = 10_000

#: Alert states, as ``/v1/ops/*`` reports them.
ALERT_OK = "ok"
ALERT_FIRING = "firing"
ALERT_NO_DATA = "no-data"
ALERT_OFF = "off"

#: Defaults used when settings cannot be read (a stripped-down test environment).
_DEFAULT_RATE = 0.2
_DEFAULT_MIN_JOBS = 10
_DEFAULT_WINDOW_SECONDS = 900


def _empty_buckets() -> Dict[str, int]:
    """A fresh duration histogram, every bucket at zero."""
    return {str(upper): 0 for upper in JOB_DURATION_BUCKET_UPPER_MS} | {"inf": 0}


def _bucket_label(duration_ms: float) -> str:
    """The bucket a duration falls into (upper-bound inclusive)."""
    for upper in JOB_DURATION_BUCKET_UPPER_MS:
        if duration_ms <= upper:
            return str(upper)
    return "inf"


def _percentile_upper_bound(buckets: Mapping[str, int], fraction: float) -> Tuple[Optional[int], bool]:
    """The bucket bound below which ``fraction`` of the observations fall.

    Args:
        buckets: Counts by bucket label, as built by :func:`_empty_buckets`.
        fraction: The percentile as a fraction, e.g. ``0.95``.

    Returns:
        ``(upper_ms, over_last_bucket)``: the bound in milliseconds, or ``None`` with no
        observations; ``over_last_bucket`` is ``True`` when the percentile lies in ``inf``
        (``upper_ms`` is then the largest bound, and the true value is above it).
    """
    total = sum(buckets.values())
    if total == 0:
        return None, False
    # The smallest bucket whose cumulative count reaches ceil(fraction × total); the epsilon keeps
    # float noise (0.95 × 20 = 19.000000000000004) from asking for one observation too many.
    needed = max(1, math.ceil(fraction * total - 1e-9))
    running = 0
    for upper in JOB_DURATION_BUCKET_UPPER_MS:
        running += buckets.get(str(upper), 0)
        if running >= needed:
            return upper, False
    return JOB_DURATION_BUCKET_UPPER_MS[-1], True


def _rate(part: int, whole: int) -> Optional[float]:
    """``part / whole`` rounded to four places, or ``None`` when ``whole`` is zero."""
    return round(part / whole, 4) if whole else None


def _alert_settings() -> Tuple[float, int, int]:
    """Read the alert threshold, minimum job count and window from settings.

    Returns:
        ``(rate, min_jobs, window_seconds)``; the module defaults when settings are unavailable.
    """
    try:
        from .config import settings

        return (
            float(settings.export_failure_alert_rate),
            int(settings.export_failure_alert_min_jobs),
            int(settings.export_failure_alert_window_seconds),
        )
    except Exception:  # noqa: BLE001 - the dashboard must render even without settings
        return _DEFAULT_RATE, _DEFAULT_MIN_JOBS, _DEFAULT_WINDOW_SECONDS


class ExportJobHealth:
    """Thread-safe export job duration histogram, failure window and alert state.

    Args:
        rate: Failure-rate threshold (0–1); ``None`` reads ``APIOME_EXPORT_FAILURE_ALERT_RATE``.
        min_jobs: Fewest jobs in the window before the alert may fire; ``None`` reads settings.
        window_seconds: Length of the rolling window; ``None`` reads settings.
        clock: Monotonic clock in seconds (tests pass a fake one).
    """

    def __init__(
        self,
        *,
        rate: Optional[float] = None,
        min_jobs: Optional[int] = None,
        window_seconds: Optional[int] = None,
        clock: Any = time.monotonic,
    ) -> None:
        self._lock = threading.Lock()
        self._overrides = (rate, min_jobs, window_seconds)
        self._clock = clock
        self._buckets: Dict[str, int] = _empty_buckets()
        # (monotonic seconds, failed?) for each completed-or-failed job, oldest first.
        self._window: Deque[Tuple[float, bool]] = deque(maxlen=MAX_WINDOW_JOBS)
        self._firing = False

    def _settings(self) -> Tuple[float, int, int]:
        """The effective ``(rate, min_jobs, window_seconds)``: overrides, else settings."""
        rate, min_jobs, window = _alert_settings()
        o_rate, o_min, o_window = self._overrides
        return (
            rate if o_rate is None else float(o_rate),
            min_jobs if o_min is None else int(o_min),
            window if o_window is None else int(o_window),
        )

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def observe(self, *, outcome: str, duration_ms: Optional[float]) -> None:
        """Record one terminal export job and re-evaluate the alert.

        Args:
            outcome: ``completed``, ``failed`` or ``canceled``. Anything else counts as failed,
                the same way the export engine maps an unknown terminal state.
            duration_ms: Whole-job wall-clock time; ``None`` when the job never started.
        """
        if outcome == OUTCOME_CANCELED:
            return
        failed = outcome != OUTCOME_COMPLETED
        now = self._clock()
        with self._lock:
            if duration_ms is not None:
                self._buckets[_bucket_label(max(0.0, float(duration_ms)))] += 1
            self._window.append((now, failed))
        self._evaluate(now)

    def _window_counts(self, now: float, window_seconds: int) -> Tuple[int, int]:
        """Drop jobs older than the window, then count what is left.

        Args:
            now: The current monotonic time.
            window_seconds: The window length.

        Returns:
            ``(jobs, failed)`` inside the window.
        """
        with self._lock:
            while self._window and now - self._window[0][0] > window_seconds:
                self._window.popleft()
            jobs = len(self._window)
            failed = sum(1 for _, was_failed in self._window if was_failed)
        return jobs, failed

    def _alert(self, now: float) -> Dict[str, Any]:
        """The alert block: state, window counts and the thresholds behind them."""
        rate, min_jobs, window_seconds = self._settings()
        jobs, failed = self._window_counts(now, window_seconds)
        failure_rate = _rate(failed, jobs)
        if rate <= 0:
            state = ALERT_OFF
        elif jobs < max(1, min_jobs):
            state = ALERT_NO_DATA
        elif failure_rate is not None and failure_rate >= rate:
            state = ALERT_FIRING
        else:
            state = ALERT_OK
        return {
            "state": state,
            "window_seconds": window_seconds,
            "window_jobs": jobs,
            "window_failed": failed,
            "window_failure_rate": failure_rate,
            "threshold_rate": rate,
            "min_jobs": min_jobs,
        }

    def _evaluate(self, now: float) -> Dict[str, Any]:
        """Compute the alert and log one line when it starts or stops firing."""
        alert = self._alert(now)
        firing = alert["state"] == ALERT_FIRING
        with self._lock:
            changed = firing != self._firing
            self._firing = firing
        if changed:
            fields = {key: value for key, value in alert.items() if key != "state"}
            if firing:
                _log.warning("export.failure_rate_alert", state=ALERT_FIRING, **fields)
            else:
                _log.info("export.failure_rate_alert", state=alert["state"], **fields)
        return alert

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def summary(self, import_export_snapshot: Mapping[str, Any]) -> Dict[str, Any]:
        """The export health view the ops endpoints and the dashboard read.

        Args:
            import_export_snapshot: :meth:`app.import_export_metrics.ImportExportMetrics.snapshot`,
                passed in so one call site can reuse a snapshot it already took.

        Returns:
            ``{totals, success_rate, failure_rate, job_duration_ms, per_target, alert}``:

            * ``totals`` — terminal export jobs by outcome since the replica started;
            * ``success_rate`` / ``failure_rate`` — over completed + failed (``None`` with none);
            * ``job_duration_ms`` — ``{count, buckets, p50_upper_ms, p95_upper_ms,
              p95_over_last_bucket}``;
            * ``per_target`` — one entry per target with any job, most failures first, with its
              counts, failure rate and failure codes;
            * ``alert`` — the failure-rate alert (see the module docstring).
        """
        jobs = (import_export_snapshot.get("jobs") or {}).get(KIND_EXPORT) or {}
        failures = (import_export_snapshot.get("failures") or {}).get(KIND_EXPORT) or {}

        totals = {OUTCOME_COMPLETED: 0, OUTCOME_FAILED: 0, OUTCOME_CANCELED: 0}
        per_target: Dict[str, Dict[str, Any]] = {}
        for target, by_format in jobs.items():
            entry = per_target.setdefault(
                target, {"target": target, **{outcome: 0 for outcome in totals}, "failure_codes": {}}
            )
            for by_outcome in by_format.values():
                for outcome, cell in by_outcome.items():
                    count = int(cell.get("count", 0))
                    if outcome in totals:
                        totals[outcome] += count
                        entry[outcome] += count
        for code, by_target in failures.items():
            for target, count in by_target.items():
                entry = per_target.setdefault(
                    target, {"target": target, **{outcome: 0 for outcome in totals}, "failure_codes": {}}
                )
                entry["failure_codes"][code] = entry["failure_codes"].get(code, 0) + int(count)

        targets: List[Dict[str, Any]] = []
        for entry in per_target.values():
            decided = entry[OUTCOME_COMPLETED] + entry[OUTCOME_FAILED]
            entry["failure_rate"] = _rate(entry[OUTCOME_FAILED], decided)
            entry["failure_codes"] = [
                {"code": code, "count": count}
                for code, count in sorted(entry["failure_codes"].items(), key=lambda item: (-item[1], item[0]))
            ]
            targets.append(entry)
        targets.sort(key=lambda entry: (-entry[OUTCOME_FAILED], entry["target"]))

        decided = totals[OUTCOME_COMPLETED] + totals[OUTCOME_FAILED]
        with self._lock:
            buckets = dict(self._buckets)
        p50, _ = _percentile_upper_bound(buckets, 0.5)
        p95, p95_over = _percentile_upper_bound(buckets, 0.95)
        return {
            "totals": totals,
            "success_rate": _rate(totals[OUTCOME_COMPLETED], decided),
            "failure_rate": _rate(totals[OUTCOME_FAILED], decided),
            "job_duration_ms": {
                "count": sum(buckets.values()),
                "buckets": buckets,
                "p50_upper_ms": p50,
                "p95_upper_ms": p95,
                "p95_over_last_bucket": p95_over,
            },
            "per_target": targets,
            "alert": self._evaluate(self._clock()),
        }

    def reset(self) -> None:
        """Clear the histogram, the window and the alert state (unit tests)."""
        with self._lock:
            self._buckets = _empty_buckets()
            self._window.clear()
            self._firing = False


#: Process-wide export job health, fed by the export engine's terminal-job seam.
export_job_health = ExportJobHealth()
