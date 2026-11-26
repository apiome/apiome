"""Pact commit statuses without a database — PFX-4.4 (#6941).

Pins the vocabulary (:mod:`app.pact_commit_status`), the GitHub commit-status adapter, where a
verdict may go (:func:`app.pact_commit_status_store.resolve_target`) with every reason it may not,
the send paths of :func:`app.pact_commit_status_store.send_status`, and the routes' RBAC and error
mapping. The live-database half is ``test_pact_commit_status_db``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import pact_commit_status_store as store
from app.auth import validate_authentication
from app.config import settings
from app.main import app
from app.pact_commit_status import (
    CODE_DISABLED,
    CODE_NO_REPOSITORY,
    CODE_NOT_A_COMMIT,
    CODE_PROVIDER_UNSUPPORTED,
    CODE_REPOSITORY_NOT_REGISTERED,
    CODE_STATUS_NOT_FOUND,
    CODE_STATUS_NOT_RETRYABLE,
    MAX_DESCRIPTION_LENGTH,
    OUTCOMES,
    STATES,
    PactCommitStatusError,
    context_for,
    is_commit_sha,
    normalize_repository_url,
    pending_description,
    repository_host,
    verdict_description,
)
from app.provider_checks import CODE_PROVIDER_FORBIDDEN, CODE_PROVIDER_UNAVAILABLE
from app.provider_status_adapter import (
    GitHubCommitStatusAdapter,
    GitLabCommitStatusAdapter,
    PublishRequest,
    StatusPublishError,
    commit_status_adapter_for,
    commit_status_providers,
)

SHA = "4f2a9c1e0b7d3a6f5c8e9d0b1a2c3d4e5f6a7b8c"


# --- Vocabulary ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (SHA, True),
        ("4f2a9c1", True),
        ("4F2A9C1E", True),
        ("a" * 64, True),
        ("4f2a9c", False),  # too short to be a commit
        ("1.0.0", False),
        ("a" * 65, False),
        ("", False),
        (None, False),
        ("4f2a9c1-dirty", False),
    ],
)
def test_is_commit_sha(value: Optional[str], expected: bool) -> None:
    assert is_commit_sha(value) is expected


def test_the_closed_lists_match_the_migration(repo_root: Path) -> None:
    migration = (repo_root / "apiome-db/scripts/V443__pact_commit_statuses_6941.sql").read_text()
    assert "CHECK (state IN ('pending', 'pass', 'fail'))" in migration
    assert "CHECK (outcome IN ('queued', 'dispatched', 'suppressed', 'failed'))" in migration
    assert STATES == ("pending", "pass", "fail")
    assert OUTCOMES == ("queued", "dispatched", "suppressed", "failed")
    # Nothing crosses a tenant, and a status goes with its pacticipant and version.
    assert "UNIQUE (tenant_id, pacticipant_version_id, context)" in migration
    assert migration.count("REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE") == 3
    assert "REFERENCES pacticipant_version (id, pacticipant_id) ON DELETE CASCADE" in migration
    assert "SET search_path TO apiome, public;" in migration
    # No secret column.
    assert "token TEXT" not in migration and "BYTEA" not in migration


def test_repository_urls_normalize_like_the_registration() -> None:
    expected = "https://github.com/acme/web.git"
    for url in ("https://github.com/Acme/Web", "https://github.com/acme/web.git", "https://www.github.com/acme/web/"):
        assert normalize_repository_url(url) == expected
    assert normalize_repository_url("git@github.com:acme/web.git") is None
    assert normalize_repository_url("http://github.com/acme/web") is None
    assert normalize_repository_url("") is None
    assert normalize_repository_url(None) is None
    assert repository_host("https://www.GitHub.com/acme/web") == "github.com"
    assert repository_host("not a url") == ""


def test_context_and_descriptions() -> None:
    assert context_for("web-app", "billing-api") == "apiome-pact/web-app/billing-api"
    assert len(context_for("c" * 200, "p" * 200)) == 255
    assert pending_description("Billing API") == "Pact awaiting verification by Billing API"
    assert verdict_description("consumer", True, "Billing API", SHA) == "Pact verified by Billing API 4f2a9c1e0b7d"
    assert verdict_description("consumer", False, "Billing API", None) == "Pact failed verification by Billing API"
    assert verdict_description("provider", True, "Web App", "1.2.3") == "Pact with Web App 1.2.3 verified"
    assert verdict_description("provider", False, "Web App", None) == "Pact with Web App failed verification"
    long = verdict_description("consumer", True, "x" * 400, None)
    assert len(long) == MAX_DESCRIPTION_LENGTH and long.endswith("…")


# --- The GitHub commit-status adapter -------------------------------------------------------------


class _Recorder:
    """An httpx client factory that records requests and answers with ``status``."""

    def __init__(self, status: int = 201, body: Optional[Dict[str, Any]] = None) -> None:
        self.requests: List[httpx.Request] = []
        self.status = status
        self.body = body if body is not None else {"target_url": "https://broker.example.com/r/1"}

    def __call__(self) -> httpx.Client:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status, json=self.body)

        return httpx.Client(transport=httpx.MockTransport(handle))


def _request(state: str = "pass", **overrides: Any) -> PublishRequest:
    values: Dict[str, Any] = {
        "repo_full_name": "acme/web",
        "commit_sha": SHA,
        "name": "apiome-pact/web/billing",
        "state": state,
        "title": "Pact verified by Billing API",
        "details_url": "https://broker.example.com/r/1",
    }
    values.update(overrides)
    return PublishRequest(**values)


@pytest.mark.parametrize("state, github", [("pending", "pending"), ("pass", "success"), ("fail", "failure")])
def test_github_commit_status_call(state: str, github: str) -> None:
    recorder = _Recorder()
    published = GitHubCommitStatusAdapter("tok", client_factory=recorder).publish(_request(state))
    sent = recorder.requests[0]
    assert sent.method == "POST"
    assert str(sent.url) == f"https://api.github.com/repos/acme/web/statuses/{SHA}"
    assert sent.headers["Authorization"] == "Bearer tok"
    assert json.loads(sent.content) == {
        "state": github,
        "context": "apiome-pact/web/billing",
        "description": "Pact verified by Billing API",
        "target_url": "https://broker.example.com/r/1",
    }
    assert published.status_code == 201
    assert published.url == "https://broker.example.com/r/1"


@pytest.mark.parametrize("state, gitlab", [("pending", "pending"), ("pass", "success"), ("fail", "failed")])
def test_gitlab_commit_status_call(state: str, gitlab: str) -> None:
    method, url, body = GitLabCommitStatusAdapter("tok").build_call(_request(state, repo_full_name="group/sub/web"))
    assert (method, url) == ("POST", f"https://gitlab.com/api/v4/projects/group%2Fsub%2Fweb/statuses/{SHA}")
    assert body == {
        "state": gitlab,
        "name": "apiome-pact/web/billing",
        "description": "Pact verified by Billing API",
        "target_url": "https://broker.example.com/r/1",
    }


def test_github_description_is_trimmed_to_140() -> None:
    _, _, body = GitHubCommitStatusAdapter("tok").build_call(_request(title="x" * 300))
    assert len(body["description"]) == 140 and body["description"].endswith("…")


def test_github_refuses_a_bad_name_or_state() -> None:
    adapter = GitHubCommitStatusAdapter("tok")
    with pytest.raises(StatusPublishError) as bad_name:
        adapter.build_call(_request(repo_full_name="justone"))
    assert bad_name.value.code == "check-provider-refused"
    with pytest.raises(StatusPublishError) as bad_state:
        adapter.build_call(_request(state="weird"))
    assert bad_state.value.code == "check-provider-refused"


def test_commit_status_adapters_cover_github_and_gitlab_only() -> None:
    assert commit_status_providers() == ("github", "gitlab")
    assert isinstance(commit_status_adapter_for("GitHub", "t"), GitHubCommitStatusAdapter)
    assert isinstance(commit_status_adapter_for("gitlab", "t"), GitLabCommitStatusAdapter)
    with pytest.raises(StatusPublishError) as refused:
        commit_status_adapter_for("bitbucket", "t")
    assert refused.value.code == "check-provider-unsupported"


@pytest.mark.parametrize(
    "status, code",
    [(401, CODE_PROVIDER_FORBIDDEN), (404, CODE_PROVIDER_FORBIDDEN), (422, "check-provider-refused"),
     (502, CODE_PROVIDER_UNAVAILABLE)],
)
def test_provider_refusals_carry_a_code_and_no_token(status: int, code: str) -> None:
    recorder = _Recorder(status=status, body={"message": "nope for tok-secret-123"})
    with pytest.raises(StatusPublishError) as refused:
        GitHubCommitStatusAdapter("tok-secret-123", client_factory=recorder).publish(_request())
    assert refused.value.code == code
    assert "tok-secret-123" not in refused.value.message


# --- Where a verdict may go ----------------------------------------------------------------------


class _Cursor:
    """Answers the registered-repository lookup with ``row``."""

    def __init__(self, row: Optional[Dict[str, Any]]) -> None:
        self.row = row
        self.params: List[Any] = []

    def execute(self, _query: str, params: Any) -> None:
        self.params.append(params)

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self.row


_GITHUB_REPO = {
    "id": "11111111-1111-1111-1111-111111111111",
    "provider": "github",
    "clone_url": "https://github.com/Acme/Web.git",
    "repository_full_name": "Acme/Web",
}


def test_a_verdict_with_a_registered_github_repository_is_queued() -> None:
    cursor = _Cursor(_GITHUB_REPO)
    resolution = store.resolve_target(cursor, "t1", "https://github.com/acme/web", SHA.upper())
    assert resolution.outcome == "queued"
    assert resolution.reason_code is None
    assert resolution.commit_sha == SHA
    assert resolution.provider == "github"
    assert resolution.repo_full_name == "acme/web"
    # Looked up by the tenant and the normalized URL.
    assert cursor.params == [("t1", "https://github.com/acme/web.git")]


def test_a_full_name_is_derived_when_the_registration_has_none() -> None:
    row = {**_GITHUB_REPO, "provider": "gitlab", "clone_url": "https://gitlab.com/g/sub/proj.git",
           "repository_full_name": None}
    resolution = store.resolve_target(_Cursor(row), "t1", "https://gitlab.com/g/sub/proj", SHA)
    assert resolution.outcome == "queued"
    assert resolution.repo_full_name == "g/sub/proj"


@pytest.mark.parametrize(
    "repository_url, version, row, code",
    [
        (None, SHA, _GITHUB_REPO, CODE_NO_REPOSITORY),
        ("", SHA, _GITHUB_REPO, CODE_NO_REPOSITORY),
        ("https://github.com/acme/web", "1.0.0", _GITHUB_REPO, CODE_NOT_A_COMMIT),
        ("https://github.com/acme/web", SHA, None, CODE_REPOSITORY_NOT_REGISTERED),
        ("git@github.com:acme/web.git", SHA, _GITHUB_REPO, CODE_REPOSITORY_NOT_REGISTERED),
        ("https://bitbucket.org/acme/web", SHA,
         {**_GITHUB_REPO, "provider": "bitbucket", "clone_url": "https://bitbucket.org/acme/web.git"},
         CODE_PROVIDER_UNSUPPORTED),
        ("https://gitlab.acme.internal/web", SHA,
         {**_GITHUB_REPO, "provider": "gitlab", "clone_url": "https://gitlab.acme.internal/web.git"},
         CODE_PROVIDER_UNSUPPORTED),
    ],
)
def test_every_verdict_that_cannot_go_says_why(
    repository_url: Optional[str], version: str, row: Optional[Dict[str, Any]], code: str
) -> None:
    resolution = store.resolve_target(_Cursor(row), "t1", repository_url, version)
    assert resolution.outcome == "suppressed"
    assert resolution.reason_code == code
    assert resolution.message


def test_switched_off_publishing_records_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "provider_checks_enabled", False)
    resolution = store.resolve_target(_Cursor(_GITHUB_REPO), "t1", "https://github.com/acme/web", SHA)
    assert (resolution.outcome, resolution.reason_code) == ("suppressed", CODE_DISABLED)
    assert resolution.repository_id == _GITHUB_REPO["id"]


# --- Sending -------------------------------------------------------------------------------------


def _row(**overrides: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "id": "s1",
        "tenant_id": "t1",
        "outcome": "queued",
        "repository_id": _GITHUB_REPO["id"],
        "git_provider": "github",
        "repo_full_name": "acme/web",
        "commit_sha": SHA,
        "context": "apiome-pact/web/billing",
        "state": "pass",
        "description": "Pact verified by Billing API",
        "target_url": "https://broker.example.com/r/1",
    }
    row.update(overrides)
    return row


@pytest.fixture
def finished(monkeypatch: pytest.MonkeyPatch) -> List[Dict[str, Any]]:
    """Capture what :func:`send_status` writes back instead of touching a database."""
    calls: List[Dict[str, Any]] = []

    def finish(_db: Any, row: Mapping[str, Any], **changes: Any) -> Dict[str, Any]:
        calls.append(changes)
        return {**row, **changes}

    monkeypatch.setattr(store, "_finish", finish)
    return calls


def test_a_send_that_lands_is_dispatched(monkeypatch: pytest.MonkeyPatch, finished: List[Dict[str, Any]]) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(store, "CLIENT_FACTORY", recorder)
    with patch("app.provider_check_store._repository_token", return_value="tok") as token:
        store.send_status(object(), _row(), actor_id="u1")
    token.assert_called_once_with("t1", _GITHUB_REPO["id"], "u1")
    assert finished == [{"outcome": "dispatched", "http_status": 201, "attempted": True}]
    assert json.loads(recorder.requests[0].content)["state"] == "success"


def test_no_credential_is_suppressed_without_a_request(
    monkeypatch: pytest.MonkeyPatch, finished: List[Dict[str, Any]]
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(store, "CLIENT_FACTORY", recorder)
    with patch("app.provider_check_store._repository_token", return_value=None):
        store.send_status(object(), _row())
    assert finished[0]["outcome"] == "suppressed"
    assert finished[0]["reason_code"] == CODE_PROVIDER_FORBIDDEN
    assert not finished[0].get("attempted")
    assert recorder.requests == []


def test_a_refused_send_is_failed_with_the_providers_reason(
    monkeypatch: pytest.MonkeyPatch, finished: List[Dict[str, Any]]
) -> None:
    monkeypatch.setattr(store, "CLIENT_FACTORY", _Recorder(status=403, body={"message": "Resource not accessible"}))
    with patch("app.provider_check_store._repository_token", return_value="tok"):
        store.send_status(object(), _row())
    assert finished[0]["outcome"] == "failed"
    assert finished[0]["reason_code"] == CODE_PROVIDER_FORBIDDEN
    assert finished[0]["http_status"] == 403
    assert "Resource not accessible" in finished[0]["message"]
    assert finished[0]["attempted"] is True


def test_only_a_queued_row_is_sent(finished: List[Dict[str, Any]]) -> None:
    row = _row(outcome="suppressed")
    assert store.send_status(object(), row) == row
    assert finished == []


def test_a_send_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("vault down")

    monkeypatch.setattr("app.provider_check_store._repository_token", boom)
    row = _row()
    assert store.send_status(object(), row) == row


def test_posting_never_fails_the_publish() -> None:
    class Broken:
        def _guarded_tx(self, _work: Any) -> Any:
            raise RuntimeError("database gone")

    result: Any = type("R", (), {"consumer_slug": "c", "provider_slug": "p"})()
    assert store.post_verification_statuses(Broken(), "t1", "https://b", result) == []


def test_a_publish_that_changed_nothing_posts_nothing() -> None:
    unchanged: Any = type("O", (), {"pacts": [type("P", (), {"created": False, "replaced": False})()]})()

    class Untouched:
        def _guarded_tx(self, _work: Any) -> Any:
            raise AssertionError("must not record anything")

    assert store.post_publish_statuses(Untouched(), "t1", "https://b", unchanged) == []


def test_a_malformed_id_reads_as_not_found() -> None:
    with pytest.raises(PactCommitStatusError) as missing:
        store.retry_commit_status(object(), "t1", "not-a-uuid")
    assert missing.value.code == CODE_STATUS_NOT_FOUND


# --- Routes --------------------------------------------------------------------------------------


@pytest.fixture
def client() -> Any:
    app.dependency_overrides[validate_authentication] = lambda: {"tenant_id": "t1", "user_id": "u1"}
    yield TestClient(app)
    app.dependency_overrides.clear()


_URL = "/v1/tenants/acme/pact-commit-statuses"


def test_listing_needs_pacts_view(client: TestClient) -> None:
    def deny(_db: Any, _auth: Any, resource: str, action: str, **_kw: Any) -> None:
        assert (resource, action) == ("pacts", "view")
        raise HTTPException(status_code=403, detail="no")

    with patch("app.pact_commit_status_routes.enforce_permission", side_effect=deny):
        assert client.get(_URL).status_code == 403


def test_retry_needs_pacts_edit(client: TestClient) -> None:
    def deny(_db: Any, _auth: Any, resource: str, action: str, **_kw: Any) -> None:
        assert (resource, action) == ("pacts", "edit")
        raise HTTPException(status_code=403, detail="no")

    with patch("app.pact_commit_status_routes.enforce_permission", side_effect=deny):
        assert client.post(f"{_URL}/00000000-0000-0000-0000-000000000000/retry").status_code == 403


def test_listing_passes_the_callers_tenant_and_filters(client: TestClient) -> None:
    with (
        patch("app.pact_commit_status_routes.enforce_permission", return_value="u1"),
        patch("app.pact_commit_status_routes.list_commit_statuses", return_value=([], "next")) as listed,
    ):
        response = client.get(_URL, params={"pacticipant": "web", "version": SHA, "outcome": "failed", "limit": 5})
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": "next"}
    assert response.headers["X-Next-Cursor"] == "next"
    args, kwargs = listed.call_args
    assert args[1] == "t1"
    assert kwargs["pacticipant"] == "web" and kwargs["version"] == SHA and kwargs["outcome"] == "failed"
    assert kwargs["limit"] == 5 and kwargs["after"] is None


def test_listing_refuses_an_unknown_outcome_and_a_bad_cursor(client: TestClient) -> None:
    with patch("app.pact_commit_status_routes.enforce_permission", return_value="u1"):
        assert client.get(_URL, params={"outcome": "sent"}).status_code == 400
        assert client.get(_URL, params={"cursor": "garbage"}).status_code == 400
        assert client.get(_URL, params={"limit": 201}).status_code == 422


@pytest.mark.parametrize("code, status", [(CODE_STATUS_NOT_FOUND, 404), (CODE_STATUS_NOT_RETRYABLE, 409)])
def test_retry_errors_map_to_statuses(client: TestClient, code: str, status: int) -> None:
    with (
        patch("app.pact_commit_status_routes.enforce_permission", return_value="u1"),
        patch("app.pact_commit_status_routes.retry_commit_status", side_effect=PactCommitStatusError(code, "x")),
    ):
        response = client.post(f"{_URL}/00000000-0000-0000-0000-000000000000/retry")
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
