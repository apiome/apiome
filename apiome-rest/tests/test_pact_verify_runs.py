"""Live hosted verification runs, with every store faked — PFX-8.9 (#7306).

:class:`app.pact_verify_runs.LiveRuns` on the real runner over a fake transport (the stores of
``tests/test_pact_verifier_service.py``):

* a run is checked exactly as ``…/verify`` checks it, and refused before it starts;
* its progress — per-pact rows, interactions done of the total, the log — follows the replay, and
  the finished run carries the very answer ``…/verify`` gives;
* the newest failing interaction is kept with expected beside actual;
* a stop ends the run before its next interaction: the pact cut short publishes nothing, the pacts
  not reached are listed as skipped, the outcome is ``stopped``;
* one interaction of a finished run can be re-run, publishing nothing;
* a run is the tenant's own: another tenant is told it does not exist;
* a workspace has at most three runs going; a long log keeps its newest lines and counts the rest.
"""

from __future__ import annotations

import threading
import time
from contextlib import ExitStack
from typing import Any, Iterator, List

import httpx
import pytest

from app import pact_verify_runs
from app.pact_pending import NO_EVIDENCE
from app.pact_verifier import InteractionMismatch, InteractionVerification, PactVerificationOptions
from app.pact_verifier_service import (
    CODE_MUTATING_PRODUCTION,
    CODE_STOPPED,
    NOT_PUBLISHED_STOPPED,
    PactVerifierError,
    PactVerifyRequest,
)
from app.pact_verify_runs import (
    CODE_INTERACTION_NOT_FOUND,
    CODE_RUN_BUSY,
    CODE_RUN_LIMIT,
    CODE_RUN_NOT_FOUND,
    CODE_RUN_PACT_NOT_FOUND,
    LiveRunError,
    LiveRuns,
    LiveRunSnapshot,
    RerunRequest,
    interaction_line,
)
from tests.pact_verifier_fakes import PACT_GO, PACT_JS, PACT_JVM, LedgerApi, target
from tests.test_pact_verifier_service import _ACTOR, _BASE, _TENANT, _Broker

_SERVICE = "app.pact_verifier_service"
_OTHER_TENANT = "99999999-9999-4999-8999-999999999999"
_EVERYTHING = PactVerificationOptions(allow_mutating=True, replay_without_state_setup=True)


class _Stack:
    """The faked stores and transport, kept in place while background runs replay."""

    def __init__(self, broker: _Broker, api: LedgerApi, *, environment: str = "staging") -> None:
        from unittest.mock import patch

        self.broker = broker
        self.api = api
        self.stack = ExitStack()
        for name, fake in (
            ("list_pact_candidates", broker.list_pact_candidates),
            ("get_pact_by_sha", broker.get_pact_by_sha),
            ("publish_verification_result", broker.publish),
            ("record_run", broker.record_run),
            ("fire_verification_events", broker.fire),
            ("record_broker_version", broker.record_branch),
        ):
            self.stack.enter_context(patch(f"{_SERVICE}.{name}", side_effect=fake))
        self.stack.enter_context(patch("app.pact_verify_runs.get_pact_by_sha", side_effect=broker.get_pact_by_sha))
        self.stack.enter_context(patch(f"{_SERVICE}.load_pending_evidence", return_value=NO_EVIDENCE))
        self.stack.enter_context(patch(f"{_SERVICE}.list_states", return_value=[]))
        self.stack.enter_context(patch(f"{_SERVICE}.results_for_provider_version", return_value={}))
        resolved = target(allow_mutating=True).model_copy(update={"environment": environment})
        self.stack.enter_context(patch(f"{_SERVICE}.resolve_target", side_effect=lambda *a, **k: resolved))
        self.stack.enter_context(patch(f"{_SERVICE}.post_verification_statuses"))
        self.stack.enter_context(patch(f"{_SERVICE}.notify_failed_verification"))
        self.stack.enter_context(
            patch("app.contract_runner.build_guarded_client", side_effect=lambda **_k: api.client())
        )

    def close(self) -> None:
        self.stack.close()


@pytest.fixture
def runs() -> Iterator[LiveRuns]:
    registry = LiveRuns(workers=2)
    yield registry
    registry.clear()


def _request(**overrides: Any) -> PactVerifyRequest:
    body = {"target_ref": "ledger-staging", "provider_version": "4f1e2d0", "verification": _EVERYTHING}
    body.update(overrides)
    return PactVerifyRequest(**body)


def _start(runs: LiveRuns, tenant: str = _TENANT, **overrides: Any) -> LiveRunSnapshot:
    return runs.start(None, tenant, "ledger-api", _request(**overrides), actor=_ACTOR, broker_base=_BASE)


