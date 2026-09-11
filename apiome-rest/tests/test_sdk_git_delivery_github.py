"""Writing a delivery to GitHub — SDK-4.2 (#4496).

Tests for :mod:`app.sdk_git_delivery_github` over :class:`httpx.MockTransport`: the exact requests
the Git Database API receives, and — the "actionable logs" criterion — that every refusal GitHub can
answer with maps to a stable code whose message names the fix and never quotes the token.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

import httpx
import pytest

from app.sdk_git_delivery_github import (
    ERROR_CREDENTIAL_REJECTED,
    ERROR_PERMISSION_DENIED,
    ERROR_PROVIDER_REFUSED,
    ERROR_PROVIDER_UNAVAILABLE,
    ERROR_PULL_REQUEST_REFUSED,
    ERROR_PUSH_REJECTED,
    ERROR_RATE_LIMITED,
    ERROR_REPOSITORY_EMPTY,
    ERROR_REPOSITORY_UNREACHABLE,
    ERROR_TARGET_PATH_INVALID,
    GIT_TOKEN_REDACTION_MARKER,
    GITHUB_API_URL,
    GitHubGitClient,
    GitProviderError,
)

_TOKEN = "ghp_repositoryTokenUnderTest0000001"


def _client(handler: Callable[[httpx.Request], httpx.Response], seen: List[httpx.Request]) -> GitHubGitClient:
    """A client whose transport records requests and answers with ``handler``."""

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return GitHubGitClient(
        _TOKEN,
        "acme/widgets-sdk",
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(record)),
    )


def _answer(status: int, payload: Any = None, headers: Dict[str, str] | None = None):
    return lambda _request: httpx.Response(status, json=payload if payload is not None else {}, headers=headers)


def test_the_client_must_be_used_as_a_context_manager():
    client = GitHubGitClient(_TOKEN, "acme/widgets-sdk")
    with pytest.raises(RuntimeError, match="context manager"):
        client.get_repository()


def test_every_request_is_authenticated_and_pinned_to_one_api_version():
    seen: List[httpx.Request] = []
    payload = {
        "full_name": "acme/widgets-sdk",
        "owner": {"login": "acme"},
        "default_branch": "trunk",
        "archived": False,
        "permissions": {"push": True},
    }
    with _client(_answer(200, payload), seen) as github:
        info = github.get_repository()
    [request] = seen
    assert str(request.url) == f"{GITHUB_API_URL}/repos/acme/widgets-sdk"
    assert request.headers["authorization"] == f"Bearer {_TOKEN}"
    assert request.headers["x-github-api-version"] == "2022-11-28"
    assert request.headers["accept"] == "application/vnd.github+json"
    assert (info.owner, info.default_branch, info.can_push, info.archived) == ("acme", "trunk", True, False)


def test_a_repository_the_token_can_only_read_reports_no_push():
    seen: List[httpx.Request] = []
    with _client(_answer(200, {"permissions": {"pull": True}}), seen) as github:
        assert github.get_repository().can_push is False


def test_a_missing_branch_is_none_not_an_error():
    seen: List[httpx.Request] = []
    with _client(_answer(404, {"message": "Not Found"}), seen) as github:
        assert github.get_branch_sha("apiome/sdk-regen-1-widgets-npm") is None
    assert seen[0].url.path == "/repos/acme/widgets-sdk/git/ref/heads/apiome/sdk-regen-1-widgets-npm"


def test_a_prefix_match_is_not_the_branch():
    seen: List[httpx.Request] = []
    with _client(_answer(200, [{"ref": "refs/heads/main-2", "object": {"sha": "abc"}}]), seen) as github:
        assert github.get_branch_sha("main") is None


def test_a_tree_write_sends_base_tree_and_entries():
    seen: List[httpx.Request] = []
    entries = [
        {"path": "sdk/a.ts", "mode": "100644", "type": "blob", "content": "x"},
        {"path": "sdk/old.ts", "mode": "100644", "type": "blob", "sha": None},
    ]
    with _client(_answer(201, {"sha": "tree-2"}), seen) as github:
        assert github.create_tree("tree-1", entries) == "tree-2"
    assert json.loads(seen[0].content) == {"base_tree": "tree-1", "tree": entries}


def test_a_branch_update_says_whether_it_may_force():
    seen: List[httpx.Request] = []
    with _client(_answer(200, {}), seen) as github:
        github.update_branch("apiome/sdk-regen-1-w-npm", "c0ffee", force=True)
    assert seen[0].method == "PATCH"
    assert json.loads(seen[0].content) == {"sha": "c0ffee", "force": True}


def test_creating_a_branch_that_already_exists_is_reported_not_raised():
    seen: List[httpx.Request] = []
    with _client(_answer(422, {"message": "Reference already exists"}), seen) as github:
        assert github.create_branch("b", "c0ffee") is False


def test_opening_a_pull_request_that_already_exists_is_reported_not_raised():
    seen: List[httpx.Request] = []
    payload = {"message": "Validation Failed", "errors": [{"message": "A pull request already exists for acme:b."}]}
    with _client(_answer(422, payload), seen) as github:
        assert github.create_pull(title="t", body="b", head="b", base="main") is None


def test_finding_an_open_pull_request_filters_by_owner_qualified_head():
    seen: List[httpx.Request] = []
    pulls = [{"number": 7, "html_url": "u", "title": "t", "body": None, "base": {"ref": "main"}}]
    with _client(_answer(200, pulls), seen) as github:
        pull = github.find_open_pull("acme", "apiome/sdk-regen-1-w-npm")
    assert seen[0].url.params["head"] == "acme:apiome/sdk-regen-1-w-npm"
    assert seen[0].url.params["state"] == "open"
    assert (pull.number, pull.body, pull.base) == (7, "", "main")


def test_listing_a_directory_walks_one_level_at_a_time_then_recurses():
    seen: List[httpx.Request] = []
    trees = {
        "root": {"tree": [{"path": "sdks", "type": "tree", "sha": "t-sdks"}]},
        "t-sdks": {"tree": [{"path": "ts", "type": "tree", "sha": "t-ts"}]},
        "t-ts": {"tree": [{"path": "package.json", "type": "blob", "sha": "b1", "mode": "100644"}]},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=trees[request.url.path.rsplit("/", 1)[-1]])

    with _client(handler, seen) as github:
        listing = github.list_directory("root", "sdks/ts", ref_label="main")

    assert list(listing) == ["sdks/ts/package.json"]
    assert listing["sdks/ts/package.json"].sha == "b1"
    assert [request.url.params.get("recursive") for request in seen] == [None, None, "1"]


def test_listing_a_directory_that_does_not_exist_is_empty():
    seen: List[httpx.Request] = []
    with _client(_answer(200, {"tree": []}), seen) as github:
        assert github.list_directory("root", "sdks/ts", ref_label="main") == {}


def test_a_target_path_through_a_file_is_refused():
    seen: List[httpx.Request] = []
    with _client(_answer(200, {"tree": [{"path": "sdks", "type": "blob", "sha": "b"}]}), seen) as github:
        with pytest.raises(GitProviderError) as raised:
            github.list_directory("root", "sdks/ts", ref_label="main")
    assert raised.value.code == ERROR_TARGET_PATH_INVALID


def test_an_unreadable_blob_is_none():
    seen: List[httpx.Request] = []
    with _client(_answer(200, {"size": 3, "content": "////"}), seen) as github:
        assert github.get_blob_text("sha") is None


# --------------------------------------------------------------------------------------------
# Refusals are actionable
# --------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "call, status, payload, headers, code, retryable, hint",
    [
        ("repo", 401, {"message": "Bad credentials"}, {}, ERROR_CREDENTIAL_REJECTED, False, "re-link"),
        ("repo", 404, {"message": "Not Found"}, {}, ERROR_REPOSITORY_UNREACHABLE, False, "renamed or deleted"),
        ("repo", 403, {"message": "API rate limit exceeded"}, {"x-ratelimit-remaining": "0"},
         ERROR_RATE_LIMITED, True, "resets"),
        ("repo", 429, {"message": "slow down"}, {}, ERROR_RATE_LIMITED, True, "resets"),
        ("repo", 503, {"message": "unavailable"}, {}, ERROR_PROVIDER_UNAVAILABLE, True, "again"),
        ("tree", 403, {"message": "Resource not accessible by integration"}, {},
         ERROR_PERMISSION_DENIED, False, "`repo` scope"),
        ("tree", 404, {"message": "Not Found"}, {}, ERROR_PERMISSION_DENIED, False, "Contents"),
        ("tree", 409, {"message": "Git Repository is empty."}, {}, ERROR_REPOSITORY_EMPTY, False, "initial commit"),
        ("tree", 422, {"message": "tree.sha is invalid"}, {}, ERROR_PROVIDER_REFUSED, False, "tree.sha"),
        ("ref", 422, {"message": "Update is not a fast forward"}, {}, ERROR_PUSH_REJECTED, False,
         "branch protection"),
        ("ref", 409, {"message": "conflict"}, {}, ERROR_PUSH_REJECTED, False, "delete the branch"),
        ("pull", 422, {"message": "Validation Failed", "errors": [{"message": "No commits between"}]}, {},
         ERROR_PULL_REQUEST_REFUSED, False, "No commits between"),
    ],
)
def test_every_refusal_maps_to_a_code_that_names_the_fix(call, status, payload, headers, code, retryable, hint):
    seen: List[httpx.Request] = []
    calls = {
        "repo": lambda github: github.get_repository(),
        "tree": lambda github: github.create_tree("base", []),
        "ref": lambda github: github.update_branch("b", "sha", force=True),
        "pull": lambda github: github.create_pull(title="t", body="b", head="h", base="main"),
    }
    with _client(_answer(status, payload, headers), seen) as github, pytest.raises(GitProviderError) as raised:
        calls[call](github)
    assert raised.value.code == code
    assert raised.value.retryable is retryable
    assert raised.value.http_status == status
    assert hint in raised.value.message


def test_a_timeout_is_retryable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with _client(handler, []) as github, pytest.raises(GitProviderError) as raised:
        github.get_repository()
    assert raised.value.code == ERROR_PROVIDER_UNAVAILABLE
    assert raised.value.retryable is True


def test_a_network_error_quoting_the_token_is_redacted():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"refused for {_TOKEN}", request=request)

    with _client(handler, []) as github, pytest.raises(GitProviderError) as raised:
        github.get_repository()
    assert _TOKEN not in raised.value.message
    assert GIT_TOKEN_REDACTION_MARKER in raised.value.message


def test_a_refusal_quoting_the_token_is_redacted():
    with _client(_answer(422, {"message": f"bad token {_TOKEN}"}), []) as github, pytest.raises(
        GitProviderError
    ) as raised:
        github.create_tree("base", [])
    assert _TOKEN not in raised.value.message
    assert GIT_TOKEN_REDACTION_MARKER in raised.value.message


def test_a_non_json_error_body_is_still_explained():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>bad gateway</html>")

    with _client(handler, []) as github, pytest.raises(GitProviderError) as raised:
        github.get_repository()
    assert "bad gateway" in raised.value.message
