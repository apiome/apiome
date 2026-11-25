"""The contract runner on pact cases, and its per-case hooks — PFX-3.2 (#6932).

* a case compiled from a pact interaction is judged by the pact: status, recorded headers and
  body under the matching rules — for pacts in the shapes pact-js, pact-jvm and pact-go write;
* a mismatch is one failed assertion naming the field pointer (or header), the rule and both values;
* the request is replayed exactly as the consumer recorded it;
* ``hooks`` surround each case that is sent, can hold a case back, never widen the target policy,
  and force one case at a time.
"""

from __future__ import annotations

import threading
import time
from typing import List, Optional

import httpx
import pytest

from app.contract_runner import (
    FAILURE_CASE_HOOK_FAILED,
    FAILURE_MUTATING_METHOD_BLOCKED,
    FAILURE_PACT_BODY_MISMATCH,
    FAILURE_PACT_HEADER_MISMATCH,
    FAILURE_STATUS_MISMATCH,
    CaseDecision,
    CaseHooks,
    run_suite,
)
from app.contract_suite import ContractCase
from app.verification_evidence import (
    ASSERTION_KIND_CUSTOM,
    ASSERTION_KIND_HEADER,
    ASSERTION_OUTCOME_FAILED,
    ASSERTION_OUTCOME_PASSED,
    OPERATION_OUTCOME_FAILED,
    OPERATION_OUTCOME_PASSED,
    OPERATION_OUTCOME_SKIPPED,
    OperationResultInput,
    VerificationRunInput,
    validate_run_input,
)
from tests.pact_verifier_fakes import PACT_GO, PACT_JS, PACT_JVM, LedgerApi, compile_fixture, target


def _run(name: str, api: LedgerApi, *, allow_mutating: bool = True, hooks: Optional[CaseHooks] = None):
    manifest = compile_fixture(name)
    client = api.client()
    try:
        return manifest, run_suite(manifest, target(allow_mutating=allow_mutating), client=client, hooks=hooks)
    finally:
        client.close()


def _by_operation(result, key: str) -> OperationResultInput:
    return next(operation for operation in result.operations if operation.operation_key == key)


# ---------------------------------------------------------------------------
# Fixtures from each client library verify against a conformant provider
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name, cases", [(PACT_JS, 2), (PACT_JVM, 2), (PACT_GO, 1)])
def test_a_conformant_provider_passes_every_interaction(name: str, cases: int) -> None:
    api = LedgerApi()
    manifest, result = _run(name, api)
    assert len(manifest.cases) == cases
    assert [operation.outcome for operation in result.operations] == [OPERATION_OUTCOME_PASSED] * cases
    assert all(a.outcome == ASSERTION_OUTCOME_PASSED for o in result.operations for a in o.assertions)


def test_the_request_is_replayed_as_recorded() -> None:
    api = LedgerApi()
    _run(PACT_GO, api)
    _run(PACT_JVM, api)
    summary, listing, create = (
        next(r for r in api.requests if (r.method, r.url.path) == wanted)
        for wanted in (("GET", "/summary"), ("GET", "/invoices"), ("POST", "/invoices"))
    )
    assert summary.url.query == b"year=2026"
    assert listing.url.query == b"status=open"
    assert create.headers["content-type"] == "application/json"
    assert create.content == b'{"customer":"acme","total":10}'


def test_passing_evidence_is_accepted_by_the_evidence_store_rules() -> None:
    manifest, result = _run(PACT_JS, LedgerApi())
    validate_run_input(
        VerificationRunInput(
            target_ref="ledger-staging",
            suite_digest=manifest.digest,
            runner_name="apiome-pact-verifier",
            started_at=result.started_at,
            finished_at=result.finished_at,
            operations=result.operations,
        )
    )


# ---------------------------------------------------------------------------
# Drift is located
# ---------------------------------------------------------------------------


def test_a_body_mismatch_names_the_pointer_the_rule_and_both_values() -> None:
    api = LedgerApi(
        {
            "GET /invoices/1042": lambda _request: httpx.Response(
                200,
                json={
                    "id": "1042",
                    "status": "archived",
                    "total": 129.5,
                    "issuedAt": "2026-11-02T09:30:00+00:00",
                    "lines": [{"sku": "SKU-1", "quantity": 2}, {"sku": "bad", "quantity": 1}],
                },
            )
        }
    )
    manifest, result = _run(PACT_JS, api)
    operation = _by_operation(result, "GET /invoices/1042")
    assert operation.outcome == OPERATION_OUTCOME_FAILED
    assert operation.failure_code == FAILURE_PACT_BODY_MISMATCH
    failed = [a for a in operation.assertions if a.outcome == ASSERTION_OUTCOME_FAILED]
    assert {a.subject for a in failed} == {"/id", "/status", "/lines/1/sku"}
    assert all(a.kind == ASSERTION_KIND_CUSTOM and a.code == FAILURE_PACT_BODY_MISMATCH for a in failed)
    by_subject = {a.subject: a for a in failed}
    assert by_subject["/id"].message == '$.id: expected an integer, got string "1042" (rule: integer)'
    assert by_subject["/status"].actual == '"archived"'
    assert by_subject["/lines/1/sku"].message.endswith("(rule: regex)")
    # A failing run is still evidence the store accepts.
    validate_run_input(
        VerificationRunInput(
            target_ref="ledger-staging",
            suite_digest=manifest.digest,
            runner_name="apiome-pact-verifier",
            started_at=result.started_at,
            finished_at=result.finished_at,
            operations=result.operations,
        )
    )


