"""Bi-directional verdicts, the pure part — PFX-2.3 (#6927).

* which provider versions a newly published pact is compared with;
* what a comparison is stored as (``success``, Pact-shaped test results, the payload);
* a pair that cannot be compared is stored as a failure with its reason;
* the run report and the notices a publish prints, nothing left out without a reason.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from app.bidirectional_verification import (
    CODE_NOT_COMPARABLE,
    STATUS_ALREADY_COMPARED,
    STATUS_COMPARED,
    STATUS_ERROR,
    STATUS_SKIPPED,
    ComparisonRun,
    ContractTarget,
    RunEntry,
    apply_evidence_policy,
    error_comparison,
    run_notices,
    select_contract_targets,
    stored_comparison,
)
from app.pact_oas_compare import compare_pact_to_oas
from app.provider_contract_evidence import Evidence, EvidenceSummary

FIXTURES = Path(__file__).parent / "fixtures" / "provider_contracts"
SHA = "c" * 64


def _oas() -> Dict[str, Any]:
    return json.loads((FIXTURES / "ledger-api-3.1.json").read_bytes())


def _pact(body: Any, path: str = "/invoices/42", **rules: Any) -> Dict[str, Any]:
    response: Dict[str, Any] = {"status": 200, "body": body}
    if rules:
        response["matchingRules"] = rules
    return {
        "consumer": {"name": "Billing Service"},
        "provider": {"name": "Ledger API"},
        "interactions": [
            {
                "description": "a request for an invoice",
                "request": {"method": "GET", "path": path},
                "response": response,
            }
        ],
        "metadata": {"pactSpecification": {"version": "2.0.0"}},
    }


def _target(version: str, seq: int, branches: tuple = (), environments: tuple = ()) -> ContractTarget:
    return ContractTarget(
        version_id=f"id-{version}",
        version_number=version,
        version_seq=seq,
        contract_id=f"c-{version}",
        contract_sha=SHA,
        branches=branches,
        environments=environments,
    )


# --- which provider versions a pact is compared with -------------------------------------------


def test_no_contract_means_nothing_to_compare() -> None:
    assert select_contract_targets([]) == []


def test_the_latest_the_branch_heads_and_every_running_version_are_selected() -> None:
    targets = [
        _target("p-1", 1, branches=("main",), environments=("production",)),
        _target("p-2", 2, branches=("main",)),
        _target("p-3", 3, branches=("feat/x",)),
        _target("p-4", 4, branches=("main",), environments=("staging",)),
        _target("p-5", 5, branches=("feat/x",)),
    ]
    selected = select_contract_targets(targets)
    assert [s.target.version_number for s in selected] == ["p-5", "p-4", "p-1"]
    assert selected[0].reasons == ["latest", "branch feat/x"]
    assert selected[1].reasons == ["branch main", "environment staging"]
    assert selected[2].reasons == ["environment production"]


def test_a_version_on_no_branch_is_still_compared_when_latest() -> None:
    selected = select_contract_targets([_target("p-1", 1), _target("p-2", 2)])
    assert [(s.target.version_number, s.reasons) for s in selected] == [("p-2", ["latest"])]


def test_order_of_the_input_does_not_matter() -> None:
    targets = [_target("p-2", 2, branches=("main",)), _target("p-1", 1, environments=("production",))]
    assert [s.target.version_number for s in select_contract_targets(targets)] == ["p-2", "p-1"]
    assert [s.target.version_number for s in select_contract_targets(targets[::-1])] == ["p-2", "p-1"]


# --- what is stored ----------------------------------------------------------------------------


def test_a_passing_comparison_is_a_successful_result_with_its_payload() -> None:
    stored = stored_comparison(compare_pact_to_oas(_pact({"id": 42, "total": 1999}), _oas()), contract_sha=SHA)
    assert stored.success is True and stored.verdict == "pass"
    assert stored.payload["verdict"] == "pass"
    assert stored.payload["providerContractSha"] == SHA
    assert stored.payload["summary"]["interactions"] == 1
    assert stored.test_results == [
        {"interactionDescription": "a request for an invoice", "success": True, "verdict": "pass"}
    ]


def test_a_failing_comparison_keeps_each_failure_as_a_mismatch() -> None:
    stored = stored_comparison(compare_pact_to_oas(_pact({"id": 42, "total": "lots"}), _oas()), contract_sha=SHA)
    assert stored.success is False and stored.verdict == "fail"
    [result] = stored.test_results
    assert result["success"] is False and result["verdict"] == "fail"
    assert result["mismatches"][0]["attribute"] == "response.body.schema-mismatch"
    assert result["mismatches"][0]["identifier"].startswith("/interactions/0/response/body")
    assert stored.payload["interactions"][0]["failures"][0]["code"] == "response.body.schema-mismatch"


def test_an_unknown_operation_fails_with_its_code() -> None:
    stored = stored_comparison(compare_pact_to_oas(_pact({"id": 1}, path="/refunds/1"), _oas()), contract_sha=SHA)
    assert stored.success is False
    assert stored.test_results[0]["mismatches"][0]["attribute"] == "request.operation.unknown"


def test_a_partial_comparison_passes_and_keeps_its_fidelity_notes() -> None:
    # A regex rule on an integer cannot be proven by the schema: compared by example only.
    pact = _pact({"id": 42, "total": 1999}, **{"$.body.id": {"match": "regex", "regex": "\\d+"}})
    stored = stored_comparison(compare_pact_to_oas(pact, _oas()), contract_sha=SHA)
    assert stored.verdict == "partial" and stored.success is True
    assert stored.payload["summary"]["fidelity"] >= 1
    assert stored.test_results[0]["success"] is True and stored.test_results[0]["verdict"] == "partial"


def test_mismatches_are_capped_but_the_payload_keeps_every_failure() -> None:
    body = {f"extra{i}": i for i in range(60)}
    stored = stored_comparison(compare_pact_to_oas(_pact(body), _oas()), contract_sha=SHA)
    assert len(stored.test_results[0]["mismatches"]) == 50
    assert len(stored.payload["interactions"][0]["failures"]) >= 50


def test_a_pair_that_cannot_be_compared_is_a_failure_with_its_reason() -> None:
    stored = error_comparison("the provider contract is not an OpenAPI 3.x document", contract_sha=SHA)
    assert stored.success is False and stored.verdict == "fail"
    assert stored.payload["error"] == {
        "code": CODE_NOT_COMPARABLE,
        "message": "the provider contract is not an OpenAPI 3.x document",
    }
    assert stored.payload["providerContractSha"] == SHA
    assert stored.test_results[0]["mismatches"][0]["attribute"] == CODE_NOT_COMPARABLE


# --- the run report ----------------------------------------------------------------------------


def _entry(status: str, **fields: Any) -> RunEntry:
    return RunEntry(
        consumer="Billing Service",
        consumer_version="2.0.0",
        provider="Ledger API",
        provider_version="5.1.0",
        sha=SHA,
        status=status,
        **fields,
    )


def test_the_run_counts_every_status_and_lists_every_pair() -> None:
    run = ComparisonRun(
        [
            _entry(STATUS_COMPARED, verdict="pass", number=1),
            _entry(STATUS_ALREADY_COMPARED, verdict="fail", number=2),
            _entry(STATUS_ERROR, reason="the result could not be stored (OperationalError)"),
            _entry(STATUS_SKIPPED, reason="over the limit of 20 provider versions compared per publish"),
        ]
    )
    payload = run.to_dict()
    assert {key: payload[key] for key in ("compared", "alreadyCompared", "errors", "skipped")} == {
        "compared": 1,
        "alreadyCompared": 1,
        "errors": 1,
        "skipped": 1,
    }
    assert payload["results"][0] == {
        "consumer": "Billing Service",
        "consumerVersion": "2.0.0",
        "provider": "Ledger API",
        "providerVersion": "5.1.0",
        "pactVersionSha": SHA,
        "status": "compared",
        "verdict": "pass",
        "verificationNumber": 1,
    }
    assert payload["results"][2]["reason"].startswith("the result could not be stored")


def test_notices_name_each_pair_and_stay_quiet_about_repeats() -> None:
    run = ComparisonRun(
        [
            _entry(STATUS_COMPARED, verdict="pass", number=1),
            _entry(STATUS_COMPARED, verdict="fail", number=2),
            _entry(STATUS_ALREADY_COMPARED, verdict="pass", number=1),
            _entry(STATUS_ERROR, reason="the pact version no longer exists"),
            _entry(STATUS_SKIPPED, reason="over the limit"),
        ]
    )
    notices = run_notices(run)
    pair = "the pact between Billing Service 2.0.0 and the provider contract of Ledger API 5.1.0"
    assert notices == [
        {"type": "success", "text": f"Bi-directional comparison of {pair}: pass."},
        {"type": "error", "text": f"Bi-directional comparison of {pair}: fail."},
        {
            "type": "warning",
            "text": f"Bi-directional comparison of {pair} failed to run: the pact version no longer exists.",
        },
        {"type": "warning", "text": f"Not compared: {pair} (over the limit)."},
    ]


def test_an_empty_run_prints_nothing() -> None:
    assert run_notices(ComparisonRun()) == []
    assert ComparisonRun().to_dict()["results"] == []


# --- PFX-2.4: the provider contract's self-verification evidence -------------------------------

_VERIFIED = Evidence(status="verified", kind="junit", tool="dredd", summary=EvidenceSummary(1, 1))
_FAILED = Evidence(status="failed", kind="junit", tool="dredd", reasons=("the report records 1 failed",))


def _passing() -> Any:
    return stored_comparison(compare_pact_to_oas(_pact({"id": 42, "total": 1999}), _oas()), contract_sha="b" * 64)


def test_verified_evidence_leaves_the_comparison_and_records_the_evidence() -> None:
    stored = apply_evidence_policy(_passing(), _VERIFIED, "fail")
    assert (stored.success, stored.verdict) == (True, "pass")
    assert stored.payload["providerContractEvidence"]["status"] == "verified"
    assert "comparisonVerdict" not in stored.payload
    assert len(stored.test_results) == len(_passing().test_results)


def test_unverified_evidence_warns_under_warn() -> None:
    stored = apply_evidence_policy(_passing(), _FAILED, "warn")
    assert (stored.success, stored.verdict) == (True, "unverified")
    assert (stored.payload["verdict"], stored.payload["comparisonVerdict"], stored.payload["unverifiedPolicy"]) == (
        "unverified",
        "pass",
        "warn",
    )
    last = stored.test_results[-1]
    assert last["success"] is True and last["warnings"][0]["attribute"] == "provider-contract-unverified"
    assert "the report records 1 failed" in last["warnings"][0]["description"]


def test_unverified_evidence_fails_under_fail() -> None:
    stored = apply_evidence_policy(_passing(), None, "fail")
    assert (stored.success, stored.verdict) == (False, "unverified")
    assert stored.payload["success"] is False
    assert stored.payload["providerContractEvidence"]["status"] == "missing"
    assert stored.test_results[-1]["mismatches"][0]["attribute"] == "provider-contract-unverified"


def test_a_failed_comparison_stays_failed_when_unverified() -> None:
    failing = stored_comparison(compare_pact_to_oas(_pact({"id": 42, "total": "lots"}), _oas()), contract_sha="b" * 64)
    stored = apply_evidence_policy(failing, None, "warn")
    assert (stored.success, stored.verdict, stored.payload["comparisonVerdict"]) == (False, "fail", "fail")


def test_an_unverified_notice_is_a_warning_or_an_error_by_success() -> None:
    warned = _entry(STATUS_COMPARED, verdict="unverified", number=1, success=True)
    failed = _entry(STATUS_COMPARED, verdict="unverified", number=2, success=False)
    notices = run_notices(ComparisonRun([warned, failed]))
    assert [n["type"] for n in notices] == ["warning", "error"]
    assert "no passing self-verification evidence" in notices[0]["text"]
    assert warned.to_dict()["success"] is True
