"""The provider status adapters — GNC-2.2 (#4738).

Every adapter is driven end to end against an in-memory transport, so the whole protocol — the URL,
the method, the body, the headers, the error mapping and the fingerprint — is asserted without a
network. That is the same discipline SDK-4.2's git delivery uses, and it is what lets three
providers share one interface without any of them being the one that is only ever exercised by
hand.

The properties that matter most are the ones a bug would make invisible: that a token appears in
exactly one place and never in a raised message, that a refused publish keeps its meaning, and that
two calls which would send the same bytes fingerprint the same.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
import pytest

from app.provider_checks import (
    CODE_PROVIDER_FORBIDDEN,
    CODE_PROVIDER_REFUSED,
    CODE_PROVIDER_UNAVAILABLE,
    CODE_PROVIDER_UNSUPPORTED,
    STATE_FAIL,
    STATE_PASS,
    STATE_PENDING,
    STATE_SKIPPED,
)
from app.provider_status_adapter import (
    BITBUCKET_API_URL,
    GITHUB_API_URL,
    GITLAB_API_URL,
    STATUS_TOKEN_REDACTION_MARKER,
    PublishRequest,
    StatusPublishError,
    adapter_for,
    supported_providers,
)

TOKEN = "ghp_a_real_looking_repository_token_0123456789"


class Transport:
    """An in-memory stand-in for the provider's API.

    Attributes:
        status: The status code to answer with.
        payload: The JSON body to answer with.
        text: A non-JSON body to answer with instead, when set.
        error: An :class:`httpx.HTTPError` raised instead of answering.
        calls: One entry per request: ``(method, url, json, headers)``.
    """

    def __init__(self) -> None:
        self.status = 201
        self.payload: Any = {"id": 99, "html_url": "https://github.com/acme/specs/runs/99"}
        self.text: Optional[str] = None
        self.error: Optional[Exception] = None
        self.calls: List[Dict[str, Any]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Answer one request, recording what was asked."""
        body = request.read().decode("utf-8") or "null"
        self.calls.append(
            {
                "method": request.method,
                "url": str(request.url),
                "body": body,
                "headers": dict(request.headers),
            }
        )
        if self.error:
            raise self.error
        if self.text is not None:
            return httpx.Response(self.status, text=self.text)
        return httpx.Response(self.status, json=self.payload)

    def factory(self):
        """Return a client factory bound to this transport."""

        def build() -> httpx.Client:
            return httpx.Client(transport=httpx.MockTransport(self.handle))

        return build


@pytest.fixture
def transport() -> Transport:
    """A provider API that answers in memory."""
    return Transport()


def _request(**kwargs: Any) -> PublishRequest:
    """A publish request with sensible defaults."""
    return PublishRequest(
        **{
            "repo_full_name": "acme/specs",
            "commit_sha": "1111111111111111111111111111111111111111",
            "name": "apiome/api-change",
            "state": STATE_FAIL,
            "title": "2 breaking changes",
            "summary": "`GET /pets` lost a required field.",
            "details_url": "https://app.apiome.dev/ade/checks/1",
            **kwargs,
        }
    )


def _body(transport: Transport) -> Dict[str, Any]:
    """The JSON body of the single call made."""
    import json

    assert len(transport.calls) == 1
    return json.loads(transport.calls[0]["body"])


# ---------------------------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------------------------


def test_the_three_providers_the_ticket_names_all_have_an_adapter():
    assert supported_providers() == ("bitbucket", "github", "gitlab")


def test_a_provider_with_no_adapter_is_refused_rather_than_defaulted():
    # Publishing a verdict to the wrong API is worse than publishing none.
    with pytest.raises(StatusPublishError) as refused:
        adapter_for("gitea", TOKEN)
    assert refused.value.code == CODE_PROVIDER_UNSUPPORTED


