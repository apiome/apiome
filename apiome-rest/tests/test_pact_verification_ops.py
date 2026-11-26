"""Verification results and operations, with every store faked — PFX-5.5 (#6949).

:mod:`app.pact_verification_ops` on top of the hosted verifier's fakes
(:class:`tests.test_pact_verifier_service._Broker`), replayed on the real runner:

* the status marks each consumer's newest pact stale when its pact version has no result, and
  counts the KPI strip;
* the history pages by an opaque cursor; a cursor it did not hand out is refused;
* one result carries its evidence run, or says why not (not recorded, forbidden, pruned);
* **Re-run** verifies one pact version as the newest result's provider version unless told
  otherwise, records ``trigger: manual`` with the duration and the evidence run, and refuses a
  pair that is already running;
* **Verify all stale** verifies only stale pacts, ``trigger: stale-recheck``; a busy pair and the
  pacts past the per-run limit are listed with reasons, never dropped;
* the hosted verifier now records ``trigger: hosted`` too.
"""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any, Dict, List, Optional, Set, Tuple
from unittest.mock import patch

import pytest

from app.pact_pending import NO_EVIDENCE
from app.pact_publication import CODE_PACT_NOT_FOUND, PactPublicationError
from app.pact_verification_ops import (
    CODE_CURSOR_INVALID,
    CODE_IN_PROGRESS,
    CODE_NO_PROVIDER_VERSION,
    CODE_OVER_LIMIT,
    EVIDENCE_ATTACHED,
    EVIDENCE_FORBIDDEN,
    EVIDENCE_NOT_FOUND,
    EVIDENCE_NOT_RECORDED,
    ConsoleRunRequest,
    ConsoleRunResponse,
    decode_cursor,
    list_results,
    read_result,
    reverify_pact,
    summarise,
    verification_status,
    verify_stale_pacts,
)
from app.pact_verifier import PactVerificationOptions
from app.pacticipant import PacticipantRecord, PacticipantValidationError
from app.verification_evidence import EvidenceValidationError
from app.verification_result import VerificationResultRecord
from tests.pact_verifier_fakes import PACT_GO, PACT_JS, PACT_JVM, LedgerApi, target
from tests.test_pact_verifier_service import _ACTOR, _BASE, _PROVIDER, _TENANT, _Broker, _verify

_OPS = "app.pact_verification_ops"
_SERVICE = "app.pact_verifier_service"
_EVERYTHING = PactVerificationOptions(allow_mutating=True, replay_without_state_setup=True)


class _Locks:
    """Per-pair locks: the keys listed in ``busy`` are held by another run."""

    def __init__(self, busy: Set[str] = frozenset()) -> None:  # type: ignore[assignment]
        self.busy = set(busy)
        self.taken: List[str] = []
        self.released: List[str] = []

    def __call__(self, _db: Any, key: str) -> "_Locks._Lock":
        return _Locks._Lock(self, key)

    class _Lock:
        def __init__(self, owner: "_Locks", key: str) -> None:
            self.owner, self.key = owner, key

        def acquire(self) -> bool:
            if any(self.key.endswith(f":{consumer_id}") for consumer_id in self.owner.busy):
                return False
            self.owner.taken.append(self.key)
            return True

        def release(self) -> None:
            self.owner.released.append(self.key)


def _result(
    consumer: str = "billing-service",
    sha: str = "a" * 64,
    *,
    success: bool = True,
    provider_version: str = "1a2b3c4",
    branch: Optional[str] = "main",
    evidence_run_id: Optional[str] = None,
    created_at: str = "2026-11-24T10:00:00+00:00",
    seq: int = 7,
) -> VerificationResultRecord:
    return VerificationResultRecord(
        id="44444444-4444-4444-8444-444444444444",
        number=2,
        consumer_slug=consumer,
        consumer_name=consumer.replace("-", " ").title(),
        provider_slug="ledger-api",
        provider_name="Ledger API",
        provider_version=provider_version,
        provider_branch=branch,
        consumer_version="1.0.0",
        sha=sha,
        success=success,
        test_results=[
            {"interactionDescription": "a request for an invoice", "success": True},
            {
                "interactionDescription": "a request for the summary",
                "success": False,
                "mismatches": [{"attribute": "body", "identifier": "/year", "expected": 2026, "actual": "2026"}],
            },
        ],
        verified_by={"implementation": "apiome-pact-verifier", "version": "1"},
        trigger="hosted",
        duration_ms=1840,
        evidence_run_id=evidence_run_id,
        created_at=created_at,
        seq=seq,
    )


