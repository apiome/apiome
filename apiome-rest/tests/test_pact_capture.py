"""The pure rules of consumer-tagged mock capture — PFX-9.1 (#7319), ``app.pact_capture``."""

from __future__ import annotations

import json

import pytest

from app.mock_capture import MAX_CAPTURE_BODY_BYTES
from app.pact_capture import (
    MAX_NAME_CHARS,
    ORIGINS,
    CaptureHeaderProblem,
    ConsumerTag,
    RedactedCall,
    classify_capture_header,
    decode_body,
    link_token_hash,
    looks_like_link_token,
    mock_session_digest,
    name_problem,
    new_link_token,
    origin_for_layer,
    redact_call,
    retention_problem,
)


class TestClassifyCaptureHeader:
    def test_no_header_or_off_records_nothing(self) -> None:
        for value in (None, "", "  ", "off", "OFF", "0", "false", "no"):
            assert classify_capture_header(value) is None

    def test_the_proxy_opt_in_values_stay_the_proxys(self) -> None:
        for value in ("on", "ON", "1", "true", "yes", "record", " record "):
            assert classify_capture_header(value) == "proxy"

    def test_a_consumer_tag(self) -> None:
        assert classify_capture_header("orders-ui@3.4.0") == ConsumerTag("orders-ui", "3.4.0")
        assert classify_capture_header("Orders UI@3.4.0+a1c9e02").label == "Orders UI@3.4.0+a1c9e02"

    def test_splits_on_the_last_at_so_scoped_names_keep_theirs(self) -> None:
        assert classify_capture_header("@acme/web@1.2.0") == ConsumerTag("@acme/web", "1.2.0")

    @pytest.mark.parametrize(
        "value, says",
        [
            ("orders-ui", "must be <consumer>@<version>"),
            ("@3.4.0", "The consumer is empty."),
            ("orders-ui@", "The version is empty."),
            ("orders-ui@ 3.4.0", "leading or trailing spaces"),
            ("orders\x01ui@1", "control character"),
            ("a" * (MAX_NAME_CHARS + 1) + "@1", f"longer than {MAX_NAME_CHARS}"),
        ],
    )
    def test_anything_else_is_reported_not_ignored(self, value: str, says: str) -> None:
        problem = classify_capture_header(value)
        assert isinstance(problem, CaptureHeaderProblem)
        assert problem.code == "invalid-tag"
        assert says in problem.message


def test_name_problem_accepts_a_plain_name() -> None:
    assert name_problem("Orders UI", "consumer") is None
    assert name_problem(7, "version") == "The version is empty."


class TestLinkTokens:
    def test_a_new_token_has_its_shape_digest_and_prefix(self) -> None:
        token, digest, prefix = new_link_token()
        assert looks_like_link_token(token)
        assert digest == link_token_hash(token)
        assert len(digest) == 64 and digest == digest.lower()
        assert token.startswith(prefix) and prefix.startswith("mcap_") and len(prefix) == 9

    def test_tokens_differ(self) -> None:
        assert new_link_token()[0] != new_link_token()[0]

    def test_other_shapes_are_not_tokens(self) -> None:
        for value in ("", "mcap_short", "apk_" + "a" * 40, "mcap_" + "a" * 40 + "/x", "mcap_" + "é" * 40):
            assert not looks_like_link_token(value)


def test_mock_session_digest_never_returns_the_token() -> None:
    assert mock_session_digest(None) is None
    assert mock_session_digest("") is None
    digest = mock_session_digest("secret-session")
    assert digest and len(digest) == 16 and "secret" not in digest
    assert digest == mock_session_digest("secret-session")


@pytest.mark.parametrize(
    "layer, origin",
    [
        ("example", "spec"),
        ("synthesis", "spec"),
        ("empty", "spec"),
        ("correlation", "spec"),
        ("scenario", "scenario"),
        ("stateful", "session"),
        ("chaos-error", "chaos"),
        ("forced-status", "forced"),
        ("no-operation", "off-spec"),
        ("method-not-allowed", "off-spec"),
        ("lifecycle", "off-spec"),
        ("request-invalid", "rejected"),
        ("unknown-scenario", "rejected"),
        ("something-new", "rejected"),
    ],
)
def test_origin_for_layer(layer: str, origin: str) -> None:
    assert origin_for_layer(layer) == origin
    assert origin in ORIGINS


