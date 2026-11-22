"""The shared half of the GitLab, Bitbucket and Azure DevOps delivery clients — #6654.

Export git delivery (:mod:`app.export_git_delivery_pipeline`) speaks GitHub's Git Data API: create a
tree, create a commit, then move a branch to it. GitLab, Bitbucket and Azure DevOps have no such
API — each writes a commit and moves a branch **in one call** (GitLab's Commits API, Bitbucket's
``/src`` form, Azure DevOps' Pushes API). :class:`StagedGitProvider` bridges the two shapes so the
pipeline needs no provider-specific branch:

* :meth:`~StagedGitProvider.create_blob`, :meth:`~StagedGitProvider.create_tree` and
  :meth:`~StagedGitProvider.create_commit` write nothing. They **stage** the change in memory and
  hand back a local handle (``apiome-tree:…``, ``apiome-commit:…``).
* :meth:`~StagedGitProvider.create_branch` and :meth:`~StagedGitProvider.update_branch` turn a staged
  commit into the one real write, through the subclass's :meth:`~StagedGitProvider._write_commit`,
  and remember the commit id the host gave it (:meth:`~StagedGitProvider.resolve_commit`).

**Tree identity.** The pipeline decides a pull request is ``unchanged`` by comparing the delivery
branch's tree with the tree it would write. These hosts expose no writable tree ids, so a staged
tree is named by a digest of its base and its file changes, and every commit Apiome writes carries
that name as an ``Apiome-Tree:`` trailer in its message. Reading a commit's tree
(:meth:`~StagedGitProvider.get_commit_tree_sha`) returns the trailer when there is one, and
``<sha>^{tree}`` otherwise, so an identical re-delivery on the same base compares equal and writes
nothing, while any other commit compares different and is rebuilt.

**Errors.** Every refusal becomes the same :class:`app.sdk_git_delivery_github.GitProviderError`
codes the GitHub client raises (re-prefixed ``export-git-delivery-*`` by the pipeline), with the
token redacted from the message. Each host is fixed (``gitlab.com``, ``api.bitbucket.org``,
``dev.azure.com``) — never a tenant-supplied URL — so there is no request-forgery surface.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Type

import httpx

from .sdk_git_delivery_changes import ExistingEntry, git_blob_sha
from .sdk_git_delivery_github import (
    ERROR_CREDENTIAL_REJECTED,
    ERROR_PERMISSION_DENIED,
    ERROR_PROVIDER_REFUSED,
    ERROR_PROVIDER_UNAVAILABLE,
    ERROR_PULL_REQUEST_REFUSED,
    ERROR_PUSH_REJECTED,
    ERROR_RATE_LIMITED,
    ERROR_REPOSITORY_UNREACHABLE,
    GIT_TOKEN_REDACTION_MARKER,
    REQUEST_TIMEOUT_SECONDS,
    ClientFactory,
    GitProviderError,
    PullRequest,
    RepositoryInfo,
)
from .sdk_registry_credentials import redact_secrets

logger = logging.getLogger(__name__)

__all__ = [
    "BLOB_READ_MAX_BYTES",
    "KIND_PULL",
    "KIND_PUSH",
    "KIND_READ",
    "KIND_REPOSITORY",
    "KIND_WRITE",
    "STAGED_COMMIT_PREFIX",
    "STAGED_TREE_PREFIX",
    "TREE_TRAILER",
    "WRITE_CREATE",
    "WRITE_FAST_FORWARD",
    "WRITE_FORCE",
    "FileChange",
    "StagedGitProvider",
    "bytes_blob_sha",
    "provider_message",
    "read_tree_trailer",
    "with_tree_trailer",
]

#: The commit-message trailer naming the staged tree a commit was written from.
TREE_TRAILER = "Apiome-Tree"

#: Prefixes of the local handles staging hands back.
STAGED_TREE_PREFIX = "apiome-tree:"
STAGED_COMMIT_PREFIX = "apiome-commit:"
_STAGED_BLOB_PREFIX = "apiome-blob:"

#: Largest blob read back (the previous delivery manifest).
BLOB_READ_MAX_BYTES = 1_000_000

#: How much of a host's error message is kept.
_MESSAGE_MAX_CHARS = 400

#: Identifies the caller in each host's audit logs.
USER_AGENT = "apiome-export-git-delivery"

#: What kind of call failed, which decides what a 404 or a 409 means.
KIND_REPOSITORY = "repository"
KIND_READ = "read"
KIND_WRITE = "write"
KIND_PUSH = "push"
KIND_PULL = "pull"

#: How :meth:`StagedGitProvider._write_commit` must move the branch.
WRITE_CREATE = "create"  #: the branch does not exist yet; create it at the new commit
WRITE_FORCE = "force"  #: replace the branch with the new commit, whatever it held
WRITE_FAST_FORWARD = "fast-forward"  #: only when the branch still points at the commit's parent

_TRAILER_PATTERN = re.compile(
    rf"^{TREE_TRAILER}:\s*({re.escape(STAGED_TREE_PREFIX)}[0-9a-f]{{40}})\s*$", re.MULTILINE
)


def bytes_blob_sha(data: bytes) -> str:
    """Compute the git blob id of raw bytes (``sha1("blob <len>\\0" + data)``).

    Args:
        data: The file's bytes as the repository stores them.

    Returns:
        The 40-character hex object id — the id :func:`app.sdk_git_delivery_changes.git_blob_sha`
        gives the same content as text.
    """
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def with_tree_trailer(message: str, tree: str) -> str:
    """Append the ``Apiome-Tree:`` trailer to a commit message.

    Args:
        message: The commit message the pipeline wrote.
        tree: The staged tree handle.

    Returns:
        The message, a blank line, and the trailer.
    """
    return f"{message.rstrip()}\n\n{TREE_TRAILER}: {tree}\n"


def read_tree_trailer(message: Optional[str]) -> Optional[str]:
    """Read the staged tree a commit was written from.

    Args:
        message: A commit message, as the host returns it.

    Returns:
        The last ``Apiome-Tree:`` handle in the message, or ``None`` when there is none.
    """
    matches = _TRAILER_PATTERN.findall(message or "")
    return matches[-1] if matches else None


def provider_message(response: httpx.Response) -> str:
    """Extract a host's own explanation from an error response.

    Handles the three shapes these hosts use: ``{"message": …}`` (GitLab, Azure DevOps),
    ``{"error": "…"}`` or ``{"message": ["…"]}`` (GitLab validation), and
    ``{"error": {"message": …, "detail": …}}`` (Bitbucket).

    Args:
        response: The failed response.

    Returns:
        The message, whitespace-collapsed and bounded in length; ``"no detail"`` when there is none.
    """
    try:
        payload = response.json()
    except ValueError:
        payload = None
    parts: List[str] = []
    if isinstance(payload, dict):
        for key in ("message", "error", "error_description"):
            value = payload.get(key)
            if isinstance(value, dict):
                parts += [str(value.get("message") or ""), str(value.get("detail") or "")]
            elif isinstance(value, list):
                parts += [str(item) for item in value]
            elif value:
                parts.append(str(value))
    else:
        parts.append((response.text or "")[:_MESSAGE_MAX_CHARS])
    text = " ".join(": ".join(part.strip() for part in parts if part and part.strip()).split())
    return text[:_MESSAGE_MAX_CHARS] or "no detail"


@dataclass(frozen=True)
class FileChange:
    """One file a staged commit writes or removes.

    Attributes:
        path: Repository-relative path.
        text: The new content, or ``None`` to remove the file.
        exists: Whether the base commit holds the path (an update rather than a create).
    """

    path: str
    text: Optional[str]
    exists: bool


@dataclass
class _StagedTree:
    """A tree waiting to be written: a base commit plus file changes."""

    base_commit: str
    files: Dict[str, Optional[str]] = field(default_factory=dict)


@dataclass
class _StagedCommit:
    """A commit waiting to be written."""

    message: str
    tree: str
    parent: str


def _default_client_factory() -> httpx.Client:
    """A client with a bounded timeout that follows the host's own redirects."""
    return httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True)


