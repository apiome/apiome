"""Reading self-verification evidence — PFX-2.4 (#6928).

The reports under ``fixtures/provider_contracts/evidence/`` were written by the real tools against
one small Ledger API (``ledger-api-evidence.yaml``), once with a server that honours it (``*-pass``)
and once with one that does not (``*-fail``): Schemathesis 4.34 (``--report junit,ndjson``), Dredd
14.1 (``--reporter xunit``) and Newman 6 (``-r json,junit``). Only the runner's hostname was
replaced (``ci-runner``).
"""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from app.provider_contract import CODE_REQUEST_INVALID, ProviderContractError
from app.provider_contract_evidence import (
    CODE_EVIDENCE_INVALID,
    CODE_EVIDENCE_TOO_LARGE,
    CODE_EVIDENCE_UNSUPPORTED,
    KIND_APIOME_REPORT,
    KIND_JUNIT,
    KIND_NEWMAN_JSON,
    KIND_SCHEMATHESIS_NDJSON,
    KIND_UNREADABLE,
    STATUS_FAILED,
    STATUS_INCONCLUSIVE,
    STATUS_MISSING,
    STATUS_VERIFIED,
    ContractSource,
    Evidence,
    EvidenceSummary,
    decode_report,
    evidence_from_conformance_report,
    evidence_of,
    missing_evidence,
    read_uploaded_report,
    unsent_evidence,
)

EVIDENCE = Path(__file__).parent / "fixtures" / "provider_contracts" / "evidence"
LIMIT = 5 * 1024 * 1024


def _fixture(name: str) -> bytes:
    return (EVIDENCE / name).read_bytes()


def _read(
    raw: bytes,
    content_type: Optional[str] = None,
    *,
    verifier: Optional[str] = None,
    success: Optional[bool] = True,
    max_bytes: int = LIMIT,
) -> Evidence:
    return read_uploaded_report(
        raw, content_type=content_type, verifier=verifier, verifier_version=None, success=success, max_bytes=max_bytes
    )


def _refusal(raw: bytes, content_type: Optional[str] = None, **kwargs: Any) -> ProviderContractError:
    with pytest.raises(ProviderContractError) as caught:
        _read(raw, content_type, **kwargs)
    return caught.value


# ---------------------------------------------------------------------------------------------
# One worked example per tool: the real reports
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, content_type, verifier, kind, tool, summary",
    [
        ("schemathesis-pass.junit.xml", "application/xml", "schemathesis", KIND_JUNIT, "schemathesis", (1, 1, 0, 0, 0)),
        (
            "schemathesis-pass.ndjson",
            "application/x-ndjson",
            None,
            KIND_SCHEMATHESIS_NDJSON,
            "schemathesis",
            (3, 2, 0, 0, 1),
        ),
        ("dredd-pass.xml", "application/xml", "dredd", KIND_JUNIT, "dredd", (1, 1, 0, 0, 0)),
        ("newman-pass.json", "application/json", "newman", KIND_NEWMAN_JSON, "newman", (3, 3, 0, 0, 0)),
        ("newman-pass.junit.xml", "application/xml", "newman", KIND_JUNIT, "newman", (3, 3, 0, 0, 0)),
    ],
)
def test_a_passing_report_verifies_the_contract(
    name: str, content_type: str, verifier: Optional[str], kind: str, tool: str, summary: tuple
) -> None:
    raw = _fixture(name)
    evidence = _read(raw, content_type, verifier=verifier)
    assert (evidence.status, evidence.kind, evidence.tool) == (STATUS_VERIFIED, kind, tool)
    assert evidence.summary == EvidenceSummary(*summary)
    assert evidence.reasons == ()
    assert evidence.digest is not None and evidence.digest.startswith("sha256:") and len(evidence.digest) == 71


@pytest.mark.parametrize(
    "name, content_type, failed",
    [
        ("schemathesis-fail.junit.xml", "application/xml", 1),
        ("schemathesis-fail.ndjson", "application/x-ndjson", 2),
        ("dredd-fail.xml", "application/xml", 1),
        ("newman-fail.json", "application/json", 1),
        ("newman-fail.junit.xml", "application/xml", 1),
    ],
)
def test_a_failing_report_fails_the_evidence_even_with_success_true(name: str, content_type: str, failed: int) -> None:
    evidence = _read(_fixture(name), content_type, success=True)
    assert evidence.status == STATUS_FAILED
    assert evidence.summary is not None and evidence.summary.failed == failed
    assert "although success: true was sent" in evidence.reasons[0]


