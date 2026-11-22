"""Linked-account repository registration for GitLab, Bitbucket and Azure DevOps — #6654.

Covers the metadata fetchers in :mod:`app.repository_linked_registration` against a scripted
:class:`httpx.MockTransport`, and ``POST /v1/tenants/{slug}/repositories`` with a linked account of
each provider (the store and the fetch patched, as in ``test_tenant_repositories_api``).
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.repository_linked_registration import (
    fetch_azure_devops_repo_with_token,
    fetch_bitbucket_repo_with_token,
    fetch_gitlab_project_with_token,
    fetch_linked_repository,
    linked_repository_provider,
)

client = TestClient(app)

_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
_USER_ID = "660e8400-e29b-41d4-a716-446655440001"
_LINKED_ACCOUNT_ID = "770e8400-e29b-41d4-a716-446655440002"
_JWT = {"tenant_id": _TENANT_ID, "tenant_slug": "acme", "user_id": _USER_ID, "auth_method": "jwt"}


@pytest.fixture(autouse=True)
def _auth_jwt():
    app.dependency_overrides[validate_authentication] = lambda: _JWT
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _client(status: int, payload: Any, seen: List[httpx.Request]) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handle))


# ===========================================================================
# Which accounts register which repositories
# ===========================================================================


@pytest.mark.parametrize("linked, expected", [("github", "github"), ("GitLab", "gitlab"), ("bitbucket", "bitbucket"),
                                              ("azure", "azure_devops"), ("google", None), (None, None)])
def test_each_linked_account_registers_its_hosts_repositories(linked: Any, expected: Any) -> None:
    assert linked_repository_provider(linked) == expected


# ===========================================================================
# Metadata fetchers
# ===========================================================================


def test_gitlab_reads_a_nested_project_by_its_encoded_path() -> None:
    seen: List[httpx.Request] = []
    payload = {"path_with_namespace": "acme/platform/widgets", "description": "Widgets", "default_branch": "trunk",
               "visibility": "internal", "http_url_to_repo": "https://gitlab.com/acme/platform/widgets.git"}
    meta = fetch_gitlab_project_with_token("tok", "acme/platform/widgets", _client(200, payload, seen))
    assert seen[0].url.raw_path.startswith(b"/api/v4/projects/acme%2Fplatform%2Fwidgets")
    assert seen[0].headers["authorization"] == "Bearer tok"
    assert meta == {"provider": "gitlab", "repository_full_name": "acme/platform/widgets", "description": "Widgets",
                    "default_branch": "trunk", "visibility": "internal",
                    "canonical_clone_url": "https://gitlab.com/acme/platform/widgets.git"}


def test_bitbucket_strips_the_user_from_its_clone_url() -> None:
    seen: List[httpx.Request] = []
    payload = {"full_name": "acme/widgets", "is_private": True, "mainbranch": {"name": "main"},
               "links": {"clone": [{"name": "ssh", "href": "git@bitbucket.org:acme/widgets.git"},
                                   {"name": "https", "href": "https://jane@bitbucket.org/acme/widgets.git"}]}}
    meta = fetch_bitbucket_repo_with_token("tok", "acme/widgets", _client(200, payload, seen))
    assert str(seen[0].url) == "https://api.bitbucket.org/2.0/repositories/acme/widgets"
    assert meta["canonical_clone_url"] == "https://bitbucket.org/acme/widgets.git"
    assert (meta["provider"], meta["visibility"], meta["default_branch"]) == ("bitbucket", "private", "main")


def test_azure_devops_names_the_repository_organization_project_repository() -> None:
    seen: List[httpx.Request] = []
    payload = {"name": "widgets", "defaultBranch": "refs/heads/develop",
               "project": {"name": "Platform Team", "visibility": "private", "description": "Team project"},
               "remoteUrl": "https://acme@dev.azure.com/acme/Platform%20Team/_git/widgets"}
    meta = fetch_azure_devops_repo_with_token("tok", "acme/Platform Team/widgets", _client(200, payload, seen))
    assert seen[0].url.raw_path.startswith(b"/acme/Platform%20Team/_apis/git/repositories/widgets")
    assert seen[0].url.params["api-version"] == "7.1"
    assert meta["repository_full_name"] == "acme/Platform Team/widgets"
    assert meta["default_branch"] == "develop" and meta["provider"] == "azure_devops"
    assert meta["canonical_clone_url"] == "https://dev.azure.com/acme/Platform%20Team/_git/widgets"


@pytest.mark.parametrize("fetch, name", [
    (fetch_gitlab_project_with_token, "just-one-segment"),
    (fetch_bitbucket_repo_with_token, "a/b/c"),
    (fetch_azure_devops_repo_with_token, "org/repo"),
])
def test_a_malformed_name_is_refused_before_any_request(fetch: Any, name: str) -> None:
    seen: List[httpx.Request] = []
    with pytest.raises(ValueError, match="repository_full_name must be"):
        fetch("tok", name, _client(200, {}, seen))
    assert not seen


@pytest.mark.parametrize("status, message", [(401, "Re-link"), (203, "Re-link"), (404, "not accessible"),
                                             (500, "HTTP 500")])
def test_a_refused_read_explains_itself(status: int, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        fetch_azure_devops_repo_with_token("tok", "acme/Platform/widgets", _client(status, {}, []))


def test_a_network_failure_is_a_value_error() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(ValueError, match="could not be reached"):
        fetch_linked_repository("gitlab", "tok", "acme/widgets", httpx.Client(transport=httpx.MockTransport(broken)))


def test_an_unknown_provider_is_refused() -> None:
    with pytest.raises(ValueError, match="does not support"):
        fetch_linked_repository("gitea", "tok", "acme/widgets")


# ===========================================================================
# POST /v1/tenants/{slug}/repositories with a linked account
# ===========================================================================


def _inserted(**fields: Any) -> Dict[str, Any]:
    row = {"id": "880e8400-e29b-41d4-a716-446655440003", "tenant_id": _TENANT_ID, "source": "linked_account",
           "provider": "gitlab", "clone_url": "https://gitlab.com/acme/platform/widgets.git",
           "repository_full_name": "acme/platform/widgets", "description": None, "default_branch": "main",
           "visibility": "private", "status": "scanning", "created_at": None, "updated_at": None,
           "linked_account_id": _LINKED_ACCOUNT_ID, "last_scanned_at": None, "total_files": None,
           "importable_count": None, "branch_count": None}
    row.update(fields)
    return row


_CASES = {
    "gitlab": ("gitlab", "acme/platform/widgets", "https://gitlab.com/acme/platform/widgets.git"),
    "bitbucket": ("bitbucket", "acme/widgets", "https://bitbucket.org/acme/widgets.git"),
    "azure": ("azure_devops", "acme/Platform/widgets", "https://dev.azure.com/acme/Platform/_git/widgets"),
}


@pytest.mark.parametrize("linked", sorted(_CASES))
def test_a_linked_account_of_each_host_registers_its_repository(linked: str) -> None:
    provider, full_name, clone = _CASES[linked]
    meta = {"provider": provider, "repository_full_name": full_name, "description": None, "default_branch": "main",
            "visibility": "private", "canonical_clone_url": clone}
    with patch("app.tenant_repositories_routes.db") as mdb, \
        patch("app.tenant_repositories_routes.fetch_linked_repository", return_value=meta) as fetch, \
        patch("app.tenant_repositories_routes.provision_repository_webhook") as provision:
        provision.return_value.error = None
        mdb.get_external_auth_provider_for_user.return_value = {"id": _LINKED_ACCOUNT_ID, "provider": linked,
                                                                 "access_token": "tok"}
        mdb.insert_tenant_repository.return_value = _inserted(provider=provider, repository_full_name=full_name,
                                                              clone_url=clone)
        response = client.post("/v1/tenants/acme/repositories", json={
            "source": "linked_account", "linkedAccountId": _LINKED_ACCOUNT_ID, "repositoryFullName": full_name})
    assert response.status_code == 200, response.text
    fetch.assert_called_once_with(provider, "tok", full_name)
    kwargs = mdb.insert_tenant_repository.call_args.kwargs
    assert (kwargs["provider"], kwargs["repository_full_name"], kwargs["linked_account_id"]) == (
        provider, full_name, _LINKED_ACCOUNT_ID)
    assert kwargs["clone_url"] == clone
    assert response.json()["repository"]["provider"] == provider


def test_a_name_that_does_not_match_the_hosts_spelling_is_refused() -> None:
    meta = {"provider": "gitlab", "repository_full_name": "acme/other", "canonical_clone_url": "https://gitlab.com/x.git"}
    with patch("app.tenant_repositories_routes.db") as mdb, \
        patch("app.tenant_repositories_routes.fetch_linked_repository", return_value=meta):
        mdb.get_external_auth_provider_for_user.return_value = {"provider": "gitlab", "access_token": "tok"}
        response = client.post("/v1/tenants/acme/repositories", json={
            "source": "linked_account", "linkedAccountId": _LINKED_ACCOUNT_ID, "repositoryFullName": "acme/widgets"})
    assert response.status_code == 400 and "GitLab metadata" in response.json()["detail"]
    mdb.insert_tenant_repository.assert_not_called()


def test_a_clone_url_for_another_repository_is_refused() -> None:
    provider, full_name, clone = _CASES["bitbucket"]
    meta = {"provider": provider, "repository_full_name": full_name, "canonical_clone_url": clone}
    with patch("app.tenant_repositories_routes.db") as mdb, \
        patch("app.tenant_repositories_routes.fetch_linked_repository", return_value=meta):
        mdb.get_external_auth_provider_for_user.return_value = {"provider": "bitbucket", "access_token": "tok"}
        response = client.post("/v1/tenants/acme/repositories", json={
            "source": "linked_account", "linkedAccountId": _LINKED_ACCOUNT_ID, "repositoryFullName": full_name,
            "cloneUrl": "https://bitbucket.org/acme/elsewhere.git"})
    assert response.status_code == 400 and "Bitbucket repository" in response.json()["detail"]


def test_a_fetch_refusal_is_a_400() -> None:
    with patch("app.tenant_repositories_routes.db") as mdb, \
        patch("app.tenant_repositories_routes.fetch_linked_repository",
              side_effect=ValueError("repository not found or not accessible with this linked account")):
        mdb.get_external_auth_provider_for_user.return_value = {"provider": "azure", "access_token": "tok"}
        response = client.post("/v1/tenants/acme/repositories", json={
            "source": "linked_account", "linkedAccountId": _LINKED_ACCOUNT_ID,
            "repositoryFullName": "acme/Platform/widgets"})
    assert response.status_code == 400 and "not accessible" in response.json()["detail"]


def test_an_account_with_no_repository_host_is_refused() -> None:
    with patch("app.tenant_repositories_routes.db") as mdb:
        mdb.get_external_auth_provider_for_user.return_value = {"provider": "google", "access_token": "tok"}
        response = client.post("/v1/tenants/acme/repositories", json={
            "source": "linked_account", "linkedAccountId": _LINKED_ACCOUNT_ID, "repositoryFullName": "acme/widgets"})
    assert response.status_code == 400
    assert "GitHub, GitLab, Bitbucket and Microsoft (Azure DevOps)" in response.json()["detail"]


def test_a_linked_account_without_a_token_names_its_host() -> None:
    with patch("app.tenant_repositories_routes.db") as mdb:
        mdb.get_external_auth_provider_for_user.return_value = {"provider": "gitlab", "access_token": None}
        response = client.post("/v1/tenants/acme/repositories", json={
            "source": "linked_account", "linkedAccountId": _LINKED_ACCOUNT_ID, "repositoryFullName": "acme/widgets"})
    assert response.status_code == 401 and response.json()["detail"].endswith("re-link GitLab")
