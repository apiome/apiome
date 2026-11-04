"""The repository providers export git delivery can write to — MFX-38.1 (#4328).

A git delivery needs a handful of operations from a repository host: read the repository and a
branch, list a directory, create a tree and a commit, move a branch, and open or update a pull
request. :class:`GitDeliveryProvider` names exactly those, and :data:`PROVIDERS` maps a registered
repository's ``provider`` to the client that implements them.

**GitHub is the one provider today.** It is the only host Apiome can register a repository for
through a linked account (``tenant_repositories``), and the only one with a write client
(:class:`app.sdk_git_delivery_github.GitHubGitClient`, the SDK-4.2 and REPO-5.8 client, which works
on the Git Data API without cloning). GitLab, Bitbucket and Azure DevOps have no write client and
no linked-account repository registration yet; each one is a new entry here — a client implementing
this protocol — plus registration support, without any change to the delivery pipeline.
"""

from __future__ import annotations

from typing import Any, Callable, ContextManager, Dict, List, Optional, Protocol, Tuple

from .sdk_git_delivery_changes import ExistingEntry
from .sdk_git_delivery_github import ClientFactory, GitHubGitClient, PullRequest, RepositoryInfo

__all__ = [
    "PROVIDERS",
    "SUPPORTED_PROVIDERS",
    "GitDeliveryProvider",
    "ProviderFactory",
    "open_provider",
]


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


#: Opens a provider client for ``(token, repository full name, HTTP client factory)``.
ProviderFactory = Callable[[str, str, Optional[ClientFactory]], ContextManager[GitDeliveryProvider]]


def _github(token: str, full_name: str, client_factory: Optional[ClientFactory]) -> ContextManager[Any]:
    return GitHubGitClient(token, full_name, client_factory=client_factory)


#: ``tenant_repositories.provider`` → the client that delivers to it.
PROVIDERS: Dict[str, ProviderFactory] = {"github": _github}

#: The providers a delivery can target, in the order the API lists them.
SUPPORTED_PROVIDERS: Tuple[str, ...] = tuple(PROVIDERS)


def open_provider(
    provider: str, token: str, full_name: str, *, client_factory: Optional[ClientFactory] = None
) -> ContextManager[GitDeliveryProvider]:
    """Open the client for a repository's provider.

    Args:
        provider: ``tenant_repositories.provider`` (``github``).
        token: The repository's linked-account token.
        full_name: ``owner/repo``.
        client_factory: How to obtain the HTTP client; injected by tests.

    Returns:
        A context manager yielding the :class:`GitDeliveryProvider`.

    Raises:
        KeyError: When the provider has no delivery client (callers check
            :data:`SUPPORTED_PROVIDERS` first and report it as a failed run).
    """
    return PROVIDERS[str(provider or "").strip().lower()](token, full_name, client_factory)
