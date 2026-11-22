"""Export git delivery to Bitbucket Cloud — #6654.

A :class:`app.export_git_delivery_staged.StagedGitProvider` over the Bitbucket Cloud REST API 2.0
(``api.bitbucket.org``):

* the repository is ``GET /repositories/{workspace}/{repo}``, and whether the token may push is
  ``GET /user/permissions/repositories`` (``write`` or ``admin``);
* a directory is ``GET /repositories/…/src/{commit}/{path}/?max_depth=…``. Bitbucket lists no blob
  ids, so each file under the target directory is read once and its git blob id computed locally
  (:func:`app.export_git_delivery_staged.bytes_blob_sha`); the text is kept, so reading the previous
  delivery manifest costs nothing more. A directory is capped at :data:`LIST_MAX_FILES` files;
* the commit is **one** ``POST /repositories/…/src`` form with ``parents`` — Bitbucket then refuses
  (409) unless the branch still points at that parent, which makes a direct commit a true
  fast-forward. Bitbucket cannot force-move a branch, so a delivery branch is rebuilt by deleting it
  and writing it again from the base;
* the pull request is ``/pullrequests``. Should Bitbucket decline the open pull request when its
  branch is rebuilt, :meth:`BitbucketGitClient.update_pull` opens a new one rather than update a
  declined one.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

from .export_git_delivery_staged import (
    KIND_PULL,
    KIND_PUSH,
    KIND_READ,
    KIND_REPOSITORY,
    WRITE_FORCE,
    FileChange,
    StagedGitProvider,
    bytes_blob_sha,
)
from .sdk_git_delivery_changes import FILE_MODE, ExistingEntry
from .sdk_git_delivery_github import (
    ERROR_TARGET_PATH_INVALID,
    ERROR_TREE_TOO_LARGE,
    GitProviderError,
    PullRequest,
    RepositoryInfo,
)

__all__ = ["BITBUCKET_API_URL", "BitbucketGitClient", "LIST_MAX_FILES"]

#: The only host a Bitbucket delivery talks to.
BITBUCKET_API_URL = "https://api.bitbucket.org/2.0"

#: How many files a target directory may hold: each is read to learn its blob id.
LIST_MAX_FILES = 1_000

#: How deep a directory listing descends, and how many pages it follows.
_LIST_MAX_DEPTH = 32
_LIST_MAX_PAGES = 100

#: Bitbucket's permission names that allow a push.
_WRITE_PERMISSIONS = ("write", "admin")


class BitbucketGitClient(StagedGitProvider):
    """The Bitbucket Cloud calls an export delivery makes, against one repository with one token.

    Args:
        token: The linked Bitbucket account's OAuth token (``repository:write`` and
            ``pullrequest:write`` scopes).
        full_name: ``workspace/repo``.
        client_factory: How to obtain the HTTP client; injected by tests.
    """

    LABEL = "Bitbucket"
    WRITE_ACCESS_HINT = ("The OAuth consumer needs the Repositories: Write and Pull requests: Write permissions, and "
                         "the account write access to the repository.")
    BRANCH_RULE_WORDS = ("restriction", "not allowed", "merge checks")

    def __init__(self, token: str, full_name: str, *, client_factory: Any = None) -> None:
        super().__init__(token, full_name, client_factory=client_factory)
        workspace, _, repo = full_name.strip("/").partition("/")
        self._repo = f"{BITBUCKET_API_URL}/repositories/{quote(workspace, safe='')}/{quote(repo, safe='')}"
        #: Text of every file listed, by git blob id — what get_blob_text answers from.
        self._texts: Dict[str, str] = {}

    # -- repository ----------------------------------------------------------------------------

    def get_repository(self) -> RepositoryInfo:
        """Read the repository, and whether the token's user may push to it.

        Returns:
            The :class:`RepositoryInfo`. Bitbucket has no archived state.
        """
        payload = self._send("GET", self._repo, what=f"reading {self._full_name}", kind=KIND_REPOSITORY).json() or {}
        full_name = str(payload.get("full_name") or self._full_name)
        return RepositoryInfo(
            full_name=full_name,
            owner=str((payload.get("workspace") or {}).get("slug") or full_name.partition("/")[0]),
            default_branch=str((payload.get("mainbranch") or {}).get("name") or "main"),
            can_push=self._can_push(full_name),
            archived=False,
            html_url=((payload.get("links") or {}).get("html") or {}).get("href"),
        )

    def _can_push(self, full_name: str) -> bool:
        """Whether the token's user holds write access; ``True`` when Bitbucket will not say.

        A token without the ``account`` scope cannot read its own permissions. The push itself is
        then the check, and its refusal is reported as permission denied.
        """
        response = self._send("GET", f"{BITBUCKET_API_URL}/user/permissions/repositories",
                              what="reading the account's repository permission", kind=KIND_READ,
                              ok=(200, 401, 403), params={"q": f'repository.full_name="{full_name}"'})
        if response.status_code != 200:
            return True
        values = (response.json() or {}).get("values") or []
        if not values:
            return True
        return str((values[0] or {}).get("permission") or "").lower() in _WRITE_PERMISSIONS

    def get_branch_sha(self, branch: str) -> Optional[str]:
        """Resolve a branch to its head commit, or ``None`` when it does not exist."""
        response = self._send("GET", f"{self._repo}/refs/branches/{quote(branch, safe='/')}",
                              what=f"reading branch {branch!r}", kind=KIND_READ, ok=(200, 404))
        if response.status_code == 404:
            return None
        return str(((response.json() or {}).get("target") or {}).get("hash") or "") or None

    def _read_commit_message(self, commit_sha: str) -> Optional[str]:
        response = self._send("GET", f"{self._repo}/commit/{quote(commit_sha, safe='')}",
                              what=f"reading commit {commit_sha[:12]}", kind=KIND_READ)
        return str((response.json() or {}).get("message") or "")

    def _list_directory(self, commit_sha: str, path: str, *, ref_label: str) -> Dict[str, ExistingEntry]:
        url: Optional[str] = f"{self._repo}/src/{quote(commit_sha, safe='')}/{quote(path, safe='/')}"
        url = url.rstrip("/") + "/"
        params: Optional[Dict[str, str]] = {"max_depth": str(_LIST_MAX_DEPTH), "pagelen": "100"}
        files: List[str] = []
        entries: Dict[str, ExistingEntry] = {}
        for _ in range(_LIST_MAX_PAGES):
            if url is None:
                break
            response = self._send("GET", url, what="reading the repository tree", kind=KIND_READ, ok=(200, 404),
                                  params=params)
            if response.status_code == 404:
                return {}
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if not isinstance(payload, dict) or not isinstance(payload.get("values"), list):
                raise GitProviderError(ERROR_TARGET_PATH_INVALID, f"`{path}` is a file in "
                                       f"{self._full_name}@{ref_label}, so the export cannot be committed under it. "
                                       "Point the delivery at a directory.")
            for item in payload["values"]:
                item_path = str((item or {}).get("path") or "")
                if not item_path:
                    continue
                if item.get("type") == "commit_directory":
                    entries[item_path] = ExistingEntry(path=item_path, sha="", type="tree", mode="040000")
                elif "subrepository" in (item.get("attributes") or []):
                    entries[item_path] = ExistingEntry(path=item_path, sha="", type="commit", mode="160000")
                else:
                    files.append(item_path)
            next_url = payload.get("next")
            # Only follow pages Bitbucket itself links to, on its own API host.
            url = str(next_url) if isinstance(next_url, str) and next_url.startswith(BITBUCKET_API_URL + "/") else None
            params = None
        else:
            raise self._too_large(path, ref_label)
        if len(files) > LIST_MAX_FILES:
            raise self._too_large(path, ref_label)
        for file_path in files:
            entries[file_path] = self._read_file_entry(commit_sha, file_path)
        return entries

    def _too_large(self, path: str, ref_label: str) -> GitProviderError:
        return GitProviderError(ERROR_TREE_TOO_LARGE, f"`{path or '/'}` in {self._full_name}@{ref_label} holds more "
                                f"than {LIST_MAX_FILES:,} files. Deliver into a dedicated directory rather than a "
                                "large one.")

    def _read_file_entry(self, commit_sha: str, path: str) -> ExistingEntry:
        """Read one file to learn its git blob id, keeping its text for :meth:`get_blob_text`."""
        response = self._send("GET", f"{self._repo}/src/{quote(commit_sha, safe='')}/{quote(path, safe='/')}",
                              what=f"reading {path}", kind=KIND_READ)
        sha = bytes_blob_sha(response.content)
        try:
            self._texts[sha] = response.content.decode("utf-8")
        except UnicodeDecodeError:
            pass
        return ExistingEntry(path=path, sha=sha, type="blob", mode=FILE_MODE)

    def get_blob_text(self, blob_sha: str) -> Optional[str]:
        """A listed file's UTF-8 text, or ``None`` when it was not text (or not listed)."""
        return self._texts.get(blob_sha)

    # -- the write -----------------------------------------------------------------------------

    def _write_commit(self, branch: str, *, message: str, parent: str, changes: List[FileChange],
                      mode: str) -> str:
        if mode == WRITE_FORCE and self.get_branch_sha(branch):
            self._send("DELETE", f"{self._repo}/refs/branches/{quote(branch, safe='/')}",
                       what=f"rebuilding branch {branch!r}", kind=KIND_PUSH, ok=(204,))
        # A leading slash keeps a file named like a form field (`message`, `branch`) a file.
        form: Dict[str, Any] = {"message": message, "branch": branch, "parents": parent}
        form.update({f"/{change.path}": change.text for change in changes if change.text is not None})
        removed = [change.path for change in changes if change.text is None]
        if removed:
            form["files"] = removed
        response = self._send("POST", f"{self._repo}/src", what=f"committing to {branch!r}", kind=KIND_PUSH,
                              ok=(200, 201), data=form)
        location = str(response.headers.get("location") or "")
        written = location.rstrip("/").rpartition("/commit/")[2] if "/commit/" in location else ""
        return written or self.get_branch_sha(branch) or ""

    # -- pull requests -------------------------------------------------------------------------

    @staticmethod
    def _pull(payload: Dict[str, Any]) -> PullRequest:
        """Project a pull request payload."""
        return PullRequest(number=int(payload.get("id") or 0),
                           url=((payload.get("links") or {}).get("html") or {}).get("href"),
                           title=str(payload.get("title") or ""), body=str(payload.get("description") or ""),
                           base=str(((payload.get("destination") or {}).get("branch") or {}).get("name") or ""))

    def find_open_pull(self, owner: str, branch: str) -> Optional[PullRequest]:
        """The open pull request from ``branch``, if any (``owner`` is unused: a repository's own branch)."""
        response = self._send("GET", f"{self._repo}/pullrequests",
                              what=f"looking for an open pull request from {branch!r}", kind=KIND_READ,
                              params={"state": "OPEN", "q": f'source.branch.name="{branch}"', "pagelen": "5"})
        values = (response.json() or {}).get("values") or []
        return self._pull(values[0]) if values else None

    def create_pull(self, *, title: str, body: str, head: str, base: str) -> Optional[PullRequest]:
        """Open a pull request; ``None`` when one is already open from ``head``."""
        what = f"opening a pull request from {head!r} into {base!r}"
        response = self._send("POST", f"{self._repo}/pullrequests", what=what, kind=KIND_PULL, ok=(200, 201, 400, 409),
                              json={"title": title, "description": body, "source": {"branch": {"name": head}},
                                    "destination": {"branch": {"name": base}}, "close_source_branch": False})
        if response.status_code in (200, 201):
            return self._pull(response.json() or {})
        if "already" in str(response.text or "").lower():
            return None
        raise self._error(response, what=what, kind=KIND_PULL)

    def update_pull(self, number: int, *, title: str, body: str, base: str) -> PullRequest:
        """Refresh a pull request — or open a new one when rebuilding its branch declined it."""
        url = f"{self._repo}/pullrequests/{int(number)}"
        current = self._send("GET", url, what=f"reading pull request #{int(number)}", kind=KIND_PULL).json() or {}
        if str(current.get("state") or "OPEN").upper() != "OPEN":
            head = str(((current.get("source") or {}).get("branch") or {}).get("name") or "")
            opened = self.create_pull(title=title, body=body, head=head, base=base)
            reopened = opened or self.find_open_pull("", head)
            if reopened is not None:
                return reopened
        response = self._send("PUT", url, what=f"updating pull request #{int(number)}", kind=KIND_PULL,
                              json={"title": title, "description": body, "destination": {"branch": {"name": base}}})
        return self._pull(response.json() or {})
