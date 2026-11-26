"""The decisions of stale-pact remediation and verification scheduling — PFX-6.2 (#6954).

:mod:`app.pact_remediation` is pure; these tests pin each rule:

* settings resolve pair → provider → workspace, value by value, with their sources;
* a pact is stale past its threshold, counted from its newest result, else its publication;
* an open request becomes republished, cleared or expired — in that order — or stays open;
* a request opens once per pact version since its last verification;
* the cadence decides when a pair is due, and a due pair without a target is reported once;
* the models refuse out-of-range values, unknown cadences and unknown fields.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.pact_remediation import (
    CADENCE_HOURLY,
    CADENCE_MANUAL,
    CADENCE_NIGHTLY,
    CADENCE_ON_PUBLISH,
    CADENCES,
    CODE_NO_TARGET,
    OPEN_STATES,
    REQUEST_STATES,
    SOURCE_PAIR,
    SOURCE_PROVIDER,
    SOURCE_WORKSPACE,
    STATE_CLEARED,
    STATE_EXPIRED,
    STATE_REPUBLISHED,
    AcknowledgeRequest,
    EffectiveSettings,
    OverrideInput,
    OverrideValues,
    PairFacts,
    RequestFacts,
    VerificationSettingsInput,
    decide_request,
    decide_schedule,
    default_settings,
    is_stale,
    reference_time,
    resolve_settings,
    should_open_request,
)

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
SHA = "a" * 64
OTHER_SHA = "b" * 64


def _hours_ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def _effective(cadence: str = CADENCE_ON_PUBLISH, target: str | None = "ledger-staging") -> EffectiveSettings:
    return EffectiveSettings(
        cadence=cadence,
        cadence_source=SOURCE_WORKSPACE,
        stale_threshold_hours=72,
        stale_threshold_source=SOURCE_WORKSPACE,
        target=target,
        target_source=SOURCE_PROVIDER if target else None,
    )


# ---------------------------------------------------------------------------
# Vocabulary and settings
# ---------------------------------------------------------------------------


def test_the_vocabulary_matches_the_migration() -> None:
    assert CADENCES == ("on-publish", "hourly", "nightly", "manual-only")
    assert REQUEST_STATES == ("requested", "acknowledged", "republished", "cleared", "expired")
    assert OPEN_STATES == ("requested", "acknowledged")


def test_the_defaults_run_nothing_and_stale_after_three_days() -> None:
    settings = default_settings()
    assert settings.cadence == CADENCE_MANUAL and settings.customised is False
    assert (settings.stale_threshold_hours, settings.max_concurrent_runs, settings.request_window_hours) == (72, 2, 72)
    assert settings.republish_requests_enabled is True


def test_settings_resolve_pair_over_provider_over_workspace_value_by_value() -> None:
    workspace = default_settings()
    provider = OverrideValues(cadence=CADENCE_NIGHTLY, target="ledger-staging")
    pair = OverrideValues(stale_threshold_hours=24)
    effective = resolve_settings(workspace, provider, pair)
    assert (effective.cadence, effective.cadence_source) == (CADENCE_NIGHTLY, SOURCE_PROVIDER)
    assert (effective.stale_threshold_hours, effective.stale_threshold_source) == (24, SOURCE_PAIR)
    assert (effective.target, effective.target_source) == ("ledger-staging", SOURCE_PROVIDER)

    overriding = resolve_settings(workspace, provider, OverrideValues(cadence=CADENCE_HOURLY, target="ledger-prod"))
    assert (overriding.cadence, overriding.cadence_source) == (CADENCE_HOURLY, SOURCE_PAIR)
    assert (overriding.target, overriding.target_source) == ("ledger-prod", SOURCE_PAIR)
    assert overriding.stale_threshold_source == SOURCE_WORKSPACE


def test_without_overrides_the_workspace_applies_and_there_is_no_target() -> None:
    effective = resolve_settings(default_settings())
    assert effective.cadence_source == effective.stale_threshold_source == SOURCE_WORKSPACE
    assert effective.target is None and effective.target_source is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("cadence", "weekly"),
        ("stale_threshold_hours", 0),
        ("stale_threshold_hours", 2161),
        ("max_concurrent_runs", 0),
        ("max_concurrent_runs", 11),
        ("request_window_hours", 0),
        ("request_window_hours", 721),
    ],
)
def test_settings_refuse_out_of_range_values(field: str, value: object) -> None:
    body = {
        "cadence": "nightly",
        "stale_threshold_hours": 72,
        "max_concurrent_runs": 2,
        "request_window_hours": 72,
        "republish_requests_enabled": True,
        field: value,
    }
    with pytest.raises(ValidationError) as caught:
        VerificationSettingsInput(**body)
    assert caught.value.errors()[0]["loc"] == (field,)


def test_settings_and_overrides_refuse_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        OverrideInput(provider="ledger-api", cadence="hourly", colour="blue")
    with pytest.raises(ValidationError):
        OverrideInput(provider="ledger-api", cadence="fortnightly")
    with pytest.raises(ValidationError):
        AcknowledgeRequest(note="x" * 1001)


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def test_the_threshold_counts_from_the_newest_result_else_the_publication() -> None:
    assert reference_time(_hours_ago(5), _hours_ago(100)) == _hours_ago(5)
    assert reference_time(None, _hours_ago(100)) == _hours_ago(100)
    assert reference_time(None, None) is None
    naive = datetime(2026, 11, 26, 11, 0)
    assert reference_time(naive, None).tzinfo == timezone.utc


def test_a_pact_is_stale_only_past_its_threshold() -> None:
    assert is_stale(_hours_ago(73), 72, NOW) is True
    assert is_stale(_hours_ago(72), 72, NOW) is False
    assert is_stale(_hours_ago(1), 72, NOW) is False
    assert is_stale(None, 72, NOW) is False


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


def _open(sha: str = SHA, requested: float = 10, expires_in: float = 62) -> RequestFacts:
    return RequestFacts(sha=sha, requested_at=_hours_ago(requested), expires_at=NOW + timedelta(hours=expires_in))


def _pair(sha: str = SHA, published: float = 100, verified: float | None = None) -> PairFacts:
    return PairFacts(
        sha=sha,
        consumer_version="1.4.0",
        published_at=_hours_ago(published),
        last_verified_at=_hours_ago(verified) if verified is not None else None,
    )


def test_a_newer_publication_republishes_the_request_even_with_new_content() -> None:
    assert decide_request(_open(), _pair(published=1), True, NOW) == STATE_REPUBLISHED
    assert decide_request(_open(), _pair(sha=OTHER_SHA, published=1), False, NOW) == STATE_REPUBLISHED


def test_a_verification_meanwhile_clears_the_request() -> None:
    assert decide_request(_open(), _pair(verified=1), False, NOW) == STATE_CLEARED


def test_a_request_past_its_window_expires_and_one_within_it_stays_open() -> None:
    assert decide_request(_open(expires_in=-1), _pair(), True, NOW) == STATE_EXPIRED
    assert decide_request(_open(expires_in=0), _pair(), True, NOW) == STATE_EXPIRED
    assert decide_request(_open(), _pair(), True, NOW) is None


def test_republishing_wins_over_expiry() -> None:
    assert decide_request(_open(expires_in=-5), _pair(published=1), True, NOW) == STATE_REPUBLISHED


@pytest.mark.parametrize(
    "stale,enabled,has_open,last_request,last_verified,expected",
    [
        (True, True, False, None, None, True),
        (False, True, False, None, None, False),
        (True, False, False, None, None, False),
        (True, True, True, None, None, False),
        # Asked already for this pact version, never verified since: not again.
        (True, True, False, 20, None, False),
        (True, True, False, 20, 30, False),
        # Verified after the last request, and stale again: ask again.
        (True, True, False, 200, 100, True),
    ],
)
def test_a_request_opens_once_per_pact_version_since_its_last_verification(
    stale: bool, enabled: bool, has_open: bool, last_request: float | None, last_verified: float | None, expected: bool
) -> None:
    assert (
        should_open_request(
            stale=stale,
            enabled=enabled,
            has_open_request=has_open,
            last_request_for_sha_at=_hours_ago(last_request) if last_request is not None else None,
            last_verified_at=_hours_ago(last_verified) if last_verified is not None else None,
        )
        is expected
    )


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


def _decide(effective: EffectiveSettings, **facts: object):
    values = {
        "sha": SHA,
        "has_result": False,
        "last_attempt_sha": None,
        "last_attempt_at": None,
        "last_verified_at": None,
        "now": NOW,
    }
    values.update(facts)
    return decide_schedule(effective, **values)


def test_manual_only_never_runs() -> None:
    assert _decide(_effective(CADENCE_MANUAL)).due is False
    assert _decide(_effective(CADENCE_MANUAL), has_result=False, last_attempt_sha=None).due is False


def test_on_publish_runs_a_new_pact_version_once() -> None:
    assert _decide(_effective()).due is True
    assert _decide(_effective(), last_attempt_sha=SHA, last_attempt_at=_hours_ago(1)).due is False
    assert _decide(_effective(), has_result=True, last_verified_at=_hours_ago(500)).due is False
    assert _decide(_effective(), last_attempt_sha=OTHER_SHA, last_attempt_at=_hours_ago(1)).due is True


@pytest.mark.parametrize("cadence,interval", [(CADENCE_HOURLY, 1), (CADENCE_NIGHTLY, 24)])
def test_periodic_cadences_rerun_after_their_interval(cadence: str, interval: int) -> None:
    effective = _effective(cadence)
    recent = {"has_result": True, "last_verified_at": _hours_ago(interval * 0.5)}
    assert _decide(effective, **recent).due is False
    assert _decide(effective, has_result=True, last_verified_at=_hours_ago(interval)).due is True
    # A recent attempt counts as recent, even if it did not verify.
    assert (
        _decide(
            effective,
            has_result=True,
            last_verified_at=_hours_ago(interval * 3),
            last_attempt_sha=SHA,
            last_attempt_at=_hours_ago(interval * 0.5),
        ).due
        is False
    )
    # A newly published pact version runs at once, as on-publish would.
    assert _decide(effective, last_attempt_sha=OTHER_SHA, last_attempt_at=_hours_ago(0.1)).due is True


def test_a_due_pair_without_a_target_is_reported_once_per_pact_version() -> None:
    decision = _decide(_effective(target=None))
    assert decision.due is True and decision.blocked_code == CODE_NO_TARGET
    assert "no verification target" in (decision.blocked_reason or "")
    again = _decide(
        _effective(CADENCE_HOURLY, target=None),
        last_attempt_sha=SHA,
        last_attempt_at=_hours_ago(5),
        last_attempt_code=CODE_NO_TARGET,
    )
    assert again.due is False


def test_adding_a_target_unblocks_a_pair_that_was_reported_without_one() -> None:
    decision = _decide(
        _effective(), last_attempt_sha=SHA, last_attempt_at=_hours_ago(1), last_attempt_code=CODE_NO_TARGET
    )
    assert decision.due is True and decision.blocked_code is None
