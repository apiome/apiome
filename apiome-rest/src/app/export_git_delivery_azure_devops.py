"""Export git delivery to Azure DevOps Repos — #6654.

A :class:`app.export_git_delivery_staged.StagedGitProvider` over the Azure DevOps Git REST API
(``dev.azure.com``, ``api-version=7.1``):

* the repository is ``GET /{org}/{project}/_apis/git/repositories/{repo}`` (a disabled repository
  reads as archived). Azure DevOps reports no per-user push permission here, so the push itself is
  the check and its refusal is reported as permission denied;
* a directory is ``GET …/items?scopePath=…&recursionLevel=Full`` at the commit, with real git object
  ids;
* the commit is **one** ``POST …/pushes``. Its ``refUpdates[].oldObjectId`` is a compare-and-swap:
  a direct commit names the base commit, so Azure DevOps refuses it if the branch moved — a true
  fast-forward. A new branch is created from its base the same way. A delivery branch is rebuilt by
  pushing the commit to a scratch branch and then moving the delivery branch to it with
  ``POST …/refs`` (which allows a non-fast-forward move when the account may force-push), deleting
  the scratch branch in the same call;
* the pull request is ``…/pullrequests``. Azure DevOps keeps at most
  :data:`DESCRIPTION_MAX_CHARS` characters of a description, so a longer one is shortened.

The repository's registered name is ``organization/project/repository``.
"""

from __future__ import annotations

import secrets
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from .export_git_delivery_staged import (
    BLOB_READ_MAX_BYTES,
    KIND_PULL,
    KIND_PUSH,
    KIND_READ,
    KIND_REPOSITORY,
    WRITE_FORCE,
    FileChange,
    StagedGitProvider,
)
from .sdk_git_delivery_changes import FILE_MODE, ExistingEntry
from .sdk_git_delivery_github import (
    ERROR_PUSH_REJECTED,
    ERROR_TARGET_PATH_INVALID,
    GitProviderError,
    PullRequest,
    RepositoryInfo,
)

__all__ = [
    "AZURE_DEVOPS_API_URL",
    "AZURE_DEVOPS_API_VERSION",
    "DESCRIPTION_MAX_CHARS",
    "SCRATCH_BRANCH_PREFIX",
    "AzureDevOpsGitClient",
    "split_azure_devops_name",
]

#: The only host an Azure DevOps delivery talks to.
AZURE_DEVOPS_API_URL = "https://dev.azure.com"

#: The REST API version every request pins.
AZURE_DEVOPS_API_VERSION = "7.1"

#: The longest pull request description Azure DevOps accepts.
DESCRIPTION_MAX_CHARS = 4_000

#: Where a rebuilt delivery branch's commit is pushed before the branch is moved to it.
SCRATCH_BRANCH_PREFIX = "apiome/scratch-"

#: The all-zero object id: "no ref" in a ref update.
_ZERO_ID = "0" * 40

_HEADS = "refs/heads/"


def split_azure_devops_name(full_name: str) -> tuple[str, str, str]:
    """Split ``organization/project/repository``.

    Args:
        full_name: The registered name.

    Returns:
        ``(organization, project, repository)``.

    Raises:
        ValueError: When the name does not have exactly three non-empty parts.
    """
    parts = [part for part in (full_name or "").strip().strip("/").split("/")]
    if len(parts) != 3 or not all(part.strip() for part in parts):
        raise ValueError(f"{full_name!r} is not an Azure DevOps organization/project/repository name")
    return parts[0], parts[1], parts[2]


def _branch(ref: Optional[str]) -> str:
    """``refs/heads/main`` → ``main``."""
    text = str(ref or "")
    return text[len(_HEADS):] if text.startswith(_HEADS) else text