def test_the_tool_is_detected_without_a_verifier() -> None:
    assert _read(_fixture("schemathesis-pass.junit.xml"), "application/xml").tool == "schemathesis"
    assert _read(_fixture("dredd-pass.xml"), "application/xml").tool == "dredd"
    assert _read(_fixture("newman-pass.junit.xml"), "application/xml").tool == "junit"


def test_the_schemathesis_version_is_read_from_the_stream() -> None:
    assert _read(_fixture("schemathesis-pass.ndjson"), "application/x-ndjson").tool_version == "4.34.2"


def test_the_content_type_is_sniffed_when_omitted() -> None:
    assert _read(_fixture("dredd-pass.xml")).kind == KIND_JUNIT
    assert _read(_fixture("newman-pass.json")).kind == KIND_NEWMAN_JSON
    assert _read(_fixture("schemathesis-pass.ndjson")).kind == KIND_SCHEMATHESIS_NDJSON


def test_ndjson_sent_as_application_json_is_still_read() -> None:
    assert _read(_fixture("schemathesis-pass.ndjson"), "application/json").kind == KIND_SCHEMATHESIS_NDJSON


def test_a_verifier_that_disagrees_with_the_report_is_noted() -> None:
    evidence = _read(_fixture("newman-pass.json"), "application/json", verifier="schemathesis")
    assert evidence.tool == "newman"
    assert evidence.notes == ("verifier 'schemathesis' was sent, but the report was written by newman",)
    assert evidence.status == STATUS_VERIFIED


def test_content_type_parameters_are_ignored() -> None:
    assert _read(_fixture("dredd-pass.xml"), "application/xml; charset=utf-8").status == STATUS_VERIFIED


# ---------------------------------------------------------------------------------------------
# What proves nothing: inconclusive
# ---------------------------------------------------------------------------------------------


def test_a_text_report_is_stored_but_inconclusive() -> None:
    evidence = _read(b"All 12 checks passed", "text/plain", verifier="schemathesis")
    assert (evidence.status, evidence.kind, evidence.tool) == (STATUS_INCONCLUSIVE, KIND_UNREADABLE, "schemathesis")
    assert "cannot read a text/plain report" in evidence.reasons[0]
    assert evidence.digest is not None


def test_a_text_report_with_success_false_fails() -> None:
    evidence = _read(b"2 checks failed", "text/plain", success=False)
    assert evidence.status == STATUS_FAILED


def test_an_unknown_json_report_is_inconclusive_with_the_formats_apiome_reads() -> None:
    evidence = _read(b'{"passed": 12}', "application/json")
    assert (evidence.status, evidence.kind) == (STATUS_INCONCLUSIVE, KIND_UNREADABLE)
    assert "Newman JSON" in evidence.reasons[0] and "JUnit XML" in evidence.reasons[0]


def test_a_report_that_executed_nothing_is_inconclusive() -> None:
    evidence = _read(b'<testsuite tests="1"><testcase name="a"><skipped/></testcase></testsuite>', "application/xml")
    assert evidence.status == STATUS_INCONCLUSIVE
    assert evidence.reasons == ("the report executed no tests (1 recorded, 1 skipped)",)


def test_an_empty_junit_report_is_inconclusive() -> None:
    assert _read(b"<testsuites/>", "application/xml").status == STATUS_INCONCLUSIVE


def test_a_schemathesis_run_that_did_not_finish_is_inconclusive() -> None:
    lines = _fixture("schemathesis-pass.ndjson").decode().splitlines()
    truncated = "\n".join(line for line in lines if not line.startswith('{"EngineFinished"')).encode()
    evidence = _read(truncated, "application/x-ndjson")
    assert evidence.status == STATUS_INCONCLUSIVE
    assert "did not finish" in evidence.reasons[0]


def test_success_false_with_a_clean_report_fails() -> None:
    evidence = _read(_fixture("dredd-pass.xml"), "application/xml", success=False)
    assert evidence.status == STATUS_FAILED
    assert "success: false" in evidence.reasons[0]