def _run(
    broker: _Broker,
    api: LedgerApi,
    call: Any,
    *,
    results: Optional[Dict[Tuple[str, str], VerificationResultRecord]] = None,
    locks: Optional[_Locks] = None,
) -> ConsoleRunResponse:
    """Run a console operation with the hosted verifier's stores faked."""
    client = api.client()
    with ExitStack() as stack:
        for module, name, fake in (
            (_SERVICE, "get_pact_by_sha", broker.get_pact_by_sha),
            (_SERVICE, "publish_verification_result", broker.publish),
            (_SERVICE, "record_run", broker.record_run),
            (_SERVICE, "fire_verification_events", broker.fire),
            (_OPS, "list_pact_candidates", broker.list_pact_candidates),
            (_OPS, "record_broker_version", broker.record_branch),
        ):
            stack.enter_context(patch(f"{module}.{name}", side_effect=fake))
        stack.enter_context(patch(f"{_OPS}.get_pacticipant", side_effect=_pacticipant(broker)))
        stack.enter_context(patch(f"{_OPS}.latest_results_by_pact", return_value=dict(results or {})))
        stack.enter_context(patch(f"{_OPS}.load_pending_evidence", return_value=NO_EVIDENCE))
        stack.enter_context(patch(f"{_SERVICE}.list_states", return_value=[]))
        stack.enter_context(
            patch(f"{_SERVICE}.resolve_target", side_effect=lambda *a, **k: target(allow_mutating=True))
        )
        stack.enter_context(patch("app.contract_runner.build_guarded_client", side_effect=lambda **_k: api.client()))
        try:
            return call(locks or _Locks())
        finally:
            client.close()


def _pacticipant(broker: _Broker) -> Any:
    """``get_pacticipant`` over the broker's consumers and the provider."""

    def lookup(_db: Any, tenant_id: str, ref: str) -> PacticipantRecord:
        assert tenant_id == _TENANT
        if ref == "ledger-api":
            return _PROVIDER
        for candidate in broker.candidates:
            if candidate.consumer_slug == ref:
                return PacticipantRecord(
                    id=candidate.consumer_id, tenant_id=_TENANT, slug=ref, name=candidate.consumer_name
                )
        raise PacticipantValidationError("pacticipant-not-found", f"no pacticipant '{ref}'")

    return lookup


def _body(**fields: Any) -> ConsoleRunRequest:
    return ConsoleRunRequest(**{"target_ref": "ledger-staging", "verification": _EVERYTHING, **fields})


def _candidate(broker: _Broker, slug: str) -> Any:
    return next(c for c in broker.candidates if c.consumer_slug == slug)


# ---------------------------------------------------------------------------
# Re-run
# ---------------------------------------------------------------------------


def test_a_rerun_verifies_one_pact_and_records_manual_duration_and_evidence() -> None:
    broker, api = _Broker([PACT_JS, PACT_JVM]), LedgerApi()
    pact = _candidate(broker, "billing-service")
    locks = _Locks()
    response = _run(
        broker,
        api,
        lambda lk: reverify_pact(
            None,
            _TENANT,
            "ledger-api",
            "billing-service",
            pact.sha.upper(),
            _body(provider_version="9f8e7d6", provider_branch="main"),
            actor=_ACTOR,
            broker_base=_BASE,
            lock_factory=lk,
        ),
        locks=locks,
    )
    assert response.trigger == "manual" and response.skipped == []
    assert (response.success, response.outcome, response.provider_version) == (True, "passed", "9f8e7d6")
    (verified,) = response.pacts
    assert verified.consumer == "billing-service" and verified.pact_version_sha == pact.sha
    assert verified.short_description == f"re-run of {pact.consumer_name} version {pact.version_number}"
    (stored,) = broker.published
    assert stored["trigger"] == "manual"
    assert isinstance(stored["duration_ms"], int) and stored["duration_ms"] >= 0
    assert stored["evidence_run_id"] == "run-1"
    assert stored["request"].provider_version == "9f8e7d6"
    assert broker.branch_versions == [("ledger-api", "9f8e7d6", "main")]
    # The pair's lock was taken and given back.
    assert locks.taken == locks.released == [f"apiome.pact_verify:{_TENANT}:p-ledger:{pact.consumer_id}"]


