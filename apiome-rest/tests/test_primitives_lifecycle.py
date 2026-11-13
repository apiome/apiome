"""Unit tests for the type deprecation rules (#3482, 7.5) — no database, no HTTP."""

from datetime import date

from app.primitives_lifecycle import (
    audit_detail,
    collect_errors,
    normalize_message,
    replacement_error,
    replacement_summary,
    sunset_date_error,
)

_TODAY = date(2026, 11, 13)


class TestNormalizeMessage:
    def test_trims_surrounding_whitespace(self):
        assert normalize_message("  Use money-v2.  ") == "Use money-v2."

    def test_empty_and_blank_are_no_message(self):
        assert normalize_message("") is None
        assert normalize_message("   \n") is None
        assert normalize_message(None) is None


class TestSunsetDateError:
    def test_no_date_is_fine(self):
        assert sunset_date_error(None, _TODAY) is None

    def test_today_and_future_are_fine(self):
        assert sunset_date_error(_TODAY, _TODAY) is None
        assert sunset_date_error(date(2027, 1, 31), _TODAY) is None

    def test_a_past_date_is_refused_and_named(self):
        error = sunset_date_error(date(2026, 11, 12), _TODAY)
        assert error is not None
        assert "2026-11-12" in error
        assert "past" in error


class TestReplacementError:
    def test_no_replacement_is_fine(self):
        assert replacement_error("p1", None, None) is None

    def test_a_visible_active_type_is_fine(self):
        assert replacement_error("p1", "p2", {"id": "p2", "name": "money-v2"}) is None

    def test_a_type_cannot_replace_itself(self):
        error = replacement_error("p1", "p1", {"id": "p1", "name": "money"})
        assert error == "A type cannot be its own replacement"

    def test_an_unknown_or_invisible_type_is_refused(self):
        assert replacement_error("p1", "p9", None) == "Replacement type not found: p9"

    def test_a_deprecated_type_is_refused(self):
        error = replacement_error(
            "p1", "p2", {"id": "p2", "name": "old-money", "deprecated_at": "2026-01-01"}
        )
        assert error == "Replacement type 'old-money' is itself deprecated"


class TestReplacementSummary:
    def test_none_stays_none(self):
        assert replacement_summary(None) is None

    def test_keeps_only_what_a_reader_follows(self):
        row = {"id": 42, "name": "money-v2", "schema_id": "https://x/money-v2", "schema": {}}
        assert replacement_summary(row) == {
            "id": "42",
            "name": "money-v2",
            "schema_id": "https://x/money-v2",
        }


class TestAuditDetail:
    def test_serializes_the_record(self):
        row = {
            "name": "money",
            "sunset_date": date(2027, 1, 31),
            "deprecation_message": "Use money-v2.",
            "replacement_id": "p2",
        }
        assert audit_detail(row, was_deprecated=False) == {
            "name": "money",
            "sunset_date": "2027-01-31",
            "message": "Use money-v2.",
            "replacement_id": "p2",
            "updated_existing": False,
        }

    def test_absent_details_stay_null_and_a_change_is_flagged(self):
        detail = audit_detail({"name": "money"}, was_deprecated=True)
        assert detail["sunset_date"] is None
        assert detail["replacement_id"] is None
        assert detail["updated_existing"] is True


def test_collect_errors_drops_the_absent_ones():
    assert collect_errors(None, "a", None, "b") == ["a", "b"]
    assert collect_errors(None, None) == []