def test_a_header_mismatch_names_the_header() -> None:
    api = LedgerApi({"POST /invoices": lambda _request: httpx.Response(201, headers={"Location": "/orders/3"})})
    _, result = _run(PACT_JVM, api)
    operation = _by_operation(result, "POST /invoices")
    assert operation.failure_code == FAILURE_PACT_HEADER_MISMATCH
    (assertion,) = operation.assertions[1:]
    assert (assertion.kind, assertion.subject) == (ASSERTION_KIND_HEADER, "Location")
    assert "(rule: regex)" in assertion.message


def test_a_status_mismatch_ends_the_case_before_the_body_is_read() -> None:
    api = LedgerApi({"GET /invoices/9999": lambda _request: httpx.Response(200, json={"error": "x"})})
    _, result = _run(PACT_JS, api)
    operation = _by_operation(result, "GET /invoices/9999")
    assert operation.failure_code == FAILURE_STATUS_MISMATCH
    assert (operation.expected_status, operation.actual_status) == ("404", 200)
    assert len(operation.assertions) == 1


def test_a_status_code_rule_accepts_its_whole_class() -> None:
    conformant = LedgerApi().__call__

    def accepted(request: httpx.Request) -> httpx.Response:
        response = conformant(request)
        return httpx.Response(206, content=response.content, headers={"Content-Type": "application/json"})

    _, result = _run(PACT_JVM, LedgerApi({"GET /invoices": accepted}))
    assert _by_operation(result, "GET /invoices").outcome == OPERATION_OUTCOME_PASSED


def test_a_mutating_pact_case_obeys_the_target_policy() -> None:
    api = LedgerApi()
    _, result = _run(PACT_JVM, api, allow_mutating=False)
    operation = _by_operation(result, "POST /invoices")
    assert (operation.outcome, operation.failure_code) == (OPERATION_OUTCOME_SKIPPED, FAILURE_MUTATING_METHOD_BLOCKED)
    assert "POST /invoices" not in api.sent


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------


def test_hooks_surround_each_case_that_is_sent() -> None:
    api = LedgerApi()
    trail: List[str] = []

    def before(case: ContractCase) -> Optional[CaseDecision]:
        trail.append(f"before {case.operation_key} (sent so far: {len(api.requests)})")
        return None

    def after(case: ContractCase, result: OperationResultInput) -> None:
        trail.append(f"after {case.operation_key} {result.outcome}")

    _run(PACT_JS, api, hooks=CaseHooks(before=before, after=after))
    assert trail == [
        "before GET /invoices/1042 (sent so far: 0)",
        "after GET /invoices/1042 passed",
        "before GET /invoices/9999 (sent so far: 1)",
        "after GET /invoices/9999 passed",
    ]


def test_a_before_hook_can_hold_a_case_back_with_its_reason() -> None:
    api = LedgerApi()
    after_calls: List[str] = []

    def before(case: ContractCase) -> Optional[CaseDecision]:
        if case.operation_key.endswith("/1042"):
            return CaseDecision(run=False, skip_code="provider-state-setup-failed", skip_message="state unknown")
        return None

    hooks = CaseHooks(before=before, after=lambda case, _result: after_calls.append(case.operation_key))
    _, result = _run(PACT_JS, api, hooks=hooks)
    held = _by_operation(result, "GET /invoices/1042")
    assert (held.outcome, held.failure_code, held.failure_message) == (
        OPERATION_OUTCOME_SKIPPED,
        "provider-state-setup-failed",
        "state unknown",
    )
    assert api.sent == ["GET /invoices/9999"]
    assert after_calls == ["GET /invoices/9999"]


def test_a_before_hook_that_raises_skips_the_case_and_a_failing_after_hook_loses_nothing() -> None:
    api = LedgerApi()

    def before(case: ContractCase) -> Optional[CaseDecision]:
        if case.operation_key.endswith("/1042"):
            raise RuntimeError("state service down")
        return None

    def after(_case: ContractCase, _result: OperationResultInput) -> None:
        raise RuntimeError("teardown failed")

    _, result = _run(PACT_JS, api, hooks=CaseHooks(before=before, after=after))
    held = _by_operation(result, "GET /invoices/1042")
    assert (held.outcome, held.failure_code) == (OPERATION_OUTCOME_SKIPPED, FAILURE_CASE_HOOK_FAILED)
    assert "RuntimeError" in (held.failure_message or "")
    assert _by_operation(result, "GET /invoices/9999").outcome == OPERATION_OUTCOME_PASSED


def test_a_hook_cannot_lift_the_target_policy_gate() -> None:
    api = LedgerApi()
    hooks = CaseHooks(before=lambda _case: CaseDecision(run=True))
    _, result = _run(PACT_JVM, api, allow_mutating=False, hooks=hooks)
    assert _by_operation(result, "POST /invoices").failure_code == FAILURE_MUTATING_METHOD_BLOCKED
    assert "POST /invoices" not in api.sent


def test_a_run_with_hooks_sends_one_case_at_a_time() -> None:
    active = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def slow(request: httpx.Request) -> httpx.Response:
        with lock:
            active["now"] += 1
            active["peak"] = max(active["peak"], active["now"])
        time.sleep(0.02)
        with lock:
            active["now"] -= 1
        return LedgerApi()(request)

    manifest = compile_fixture(PACT_JS)
    client = httpx.Client(transport=httpx.MockTransport(slow))
    try:
        run_suite(manifest, target(max_concurrency=8), client=client, hooks=CaseHooks())
    finally:
        client.close()
    assert active["peak"] == 1