def test_a_rerun_defaults_to_the_provider_version_and_branch_of_the_newest_result() -> None:
    broker, api = _Broker([PACT_JS]), LedgerApi()
    pact = broker.candidates[0]
    newest = _result(pact.consumer_slug, pact.sha, provider_version="1a2b3c4", branch="release")
    response = _run(
        broker,
        api,
        lambda lk: reverify_pact(
            None,
            _TENANT,
            "ledger-api",
            pact.consumer_slug,
            pact.sha,
            _body(),
            actor=_ACTOR,
            broker_base=_BASE,
            lock_factory=lk,
        ),
        results={(pact.consumer_id, pact.sha): newest},
    )
    assert (response.provider_version, response.provider_branch) == ("1a2b3c4", "release")
    assert broker.published[0]["request"].provider_version == "1a2b3c4"


def test_a_rerun_without_a_version_or_a_result_says_which_field_to_give() -> None:
    broker = _Broker([PACT_JS])
    pact = broker.candidates[0]
    with pytest.raises(Exception) as caught:
        _run(
            broker,
            LedgerApi(),
            lambda lk: reverify_pact(
                None, _TENANT, "ledger-api", pact.consumer_slug, pact.sha, _body(), actor=_ACTOR, broker_base=_BASE
            ),
        )
    assert getattr(caught.value, "code", None) == CODE_NO_PROVIDER_VERSION
    assert "provider_version" in str(caught.value)
    assert broker.published == []


def test_a_rerun_of_a_pact_version_the_pair_does_not_have_is_not_found() -> None:
    broker = _Broker([PACT_JS, PACT_JVM])
    other = _candidate(broker, "orders-ui")
    with pytest.raises(PactPublicationError) as caught:
        _run(
            broker,
            LedgerApi(),
            lambda lk: reverify_pact(
                None,
                _TENANT,
                "ledger-api",
                "billing-service",
                other.sha,  # orders-ui's pact, not billing-service's
                _body(provider_version="9f8e7d6"),
                actor=_ACTOR,
                broker_base=_BASE,
            ),
        )
    assert caught.value.code == CODE_PACT_NOT_FOUND


def test_a_rerun_of_a_pair_already_running_is_refused_before_anything_is_sent() -> None:
    broker, api = _Broker([PACT_JS]), LedgerApi()
    pact = broker.candidates[0]
    with pytest.raises(Exception) as caught:
        _run(
            broker,
            api,
            lambda lk: reverify_pact(
                None,
                _TENANT,
                "ledger-api",
                pact.consumer_slug,
                pact.sha,
                _body(provider_version="9f8e7d6"),
                actor=_ACTOR,
                broker_base=_BASE,
                lock_factory=lk,
            ),
            locks=_Locks({pact.consumer_id}),
        )
    assert getattr(caught.value, "code", None) == CODE_IN_PROGRESS
    assert api.sent == [] and broker.published == []


def test_an_unknown_consumer_is_not_found() -> None:
    broker = _Broker([PACT_JS])
    with pytest.raises(PacticipantValidationError):
        _run(
            broker,
            LedgerApi(),
            lambda lk: reverify_pact(
                None,
                _TENANT,
                "ledger-api",
                "nobody",
                "a" * 64,
                _body(provider_version="1"),
                actor=_ACTOR,
                broker_base=_BASE,
            ),
        )


# ---------------------------------------------------------------------------
# Verify all stale
# ---------------------------------------------------------------------------


def test_verify_all_stale_verifies_only_pacts_without_a_result() -> None:
    broker, api = _Broker([PACT_JS, PACT_JVM, PACT_GO]), LedgerApi()
    verified_one = broker.candidates[0]
    response = _run(
        broker,
        api,
        lambda lk: verify_stale_pacts(
            None,
            _TENANT,
            "ledger-api",
            _body(provider_version="9f8e7d6"),
            actor=_ACTOR,
            broker_base=_BASE,
            lock_factory=lk,
        ),
        results={(verified_one.consumer_id, verified_one.sha): _result(verified_one.consumer_slug, verified_one.sha)},
    )
    assert response.trigger == "stale-recheck" and response.skipped == []
    consumers = sorted(pact.consumer for pact in response.pacts)
    assert verified_one.consumer_slug not in consumers and len(consumers) == 2
    assert all(stored["trigger"] == "stale-recheck" for stored in broker.published)
    assert all(pact.short_description.startswith("stale: ") for pact in response.pacts)


def test_verify_all_stale_lists_a_busy_pair_as_skipped_and_runs_the_rest() -> None:
    broker, api = _Broker([PACT_JS, PACT_JVM]), LedgerApi()
    busy = broker.candidates[0]
    response = _run(
        broker,
        api,
        lambda lk: verify_stale_pacts(
            None,
            _TENANT,
            "ledger-api",
            _body(provider_version="9f8e7d6"),
            actor=_ACTOR,
            broker_base=_BASE,
            lock_factory=lk,
        ),
        locks=_Locks({busy.consumer_id}),
    )
    (skipped,) = response.skipped
    assert (skipped.consumer, skipped.code) == (busy.consumer_slug, CODE_IN_PROGRESS)
    assert "already running" in skipped.reason
    assert [pact.consumer for pact in response.pacts] == [broker.candidates[1].consumer_slug]


