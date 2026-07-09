"""RFC 7807 problem+json response tests."""

from __future__ import annotations

from apiome_mock.problems import PROBLEM_CONTENT_TYPE, bad_request, method_not_allowed, not_found


def test_not_found_problem_json() -> None:
    response = not_found("missing spec", instance="/acme/demo/1.0.0/pets")
    assert response.status_code == 404
    assert response.media_type == PROBLEM_CONTENT_TYPE
    body = response.body.decode()
    assert "not-found" in body
    assert "missing spec" in body


def test_method_not_allowed_includes_allow_header() -> None:
    response = method_not_allowed("nope", allow=["GET", "POST"])
    assert response.status_code == 405
    assert response.headers["Allow"] == "GET, POST"


def test_bad_request_problem_json() -> None:
    response = bad_request("invalid", instance="/demo/pets", extra={"violations": []})
    assert response.status_code == 400
    assert response.media_type == PROBLEM_CONTENT_TYPE
    assert "bad-request" in response.body.decode()


def test_too_many_requests_includes_retry_after() -> None:
    from apiome_mock.problems import too_many_requests

    response = too_many_requests(
        "slow down",
        instance="/demo/petstore/1.0.0/pets",
        retry_after=2,
        limit_type="rps",
    )
    assert response.status_code == 429
    assert response.media_type == PROBLEM_CONTENT_TYPE
    assert response.headers["Retry-After"] == "2"
    assert "rate-limited" in response.body.decode()