def _wait(runs: LiveRuns, run_id: str, tenant: str = _TENANT, timeout: float = 10.0) -> LiveRunSnapshot:
    """Poll a run until it is no longer running."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = runs.snapshot(tenant, run_id)
        if snapshot.status != "running":
            return snapshot
        time.sleep(0.01)
    raise AssertionError("the run did not finish")


class _Gate:
    """Hold the provider's answer to one request until the test lets it go."""

    def __init__(self) -> None:
        self.reached = threading.Event()
        self.release = threading.Event()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.reached.set()
        assert self.release.wait(5), "the test never released the gate"
        return LedgerApi()(request)


# ---------------------------------------------------------------------------
# A run as it happens
# ---------------------------------------------------------------------------


def test_a_live_run_reports_progress_and_ends_with_the_verify_answer(runs: LiveRuns) -> None:
    broker, api = _Broker([PACT_JS, PACT_JVM, PACT_GO]), LedgerApi()
    stack = _Stack(broker, api)
    try:
        started = _start(runs)
        assert started.status == "running"
        assert [row.status for row in started.pacts] == ["queued", "queued", "queued"]
        assert (started.provider, started.provider_name, started.target) == (
            "ledger-api",
            "Ledger API",
            "ledger-staging",
        )
        done = _wait(runs, started.run_id)
    finally:
        stack.close()

    assert done.status == "finished" and done.finished_at is not None
    assert done.result is not None and (done.result.outcome, done.result.success) == ("passed", True)
    assert [row.status for row in done.pacts] == ["passed", "passed", "passed"]
    assert all(row.done == row.interactions and row.passed == row.interactions for row in done.pacts)
    assert done.interactions == done.done == 5
    assert all(row.published for row in done.pacts)
    assert len(broker.published) == 3
    assert done.failure is None
    texts = [line.text for line in done.log]
    assert any("GET /invoices/1042  200  ok" in text for text in texts)
    assert texts[-1].endswith("run    passed")
    assert [line.seq for line in done.log] == list(range(1, len(done.log) + 1))
    assert done.log_next == len(done.log) and done.log_dropped == 0


def test_the_log_is_read_on_from_a_cursor(runs: LiveRuns) -> None:
    stack = _Stack(_Broker([PACT_JS]), LedgerApi())
    try:
        run_id = _start(runs).run_id
        done = _wait(runs, run_id)
        later = runs.snapshot(_TENANT, run_id, log_after=done.log_next - 2)
    finally:
        stack.close()
    assert [line.seq for line in later.log] == [done.log_next - 1, done.log_next]


def test_the_newest_failing_interaction_is_kept_with_expected_and_actual(runs: LiveRuns) -> None:
    drifted = LedgerApi({"GET /invoices/1042": lambda _r: httpx.Response(200, json={"id": "x", "status": "paid"})})
    broker = _Broker([PACT_JS])
    stack = _Stack(broker, drifted)
    try:
        done = _wait(runs, _start(runs).run_id)
    finally:
        stack.close()

    assert done.result is not None and done.result.outcome == "failed"
    (row,) = done.pacts
    assert row.status == "failed" and row.failed == 1 and row.published is True
    assert done.failure is not None
    assert (done.failure.consumer, done.failure.pact_version_sha) == (row.consumer, row.pact_version_sha)
    interaction = done.failure.interaction
    assert interaction.operation == "GET /invoices/1042" and interaction.outcome == "failed"
    assert interaction.mismatches and all(m.description for m in interaction.mismatches)
    assert any("differs" in line.text for line in done.log if line.kind == "interaction")


# ---------------------------------------------------------------------------
# Stopping
# ---------------------------------------------------------------------------


def test_a_stop_ends_the_run_before_its_next_interaction(runs: LiveRuns) -> None:
    gate = _Gate()
    api = LedgerApi({"GET /invoices/1042": gate})
    broker = _Broker([PACT_JS, PACT_JVM])
    stack = _Stack(broker, api)
    try:
        run_id = _start(runs).run_id
        assert gate.reached.wait(5)
        stopping = runs.stop(_TENANT, run_id)
        assert stopping.stop_requested is True and stopping.status == "running"
        gate.release.set()
        done = _wait(runs, run_id)
    finally:
        stack.close()

    assert done.result is not None and (done.result.outcome, done.result.success) == ("stopped", False)
    first, second = done.pacts
    assert first.status == "stopped" and first.not_published_reason == NOT_PUBLISHED_STOPPED
    assert first.published is False and first.skipped >= 1
    assert second.status == "stopped" and second.done == 0
    assert [item.code for item in done.skipped] == [CODE_STOPPED]
    assert broker.published == [], "a stopped pact publishes nothing"
    assert api.sent == ["GET /invoices/1042"], "nothing is sent after the stop"
    assert any("stop requested" in line.text for line in done.log)


