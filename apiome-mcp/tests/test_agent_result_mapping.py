"""AGX-2.1 response mapping (#4533): useful successes and distinct, hint-carrying failures."""

from __future__ import annotations

import json

import pytest

from apiome_mcp.agent_invocations import InvocationOutcome
from apiome_mcp.agent_request_builder import ArgumentIssue, OperationBinding, ParameterBinding
from apiome_mcp.agent_result_mapping import (
    AGENT_INVOCATION_ERROR_CODE,
    INVALID_ARGUMENTS_CODE,
    InvocationErrorResult,
    InvocationReason,
    failure_for_response,
    fixed_failure,
    invalid_arguments,
    success_result,
    timeout_failure,
    unreachable_failure,
)
from apiome_mcp.agent_upstream_client import UpstreamResponse

SHOW = OperationBinding(
    operation_key="GET /pets/{petId}",
    method="GET",
    path_template="/pets/{petId}",
    parameters=(ParameterBinding(name="petId", location="path", style="simple", explode=False, required=True),),
)
CREATE = OperationBinding(operation_key="POST /pets", method="POST", path_template="/pets", body_mode="flat")


def _json(status: int, body: object, **headers: str) -> UpstreamResponse:
    return UpstreamResponse(
        status=status,
        headers={"content-type": "application/json", **{k.lower(): v for k, v in headers.items()}},
        content=json.dumps(body).encode(),
    )


# ============================================================================
# Success
# ============================================================================


def test_a_json_success_returns_the_body_and_structured_content() -> None:
    result, text = success_result(_json(200, [{"id": "1"}]))
    assert text == '[{"id": "1"}]'
    assert result.content[0].text == text  # type: ignore[union-attr]
    assert result.structured_content == {
        "httpStatus": 200,
        "contentType": "application/json",
        "truncated": False,
        "body": [{"id": "1"}],
    }


def test_an_empty_success_says_so() -> None:
    result, text = success_result(UpstreamResponse(status=204))
    assert text == "HTTP 204: no content"
    assert result.structured_content == {"httpStatus": 204, "contentType": None, "truncated": False}


def test_a_truncated_success_carries_a_marker_and_no_parsed_body() -> None:
    response = UpstreamResponse(
        status=200, headers={"content-type": "application/json"}, content=b'[{"id":', truncated=True, total_bytes=9000
    )
    result, _ = success_result(response)
    assert len(result.content) == 2
    marker = result.content[1].text  # type: ignore[union-attr]
    assert marker.startswith("[truncated:") and "7 of 9000 bytes" in marker
    assert result.structured_content is not None
    assert result.structured_content["truncated"] is True and "body" not in result.structured_content


# ============================================================================
# Failures are distinct and carry hints
# ============================================================================


def test_400_names_the_arguments_the_upstream_complained_about() -> None:
    body = {"title": "Invalid", "invalid-params": [{"name": "tag", "reason": "unknown tag"}]}
    failure = failure_for_response(_json(400, body), CREATE, {"name": "Tom", "tag": "zzz"})
    assert failure.reason is InvocationReason.UPSTREAM_BAD_REQUEST
    assert "points at: tag." in failure.hint
    assert failure.outcome is InvocationOutcome.UPSTREAM_ERROR
    assert failure.retryable is False
    assert failure.upstream_body == body


def test_422_with_a_message_mentioning_an_argument_points_at_it() -> None:
    failure = failure_for_response(_json(422, {"detail": "name must be unique"}), CREATE, {"name": "Rex"})
    assert failure.reason is InvocationReason.UPSTREAM_BAD_REQUEST
    assert "name must be unique" in failure.message
    assert "points at: name" in failure.hint


def test_404_points_at_the_identifiers() -> None:
    failure = failure_for_response(_json(404, {"detail": "nope"}), SHOW, {"petId": "99"})
    assert failure.reason is InvocationReason.UPSTREAM_NOT_FOUND
    assert "petId='99'" in failure.hint
    assert failure.retryable is False


def test_500_is_retryable_with_a_backoff_hint() -> None:
    failure = failure_for_response(_json(500, {"message": "boom"}), SHOW, {"petId": "1"})
    assert failure.reason is InvocationReason.UPSTREAM_SERVER_ERROR
    assert failure.retryable is True
    assert "already retried" in failure.hint


def test_a_failed_post_warns_it_may_have_taken_effect() -> None:
    failure = failure_for_response(_json(502, {}), CREATE, {"name": "Tom"})
    assert "may already have taken effect" in failure.hint