def test_verify_all_stale_lists_pacts_past_the_limit_as_not_run() -> None:
    broker, api = _Broker([PACT_JS, PACT_JVM, PACT_GO]), LedgerApi()
    with patch(f"{_OPS}.MAX_PACTS_PER_RUN", 2):
        response = _run(
            broker,
            api,
            lambda lk: verify_stale_pacts(
                None,
                _TENANT,
                "ledger-api",
                _body(provider_version="9f8e7d6"),
                actor=_ACTOR,
                broker_base=_BASE,
                lock_factory=lk,
            ),
        )
    assert len(response.pacts) == 2
    (skipped,) = response.skipped
    assert skipped.code == CODE_OVER_LIMIT and "at most 2" in skipped.reason
    # By consumer handle: the last one alphabetically is the one left over.
    assert skipped.consumer == sorted(c.consumer_slug for c in broker.candidates)[-1]


def test_verify_all_stale_with_nothing_stale_is_no_pacts() -> None:
    broker = _Broker([PACT_JS])
    pact = broker.candidates[0]
    response = _run(
        broker,
        LedgerApi(),
        lambda lk: verify_stale_pacts(
            None,
            _TENANT,
            "ledger-api",
            _body(provider_version="9f8e7d6"),
            actor=_ACTOR,
            broker_base=_BASE,
            lock_factory=lk,
        ),
        results={(pact.consumer_id, pact.sha): _result(pact.consumer_slug, pact.sha)},
    )
    assert (response.outcome, response.success, response.pacts, response.skipped) == ("no-pacts", False, [], [])


def test_verify_all_stale_requires_a_provider_version() -> None:
    with pytest.raises(Exception) as caught:
        verify_stale_pacts(None, _TENANT, "ledger-api", _body(), actor=_ACTOR, broker_base=_BASE)
    assert getattr(caught.value, "code", None) == CODE_NO_PROVIDER_VERSION


def test_the_hosted_verifier_records_trigger_hosted() -> None:
    broker = _Broker([PACT_JS])
    _verify(broker, LedgerApi())
    (stored,) = broker.published
    assert stored["trigger"] == "hosted" and stored["evidence_run_id"] == "run-1"
    assert isinstance(stored["duration_ms"], int)


# ---------------------------------------------------------------------------
# Status, history and one result
# ---------------------------------------------------------------------------


def test_the_status_marks_stale_pacts_and_counts_the_kpi_strip() -> None:
    broker = _Broker([PACT_JS, PACT_JVM, PACT_GO])
    first, second, third = sorted(broker.candidates, key=lambda c: c.consumer_slug)
    results = {
        (first.consumer_id, first.sha): _result(first.consumer_slug, first.sha, success=True),
        (second.consumer_id, second.sha): _result(
            second.consumer_slug, second.sha, success=False, created_at="2026-11-25T09:00:00+00:00"
        ),
    }
    with (
        patch(f"{_OPS}.list_pact_candidates", side_effect=broker.list_pact_candidates),
        patch(f"{_OPS}.latest_results_by_pact", return_value=results) as latest,
    ):
        status = verification_status(None, _TENANT, "ledger-api")
    assert [entry.consumer for entry in status.pacts] == [
        first.consumer_slug,
        second.consumer_slug,
        third.consumer_slug,
    ]
    assert [entry.stale for entry in status.pacts] == [False, False, True]
    assert status.pacts[2].latest_result is None
    counts = status.counts
    assert (counts.pacts, counts.verified, counts.failing, counts.stale) == (3, 1, 1, 1)
    assert (counts.interactions, counts.passing_interactions) == (4, 2)
    assert counts.last_verified_at == "2026-11-25T09:00:00+00:00"
    assert status.truncated is False
    # One read for every pact's newest result, by (consumer, sha).
    assert sorted(latest.call_args.args[3]) == sorted((c.consumer_id, c.sha) for c in broker.candidates)


def test_a_provider_with_no_pacts_has_an_empty_status() -> None:
    with (
        patch(f"{_OPS}.list_pact_candidates", return_value=(_PROVIDER, [])),
        patch(f"{_OPS}.latest_results_by_pact", return_value={}),
    ):
        status = verification_status(None, _TENANT, "ledger-api")
    assert status.pacts == [] and status.counts.pacts == 0 and status.counts.last_verified_at is None