def test_stopping_a_finished_run_changes_nothing(runs: LiveRuns) -> None:
    stack = _Stack(_Broker([PACT_JS]), LedgerApi())
    try:
        run_id = _start(runs).run_id
        done = _wait(runs, run_id)
        again = runs.stop(_TENANT, run_id)
    finally:
        stack.close()
    assert again.stop_requested is False and again.result == done.result


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_run_that_cannot_start_is_refused_before_anything_is_registered(runs: LiveRuns) -> None:
    api = LedgerApi()
    stack = _Stack(_Broker([PACT_JS]), api, environment="production")
    try:
        with pytest.raises(PactVerifierError) as refused:
            _start(runs)
    finally:
        stack.close()
    assert refused.value.code == CODE_MUTATING_PRODUCTION
    assert api.sent == [] and runs._runs == {}


def test_another_tenant_is_told_the_run_does_not_exist(runs: LiveRuns) -> None:
    stack = _Stack(_Broker([PACT_JS]), LedgerApi())
    try:
        run_id = _start(runs).run_id
        _wait(runs, run_id)
    finally:
        stack.close()
    for call in (
        lambda: runs.snapshot(_OTHER_TENANT, run_id),
        lambda: runs.stop(_OTHER_TENANT, run_id),
        lambda: runs.provider_of(_OTHER_TENANT, run_id),
        lambda: runs.rerun_interaction(
            None, _OTHER_TENANT, run_id, RerunRequest(pact_version_sha="a", case_id="b"), actor=_ACTOR
        ),
    ):
        with pytest.raises(LiveRunError) as refused:
            call()
        assert (refused.value.code, refused.value.status) == (CODE_RUN_NOT_FOUND, 404)


def test_an_unknown_run_is_not_found(runs: LiveRuns) -> None:
    with pytest.raises(LiveRunError) as refused:
        runs.snapshot(_TENANT, "no-such-run")
    assert refused.value.status == 404


def test_a_workspace_runs_at_most_three_at_once(runs: LiveRuns) -> None:
    gate = _Gate()
    registry = LiveRuns(workers=4)
    stack = _Stack(_Broker([PACT_JS]), LedgerApi({"GET /invoices/1042": gate}))
    try:
        ids = [_start(registry).run_id for _ in range(3)]
        with pytest.raises(LiveRunError) as refused:
            _start(registry)
        assert (refused.value.code, refused.value.status) == (CODE_RUN_LIMIT, 429)
        # Another workspace is not held back by this one's runs.
        assert registry._runs and all(registry._runs[run_id].tenant_id == _TENANT for run_id in ids)
        gate.release.set()
        for run_id in ids:
            _wait(registry, run_id)
    finally:
        gate.release.set()
        stack.close()
        registry.clear()


def test_a_long_log_keeps_its_newest_lines_and_counts_the_rest(runs: LiveRuns, monkeypatch) -> None:
    monkeypatch.setattr(pact_verify_runs, "MAX_LOG_LINES", 3)
    stack = _Stack(_Broker([PACT_JS, PACT_JVM]), LedgerApi())
    try:
        done = _wait(runs, _start(runs).run_id)
    finally:
        stack.close()
    assert len(done.log) == 3
    assert done.log_dropped == done.log_next - 3 > 0
    assert done.log[0].seq == done.log_dropped + 1


def test_a_run_that_breaks_on_apiomes_side_says_so(runs: LiveRuns) -> None:
    broker = _Broker([PACT_JS])
    stack = _Stack(broker, LedgerApi())
    from unittest.mock import patch

    try:
        with patch(f"{_SERVICE}.compile_stored_pact", side_effect=RuntimeError("boom")):
            done = _wait(runs, _start(runs).run_id)
    finally:
        stack.close()
    assert done.status == "errored" and done.error is not None
    assert "RuntimeError" in done.error.message
    assert [row.status for row in done.pacts] == ["stopped"]


# ---------------------------------------------------------------------------
# Re-running one interaction
# ---------------------------------------------------------------------------


