"""The verification-result body and record — PFX-1.4 (#6917).

The pure part of publishing a result (:mod:`app.verification_result`) and the metadata a
for-verification link carries (:func:`app.pact_selectors.decode_metadata`):

* the body is the Pact Broker's: ``success`` and ``providerApplicationVersion`` are required, the
  rest optional; a malformed field is ``pact-verification-invalid`` with its pointer;
* ``testResults`` are kept as sent, so a failure keeps its mismatches;
* ``verifiedBy`` and its ``clientLanguage`` become the five stored labels;
* ``providerVerificationReportId`` (Apiome only) must be a UUID;
* the metadata Apiome encoded in a for-verification URL reads back as the pending and WIP flags.
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Dict

import pytest

from app.pact_publication import PactPublicationError
from app.pact_selectors import decode_metadata, encode_metadata
from app.pacticipant import CODE_INVALID_URL, CODE_INVALID_VERSION, PacticipantValidationError
from app.verification_result import (
    CODE_VERIFICATION_INVALID,
    MAX_TEST_RESULTS,
    parse_verification_request,
    verification_result_from_row,
)

_FAILED = {
    "success": False,
    "providerApplicationVersion": "4f1e2d0",
    "buildUrl": "https://ci.example.com/builds/77",
    "testResults": [
        {
            "interactionId": "a1",
            "interactionDescription": "a request for an invoice",
            "success": False,
            "mismatches": [{"attribute": "status", "description": "expected 200 but was 404"}],
        }
    ],
    "verifiedBy": {
        "implementation": "Pact-Rust",
        "version": "1.2.0",
        "clientLanguage": {"name": "pact-js", "version": "13.1.0", "testFramework": "jest"},
    },
}


def _parse(body: Any):
    return parse_verification_request(json.dumps(body).encode())


def test_a_verifier_body_is_read_with_its_test_detail() -> None:
    request = _parse(_FAILED)
    assert request.success is False
    assert request.provider_version == "4f1e2d0"
    assert request.build_url == "https://ci.example.com/builds/77"
    assert request.test_results == _FAILED["testResults"]
    assert request.verified_by == {
        "implementation": "Pact-Rust",
        "version": "1.2.0",
        "client_implementation": "pact-js",
        "client_version": "13.1.0",
        "client_test_framework": "jest",
    }
    assert request.report_id is None


def test_the_smallest_body_is_success_and_a_version() -> None:
    request = _parse({"success": True, "providerApplicationVersion": "1.0.0", "unknown": "ignored"})
    assert request.success is True and request.test_results == [] and request.build_url is None
    assert set(request.verified_by.values()) == {None}


def test_a_report_id_is_normalised() -> None:
    report = "1F2E3D4C-0000-4000-8000-000000000001"
    assert _parse({**_FAILED, "providerVerificationReportId": report}).report_id == report.lower()


@pytest.mark.parametrize(
    ("body", "pointer"),
    [
        ([], ""),
        ({"providerApplicationVersion": "1"}, "/success"),
        ({"success": "true", "providerApplicationVersion": "1"}, "/success"),
        ({"success": True}, "/providerApplicationVersion"),
        ({"success": True, "providerApplicationVersion": "  "}, "/providerApplicationVersion"),
        ({"success": True, "providerApplicationVersion": 7}, "/providerApplicationVersion"),
        ({"success": True, "providerApplicationVersion": "1", "buildUrl": 3}, "/buildUrl"),
        ({"success": True, "providerApplicationVersion": "1", "testResults": {}}, "/testResults"),
        ({"success": True, "providerApplicationVersion": "1", "verifiedBy": "rust"}, "/verifiedBy"),
        (
            {"success": True, "providerApplicationVersion": "1", "verifiedBy": {"version": 2}},
            "/verifiedBy/version",
        ),
        (
            {"success": True, "providerApplicationVersion": "1", "verifiedBy": {"clientLanguage": []}},
            "/verifiedBy/clientLanguage",
        ),
        (
            {"success": True, "providerApplicationVersion": "1", "verifiedBy": {"implementation": "x" * 256}},
            "/verifiedBy/implementation",
        ),
        (
            {"success": True, "providerApplicationVersion": "1", "providerVerificationReportId": "report-1"},
            "/providerVerificationReportId",
        ),
        (
            {"success": True, "providerApplicationVersion": "1", "testResults": [{}] * (MAX_TEST_RESULTS + 1)},
            "/testResults",
        ),
    ],
)
def test_a_malformed_body_is_refused_with_a_pointer(body: Any, pointer: str) -> None:
    with pytest.raises(PactPublicationError) as caught:
        _parse(body)
    assert caught.value.code == CODE_VERIFICATION_INVALID
    assert caught.value.pointer == pointer


def test_a_body_that_is_not_json_is_refused() -> None:
    with pytest.raises(PactPublicationError) as caught:
        parse_verification_request(b"{nope")
    assert caught.value.code == CODE_VERIFICATION_INVALID and caught.value.pointer == ""
    with pytest.raises(PactPublicationError):
        parse_verification_request(b"")


def test_a_malformed_version_or_url_is_the_registrys_refusal() -> None:
    with pytest.raises(PacticipantValidationError) as caught:
        _parse({"success": True, "providerApplicationVersion": " 1.0 "})
    assert caught.value.code == CODE_INVALID_VERSION
    with pytest.raises(PacticipantValidationError) as caught:
        _parse({"success": True, "providerApplicationVersion": "1", "buildUrl": "ftp://x"})
    assert caught.value.code == CODE_INVALID_URL


def test_a_row_becomes_a_record() -> None:
    row: Dict[str, Any] = {
        "id": "r-1",
        "number": 2,
        "consumer_slug": "billing",
        "consumer_name": "Billing",
        "provider_slug": "ledger",
        "provider_name": "Ledger",
        "provider_version": "4f1e2d0",
        "consumer_version": "1.0.0",
        "sha": "a" * 64,
        "success": False,
        "build_url": None,
        "provider_branch": "main",
        "test_results": [{"success": False}],
        "verified_by_implementation": "Pact-Rust",
        "verified_by_version": None,
        "verified_by_client_implementation": None,
        "verified_by_client_version": None,
        "verified_by_client_test_framework": None,
        "pact_pending": True,
        "wip": False,
        "provider_verification_report_id": None,
        "created_at": datetime.datetime(2026, 11, 24, 10, 0, tzinfo=datetime.timezone.utc),
    }
    record = verification_result_from_row(row)
    assert record.number == 2 and record.success is False and record.provider_branch == "main"
    assert record.verified_by["implementation"] == "Pact-Rust"
    assert record.created_at == "2026-11-24T10:00:00+00:00"
    assert record.report_id is None and record.pact_pending is True


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"s": [{"b": "main", "l": True, "cv": "v1"}], "p": True}, {"pending": True, "wip": False}),
        ({"s": [{"t": "prod", "cv": "v1"}], "p": False}, {"pending": False, "wip": False}),
        ({"w": True}, {"pending": True, "wip": True}),
    ],
)
def test_for_verification_metadata_reads_back(metadata: Dict[str, Any], expected: Dict[str, Any]) -> None:
    assert decode_metadata(encode_metadata(metadata)) == expected


@pytest.mark.parametrize("segment", [None, "", "!!!not-base64!!!", "AA"])
def test_unreadable_metadata_is_no_metadata(segment: Any) -> None:
    assert decode_metadata(segment) == {"pending": None, "wip": False}
