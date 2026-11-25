"""Reading verifier reports produced elsewhere — PFX-3.5 (#6935).

:mod:`app.pact_external_verification` maps ``pact_verifier_cli --json`` output and JUnit XML into the
verification-result model. The rules under test:

* both inputs become ``testResults`` of ``{interactionId, interactionDescription, success,
  mismatches}``, and a failed run keeps every mismatch;
* the format is chosen by ``format``, then the content type, then the body;
* nothing is dropped silently — whatever is not stored comes back as a notice with a pointer;
* a report that proves nothing (no interactions) is refused, a skipped case is never a pass, and a
  report that says "success" while listing failures is recorded as failed;
* hostile XML (DTDs, entities) is refused.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.pact_external_verification import (
    FORMAT_AUTO,
    FORMAT_JUNIT,
    FORMAT_PACT_VERIFIER_JSON,
    read_external_report,
)
from app.pact_publication import PactPublicationError


def _json(document: Any) -> bytes:
    return json.dumps(document).encode("utf-8")


def _pointers(report: Any) -> list[str]:
    return [notice.pointer for notice in report.notices]


# --- pact_verifier_cli JSON ----------------------------------------------------------------------


def test_a_passing_run_is_a_success_with_no_results() -> None:
    # The verifier lists only failures: a clean run is {"result": true}. It still proves
    # something because the verifier said it replayed the pact — but not "no interactions at all".
    report = read_external_report(_json({"result": True, "errors": [], "pendingErrors": [], "notices": []}))
    assert report.success is True
    assert report.format == FORMAT_PACT_VERIFIER_JSON
    assert report.test_results == []


def test_failures_keep_every_mismatch() -> None:
    report = read_external_report(
        _json(
            {
                "result": False,
                "errors": [
                    {
                        "interactionId": "a1",
                        "description": "a request for an invoice",
                        "mismatch": [
                            {"type": "StatusMismatch", "description": "expected 200 but was 404"},
                            {"type": "BodyMismatch", "mismatch": "$.id is missing"},
                        ],
                    }
                ],
            }
        )
    )
    assert report.success is False
    [entry] = report.test_results
    assert entry["interactionId"] == "a1"
    assert entry["interactionDescription"] == "a request for an invoice"
    assert entry["success"] is False
    assert [(m["attribute"], m["description"]) for m in entry["mismatches"]] == [
        ("StatusMismatch", "expected 200 but was 404"),
        ("BodyMismatch", "$.id is missing"),
    ]
    assert entry["mismatches"][0]["detail"] == {"type": "StatusMismatch", "description": "expected 200 but was 404"}


def test_an_id_and_mismatch_pair_is_read() -> None:
    report = read_external_report(_json({"result": False, "errors": [["a1", {"type": "x", "description": "bad"}]]}))
    assert report.test_results[0]["interactionId"] == "a1"
    assert report.test_results[0]["mismatches"][0]["description"] == "bad"


def test_pending_errors_do_not_fail_the_run_but_are_kept() -> None:
    report = read_external_report(
        _json({"result": True, "pendingErrors": [{"interactionId": "p1", "mismatch": "boom"}]})
    )
    assert report.success is True
    assert report.test_results[0]["pending"] is True and report.test_results[0]["success"] is False


def test_a_success_flag_contradicted_by_failures_is_recorded_as_failed() -> None:
    report = read_external_report(_json({"result": True, "errors": [{"interactionId": "a1", "mismatch": "x"}]}))
    assert report.success is False
    assert "/result" in _pointers(report)


def test_the_per_interaction_listing_is_read() -> None:
    report = read_external_report(
        _json(
            {
                "pacts": [
                    {
                        "interactions": [
                            {"id": "a", "description": "ok one", "success": True},
                            {"id": "b", "description": "bad one", "success": False, "mismatches": ["status differs"]},
                        ]
                    }
                ]
            }
        )
    )
    assert report.success is False
    assert [r["success"] for r in report.test_results] == [True, False]
    assert report.test_results[1]["mismatches"][0]["description"] == "status differs"
    assert any("derived" in n.reason for n in report.notices)


def test_unrecognised_fields_are_noticed_with_their_pointer() -> None:
    report = read_external_report(
        _json(
            {
                "result": True,
                "errors": [],
                "output": ["line 1", "line 2"],
                "notices": [{"text": "pending"}],
                "mystery": 1,
            }
        )
    )
    assert _pointers(report) == ["/notices", "/output", "/mystery"]


def test_unknown_interaction_fields_are_noticed() -> None:
    report = read_external_report(_json({"pacts": [{"interactions": [{"id": "a", "success": True, "extra": 1}]}]}))
    assert "/pacts/0/interactions/0/extra" in _pointers(report)


def test_a_mismatch_without_a_description_is_kept_as_json_text() -> None:
    report = read_external_report(_json({"result": False, "errors": [{"interactionId": "a", "mismatch": {"x": 1}}]}))
    mismatch = report.test_results[0]["mismatches"][0]
    assert json.loads(mismatch["description"]) == {"x": 1}
    assert any("no description" in n.reason for n in report.notices)


def test_an_entry_naming_no_interaction_is_noticed() -> None:
    report = read_external_report(_json({"result": False, "errors": ["boom"]}))
    assert report.test_results[0]["interactionId"] is None
    assert any("names no interaction" in n.reason for n in report.notices)


@pytest.mark.parametrize(
    ("document", "pointer"),
    [
        ({}, ""),
        ({"pacts": [{"interactions": []}]}, ""),
        ({"result": False}, "/errors"),
        ({"result": "yes"}, "/result"),
        ({"result": False, "errors": "boom"}, "/errors"),
        ({"pacts": [{"interactions": ["nope"]}]}, "/pacts/0/interactions/0"),
    ],
)
def test_a_report_that_proves_nothing_or_is_malformed_is_refused(document: Any, pointer: str) -> None:
    with pytest.raises(PactPublicationError) as caught:
        read_external_report(_json(document))
    assert caught.value.code == "pact-verification-invalid"
    assert caught.value.pointer == pointer


@pytest.mark.parametrize("body", [b"", b"   \n", b"{not json", b"[1, 2]", b"plain text"])
def test_unreadable_bodies_are_refused(body: bytes) -> None:
    with pytest.raises(PactPublicationError) as caught:
        read_external_report(body)
    assert caught.value.code == "pact-verification-invalid"


# --- JUnit ---------------------------------------------------------------------------------------

_JUNIT = b"""<?xml version="1.0"?>
<testsuites>
  <testsuite name="pact" tests="3">
    <testcase classname="billing-service" name="a request for an invoice"/>
    <testcase classname="billing-service" name="a request for a refund">
      <failure type="StatusMismatch" message="expected 200 but was 404">trace</failure>
    </testcase>
    <testcase name="a request that raised"><error message="connection refused"/></testcase>
  </testsuite>