def test_one_interaction_is_re_run_and_nothing_is_published(runs: LiveRuns) -> None:
    fixed = {"broken": True}

    def invoice(request: httpx.Request) -> httpx.Response:
        if fixed["broken"]:
            return httpx.Response(200, json={"id": "x"})
        return LedgerApi()(request)

    broker = _Broker([PACT_JS])
    stack = _Stack(broker, LedgerApi({"GET /invoices/1042": invoice}))
    try:
        run_id = _start(runs).run_id
        done = _wait(runs, run_id)
        assert done.failure is not None
        published = len(broker.published)
        fixed["broken"] = False
        answer = runs.rerun_interaction(
            None,
            _TENANT,
            run_id,
            RerunRequest(pact_version_sha=done.failure.pact_version_sha, case_id=done.failure.interaction.case_id),
            actor=_ACTOR,
        )
        after = runs.snapshot(_TENANT, run_id, log_after=done.log_next)
    finally:
        stack.close()
    assert answer.interaction.outcome == "passed" and answer.published is False
    assert len(broker.published) == published and len(broker.evidence) == 1
    assert [line.kind for line in after.log] == ["rerun"]
    assert after.log[0].text.endswith(f"re-run GET /invoices/1042  200  ok  {answer.interaction.duration_ms} ms")


def test_re_running_is_refused_while_the_run_is_going_or_for_what_it_did_not_verify(runs: LiveRuns) -> None:
    gate = _Gate()
    stack = _Stack(_Broker([PACT_JS]), LedgerApi({"GET /invoices/1042": gate}))
    try:
        started = _start(runs)
        assert gate.reached.wait(5)
        sha = started.pacts[0].pact_version_sha
        with pytest.raises(LiveRunError) as busy:
            runs.rerun_interaction(
                None, _TENANT, started.run_id, RerunRequest(pact_version_sha=sha, case_id="x"), actor=_ACTOR
            )
        assert (busy.value.code, busy.value.status) == (CODE_RUN_BUSY, 409)
        gate.release.set()
        _wait(runs, started.run_id)
        with pytest.raises(LiveRunError) as unknown_pact:
            runs.rerun_interaction(
                None, _TENANT, started.run_id, RerunRequest(pact_version_sha="f" * 64, case_id="x"), actor=_ACTOR
            )
        assert (unknown_pact.value.code, unknown_pact.value.status) == (CODE_RUN_PACT_NOT_FOUND, 404)
        with pytest.raises(LiveRunError) as unknown_case:
            runs.rerun_interaction(
                None, _TENANT, started.run_id, RerunRequest(pact_version_sha=sha, case_id="nope"), actor=_ACTOR
            )
        assert (unknown_case.value.code, unknown_case.value.status) == (CODE_INTERACTION_NOT_FOUND, 404)
    finally:
        gate.release.set()
        stack.close()


def test_a_re_run_against_production_with_mutating_on_is_still_refused(runs: LiveRuns) -> None:
    stack = _Stack(_Broker([PACT_JS]), LedgerApi())
    try:
        started = _start(runs)
        done = _wait(runs, started.run_id)
    finally:
        stack.close()
    production = _Stack(_Broker([PACT_JS]), LedgerApi(), environment="production")
    try:
        with pytest.raises(PactVerifierError) as refused:
            runs.rerun_interaction(
                None,
                _TENANT,
                started.run_id,
                RerunRequest(pact_version_sha=done.pacts[0].pact_version_sha, case_id="any"),
                actor=_ACTOR,
            )
    finally:
        production.close()
    assert refused.value.code == CODE_MUTATING_PRODUCTION


# ---------------------------------------------------------------------------
# The log's lines
# ---------------------------------------------------------------------------


def _interaction(**fields: Any) -> InteractionVerification:
    base = {
        "case_id": "c",
        "description": "d",
        "pointer": "/interactions/0",
        "operation": "POST /invoices",
        "outcome": "passed",
    }
    base.update(fields)
    return InteractionVerification(**base)


def test_interaction_lines_read_like_a_verifier_log() -> None:
    assert interaction_line(_interaction(actual_status=201, duration_ms=12)) == "POST /invoices  201  ok  12 ms"
    body = InteractionMismatch(attribute="body", field="/currency", rule="regex", description="d")
    header = InteractionMismatch(attribute="header", field="Location", rule="equality", description="d")
    assert (
        interaction_line(_interaction(outcome="failed", actual_status=201, mismatches=[body, header]))
        == "POST /invoices  201  body differs at /currency (+1 more)"
    )
    assert interaction_line(_interaction(outcome="failed", actual_status=200, mismatches=[header])).endswith(
        "header differs (Location)"
    )
    skipped: List[str] = [
        interaction_line(_interaction(outcome="skipped", code="run-stopped", message="the run was stopped")),
        interaction_line(_interaction(outcome="errored", code="timeout")),
    ]
    assert skipped == ["POST /invoices  —  the run was stopped", "POST /invoices  —  timeout"]
