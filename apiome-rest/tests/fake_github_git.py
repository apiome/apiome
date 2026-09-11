"""An in-memory GitHub for SDK-4.2 git delivery tests (#4496).

Implements just the REST endpoints :class:`app.sdk_git_delivery_github.GitHubGitClient` calls —
repository, refs, commits, trees, blobs and pull requests — over real object semantics: blobs are
named by their true git blob id (so a delivery's locally computed ids match), trees and commits by a
deterministic digest (so identical content yields identical ids), and a tree write applies its
entries on top of ``base_tree`` exactly as GitHub does, including deletion by ``sha: null``.

Served through :class:`httpx.MockTransport`, so the pipeline runs its whole protocol — including
force-updates, pull-request reuse and every refusal — without a network. Not a test module (no
``test_`` prefix), so pytest does not collect it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import unquote

import httpx

from app.sdk_git_delivery_changes import git_blob_sha

#: The token the fake accepts unless a test says otherwise.
DEFAULT_TOKEN = "ghp_fakeRepositoryTokenValue123456"


@dataclass
class _Fault:
    """A scripted refusal for matching requests."""

    method: str
    pattern: re.Pattern
    status: int
    payload: Dict[str, Any]
    headers: Dict[str, str]
    times: int


@dataclass
class FakePull:
    """A pull request the fake holds."""

    number: int
    head: str
    base: str
    title: str
    body: str
    state: str = "open"
    merged: bool = False


@dataclass
class FakeGitHub:
    """One repository's worth of GitHub.

    Attributes:
        full_name: ``owner/repo``.
        token: The only token accepted.
        default_branch: The repository's default branch.
        can_push: What ``permissions.push`` reports.
        archived: What ``archived`` reports.
        protected: Branches whose ref updates are refused with 422.
        truncate_trees: When set, recursive tree listings report ``truncated``.
        requests: Every request received, as ``(method, path, json_body)``.
    """

    full_name: str = "acme/widgets-sdk"
    token: str = DEFAULT_TOKEN
    default_branch: str = "main"
    can_push: bool = True
    archived: bool = False
    protected: List[str] = field(default_factory=list)
    truncate_trees: bool = False
    requests: List[Tuple[str, str, Any]] = field(default_factory=list)
    blobs: Dict[str, bytes] = field(default_factory=dict)
    trees: Dict[str, List[Dict[str, str]]] = field(default_factory=dict)
    commits: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    refs: Dict[str, str] = field(default_factory=dict)
    pulls: List[FakePull] = field(default_factory=list)
    _faults: List[_Fault] = field(default_factory=list)
    _hooks: List[Tuple[str, re.Pattern, Callable[[], None]]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.owner, self.name = self.full_name.split("/")

    # -- seeding and inspection ----------------------------------------------------------------

    def seed(self, files: Dict[str, str], *, branch: Optional[str] = None, message: str = "init") -> str:
        """Create a commit holding exactly ``files`` on ``branch`` (default branch by default)."""
        tree = self._write_tree({path: text.encode("utf-8") for path, text in files.items()})
        branch = branch or self.default_branch
        parent = self.refs.get(branch)
        sha = self._commit(tree, [parent] if parent else [], message)
        self.refs[branch] = sha
        return sha

    def commit_to(self, branch: str, changes: Dict[str, Optional[str]], message: str = "change") -> str:
        """Commit changes on top of a branch (``None`` deletes a file) — a human pushing."""
        files = self._flatten_blobs(self.commits[self.refs[branch]]["tree"])
        for path, text in changes.items():
            if text is None:
                files.pop(path, None)
            else:
                files[path] = text.encode("utf-8")
        sha = self._commit(self._write_tree(files), [self.refs[branch]], message)
        self.refs[branch] = sha
        return sha

    def files_at(self, ref: str) -> Dict[str, str]:
        """Every file on a branch (or at a commit), as text."""
        commit = self.refs.get(ref, ref)
        blobs = self._flatten_blobs(self.commits[commit]["tree"])
        return {path: data.decode("utf-8") for path, data in blobs.items()}

    def tree_of(self, ref: str) -> str:
        """The tree id a branch points at."""
        return self.commits[self.refs.get(ref, ref)]["tree"]

    def open_pulls(self) -> List[FakePull]:
        """Every open pull request."""
        return [pull for pull in self.pulls if pull.state == "open"]

    def merge(self, number: int) -> None:
        """Squash-merge a pull request into its base."""
        pull = next(item for item in self.pulls if item.number == number)
        head_tree = self.commits[self.refs[pull.head]]["tree"]
        self.refs[pull.base] = self._commit(head_tree, [self.refs[pull.base]], f"Merge #{number}")
        pull.state, pull.merged = "closed", True

    def close(self, number: int) -> None:
        """Close a pull request without merging."""
        next(item for item in self.pulls if item.number == number).state = "closed"

    def fault(
        self,
        method: str,
        path_pattern: str,
        status: int,
        message: str = "refused",
        *,
        headers: Optional[Dict[str, str]] = None,
        times: int = 1,
    ) -> None:
        """Answer the next ``times`` matching requests with a scripted refusal."""
        self._faults.append(
            _Fault(method, re.compile(path_pattern), status, {"message": message}, headers or {}, times)
        )

    def before(self, method: str, path_pattern: str, action: Callable[[], None]) -> None:
        """Run ``action`` once, just before the first matching request is served."""
        self._hooks.append((method, re.compile(path_pattern), action))

    def client_factory(self) -> httpx.Client:
        """An :class:`httpx.Client` served by this fake."""
        return httpx.Client(transport=httpx.MockTransport(self._handle))

    def written(self) -> List[Tuple[str, str, Any]]:
        """Every request that could change the repository."""
        return [item for item in self.requests if item[0] in ("POST", "PATCH", "PUT", "DELETE")]

    # -- object store --------------------------------------------------------------------------

    @staticmethod
    def _digest(kind: str, payload: Any) -> str:
        return hashlib.sha1(f"{kind}:{json.dumps(payload, sort_keys=True)}".encode()).hexdigest()

    def _put_blob(self, data: bytes) -> str:
        sha = git_blob_sha(data.decode("utf-8"))
        self.blobs[sha] = data
        return sha

    def _write_tree(self, files: Dict[str, bytes]) -> str:
        """Build nested trees from a flat ``path → bytes`` map; returns the root tree id."""
        children: Dict[str, Dict[str, bytes]] = {}
        entries: List[Dict[str, str]] = []
        for path, data in files.items():
            head, _, rest = path.partition("/")
            if rest:
                children.setdefault(head, {})[rest] = data
            else:
                entries.append({"path": head, "mode": "100644", "type": "blob", "sha": self._put_blob(data)})
        for name, nested in children.items():
            entries.append({"path": name, "mode": "040000", "type": "tree", "sha": self._write_tree(nested)})
        entries.sort(key=lambda entry: entry["path"])
        sha = self._digest("tree", entries)
        self.trees[sha] = entries
        return sha

    def _flatten(self, tree_sha: str, prefix: str = "") -> List[Dict[str, str]]:
        """Recursive listing: every tree and blob under a tree, with full relative paths."""
        out: List[Dict[str, str]] = []
        for entry in self.trees[tree_sha]:
            path = f"{prefix}{entry['path']}"
            out.append({**entry, "path": path})
            if entry["type"] == "tree":
                out.extend(self._flatten(entry["sha"], f"{path}/"))
        return out

    def _flatten_blobs(self, tree_sha: str) -> Dict[str, bytes]:
        return {
            entry["path"]: self.blobs[entry["sha"]]
            for entry in self._flatten(tree_sha)
            if entry["type"] == "blob"
        }

    def _commit(self, tree: str, parents: List[str], message: str) -> str:
        sha = self._digest("commit", {"tree": tree, "parents": parents, "message": message})
        self.commits[sha] = {"tree": tree, "parents": parents, "message": message}
        return sha

    # -- HTTP ----------------------------------------------------------------------------------

    def _pull_json(self, pull: FakePull) -> Dict[str, Any]:
        return {
            "number": pull.number,
            "html_url": f"https://github.com/{self.full_name}/pull/{pull.number}",
            "title": pull.title,
            "body": pull.body,
            "state": pull.state,
            "base": {"ref": pull.base},
            "head": {"ref": pull.head},
        }

    def _handle(self, request: httpx.Request) -> httpx.Response:
        method = request.method
        path = unquote(request.url.path)
        body = json.loads(request.content) if request.content else None
        self.requests.append((method, path, body))

        for index, (hook_method, pattern, action) in enumerate(list(self._hooks)):
            if hook_method == method and pattern.search(path):
                self._hooks.pop(index)
                action()
                break

        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"message": "Bad credentials"})

        for fault in self._faults:
            if fault.times > 0 and fault.method == method and fault.pattern.search(path):
                fault.times -= 1
                return httpx.Response(fault.status, json=fault.payload, headers=fault.headers)

        prefix = f"/repos/{self.owner}/{self.name}"
        if not path.startswith(prefix):
            return httpx.Response(404, json={"message": "Not Found"})
        route = path[len(prefix):]
        return self._route(method, route, body, request)

    def _route(self, method: str, route: str, body: Any, request: httpx.Request) -> httpx.Response:
        not_found = httpx.Response(404, json={"message": "Not Found"})

        if method == "GET" and route == "":
            return httpx.Response(
                200,
                json={
                    "full_name": self.full_name,
                    "owner": {"login": self.owner},
                    "default_branch": self.default_branch,
                    "archived": self.archived,
                    "html_url": f"https://github.com/{self.full_name}",
                    "permissions": {"admin": False, "push": self.can_push, "pull": True},
                },
            )

        match = re.fullmatch(r"/git/ref/heads/(.+)", route)
        if method == "GET" and match:
            sha = self.refs.get(match.group(1))
            if not sha:
                return not_found
            return httpx.Response(
                200, json={"ref": f"refs/heads/{match.group(1)}", "object": {"sha": sha, "type": "commit"}}
            )

        match = re.fullmatch(r"/git/commits/([0-9a-f]+)", route)
        if method == "GET" and match:
            commit = self.commits.get(match.group(1))
            if not commit:
                return not_found
            return httpx.Response(
                200,
                json={
                    "sha": match.group(1),
                    "tree": {"sha": commit["tree"]},
                    "parents": [{"sha": parent} for parent in commit["parents"]],
                    "message": commit["message"],
                },
            )

        match = re.fullmatch(r"/git/trees/([0-9a-f]+)", route)
        if method == "GET" and match:
            if match.group(1) not in self.trees:
                return not_found
            recursive = request.url.params.get("recursive") == "1"
            entries = self._flatten(match.group(1)) if recursive else self.trees[match.group(1)]
            return httpx.Response(
                200,
                json={"sha": match.group(1), "tree": entries, "truncated": recursive and self.truncate_trees},
            )

        match = re.fullmatch(r"/git/blobs/([0-9a-f]+)", route)
        if method == "GET" and match:
            data = self.blobs.get(match.group(1))
            if data is None:
                return not_found
            return httpx.Response(
                200,
                json={
                    "sha": match.group(1),
                    "size": len(data),
                    "encoding": "base64",
                    "content": base64.b64encode(data).decode("ascii"),
                },
            )

        if method == "POST" and route == "/git/blobs":
            return httpx.Response(201, json={"sha": self._put_blob(body["content"].encode("utf-8"))})

        if method == "POST" and route == "/git/trees":
            base = body.get("base_tree")
            files = self._flatten_blobs(base) if base else {}
            for entry in body["tree"]:
                if "content" in entry:
                    files[entry["path"]] = entry["content"].encode("utf-8")
                elif entry.get("sha") is None:
                    if entry["path"] not in files:
                        return httpx.Response(422, json={"message": "GitRPC::BadObjectState"})
                    files.pop(entry["path"])
                else:
                    files[entry["path"]] = self.blobs[entry["sha"]]
            return httpx.Response(201, json={"sha": self._write_tree(files)})

        if method == "POST" and route == "/git/commits":
            return httpx.Response(
                201, json={"sha": self._commit(body["tree"], list(body["parents"]), body["message"])}
            )

        if method == "POST" and route == "/git/refs":
            branch = body["ref"][len("refs/heads/"):]
            if branch in self.refs:
                return httpx.Response(422, json={"message": "Reference already exists"})
            self.refs[branch] = body["sha"]
            return httpx.Response(201, json={"ref": body["ref"], "object": {"sha": body["sha"]}})

        match = re.fullmatch(r"/git/refs/heads/(.+)", route)
        if method == "PATCH" and match:
            branch = match.group(1)
            if branch not in self.refs:
                return httpx.Response(422, json={"message": "Reference does not exist"})
            if branch in self.protected:
                return httpx.Response(
                    422, json={"message": "Protected branch update failed for refs/heads/" + branch}
                )
            if not body.get("force") and self.refs[branch] not in self.commits[body["sha"]]["parents"]:
                return httpx.Response(422, json={"message": "Update is not a fast forward"})
            self.refs[branch] = body["sha"]
            return httpx.Response(200, json={"ref": f"refs/heads/{branch}", "object": {"sha": body["sha"]}})

        if method == "GET" and route == "/pulls":
            head = request.url.params.get("head", "")
            state = request.url.params.get("state", "open")
            branch = head.split(":", 1)[1] if ":" in head else head
            found = [
                self._pull_json(pull)
                for pull in self.pulls
                if pull.head == branch and (state == "all" or pull.state == state)
            ]
            return httpx.Response(200, json=found)

        if method == "POST" and route == "/pulls":
            if any(pull.head == body["head"] and pull.state == "open" for pull in self.pulls):
                return httpx.Response(
                    422,
                    json={
                        "message": "Validation Failed",
                        "errors": [{"message": f"A pull request already exists for {self.owner}:{body['head']}."}],
                    },
                )
            if body["base"] not in self.refs or body["head"] not in self.refs:
                return httpx.Response(
                    422, json={"message": "Validation Failed", "errors": [{"message": "base invalid"}]}
                )
            pull = FakePull(
                number=len(self.pulls) + 1,
                head=body["head"],
                base=body["base"],
                title=body["title"],
                body=body["body"],
            )
            self.pulls.append(pull)
            return httpx.Response(201, json=self._pull_json(pull))

        match = re.fullmatch(r"/pulls/(\d+)", route)
        if method == "PATCH" and match:
            pull = next((item for item in self.pulls if item.number == int(match.group(1))), None)
            if pull is None:
                return not_found
            pull.title = body.get("title", pull.title)
            pull.body = body.get("body", pull.body)
            pull.base = body.get("base", pull.base)
            return httpx.Response(200, json=self._pull_json(pull))

        return not_found
