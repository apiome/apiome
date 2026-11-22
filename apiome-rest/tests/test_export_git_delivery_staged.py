"""The staging half of the GitLab, Bitbucket and Azure DevOps delivery clients — #6654.

Unit tests of :mod:`app.export_git_delivery_staged` (tree handles, the ``Apiome-Tree:`` trailer,
staged commits and error mapping) and of the provider-aware eligibility rules in
:func:`app.sdk_git_delivery_targets.repository_problem`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
import pytest

from app.export_git_delivery_providers import (
    PROVIDERS,
    SUPPORTED_PROVIDERS,
    WRITE_ACCESS_HINTS,
    open_provider,
    provider_label,
)
from app.export_git_delivery_staged import (
    KIND_PULL,
    KIND_PUSH,
    KIND_READ,
    KIND_REPOSITORY,
    STAGED_TREE_PREFIX,
    WRITE_CREATE,
    WRITE_FAST_FORWARD,
    WRITE_FORCE,
    FileChange,
    StagedGitProvider,
    bytes_blob_sha,
    provider_message,
    read_tree_trailer,
    with_tree_trailer,
)
from app.sdk_git_delivery_changes import ExistingEntry, git_blob_sha
from app.sdk_git_delivery_github import GitHubGitClient, GitProviderError
from app.sdk_git_delivery_targets import repository_name_is_valid, repository_problem


class _Recorder(StagedGitProvider):
    """A staged provider whose host calls are recorded rather than sent."""

    LABEL = "Host"
    WRITE_ACCESS_HINT = "Grant write."

    def __init__(self) -> None:
        super().__init__("secret-token-value", "acme/widgets")
        self.messages: Dict[str, Optional[str]] = {"base": "init", "apiome": "x"}
        self.writes: List[Dict[str, Any]] = []

    def _read_commit_message(self, commit_sha: str) -> Optional[str]:
        return self.messages.get(commit_sha, "")

    def _list_directory(self, commit_sha: str, path: str, *, ref_label: str) -> Dict[str, ExistingEntry]:
        return {"specs/a.yaml": ExistingEntry("specs/a.yaml", git_blob_sha("old\n"))}

    def _write_commit(self, branch: str, *, message: str, parent: str, changes: List[FileChange], mode: str) -> str:
        self.writes.append({"branch": branch, "message": message, "parent": parent, "changes": changes, "mode": mode})
        return f"written-{len(self.writes)}"

    def get_branch_sha(self, branch: str) -> Optional[str]:
        return "base" if branch == "main" else None


def test_bytes_and_text_blob_ids_agree() -> None:
    assert bytes_blob_sha("héllo\n".encode("utf-8")) == git_blob_sha("héllo\n")


def test_the_tree_trailer_round_trips_and_the_last_one_wins() -> None:
    handle = STAGED_TREE_PREFIX + "a" * 40
    message = with_tree_trailer("Title\n\nBody\n\n", handle)
    assert message.endswith(f"\n\nApiome-Tree: {handle}\n") and read_tree_trailer(message) == handle
    other = STAGED_TREE_PREFIX + "b" * 40
    assert read_tree_trailer(f"x\nApiome-Tree: {handle}\nApiome-Tree: {other}\n") == other
    assert read_tree_trailer("no trailer") is None and read_tree_trailer(None) is None
    assert read_tree_trailer("Apiome-Tree: not-a-handle") is None


def test_a_plain_commit_names_its_tree_by_the_commit_and_a_delivered_one_by_its_trailer() -> None:
    provider = _Recorder()
    handle = STAGED_TREE_PREFIX + "c" * 40
    provider.messages["apiome"] = with_tree_trailer("Export", handle)
    assert provider.get_commit_tree_sha("base") == "base^{tree}"
    assert provider.get_commit_tree_sha("apiome") == handle


def test_identical_changes_on_the_same_base_stage_the_same_tree() -> None:
    provider = _Recorder()
    base = provider.get_commit_tree_sha("base")
    first = provider.create_tree(base, [{"path": "specs/a.yaml", "content": "new\n"}])
    second = provider.create_tree(base, [{"path": "specs/a.yaml", "content": "new\n"}])
    third = provider.create_tree(base, [{"path": "specs/a.yaml", "content": "other\n"}])
    assert first == second != third and first.startswith(STAGED_TREE_PREFIX)


def test_a_staged_commit_is_written_once_a_branch_moves_and_resolves_to_the_hosts_id() -> None:
    provider = _Recorder()
    base = provider.get_commit_tree_sha("base")
    provider.list_directory(base, "specs", ref_label="main")
    blob = provider.create_blob("large\n")
    tree = provider.create_tree(base, [{"path": "specs/a.yaml", "content": "new\n"},
                                       {"path": "specs/big.json", "sha": blob},
                                       {"path": "specs/gone.yaml", "sha": None}])
    commit = provider.create_commit("Export", tree, ["base"])
    assert not provider.writes and provider.resolve_commit(commit) == commit
    provider.update_branch("main", commit, force=False)
    [write] = provider.writes
    assert write["mode"] == WRITE_FAST_FORWARD and write["parent"] == "base"
    assert read_tree_trailer(write["message"]) == tree
    assert [(c.path, c.text, c.exists) for c in write["changes"]] == [
        ("specs/a.yaml", "new\n", True), ("specs/big.json", "large\n", False), ("specs/gone.yaml", None, False)]
    assert provider.resolve_commit(commit) == "written-1"


def test_force_and_create_choose_their_write_mode() -> None:
    provider = _Recorder()
    base = provider.get_commit_tree_sha("base")
    commit = provider.create_commit("Export", provider.create_tree(base, []), ["base"])
    provider.update_branch("feature", commit, force=True)
    assert provider.create_branch("feature", commit) is True
    assert [w["mode"] for w in provider.writes] == [WRITE_FORCE, WRITE_CREATE]


def test_create_branch_reports_an_existing_branch_as_false() -> None:
    provider = _Recorder()
    base = provider.get_commit_tree_sha("base")
    commit = provider.create_commit("Export", provider.create_tree(base, []), ["base"])

    def refuse(*args: Any, **kwargs: Any) -> str:
        raise GitProviderError("sdk-git-delivery-push-rejected", "exists")

    provider._write_commit = refuse  # type: ignore[method-assign]
    assert provider.create_branch("main", commit) is False
    with pytest.raises(GitProviderError):
        provider.create_branch("missing", commit)


def test_a_commit_that_does_not_match_its_tree_is_refused() -> None:
    provider = _Recorder()
    tree = provider.create_tree(provider.get_commit_tree_sha("base"), [])
    with pytest.raises(GitProviderError):
        provider.create_commit("Export", tree, ["elsewhere"])
    with pytest.raises(GitProviderError):
        provider.create_commit("Export", tree, ["base", "other"])
    with pytest.raises(GitProviderError):
        provider.update_branch("main", "deadbeef", force=False)
    with pytest.raises(GitProviderError):
        provider.create_tree("never-read^{tree}", [])
    with pytest.raises(GitProviderError):
        provider.create_tree(provider.get_commit_tree_sha("base"), [{"path": "x", "sha": "apiome-blob:nope"}])


def test_a_fast_forward_check_refuses_a_moved_branch() -> None:
    provider = _Recorder()
    with pytest.raises(GitProviderError) as caught:
        provider._refuse_moved_branch("main", "older")
    assert caught.value.code == "sdk-git-delivery-push-rejected"
    provider._refuse_moved_branch("main", "base")


@pytest.mark.parametrize("status, kind, detail, code", [
    (401, KIND_READ, "bad token", "sdk-git-delivery-credential-rejected"),
    (429, KIND_READ, "slow down", "sdk-git-delivery-rate-limited"),
    (404, KIND_REPOSITORY, "gone", "sdk-git-delivery-repository-unreachable"),
    (403, KIND_PUSH, "branch is protected", "sdk-git-delivery-push-rejected"),
    (409, KIND_PUSH, "moved", "sdk-git-delivery-push-rejected"),
    (403, KIND_PUSH, "Forbidden", "sdk-git-delivery-permission-denied"),
    (404, KIND_PULL, "nope", "sdk-git-delivery-permission-denied"),
    (422, KIND_PULL, "invalid", "sdk-git-delivery-pull-request-refused"),
    (503, KIND_READ, "down", "sdk-git-delivery-provider-unavailable"),
    (418, KIND_READ, "teapot", "sdk-git-delivery-provider-refused"),
])
def test_refusals_map_to_the_shared_codes_and_redact_the_token(status: int, kind: str, detail: str, code: str) -> None:
    provider = _Recorder()
    error = provider._error(httpx.Response(status, json={"message": f"{detail} secret-token-value"}),
                            what="testing", kind=kind)
    assert error.code == code and "secret-token-value" not in error.message
    assert error.retryable == (code in ("sdk-git-delivery-rate-limited", "sdk-git-delivery-provider-unavailable"))


@pytest.mark.parametrize("payload, text", [
    ({"message": "plain"}, "plain"),
    ({"message": ["first", "second"]}, "first: second"),
    ({"error": {"message": "bitbucket", "detail": "more"}}, "bitbucket: more"),
    ({"error": "invalid_token", "error_description": "expired"}, "invalid_token: expired"),
    ({}, "no detail"),
])
def test_provider_messages_are_read_from_each_hosts_shape(payload: Dict[str, Any], text: str) -> None:
    assert provider_message(httpx.Response(400, json=payload)) == text


def test_every_supported_provider_has_a_client_a_label_and_a_hint() -> None:
    assert SUPPORTED_PROVIDERS == ("github", "gitlab", "bitbucket", "azure_devops")
    for provider in SUPPORTED_PROVIDERS:
        assert provider in PROVIDERS and WRITE_ACCESS_HINTS[provider] and provider_label(provider) != provider
    assert provider_label("gitea") == "gitea"
    with open_provider("GitHub", "t", "acme/widgets") as github:
        assert isinstance(github, GitHubGitClient) and github.resolve_commit("abc") == "abc"


# ===========================================================================
# repository_problem with the export channel's providers
# ===========================================================================


@pytest.mark.parametrize("provider, name, valid", [
    ("github", "acme/widgets", True),
    ("github", "acme/platform/widgets", False),
    ("gitlab", "acme/platform/widgets", True),
    ("gitlab", "widgets", False),
    ("bitbucket", "acme/widgets", True),
    ("bitbucket", "acme/a/b", False),
    ("azure_devops", "acme/Platform Team/widgets", True),
    ("azure_devops", "acme/widgets", False),
])
def test_each_provider_has_its_own_name_shape(provider: str, name: str, valid: bool) -> None:
    assert repository_name_is_valid(provider, name) is valid


def _row(**fields: Any) -> Dict[str, Any]:
    row = {"provider": "gitlab", "repository_full_name": "acme/platform/widgets", "linked_account_id": "linked"}
    row.update(fields)
    return row


def test_sdk_delivery_still_supports_github_only() -> None:
    problem = repository_problem(_row())
    assert problem is not None and problem.code == "sdk-git-delivery-provider-unsupported"


def test_export_delivery_accepts_each_of_its_providers() -> None:
    for provider, name in [("gitlab", "acme/platform/widgets"), ("bitbucket", "acme/widgets"),
                           ("azure_devops", "acme/Platform/widgets"), ("github", "acme/widgets")]:
        assert repository_problem(_row(provider=provider, repository_full_name=name),
                                  supported_providers=SUPPORTED_PROVIDERS) is None


def test_an_unlinked_or_misnamed_repository_names_its_provider() -> None:
    unlinked = repository_problem(_row(linked_account_id=None), supported_providers=SUPPORTED_PROVIDERS)
    assert unlinked is not None and "linked GitLab account" in unlinked.message
    misnamed = repository_problem(_row(provider="azure_devops", repository_full_name="acme/widgets"),
                                  supported_providers=SUPPORTED_PROVIDERS)
    assert misnamed is not None and misnamed.code == "sdk-git-delivery-repository-invalid"
    assert "Azure DevOps" in misnamed.message