def test_timeout_and_unreachable_are_their_own_reasons() -> None:
    timeout = timeout_failure(SHOW, 45, 3)
    unreachable = unreachable_failure(SHOW, 3)
    assert (timeout.reason, unreachable.reason) == (
        InvocationReason.UPSTREAM_TIMEOUT,
        InvocationReason.UPSTREAM_UNREACHABLE,
    )
    assert timeout.retryable and unreachable.retryable
    assert "45 s" in timeout.message and "3 attempts" in timeout.message


def test_the_four_acceptance_failures_are_distinct() -> None:
    reasons = {
        failure_for_response(_json(400, {}), SHOW, {}).reason,
        failure_for_response(_json(404, {}), SHOW, {}).reason,
        failure_for_response(_json(500, {}), SHOW, {}).reason,
        timeout_failure(SHOW, 1, 1).reason,
    }
    assert len(reasons) == 4


@pytest.mark.parametrize(
    ("status", "reason", "retryable"),
    [
        (401, InvocationReason.UPSTREAM_UNAUTHORIZED, False),
        (403, InvocationReason.UPSTREAM_FORBIDDEN, False),
        (409, InvocationReason.UPSTREAM_CONFLICT, False),
        (429, InvocationReason.UPSTREAM_RATE_LIMITED, True),
        (418, InvocationReason.UPSTREAM_CLIENT_ERROR, False),
        (302, InvocationReason.UPSTREAM_REDIRECT, False),
    ],
)
def test_other_statuses_map_to_their_reasons(status: int, reason: InvocationReason, retryable: bool) -> None:
    failure = failure_for_response(_json(status, {}), SHOW, {})
    assert (failure.reason, failure.retryable, failure.http_status) == (reason, retryable, status)
    assert failure.hint


def test_429_carries_retry_after() -> None:
    failure = failure_for_response(_json(429, {}, **{"Retry-After": "7"}), SHOW, {})
    assert failure.retry_after_seconds == 7 and "7 s" in failure.hint


def test_a_large_error_body_is_excerpted() -> None:
    response = UpstreamResponse(status=500, headers={"content-type": "text/html"}, content=b"<p>" + b"x" * 9000)
    failure = failure_for_response(response, SHOW, {})
    assert isinstance(failure.upstream_body, str) and len(failure.upstream_body) <= 2001


# ============================================================================
# The error result
# ============================================================================


def test_an_error_result_is_is_error_with_structured_details() -> None:
    failure = failure_for_response(_json(404, {"detail": "pet 9 not found"}), SHOW, {"petId": "9"})
    mcp = InvocationErrorResult(failure).to_mcp_result()
    assert mcp.isError is True
    text = mcp.content[0].text  # type: ignore[union-attr]
    assert text.startswith("upstream_not_found: ") and "Hint: " in text and "pet 9 not found" in text
    data = mcp.structuredContent or {}
    assert data["error"] == {
        "code": AGENT_INVOCATION_ERROR_CODE,
        "reason": "upstream_not_found",
        "message": failure.message,
    }
    assert (data["httpStatus"], data["retryable"]) == (404, False)
    assert data["upstream"] == {"contentType": "application/json", "body": {"detail": "pet 9 not found"}}


def test_invalid_arguments_use_invalid_params_and_list_every_problem() -> None:
    failure = invalid_arguments([ArgumentIssue("name", "is too short"), ArgumentIssue("limit", "is too big")])
    data = InvocationErrorResult(failure).to_mcp_result().structuredContent or {}
    assert data["error"]["code"] == INVALID_ARGUMENTS_CODE
    assert data["invalidArguments"] == [
        {"argument": "name", "problem": "is too short"},
        {"argument": "limit", "problem": "is too big"},
    ]
    assert failure.outcome is InvocationOutcome.VALIDATION_FAILURE
    assert "nothing was sent" in failure.message


@pytest.mark.parametrize(
    "reason",
    [
        InvocationReason.UPSTREAM_NOT_CONFIGURED,
        InvocationReason.UPSTREAM_CREDENTIAL_UNAVAILABLE,
        InvocationReason.TOOL_NOT_INVOCABLE,
        InvocationReason.INVOCATION_FAILED,
    ],
)
def test_fixed_failures_are_internal_errors_with_hints(reason: InvocationReason) -> None:
    failure = fixed_failure(reason)
    assert failure.outcome is InvocationOutcome.INTERNAL_ERROR
    assert failure.message and failure.hint