class StagedGitProvider:
    """A :class:`app.export_git_delivery_providers.GitDeliveryProvider` for a commit-in-one-call host.

    Subclasses set :attr:`LABEL`, :attr:`WRITE_ACCESS_HINT` and :attr:`BRANCH_RULE_WORDS`, build
    request URLs, and implement the ``_``-prefixed host calls; the staging, the tree identity, the
    transport and the error mapping live here.

    Args:
        token: The repository's linked-account token, sent only in the ``Authorization`` header.
        full_name: The repository's registered name (its shape is the host's).
        client_factory: How to obtain the HTTP client; injected by tests.
    """

    #: How messages name the host ("GitLab").
    LABEL = "the provider"
    #: What a token needs to deliver, quoted when the host refuses a write.
    WRITE_ACCESS_HINT = ""
    #: Lower-case words that mark a refusal as a branch rule rather than missing access.
    BRANCH_RULE_WORDS: Tuple[str, ...] = ("protected",)

    def __init__(self, token: str, full_name: str, *, client_factory: Optional[ClientFactory] = None) -> None:
        self._token = token
        self._full_name = full_name
        self._factory = client_factory or _default_client_factory
        self._client: Optional[httpx.Client] = None
        self._blobs: Dict[str, str] = {}
        self._trees: Dict[str, _StagedTree] = {}
        self._commits: Dict[str, _StagedCommit] = {}
        self._tree_commits: Dict[str, str] = {}
        self._known_paths: Dict[str, set] = {}
        self._written: Dict[str, str] = {}

    # -- lifecycle -----------------------------------------------------------------------------

    def __enter__(self) -> "StagedGitProvider":
        self._client = self._factory()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # -- transport -----------------------------------------------------------------------------

    def _redact(self, text: str) -> str:
        """Scrub the token from a message."""
        return redact_secrets(text, [self._token], marker=GIT_TOKEN_REDACTION_MARKER)

    def _headers(self) -> Dict[str, str]:
        """The headers every request carries: the bearer token and the user agent."""
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json", "User-Agent": USER_AGENT}

    def _send(
        self,
        method: str,
        url: str,
        *,
        what: str,
        kind: str,
        ok: Iterable[int] = (200,),
        json: Optional[Any] = None,
        params: Optional[Mapping[str, Any]] = None,
        data: Optional[Any] = None,
    ) -> httpx.Response:
        """Send one request and return the response when its status is expected.

        Args:
            method: HTTP method.
            url: The absolute URL, always on the subclass's fixed host.
            what: What the call does, phrased to complete "while …" in an error message.
            kind: Which ``KIND_*`` the call is, deciding what a 404 or 409 means.
            ok: The statuses that are not errors (a caller that treats 404 as "absent" passes it).
            json: JSON request body.
            params: Query parameters.
            data: Form body (Bitbucket's ``/src``).

        Returns:
            The response.

        Raises:
            GitProviderError: For a network failure or any status outside ``ok``.
            RuntimeError: When used outside ``with``.
        """
        if self._client is None:
            raise RuntimeError(f"{type(self).__name__} must be used as a context manager")
        try:
            response = self._client.request(
                method, url, headers=self._headers(), json=json, params=dict(params or {}) or None, data=data
            )
        except httpx.TimeoutException as exc:
            raise GitProviderError(
                ERROR_PROVIDER_UNAVAILABLE,
                f"{self.LABEL} did not answer within {REQUEST_TIMEOUT_SECONDS:.0f}s while {what}. Try the "
                "delivery again.",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise GitProviderError(
                ERROR_PROVIDER_UNAVAILABLE,
                self._redact(f"{self.LABEL} could not be reached while {what}: {exc}"),
                retryable=True,
            ) from exc
        if response.status_code in set(ok):
            return response
        raise self._error(response, what=what, kind=kind)

    def _is_credential_failure(self, response: httpx.Response) -> bool:
        """Whether a response means the token itself was refused (a 401, by default)."""
        return response.status_code == 401

    def _is_branch_rule(self, status: int, detail: str) -> bool:
        """Whether a refused push names a branch rule rather than missing access."""
        lowered = detail.lower()
        return status != 403 or any(word in lowered for word in self.BRANCH_RULE_WORDS)

    def _error(self, response: httpx.Response, *, what: str, kind: str) -> GitProviderError:
        """Translate a refusal into an actionable :class:`GitProviderError`.

        Args:
            response: The host's answer.
            what: What the call was doing.
            kind: Which ``KIND_*`` the call is.

        Returns:
            The error to raise, redacted.
        """
        status = response.status_code
        detail = provider_message(response)
        repo = self._full_name
        label = self.LABEL

        def fail(code: str, message: str, retryable: bool = False) -> GitProviderError:
            return GitProviderError(code, self._redact(message), http_status=status, retryable=retryable)

        if status == 429:
            retry = response.headers.get("retry-after")
            when = f" (retry after {retry}s)" if retry else ""
            return fail(ERROR_RATE_LIMITED, f"{label}'s API rate limit for the linked account was exhausted while "
                        f"{what}{when}. Deliver again once it resets.", retryable=True)
        if self._is_credential_failure(response):
            return fail(ERROR_CREDENTIAL_REJECTED, f"{label} rejected the linked account's token while {what} "
                        f"(HTTP {status}: {detail}). The token has expired, been revoked, or was not issued for "
                        f"{label} — re-link the account that registered {repo}, then deliver again.")
        if status == 404 and kind == KIND_REPOSITORY:
            return fail(ERROR_REPOSITORY_UNREACHABLE, f"{repo} was not found with the linked account's token "
                        "(HTTP 404). The repository was renamed or deleted, or that account can no longer see "
                        "it — check the repository, or re-register it through an account with access.")
        if kind == KIND_PUSH and status in (400, 403, 409, 422) and self._is_branch_rule(status, detail):
            return fail(ERROR_PUSH_REJECTED, f"{label} rejected the push while {what} (HTTP {status}: {detail}). "
                        "A branch rule may forbid it, or the branch moved while the delivery ran — allow the "
                        "linked account to push, then deliver again.")
        if status == 403 or (status == 404 and kind in (KIND_WRITE, KIND_PUSH, KIND_PULL)):
            hint = f"{self.WRITE_ACCESS_HINT} " if self.WRITE_ACCESS_HINT else ""
            return fail(ERROR_PERMISSION_DENIED, f"The linked account's token is not allowed to write to {repo} "
                        f"while {what} (HTTP {status}: {detail}). {hint}Update the linked account, then deliver "
                        "again.")
        if kind == KIND_PULL and status in (400, 409, 422):
            return fail(ERROR_PULL_REQUEST_REFUSED, f"{label} refused the pull request while {what} (HTTP "
                        f"{status}: {detail}). The commit was pushed; open the pull request by hand, or fix the "
                        "cause and deliver again.")
        if status >= 500:
            return fail(ERROR_PROVIDER_UNAVAILABLE, f"{label} failed while {what} (HTTP {status}: {detail}). Try "
                        "the delivery again.", retryable=True)
        return fail(ERROR_PROVIDER_REFUSED, f"{label} refused the request while {what} (HTTP {status}: {detail}).")

    # -- staging (the GitDeliveryProvider write half) -----------------------------------------

    def get_commit_tree_sha(self, commit_sha: str) -> str:
        """Name a commit's tree: its ``Apiome-Tree:`` trailer, or ``<sha>^{tree}``.

        Args:
            commit_sha: A commit on the host.

        Returns:
            A tree handle that :meth:`list_directory` and :meth:`create_tree` accept.
        """
        trailer = read_tree_trailer(self._read_commit_message(commit_sha))
        handle = trailer or f"{commit_sha}^{{tree}}"
        self._tree_commits[handle] = commit_sha
        return handle

    def _commit_for_tree(self, tree: str) -> str:
        """The host commit a tree handle from :meth:`get_commit_tree_sha` stands for."""
        commit = self._tree_commits.get(tree)
        if commit is None:
            raise GitProviderError(ERROR_PROVIDER_REFUSED, f"Tree {tree[:24]!r} was not read from {self.LABEL} "
                                   "in this delivery, so it cannot be listed or built on.")
        return commit

    def list_directory(self, root_tree_sha: str, path: str, *, ref_label: str) -> Dict[str, ExistingEntry]:
        """Every entry under ``path`` (recursively) at the commit a tree handle names.

        Args:
            root_tree_sha: A handle from :meth:`get_commit_tree_sha`.
            path: The normalised directory (``''`` for the root).
            ref_label: How to name the branch in an error message.

        Returns:
            Entries keyed by repository-relative path; empty when the directory does not exist.
        """
        commit = self._commit_for_tree(root_tree_sha)
        entries = self._list_directory(commit, path, ref_label=ref_label)
        self._known_paths.setdefault(commit, set()).update(entries)
        return entries

    def create_blob(self, text: str) -> str:
        """Stage a large file's content.

        Args:
            text: The content.

        Returns:
            A local blob handle that :meth:`create_tree` resolves.
        """
        handle = f"{_STAGED_BLOB_PREFIX}{git_blob_sha(text)}"
        self._blobs[handle] = text
        return handle

    def create_tree(self, base_tree_sha: str, entries: List[Dict[str, Any]]) -> str:
        """Stage a tree: ``entries`` applied on top of a base tree.

        Args:
            base_tree_sha: A handle from :meth:`get_commit_tree_sha` (or an earlier staged tree).
            entries: ``{path, content}`` to write a file, ``{path, sha}`` to point at a staged blob,
                or ``{path, sha: None}`` to remove one.

        Returns:
            ``apiome-tree:<digest>`` — the same for the same base and the same changes.

        Raises:
            GitProviderError: When an entry names a blob that was not staged here.
        """
        staged_base = self._trees.get(base_tree_sha)
        if staged_base is not None:
            tree = _StagedTree(staged_base.base_commit, dict(staged_base.files))
        else:
            tree = _StagedTree(self._commit_for_tree(base_tree_sha))
        for entry in entries:
            path = str(entry.get("path") or "")
            if "content" in entry:
                tree.files[path] = str(entry.get("content") or "")
            elif entry.get("sha") is None:
                tree.files[path] = None
            else:
                text = self._blobs.get(str(entry["sha"]))
                if text is None:
                    raise GitProviderError(ERROR_PROVIDER_REFUSED, f"Blob {str(entry['sha'])[:24]!r} for {path} "
                                           "was not uploaded in this delivery.")
                tree.files[path] = text
        digest = json.dumps(
            {"base": base_tree_sha if staged_base is None else self._base_handle(staged_base),
             "files": sorted([path, None if text is None else git_blob_sha(text)]
                             for path, text in tree.files.items())},
            separators=(",", ":"),
        )
        handle = f"{STAGED_TREE_PREFIX}{hashlib.sha1(digest.encode('utf-8'), usedforsecurity=False).hexdigest()}"
        self._trees[handle] = tree
        return handle

    def _base_handle(self, tree: _StagedTree) -> str:
        """The tree handle a staged tree's base commit was read under."""
        return next((handle for handle, commit in self._tree_commits.items() if commit == tree.base_commit),
                    f"{tree.base_commit}^{{tree}}")

    def create_commit(self, message: str, tree_sha: str, parents: List[str]) -> str:
        """Stage a commit.

        Args:
            message: The commit message; the ``Apiome-Tree:`` trailer is added when it is written.
            tree_sha: A staged tree handle.
            parents: Exactly one parent — the commit the tree was built on.

        Returns:
            ``apiome-commit:<digest>``; the host's id is known once a branch is moved to it
            (:meth:`resolve_commit`).

        Raises:
            GitProviderError: When the tree was not staged here, or the parents do not match it.
        """
        tree = self._trees.get(tree_sha)
        if tree is None or len(parents) != 1 or parents[0] != tree.base_commit:
            raise GitProviderError(ERROR_PROVIDER_REFUSED, f"{self.LABEL} delivery writes one commit on top of the "
                                   "commit its tree was built from; this commit does not match its tree.")
        digest = hashlib.sha1(f"{tree_sha}\n{parents[0]}\n{message}".encode("utf-8"),
                              usedforsecurity=False).hexdigest()
        handle = f"{STAGED_COMMIT_PREFIX}{digest}"
        self._commits[handle] = _StagedCommit(message=message, tree=tree_sha, parent=parents[0])
        return handle

    def resolve_commit(self, commit_sha: str) -> str:
        """The host's id for a commit: a staged commit's written id, or the id itself.

        Args:
            commit_sha: A staged commit handle or a host commit id.

        Returns:
            The id the host gave the commit when a branch was moved to it.
        """
        return self._written.get(commit_sha, commit_sha)

    def _changes(self, commit: _StagedCommit) -> List[FileChange]:
        """A staged commit's file changes, in path order, each marked as a create or an update."""
        tree = self._trees[commit.tree]
        known = self._known_paths.get(tree.base_commit, set())
        return [FileChange(path=path, text=text, exists=path in known) for path, text in sorted(tree.files.items())]

    def _write(self, branch: str, commit_sha: str, mode: str) -> str:
        """Write a staged commit onto a branch and remember the host's id for it."""
        commit = self._commits.get(commit_sha)
        if commit is None:
            raise GitProviderError(ERROR_PROVIDER_REFUSED, f"{self.LABEL} delivery can only move a branch to a commit "
                                   "it wrote in this delivery.")
        written = self._write_commit(
            branch,
            message=with_tree_trailer(commit.message, commit.tree),
            parent=commit.parent,
            changes=self._changes(commit),
            mode=mode,
        )
        self._written[commit_sha] = written
        self._tree_commits[commit.tree] = written
        return written

    def create_branch(self, branch: str, commit_sha: str) -> bool:
        """Write a staged commit as a new branch.

        Args:
            branch: The branch name.
            commit_sha: A staged commit handle.

        Returns:
            ``True`` when created; ``False`` when the branch already exists (a concurrent delivery).
        """
        try:
            self._write(branch, commit_sha, WRITE_CREATE)
        except GitProviderError:
            if self.get_branch_sha(branch):
                return False
            raise
        return True

    def update_branch(self, branch: str, commit_sha: str, *, force: bool) -> None:
        """Write a staged commit onto an existing branch.

        Args:
            branch: The branch name.
            commit_sha: A staged commit handle.
            force: ``True`` replaces whatever the branch held; ``False`` only fast-forwards, refusing
                when the branch no longer points at the commit's parent.
        """
        self._write(branch, commit_sha, WRITE_FORCE if force else WRITE_FAST_FORWARD)

    def _refuse_moved_branch(self, branch: str, parent: str) -> None:
        """Refuse a fast-forward when the branch no longer points at ``parent``.

        For hosts whose commit call appends to whatever the branch holds (GitLab) rather than
        asserting its head, this check is what keeps a direct commit from landing on work the
        delivery never saw.
        """
        current = self.get_branch_sha(branch)
        if current != parent:
            raise GitProviderError(
                ERROR_PUSH_REJECTED,
                f"{branch!r} moved while the delivery ran (it was {parent[:12]}, it is now "
                f"{(current or 'gone')[:12]}), so the commit would not be a fast-forward.",
                http_status=409,
            )

    # -- what a subclass implements ------------------------------------------------------------

    def get_repository(self) -> RepositoryInfo:  # pragma: no cover - abstract
        """The repository's name, owner, default branch, and whether the token may push."""
        raise NotImplementedError

    def get_branch_sha(self, branch: str) -> Optional[str]:  # pragma: no cover - abstract
        """The commit a branch points at, or ``None`` when it does not exist."""
        raise NotImplementedError

    def get_blob_text(self, blob_sha: str) -> Optional[str]:  # pragma: no cover - abstract
        """A blob's UTF-8 text, or ``None`` when it is too large or not text."""
        raise NotImplementedError

    def find_open_pull(self, owner: str, branch: str) -> Optional[PullRequest]:  # pragma: no cover - abstract
        """The open pull request from ``branch``, if any."""
        raise NotImplementedError

    def create_pull(self, *, title: str, body: str, head: str, base: str) -> Optional[PullRequest]:  # pragma: no cover
        """Open a pull request; ``None`` when one is already open from ``head``."""
        raise NotImplementedError

    def update_pull(self, number: int, *, title: str, body: str, base: str) -> PullRequest:  # pragma: no cover
        """Update a pull request's title, description and base."""
        raise NotImplementedError

    def _read_commit_message(self, commit_sha: str) -> Optional[str]:  # pragma: no cover - abstract
        """A commit's full message (``None`` when the host truncated it)."""
        raise NotImplementedError

    def _list_directory(  # pragma: no cover - abstract
        self, commit_sha: str, path: str, *, ref_label: str
    ) -> Dict[str, ExistingEntry]:
        """Every entry under ``path`` at a commit, with git blob ids."""
        raise NotImplementedError

    def _write_commit(self, branch: str, *, message: str, parent: str, changes: List[FileChange],
                      mode: str) -> str:  # pragma: no cover - abstract
        """Write one commit of ``changes`` on top of ``parent`` onto ``branch``; returns its id.

        ``mode`` is :data:`WRITE_CREATE`, :data:`WRITE_FORCE` or :data:`WRITE_FAST_FORWARD`.
        """
        raise NotImplementedError