def test_retention_problem() -> None:
    assert retention_problem(7) is None
    assert retention_problem(1) is None and retention_problem(30) is None
    for bad in (0, 31, -1, 7.5, "7", True, None):
        assert retention_problem(bad)


class TestDecodeBody:
    def test_no_body(self) -> None:
        assert decode_body(None, None) == (None, True, False)
        assert decode_body(b"", "application/json") == (None, True, False)

    def test_json_text_and_broken_json(self) -> None:
        assert decode_body(b'{"a": 1}', "application/json; charset=utf-8") == ({"a": 1}, True, False)
        assert decode_body(b"hello", "text/plain") == ("hello", True, False)
        assert decode_body(b"{nope", "application/problem+json") == ("{nope", True, False)

    def test_binary_and_oversize_are_flagged(self) -> None:
        assert decode_body(b"\x89PNG", "image/png") == (None, False, False)
        assert decode_body(b"\xff\xfe", "application/json") == (None, False, False)
        assert decode_body(b"x" * (MAX_CAPTURE_BODY_BYTES + 1), "text/plain") == (None, True, True)


def _call(**overrides):
    args = dict(
        policy={},
        method="get",
        path="/invoices/42",
        query_params=[("expand", "lines"), ("access_token", "abc")],
        request_headers={
            "Accept": "application/json",
            "Authorization": "Bearer abc.def.ghi",
            "X-Mock-Capture": "orders-ui@3.4.0",
            "X-Mock-Session": "session-token",
        },
        request_body=None,
        request_media_type=None,
        status=200,
        response_headers={"content-type": "application/json"},
        response_body=json.dumps({"id": 42, "amount": 1250}).encode(),
        response_media_type="application/json",
    )
    args.update(overrides)
    return redact_call(**args)


class TestRedactCall:
    def test_stores_the_call_with_credentials_removed_and_says_what_was_removed(self) -> None:
        call = _call()
        assert isinstance(call, RedactedCall)
        assert call.request["method"] == "GET"
        assert call.request["path"] == "/invoices/42"
        assert call.request["query"] == [{"name": "expand", "value": "lines"}]
        headers = {name.lower() for name in call.request["headers"]}
        assert "authorization" not in headers
        assert "x-mock-capture" not in headers and "x-mock-session" not in headers
        assert call.response == {
            "status": 200,
            "headers": {"content-type": "application/json"},
            "body": {"id": 42, "amount": 1250},
            "mediaType": "application/json",
        }
        rules = {entry["rule"] for entry in call.redactions}
        assert "always-header" in rules or "credential-header" in rules
        assert any(entry["pointer"].startswith("/request/query") for entry in call.redactions)

    def test_applies_the_versions_own_redaction_rules(self) -> None:
        policy = {"redaction": {"bodyFields": ["amount"], "patterns": ["email"]}}
        body = json.dumps({"id": 1, "amount": 3, "contact": "a@example.com"}).encode()
        call = _call(policy=policy, response_body=body)
        assert isinstance(call, RedactedCall)
        assert call.response["body"] == {"id": 1}

    def test_a_dropped_body_is_recorded_as_a_decision(self) -> None:
        call = _call(response_body=b"\x89PNG", response_media_type="image/png")
        assert isinstance(call, RedactedCall)
        assert call.response["body"] is None
        assert [entry["rule"] for entry in call.redactions if entry["pointer"] == "/response/body"] == [
            "body-not-textual"
        ]

    def test_refuses_a_record_that_still_looks_credential_bearing(self, monkeypatch) -> None:
        monkeypatch.setattr("app.pact_capture.residual_credential_pointers", lambda record: ["/response/body/x"])
        result = _call()
        assert isinstance(result, CaptureHeaderProblem)
        assert result.code == "credential-residual"