@pytest.mark.parametrize("provider", ["GitHub", " github ", "GITHUB"])
def test_the_provider_key_is_matched_case_and_space_insensitively(provider):
    assert adapter_for(provider, TOKEN).provider == "github"


# ---------------------------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------------------------


def test_github_creates_a_check_run_on_the_commit(transport):
    adapter = adapter_for("github", TOKEN, client_factory=transport.factory())
    published = adapter.publish(_request())

    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == f"{GITHUB_API_URL}/repos/acme/specs/check-runs"
    body = _body(transport)
    assert body["head_sha"] == "1111111111111111111111111111111111111111"
    assert body["name"] == "apiome/api-change"
    assert body["status"] == "completed"
    assert body["conclusion"] == "failure"
    assert body["output"] == {
        "title": "2 breaking changes",
        "summary": "`GET /pets` lost a required field.",
    }
    assert body["details_url"] == "https://app.apiome.dev/ade/checks/1"
    assert published.status_code == 201
    assert published.external_id == "99"
    assert published.url == "https://github.com/acme/specs/runs/99"


def test_github_moves_the_run_it_already_created_rather_than_stacking_a_second(transport):
    adapter = adapter_for("github", TOKEN, client_factory=transport.factory())
    adapter.publish(_request(external_id="99", state=STATE_PASS))

    call = transport.calls[0]
    assert call["method"] == "PATCH"
    assert call["url"] == f"{GITHUB_API_URL}/repos/acme/specs/check-runs/99"


def test_github_sends_no_conclusion_while_a_run_is_pending(transport):
    adapter = adapter_for("github", TOKEN, client_factory=transport.factory())
    adapter.publish(_request(state=STATE_PENDING))

    body = _body(transport)
    assert body["status"] == "in_progress"
    assert "conclusion" not in body


def test_github_falls_back_to_the_check_name_when_there_is_no_title(transport):
    adapter = adapter_for("github", TOKEN, client_factory=transport.factory())
    adapter.publish(_request(title=""))
    assert _body(transport)["output"]["title"] == "apiome/api-change"


def test_github_omits_the_details_link_when_there_is_none(transport):
    adapter = adapter_for("github", TOKEN, client_factory=transport.factory())
    adapter.publish(_request(details_url=""))
    assert "details_url" not in _body(transport)


def test_github_pins_its_api_version_and_carries_the_token_only_in_the_header(transport):
    adapter = adapter_for("github", TOKEN, client_factory=transport.factory())
    adapter.publish(_request())

    call = transport.calls[0]
    assert call["headers"]["authorization"] == f"Bearer {TOKEN}"
    assert call["headers"]["x-github-api-version"] == "2022-11-28"
    # The one place the token appears: never in the URL (a proxy log would keep it) and never in
    # the body (the provider would store it).
    assert TOKEN not in call["url"]
    assert TOKEN not in call["body"]


# ---------------------------------------------------------------------------------------------
# GitLab
# ---------------------------------------------------------------------------------------------


def test_gitlab_posts_a_commit_status_against_the_url_encoded_project(transport):
    transport.status = 201
    transport.payload = {"target_url": "https://gitlab.com/acme/specs/-/commit/1111"}
    adapter = adapter_for("gitlab", TOKEN, client_factory=transport.factory())
    published = adapter.publish(_request())

    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == (
        f"{GITLAB_API_URL}/projects/acme%2Fspecs/statuses/1111111111111111111111111111111111111111"
    )
    body = _body(transport)
    assert body["state"] == "failed"
    assert body["name"] == "apiome/api-change"
    assert body["target_url"] == "https://app.apiome.dev/ade/checks/1"
    assert published.url == "https://gitlab.com/acme/specs/-/commit/1111"


def test_gitlab_handles_a_nested_group_path(transport):
    adapter = adapter_for("gitlab", TOKEN, client_factory=transport.factory())
    adapter.publish(_request(repo_full_name="acme/platform/specs"))
    assert "projects/acme%2Fplatform%2Fspecs/" in transport.calls[0]["url"]


