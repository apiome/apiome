"""The retention planner — PFX-1.11 (#6924).

:func:`app.pact_retention.plan_retention` is pure, so every rule is pinned here without a database:

* each keep selector keeps what it says, and the first rule that keeps a version is the one counted;
* a pacticipant's latest version is kept whatever the selectors say;
* a run with no selector is refused rather than deleting everything but the latest;
* the cap deletes the oldest first and reports the rest as ``remaining``;
* the digest is stable for the same plan and changes when the plan does;
* the answer lists at most :data:`MAX_LISTED_PER_PACTICIPANT` deletions per pacticipant, but counts all.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Sequence

import pytest
from pydantic import ValidationError

from app.pact_retention import (
    CODE_NO_SELECTOR,
    MAX_LISTED_PER_PACTICIPANT,
    RetentionError,
    RetentionKeep,
    RetentionRequest,
    VersionFacts,
    digest_of,
    plan_retention,
)

NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)
BILLING = ("p1", "billing-service", "Billing Service")
LEDGER = ("p2", "ledger-api", "Ledger API")


def _v(
    number: str,
    seq: int,
    *,
    days_old: int = 100,
    branches: Sequence[str] = ("main",),
    in_use: bool = False,
    owner: str = "p1",
) -> VersionFacts:
    return VersionFacts(
        id=f"{owner}-{number}",
        pacticipant_id=owner,
        number=number,
        seq=seq,
        created_at=NOW - timedelta(days=days_old),
        branches=tuple(branches),
        in_use=in_use,
    )


def _deleted(versions: Sequence[VersionFacts], **keep: object) -> List[str]:
    plan, deletions = plan_retention(RetentionKeep(**keep), [BILLING], versions, now=NOW)
    return sorted(v.number for v in versions if v.id in set(deletions.get("p1", [])))


HISTORY = [
    _v("1", 1, in_use=True),
    _v("2", 2),
    _v("3", 3),
    _v("f-1", 4, branches=("feat/x",)),
    _v("4", 5, days_old=3),
    _v("5", 6, days_old=1),
]


def test_latest_per_branch_keeps_the_newest_n_of_each_branch() -> None:
    assert _deleted(HISTORY, latest_per_branch=2, deployed_or_released=False) == ["1", "2", "3"]
    assert _deleted(HISTORY, latest_per_branch=1, deployed_or_released=False) == ["1", "2", "3", "4"]


def test_deployed_or_released_is_on_by_default() -> None:
    assert _deleted(HISTORY, latest_per_branch=2) == ["2", "3"]


def test_created_within_days_keeps_the_recent_ones() -> None:
    assert _deleted(HISTORY, created_within_days=7, deployed_or_released=False) == ["1", "2", "3", "f-1"]


def test_the_latest_version_is_always_kept() -> None:
    # Only the deployed selector, and nothing deployed: everything but the latest goes.
    versions = [_v("1", 1), _v("2", 2), _v("3", 3, branches=())]
    assert _deleted(versions) == ["1", "2"]


def test_a_version_on_no_branch_is_only_kept_by_the_other_rules() -> None:
    versions = [_v("a", 1, branches=()), _v("b", 2, branches=(), days_old=1), _v("c", 3)]
    assert _deleted(versions, latest_per_branch=5, created_within_days=7, deployed_or_released=False) == ["a"]


def test_no_selector_is_refused() -> None:
    with pytest.raises(RetentionError) as caught:
        plan_retention(RetentionKeep(deployed_or_released=False), [BILLING], HISTORY, now=NOW)
    assert caught.value.code == CODE_NO_SELECTOR


def test_the_plan_counts_why_each_version_is_kept() -> None:
    plan, _ = plan_retention(RetentionKeep(latest_per_branch=2), [BILLING], HISTORY, now=NOW, grace_days=14)
    (row,) = plan.pacticipants
    assert row.kept_by == {"latest": 1, "latest_per_branch": 2, "deployed_or_released": 1}
    assert (row.evaluated, row.kept, row.deleted) == (6, 4, 2)
    assert [d.number for d in row.deletions] == ["2", "3"]
    assert (plan.dry_run, plan.applied, plan.grace_days) == (True, False, 14)


def test_the_cap_deletes_the_oldest_and_reports_the_rest() -> None:
    plan, deletions = plan_retention(
        RetentionKeep(deployed_or_released=True), [BILLING], HISTORY, now=NOW, max_deletions=2
    )
    assert plan.deleted == 2 and plan.remaining == 2
    assert sorted(deletions["p1"]) == ["p1-2", "p1-3"]
    assert plan.pacticipants[0].remaining == 2


def test_the_digest_is_stable_and_follows_the_plan() -> None:
    first, _ = plan_retention(RetentionKeep(latest_per_branch=2), [BILLING], HISTORY, now=NOW)
    again, _ = plan_retention(RetentionKeep(latest_per_branch=2), [BILLING], list(reversed(HISTORY)), now=NOW)
    assert first.plan_digest == again.plan_digest and first.plan_digest.startswith("sha256:")
    moved, _ = plan_retention(RetentionKeep(latest_per_branch=2), [BILLING], HISTORY + [_v("6", 7)], now=NOW)
    assert moved.plan_digest != first.plan_digest
    other_keep, _ = plan_retention(RetentionKeep(latest_per_branch=3), [BILLING], HISTORY, now=NOW)
    assert other_keep.plan_digest != first.plan_digest
    assert digest_of(RetentionKeep(latest_per_branch=1), ["b", "a"], ["y", "x"]) == digest_of(
        RetentionKeep(latest_per_branch=1), ["a", "b"], ["x", "y"]
    )


def test_each_pacticipant_is_planned_on_its_own() -> None:
    versions = HISTORY + [_v("l1", 10, owner="p2"), _v("l2", 11, owner="p2")]
    plan, deletions = plan_retention(
        RetentionKeep(latest_per_branch=1, deployed_or_released=False), [BILLING, LEDGER], versions, now=NOW
    )
    assert [row.slug for row in plan.pacticipants] == ["billing-service", "ledger-api"]
    assert deletions["p2"] == ["p2-l1"]
    # A pacticipant with no version is listed with zeros.
    empty, _ = plan_retention(RetentionKeep(latest_per_branch=1), [LEDGER], [], now=NOW)
    assert (empty.pacticipants[0].evaluated, empty.deleted) == (0, 0)


def test_the_answer_lists_a_bounded_number_of_deletions_but_counts_all() -> None:
    many = [_v(str(n), n, branches=()) for n in range(1, MAX_LISTED_PER_PACTICIPANT + 20)]
    plan, _ = plan_retention(RetentionKeep(), [BILLING], many, now=NOW)
    (row,) = plan.pacticipants
    assert row.deleted == len(many) - 1
    assert len(row.deletions) == MAX_LISTED_PER_PACTICIPANT


def test_the_request_model_bounds_its_selectors() -> None:
    with pytest.raises(ValidationError):
        RetentionKeep(latest_per_branch=0)
    with pytest.raises(ValidationError):
        RetentionKeep(created_within_days=5000)
    with pytest.raises(ValidationError):
        RetentionRequest(keep=RetentionKeep(), unknown=True)
    assert RetentionRequest(keep=RetentionKeep()).dry_run is True