def test_junit_errors_and_skips_are_counted_from_test_cases() -> None:
    raw = (
        b'<testsuites tests="99"><testsuite name="x">'
        b'<testcase name="ok"/><testcase name="bad"><failure/></testcase>'
        b'<testcase name="boom"><error/></testcase><testcase name="later"><skipped/></testcase>'
        b"</testsuite></testsuites>"
    )
    assert _read(raw, "application/xml").summary == EvidenceSummary(4, 1, 1, 1, 1)


def test_namespaced_junit_is_read() -> None:
    raw = b'<j:testsuite xmlns:j="urn:x"><j:testcase name="a"/></j:testsuite>'
    assert _read(raw, "text/xml").status == STATUS_VERIFIED


def test_a_success_flag_alone_is_inconclusive_and_false_alone_fails() -> None:
    assert unsent_evidence(True, verifier="dredd", verifier_version="14").status == STATUS_INCONCLUSIVE
    failed = unsent_evidence(False, verifier=None, verifier_version=None)
    assert failed.status == STATUS_FAILED and failed.tool is None


def test_no_results_are_missing_evidence() -> None:
    assert missing_evidence().status == STATUS_MISSING
    assert evidence_of(None, max_bytes=LIMIT).status == STATUS_MISSING


# ---------------------------------------------------------------------------------------------
# What is refused, with a pointer
# ---------------------------------------------------------------------------------------------


def test_a_report_over_the_limit_is_refused() -> None:
    error = _refusal(_fixture("newman-pass.json"), "application/json", max_bytes=1024)
    assert (error.code, error.pointer) == (CODE_EVIDENCE_TOO_LARGE, "/verificationResults/content")


@pytest.mark.parametrize("content_type", ["image/png", "application/pdf", "text/html"])
def test_a_media_type_no_report_is_read_as_is_refused(content_type: str) -> None:
    error = _refusal(b"\x89PNG", content_type)
    assert (error.code, error.pointer) == (CODE_EVIDENCE_UNSUPPORTED, "/verificationResults/contentType")


def test_xml_that_does_not_parse_is_refused() -> None:
    error = _refusal(b"<testsuite><testcase>", "application/xml")
    assert error.code == CODE_EVIDENCE_INVALID and "not well-formed XML" in str(error)


def test_xml_that_is_not_junit_is_refused() -> None:
    error = _refusal(b"<html><body/></html>", "application/xml")
    assert error.code == CODE_EVIDENCE_INVALID and "<html>" in str(error)


def test_xml_with_a_dtd_is_refused() -> None:
    bomb = b'<?xml version="1.0"?><!DOCTYPE t [<!ENTITY a "aaaa">]><testsuite><testcase name="&a;"/></testsuite>'
    error = _refusal(bomb, "application/xml")
    assert error.code == CODE_EVIDENCE_INVALID and "DTD" in str(error)


def test_json_that_is_not_json_is_refused() -> None:
    error = _refusal(b'{"run": ', "application/json")
    assert error.code == CODE_EVIDENCE_INVALID and "not JSON" in str(error)


def test_an_ndjson_line_that_is_not_json_is_refused_with_its_line() -> None:
    error = _refusal(b'{"Initialize": {"schemathesis_version": "4"}}\nnot json\n', "application/x-ndjson")
    assert error.code == CODE_EVIDENCE_INVALID and "line 2" in str(error)


def test_a_report_that_is_not_utf8_is_refused() -> None:
    error = _refusal(b"\xff\xfe<\x00t\x00", "application/xml")
    assert error.code == CODE_EVIDENCE_INVALID and "UTF-8" in str(error)


def test_bad_base64_is_refused_at_the_content() -> None:
    with pytest.raises(ProviderContractError) as caught:
        decode_report("%%%")
    assert (caught.value.code, caught.value.pointer) == (CODE_REQUEST_INVALID, "/verificationResults/content")


# ---------------------------------------------------------------------------------------------
# An Apiome provider-verification report
# ---------------------------------------------------------------------------------------------


