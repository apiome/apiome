"""The repository providers export git delivery can write to — MFX-38.1 (#4328).

A git delivery needs a handful of operations from a repository host: read the repository and a
branch, list a directory, create a tree and a commit, move a branch, and open or update a pull
request. :class:`GitDeliveryProvider` names exactly those, and :data:`PROVIDERS` maps a registered
repository's ``provider`` to the client that implements them.

**Four providers.** GitHub uses :class:`app.sdk_git_delivery_github.GitHubGitClient` (the SDK-4.2
and REPO-5.8 client, on the Git Data API without cloning). GitLab, Bitbucket Cloud and Azure DevOps
(#6654) use :class:`app.export_git_delivery_staged.StagedGitProvider` subclasses, which stage the
tree and the commit locally and write them in the host's one commit call
(:mod:`app.export_git_delivery_gitlab`, :mod:`app.export_git_delivery_bitbucket`,
:mod:`app.export_git_delivery_azure_devops`). Each is registered through a linked account of its
own host (``tenant_repositories``); the delivery pipeline has no provider-specific branch.
"""

from __future__ import annotations

from typing import Any, Callable, ContextManager, Dict, List, Optional, Protocol, Tuple

from .export_git_delivery_azure_devops import AzureDevOpsGitClient
from .export_git_delivery_bitbucket import BitbucketGitClient
from .export_git_delivery_gitlab import GitLabGitClient
from .sdk_git_delivery_changes import ExistingEntry
from .sdk_git_delivery_github import ClientFactory, GitHubGitClient, PullRequest, RepositoryInfo

__all__ = [
    "PROVIDERS",
    "PROVIDER_AZURE_DEVOPS",
    "PROVIDER_BITBUCKET",
    "PROVIDER_GITHUB",
    "PROVIDER_GITLAB",
    "PROVIDER_LABELS",
    "SUPPORTED_PROVIDERS",
    "WRITE_ACCESS_HINTS",
    "GitDeliveryProvider",
    "ProviderFactory",
    "open_provider",
    "provider_label",
]

#: ``tenant_repositories.provider`` values a delivery can target.
PROVIDER_GITHUB = "github"
PROVIDER_GITLAB = "gitlab"
PROVIDER_BITBUCKET = "bitbucket"
PROVIDER_AZURE_DEVOPS = "azure_devops"


class GitDeliveryProvider(Protocol):
    """What a repository host must offer for an export to be delivered to it.

    Every method raises :class:`app.sdk_git_delivery_github.GitProviderError` (a stable code, a
    redacted message and whether a retry could help) when the host refuses.
    """

    def get_repository(self) -> RepositoryInfo:
        """The repository's name, owner, default branch, and whether the token may push."""

    def get_branch_sha(self, branch: str) -> Optional[str]:
        """The commit a branch points at, or ``None`` when it does not exist."""

    def get_commit_tree_sha(self, commit_sha: str) -> str:
        """The root tree of a commit."""

    def list_directory(self, root_tree_sha: str, path: str, *, ref_label: str) -> Dict[str, ExistingEntry]:
        """Every entry under ``path`` (recursively), keyed by repository-relative path."""

    def get_blob_text(self, blob_sha: str) -> Optional[str]:
        """A blob's UTF-8 text, or ``None`` when it is not text."""

    def create_blob(self, text: str) -> str:
        """Upload a large file's content; returns the blob id."""

    def create_tree(self, base_tree_sha: str, entries: List[Dict[str, Any]]) -> str:
        """Write a tree on top of ``base_tree_sha`` (an entry with ``sha: None`` deletes a path)."""

    def create_commit(self, message: str, tree_sha: str, parents: List[str]) -> str:
        """Write a commit; returns its id."""

    def create_branch(self, branch: str, commit_sha: str) -> bool:
        """Create a branch; ``False`` when it already exists."""

    def update_branch(self, branch: str, commit_sha: str, *, force: bool) -> None:
        """Move a branch; ``force=False`` refuses anything but a fast-forward."""

    def find_open_pull(self, owner: str, branch: str) -> Optional[PullRequest]:
        """The open pull request from ``branch``, if any."""

    def create_pull(self, *, title: str, body: str, head: str, base: str) -> Optional[PullRequest]:
        """Open a pull request; ``None`` when one is already open from ``head``."""

    def update_pull(self, number: int, *, title: str, body: str, base: str) -> PullRequest:
        """Update a pull request's title, description and base."""

    def resolve_commit(self, commit_sha: str) -> str:
        """The host's id for a commit returned by :meth:`create_commit`, once a branch points at it."""


