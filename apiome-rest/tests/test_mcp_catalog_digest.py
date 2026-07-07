"""Pure catalog-digest compilation tests (MCAT-19.5, #4654).

Deterministic, DB-free coverage of ``app.mcp_catalog_digest``: the raw-rows → digest fold, the
breaking-change classification/cap, grade-movement direction, the empty-window predicate, and the
webhook payload shape. No database or network is touched.
"""

from datetime import datetime, timedelta, timezone

from app.mcp_catalog_digest import (
    EVENT_TYPE_DIGEST,
    build_digest_payload,
    compile_digest,
    digest_is_empty,
    render_digest_summary,
)

NOW = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)
WINDOW_START = NOW - timedelta(days=7)


def _endpoint_row(slug: str, *, name=None, visibility="private", created_at=None):
    return {
        "id": f"ep-{slug}",
        "name": name or f"Server {slug}",
        "slug": slug,
        "visibility": visibility,
        "created_at": created_at or (NOW - timedelta(days=1)),
    }


def _removed_change(slug: str, item_name: str):
    """A ``removed`` change — always breaking per classify_change."""
    return {
        "endpoint_id": f"ep-{slug}",
        "endpoint_name": f"Server {slug}",
        "endpoint_slug": slug,
        "version_id": f"v-{slug}-{item_name}",
        "change_type": "removed",
        "item_type": "tool",
        "item_name": item_name,
        "detail": {},
        "version_seq": 3,
        "version_tag": "2026-07-06T00:00Z",
        "discovered_at": NOW - timedelta(hours=2),
        "version_created_at": NOW - timedelta(hours=2),
        "created_at": NOW - timedelta(hours=2),
    }


def _added_change(slug: str, item_name: str):
    """An ``added`` change — always additive (never breaking)."""
    return {
        "endpoint_id": f"ep-{slug}",
        "endpoint_name": f"Server {slug}",
        "endpoint_slug": slug,
        "version_id": f"v-{slug}-{item_name}",
        "change_type": "added",
        "item_type": "tool",
        "item_name": item_name,
        "detail": {},
        "version_seq": 3,
        "version_tag": "2026-07-06T00:00Z",
        "discovered_at": NOW - timedelta(hours=2),
    }


def _grade_row(slug: str, prev, new):
    return {
        "endpoint_id": f"ep-{slug}",
        "endpoint_name": f"Server {slug}",
        "endpoint_slug": slug,
        "version_seq": 4,
        "version_tag": "2026-07-06T00:00Z",
        "moved_at": NOW - timedelta(hours=3),
        "prev_grade": prev,
        "new_grade": new,
    }


def _health_row(slug: str, *, quarantined=False, failures=1, status="failed"):
    return {
        "id": f"ep-{slug}",
        "name": f"Server {slug}",
        "slug": slug,
        "visibility": "private",
        "quarantined_at": (NOW - timedelta(hours=1)) if quarantined else None,
        "quarantine_reason": "unreachable" if quarantined else None,
        "consecutive_failures": failures,
        "last_discovery_status": status,
        "last_discovered_at": NOW - timedelta(hours=1),
    }


def _compile(**kwargs):
    base = dict(
        tenant_slug="acme",
        window_start=WINDOW_START,
        window_end=NOW,
        new_endpoint_rows=[],
        change_rows=[],
        grade_movement_rows=[],
        health_rows=[],
    )
    base.update(kwargs)
    return compile_digest(**base)


# --- empty window ----------------------------------------------------------------------------------


def test_empty_window_is_empty():
    digest = _compile()
    assert digest_is_empty(digest)
    assert "No catalog changes" in render_digest_summary(digest)
    payload = build_digest_payload(digest)
    assert payload["empty"] is True
    assert payload["event"] == EVENT_TYPE_DIGEST
    assert payload["totals"] == {
        "newEndpoints": 0,
        "gradeMovements": 0,
        "breakingChanges": 0,
        "healthProblems": 0,
    }