def _record(outcome: str = "passed", failed: int = 0, errored: int = 0, version: str = "1.4.0") -> Any:
    """A stand-in for a ``ConformanceReportRecord`` with the fields the reader uses."""
    report = SimpleNamespace(model_dump=lambda mode="json": {"outcome": outcome, "suite_digest": "d"})
    return SimpleNamespace(
        id="6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b",
        outcome=outcome,
        artifact_id="proj-1",
        artifact_slug="ledger-api",
        version_label=version,
        target_slug="staging-ledger",
        target_environment="staging",
        cases_total=10,
        cases_passed=10 - failed - errored,
        cases_failed=failed,
        cases_errored=errored,
        cases_skipped=0,
        operations_total=4,
        operations_exercised=3,
        coverage_percent=75.0,
        report=report,
    )


SOURCE = ContractSource("proj-1", "ledger-api", "1.4.0")


def test_a_passing_report_of_the_same_version_verifies() -> None:
    evidence = evidence_from_conformance_report(_record(), success=None, source=SOURCE)
    assert (evidence.status, evidence.kind, evidence.tool) == (
        STATUS_VERIFIED,
        KIND_APIOME_REPORT,
        "apiome-provider-verifier",
    )
    assert evidence.report_id == "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b"
    assert evidence.target == {"slug": "staging-ledger", "environment": "staging"}
    assert evidence.coverage == {"operationsTotal": 4, "operationsExercised": 3, "percent": 75.0}
    assert evidence.digest is not None and evidence.digest.startswith("sha256:")


def test_a_failed_report_fails() -> None:
    evidence = evidence_from_conformance_report(_record("failed", failed=2), success=None, source=SOURCE)
    assert evidence.status == STATUS_FAILED


def test_an_errored_report_without_counted_errors_fails_on_its_outcome() -> None:
    evidence = evidence_from_conformance_report(_record("errored"), success=None, source=SOURCE)
    assert evidence.status == STATUS_INCONCLUSIVE
    assert "outcome is 'errored'" in evidence.reasons[0]


def test_a_report_of_another_version_is_inconclusive() -> None:
    evidence = evidence_from_conformance_report(_record(version="1.3.0"), success=None, source=SOURCE)
    assert evidence.status == STATUS_INCONCLUSIVE
    assert "verified ledger-api@1.3.0, but the contract was rendered from ledger-api@1.4.0" in evidence.reasons[0]


def test_an_inline_contract_is_noted_as_not_tied_to_the_report() -> None:
    evidence = evidence_from_conformance_report(_record(), success=None, source=None)
    assert evidence.status == STATUS_VERIFIED
    assert "sent inline" in evidence.notes[0]


def test_a_success_flag_that_contradicts_the_report_fails() -> None:
    evidence = evidence_from_conformance_report(_record(), success=False, source=SOURCE)
    assert evidence.status == STATUS_FAILED


# ---------------------------------------------------------------------------------------------
# Stored evidence
# ---------------------------------------------------------------------------------------------


def test_evidence_round_trips_through_storage() -> None:
    evidence = _read(_fixture("schemathesis-fail.ndjson"), "application/x-ndjson")
    assert Evidence.from_dict(evidence.to_dict()) == evidence


def test_stored_evidence_is_read_back_not_recomputed() -> None:
    stored = {"success": True, "content": "%%%", "evidence": {"status": "verified", "kind": "junit"}}
    assert evidence_of(stored, max_bytes=LIMIT).status == STATUS_VERIFIED


def test_an_unknown_stored_status_reads_inconclusive() -> None:
    assert Evidence.from_dict({"status": "great"}).status == STATUS_INCONCLUSIVE


def test_a_publication_from_before_evidence_is_read_now() -> None:
    content = base64.b64encode(_fixture("dredd-fail.xml")).decode()
    stored = {"success": True, "content": content, "contentType": "application/xml", "verifier": "dredd"}
    assert evidence_of(stored, max_bytes=LIMIT).status == STATUS_FAILED


def test_a_publication_from_before_evidence_with_a_flag_only_is_inconclusive() -> None:
    assert evidence_of({"success": True}, max_bytes=LIMIT).status == STATUS_INCONCLUSIVE


def test_a_publication_from_before_evidence_with_an_unreadable_report_is_inconclusive() -> None:
    stored = {"success": True, "content": base64.b64encode(b"<oops").decode(), "contentType": "application/xml"}
    evidence = evidence_of(stored, max_bytes=LIMIT)
    assert (evidence.status, evidence.kind) == (STATUS_INCONCLUSIVE, KIND_UNREADABLE)