</testsuites>
"""


def test_junit_cases_become_interactions() -> None:
    report = read_external_report(_JUNIT, content_type="application/xml")
    assert report.format == FORMAT_JUNIT
    assert report.success is False
    assert [r["interactionDescription"] for r in report.test_results] == [
        "a request for an invoice",
        "a request for a refund",
        "a request that raised",
    ]
    assert [r["success"] for r in report.test_results] == [True, False, False]
    assert report.test_results[1]["mismatches"] == [
        {"attribute": "StatusMismatch", "description": "expected 200 but was 404"}
    ]
    assert report.test_results[2]["mismatches"] == [{"attribute": "error", "description": "connection refused"}]
    assert report.test_results[0]["suite"] == "billing-service"


def test_a_clean_junit_run_is_a_success() -> None:
    report = read_external_report(b"<testsuite><testcase name='a'/><testcase name='b'/></testsuite>")
    assert report.success is True and report.format == FORMAT_JUNIT


def test_a_skipped_case_is_never_verified() -> None:
    report = read_external_report(
        b"<testsuite><testcase name='a'/><testcase name='b'><skipped message='no state'/></testcase></testsuite>"
    )
    assert report.success is False
    assert report.test_results[1]["skipped"] is True
    assert report.test_results[1]["mismatches"][0]["description"] == "no state"
    assert "//testcase[2]" in _pointers(report)


def test_a_nameless_case_is_noticed() -> None:
    report = read_external_report(b"<testsuite><testcase/></testsuite>")
    assert "//testcase[1]" in _pointers(report)


@pytest.mark.parametrize(
    "body",
    [
        b"<testsuite name='empty'/>",
        b"<report/>",
        b"<testsuite><testcase name='a'>",
        b'<!DOCTYPE x [<!ENTITY a "boom">]><testsuite><testcase name="&a;"/></testsuite>',
    ],
)
def test_bad_xml_is_refused(body: bytes) -> None:
    with pytest.raises(PactPublicationError) as caught:
        read_external_report(body, fmt=FORMAT_JUNIT)
    assert caught.value.code == "pact-verification-invalid"


# --- choosing the format -------------------------------------------------------------------------


def test_the_content_type_chooses_the_reader() -> None:
    assert read_external_report(_JUNIT, content_type="text/xml; charset=utf-8").format == FORMAT_JUNIT
    assert (
        read_external_report(_json({"result": True}), content_type="application/json").format
        == FORMAT_PACT_VERIFIER_JSON
    )


def test_the_body_chooses_the_reader_without_a_content_type() -> None:
    assert read_external_report(_JUNIT, content_type="application/octet-stream").format == FORMAT_JUNIT
    assert (
        read_external_report(_json({"result": True}), content_type=None, fmt=FORMAT_AUTO).format
        == FORMAT_PACT_VERIFIER_JSON
    )


def test_an_explicit_format_wins_over_the_content_type() -> None:
    report = read_external_report(
        _json({"result": True}), content_type="application/xml", fmt=FORMAT_PACT_VERIFIER_JSON
    )
    assert report.format == FORMAT_PACT_VERIFIER_JSON


def test_an_unknown_format_or_a_body_of_neither_kind_is_refused() -> None:
    with pytest.raises(PactPublicationError) as caught:
        read_external_report(_JUNIT, fmt="tap")
    assert caught.value.pointer == "/format"
    with pytest.raises(PactPublicationError):
        read_external_report(b"TAP version 13", content_type="text/plain")


def test_a_byte_order_mark_is_tolerated() -> None:
    assert read_external_report(b"\xef\xbb\xbf" + _json({"result": True})).success is True
    assert read_external_report(b"\xef\xbb\xbf" + b"<testsuite><testcase name='a'/></testsuite>").success is True
