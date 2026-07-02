"""Unit tests for revision deprecation helpers (#507)."""

from datetime import date

from app.revision_deprecation import (
    MIGRATION_GUIDE_ISSUE_URL,
    deprecation_payload_for_openapi,
    is_revision_deprecated,
    merge_version_metadata,
    parse_calendar_date,
    sunset_timeline_fields,
    warnings_for_revision,
)


def test_is_revision_deprecated():
    assert is_revision_deprecated(None) is False
    assert is_revision_deprecated({}) is False
    assert is_revision_deprecated({"deprecated": True}) is True
    assert is_revision_deprecated({"deprecated": "true"}) is True


def test_merge_version_metadata():
    assert merge_version_metadata(None, {"deprecated": True}) == {"deprecated": True}
    assert merge_version_metadata({"a": 1}, {"deprecated": True}) == {"a": 1, "deprecated": True}


def test_deprecation_payload_for_openapi():
    assert deprecation_payload_for_openapi(None) is None
    p = deprecation_payload_for_openapi(
        {
            "deprecated": True,
            "deprecationMessage": "Use v2",
            "successorRevisionId": "uuid-1",
            "sunsetDate": "2026-12-01",
        }
    )
    assert p is not None
    assert p["deprecated"] is True
    assert p["message"] == "Use v2"
    assert p["successorRevisionId"] == "uuid-1"
    assert p["sunsetDate"] == "2026-12-01"
    assert p["sunsetAt"] == "2026-12-01"
    assert p["migrationGuideUrl"] == MIGRATION_GUIDE_ISSUE_URL


def test_warnings_for_revision():
    w = warnings_for_revision(
        revision_id="rev-full",
        version_label="1.0.0",
        role="base",
        metadata={
            "deprecated": True,
            "deprecationMessage": "Old line",
            "successorRevisionId": "new-rev",
            "sunsetDate": "2026-06-01",
        },
    )
    assert len(w) == 1
    assert w[0].revision_id == "rev-full"
    assert w[0].role == "base"
    assert w[0].replacement_revision_id == "new-rev"
    assert w[0].sunset_date == "2026-06-01"
    assert MIGRATION_GUIDE_ISSUE_URL in w[0].message


def test_parse_calendar_date():
    assert parse_calendar_date("2026-06-01") == date(2026, 6, 1)
    assert parse_calendar_date("2026-06-01T12:00:00Z") == date(2026, 6, 1)
    assert parse_calendar_date("") is None
    assert parse_calendar_date("bad") is None


def test_sunset_timeline_fields_deprecated_only():
    ts, life, sd = sunset_timeline_fields({"deprecated": True}, today=date(2026, 1, 1))
    assert ts == "announced"
    assert life == "deprecated"
    assert sd is None


def test_sunset_timeline_fields_past_sunset():
    ts, life, sd = sunset_timeline_fields(
        {"deprecated": True, "sunsetDate": "2020-01-01"},
        today=date(2026, 1, 1),
    )
    assert ts == "past"
    assert life == "sunset_reached"
    assert sd == "2020-01-01"


def test_sunset_timeline_fields_imminent():
    ts, life, sd = sunset_timeline_fields(
        {"deprecated": True, "sunsetDate": "2026-01-15"},
        today=date(2026, 1, 1),
    )
    assert ts == "imminent"
    assert life == "deprecated"
    assert sd == "2026-01-15"
