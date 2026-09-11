"""Writing a delivery to GitHub — SDK-4.2 (#4496).

The one place a repository token leaves the process during a git delivery. Everything above this
module thinks in branches, trees and pull requests; this module turns each of those into one
GitHub REST call and turns each refusal into a :class:`GitProviderError` that says *what to do*.

**Git operations without a working copy.** A delivery never clones, and never runs ``git``. It uses
GitHub's Git Database API — create a tree on top of the base commit's tree, create a commit, move
the branch ref — which is the same set of objects a ``git push`` would transfer, written directly.
That keeps the token out of a command line, a ``.git/config`` and a credential helper, needs no
disk, and turns "the push was rejected" into a status code and a message instead of parsed
terminal output. It is the same reasoning SDK-4.1 gave for not shelling out to ``npm``/``twine``,
and the same read plumbing :class:`app.git_intake.GitHubApiClient` already uses.

**The host is fixed.** Requests only ever go to :data:`GITHUB_API_URL`, never to a URL a tenant
configured, so there is no server-side request forgery surface to guard (contrast
:mod:`app.sdk_registry_client`, whose registry URL is tenant-supplied).

**Every refusal is actionable.** GitHub answers a revoked token with 401, a token without write
scope with 403 (or 404 on a private repository), a protected branch with 422 and an exhausted rate
limit with 403/429. Each maps to a stable ``code`` naming the fix — re-link the account, widen the
token's scope, relax the branch rule, wait — and every message passes through the redactor before
it is raised, because a provider error body is outside our control.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Type
from urllib.parse import quote

import httpx

from .sdk_git_delivery_changes import FILE_MODE, ExistingEntry, join_repo_path
from .sdk_registry_credentials import redact_secrets

logger = logging.getLogger(__name__)

__all__ = [
    "ERROR_CREDENTIAL_REJECTED",
    "ERROR_PERMISSION_DENIED",
    "ERROR_PROVIDER_REFUSED",
    "ERROR_PROVIDER_UNAVAILABLE",
    "ERROR_PULL_REQUEST_REFUSED",
    "ERROR_PUSH_REJECTED",
    "ERROR_RATE_LIMITED",
    "ERROR_REPOSITORY_EMPTY",
    "ERROR_REPOSITORY_UNREACHABLE",
    "ERROR_TARGET_PATH_INVALID",
    "ERROR_TREE_TOO_LARGE",
    "GITHUB_API_URL",
    "GIT_TOKEN_REDACTION_MARKER",
    "INLINE_BLOB_MAX_BYTES",
    "REQUEST_TIMEOUT_SECONDS",
    "ClientFactory",
    "GitHubGitClient",
    "GitProviderError",
    "PullRequest",
    "RepositoryInfo",
]

#: The only host a delivery talks to.
GITHUB_API_URL = "https://api.github.com"

#: Per-request timeout. A delivery is a dozen small requests; one that hangs must not hold a
#: request thread indefinitely.
REQUEST_TIMEOUT_SECONDS = 30.0

#: Files larger than this are uploaded as separate blobs rather than inlined in the tree request,
#: so one oversized contract cannot push the tree request past GitHub's payload limits.
INLINE_BLOB_MAX_BYTES = 100_000

#: What a repository token becomes when a message would otherwise quote it.
GIT_TOKEN_REDACTION_MARKER = "[git-token-redacted]"

#: The GitHub REST API version every request pins.
_API_VERSION = "2022-11-28"

#: Identifies the caller in GitHub's audit logs.
_USER_AGENT = "apiome-sdk-git-delivery"

#: How much of a GitHub error message is kept.
_MESSAGE_MAX_CHARS = 400

#: Largest blob read back (the previous delivery manifest).
_BLOB_READ_MAX_BYTES = 1_000_000

#: Stable failure codes. The pipeline records them on the run; a caller dispatches on them.
ERROR_CREDENTIAL_REJECTED = "sdk-git-delivery-credential-rejected"
ERROR_PERMISSION_DENIED = "sdk-git-delivery-permission-denied"
ERROR_RATE_LIMITED = "sdk-git-delivery-rate-limited"
ERROR_REPOSITORY_UNREACHABLE = "sdk-git-delivery-repository-unreachable"
ERROR_REPOSITORY_EMPTY = "sdk-git-delivery-repository-empty"
ERROR_PUSH_REJECTED = "sdk-git-delivery-push-rejected"
ERROR_PULL_REQUEST_REFUSED = "sdk-git-delivery-pull-request-refused"
ERROR_PROVIDER_REFUSED = "sdk-git-delivery-provider-refused"
ERROR_PROVIDER_UNAVAILABLE = "sdk-git-delivery-provider-unavailable"
ERROR_TARGET_PATH_INVALID = "sdk-git-delivery-target-path-invalid"
ERROR_TREE_TOO_LARGE = "sdk-git-delivery-tree-too-large"

#: How an :class:`httpx.Client` is obtained. Injected so tests drive the whole protocol against an
#: in-memory repository.
ClientFactory = Callable[[], httpx.Client]

#: What kind of call failed, which decides what a 404 or a 422 means.
_KIND_REPOSITORY = "repository"
_KIND_READ = "read"
_KIND_WRITE = "write"
_KIND_PUSH = "push"
_KIND_PULL = "pull"


class GitProviderError(RuntimeError):
    """A GitHub call that failed, with the reason a person can act on.

    Attributes:
        code: A stable, machine-readable reason (one of the ``ERROR_*`` constants).
        message: What happened and what to do about it. Already redacted.
        http_status: GitHub's status code, when there was a response.
        retryable: Whether trying again unchanged could plausibly succeed.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: Optional[int] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable


@dataclass(frozen=True)
class RepositoryInfo:
    """What GitHub says about the repository.

    Attributes:
        full_name: ``owner/repo`` as GitHub currently spells it (after any rename).
        owner: The owner's login — a pull request's ``head`` is qualified with it.
        default_branch: The repository's default branch.
        can_push: Whether the token's user may push.
        archived: Whether the repository is read-only.
        html_url: The repository's web page.
    """

    full_name: str
    owner: str
    default_branch: str
    can_push: bool
    archived: bool
    html_url: Optional[str] = None


@dataclass(frozen=True)
class PullRequest:
    """An open pull request.

    Attributes:
        number: Its number.
        url: Its web page.
        title: Its current title.
        body: Its current description.
        base: The branch it targets.
    """

    number: int
    url: Optional[str]
    title: str
    body: str
    base: str


def _default_client_factory() -> httpx.Client:
    """Build the client every delivery request goes through.

    Returns:
        A client with a bounded timeout that follows GitHub's own redirects (a renamed repository
        answers with one).
    """
    return httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True)


def _github_message(response: httpx.Response) -> str:
    """Extract GitHub's own explanation from an error response.

    Args:
        response: The failed response.

    Returns:
        ``message`` plus the first entry of ``errors`` when present, bounded in length.
    """
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        parts = [str(payload.get("message") or "").strip()]
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            detail = first.get("message") if isinstance(first, dict) else first
            if detail:
                parts.append(str(detail).strip())
        text = ": ".join(part for part in parts if part)
    else:
        text = (response.text or "").strip()
    text = " ".join(text.split())
    return text[:_MESSAGE_MAX_CHARS] or "no detail"


