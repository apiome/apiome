"""Export git delivery to GitLab — #6654.

A :class:`app.export_git_delivery_staged.StagedGitProvider` over the GitLab REST API v4 on
``gitlab.com``:

* the repository is ``GET /projects/:path`` (``project_access`` / ``group_access`` of Developer
  or above means the token's user may push);
* a directory is ``GET /projects/:id/repository/tree?recursive=true`` (blob ids are real git ids,
  so unchanged files are recognised without downloading them);
* the commit is **one** ``POST /projects/:id/repository/commits`` with ``create`` / ``update`` /
  ``delete`` actions. A delivery branch is rebuilt with ``start_sha`` + ``force: true``; a direct
  commit first confirms the branch still points at its parent (GitLab's Commits API appends to the
  branch head, so this check is what keeps it a fast-forward);
* the pull request is a **merge request** (``number`` is its project-scoped ``iid``).

The project is addressed by its full path (``group/subgroup/project``), URL-encoded, which is the
``repository_full_name`` linked-account registration stores.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

from .export_git_delivery_staged import (
    BLOB_READ_MAX_BYTES,
    KIND_PULL,
    KIND_PUSH,
    KIND_READ,
    KIND_REPOSITORY,
    WRITE_CREATE,
    WRITE_FAST_FORWARD,
    WRITE_FORCE,
    FileChange,
    StagedGitProvider,
)
from .sdk_git_delivery_changes import FILE_MODE, ExistingEntry
from .sdk_git_delivery_github import (
    ERROR_TARGET_PATH_INVALID,
    ERROR_TREE_TOO_LARGE,
    GitProviderError,
    PullRequest,
    RepositoryInfo,
)

__all__ = ["GITLAB_API_URL", "GitLabGitClient", "TREE_MAX_PAGES"]

#: The only host a GitLab delivery talks to.
GITLAB_API_URL = "https://gitlab.com/api/v4"

#: GitLab's Developer role — the lowest that may push to an unprotected branch.
_DEVELOPER_ACCESS = 30

#: Entries per tree page, and how many pages a directory listing may take (10,000 entries).
_TREE_PAGE_SIZE = 100
TREE_MAX_PAGES = 100


class GitLabGitClient(StagedGitProvider):
    """The GitLab calls an export delivery makes, against one project with one token.

    Args:
        token: The linked GitLab account's OAuth token (``api`` scope).
        full_name: The project's full path (``group/subgroup/project``).
        client_factory: How to obtain the HTTP client; injected by tests.
    """

    LABEL = "GitLab"
    WRITE_ACCESS_HINT = ("The token needs the `api` scope, and the account at least the Developer role on the "
                         "project.")
    BRANCH_RULE_WORDS = ("protected", "not allowed to push", "not allowed to force push")

    def __init__(self, token: str, full_name: str, *, client_factory: Any = None) -> None:
        super().__init__(token, full_name, client_factory=client_factory)
        self._project = f"{GITLAB_API_URL}/projects/{quote(full_name.strip('/'), safe='')}"

    # -- repository ----------------------------------------------------------------------------

    def get_repository(self) -> RepositoryInfo:
        """Read the project, confirming the token can see it.

        Returns:
            The :class:`RepositoryInfo`; ``owner`` is the namespace's full path.
        """
        payload = self._send("GET", self._project, what=f"reading {self._full_name}", kind=KIND_REPOSITORY).json() or {}
        permissions = payload.get("permissions") or {}
        levels = [int((permissions.get(key) or {}).get("access_level") or 0)
                  for key in ("project_access", "group_access")]
        namespace = (payload.get("namespace") or {}).get("full_path")
        return RepositoryInfo(
            full_name=str(payload.get("path_with_namespace") or self._full_name),
            owner=str(namespace or self._full_name.rpartition("/")[0]),
            default_branch=str(payload.get("default_branch") or "main"),
            can_push=max(levels) >= _DEVELOPER_ACCESS,
            archived=bool(payload.get("archived")),
            html_url=payload.get("web_url"),
        )

    def get_branch_sha(self, branch: str) -> Optional[str]:
        """Resolve a branch to its head commit, or ``None`` when it does not exist."""
        response = self._send("GET", f"{self._project}/repository/branches/{quote(branch, safe='')}",
                              what=f"reading branch {branch!r}", kind=KIND_READ, ok=(200, 404))
        if response.status_code == 404:
            return None
        return str(((response.json() or {}).get("commit") or {}).get("id") or "") or None

    def _read_commit_message(self, commit_sha: str) -> Optional[str]:
        response = self._send("GET", f"{self._project}/repository/commits/{quote(commit_sha, safe='')}",
                              what=f"reading commit {commit_sha[:12]}", kind=KIND_READ)
        return str((response.json() or {}).get("message") or "")

    def _list_directory(self, commit_sha: str, path: str, *, ref_label: str) -> Dict[str, ExistingEntry]:
        entries: Dict[str, ExistingEntry] = {}
        page = "1"
        for _ in range(TREE_MAX_PAGES):
            params = {"ref": commit_sha, "recursive": "true", "per_page": str(_TREE_PAGE_SIZE), "page": page}
            if path:
                params["path"] = path
            response = self._send("GET", f"{self._project}/repository/tree", what="reading the repository tree",
                                  kind=KIND_READ, ok=(200, 404), params=params)
            if response.status_code == 404:
                break
            for item in response.json() or []:
                if isinstance(item, dict) and item.get("path"):
                    entries[str(item["path"])] = ExistingEntry(path=str(item["path"]), sha=str(item.get("id") or ""),
                                                               type=str(item.get("type") or "blob"),
                                                               mode=str(item.get("mode") or FILE_MODE))
            page = str(response.headers.get("x-next-page") or "").strip()
            if not page:
                break
        else:
            raise GitProviderError(ERROR_TREE_TOO_LARGE, f"`{path or '/'}` in {self._full_name}@{ref_label} has too "
                                   "many files to list. Deliver into a dedicated directory rather than a large one.")
        if not entries and path and self._is_file(commit_sha, path):
            raise GitProviderError(ERROR_TARGET_PATH_INVALID, f"`{path}` is a file in {self._full_name}@{ref_label}, "
                                   "so the export cannot be committed under it. Point the delivery at a directory.")
        return entries

    def _is_file(self, commit_sha: str, path: str) -> bool:
        """Whether ``path`` is a file at a commit."""
        response = self._send("HEAD", f"{self._project}/repository/files/{quote(path, safe='')}",
                              what=f"reading {path}", kind=KIND_READ, ok=(200, 404), params={"ref": commit_sha})
        return response.status_code == 200

    def get_blob_text(self, blob_sha: str) -> Optional[str]:
        """Read a small text blob, or ``None`` when it is too large or not UTF-8."""
        response = self._send("GET", f"{self._project}/repository/blobs/{quote(blob_sha, safe='')}/raw",
                              what=f"reading blob {blob_sha[:12]}", kind=KIND_READ)
        if len(response.content) > BLOB_READ_MAX_BYTES:
            return None
        try:
            return response.content.decode("utf-8")
        except UnicodeDecodeError:
            return None

    # -- the write -----------------------------------------------------------------------------

    @staticmethod
    def _actions(changes: List[FileChange]) -> List[Dict[str, Any]]:
        """GitLab commit actions for a change set."""
        actions: List[Dict[str, Any]] = []
        for change in changes:
            if change.text is None:
                actions.append({"action": "delete", "file_path": change.path})
            else:
                actions.append({"action": "update" if change.exists else "create", "file_path": change.path,
                                "content": change.text, "encoding": "text"})
        return actions

    def _write_commit(self, branch: str, *, message: str, parent: str, changes: List[FileChange],
                      mode: str) -> str:
        body: Dict[str, Any] = {"branch": branch, "commit_message": message, "actions": self._actions(changes)}
        if mode == WRITE_FAST_FORWARD:
            self._refuse_moved_branch(branch, parent)
        elif mode in (WRITE_CREATE, WRITE_FORCE):
            body["start_sha"] = parent
            body["force"] = mode == WRITE_FORCE
        response = self._send("POST", f"{self._project}/repository/commits", what=f"committing to {branch!r}",
                              kind=KIND_PUSH, ok=(200, 201), json=body)
        return str((response.json() or {}).get("id") or "")

    # -- merge requests ------------------------------------------------------------------------

    @staticmethod
    def _pull(payload: Dict[str, Any]) -> PullRequest:
        """Project a merge request payload."""
        return PullRequest(number=int(payload.get("iid") or 0), url=payload.get("web_url"),
                           title=str(payload.get("title") or ""), body=str(payload.get("description") or ""),
                           base=str(payload.get("target_branch") or ""))

    def find_open_pull(self, owner: str, branch: str) -> Optional[PullRequest]:
        """The open merge request from ``branch``, if any (``owner`` is unused: a project's own branch)."""
        response = self._send("GET", f"{self._project}/merge_requests",
                              what=f"looking for an open merge request from {branch!r}", kind=KIND_READ,
                              params={"state": "opened", "source_branch": branch, "per_page": "5"})
        payload = response.json()
        return self._pull(payload[0]) if isinstance(payload, list) and payload else None

    def create_pull(self, *, title: str, body: str, head: str, base: str) -> Optional[PullRequest]:
        """Open a merge request; ``None`` when one is already open from ``head``."""
        what = f"opening a merge request from {head!r} into {base!r}"
        response = self._send("POST", f"{self._project}/merge_requests", what=what, kind=KIND_PULL,
                              ok=(201, 409), json={"source_branch": head, "target_branch": base, "title": title,
                                                   "description": body, "remove_source_branch": False})
        return self._pull(response.json() or {}) if response.status_code == 201 else None

    def update_pull(self, number: int, *, title: str, body: str, base: str) -> PullRequest:
        """Refresh a merge request's title, description and target branch."""
        response = self._send("PUT", f"{self._project}/merge_requests/{int(number)}",
                              what=f"updating merge request !{int(number)}", kind=KIND_PULL,
                              json={"title": title, "description": body, "target_branch": base})
        return self._pull(response.json() or {})