#: Opens a provider client for ``(token, repository full name, HTTP client factory)``.
ProviderFactory = Callable[[str, str, Optional[ClientFactory]], ContextManager[GitDeliveryProvider]]


def _github(token: str, full_name: str, client_factory: Optional[ClientFactory]) -> ContextManager[Any]:
    return GitHubGitClient(token, full_name, client_factory=client_factory)


def _gitlab(token: str, full_name: str, client_factory: Optional[ClientFactory]) -> ContextManager[Any]:
    return GitLabGitClient(token, full_name, client_factory=client_factory)


def _bitbucket(token: str, full_name: str, client_factory: Optional[ClientFactory]) -> ContextManager[Any]:
    return BitbucketGitClient(token, full_name, client_factory=client_factory)


def _azure_devops(token: str, full_name: str, client_factory: Optional[ClientFactory]) -> ContextManager[Any]:
    return AzureDevOpsGitClient(token, full_name, client_factory=client_factory)


#: ``tenant_repositories.provider`` → the client that delivers to it.
PROVIDERS: Dict[str, ProviderFactory] = {
    PROVIDER_GITHUB: _github,
    PROVIDER_GITLAB: _gitlab,
    PROVIDER_BITBUCKET: _bitbucket,
    PROVIDER_AZURE_DEVOPS: _azure_devops,
}

#: The providers a delivery can target, in the order the API lists them.
SUPPORTED_PROVIDERS: Tuple[str, ...] = tuple(PROVIDERS)

#: How messages name each provider.
PROVIDER_LABELS: Dict[str, str] = {
    PROVIDER_GITHUB: "GitHub",
    PROVIDER_GITLAB: "GitLab",
    PROVIDER_BITBUCKET: "Bitbucket",
    PROVIDER_AZURE_DEVOPS: "Azure DevOps",
}

#: What the linked account's token needs before a delivery can push, per provider.
WRITE_ACCESS_HINTS: Dict[str, str] = {
    PROVIDER_GITHUB: "Grant that account write access (and the token the `repo` scope, or Contents and Pull "
                     "requests write access)",
    PROVIDER_GITLAB: GitLabGitClient.WRITE_ACCESS_HINT.rstrip("."),
    PROVIDER_BITBUCKET: BitbucketGitClient.WRITE_ACCESS_HINT.rstrip("."),
    PROVIDER_AZURE_DEVOPS: AzureDevOpsGitClient.WRITE_ACCESS_HINT.rstrip("."),
}


def provider_label(provider: Optional[str]) -> str:
    """How a message names a provider (``GitLab``); an unknown one is returned as given."""
    key = str(provider or "").strip().lower()
    return PROVIDER_LABELS.get(key, key or "the provider")


def open_provider(
    provider: str, token: str, full_name: str, *, client_factory: Optional[ClientFactory] = None
) -> ContextManager[GitDeliveryProvider]:
    """Open the client for a repository's provider.

    Args:
        provider: ``tenant_repositories.provider`` (one of :data:`SUPPORTED_PROVIDERS`).
        token: The repository's linked-account token.
        full_name: The registered name (``owner/repo``; a GitLab ``group/subgroup/project``; an Azure
            DevOps ``organization/project/repository``).
        client_factory: How to obtain the HTTP client; injected by tests.

    Returns:
        A context manager yielding the :class:`GitDeliveryProvider`.

    Raises:
        KeyError: When the provider has no delivery client (callers check
            :data:`SUPPORTED_PROVIDERS` first and report it as a failed run).
    """
    return PROVIDERS[str(provider or "").strip().lower()](token, full_name, client_factory)