class GitHubGitClient:
    """The GitHub calls a delivery makes, against one repository with one token.

    Use as a context manager so the underlying connection pool is closed::

        with GitHubGitClient(token, "acme/widgets-sdk") as github:
            info = github.get_repository()

    Args:
        token: The repository's linked-account token. Held for the life of the client and used
            only in the ``Authorization`` header.
        full_name: ``owner/repo``.
        client_factory: How to obtain the HTTP client; defaults to a plain client with a bounded
            timeout.
    """

    def __init__(
        self, token: str, full_name: str, *, client_factory: Optional[ClientFactory] = None
    ) -> None:
        owner, _, name = full_name.partition("/")
        self._token = token
        self._full_name = full_name
        self._repo_path = f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"
        self._factory = client_factory or _default_client_factory
        self._client: Optional[httpx.Client] = None

    # -- lifecycle -----------------------------------------------------------------------------

    def __enter__(self) -> "GitHubGitClient":
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

    def _request(
        self,
        method: str,
        path: str,
        *,
        what: str,
        kind: str,
        ok: Iterable[int] = (200,),
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> httpx.Response:
        """Send one request and return the response when its status is expected.

        Args:
            method: HTTP method.
            path: Path under the repository (``/git/trees``), or an absolute API path starting with
                ``/repos/``.
            what: What the call does, phrased to complete "while …" in an error message.
            kind: Which ``_KIND_*`` the call is, deciding what a 404 or 422 means.
            ok: The statuses that are not errors (a caller that treats 404 as "absent" passes it).
            json: Request body.
            params: Query parameters.

        Returns:
            The response.

        Raises:
            GitProviderError: For a network failure or any status outside ``ok``.
            RuntimeError: When used outside ``with``.
        """
        if self._client is None:
            raise RuntimeError("GitHubGitClient must be used as a context manager")
        url = f"{GITHUB_API_URL}{path if path.startswith('/repos/') else self._repo_path + path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": _API_VERSION,
            "User-Agent": _USER_AGENT,
        }
        try:
            response = self._client.request(method, url, headers=headers, json=json, params=params)
        except httpx.TimeoutException as exc:
            raise GitProviderError(
                ERROR_PROVIDER_UNAVAILABLE,
                f"GitHub did not answer within {REQUEST_TIMEOUT_SECONDS:.0f}s while {what}. Try the "
                "delivery again.",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise GitProviderError(
                ERROR_PROVIDER_UNAVAILABLE,
                self._redact(f"GitHub could not be reached while {what}: {exc}"),
                retryable=True,
            ) from exc
        if response.status_code in set(ok):
            return response
        raise self._error(response, what=what, kind=kind)

    def _error(self, response: httpx.Response, *, what: str, kind: str) -> GitProviderError:
        """Translate a refusal into an actionable :class:`GitProviderError`.

        Args:
            response: GitHub's answer.
            what: What the call was doing.
            kind: Which ``_KIND_*`` the call is.

        Returns:
            The error to raise, redacted.
        """
        status = response.status_code
        detail = _github_message(response)
        repo = self._full_name

        def fail(code: str, message: str, retryable: bool = False) -> GitProviderError:
            return GitProviderError(
                code, self._redact(message), http_status=status, retryable=retryable
            )

        rate_limited = response.headers.get("x-ratelimit-remaining") == "0" or (
            status in (403, 429) and "rate limit" in detail.lower()
        )
        if status == 429 or (status == 403 and rate_limited):
            reset = response.headers.get("x-ratelimit-reset")
            when = f" (the limit resets at Unix time {reset})" if reset else ""
            return fail(
                ERROR_RATE_LIMITED,
                f"GitHub's API rate limit for the linked account was exhausted while {what}{when}. "
                "Deliver again once it resets.",
                retryable=True,
            )
        if status == 401:
            return fail(
                ERROR_CREDENTIAL_REJECTED,
                f"GitHub rejected the linked account's token while {what} (HTTP 401: {detail}). "
                f"The token has expired or been revoked — re-link the GitHub account that "
                f"registered {repo}, then deliver again.",
            )
        if status == 404 and kind == _KIND_REPOSITORY:
            return fail(
                ERROR_REPOSITORY_UNREACHABLE,
                f"{repo} was not found with the linked account's token (HTTP 404). The repository "
                "was renamed or deleted, or that account can no longer see it — check the "
                "repository, or re-register it through an account with access.",
            )
        if status == 403 or (status == 404 and kind in (_KIND_WRITE, _KIND_PUSH, _KIND_PULL)):
            return fail(
                ERROR_PERMISSION_DENIED,
                f"The linked account's token is not allowed to write to {repo} while {what} "
                f"(HTTP {status}: {detail}). A classic token needs the `repo` scope; a fine-grained "
                "token needs read and write access to Contents and Pull requests on this "
                "repository. Update the token on the linked account, then deliver again.",
            )
        if status == 409 and "empty" in detail.lower():
            return fail(
                ERROR_REPOSITORY_EMPTY,
                f"{repo} has no commits yet (HTTP 409: {detail}). Push an initial commit to its "
                "base branch, then deliver again.",
            )
        if kind == _KIND_PUSH and status in (409, 422):
            return fail(
                ERROR_PUSH_REJECTED,
                f"GitHub rejected the push while {what} (HTTP {status}: {detail}). A branch "
                "protection rule or ruleset may forbid creating or force-pushing Apiome's "
                "`apiome/sdk-regen-*` branches — allow it for the linked account, or delete the "
                "branch, then deliver again.",
            )
        if kind == _KIND_PULL and status in (403, 409, 422):
            return fail(
                ERROR_PULL_REQUEST_REFUSED,
                f"GitHub refused the pull request while {what} (HTTP {status}: {detail}). The "
                "commit was pushed; open the pull request by hand, or fix the cause and deliver "
                "again.",
            )
        if status >= 500:
            return fail(
                ERROR_PROVIDER_UNAVAILABLE,
                f"GitHub failed while {what} (HTTP {status}: {detail}). Try the delivery again.",
                retryable=True,
            )
        return fail(
            ERROR_PROVIDER_REFUSED,
            f"GitHub refused the request while {what} (HTTP {status}: {detail}).",
        )

    # -- repository ----------------------------------------------------------------------------

    def get_repository(self) -> RepositoryInfo:
        """Read the repository, confirming the token can see it.

        Returns:
            The :class:`RepositoryInfo`.

        Raises:
            GitProviderError: When the token is rejected or cannot see the repository.
        """
        response = self._request(
            "GET", "", what=f"reading {self._full_name}", kind=_KIND_REPOSITORY
        )
        payload = response.json() or {}
        permissions = payload.get("permissions") or {}
        owner = (payload.get("owner") or {}).get("login") or self._full_name.partition("/")[0]
        return RepositoryInfo(
            full_name=str(payload.get("full_name") or self._full_name),
            owner=str(owner),
            default_branch=str(payload.get("default_branch") or "main"),
            can_push=bool(permissions.get("push") or permissions.get("admin")),
            archived=bool(payload.get("archived")),
            html_url=payload.get("html_url"),
        )

    # -- refs, commits and trees ---------------------------------------------------------------

    def get_branch_sha(self, branch: str) -> Optional[str]:
        """Resolve a branch to its head commit.

        Args:
            branch: The branch name.

        Returns:
            The commit sha, or ``None`` when the branch does not exist.
        """
        response = self._request(
            "GET",
            f"/git/ref/heads/{quote(branch, safe='/')}",
            what=f"reading branch {branch!r}",
            kind=_KIND_READ,
            ok=(200, 404),
        )
        if response.status_code == 404:
            return None
        payload = response.json()
        if isinstance(payload, list):
            # A prefix match rather than the exact ref: the exact branch does not exist.
            return None
        return str(((payload or {}).get("object") or {}).get("sha") or "") or None

    def get_commit_tree_sha(self, commit_sha: str) -> str:
        """Read the tree a commit points at.

        Args:
            commit_sha: The commit.

        Returns:
            Its tree's sha.
        """
        response = self._request(
            "GET", f"/git/commits/{commit_sha}", what=f"reading commit {commit_sha[:12]}", kind=_KIND_READ
        )
        return str(((response.json() or {}).get("tree") or {}).get("sha") or "")

    def _list_tree(self, tree_sha: str, *, recursive: bool) -> Tuple[List[Dict[str, Any]], bool]:
        """List one tree.

        Args:
            tree_sha: The tree.
            recursive: Whether to list every descendant.

        Returns:
            ``(entries, truncated)``.
        """
        response = self._request(
            "GET",
            f"/git/trees/{tree_sha}",
            what="reading the repository tree",
            kind=_KIND_READ,
            params={"recursive": "1"} if recursive else None,
        )
        payload = response.json() or {}
        entries = [entry for entry in payload.get("tree") or [] if isinstance(entry, dict)]
        return entries, bool(payload.get("truncated"))

    def list_directory(self, root_tree_sha: str, path: str, *, ref_label: str) -> Dict[str, ExistingEntry]:
        """List everything under a directory of a commit's tree.

        Walks to the directory one level at a time (so a large monorepo is never listed whole),
        then lists that directory recursively.

        Args:
            root_tree_sha: The commit's root tree.
            path: The normalised directory (``''`` for the root).
            ref_label: How to name the branch in an error message.

        Returns:
            Every entry under the directory, keyed by repository-relative path. Empty when the
            directory does not exist yet.

        Raises:
            GitProviderError: When part of the path is a file (``ERROR_TARGET_PATH_INVALID``) or
                the directory is too large for GitHub to list in one response
                (``ERROR_TREE_TOO_LARGE``).
        """
        current = root_tree_sha
        walked: List[str] = []
        for segment in [part for part in path.split("/") if part]:
            entries, truncated = self._list_tree(current, recursive=False)
            match = next((entry for entry in entries if entry.get("path") == segment), None)
            walked.append(segment)
            if match is None:
                if truncated:
                    raise GitProviderError(
                        ERROR_TREE_TOO_LARGE,
                        f"`{'/'.join(walked[:-1]) or '/'}` in {self._full_name}@{ref_label} has too "
                        "many entries for GitHub to list. Deliver into a smaller directory.",
                    )
                return {}
            if match.get("type") != "tree":
                raise GitProviderError(
                    ERROR_TARGET_PATH_INVALID,
                    f"`{'/'.join(walked)}` is a file in {self._full_name}@{ref_label}, so the SDK "
                    "cannot be committed under it. Point the delivery target at a directory.",
                )
            current = str(match.get("sha") or "")

        entries, truncated = self._list_tree(current, recursive=True)
        if truncated:
            raise GitProviderError(
                ERROR_TREE_TOO_LARGE,
                f"`{path or '/'}` in {self._full_name}@{ref_label} has too many files for GitHub to "
                "list in one response. Deliver into a dedicated directory rather than a large one.",
            )
        return {
            join_repo_path(path, str(entry.get("path") or "")): ExistingEntry(
                path=join_repo_path(path, str(entry.get("path") or "")),
                sha=str(entry.get("sha") or ""),
                type=str(entry.get("type") or "blob"),
                mode=str(entry.get("mode") or FILE_MODE),
            )
            for entry in entries
            if entry.get("path")
        }

    def get_blob_text(self, blob_sha: str) -> Optional[str]:
        """Read a small text blob.

        Args:
            blob_sha: The blob.

        Returns:
            Its UTF-8 text, or ``None`` when it is too large or not valid UTF-8.
        """
        response = self._request(
            "GET", f"/git/blobs/{blob_sha}", what="reading the previous delivery manifest", kind=_KIND_READ
        )
        payload = response.json() or {}
        if int(payload.get("size") or 0) > _BLOB_READ_MAX_BYTES:
            return None
        try:
            raw = base64.b64decode(str(payload.get("content") or ""), validate=False)
            return raw.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None

    def create_blob(self, text: str) -> str:
        """Upload one file's content.

        Args:
            text: The content.

        Returns:
            The blob's sha.
        """
        response = self._request(
            "POST",
            "/git/blobs",
            what="uploading a file",
            kind=_KIND_WRITE,
            ok=(201,),
            json={"content": text, "encoding": "utf-8"},
        )
        return str((response.json() or {}).get("sha") or "")

    def create_tree(self, base_tree_sha: str, entries: List[Dict[str, Any]]) -> str:
        """Create a tree that applies ``entries`` on top of a base tree.

        Args:
            base_tree_sha: The base commit's tree; everything not named in ``entries`` is kept.
            entries: ``{path, mode, type, content}`` to write a file, ``{…, sha}`` to point at an
                uploaded blob, or ``{…, sha: None}`` to delete one.

        Returns:
            The new tree's sha.
        """
        response = self._request(
            "POST",
            "/git/trees",
            what="writing the SDK tree",
            kind=_KIND_WRITE,
            ok=(201,),
            json={"base_tree": base_tree_sha, "tree": entries},
        )
        return str((response.json() or {}).get("sha") or "")

    def create_commit(self, message: str, tree_sha: str, parents: List[str]) -> str:
        """Create a commit.

        Args:
            message: The commit message.
            tree_sha: Its tree.
            parents: Its parent commits.

        Returns:
            The commit's sha.
        """
        response = self._request(
            "POST",
            "/git/commits",
            what="creating the SDK commit",
            kind=_KIND_WRITE,
            ok=(201,),
            json={"message": message, "tree": tree_sha, "parents": parents},
        )
        return str((response.json() or {}).get("sha") or "")

    def create_branch(self, branch: str, commit_sha: str) -> bool:
        """Create a branch at a commit.

        Args:
            branch: The branch name.
            commit_sha: Where it points.

        Returns:
            ``True`` when created; ``False`` when it already exists (another delivery created it
            between this one's read and write).

        Raises:
            GitProviderError: When the push is rejected for any other reason.
        """
        response = self._request(
            "POST",
            "/git/refs",
            what=f"creating branch {branch!r}",
            kind=_KIND_PUSH,
            ok=(201, 422),
            json={"ref": f"refs/heads/{branch}", "sha": commit_sha},
        )
        if response.status_code == 201:
            return True
        if "already exists" in _github_message(response).lower():
            return False
        raise self._error(response, what=f"creating branch {branch!r}", kind=_KIND_PUSH)

    def update_branch(self, branch: str, commit_sha: str, *, force: bool) -> None:
        """Move a branch to a commit.

        Args:
            branch: The branch name.
            commit_sha: Where it should point.
            force: Whether the move may discard commits (a delivery branch is rebuilt on the latest
                base, so this is normally ``True``).

        Raises:
            GitProviderError: ``ERROR_PUSH_REJECTED`` when a branch rule refuses the update.
        """
        self._request(
            "PATCH",
            f"/git/refs/heads/{quote(branch, safe='/')}",
            what=f"updating branch {branch!r}",
            kind=_KIND_PUSH,
            json={"sha": commit_sha, "force": force},
        )

    # -- pull requests -------------------------------------------------------------------------

    @staticmethod
    def _pull(payload: Dict[str, Any]) -> PullRequest:
        """Project a pull request payload."""
        return PullRequest(
            number=int(payload.get("number") or 0),
            url=payload.get("html_url"),
            title=str(payload.get("title") or ""),
            body=str(payload.get("body") or ""),
            base=str((payload.get("base") or {}).get("ref") or ""),
        )

    def find_open_pull(self, owner: str, branch: str) -> Optional[PullRequest]:
        """Find the open pull request whose head is a branch of this repository.

        Args:
            owner: The repository owner's login.
            branch: The head branch.

        Returns:
            The pull request, or ``None`` when none is open.
        """
        response = self._request(
            "GET",
            "/pulls",
            what=f"looking for an open pull request from {branch!r}",
            kind=_KIND_READ,
            params={"state": "open", "head": f"{owner}:{branch}", "per_page": "5"},
        )
        payload = response.json()
        if not isinstance(payload, list) or not payload:
            return None
        return self._pull(payload[0])

    def create_pull(self, *, title: str, body: str, head: str, base: str) -> Optional[PullRequest]:
        """Open a pull request.

        Args:
            title: Its title.
            body: Its description.
            head: The delivery branch.
            base: The branch to merge into.

        Returns:
            The pull request, or ``None`` when one is already open for ``head`` (another delivery
            opened it concurrently).

        Raises:
            GitProviderError: ``ERROR_PULL_REQUEST_REFUSED`` for any other refusal.
        """
        response = self._request(
            "POST",
            "/pulls",
            what=f"opening a pull request from {head!r} into {base!r}",
            kind=_KIND_PULL,
            ok=(201, 422),
            json={"title": title, "body": body, "head": head, "base": base},
        )
        if response.status_code == 201:
            return self._pull(response.json() or {})
        if "already exists" in _github_message(response).lower():
            return None
        raise self._error(
            response, what=f"opening a pull request from {head!r} into {base!r}", kind=_KIND_PULL
        )

    def update_pull(self, number: int, *, title: str, body: str, base: str) -> PullRequest:
        """Refresh an open pull request's title, description and base.

        Args:
            number: The pull request.
            title: Its new title.
            body: Its new description.
            base: The branch it should target.

        Returns:
            The updated pull request.
        """
        response = self._request(
            "PATCH",
            f"/pulls/{int(number)}",
            what=f"updating pull request #{int(number)}",
            kind=_KIND_PULL,
            json={"title": title, "body": body, "base": base},
        )
        return self._pull(response.json() or {})