# ---------------------------------------------------------------------------------------------
# Bitbucket
# ---------------------------------------------------------------------------------------------


def test_bitbucket_posts_a_build_status_keyed_on_the_check_name(transport):
    transport.payload = {"url": "https://bitbucket.org/acme/specs/commits/1111"}
    adapter = adapter_for("bitbucket", TOKEN, client_factory=transport.factory())
    published = adapter.publish(_request())

    call = transport.calls[0]
    assert call["url"] == (
        f"{BITBUCKET_API_URL}/repositories/acme/specs/commit/"
        "1111111111111111111111111111111111111111/statuses/build"
    )
    body = _body(transport)
    # The key is the upsert identity, which is what makes re-publishing move the same status.
    assert body["key"] == "apiome/api-change"
    assert body["state"] == "FAILED"
    assert published.url == "https://bitbucket.org/acme/specs/commits/1111"


def test_bitbucket_truncates_a_key_to_the_length_it_accepts(transport):
    adapter = adapter_for("bitbucket", TOKEN, client_factory=transport.factory())
    adapter.publish(_request(name="a" * 128))
    assert len(_body(transport)["key"]) == 40


def test_bitbucket_always_sends_a_url_because_it_refuses_a_status_without_one(transport):
    adapter = adapter_for("bitbucket", TOKEN, client_factory=transport.factory())
    adapter.publish(_request(details_url=""))
    body = _body(transport)
    assert body["url"] == (
        "https://bitbucket.org/acme/specs/commits/1111111111111111111111111111111111111111"
    )


# ---------------------------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["github", "gitlab", "bitbucket"])
def test_publishing_without_a_credential_is_refused_before_any_request(provider, transport):
    adapter = adapter_for(provider, None, client_factory=transport.factory())
    with pytest.raises(StatusPublishError) as refused:
        adapter.publish(_request())
    assert refused.value.code == CODE_PROVIDER_FORBIDDEN
    assert transport.calls == []


@pytest.mark.parametrize("status", [401, 403, 404])
def test_a_credential_problem_keeps_its_meaning_on_every_provider(status, transport):
    # A private repository answers 404 rather than admit it exists, so 404 is a permission
    # problem here and not a "there is no such repository".
    transport.status = status
    transport.payload = {"message": "Bad credentials"}
    adapter = adapter_for("github", TOKEN, client_factory=transport.factory())
    with pytest.raises(StatusPublishError) as refused:
        adapter.publish(_request())
    assert refused.value.code == CODE_PROVIDER_FORBIDDEN
    assert refused.value.http_status == status
    assert refused.value.retryable is False


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_a_transient_provider_problem_is_marked_retryable(status, transport):
    transport.status = status
    transport.payload = {"message": "try later"}
    adapter = adapter_for("gitlab", TOKEN, client_factory=transport.factory())
    with pytest.raises(StatusPublishError) as refused:
        adapter.publish(_request())
    assert refused.value.code == CODE_PROVIDER_UNAVAILABLE
    assert refused.value.retryable is True


def test_a_request_the_provider_will_never_accept_is_not_retryable(transport):
    transport.status = 422
    transport.payload = {"message": "No commit found for SHA"}
    adapter = adapter_for("github", TOKEN, client_factory=transport.factory())
    with pytest.raises(StatusPublishError) as refused:
        adapter.publish(_request())
    assert refused.value.code == CODE_PROVIDER_REFUSED
    assert refused.value.retryable is False
    assert "No commit found for SHA" in refused.value.message


def test_an_unreachable_provider_is_a_failure_and_not_a_crash(transport):
    transport.error = httpx.ConnectError("name resolution failed")
    adapter = adapter_for("bitbucket", TOKEN, client_factory=transport.factory())
    with pytest.raises(StatusPublishError) as refused:
        adapter.publish(_request())
    assert refused.value.code == CODE_PROVIDER_UNAVAILABLE
    assert refused.value.retryable is True