class AzureDevOpsGitClient(StagedGitProvider):
    """The Azure DevOps calls an export delivery makes, against one repository with one token.

    Args:
        token: The linked Microsoft account's token, issued for Azure DevOps (``vso.code_write``).
        full_name: ``organization/project/repository``.
        client_factory: How to obtain the HTTP client; injected by tests.

    Raises:
        ValueError: When ``full_name`` is not ``organization/project/repository``.
    """

    LABEL = "Azure DevOps"
    WRITE_ACCESS_HINT = ("The token must be issued for Azure DevOps with the Code (read and write) scope "
                         "(`vso.code_write`), and the account needs Contribute, Create branch and Contribute to pull "
                         "requests on the repository.")
    BRANCH_RULE_WORDS = ("tf402455", "policy", "forcepush", "force push", "tf401027")

    def __init__(self, token: str, full_name: str, *, client_factory: Any = None) -> None:
        super().__init__(token, full_name, client_factory=client_factory)
        self._org, self._project_name, self._repo_name = split_azure_devops_name(full_name)
        self._project = f"{AZURE_DEVOPS_API_URL}/{quote(self._org, safe='')}/{quote(self._project_name, safe='')}"
        self._repo = f"{self._project}/_apis/git/repositories/{quote(self._repo_name, safe='')}"

    # -- transport -----------------------------------------------------------------------------

    def _call(self, method: str, url: str, *, params: Optional[Dict[str, Any]] = None, **kwargs: Any) -> httpx.Response:
        """:meth:`_send` with the pinned ``api-version``."""
        return self._send(method, url, params={**(params or {}), "api-version": AZURE_DEVOPS_API_VERSION}, **kwargs)

    def _is_credential_failure(self, response: httpx.Response) -> bool:
        """A 401, or the 203 sign-in page Azure DevOps answers a token it does not recognise with."""
        return response.status_code in (401, 203)

    # -- repository ----------------------------------------------------------------------------

    def get_repository(self) -> RepositoryInfo:
        """Read the repository, confirming the token can see it.

        Returns:
            The :class:`RepositoryInfo`; ``owner`` is ``organization/project``.
        """
        payload = self._call("GET", self._repo, what=f"reading {self._full_name}", kind=KIND_REPOSITORY).json() or {}
        project = str((payload.get("project") or {}).get("name") or self._project_name)
        return RepositoryInfo(
            full_name=f"{self._org}/{project}/{payload.get('name') or self._repo_name}",
            owner=f"{self._org}/{project}",
            default_branch=_branch(payload.get("defaultBranch")) or "main",
            can_push=True,
            archived=bool(payload.get("isDisabled")),
            html_url=payload.get("webUrl"),
        )

    def get_branch_sha(self, branch: str) -> Optional[str]:
        """Resolve a branch to its head commit, or ``None`` when it does not exist."""
        response = self._call("GET", f"{self._repo}/refs", what=f"reading branch {branch!r}", kind=KIND_READ,
                              params={"filter": f"heads/{branch}"})
        for ref in (response.json() or {}).get("value") or []:
            if (ref or {}).get("name") == f"{_HEADS}{branch}":
                return str(ref.get("objectId") or "") or None
        return None

    def _read_commit_message(self, commit_sha: str) -> Optional[str]:
        payload = self._call("GET", f"{self._repo}/commits/{quote(commit_sha, safe='')}",
                             what=f"reading commit {commit_sha[:12]}", kind=KIND_READ).json() or {}
        # A truncated comment may have lost its trailer; reading none means "rebuild", which is safe.
        return None if payload.get("commentTruncated") else str(payload.get("comment") or "")

    def _list_directory(self, commit_sha: str, path: str, *, ref_label: str) -> Dict[str, ExistingEntry]:
        scope = f"/{path}" if path else "/"
        response = self._call("GET", f"{self._repo}/items", what="reading the repository tree", kind=KIND_READ,
                              ok=(200, 404), params={"scopePath": scope, "recursionLevel": "Full",
                                                     "versionDescriptor.version": commit_sha,
                                                     "versionDescriptor.versionType": "commit"})
        if response.status_code == 404:
            return {}
        entries: Dict[str, ExistingEntry] = {}
        for item in (response.json() or {}).get("value") or []:
            item_path = str((item or {}).get("path") or "").strip("/")
            kind = str(item.get("gitObjectType") or ("tree" if item.get("isFolder") else "blob"))
            if item_path == path:
                if path and kind == "blob":
                    raise GitProviderError(ERROR_TARGET_PATH_INVALID, f"`{path}` is a file in "
                                           f"{self._full_name}@{ref_label}, so the export cannot be committed under "
                                           "it. Point the delivery at a directory.")
                continue
            if item_path:
                entries[item_path] = ExistingEntry(path=item_path, sha=str(item.get("objectId") or ""), type=kind,
                                                   mode={"tree": "040000", "commit": "160000"}.get(kind, FILE_MODE))
        return entries

    def get_blob_text(self, blob_sha: str) -> Optional[str]:
        """Read a small text blob, or ``None`` when it is too large or not UTF-8."""
        response = self._call("GET", f"{self._repo}/blobs/{quote(blob_sha, safe='')}",
                              what=f"reading blob {blob_sha[:12]}", kind=KIND_READ, params={"$format": "octetstream"})
        if len(response.content) > BLOB_READ_MAX_BYTES:
            return None
        try:
            return response.content.decode("utf-8")
        except UnicodeDecodeError:
            return None

    # -- the write -----------------------------------------------------------------------------

    @staticmethod
    def _push_changes(changes: List[FileChange]) -> List[Dict[str, Any]]:
        """Azure DevOps push changes for a change set."""
        out: List[Dict[str, Any]] = []
        for change in changes:
            item = {"path": f"/{change.path}"}
            if change.text is None:
                out.append({"changeType": "delete", "item": item})
            else:
                out.append({"changeType": "edit" if change.exists else "add", "item": item,
                            "newContent": {"content": change.text, "contentType": "rawtext"}})
        return out

    def _push(self, branch: str, old_object_id: str, message: str, changes: List[FileChange]) -> str:
        """Push one commit onto ``branch``, asserting it points at ``old_object_id``; returns the commit."""
        body = {"refUpdates": [{"name": f"{_HEADS}{branch}", "oldObjectId": old_object_id}],
                "commits": [{"comment": message, "changes": self._push_changes(changes)}]}
        payload = self._call("POST", f"{self._repo}/pushes", what=f"committing to {branch!r}", kind=KIND_PUSH,
                             ok=(200, 201), json=body).json() or {}
        commits = payload.get("commits") or []
        if commits and (commits[-1] or {}).get("commitId"):
            return str(commits[-1]["commitId"])
        updates = payload.get("refUpdates") or []
        return str((updates[0] or {}).get("newObjectId") or "") if updates else ""

    def _write_commit(self, branch: str, *, message: str, parent: str, changes: List[FileChange],
                      mode: str) -> str:
        current = self.get_branch_sha(branch) if mode == WRITE_FORCE else None
        if current is None:
            # Creating a branch (oldObjectId is the base it starts from) or fast-forwarding one
            # (oldObjectId is the parent it must still point at): both are one compare-and-swap push.
            return self._push(branch, parent, message, changes)
        scratch = f"{SCRATCH_BRANCH_PREFIX}{secrets.token_hex(6)}"
        written = self._push(scratch, parent, message, changes)
        updates = [{"name": f"{_HEADS}{branch}", "oldObjectId": current, "newObjectId": written},
                   {"name": f"{_HEADS}{scratch}", "oldObjectId": written, "newObjectId": _ZERO_ID}]
        response = self._call("POST", f"{self._repo}/refs", what=f"rebuilding branch {branch!r}", kind=KIND_PUSH,
                              json=updates)
        results = (response.json() or {}).get("value") or []
        first = results[0] if results else {}
        if not first.get("success", True):
            status = str(first.get("updateStatus") or "rejected")
            raise GitProviderError(ERROR_PUSH_REJECTED, self._redact(
                f"Azure DevOps refused to move {branch!r} to the rebuilt commit ({status}: "
                f"{first.get('customMessage') or 'no detail'}). Rebuilding a delivery branch needs the Force push "
                f"permission on Apiome's `apiome/export-*` branches; the commit was left on {scratch!r}."),
                http_status=response.status_code)
        return written

    # -- pull requests -------------------------------------------------------------------------

    def _pull(self, payload: Dict[str, Any]) -> PullRequest:
        """Project a pull request payload; its web page is built from the repository's address."""
        number = int(payload.get("pullRequestId") or 0)
        url = (f"{AZURE_DEVOPS_API_URL}/{quote(self._org, safe='')}/{quote(self._project_name, safe='')}/_git/"
               f"{quote(self._repo_name, safe='')}/pullrequest/{number}")
        return PullRequest(number=number, url=url, title=str(payload.get("title") or ""),
                           body=str(payload.get("description") or ""), base=_branch(payload.get("targetRefName")))

    @staticmethod
    def _description(body: str) -> str:
        """A description Azure DevOps accepts: at most :data:`DESCRIPTION_MAX_CHARS` characters."""
        if len(body) <= DESCRIPTION_MAX_CHARS:
            return body
        note = "\n\n… (shortened: Azure DevOps keeps 4,000 characters; the export's report has the rest.)"
        return body[: DESCRIPTION_MAX_CHARS - len(note)].rstrip() + note

    def find_open_pull(self, owner: str, branch: str) -> Optional[PullRequest]:
        """The active pull request from ``branch``, if any (``owner`` is unused)."""
        response = self._call("GET", f"{self._repo}/pullrequests",
                              what=f"looking for an open pull request from {branch!r}", kind=KIND_READ,
                              params={"searchCriteria.sourceRefName": f"{_HEADS}{branch}",
                                      "searchCriteria.status": "active", "$top": "5"})
        values = (response.json() or {}).get("value") or []
        return self._pull(values[0]) if values else None

    def create_pull(self, *, title: str, body: str, head: str, base: str) -> Optional[PullRequest]:
        """Open a pull request; ``None`` when one is already active from ``head``."""
        what = f"opening a pull request from {head!r} into {base!r}"
        response = self._call("POST", f"{self._repo}/pullrequests", what=what, kind=KIND_PULL, ok=(200, 201, 409),
                              json={"sourceRefName": f"{_HEADS}{head}", "targetRefName": f"{_HEADS}{base}",
                                    "title": title, "description": self._description(body)})
        return None if response.status_code == 409 else self._pull(response.json() or {})

    def update_pull(self, number: int, *, title: str, body: str, base: str) -> PullRequest:
        """Refresh a pull request's title, description and target branch."""
        response = self._call("PATCH", f"{self._repo}/pullrequests/{int(number)}",
                              what=f"updating pull request #{int(number)}", kind=KIND_PULL,
                              json={"title": title, "description": self._description(body),
                                    "targetRefName": f"{_HEADS}{base}"})
        return self._pull(response.json() or {})
