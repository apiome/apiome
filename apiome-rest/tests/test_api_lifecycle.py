"""The product and plan lifecycle rules — APX-1.4 (#6101).

Pure tests of :mod:`app.api_lifecycle` and the lifecycle parts of :mod:`app.api_plans`: which state
steps are allowed, what each step stamps or clears, that retiring waits for the date, that a successor
must keep the consumer's credential working, where an entry sits on the sunset timeline, and what a
deprecated plan says and exports.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app import api_lifecycle as lc
from app.api_plans import (
    NOTICE_DEPRECATED,
    ApiPlanPatch,
    ApiPlanRecord,
    PlanAuthConfig,
    PlanRef,
    deprecated_notice,
    plan_extension_entry,
)

_NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def _changes(row, target, **sent):
    return lc.lifecycle_changes(
        row, target=target, sent=frozenset(sent), retire_at=sent.get("retire_at"),
        message=sent.get("deprecation_message"), now=_NOW, noun="plan",
    )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("draft", "published"), ("published", "draft"), ("published", "deprecated"),
        ("deprecated", "published"), ("deprecated", "retired"), ("published", "published"),
        ("retired", "retired"),
    ],
)
def test_lifecycle_steps_are_allowed(current: str, target: str) -> None:
    lc.check_transition(current, target, "plan")


@pytest.mark.parametrize(
    ("current", "target", "words"),
    [
        ("published", "retired", "deprecate the plan before retiring it"),
        ("draft", "retired", "deprecate the plan before retiring it"),
        ("draft", "deprecated", "a draft plan cannot become deprecated"),
        ("retired", "published", "a retired plan cannot change state"),
        ("retired", "deprecated", "a retired plan cannot change state"),
    ],
)
def test_other_steps_are_refused(current: str, target: str, words: str) -> None:
    with pytest.raises(lc.LifecycleError) as caught:
        lc.check_transition(current, target, "plan")
    assert caught.value.code == lc.CODE_TRANSITION and str(caught.value) == words


def test_a_new_record_starts_as_draft_or_published() -> None:
    lc.check_initial_state("draft", "plan")
    lc.check_initial_state("published", "product")
    for state in ("deprecated", "retired"):
        with pytest.raises(lc.LifecycleError) as caught:
            lc.check_initial_state(state, "plan")
        assert caught.value.code == lc.CODE_INVALID_STATE


def test_deprecating_stamps_the_time_and_takes_the_date_and_message() -> None:
    retire = datetime(2027, 3, 31)
    changes = _changes(
        {"state": "published"}, "deprecated", retire_at=retire, deprecation_message="  Move to Premium. "
    )
    assert changes == {
        "deprecated_at": _NOW,
        "retire_at": datetime(2027, 3, 31, tzinfo=timezone.utc),
        "deprecation_message": "Move to Premium.",
    }


def test_a_deprecated_record_can_move_its_date_without_restamping() -> None:
    later = _NOW + timedelta(days=90)
    assert _changes({"state": "deprecated"}, "deprecated", retire_at=later) == {"retire_at": later}


def test_reinstating_clears_the_deprecation() -> None:
    assert _changes({"state": "deprecated"}, "published") == {
        "deprecated_at": None, "retire_at": None, "deprecation_message": None,
    }


def test_deprecation_fields_need_a_deprecated_record() -> None:
    with pytest.raises(lc.LifecycleError) as caught:
        _changes({"state": "published"}, "published", deprecation_message="soon")
    assert caught.value.code == lc.CODE_TRANSITION


def test_retiring_waits_for_the_date() -> None:
    with pytest.raises(lc.LifecycleError) as caught:
        _changes({"state": "deprecated", "retire_at": _NOW + timedelta(days=1)}, "retired")
    assert caught.value.code == lc.CODE_RETIRE_EARLY and "2026-11-17" in str(caught.value)
    assert _changes({"state": "deprecated", "retire_at": _NOW - timedelta(days=1)}, "retired") == {"retired_at": _NOW}
    assert _changes({"state": "deprecated", "retire_at": None}, "retired") == {"retired_at": _NOW}


def test_a_message_is_bounded() -> None:
    assert lc.normalize_message("   ") is None
    with pytest.raises(lc.LifecycleError):
        lc.normalize_message("x" * (lc.MAX_MESSAGE_LENGTH + 1))


def test_only_a_published_plan_accepts_new_subscriptions() -> None:
    assert [s for s in ("draft", "published", "deprecated", "retired") if lc.accepts_new_subscriptions(s)] == [
        "published"
    ]


@pytest.mark.parametrize(
    ("candidate", "words"),
    [
        (None, "no such plan"),
        ({"id": "p1", "slug": "standard", "state": "deprecated", "auth_strategy": "key_auth"}, "replace itself"),
        ({"id": "p2", "slug": "premium", "state": "draft", "auth_strategy": "key_auth"}, "is draft"),
        ({"id": "p2", "slug": "premium", "state": "published", "auth_strategy": "mtls"}, "same auth strategy"),
    ],
)
def test_a_successor_must_keep_the_credential_working(candidate, words: str) -> None:
    plan = {"id": "p1", "auth_strategy": "key_auth"}
    assert words in (lc.successor_problem(plan, candidate) or "")


def test_a_published_plan_with_the_same_auth_is_a_good_successor() -> None:
    candidate = {"id": "p2", "slug": "premium", "state": "published", "auth_strategy": "key_auth"}
    assert lc.successor_problem({"id": "p1", "auth_strategy": "key_auth"}, candidate) is None


def test_the_consumer_group_name() -> None:
    assert lc.plan_group_name("payments", "standard") == "plan:payments-standard"


@pytest.mark.parametrize(
    ("state", "retire_at", "expected"),
    [
        ("deprecated", None, ("announced", "deprecated")),
        ("deprecated", datetime(2027, 6, 1, tzinfo=timezone.utc), ("announced", "deprecated")),
        ("deprecated", datetime(2026, 12, 1, tzinfo=timezone.utc), ("imminent", "deprecated")),
        ("deprecated", datetime(2026, 11, 1, tzinfo=timezone.utc), ("past", "sunset_reached")),
        ("retired", datetime(2026, 11, 1, tzinfo=timezone.utc), ("past", "retired")),
    ],
)
def test_timeline_status(state, retire_at, expected) -> None:
    assert lc.timeline_status(state, retire_at, date(2026, 11, 16)) == expected


def test_a_deprecated_plan_says_what_happens_next() -> None:
    premium = PlanRef(slug="premium", name="Premium", state="published")
    notice = deprecated_notice("deprecated", "2027-03-31T00:00:00+00:00", premium)
    assert notice is not None and notice.code == NOTICE_DEPRECATED
    assert notice.message == (
        "Deprecated: new subscriptions are blocked. It retires on 2027-03-31. Consumers move to Premium (premium)."
    )
    assert "Choose a replacement plan" in deprecated_notice("deprecated", None, None).message
    assert deprecated_notice("published", None, None) is None


def test_the_export_entry_carries_the_deprecation() -> None:
    plan = ApiPlanRecord(
        id="pl-1", product="payments", slug="standard", name="Standard", auth_strategy="key_auth",
        auth_config=PlanAuthConfig(), approval="manual", declared_only=True, state="deprecated",
        retire_at="2027-03-31T00:00:00+00:00", deprecation_message="Move to Premium.",
        successor=PlanRef(slug="premium", name="Premium", state="published"),
    )
    entry = plan_extension_entry("payments", "Payments", plan)
    assert entry["state"] == "deprecated" and entry["successor"] == "premium"
    assert entry["retire_at"] == "2027-03-31T00:00:00+00:00" and entry["deprecation_message"] == "Move to Premium."


def test_the_patch_accepts_the_lifecycle_fields() -> None:
    patch = ApiPlanPatch(state="deprecated", retire_at="2027-03-31", successor="premium", deprecation_message="m")
    assert patch.retire_at == datetime(2027, 3, 31) and patch.successor == "premium"