def test_a_provider_that_quotes_the_token_back_never_leaks_it(transport):
    transport.status = 403
    transport.payload = {"message": f"token {TOKEN} is not authorized"}
    adapter = adapter_for("github", TOKEN, client_factory=transport.factory())
    with pytest.raises(StatusPublishError) as refused:
        adapter.publish(_request())
    assert TOKEN not in refused.value.message
    assert STATUS_TOKEN_REDACTION_MARKER in refused.value.message


def test_a_body_that_is_not_json_still_produces_an_explanation(transport):
    transport.status = 502
    transport.text = "<html><body>Bad Gateway</body></html>"
    adapter = adapter_for("gitlab", TOKEN, client_factory=transport.factory())
    with pytest.raises(StatusPublishError) as refused:
        adapter.publish(_request())
    assert "Bad Gateway" in refused.value.message


def test_a_success_body_that_is_not_json_is_still_a_success(transport):
    transport.status = 200
    transport.text = ""
    adapter = adapter_for("gitlab", TOKEN, client_factory=transport.factory())
    published = adapter.publish(_request())
    assert published.status_code == 200
    assert published.external_id is None


@pytest.mark.parametrize("provider", ["github", "gitlab", "bitbucket"])
@pytest.mark.parametrize("malformed", ["specs", "", "/", "   "])
def test_a_name_that_is_not_owner_slash_name_is_refused(provider, malformed, transport):
    # Guessing would mean putting a verdict on somebody else's repository. GitLab addresses a
    # project by its whole path, so only the two that split a name are asserted here.
    adapter = adapter_for(provider, TOKEN, client_factory=transport.factory())
    if provider == "gitlab" and malformed == "specs":
        pytest.skip("GitLab addresses a project by its whole path, so one segment is legitimate")
    with pytest.raises(StatusPublishError):
        adapter.publish(_request(repo_full_name=malformed))


# ---------------------------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["github", "gitlab", "bitbucket"])
def test_the_fingerprint_is_stable_for_a_request_that_would_send_the_same_bytes(provider):
    adapter = adapter_for(provider, TOKEN)
    assert adapter.fingerprint(_request()) == adapter.fingerprint(_request())


@pytest.mark.parametrize("provider", ["github", "gitlab", "bitbucket"])
@pytest.mark.parametrize(
    "change",
    [
        {"state": STATE_PASS},
        {"state": STATE_SKIPPED},
        {"commit_sha": "2222222222222222222222222222222222222222"},
        {"name": "apiome/other"},
        {"title": "different"},
    ],
)
def test_a_different_verdict_fingerprints_differently(provider, change):
    adapter = adapter_for(provider, TOKEN)
    assert adapter.fingerprint(_request()) != adapter.fingerprint(_request(**change))


def test_the_fingerprint_does_not_depend_on_the_providers_id_for_the_check():
    # Once GitHub has given us an id, the same verdict publishes as a PATCH to a different URL.
    # Fingerprinting the call would make every webhook redelivery look like new work.
    adapter = adapter_for("github", TOKEN)
    assert adapter.fingerprint(_request()) == adapter.fingerprint(_request(external_id="99"))


def test_the_fingerprint_does_not_depend_on_the_token():
    # Two deployments holding different credentials must agree about what the same verdict is,
    # or a token rotation would silently re-publish every check.
    one = adapter_for("github", TOKEN).fingerprint(_request())
    two = adapter_for("github", "a-completely-different-token").fingerprint(_request())
    assert one == two


def test_the_fingerprint_matches_the_call_that_is_actually_made(transport):
    adapter = adapter_for("github", TOKEN, client_factory=transport.factory())
    predicted = adapter.fingerprint(_request())
    published = adapter.publish(_request())
    assert published.fingerprint == predicted
