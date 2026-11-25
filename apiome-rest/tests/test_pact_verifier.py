"""Unit tests for the hosted verifier's judgment — PFX-3.2 (#6932).

:mod:`app.pact_verifier` decides what a run may send and what it proves:

* a mutating interaction needs the target policy **and** the run's opt-in, policy first — a run
  cannot widen the target;
* an interaction with a provider state is skipped with its reason unless a handler sets the state
  up or the run asks to replay without setup;
* a pact is ``passed`` only when everything was replayed and matched, ``failed`` when something
  did not match, ``incomplete`` otherwise; a Pact 4 ``pending`` interaction never decides;
* results name the interaction, the field, the rule, and what was expected and returned.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

import httpx
import pytest

from app.contract_runner import run_suite
from app.contract_suite import PactProviderState, SuiteUnsupportedOperation
from app.contract_suite_pact import compile_pact_suite
from app.pact_verifier import (
    OUTCOME_FAILED,
    OUTCOME_INCOMPLETE,
    OUTCOME_PASSED,
    SKIP_MUTATING_BLOCKED,
    SKIP_PATH_NOT_ON_TARGET,
    SKIP_STATE_NOT_SET_UP,
    SKIP_STATE_SETUP_FAILED,
    InteractionVerification,
    PactVerificationOptions,
    interaction_counts,
    interaction_results,
    pact_outcome,
    pact_test_results,
    plan_pact_run,
    state_hooks,
)
from app.provider_verification import MutatingFixture
from tests.pact_verifier_fakes import PACT_GO, PACT_JS, PACT_JVM, LedgerApi, compile_fixture, load_pact, target


def _codes(plan) -> dict:
    return dict(plan.skips)


def _case_id(manifest, operation_key: str) -> str:
    return next(case.case_id for case in manifest.cases if case.operation_key == operation_key)


# ---------------------------------------------------------------------------
# Planning: mutation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target_allows, opted_in, sent",
    [(False, False, False), (False, True, False), (True, False, False), (True, True, True)],
)
def test_a_mutating_interaction_needs_the_policy_and_the_opt_in(
    target_allows: bool, opted_in: bool, sent: bool
) -> None:
    manifest = compile_fixture(PACT_JVM)
    plan = plan_pact_run(
        manifest, PactVerificationOptions(allow_mutating=opted_in), target_allows_mutating=target_allows
    )
    post = _case_id(manifest, "POST /invoices")
    assert (post not in plan.skips) is sent
    if not sent:
        assert plan.skips[post] == SKIP_MUTATING_BLOCKED
    assert _case_id(manifest, "GET /invoices") not in plan.skips


def test_the_policy_is_named_first_so_an_opt_in_reads_as_overruled() -> None:
    manifest = compile_fixture(PACT_JVM)
    plan = plan_pact_run(manifest, PactVerificationOptions(allow_mutating=True), target_allows_mutating=False)
    message = plan.decisions[_case_id(manifest, "POST /invoices")].skip_message or ""
    assert "a run cannot override" in message


def test_a_fixture_redirects_a_mutating_interaction_without_touching_its_expectation() -> None:
    manifest = compile_fixture(PACT_JVM)
    fixture = MutatingFixture(operation_key="POST /invoices", body={"customer": "disposable", "total": 1})
    plan = plan_pact_run(
        manifest, PactVerificationOptions(allow_mutating=True, fixtures=[fixture]), target_allows_mutating=True
    )
    post = _case_id(manifest, "POST /invoices")
    replaced = plan.decisions[post].case
    assert replaced is not None and replaced.request.body == {"customer": "disposable", "total": 1}
    original = next(case for case in manifest.cases if case.case_id == post)
    assert replaced.pact == original.pact and replaced.expect == original.expect
    assert plan.fixtures_applied == 1


def test_a_fixture_is_not_an_opt_in() -> None:
    manifest = compile_fixture(PACT_JVM)
    fixture = MutatingFixture(operation_key="POST /invoices", body={})
    plan = plan_pact_run(manifest, PactVerificationOptions(fixtures=[fixture]), target_allows_mutating=True)
    assert plan.skips[_case_id(manifest, "POST /invoices")] == SKIP_MUTATING_BLOCKED


@pytest.mark.parametrize(
    "path", ["https://elsewhere.example.test/steal", "//elsewhere.example.test/steal", "invoices/1", "/\\elsewhere"]
)
def test_a_recorded_path_that_would_leave_the_target_is_never_sent(path: str) -> None:
    document = load_pact(PACT_JVM)
    document["interactions"][0]["request"]["path"] = path
    manifest = compile_pact_suite(document, consumer="Orders UI", provider="Ledger API")
    plan = plan_pact_run(manifest, PactVerificationOptions(allow_mutating=True), target_allows_mutating=True)
    api = LedgerApi()
    client = api.client()
    try:
        run = run_suite(manifest, target(allow_mutating=True), client=client, decisions=plan.decisions)
    finally:
        client.close()
    results = interaction_results(manifest, run.operations)
    held = next(r for r in results if r.description == "list open invoices")
    assert (held.outcome, held.code) == ("skipped", SKIP_PATH_NOT_ON_TARGET)
    assert [str(request.url.host) for request in api.requests] == ["ledger.staging.example.test"]
    assert api.sent == ["POST /invoices"]
    assert pact_outcome(results, manifest.unsupported) == OUTCOME_INCOMPLETE


# ---------------------------------------------------------------------------
# Planning: provider states
# ---------------------------------------------------------------------------


def test_an_interaction_with_a_state_is_skipped_and_says_which_state() -> None:
    manifest = compile_fixture(PACT_JS)
    plan = plan_pact_run(manifest, PactVerificationOptions(), target_allows_mutating=False)
    with_state = _case_id(manifest, "GET /invoices/1042")
    assert _codes(plan) == {with_state: SKIP_STATE_NOT_SET_UP}
    assert "'invoice 1042 exists'" in (plan.decisions[with_state].skip_message or "")


def test_a_pact_2_provider_state_string_is_a_state_too() -> None:
    manifest = compile_fixture(PACT_GO)
    plan = plan_pact_run(manifest, PactVerificationOptions(), target_allows_mutating=False)
    assert list(plan.skips.values()) == [SKIP_STATE_NOT_SET_UP]


def test_replaying_without_setup_is_an_explicit_choice_that_is_remembered() -> None:
    manifest = compile_fixture(PACT_JS)
    plan = plan_pact_run(
        manifest, PactVerificationOptions(replay_without_state_setup=True), target_allows_mutating=False
    )
    assert plan.skips == {}
    assert plan.states_assumed == [_case_id(manifest, "GET /invoices/1042")]


def test_a_state_handler_makes_the_interaction_runnable_without_assuming_anything() -> None:
    manifest = compile_fixture(PACT_JS)
    plan = plan_pact_run(manifest, PactVerificationOptions(), target_allows_mutating=False, has_state_handler=True)
    assert plan.skips == {} and plan.states_assumed == []


class _Handler:
    """A provider-state handler that records what it was asked."""

    def __init__(self, problem: Optional[str] = None) -> None:
        self.problem = problem
        self.calls: List[str] = []

    def setup(self, states: Sequence[PactProviderState]) -> Optional[str]:
        self.calls.append("setup " + ", ".join(f"{state.name} {state.params}" for state in states))
        return self.problem

    def teardown(self, states: Sequence[PactProviderState]) -> None:
        self.calls.append("teardown " + ", ".join(state.name for state in states))


def _replay(name: str, api: LedgerApi, handler: Optional[_Handler], options: Optional[PactVerificationOptions] = None):
    manifest = compile_fixture(name)
    plan = plan_pact_run(
        manifest,
        options or PactVerificationOptions(),
        target_allows_mutating=True,
        has_state_handler=handler is not None,
    )
    client = api.client()
    try:
        run = run_suite(
            manifest, target(allow_mutating=True), client=client, decisions=plan.decisions, hooks=state_hooks(handler)
        )
    finally:
        client.close()
    return manifest, interaction_results(manifest, run.operations, states_assumed=plan.states_assumed)


def test_the_handler_sets_states_up_before_and_tears_them_down_after_only_where_named() -> None:
    api, handler = LedgerApi(), _Handler()
    manifest, results = _replay(PACT_JS, api, handler)
    assert handler.calls == ["setup invoice 1042 exists {'id': 1042}", "teardown invoice 1042 exists"]
    assert [r.outcome for r in results] == ["passed", "passed"]
    assert pact_outcome(results, manifest.unsupported) == OUTCOME_PASSED


def test_a_state_that_cannot_be_set_up_skips_the_interaction_with_the_reason() -> None:
    api, handler = LedgerApi(), _Handler(problem="no state named 'invoice 1042 exists' is registered")
    manifest, results = _replay(PACT_JS, api, handler)
    held = results[0]
    assert (held.outcome, held.code) == ("skipped", SKIP_STATE_SETUP_FAILED)
    assert "no state named" in (held.message or "")
    assert api.sent == ["GET /invoices/9999"]
    assert handler.calls == ["setup invoice 1042 exists {'id': 1042}"]
    assert pact_outcome(results, manifest.unsupported) == OUTCOME_INCOMPLETE


def test_no_handler_means_no_hooks() -> None:
    assert state_hooks(None) is None


# ---------------------------------------------------------------------------
# Reading a run back
# ---------------------------------------------------------------------------


def test_results_follow_the_pact_order_and_carry_the_interaction_identity() -> None:
    manifest, results = _replay(PACT_JVM, LedgerApi(), None, PactVerificationOptions(allow_mutating=True))
    assert [(r.description, r.key, r.operation, r.pointer) for r in results] == [
        ("list open invoices", "5a1c9e0b", "GET /invoices", "/interactions/0"),
        ("create an invoice", "77aa01ff", "POST /invoices", "/interactions/1"),
    ]
    counts = interaction_counts(manifest, results)
    assert (counts.interactions, counts.passed, counts.failed, counts.skipped) == (2, 2, 0, 0)


def test_a_failure_names_the_interaction_the_field_pointer_and_the_rule() -> None:
    drifted = LedgerApi(
        {
            "GET /invoices": lambda _request: httpx.Response(
                200,
                json={
                    "invoices": [{"id": 7, "currency": "usd", "tags": {"priority": 1}}],
                    "page": {"number": "3", "last": True},
                },
            )
        }
    )
    manifest, results = _replay(PACT_JVM, drifted, None, PactVerificationOptions(allow_mutating=True))
    failed = results[0]
    assert (failed.description, failed.outcome, failed.code) == ("list open invoices", "failed", "pact-body-mismatch")
    assert {(m.attribute, m.field, m.rule) for m in failed.mismatches} == {
        ("body", "/invoices/0/currency", "regex"),
        ("body", "/invoices/0/tags/priority", "type"),
        ("body", "/page/number", "integer"),
    }
    currency = next(m for m in failed.mismatches if m.field == "/invoices/0/currency")
    assert currency.actual == '"usd"'
    assert "/^[A-Z]{3}$/" in (currency.expected or "")
    assert pact_outcome(results, manifest.unsupported) == OUTCOME_FAILED


def test_a_status_mismatch_names_the_status_rule() -> None:
    wrong = LedgerApi({"GET /invoices": lambda _request: httpx.Response(500, json={})})
    _, results = _replay(PACT_JVM, wrong, None, PactVerificationOptions(allow_mutating=True))
    (mismatch,) = results[0].mismatches
    assert (mismatch.attribute, mismatch.field, mismatch.rule) == ("status", "status", "statuscode")
    plain = LedgerApi({"GET /invoices/9999": lambda _request: httpx.Response(500, json={})})
    _, js = _replay(PACT_JS, plain, None, PactVerificationOptions(replay_without_state_setup=True))
    assert js[1].mismatches[0].rule == "equality"


def test_a_header_mismatch_names_the_header() -> None:
    wrong = LedgerApi({"POST /invoices": lambda _request: httpx.Response(201)})
    _, results = _replay(PACT_JVM, wrong, None, PactVerificationOptions(allow_mutating=True))
    (mismatch,) = results[1].mismatches
    assert (mismatch.attribute, mismatch.field, mismatch.rule) == ("header", "Location", "presence")


def test_states_replayed_without_setup_are_marked() -> None:
    _, results = _replay(PACT_JS, LedgerApi(), None, PactVerificationOptions(replay_without_state_setup=True))
    assert [(r.provider_states, r.states_set_up) for r in results] == [(["invoice 1042 exists"], False), ([], True)]


# ---------------------------------------------------------------------------
# Outcome
# ---------------------------------------------------------------------------


def _interaction(outcome: str, *, pending: bool = False) -> InteractionVerification:
    return InteractionVerification(
        case_id=f"case-{outcome}-{pending}",
        description=f"{outcome} interaction",
        pointer="/interactions/0",
        operation="GET /x",
        pending=pending,
        outcome=outcome,
        code=None if outcome == "passed" else f"{outcome}-code",
        message=None if outcome == "passed" else f"why it {outcome}",
    )


_UNSUPPORTED = [
    SuiteUnsupportedOperation(operation_key="/interactions/3", code="UNSUPPORTED_OPERATION_KIND", reason="a message")
]


@pytest.mark.parametrize(
    "outcomes, unsupported, expected",
    [
        (["passed", "passed"], [], OUTCOME_PASSED),
        (["passed", "failed"], [], OUTCOME_FAILED),
        (["failed", "skipped"], _UNSUPPORTED, OUTCOME_FAILED),
        (["passed", "skipped"], [], OUTCOME_INCOMPLETE),
        (["passed", "errored"], [], OUTCOME_INCOMPLETE),
        (["passed"], _UNSUPPORTED, OUTCOME_INCOMPLETE),
        (["skipped"], [], OUTCOME_INCOMPLETE),
        ([], [], OUTCOME_INCOMPLETE),
    ],
)
def test_a_pact_passes_only_when_everything_was_replayed_and_matched(outcomes, unsupported, expected) -> None:
    assert pact_outcome([_interaction(outcome) for outcome in outcomes], unsupported) == expected


def test_a_pending_interaction_never_decides_the_outcome() -> None:
    assert pact_outcome([_interaction("passed"), _interaction("failed", pending=True)]) == OUTCOME_PASSED
    assert pact_outcome([_interaction("passed"), _interaction("skipped", pending=True)]) == OUTCOME_PASSED
    assert pact_outcome([_interaction("failed", pending=True)]) == OUTCOME_INCOMPLETE


def test_a_pact_with_a_message_interaction_is_never_passed() -> None:
    document = load_pact(PACT_JVM)
    document["interactions"].append({"type": "Asynchronous/Messages", "description": "invoice paid", "contents": {}})
    manifest = compile_pact_suite(document, consumer="Orders UI", provider="Ledger API")
    plan = plan_pact_run(manifest, PactVerificationOptions(allow_mutating=True), target_allows_mutating=True)
    api = LedgerApi()
    client = api.client()
    try:
        run = run_suite(manifest, target(allow_mutating=True), client=client, decisions=plan.decisions)
    finally:
        client.close()
    results = interaction_results(manifest, run.operations)
    assert [r.outcome for r in results] == ["passed", "passed"]
    assert pact_outcome(results, manifest.unsupported) == OUTCOME_INCOMPLETE
    counts = interaction_counts(manifest, results)
    assert (counts.interactions, counts.unsupported) == (3, 1)


# ---------------------------------------------------------------------------
# Published test results
# ---------------------------------------------------------------------------


def test_test_results_are_pact_shaped_and_lose_nothing() -> None:
    drifted = LedgerApi({"GET /invoices/1042": lambda _request: httpx.Response(200, json={"id": 1})})
    _, results = _replay(PACT_JS, drifted, None, PactVerificationOptions(replay_without_state_setup=True))
    entries = pact_test_results(results, _UNSUPPORTED)
    failed, passed, unsupported = entries
    assert failed["interactionDescription"] == "a request for invoice 1042"
    assert failed["success"] is False and failed["outcome"] == "failed" and failed["code"] == "pact-body-mismatch"
    assert failed["interactionProviderState"] == "invoice 1042 exists"
    assert failed["providerStatesSetUp"] is False
    first = failed["mismatches"][0]
    assert set(first) == {"attribute", "identifier", "description", "rule", "expected", "actual"}
    assert first["attribute"] == "body" and first["identifier"].startswith("/")
    assert passed == {"interactionDescription": "a request for a missing invoice", "success": True, "outcome": "passed"}
    assert unsupported == {
        "interactionDescription": "/interactions/3",
        "success": False,
        "outcome": "unsupported",
        "code": "UNSUPPORTED_OPERATION_KIND",
        "exceptions": [{"message": "a message"}],
    }


def test_a_skipped_interaction_carries_its_reason_as_an_exception() -> None:
    (entry,) = pact_test_results([_interaction("skipped")])
    assert entry["exceptions"] == [{"message": "why it skipped"}]
    assert entry["code"] == "skipped-code"
    (pending,) = pact_test_results([_interaction("failed", pending=True)])
    assert pending["pending"] is True


def test_a_pact_4_interaction_key_is_the_interaction_id() -> None:
    _, results = _replay(PACT_JVM, LedgerApi(), None, PactVerificationOptions(allow_mutating=True))
    assert [entry["interactionId"] for entry in pact_test_results(results)] == ["5a1c9e0b", "77aa01ff"]
