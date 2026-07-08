"""Unit tests for MCP catalog freshness reporting (V2-MCP-36.2 / MCAT-22.2, #4665)."""

from datetime import datetime, timedelta, timezone

from app.mcp_freshness_report import (
    derive_freshness_status,
    freshness_is_flagged,
    mcp_freshness_report_from_rows,
    resolve_last_known_good_at,
)

_NOW = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)
_DEFAULT_CADENCE = 3600


def _row(
    *,
    id: str = "ep-1",
    name: str = "Weather",
    slug: str = "weather",
    endpoint_url: str = "https://mcp.acme.example/sse",
    enabled: bool = True,
    discovery_cadence_seconds: int | None = None,
    last_discovered_at: datetime | None = _NOW - timedelta(minutes=30),
    last_discovery_status: str = "unchanged",
    consecutive_failures: int = 0,
    next_discovery_after: datetime | None = None,
    quarantined_at: datetime | None = None,
    last_known_good_at: datetime | None = _NOW - timedelta(hours=2),
) -> dict:
    return {
        "id": id,
        "tenant_id": "t1",
        "name": name,
        "slug": slug,
        "endpoint_url": endpoint_url,
        "transport": "streamable_http",
        "visibility": "private",
        "published": False,
        "enabled": enabled,
        "discovery_cadence_seconds": discovery_cadence_seconds,
        "last_discovered_at": last_discovered_at,
        "last_discovery_status": last_discovery_status,
        "consecutive_failures": consecutive_failures,
        "next_discovery_after": next_discovery_after,
        "quarantined_at": quarantined_at,
        "quarantine_reason": "connect_error" if quarantined_at else None,
        "current_version_id": "ver-1" if last_known_good_at else None,
        "last_known_good_at": last_known_good_at,
    }


def test_healthy_in_cadence_endpoint_is_fresh():
    status = derive_freshness_status(
        _row(),
        default_cadence_seconds=_DEFAULT_CADENCE,
        now=_NOW,
    )
    assert status == "fresh"
    assert not freshness_is_flagged(status)


def test_past_cadence_endpoint_is_stale():
    status = derive_freshness_status(
        _row(last_discovered_at=_NOW - timedelta(hours=3)),
        default_cadence_seconds=_DEFAULT_CADENCE,
        now=_NOW,
    )
    assert status == "stale"


def test_failing_endpoint_is_flagged_before_stale():
    status = derive_freshness_status(
        _row(
            consecutive_failures=2,
            last_discovery_status="failed",
            last_discovered_at=_NOW - timedelta(hours=3),
        ),
        default_cadence_seconds=_DEFAULT_CADENCE,
        now=_NOW,
    )
    assert status == "failing"


def test_backoff_takes_precedence_over_failing_streak_display():
    status = derive_freshness_status(
        _row(
            consecutive_failures=1,
            next_discovery_after=_NOW + timedelta(minutes=10),
            last_discovery_status="failed",
        ),
        default_cadence_seconds=_DEFAULT_CADENCE,
        now=_NOW,
    )
    assert status == "backoff"


def test_quarantined_takes_precedence():
    status = derive_freshness_status(
        _row(
            quarantined_at=_NOW - timedelta(hours=1),
            consecutive_failures=5,
            next_discovery_after=_NOW + timedelta(minutes=5),
        ),
        default_cadence_seconds=_DEFAULT_CADENCE,
        now=_NOW,
    )
    assert status == "quarantined"


def test_disabled_endpoint_is_unflagged():
    status = derive_freshness_status(
        _row(enabled=False, last_discovered_at=_NOW - timedelta(days=2)),
        default_cadence_seconds=_DEFAULT_CADENCE,
        now=_NOW,
    )
    assert status == "fresh"


def test_last_known_good_prefers_snapshot_timestamp_when_failing():
    row = _row(
        consecutive_failures=2,
        last_discovery_status="failed",
        last_known_good_at=_NOW - timedelta(days=1),
        last_discovered_at=_NOW - timedelta(minutes=5),
    )
    assert resolve_last_known_good_at(row) == (_NOW - timedelta(days=1)).isoformat()


def test_report_lists_only_flagged_endpoints_on_seeded_like_rows():
    rows = [
        _row(id="fresh", slug="fresh"),
        _row(
            id="stale",
            slug="stale",
            name="Stale API",
            last_discovered_at=_NOW - timedelta(hours=5),
        ),
        _row(
            id="failing",
            slug="failing",
            name="Failing API",
            consecutive_failures=3,
            last_discovery_status="failed",
        ),
    ]
    report = mcp_freshness_report_from_rows(
        default_cadence_seconds=_DEFAULT_CADENCE,
        candidates=rows,
        now=_NOW,
    )
    assert report.flagged_endpoint_count == 2
    slugs = {item.slug for item in report.endpoints}
    assert slugs == {"stale", "failing"}
    failing = next(item for item in report.endpoints if item.slug == "failing")
    assert failing.last_known_good_at is not None
    assert failing.freshness == "failing"