def test_a_summary_counts_interactions_and_names_the_verifier() -> None:
    summary = summarise(_result())
    assert (summary.counts.total, summary.counts.passed, summary.counts.failed) == (2, 1, 1)
    assert summary.verified_by == "apiome-pact-verifier 1"
    assert (summary.trigger, summary.duration_ms) == ("hosted", 1840)


@pytest.mark.parametrize("cursor", ["abc", "-1", "0", "1.5", "9" * 20, " "])
def test_a_cursor_this_api_did_not_hand_out_is_refused(cursor: str) -> None:
    with pytest.raises(PactPublicationError) as caught:
        decode_cursor(cursor)
    assert caught.value.code == CODE_CURSOR_INVALID


def test_the_history_pages_by_cursor_and_narrows_by_consumer() -> None:
    consumer = PacticipantRecord(id="c-1", tenant_id=_TENANT, slug="billing-service", name="Billing Service")
    lookup = {"ledger-api": _PROVIDER, "billing-service": consumer}
    with (
        patch(f"{_OPS}.get_pacticipant", side_effect=lambda _db, _t, ref: lookup[ref]),
        patch(f"{_OPS}.list_provider_results", return_value=([_result()], 7)) as listed,
    ):
        page = list_results(None, _TENANT, "ledger-api", consumer_ref="billing-service", cursor="42", limit=10)
    assert page.next_cursor == "7" and page.consumer == "billing-service"
    assert [result.id for result in page.results] == ["44444444-4444-4444-8444-444444444444"]
    assert listed.call_args.kwargs == {"consumer": consumer, "before_seq": 42, "limit": 10}


def test_the_last_history_page_has_no_cursor() -> None:
    with (
        patch(f"{_OPS}.get_pacticipant", return_value=_PROVIDER),
        patch(f"{_OPS}.list_provider_results", return_value=([], None)),
    ):
        page = list_results(None, _TENANT, "ledger-api")
    assert page.next_cursor is None and page.results == [] and page.consumer is None


def _read(record: VerificationResultRecord, *, include_evidence: bool, load_run: Any = None) -> Any:
    with (
        patch(f"{_OPS}.get_pacticipant", return_value=_PROVIDER),
        patch(f"{_OPS}.get_provider_result", return_value=record),
    ):
        kwargs = {"load_run": load_run} if load_run else {}
        return read_result(None, _TENANT, "ledger-api", record.id, include_evidence=include_evidence, **kwargs)


def test_a_result_a_verifier_published_has_no_evidence_recorded() -> None:
    detail = _read(_result(evidence_run_id=None), include_evidence=True)
    assert detail.evidence_status == EVIDENCE_NOT_RECORDED and detail.evidence is None
    assert detail.test_results[1]["mismatches"][0]["expected"] == 2026


def test_evidence_is_withheld_without_evidence_view() -> None:
    def never(*_args: Any) -> Any:
        raise AssertionError("the evidence must not be read")

    detail = _read(
        _result(evidence_run_id="55555555-5555-4555-8555-555555555555"), include_evidence=False, load_run=never
    )
    assert detail.evidence_status == EVIDENCE_FORBIDDEN and detail.evidence is None


def test_a_pruned_evidence_run_is_reported_not_found() -> None:
    def pruned(*_args: Any) -> Any:
        raise EvidenceValidationError("evidence-run-not-found", "gone")

    detail = _read(
        _result(evidence_run_id="55555555-5555-4555-8555-555555555555"), include_evidence=True, load_run=pruned
    )
    assert detail.evidence_status == EVIDENCE_NOT_FOUND


def test_the_evidence_run_is_attached_for_the_callers_tenant() -> None:
    seen: List[Tuple[str, str]] = []
    run = object()

    def load(tenant_id: str, run_id: str) -> Any:
        seen.append((tenant_id, run_id))
        return run

    evidence_id = "55555555-5555-4555-8555-555555555555"
    with (
        patch(f"{_OPS}.get_pacticipant", return_value=_PROVIDER),
        patch(f"{_OPS}.get_provider_result", return_value=_result(evidence_run_id=evidence_id)),
        patch(f"{_OPS}.ResultDetail", side_effect=lambda **fields: fields),
    ):
        detail = read_result(None, _TENANT, "ledger-api", "x", include_evidence=True, load_run=load)
    assert seen == [(_TENANT, evidence_id)]
    assert detail["evidence_status"] == EVIDENCE_ATTACHED and detail["evidence"] is run
