"""Staleness & freshness reporting for the MCP catalog (V2-MCP-36.2 / MCAT-22.2, #4665).

Pure classification over endpoint rows (plus optional discovery-job context): flags endpoints
that are overdue for re-discovery, in backoff/quarantine, or repeatedly failing, and surfaces a
``last_known_good_at`` anchor from the current snapshot (or the last completed discovery job).

Read paths join ``mcp_endpoints`` with ``mcp_endpoint_versions`` / ``mcp_discovery_jobs``; this
module only folds the rows the caller hands it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, List, Literal, Mapping, Optional, Sequence

from .models import (
    McpFreshnessEndpointOut,
    McpFreshnessReportResponse,
    mcp_endpoint_host,
    redact_url_credentials,
)

McpFreshnessStatus = Literal["fresh", "stale", "failing", "backoff", "quarantined"]

_FRESHNESS_REASONS: dict[McpFreshnessStatus, str] = {
    "fresh": "Discovery is current and the endpoint is healthy.",
    "stale": "Past the discovery cadence without a newer successful run.",
    "failing": "Recent discovery attempts are failing.",
    "backoff": "Discovery is deferred by the failure backoff window.",
    "quarantined": "Discovery is suspended after repeated failures.",
}

_FRESHNESS_PRECEDENCE: tuple[McpFreshnessStatus, ...] = (
    "quarantined",
    "backoff",
    "failing",
    "stale",
    "fresh",
)


def effective_discovery_cadence_seconds(
    endpoint_cadence: Any,
    *,
    default_cadence_seconds: int,
) -> int:
    """Resolve the per-endpoint cadence, falling back to the global default (MCAT-5.1)."""
    if isinstance(endpoint_cadence, int) and endpoint_cadence > 0:
        return endpoint_cadence
    cadence = int(default_cadence_seconds)
    return cadence if cadence > 0 else 1


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _isoformat(value: Any) -> Optional[str]:
    dt = _parse_dt(value)
    return dt.isoformat() if dt is not None else None


def is_past_discovery_cadence(
    last_discovered_at: Any,
    *,
    cadence_seconds: int,
    now: datetime,
) -> bool:
    """True when an enabled endpoint is overdue for its next discovery sweep tick."""
    last = _parse_dt(last_discovered_at)
    if last is None:
        return True
    return last + timedelta(seconds=max(1, int(cadence_seconds))) <= now


def derive_freshness_status(
    row: Mapping[str, Any],
    *,
    default_cadence_seconds: int,
    now: Optional[datetime] = None,
) -> McpFreshnessStatus:
    """Fold endpoint + job context into one freshness label for cards and the report.

    Precedence mirrors how operators act on problems: quarantine and backoff are the strongest
    holds, then repeated failures, then cadence staleness. Disabled endpoints are deliberately
    left ``fresh`` (unflagged) so the report stays focused on live catalog drift.
    """
    now = now or datetime.now(timezone.utc)

    if not bool(row.get("enabled", True)):
        return "fresh"

    if row.get("quarantined_at") is not None:
        return "quarantined"

    next_after = _parse_dt(row.get("next_discovery_after"))
    if next_after is not None and next_after > now:
        return "backoff"

    if int(row.get("consecutive_failures") or 0) > 0:
        return "failing"

    cadence = effective_discovery_cadence_seconds(
        row.get("discovery_cadence_seconds"),
        default_cadence_seconds=default_cadence_seconds,
    )
    if is_past_discovery_cadence(
        row.get("last_discovered_at"),
        cadence_seconds=cadence,
        now=now,
    ):
        return "stale"

    return "fresh"


def freshness_is_flagged(status: McpFreshnessStatus) -> bool:
    """Whether a freshness label should appear on cards / in the report."""
    return status != "fresh"


def freshness_reason(status: McpFreshnessStatus) -> str:
    """Human-readable explanation for a freshness label."""
    return _FRESHNESS_REASONS[status]


def mcp_freshness_endpoint_out_from_row(
    row: Mapping[str, Any],
    *,
    freshness: McpFreshnessStatus,
    reason: str,
    last_known_good_at: Optional[str],
) -> McpFreshnessEndpointOut:
    """Project a freshness-candidate row onto the wire model."""
    cadence = row.get("discovery_cadence_seconds")
    raw_url = str(row["endpoint_url"])
    return McpFreshnessEndpointOut(
        id=str(row["id"]),
        name=str(row["name"]),
        slug=str(row["slug"]),
        host=mcp_endpoint_host(raw_url),
        endpoint_url=redact_url_credentials(raw_url) or "",
        transport=str(row["transport"]),
        published=bool(row.get("published", False)),
        visibility=str(row["visibility"]),
        enabled=bool(row.get("enabled", True)),
        freshness=freshness,
        reason=reason,
        last_known_good_at=last_known_good_at,
        last_discovered_at=_isoformat(row.get("last_discovered_at")),
        last_discovery_status=(
            str(row["last_discovery_status"]) if row.get("last_discovery_status") is not None else None
        ),
        discovery_cadence_seconds=int(cadence) if isinstance(cadence, int) else None,
        consecutive_failures=int(row.get("consecutive_failures") or 0),
        next_discovery_after=_isoformat(row.get("next_discovery_after")),
        quarantined=row.get("quarantined_at") is not None,
        quarantine_reason=(
            str(row["quarantine_reason"]) if row.get("quarantine_reason") is not None else None
        ),
    )


def resolve_last_known_good_at(row: Mapping[str, Any]) -> Optional[str]:
    """Best-effort timestamp of the last successful discovery snapshot.

    Prefers the explicit ``last_known_good_at`` column when the query supplies it (typically the
    current version's ``discovered_at``). Falls back to ``last_discovered_at`` only when the latest
    outcome was successful (no active failure streak).
    """
    explicit = _isoformat(row.get("last_known_good_at"))
    if explicit is not None:
        return explicit

    if int(row.get("consecutive_failures") or 0) > 0:
        return None

    status = str(row.get("last_discovery_status") or "").strip().lower()
    if status in {"", "failed", "failure", "error"}:
        return None

    return _isoformat(row.get("last_discovered_at"))


def mcp_freshness_report_from_rows(
    *,
    default_cadence_seconds: int,
    candidates: Sequence[Mapping[str, Any]],
    now: Optional[datetime] = None,
) -> McpFreshnessReportResponse:
    """Build the tenant freshness report envelope from enriched endpoint rows."""
    now = now or datetime.now(timezone.utc)
    flagged: List[McpFreshnessEndpointOut] = []

    for row in candidates:
        status = derive_freshness_status(
            row,
            default_cadence_seconds=default_cadence_seconds,
            now=now,
        )
        if not freshness_is_flagged(status):
            continue
        flagged.append(
            mcp_freshness_endpoint_out_from_row(
                row,
                freshness=status,
                reason=freshness_reason(status),
                last_known_good_at=resolve_last_known_good_at(row),
            )
        )

    flagged.sort(
        key=lambda item: (
            _FRESHNESS_PRECEDENCE.index(item.freshness)
            if item.freshness in _FRESHNESS_PRECEDENCE
            else len(_FRESHNESS_PRECEDENCE),
            item.name.lower(),
            item.slug,
        )
    )

    return McpFreshnessReportResponse(
        success=True,
        default_cadence_seconds=effective_discovery_cadence_seconds(
            None,
            default_cadence_seconds=default_cadence_seconds,
        ),
        flagged_endpoint_count=len(flagged),
        endpoints=flagged,
    )
