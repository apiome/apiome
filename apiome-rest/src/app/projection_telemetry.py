"""Privacy-safe projection telemetry — EFP-3.2 (#4817).

Counters and structured log lines for the export-projection surface. Telemetry
carries **counts and reason categories only** — never construct labels, native
ids, source locations, artifact names, or free-text explanations.

Kinds tracked:

* ``preview_failure`` — preview/verify/evidence could not compute (reason category)
* ``stale_acknowledgement`` — generate rejected a mismatched acknowledged snapshot
* ``evidence_page`` — a bounded evidence page was served
* ``aggregation_used`` — the UI collapsed clean outcomes for a large view
* ``documentation_link_available`` / ``documentation_link_missing`` — doc URL counts
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Dict, Mapping, Optional

from .logging_config import get_logger

_log = get_logger("app.projection_telemetry")

#: Whitelist of metric kinds the REST surface (and UI proxy) may record.
ALLOWED_METRIC_KINDS = frozenset(
    {
        "preview_failure",
        "stale_acknowledgement",
        "evidence_page",
        "aggregation_used",
        "documentation_link_available",
        "documentation_link_missing",
    }
)

#: Controlled failure categories (no free-form caller text).
ALLOWED_REASON_CATEGORIES = frozenset(
    {
        "source_load",
        "unsupported_target",
        "unsupported_options",
        "malformed_cursor",
        "unknown",
    }
)


class ProjectionTelemetry:
    """Thread-safe in-process counters + structured log emitter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: Dict[str, int] = defaultdict(int)

    def reset(self) -> None:
        """Clear all counters (unit tests)."""
        with self._lock:
            self._counts.clear()

    def snapshot(self) -> Dict[str, int]:
        """Return a copy of every counter key → count."""
        with self._lock:
            return dict(self._counts)

    def record(
        self,
        kind: str,
        *,
        reason_category: Optional[str] = None,
        page_total: Optional[int] = None,
        latency_ms: Optional[float] = None,
        status_counts: Optional[Mapping[str, int]] = None,
        reason_counts: Optional[Mapping[str, int]] = None,
        large_manifest: Optional[bool] = None,
        n: int = 1,
    ) -> None:
        """Increment counters and emit one privacy-safe structlog event.

        Args:
            kind: A member of :data:`ALLOWED_METRIC_KINDS`.
            reason_category: Optional member of :data:`ALLOWED_REASON_CATEGORIES`
                (ignored when not allowed — never logged as free text).
            page_total: Bounded page/evidence total (integer count only).
            latency_ms: Wall-clock latency for the operation, when timed.
            status_counts: Projection status → count mapping (ints only).
            reason_counts: Projection reason → count mapping (ints only).
            large_manifest: True when the page total exceeds the UI aggregation
                threshold (mirrored constant on the REST side).
            n: How many times to increment the kind counter (doc-link batches).

        Raises:
            ValueError: When ``kind`` is not in the whitelist.
        """
        if kind not in ALLOWED_METRIC_KINDS:
            raise ValueError(f"unsupported projection metric kind: {kind!r}")
        if n < 1:
            return

        safe_reason: Optional[str] = None
        if reason_category is not None and reason_category in ALLOWED_REASON_CATEGORIES:
            safe_reason = reason_category

        safe_status = _int_count_map(status_counts)
        safe_reasons = _int_count_map(reason_counts)

        with self._lock:
            self._counts[kind] += n
            if safe_reason is not None:
                self._counts[f"{kind}:{safe_reason}"] += n

        payload: Dict[str, Any] = {
            "kind": kind,
            "n": n,
        }
        if safe_reason is not None:
            payload["reason_category"] = safe_reason
        if page_total is not None:
            payload["page_total"] = int(page_total)
        if latency_ms is not None:
            payload["latency_ms"] = round(float(latency_ms), 3)
        if safe_status:
            payload["status_counts"] = safe_status
        if safe_reasons:
            payload["reason_counts"] = safe_reasons
        if large_manifest is not None:
            payload["large_manifest"] = bool(large_manifest)

        # Structured event name is the positional message; fields ride as kwargs.
        _log.info("export.projection", **payload)


def _int_count_map(raw: Optional[Mapping[str, int]]) -> Dict[str, int]:
    """Copy a mapping keeping only string keys → non-negative int values."""
    if not raw:
        return {}
    out: Dict[str, int] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count >= 0:
            out[key] = count
    return out


#: Process-wide telemetry registry for the projection surface.
projection_telemetry = ProjectionTelemetry()