def test_added_only_changes_are_not_breaking_and_stay_empty():
    """A window with only additive changes has no breaking section and is still 'empty'."""
    digest = _compile(change_rows=[_added_change("weather", "getForecast")])
    assert digest.breaking_change_total == 0
    assert digest_is_empty(digest)


# --- populated sections ----------------------------------------------------------------------------


def test_new_endpoints_section():
    digest = _compile(new_endpoint_rows=[_endpoint_row("weather"), _endpoint_row("maps")])
    assert not digest_is_empty(digest)
    assert [e.slug for e in digest.new_endpoints] == ["weather", "maps"]
    assert "2 new endpoints" in render_digest_summary(digest)


def test_breaking_changes_only_keeps_breaking():
    digest = _compile(
        change_rows=[
            _removed_change("weather", "getForecast"),
            _added_change("weather", "getAlerts"),  # additive, excluded
            _removed_change("maps", "geocode"),
        ]
    )
    assert digest.breaking_change_total == 2
    names = {c.item_name for c in digest.breaking_changes}
    assert names == {"getForecast", "geocode"}


def test_breaking_changes_capped_but_total_preserved():
    rows = [_removed_change("weather", f"tool{i}") for i in range(60)]
    digest = _compile(change_rows=rows)
    assert digest.breaking_change_total == 60
    assert len(digest.breaking_changes) == 50  # _MAX_BREAKING_ENTRIES
    payload = build_digest_payload(digest)
    assert payload["breakingChangesTruncated"] is True
    assert payload["totals"]["breakingChanges"] == 60


def test_grade_movement_direction():
    digest = _compile(
        grade_movement_rows=[
            _grade_row("up", "C", "A"),
            _grade_row("down", "B", "D"),
            _grade_row("weird", "Z", "A"),
        ]
    )
    by_slug = {m.slug: m for m in digest.grade_movements}
    assert by_slug["up"].direction == "improved"
    assert by_slug["down"].direction == "declined"
    assert by_slug["weird"].direction == "changed"  # unrecognized grade → neutral


def test_health_problems_section():
    digest = _compile(
        health_rows=[
            _health_row("dead", quarantined=True),
            _health_row("flaky", quarantined=False, failures=2),
        ]
    )
    by_slug = {h.slug: h for h in digest.health_problems}
    assert by_slug["dead"].quarantined is True
    assert by_slug["dead"].quarantine_reason == "unreachable"
    assert by_slug["flaky"].quarantined is False
    assert by_slug["flaky"].consecutive_failures == 2


# --- payload contract ------------------------------------------------------------------------------


def test_payload_shape_and_camelcase():
    digest = _compile(
        new_endpoint_rows=[_endpoint_row("weather")],
        change_rows=[_removed_change("weather", "getForecast")],
        grade_movement_rows=[_grade_row("weather", "B", "A")],
        health_rows=[_health_row("weather", quarantined=True)],
    )
    payload = build_digest_payload(digest)
    assert payload["event"] == EVENT_TYPE_DIGEST
    assert payload["tenantSlug"] == "acme"
    assert payload["windowStart"] == WINDOW_START.isoformat()
    assert payload["windowEnd"] == NOW.isoformat()
    assert payload["empty"] is False
    assert payload["totals"] == {
        "newEndpoints": 1,
        "gradeMovements": 1,
        "breakingChanges": 1,
        "healthProblems": 1,
    }
    # Sections present with camelCase keys and no leaked endpoint_url.
    assert payload["newEndpoints"][0]["slug"] == "weather"
    assert payload["gradeMovements"][0]["newGrade"] == "A"
    assert payload["breakingChanges"][0]["itemName"] == "getForecast"
    assert payload["healthProblems"][0]["quarantined"] is True
    assert "endpointUrl" not in payload["newEndpoints"][0]


def test_malformed_timestamp_degrades_to_none():
    row = _endpoint_row("weather")
    row["created_at"] = "not-a-date"
    digest = _compile(new_endpoint_rows=[row])
    assert digest.new_endpoints[0].created_at is None
    # Payload still serializes.
    assert build_digest_payload(digest)["newEndpoints"][0]["createdAt"] is None
