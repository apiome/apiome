"""The comparison fidelity report — PFX-2.5 (#6929). Pure.

:func:`app.pact_comparison_fidelity.build_fidelity_report` over the PFX-2.2 golden corpus and a few
hand-made payloads:

* **the tables hold together** — every fidelity code is in exactly one group, every failure and
  warning code belongs to a core check;
* **nothing is dropped** — over every golden comparison, each fidelity note is reported exactly
  once and each failure is attributed to a ``failed`` check;
* **a green verdict is never stronger than it is** — ``full`` only when every core check ran with
  nothing to report; a check that did not run says why;
* the evidence policy (PFX-2.4), the "could not compare at all" payload and malformed payloads.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.bidirectional_verification import POLICY_WARN, apply_evidence_policy, error_comparison, stored_comparison
from app.pact_comparison_fidelity import (
    CHECK_COMPARED,
    CHECK_FAILED,
    CHECK_LABELS,
    CHECK_NOT_RUN,
    CHECK_PARTIAL,
    CORE_CHECKS,
    MATCHING_RULE_CODES,
    NOT_COMPARED_CODES,
    STRENGTH_FAILED,
    STRENGTH_FULL,
    STRENGTH_NONE,
    STRENGTH_PARTIAL,
    build_fidelity_report,
    check_of_finding,
    check_of_note,
)
from app.pact_oas_result import FAILURE_CLASSES, FIDELITY_CLASSES, WARNING_CLASSES, ComparisonResult

_EXPECTED = Path(__file__).parent / "golden" / "pact_oas_compare" / "expected"
_GOLDENS = sorted(_EXPECTED.glob("*.json"))


def _golden(name: str) -> Dict[str, Any]:
    """One golden comparison payload by file stem."""
    return json.loads((_EXPECTED / f"{name}.json").read_text())


def _checks(report: Dict[str, Any], index: int = 0) -> Dict[str, Dict[str, Any]]:
    """The checks of one interaction, by key."""
    return {check["check"]: check for check in report["interactions"][index]["checks"]}


# --- the tables -------------------------------------------------------------------------------


def test_every_fidelity_code_is_in_exactly_one_group() -> None:
    from app.pact_asyncapi_compare import MESSAGE_FIDELITY_CLASSES

    assert set(MATCHING_RULE_CODES) | set(NOT_COMPARED_CODES) == set(FIDELITY_CLASSES) | set(
        MESSAGE_FIDELITY_CLASSES
    )
    assert set(MATCHING_RULE_CODES) & set(NOT_COMPARED_CODES) == set()


@pytest.mark.parametrize("code", sorted(FAILURE_CLASSES) + sorted(WARNING_CLASSES))
def test_every_failure_and_warning_code_belongs_to_a_core_check(code: str) -> None:
    assert check_of_finding(code) in CORE_CHECKS


def test_the_core_checks_are_the_labelled_checks_without_matching_rules() -> None:
    assert CORE_CHECKS == (
        "request.operation",
        "request.path-parameters",
        "request.query",
        "request.headers",
        "request.body",
        "response.status",
        "response.headers",
        "response.body",
    )
    assert set(CHECK_LABELS) - set(CORE_CHECKS) == {"request.matching-rules", "response.matching-rules"}


@pytest.mark.parametrize(
    ("pointer", "check"),
    [
        ("/interactions/2/request/body/items/0", "request.body"),
        ("/interactions/2/request/query/limit", "request.query"),
        ("/interactions/2/request/path", "request.path-parameters"),
        ("/interactions/2/request/matchingRules/body/$.id", "request.matching-rules"),
        ("/interactions/2/response/generators/body/$.id", "response.matching-rules"),
        ("/interactions/2/response/headers/ETag", "response.headers"),
        ("/interactions/2", None),
        ("/interactions/2/messages/0", None),
        ("/interactions/20/request/body", None),
    ],
)
def test_a_note_belongs_to_the_check_its_pointer_names(pointer: str, check: str) -> None:
    assert check_of_note(pointer, "/interactions/2") == check


# --- nothing dropped, over the whole corpus ---------------------------------------------------


@pytest.mark.parametrize("path", _GOLDENS, ids=[path.stem for path in _GOLDENS])
def test_every_golden_report_keeps_every_note_and_failure(path: Path) -> None:
    payload = json.loads(path.read_text())
    report = build_fidelity_report(payload)
    assert report == build_fidelity_report(copy.deepcopy(payload)), "deterministic"
    assert len(report["interactions"]) == len(payload["interactions"])
    for stored, item in zip(payload["interactions"], report["interactions"]):
        listed = item["unsupportedMatchingRules"] + item["couldNotCompare"]
        assert sorted(note["pactPointer"] + note["code"] for note in listed) == sorted(
            note["pactPointer"] + note["code"] for note in stored["fidelity"]
        )
        checks = {check["check"]: check for check in item["checks"]}
        for check in stored["checks"]:
            assert checks[check]["status"] != CHECK_NOT_RUN, f"{check} ran"
        for finding in stored["failures"]:
            assert checks[check_of_finding(finding["code"])]["status"] == CHECK_FAILED
        for check in item["checks"]:
            if check["status"] == CHECK_NOT_RUN:
                assert check["reason"]
        assert item["failures"] == len(stored["failures"])


@pytest.mark.parametrize("path", _GOLDENS, ids=[path.stem for path in _GOLDENS])
def test_the_strength_follows_the_verdict_and_never_overstates_it(path: Path) -> None:
    payload = json.loads(path.read_text())
    report = build_fidelity_report(payload)
    if payload["verdict"] == "fail":
        assert report["strength"] == STRENGTH_FAILED
    elif report["strength"] == STRENGTH_FULL:
        assert payload["verdict"] == "pass"
        for item in report["interactions"]:
            assert all(check["status"] == CHECK_COMPARED for check in item["checks"])
            assert item["couldNotCompare"] == [] and item["unsupportedMatchingRules"] == []
    else:
        assert report["strength"] in (STRENGTH_PARTIAL, STRENGTH_NONE)
    assert report["statement"].endswith(".")


# --- what each kind of gap reads as -----------------------------------------------------------


def test_a_fully_compared_pass_says_nothing_was_left_out() -> None:
    report = build_fidelity_report(_golden("pass-01-get-invoice-v2"))
    assert report["strength"] == STRENGTH_FULL
    assert report["summary"]["fullyCompared"] == report["summary"]["interactions"]
    assert report["statement"].startswith("Every check ran")


def test_a_failed_operation_says_why_the_later_checks_did_not_run() -> None:
    report = build_fidelity_report(_golden("fail-02-operation-unknown"))
    checks = _checks(report)
    assert checks["request.operation"]["status"] == CHECK_FAILED
    assert checks["request.operation"]["failures"] == 1
    for key in CORE_CHECKS[1:]:
        assert checks[key]["status"] == CHECK_NOT_RUN
        assert checks[key]["reason"] == "not run because an earlier check failed (Operation (method and path))"
    assert report["summary"]["checksNotRun"] == 7
    assert report["statement"] == "The provider contract contradicts 1 of 1 interaction; also 7 checks not run."


def test_a_relaxed_oneof_marks_the_response_body_partial() -> None:
    report = build_fidelity_report(_golden("partial-19-oneof-relaxed"))
    assert report["strength"] == STRENGTH_PARTIAL
    assert _checks(report)["response.body"]["status"] == CHECK_PARTIAL
    notes = report["interactions"][0]["couldNotCompare"]
    assert [note["code"] for note in notes] == ["oneof-relaxed"]
    assert notes[0]["check"] == "response.body"
    assert report["statement"].startswith("Passed, but not everything was compared: 0 of 1 interaction")


def test_an_unmapped_rule_is_listed_as_unsupported_under_its_check() -> None:
    report = build_fidelity_report(_golden("partial-06-status-code-rule"))
    item = report["interactions"][0]
    assert [note["code"] for note in item["unsupportedMatchingRules"]] == ["matching-rule-not-mapped"]
    assert item["unsupportedMatchingRules"][0]["check"] == "response.matching-rules"
    assert _checks(report)["response.matching-rules"]["status"] == CHECK_PARTIAL
    assert report["summary"]["unsupportedMatchingRules"] == 1


def test_generators_without_rules_still_get_a_check() -> None:
    report = build_fidelity_report(_golden("partial-13-generators"))
    generator_checks = {
        note["check"]
        for item in report["interactions"]
        for note in item["unsupportedMatchingRules"]
        if note["code"] == "generator-not-applied"
    }
    assert generator_checks
    for check in generator_checks:
        assert _checks(report)[check]["status"] == CHECK_PARTIAL


def test_a_message_pact_compares_nothing_and_says_so() -> None:
    report = build_fidelity_report(_golden("partial-21-message-pact-v3"))
    assert report["strength"] == STRENGTH_NONE
    for check in report["interactions"][0]["checks"]:
        assert check["status"] == CHECK_NOT_RUN
        assert check["reason"] == "the interaction has no HTTP exchange to compare"
    assert report["summary"]["notCompared"] == len(report["interactions"])
    assert report["statement"].startswith("Nothing was compared")


def test_an_empty_pact_compares_nothing() -> None:
    report = build_fidelity_report(_golden("pass-27-no-interactions"))
    assert report["strength"] == STRENGTH_NONE
    assert report["statement"] == "Nothing was compared: the pact has no interactions."


# --- the stored payload as PFX-2.3 / PFX-2.4 write it -----------------------------------------


def _pass_result() -> ComparisonResult:
    """A comparison result rebuilt from a passing golden."""
    payload = _golden("pass-01-get-invoice-v2")
    result = ComparisonResult(
        consumer=payload["consumer"],
        provider=payload["provider"],
        pact_specification=payload["pactSpecification"],
        oas_version=payload["oasVersion"],
    )
    return result


def test_an_unverified_contract_keeps_the_comparison_verdict_and_the_evidence_status() -> None:
    stored = stored_comparison(_pass_result(), contract_sha="cd" * 32)
    weighed = apply_evidence_policy(stored, None, POLICY_WARN)
    payload = weighed.payload
    payload["interactions"] = _golden("pass-01-get-invoice-v2")["interactions"]
    report = build_fidelity_report(payload)
    assert report["verdict"] == "unverified"
    assert report["comparisonVerdict"] == "pass"
    assert report["strength"] == STRENGTH_FULL
    assert report["selfVerification"] == "missing"
    assert report["providerContractSha"] == "cd" * 32


def test_a_comparison_that_could_not_run_reports_its_error() -> None:
    report = build_fidelity_report(
        error_comparison("the provider contract is not OpenAPI 3.x", contract_sha="ef" * 32).payload
    )
    assert report["strength"] == STRENGTH_NONE
    assert report["error"] == {"code": "comparison-not-possible", "message": "the provider contract is not OpenAPI 3.x"}
    assert report["statement"] == "Nothing was compared: the provider contract is not OpenAPI 3.x."
    assert report["interactions"] == []


def test_an_unknown_fidelity_code_is_still_reported() -> None:
    payload = _golden("pass-01-get-invoice-v2")
    payload["verdict"] = "partial"
    payload["interactions"][0]["verdict"] = "partial"
    payload["interactions"][0]["fidelity"] = [
        {"code": "from-a-newer-engine", "message": "something new", "pactPointer": "/interactions/0/request/body"}
    ]
    report = build_fidelity_report(payload)
    notes: List[Dict[str, Any]] = report["interactions"][0]["couldNotCompare"]
    assert [note["code"] for note in notes] == ["from-a-newer-engine"]
    assert report["strength"] == STRENGTH_PARTIAL


@pytest.mark.parametrize("payload", [{}, {"interactions": "nope"}, {"interactions": [None, 3]}])
def test_a_malformed_payload_reads_as_nothing_compared(payload: Dict[str, Any]) -> None:
    report = build_fidelity_report(payload)
    assert report["strength"] == STRENGTH_NONE
    assert report["summary"]["checksCompared"] == 0
