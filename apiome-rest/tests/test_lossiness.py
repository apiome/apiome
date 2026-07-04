"""Unit tests for the lossiness report model — MFX-2.1 (#3838).

Pins the acceptance criteria of the *model* (the computation engine is MFX-2.2):

* the report **serializes to JSON** losslessly and round-trips through
  ``model_validate`` — including the ``construct`` JSON key (aliased);
* it carries **summary counts per kind and per severity**, zero-filled for every
  enum member and always consistent with ``items`` (cannot drift);
* items are in a **stable, deterministic order** regardless of insertion order or
  how the report was built;

plus the model's invariants: ``extra="forbid"`` strictness, the DROP/APPROX/SYNTH/OK
and info/warn/critical vocabularies, the ``LossinessReportBuilder`` ergonomics, and
the ``is_lossless`` / ``worst_severity`` convenience gates downstream tickets read.
"""

import pytest
from pydantic import ValidationError

from app.lossiness import (
    LossinessKind,
    LossinessReport,
    LossinessReportBuilder,
    LossinessSeverity,
    LossItem,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_report() -> LossinessReport:
    """A mixed report touching every kind and severity, built out of order."""
    builder = LossinessReportBuilder()
    # Deliberately inserted in a non-sorted order to prove the model reorders.
    builder.add(
        "acme.Pet.tags",
        LossinessKind.SYNTH,
        LossinessSeverity.INFO,
        "target requires a field number; synthesized 5",
        target_mapping="protobuf field number 5",
    )
    builder.add(
        "User.contact",
        LossinessKind.DROP,
        LossinessSeverity.CRITICAL,
        "discriminated union has no target representation",
    )
    builder.add(
        "acme.Pet.count",
        LossinessKind.APPROX,
        LossinessSeverity.WARN,
        "numeric range demoted to a doc comment",
        target_mapping="minimum/maximum → field comment",
    )
    builder.ok("acme.Pet.id")
    return builder.build()


# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------


def test_kind_vocabulary():
    assert [k.value for k in LossinessKind] == ["drop", "approx", "synth", "ok"]


def test_severity_vocabulary():
    assert [s.value for s in LossinessSeverity] == ["info", "warn", "critical"]


# ---------------------------------------------------------------------------
# LossItem
# ---------------------------------------------------------------------------


def test_lossitem_serializes_construct_as_alias():
    item = LossItem(
        construct_key="User.email",
        kind=LossinessKind.DROP,
        severity=LossinessSeverity.WARN,
        message="dropped",
    )
    dumped = item.model_dump()
    assert dumped["construct"] == "User.email"
    assert "construct_key" not in dumped
    assert dumped["target_mapping"] is None


def test_lossitem_construct_populate_by_name_and_alias():
    by_alias = LossItem(
        construct="User.email",
        kind=LossinessKind.OK,
        severity=LossinessSeverity.INFO,
        message="ok",
    )
    by_name = LossItem(
        construct_key="User.email",
        kind=LossinessKind.OK,
        severity=LossinessSeverity.INFO,
        message="ok",
    )
    assert by_alias.construct_key == by_name.construct_key == "User.email"


def test_lossitem_rejects_unknown_field():
    with pytest.raises(ValidationError):
        LossItem(
            construct="User.email",
            kind=LossinessKind.OK,
            severity=LossinessSeverity.INFO,
            message="ok",
            bogus="nope",
        )


def test_lossitem_rejects_unknown_enum_value():
    with pytest.raises(ValidationError):
        LossItem(
            construct="User.email",
            kind="deleted",  # not a LossinessKind
            severity=LossinessSeverity.INFO,
            message="ok",
        )


# ---------------------------------------------------------------------------
# Counts — per kind and per severity, zero-filled, always consistent
# ---------------------------------------------------------------------------


def test_counts_cover_every_enum_member_zero_filled():
    report = LossinessReport()
    assert report.kind_counts == {"drop": 0, "approx": 0, "synth": 0, "ok": 0}
    assert report.severity_counts == {"info": 0, "warn": 0, "critical": 0}


def test_counts_tally_items():
    report = _sample_report()
    assert report.kind_counts == {"drop": 1, "approx": 1, "synth": 1, "ok": 1}
    assert report.severity_counts == {"info": 2, "warn": 1, "critical": 1}
    assert sum(report.kind_counts.values()) == report.total == 4
    assert sum(report.severity_counts.values()) == report.total


def test_counts_are_recomputed_and_cannot_drift():
    # A caller supplying deliberately wrong counts gets them overwritten from items.
    report = LossinessReport(
        items=[
            LossItem(
                construct="A",
                kind=LossinessKind.DROP,
                severity=LossinessSeverity.WARN,
                message="m",
            )
        ],
        kind_counts={"drop": 999, "ok": 42},
        severity_counts={"critical": 7},
    )
    assert report.kind_counts == {"drop": 1, "approx": 0, "synth": 0, "ok": 0}
    assert report.severity_counts == {"info": 0, "warn": 1, "critical": 0}


# ---------------------------------------------------------------------------
# Stable ordering
# ---------------------------------------------------------------------------


def test_items_sorted_by_construct_then_kind_then_severity():
    report = _sample_report()
    order = [(i.construct_key, i.kind.value, i.severity.value) for i in report.items]
    assert order == [
        ("User.contact", "drop", "critical"),
        ("acme.Pet.count", "approx", "warn"),
        ("acme.Pet.id", "ok", "info"),
        ("acme.Pet.tags", "synth", "info"),
    ]


def test_ordering_is_insertion_independent():
    """Two reports with the same items inserted in different orders are equal."""
    forward = LossinessReportBuilder()
    forward.add("A", LossinessKind.DROP, LossinessSeverity.WARN, "a")
    forward.add("B", LossinessKind.APPROX, LossinessSeverity.INFO, "b")
    forward.add("C", LossinessKind.SYNTH, LossinessSeverity.CRITICAL, "c")

    reverse = LossinessReportBuilder()
    reverse.add("C", LossinessKind.SYNTH, LossinessSeverity.CRITICAL, "c")
    reverse.add("B", LossinessKind.APPROX, LossinessSeverity.INFO, "b")
    reverse.add("A", LossinessKind.DROP, LossinessSeverity.WARN, "a")

    assert forward.build().model_dump() == reverse.build().model_dump()


def test_ordering_tie_break_within_a_construct():
    """Same construct + kind + severity falls back to message then mapping."""
    builder = LossinessReportBuilder()
    builder.add("User.x", LossinessKind.APPROX, LossinessSeverity.WARN, "zebra")
    builder.add("User.x", LossinessKind.APPROX, LossinessSeverity.WARN, "alpha")
    messages = [i.message for i in builder.build().items]
    assert messages == ["alpha", "zebra"]


# ---------------------------------------------------------------------------
# JSON serialization / round-trip (acceptance criterion)
# ---------------------------------------------------------------------------


def test_report_round_trips_through_json():
    report = _sample_report()
    payload = report.model_dump_json()
    restored = LossinessReport.model_validate_json(payload)
    assert restored.model_dump() == report.model_dump()


def test_report_json_uses_construct_key_and_carries_counts():
    report = _sample_report()
    dumped = report.model_dump()
    assert all("construct" in item and "construct_key" not in item for item in dumped["items"])
    assert dumped["kind_counts"] == {"drop": 1, "approx": 1, "synth": 1, "ok": 1}
    assert dumped["severity_counts"] == {"info": 2, "warn": 1, "critical": 1}


def test_report_validates_from_construct_alias_payload():
    """A persisted/producer payload keyed by ``construct`` validates back."""
    payload = {
        "items": [
            {
                "construct": "User.email",
                "kind": "drop",
                "severity": "critical",
                "message": "gone",
                "target_mapping": None,
            }
        ]
    }
    report = LossinessReport.model_validate(payload)
    assert report.items[0].construct_key == "User.email"
    assert report.kind_counts["drop"] == 1


def test_report_serialization_is_deterministic():
    assert _sample_report().model_dump_json() == _sample_report().model_dump_json()


# ---------------------------------------------------------------------------
# Convenience gates used downstream (MFX-2.4)
# ---------------------------------------------------------------------------


def test_empty_report_is_lossless():
    report = LossinessReport()
    assert report.is_lossless is True
    assert report.worst_severity is None
    assert report.total == 0


def test_ok_only_report_is_lossless():
    builder = LossinessReportBuilder()
    builder.ok("A")
    builder.ok("B")
    report = builder.build()
    assert report.is_lossless is True
    assert report.worst_severity is None


def test_report_with_any_loss_is_not_lossless():
    builder = LossinessReportBuilder()
    builder.ok("A")
    builder.add("B", LossinessKind.APPROX, LossinessSeverity.INFO, "approximated")
    report = builder.build()
    assert report.is_lossless is False


def test_worst_severity_ignores_ok_items():
    builder = LossinessReportBuilder()
    # An OK item nominally at info; a real loss at warn should win.
    builder.ok("A")
    builder.add("B", LossinessKind.DROP, LossinessSeverity.WARN, "dropped")
    assert builder.build().worst_severity is LossinessSeverity.WARN


def test_worst_severity_picks_the_most_severe():
    builder = LossinessReportBuilder()
    builder.add("A", LossinessKind.APPROX, LossinessSeverity.INFO, "a")
    builder.add("B", LossinessKind.DROP, LossinessSeverity.CRITICAL, "b")
    builder.add("C", LossinessKind.SYNTH, LossinessSeverity.WARN, "c")
    assert builder.build().worst_severity is LossinessSeverity.CRITICAL


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------


def test_items_of_kind_and_severity():
    report = _sample_report()
    assert [i.construct_key for i in report.items_of_kind(LossinessKind.DROP)] == [
        "User.contact"
    ]
    assert [i.construct_key for i in report.items_of_severity(LossinessSeverity.INFO)] == [
        "acme.Pet.id",
        "acme.Pet.tags",
    ]


# ---------------------------------------------------------------------------
# Builder ergonomics
# ---------------------------------------------------------------------------


def test_builder_ok_defaults_to_info_and_ok_kind():
    item = LossinessReportBuilder().ok("A")
    assert item.kind is LossinessKind.OK
    assert item.severity is LossinessSeverity.INFO


def test_builder_add_returns_the_recorded_item():
    builder = LossinessReportBuilder()
    item = builder.add(
        "A", LossinessKind.SYNTH, LossinessSeverity.INFO, "synth", "field 1"
    )
    assert item.construct_key == "A"
    assert item.target_mapping == "field 1"
    assert builder.build().items == [item]


def test_builder_build_is_isolated_from_further_mutation():
    """A built report is not mutated by later additions to the same builder."""
    builder = LossinessReportBuilder()
    builder.add("A", LossinessKind.DROP, LossinessSeverity.WARN, "a")
    report = builder.build()
    builder.add("B", LossinessKind.DROP, LossinessSeverity.WARN, "b")
    assert [i.construct_key for i in report.items] == ["A"]
    assert [i.construct_key for i in builder.build().items] == ["A", "B"]
