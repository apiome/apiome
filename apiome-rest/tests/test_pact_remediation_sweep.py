"""The stale-pact remediation and scheduling worker — PFX-6.2 (#6954).

:func:`app.pact_remediation_sweep.process_pact_remediation_sweep` against an in-memory store:

* a pair going stale (or fresh again) fires its event once, and records the state;
* a stale pact opens one re-publish request, notifies its consumer's owners (or records why nobody
  was), and fires ``contract_republish_requested``;
* an open request is republished, cleared, or expired and escalated to both parties;
* a due pair is verified on its cadence through the scheduled-run path, inside a concurrency slot;
  a pair that cannot run is recorded with its reason, never skipped silently; a busy one stays due;
* one provider's failure, a full slot pool and the kill switch are handled.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import pytest

from app.owner_routing import OwnerRecipients, OwnerTeam, RoutingOutcome
from app.pact_remediation import (
    CADENCE_MANUAL,
    CADENCE_ON_PUBLISH,
    CODE_NO_PROVIDER_VERSION,
    CODE_NO_TARGET,
    OverrideValues,
    RepublishRequestRecord,
    ScheduledAttempt,
    VerificationSettings,
    default_settings,
)
from app.pact_remediation_sweep import (
    STATUS_UNLINKED,
    ScheduledRun,
    broker_base_for,
    execute_scheduled_run,
    process_pact_remediation_sweep,
)
from app.pact_selectors import PactCandidate
from app.pact_verifier_service import PactVerifierError
from app.pact_webhook import (
    EVENT_BECAME_STALE,
    EVENT_NO_LONGER_STALE,
    EVENT_REPUBLISH_REQUEST_EXPIRED,
    EVENT_REPUBLISH_REQUESTED,
)
from app.pacticipant import PacticipantRecord
from app.verification_result import VerificationResultRecord

_SWEEP = "app.pact_remediation_sweep"
NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
TENANT = "11111111-1111-4111-8111-111111111111"
SHA = "a" * 64

PROVIDER = PacticipantRecord(id="p-1", tenant_id=TENANT, slug="ledger-api", name="Ledger API", project_id="proj-ledger")
CONSUMER = PacticipantRecord(
    id="c-1", tenant_id=TENANT, slug="billing-service", name="Billing Service", consumer_id="reg-billing"
)
LONE = PacticipantRecord(id="c-2", tenant_id=TENANT, slug="lone-app", name="Lone App")


def _candidate(consumer: PacticipantRecord = CONSUMER, *, published_hours_ago: float = 100, sha: str = SHA):
    return PactCandidate(
        consumer_id=consumer.id,
        consumer_slug=consumer.slug,
        consumer_name=consumer.name,
        consumer_main_branch="main",
        version_id=f"v-{consumer.id}",
        version_number="1.4.0",
        version_seq=3,
        sha=sha,
        published_at=NOW - timedelta(hours=published_hours_ago),
    )


def _result(*, hours_ago: float, success: bool = True) -> VerificationResultRecord:
    return VerificationResultRecord(
        id="r-1",
        number=1,
        consumer_slug=CONSUMER.slug,
        consumer_name=CONSUMER.name,
        provider_slug=PROVIDER.slug,
        provider_name=PROVIDER.name,
        provider_version="4f1e2d0",
        provider_branch="main",
        consumer_version="1.4.0",
        sha=SHA,
        success=success,
        test_results=[],
        created_at=(NOW - timedelta(hours=hours_ago)).isoformat(),
    )


def _request(*, requested_hours_ago: float = 10, expires_in_hours: float = 62) -> RepublishRequestRecord:
    return RepublishRequestRecord(
        id="req-1",
        provider=PROVIDER.slug,
        provider_name=PROVIDER.name,
        consumer=CONSUMER.slug,
        consumer_name=CONSUMER.name,
        pact_version_sha=SHA,
        consumer_version="1.4.0",
        state="requested",
        threshold_hours=72,
        requested_at=(NOW - timedelta(hours=requested_hours_ago)).isoformat(),
        expires_at=(NOW + timedelta(hours=expires_in_hours)).isoformat(),
    )


class _Lock:
    """An advisory lock that is free unless its key is listed as busy."""

    def __init__(self, busy: set, key: str) -> None:
        self.busy, self.key, self.held = busy, key, False

    def acquire(self) -> bool:
        self.held = self.key not in self.busy
        return self.held

    def release(self) -> None:
        self.held = False


@dataclass
class _Store:
    """The state the sweep reads and the writes it makes."""

    candidates: List[PactCandidate] = field(default_factory=lambda: [_candidate()])
    results: Dict[Tuple[str, str], VerificationResultRecord] = field(default_factory=dict)
    settings: VerificationSettings = field(default_factory=default_settings)
    provider_override: Optional[OverrideValues] = None
    pair_overrides: Dict[str, OverrideValues] = field(default_factory=dict)
    staleness: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    requests: Dict[str, RepublishRequestRecord] = field(default_factory=dict)
    attempts: Dict[str, ScheduledAttempt] = field(default_factory=dict)
    last_request_at: Optional[datetime] = None
    provider_history: List[VerificationResultRecord] = field(default_factory=list)
    routing: str = "routed"
    #: Confirmed owner teams by (kind, id); the 6.2 bindings are owned by default (PFX-6.4).
    owners: Dict[Tuple[str, str], str] = field(
        default_factory=lambda: {("consumer", "reg-billing"): "t-billing", ("project", "proj-ledger"): "t-ledger"}
    )
    events: List[str] = field(default_factory=list)
    upserts: List[Dict[str, Any]] = field(default_factory=list)
    opened: List[Dict[str, Any]] = field(default_factory=list)
    closed: List[Tuple[str, str]] = field(default_factory=list)
    notifications: List[Tuple[str, Optional[str], int]] = field(default_factory=list)
    escalations: List[Tuple[str, Optional[str], int]] = field(default_factory=list)
    findings: List[Any] = field(default_factory=list)
    recorded: List[Dict[str, Any]] = field(default_factory=list)
    busy: set = field(default_factory=set)
    providers: List[Tuple[str, str, str]] = field(default_factory=lambda: [(TENANT, "acme", PROVIDER.id)])

    def patches(self) -> ExitStack:
        stack = ExitStack()
        lookup = {PROVIDER.id: PROVIDER, CONSUMER.id: CONSUMER, LONE.id: LONE}

        def fire(_db: Any, _tenant: str, _base: str, event: str, **_kwargs: Any) -> List[str]:
            self.events.append(event)
            return ["delivery-1"]

        def route(_db: Any, finding: Any) -> RoutingOutcome:
            self.findings.append(finding)
            return RoutingOutcome(status=self.routing)

        def owner(_db: Any, _t: str, kind: str, entity_id: str) -> Any:
            team = self.owners.get((kind, entity_id))
            return None if team is None else OwnerRecipients(team=OwnerTeam(id=team, slug=team, name=team))

        def open_request(_db: Any, _t: str, _p: str, consumer_id: str, **values: Any) -> Optional[str]:
            self.opened.append({"consumer_id": consumer_id, **values})
            return "req-new"

        def close(_db: Any, _t: str, request_id: str, state: str, **_kw: Any) -> bool:
            self.closed.append((request_id, state))
            return True

        def record(_db: Any, _t: str, _p: str, consumer_id: str, **values: Any) -> None:
            self.recorded.append({"consumer_id": consumer_id, **values})

        replacements = {
            f"{_SWEEP}.providers_with_pacts": lambda _db, limit: self.providers,
            f"{_SWEEP}.get_settings": lambda _db, _t: self.settings,
            "app.pact_verification_ops.latest_pacts": lambda _db, _t, _p: (PROVIDER, self.candidates),
            "app.verification_result_store.latest_results_by_pact": lambda *_a: self.results,
            "app.verification_result_store.list_provider_results": lambda *_a, **_k: (self.provider_history, None),
            f"{_SWEEP}.override_values_for_provider": lambda *_a: (self.provider_override, self.pair_overrides),
            f"{_SWEEP}.staleness_for_provider": lambda *_a: self.staleness,
            f"{_SWEEP}.open_requests_for_provider": lambda *_a: self.requests,
            f"{_SWEEP}.attempts_for_provider": lambda *_a: self.attempts,
            f"{_SWEEP}.upsert_staleness": lambda _db, _t, _p, cid, **v: self.upserts.append({"consumer_id": cid, **v}),
            f"{_SWEEP}.latest_request_at_for_sha": lambda *_a: self.last_request_at,
            f"{_SWEEP}.open_request": open_request,
            f"{_SWEEP}.close_request": close,
            f"{_SWEEP}.set_notification_status": lambda _db, _t, rid, s, d: self.notifications.append((rid, s, d)),
            f"{_SWEEP}.set_escalation_status": lambda _db, _t, rid, s, d: self.escalations.append((rid, s, d)),
            f"{_SWEEP}.record_attempt": record,
            f"{_SWEEP}.get_pacticipant": lambda _db, _t, ref: lookup[ref],
            "app.pact_owner_routing.route_owner_finding_safely": route,
            "app.pact_owner_routing.owner_recipients": owner,
            f"{_SWEEP}.fire_remediation_event": fire,
        }
        for target, replacement in replacements.items():
            stack.enter_context(patch(target, side_effect=replacement))
        return stack

    def lock(self, _db: Any, key: str) -> _Lock:
        return _Lock(self.busy, key)

    def sweep(self, verify: Any = None):
        with self.patches():
            return process_pact_remediation_sweep(None, now=NOW, lock_factory=self.lock, verify=verify)


# ---------------------------------------------------------------------------
# Stale state
# ---------------------------------------------------------------------------


def test_a_pact_past_its_threshold_becomes_stale_once_and_is_recorded() -> None:
    store = _Store()
    counts = store.sweep()
    assert counts.became_stale == 1 and counts.providers == 1
    assert store.events[0] == EVENT_BECAME_STALE
    (upsert,) = store.upserts
    assert upsert["stale"] is True and upsert["sha"] == SHA and upsert["threshold_hours"] == 72

    store = _Store(staleness={CONSUMER.id: {"stale": True}}, requests={CONSUMER.id: _request()})
    store.sweep()
    assert EVENT_BECAME_STALE not in store.events


def test_a_verified_pact_is_no_longer_stale_and_its_request_is_cleared() -> None:
    store = _Store(
        results={(CONSUMER.id, SHA): _result(hours_ago=1)},
        staleness={CONSUMER.id: {"stale": True}},
        requests={CONSUMER.id: _request()},
    )
    counts = store.sweep()
    assert store.events == [EVENT_NO_LONGER_STALE]
    assert store.closed == [("req-1", "cleared")]
    assert counts.no_longer_stale == 1 and counts.requests_closed == {"cleared": 1}


def test_a_fresh_pact_seen_for_the_first_time_fires_nothing() -> None:
    store = _Store(candidates=[_candidate(published_hours_ago=1)])
    store.sweep()
    assert store.events == [] and store.opened == []
    assert store.upserts[0]["stale"] is False


def test_a_pair_override_threshold_applies() -> None:
    store = _Store(
        candidates=[_candidate(published_hours_ago=30)],
        pair_overrides={CONSUMER.id: OverrideValues(stale_threshold_hours=24)},
    )
    store.sweep()
    assert store.upserts[0]["stale"] is True and store.upserts[0]["threshold_hours"] == 24


# ---------------------------------------------------------------------------
# Re-publish requests
# ---------------------------------------------------------------------------


def test_a_stale_pact_opens_a_request_and_notifies_the_consumers_owners() -> None:
    store = _Store()
    counts = store.sweep()
    assert counts.requests_opened == 1
    (opened,) = store.opened
    assert (opened["sha"], opened["consumer_version"], opened["window_hours"]) == (SHA, "1.4.0", 72)
    (finding,) = store.findings
    assert (finding.entity_kind, finding.entity_id) == ("consumer", "reg-billing")
    assert finding.finding_type == "owner_verification_drift"
    assert finding.details["pactVersionSha"] == SHA and finding.details["requestId"] == "req-new"
    assert finding.link == "/ade/dashboard/pacts/pacticipants/ledger-api/verification"
    assert EVENT_REPUBLISH_REQUESTED in store.events
    assert store.notifications == [("req-new", "routed", 1)]


def test_an_ownerless_consumer_is_routed_under_itself_as_unowned() -> None:
    # PFX-6.4: no owner anywhere is no longer `unlinked`; the finding is recorded as unowned under
    # the pacticipant (owner routing's Unowned findings report or catch-all team).
    store = _Store(candidates=[_candidate(LONE)], routing="unowned")
    store.sweep()
    (finding,) = store.findings
    assert (finding.entity_kind, finding.entity_id) == ("pacticipant", LONE.id)
    assert finding.details["ownerSource"] == "pacticipant" and finding.details["pacticipant"] == "lone-app"
    assert store.notifications == [("req-new", "unowned", 1)]
    assert STATUS_UNLINKED not in [status for _rid, status, _d in store.notifications]


def test_the_consumer_pacticipants_own_owner_wins_over_its_binding() -> None:
    store = _Store(owners={("pacticipant", CONSUMER.id): "t-checkout", ("consumer", "reg-billing"): "t-billing"})
    store.sweep()
    (finding,) = store.findings
    assert (finding.entity_kind, finding.entity_id) == ("pacticipant", CONSUMER.id)
    assert finding.details["ownerSource"] == "pacticipant"


def test_a_routing_failure_is_recorded_as_failed() -> None:
    store = _Store(routing="skipped")
    store.sweep()
    assert store.notifications == [("req-new", "failed", 1)]


def test_requests_can_be_turned_off() -> None:
    store = _Store(settings=default_settings().model_copy(update={"republish_requests_enabled": False}))
    store.sweep()
    assert store.opened == [] and store.events == [EVENT_BECAME_STALE]


def test_an_expired_pact_version_is_not_asked_again_until_it_is_verified() -> None:
    store = _Store(staleness={CONSUMER.id: {"stale": True}}, last_request_at=NOW - timedelta(hours=5))
    store.sweep()
    assert store.opened == []


def test_a_request_past_its_window_expires_and_escalates_to_both_parties() -> None:
    store = _Store(
        staleness={CONSUMER.id: {"stale": True}},
        requests={CONSUMER.id: _request(requested_hours_ago=80, expires_in_hours=-8)},
        last_request_at=NOW - timedelta(hours=80),
    )
    counts = store.sweep()
    assert store.closed == [("req-1", "expired")]
    assert counts.requests_closed == {"expired": 1}
    assert [(f.entity_kind, f.entity_id) for f in store.findings] == [
        ("consumer", "reg-billing"),
        ("project", "proj-ledger"),
    ]
    assert all(f.details["escalated"] for f in store.findings)
    assert store.events == [EVENT_REPUBLISH_REQUEST_EXPIRED]
    assert store.escalations == [("req-1", "routed", 1)]
    # The same pact version is not asked again.
    assert store.opened == []


def test_a_newer_publication_republishes_the_open_request() -> None:
    store = _Store(
        candidates=[_candidate(published_hours_ago=1)],
        staleness={CONSUMER.id: {"stale": True}},
        requests={CONSUMER.id: _request()},
    )
    store.sweep()
    assert store.closed == [("req-1", "republished")]


def test_an_open_request_within_its_window_stays_open() -> None:
    store = _Store(staleness={CONSUMER.id: {"stale": True}}, requests={CONSUMER.id: _request()})
    store.sweep()
    assert store.closed == [] and store.opened == []


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


def _scheduled(**changes: Any) -> _Store:
    on_publish = default_settings().model_copy(update={"cadence": CADENCE_ON_PUBLISH})
    values: Dict[str, Any] = {
        "candidates": [_candidate(published_hours_ago=1)],
        "settings": on_publish,
        "provider_override": OverrideValues(target="ledger-staging"),
        "provider_history": [_result(hours_ago=50)],
    }
    values.update(changes)
    return _Store(**values)


@dataclass
class _Run:
    pacts: List[Any]
    skipped: List[Any]
    success: bool
    outcome: str


def test_a_due_pair_is_verified_as_the_providers_newest_version_in_a_slot() -> None:
    store = _scheduled()
    calls: List[Dict[str, Any]] = []

    def verify(_db: Any, tenant: str, provider: Any, candidate: Any, **kwargs: Any) -> _Run:
        calls.append({"tenant": tenant, "provider": provider.slug, "consumer": candidate.consumer_slug, **kwargs})
        return _Run(pacts=[object()], skipped=[], success=True, outcome="passed")

    counts = store.sweep(verify)
    (call,) = calls
    assert (call["target_ref"], call["provider_version"], call["provider_branch"]) == (
        "ledger-staging",
        "4f1e2d0",
        "main",
    )
    assert call["broker_base"].endswith("/v1/tenants/acme/pact-broker")
    assert counts.scheduled_runs == 1
    assert store.recorded == [
        {"consumer_id": CONSUMER.id, "sha": SHA, "status": "verified", "code": None, "reason": None}
    ]


def test_a_failed_run_is_recorded_failed() -> None:
    store = _scheduled()
    store.sweep(lambda *_a, **_k: _Run(pacts=[object()], skipped=[], success=False, outcome="failed"))
    assert store.recorded[0]["status"] == "failed"


def test_manual_only_runs_nothing() -> None:
    store = _scheduled(settings=default_settings().model_copy(update={"cadence": CADENCE_MANUAL}))
    store.sweep(lambda *_a, **_k: pytest.fail("manual-only ran a verification"))
    assert store.recorded == []


def test_a_due_pair_without_a_target_is_recorded_with_the_reason() -> None:
    store = _scheduled(provider_override=None)
    counts = store.sweep(lambda *_a, **_k: pytest.fail("ran without a target"))
    (recorded,) = store.recorded
    assert (recorded["status"], recorded["code"]) == ("skipped", CODE_NO_TARGET)
    assert counts.scheduled_recorded_skips == 1


def test_a_due_pair_with_no_known_provider_version_is_recorded_with_the_reason() -> None:
    store = _scheduled(provider_history=[])
    store.sweep(lambda *_a, **_k: pytest.fail("ran without a provider version"))
    (recorded,) = store.recorded
    assert (recorded["status"], recorded["code"]) == ("skipped", CODE_NO_PROVIDER_VERSION)


def test_a_refused_run_is_recorded_errored_with_the_verifiers_code() -> None:
    def refuse(*_a: Any, **_k: Any) -> Any:
        raise PactVerifierError("pact-verify-target-auth-unavailable", "the target's credential is gone")

    store = _scheduled()
    store.sweep(refuse)
    (recorded,) = store.recorded
    assert (recorded["status"], recorded["code"]) == ("errored", "pact-verify-target-auth-unavailable")


def test_an_unexpected_failure_is_recorded_and_does_not_stop_the_tick() -> None:
    store = _scheduled()
    store.sweep(lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert store.recorded[0]["status"] == "errored" and store.recorded[0]["code"] == "INTERNAL_ERROR"


def test_a_busy_pair_stays_due_and_records_nothing() -> None:
    store = _scheduled()
    counts = store.sweep(lambda *_a, **_k: _Run(pacts=[], skipped=[object()], success=False, outcome="no-pacts"))
    assert store.recorded == [] and counts.scheduled_runs == 0


def test_a_workspace_with_every_slot_taken_waits_for_the_next_tick() -> None:
    store = _scheduled(busy={f"apiome.pact_schedule_slot:{TENANT}:0", f"apiome.pact_schedule_slot:{TENANT}:1"})
    counts = store.sweep(lambda *_a, **_k: pytest.fail("ran without a slot"))
    assert counts.scheduled_runs == 0 and store.recorded == []


def test_the_batch_bounds_the_runs_of_one_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "pact_schedule_batch_size", 1)
    store = _scheduled(candidates=[_candidate(published_hours_ago=1), _candidate(LONE, published_hours_ago=1)])
    ran: List[str] = []

    def verify(_db: Any, _t: str, _p: Any, candidate: Any, **_k: Any) -> _Run:
        ran.append(candidate.consumer_slug)
        return _Run(pacts=[object()], skipped=[], success=True, outcome="passed")

    store.sweep(verify)
    assert ran == ["billing-service"]


# ---------------------------------------------------------------------------
# The tick
# ---------------------------------------------------------------------------


def test_the_kill_switch_halts_the_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "pact_remediation_enabled", False)
    store = _Store()
    counts = store.sweep()
    assert counts.providers == 0 and store.upserts == []


def test_one_failing_provider_does_not_stop_the_others() -> None:
    store = _Store(providers=[(TENANT, "acme", "broken"), (TENANT, "acme", PROVIDER.id)])
    real = store.patches

    def patches() -> ExitStack:
        stack = real()

        def latest(_db: Any, _t: str, provider_id: str):
            if provider_id == "broken":
                raise RuntimeError("unreadable")
            return PROVIDER, store.candidates

        stack.enter_context(patch("app.pact_verification_ops.latest_pacts", side_effect=latest))
        return stack

    store.patches = patches  # type: ignore[method-assign]
    counts = store.sweep()
    assert counts.providers == 1 and counts.became_stale == 1


def test_links_use_the_public_api_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "api_public_url", "https://api.example.test/")
    assert broker_base_for("acme corp") == "https://api.example.test/v1/tenants/acme%20corp/pact-broker"


def test_execute_reports_no_provider_version_without_running() -> None:
    from app.pact_remediation import resolve_settings

    run = ScheduledRun(TENANT, "acme", PROVIDER, _candidate(), resolve_settings(default_settings()), None, None)
    recorded: List[Dict[str, Any]] = []
    with patch(f"{_SWEEP}.record_attempt", side_effect=lambda *_a, **k: recorded.append(k)):
        status = execute_scheduled_run(None, run, verify=lambda *_a, **_k: pytest.fail("ran"))
    assert status == "skipped" and recorded[0]["code"] == CODE_NO_PROVIDER_VERSION
