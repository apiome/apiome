"""In-memory GitLab, Bitbucket Cloud and Azure DevOps for export git delivery tests (#6654).

Each fake implements just the REST endpoints its client in :mod:`app.export_git_delivery_gitlab`,
:mod:`app.export_git_delivery_bitbucket` or :mod:`app.export_git_delivery_azure_devops` calls, over
one shared object model (:class:`HostedRepo`): commits hold a flat ``path → bytes`` snapshot, refs
name commits, and blob ids are true git blob ids — so a delivery's locally computed ids match what
the host lists. Each host's write semantics are modelled where the delivery depends on them:

* **GitLab** — ``POST …/repository/commits`` refuses a ``start_sha`` on an existing branch without
  ``force``, refuses ``create`` of an existing file and ``update`` of a missing one, and appends to
  the branch head otherwise;
* **Bitbucket** — ``POST …/src`` with ``parents`` answers 409 unless the branch still points there;
  a branch can only be created and deleted, never moved;
* **Azure DevOps** — ``POST …/pushes`` compares ``oldObjectId`` with the branch head, and
  ``POST …/refs`` moves or deletes refs with the same compare-and-swap.

Served through :class:`httpx.MockTransport`. Not a test module (no ``test_`` prefix).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote

import httpx

from app.export_git_delivery_staged import bytes_blob_sha

#: The token every fake accepts unless a test says otherwise.
HOSTED_TOKEN = "glpat-fakeRepositoryTokenValue123456"

_ZERO = "0" * 40


@dataclass
class HostedPull:
    """A pull (merge) request a fake holds."""

    number: int
    head: str
    base: str
    title: str
    body: str
    state: str = "open"


@dataclass
class _Fault:
    method: str
    pattern: re.Pattern
    status: int
    message: str
    times: int


@dataclass
class HostedRepo:
    """One repository's worth of state, shared by the three host facades.

    Attributes:
        full_name: The repository's registered name.
        token: The only token accepted.
        default_branch: The repository's default branch.
        can_push: Whether the account may push (what each host reports in its own way).
        archived: Whether the repository is read-only.
        protected: Branches whose pushes are refused.
        requests: Every request received, as ``(method, path, body)``.
    """

    full_name: str
    token: str = HOSTED_TOKEN
    default_branch: str = "main"
    can_push: bool = True
    archived: bool = False
    protected: List[str] = field(default_factory=list)
    requests: List[Tuple[str, str, Any]] = field(default_factory=list)
    commits: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    refs: Dict[str, str] = field(default_factory=dict)
    pulls: List[HostedPull] = field(default_factory=list)
    _faults: List[_Fault] = field(default_factory=list)
    _hooks: List[Tuple[str, re.Pattern, Callable[[], None]]] = field(default_factory=list)

    # -- seeding and inspection ----------------------------------------------------------------

    def new_commit(self, files: Dict[str, bytes], parents: List[str], message: str) -> str:
        """Store a commit holding exactly ``files``; returns its id."""
        payload = json.dumps({"files": {k: v.decode("latin-1") for k, v in sorted(files.items())},
                              "parents": parents, "message": message, "n": len(self.commits)}, sort_keys=True)
        sha = hashlib.sha1(payload.encode("utf-8")).hexdigest()
        self.commits[sha] = {"files": dict(files), "parents": list(parents), "message": message}
        return sha

    def seed(self, files: Dict[str, str], *, branch: Optional[str] = None, message: str = "init") -> str:
        """Create a commit holding exactly ``files`` on ``branch`` (the default branch by default)."""
        branch = branch or self.default_branch
        parent = self.refs.get(branch)
        sha = self.new_commit({path: text.encode("utf-8") for path, text in files.items()},
                              [parent] if parent else [], message)
        self.refs[branch] = sha
        return sha

    def commit_to(self, branch: str, changes: Dict[str, Optional[str]], message: str = "change") -> str:
        """Commit on top of a branch (``None`` deletes a file) — a human pushing."""
        files = dict(self.commits[self.refs[branch]]["files"])
        for path, text in changes.items():
            if text is None:
                files.pop(path, None)
            else:
                files[path] = text.encode("utf-8")
        sha = self.new_commit(files, [self.refs[branch]], message)
        self.refs[branch] = sha
        return sha

    def files_at(self, ref: str) -> Dict[str, str]:
        """Every file on a branch (or at a commit), as text."""
        return {path: data.decode("utf-8") for path, data in self.commits[self.refs.get(ref, ref)]["files"].items()}

    def open_pulls(self) -> List[HostedPull]:
        """Every open pull request."""
        return [pull for pull in self.pulls if pull.state == "open"]

    def merge(self, number: int) -> None:
        """Squash-merge a pull request into its base."""
        pull = next(item for item in self.pulls if item.number == number)
        files = self.commits[self.refs[pull.head]]["files"]
        self.refs[pull.base] = self.new_commit(dict(files), [self.refs[pull.base]], f"Merge #{number}")
        pull.state = "merged"

    def fault(self, method: str, path_pattern: str, status: int, message: str = "refused", *, times: int = 1) -> None:
        """Answer the next ``times`` matching requests with a scripted refusal."""
        self._faults.append(_Fault(method, re.compile(path_pattern), status, message, times))

    def before(self, method: str, path_pattern: str, action: Callable[[], None]) -> None:
        """Run ``action`` once, just before the first matching request is served."""
        self._hooks.append((method, re.compile(path_pattern), action))

    def written(self) -> List[Tuple[str, str, Any]]:
        """Every request that could change the repository."""
        return [item for item in self.requests if item[0] in ("POST", "PATCH", "PUT", "DELETE")]

    # -- helpers for the facades ---------------------------------------------------------------

    def listing(self, commit: str, path: str) -> Optional[List[Dict[str, Any]]]:
        """Every directory and file under ``path`` at a commit; ``None`` when ``path`` is no directory."""
        files = self.commits[commit]["files"]
        prefix = f"{path}/" if path else ""
        under = {p: data for p, data in files.items() if p.startswith(prefix)}
        if path and not under:
            return None
        dirs = set()
        for p in under:
            parts = p[len(prefix):].split("/")[:-1]
            for i in range(1, len(parts) + 1):
                dirs.add(prefix + "/".join(parts[:i]))
        out: List[Dict[str, Any]] = [{"path": d, "type": "tree", "sha": ""} for d in sorted(dirs)]
        out += [{"path": p, "type": "blob", "sha": bytes_blob_sha(data), "data": data}
                for p, data in sorted(under.items())]
        return out

    def blob(self, sha: str) -> Optional[bytes]:
        """Any blob with this id, from any commit."""
        for commit in self.commits.values():
            for data in commit["files"].values():
                if bytes_blob_sha(data) == sha:
                    return data
        return None

    def apply(self, base: str, writes: Dict[str, Optional[bytes]], message: str) -> str:
        """A new commit: ``base``'s files with ``writes`` applied (``None`` deletes)."""
        files = dict(self.commits[base]["files"])
        for path, data in writes.items():
            if data is None:
                files.pop(path, None)
            else:
                files[path] = data
        return self.new_commit(files, [base], message)

    def pull(self, number: int) -> HostedPull:
        return next(item for item in self.pulls if item.number == number)

    def open_from(self, head: str) -> Optional[HostedPull]:
        return next((p for p in self.pulls if p.state == "open" and p.head == head), None)

    def add_pull(self, head: str, base: str, title: str, body: str) -> HostedPull:
        pull = HostedPull(len(self.pulls) + 1, head, base, title, body)
        self.pulls.append(pull)
        return pull


class _Facade:
    """The HTTP half every host shares: authentication, scripted faults and hooks."""

    #: Path prefix every repository route starts with (set by each facade).
    prefix = ""

    def __init__(self, repo: HostedRepo) -> None:
        self.repo = repo

    def __getattr__(self, name: str) -> Any:
        return getattr(self.repo, name)

    def client_factory(self) -> httpx.Client:
        """An :class:`httpx.Client` served by this fake."""
        return httpx.Client(transport=httpx.MockTransport(self._handle))

    def _unauthorized(self) -> httpx.Response:
        return httpx.Response(401, json={"message": "401 Unauthorized"})

    def _error(self, status: int, message: str) -> httpx.Response:
        return httpx.Response(status, json={"message": message})

    def _handle(self, request: httpx.Request) -> httpx.Response:
        raw = request.url.raw_path.decode("ascii").split("?", 1)[0]
        segments = [unquote(segment) for segment in raw.split("/")]
        path = "/".join(segments)
        content_type = request.headers.get("content-type", "")
        if "json" in content_type and request.content:
            body: Any = json.loads(request.content)
        elif request.content:
            body = parse_qs(request.content.decode("utf-8"), keep_blank_values=True)
        else:
            body = None
        self.repo.requests.append((request.method, path, body))
        for index, (method, pattern, action) in enumerate(list(self.repo._hooks)):
            if method == request.method and pattern.search(path):
                self.repo._hooks.pop(index)
                action()
                break
        if request.headers.get("authorization") != f"Bearer {self.repo.token}":
            return self._unauthorized()
        for fault in self.repo._faults:
            if fault.times > 0 and fault.method == request.method and fault.pattern.search(path):
                fault.times -= 1
                return self._error(fault.status, fault.message)
        return self._route(request, segments, path, body)

    def _route(self, request: httpx.Request, segments: List[str], path: str, body: Any) -> httpx.Response:
        raise NotImplementedError


# ===========================================================================
# GitLab
# ===========================================================================


class FakeGitLab(_Facade):
    """GitLab API v4 for one project (``/api/v4/projects/<encoded path>``)."""

    def _route(self, request: httpx.Request, segments: List[str], path: str, body: Any) -> httpx.Response:
        repo = self.repo
        if segments[:4] != ["", "api", "v4", "projects"] or len(segments) < 5 or segments[4] != repo.full_name:
            return self._error(404, "404 Project Not Found")
        rest = segments[5:]
        method = request.method
        params = request.url.params
        if not rest and method == "GET":
            namespace, _, _ = repo.full_name.rpartition("/")
            return httpx.Response(200, json={
                "path_with_namespace": repo.full_name, "namespace": {"full_path": namespace},
                "default_branch": repo.default_branch, "archived": repo.archived,
                "web_url": f"https://gitlab.com/{repo.full_name}",
                "permissions": {"project_access": {"access_level": 30 if repo.can_push else 20}, "group_access": None},
            })
        if rest[:2] == ["repository", "branches"] and method == "GET":
            sha = repo.refs.get("/".join(rest[2:]))
            if not sha:
                return self._error(404, "404 Branch Not Found")
            return httpx.Response(200, json={"commit": {"id": sha}})
        if rest[:2] == ["repository", "commits"] and len(rest) == 3 and method == "GET":
            commit = repo.commits.get(rest[2])
            if not commit:
                return self._error(404, "404 Commit Not Found")
            return httpx.Response(200, json={"id": rest[2], "message": commit["message"],
                                             "parent_ids": commit["parents"]})
        if rest == ["repository", "tree"] and method == "GET":
            commit = repo.refs.get(params.get("ref", ""), params.get("ref", ""))
            listing = repo.listing(commit, params.get("path", ""))
            if listing is None:
                if params.get("path", "") in repo.commits[commit]["files"]:
                    return httpx.Response(200, json=[])
                return self._error(404, "404 Tree Not Found")
            items = [{"id": e["sha"], "path": e["path"], "name": e["path"].rpartition("/")[2], "type": e["type"],
                      "mode": "040000" if e["type"] == "tree" else "100644"} for e in listing]
            per_page, page = int(params.get("per_page", "20")), int(params.get("page", "1"))
            chunk = items[(page - 1) * per_page: page * per_page]
            headers = {"x-next-page": str(page + 1)} if page * per_page < len(items) else {}
            return httpx.Response(200, json=chunk, headers=headers)
        if rest[:2] == ["repository", "files"] and method == "HEAD":
            commit = repo.refs.get(params.get("ref", ""), params.get("ref", ""))
            return httpx.Response(200 if "/".join(rest[2:]) in repo.commits[commit]["files"] else 404)
        if rest[:2] == ["repository", "blobs"] and rest[-1] == "raw" and method == "GET":
            data = repo.blob(rest[2])
            return httpx.Response(200, content=data) if data is not None else self._error(404, "404 Blob Not Found")
        if rest == ["repository", "commits"] and method == "POST":
            return self._commit(body)
        if rest == ["merge_requests"] and method == "GET":
            pull = repo.open_from(params.get("source_branch", "")) if params.get("state") == "opened" else None
            return httpx.Response(200, json=[self._mr(pull)] if pull else [])
        if rest == ["merge_requests"] and method == "POST":
            if repo.open_from(body["source_branch"]):
                return self._error(409, "Another open merge request already exists for this source branch")
            pull = repo.add_pull(body["source_branch"], body["target_branch"], body["title"], body["description"])
            return httpx.Response(201, json=self._mr(pull))
        if rest[:1] == ["merge_requests"] and len(rest) == 2 and method == "PUT":
            pull = repo.pull(int(rest[1]))
            pull.title, pull.body, pull.base = body["title"], body["description"], body["target_branch"]
            return httpx.Response(200, json=self._mr(pull))
        return self._error(404, "404 Not Found")

    def _mr(self, pull: HostedPull) -> Dict[str, Any]:
        return {"iid": pull.number, "web_url": f"https://gitlab.com/{self.repo.full_name}/-/merge_requests/{pull.number}",
                "title": pull.title, "description": pull.body, "target_branch": pull.base, "source_branch": pull.head}

    def _commit(self, body: Dict[str, Any]) -> httpx.Response:
        repo = self.repo
        branch = body["branch"]
        if branch in repo.protected:
            return self._error(403, "You are not allowed to push into this branch")
        exists = branch in repo.refs
        start = body.get("start_sha")
        if exists and start and not body.get("force"):
            return self._error(400, f"A branch called '{branch}' already exists. Switch to that branch in order to "
                               "make changes")
        base = start or repo.refs.get(branch)
        if not base:
            return self._error(400, "You can only create or edit files when you are on a branch")
        files = repo.commits[base]["files"]
        writes: Dict[str, Optional[bytes]] = {}
        for action in body["actions"]:
            present = action["file_path"] in files
            if action["action"] == "create" and present:
                return self._error(400, "A file with this name already exists")
            if action["action"] in ("update", "delete") and not present:
                return self._error(400, "A file with this name doesn't exist")
            writes[action["file_path"]] = None if action["action"] == "delete" else action["content"].encode("utf-8")
        sha = repo.apply(base, writes, body["commit_message"])
        repo.refs[branch] = sha
        return httpx.Response(201, json={"id": sha})


# ===========================================================================
# Bitbucket
# ===========================================================================


class FakeBitbucket(_Facade):
    """Bitbucket Cloud API 2.0 for one repository (``/2.0/repositories/<workspace>/<repo>``).

    Attributes:
        decline_on_branch_delete: When set, deleting a branch declines the open pull request from it.
        permission: What ``/user/permissions/repositories`` reports (``None`` answers 403).
    """

    def __init__(self, repo: HostedRepo, *, decline_on_branch_delete: bool = False,
                 permission: Optional[str] = "write") -> None:
        super().__init__(repo)
        self.decline_on_branch_delete = decline_on_branch_delete
        self.permission = permission

    def _error(self, status: int, message: str) -> httpx.Response:
        return httpx.Response(status, json={"type": "error", "error": {"message": message}})

    def _route(self, request: httpx.Request, segments: List[str], path: str, body: Any) -> httpx.Response:
        repo = self.repo
        method = request.method
        params = request.url.params
        if segments[:5] == ["", "2.0", "user", "permissions", "repositories"]:
            if self.permission is None:
                return self._error(403, "Your credentials lack one or more required privilege scopes.")
            return httpx.Response(200, json={"values": [{"permission": self.permission}]})
        workspace, _, name = repo.full_name.partition("/")
        if segments[:5] != ["", "2.0", "repositories", workspace, name]:
            return self._error(404, "Repository not found")
        rest = segments[5:]
        if not rest and method == "GET":
            return httpx.Response(200, json={"full_name": repo.full_name, "workspace": {"slug": workspace},
                                             "mainbranch": {"name": repo.default_branch},
                                             "links": {"html": {"href": f"https://bitbucket.org/{repo.full_name}"}}})
        if rest[:2] == ["refs", "branches"] and method == "GET":
            sha = repo.refs.get("/".join(rest[2:]))
            return httpx.Response(200, json={"target": {"hash": sha}}) if sha else self._error(404, "Branch not found")
        if rest[:2] == ["refs", "branches"] and method == "DELETE":
            branch = "/".join(rest[2:])
            if branch not in repo.refs:
                return self._error(404, "Branch not found")
            del repo.refs[branch]
            if self.decline_on_branch_delete:
                for pull in repo.pulls:
                    if pull.head == branch and pull.state == "open":
                        pull.state = "declined"
            return httpx.Response(204)
        if rest[:1] == ["commit"] and method == "GET":
            commit = repo.commits.get(rest[1])
            return httpx.Response(200, json={"hash": rest[1], "message": commit["message"]}) if commit else \
                self._error(404, "Commit not found")
        if rest[:1] == ["src"] and method == "GET":
            return self._src(request, rest)
        if rest == ["src"] and method == "POST":
            return self._commit(body)
        if rest == ["pullrequests"] and method == "GET":
            match = re.fullmatch(r'source\.branch\.name="(.*)"', params.get("q", ""))
            pull = repo.open_from(match.group(1)) if match and params.get("state") == "OPEN" else None
            return httpx.Response(200, json={"values": [self._pr(pull)] if pull else []})
        if rest == ["pullrequests"] and method == "POST":
            head, base = body["source"]["branch"]["name"], body["destination"]["branch"]["name"]
            if repo.open_from(head):
                return self._error(400, f"There is already an open pull request from {head} to {base}")
            return httpx.Response(201, json=self._pr(repo.add_pull(head, base, body["title"], body["description"])))
        if rest[:1] == ["pullrequests"] and len(rest) == 2:
            pull = repo.pull(int(rest[1]))
            if method == "PUT":
                pull.title, pull.body = body["title"], body["description"]
                pull.base = body["destination"]["branch"]["name"]
            return httpx.Response(200, json=self._pr(pull))
        return self._error(404, "Not found")

    def _pr(self, pull: HostedPull) -> Dict[str, Any]:
        return {"id": pull.number, "title": pull.title, "description": pull.body,
                "state": {"open": "OPEN", "merged": "MERGED"}.get(pull.state, "DECLINED"),
                "source": {"branch": {"name": pull.head}}, "destination": {"branch": {"name": pull.base}},
                "links": {"html": {"href": f"https://bitbucket.org/{self.repo.full_name}/pull-requests/{pull.number}"}}}

    def _src(self, request: httpx.Request, rest: List[str]) -> httpx.Response:
        repo = self.repo
        commit = rest[1]
        raw_path = "/".join(rest[2:])
        is_dir = raw_path == "" or raw_path.endswith("/")
        file_path = raw_path.strip("/")
        if commit not in repo.commits:
            return self._error(404, "Commit not found")
        files = repo.commits[commit]["files"]
        if not is_dir or file_path in files:
            data = files.get(file_path)
            return httpx.Response(200, content=data) if data is not None else self._error(404, "No such file")
        listing = repo.listing(commit, file_path)
        if listing is None:
            return self._error(404, "No such directory")
        values = [{"type": "commit_directory" if e["type"] == "tree" else "commit_file", "path": e["path"],
                   "attributes": []} for e in listing]
        page = int(request.url.params.get("page", "1"))
        size = 2
        chunk = values[(page - 1) * size: page * size]
        payload: Dict[str, Any] = {"values": chunk, "page": page}
        if page * size < len(values):
            payload["next"] = (f"https://api.bitbucket.org/2.0/repositories/{repo.full_name}/src/{commit}/"
                               f"{file_path + '/' if file_path else ''}?max_depth=32&page={page + 1}")
        return httpx.Response(200, json=payload)

    def _commit(self, form: Dict[str, List[str]]) -> httpx.Response:
        repo = self.repo
        branch = form["branch"][0]
        parent = form["parents"][0]
        if branch in repo.protected:
            return self._error(403, f"You can't push to {branch}: a branch restriction forbids it")
        if branch in repo.refs and repo.refs[branch] != parent:
            return self._error(409, f"{parent} is not the head of {branch}")
        writes: Dict[str, Optional[bytes]] = {key[1:]: values[0].encode("utf-8") for key, values in form.items()
                                              if key.startswith("/")}
        for path in form.get("files", []):
            writes[path] = None
        sha = repo.apply(parent, writes, form["message"][0])
        repo.refs[branch] = sha
        return httpx.Response(201, headers={"location": f"https://api.bitbucket.org/2.0/repositories/"
                                                        f"{repo.full_name}/commit/{sha}"})


# ===========================================================================
# Azure DevOps
# ===========================================================================


class FakeAzureDevOps(_Facade):
    """Azure DevOps Git API for one repository (``/<org>/<project>/_apis/git/repositories/<repo>``).

    Attributes:
        allow_force: Whether a non-fast-forward ref move is allowed (the Force push permission).
    """

    def __init__(self, repo: HostedRepo, *, allow_force: bool = True) -> None:
        super().__init__(repo)
        self.allow_force = allow_force

    def _unauthorized(self) -> httpx.Response:
        return httpx.Response(203, text="<html>Sign in</html>")

    def _is_ancestor(self, ancestor: str, commit: str) -> bool:
        seen = [commit]
        while seen:
            current = seen.pop()
            if current == ancestor:
                return True
            seen += self.repo.commits.get(current, {}).get("parents", [])
        return False

    def _route(self, request: httpx.Request, segments: List[str], path: str, body: Any) -> httpx.Response:
        repo = self.repo
        method = request.method
        params = request.url.params
        if params.get("api-version") != "7.1":
            return self._error(400, "api-version is required")
        org, project, name = repo.full_name.split("/")
        expected = ["", org, project, "_apis", "git", "repositories", name]
        if segments[:7] != expected:
            return self._error(404, "TF401019: The Git repository does not exist")
        rest = segments[7:]
        if not rest and method == "GET":
            return httpx.Response(200, json={"name": name, "project": {"name": project},
                                             "defaultBranch": f"refs/heads/{repo.default_branch}",
                                             "isDisabled": repo.archived,
                                             "webUrl": f"https://dev.azure.com/{org}/{project}/_git/{name}"})
        if rest == ["refs"] and method == "GET":
            prefix = "refs/" + params.get("filter", "")
            values = [{"name": f"refs/heads/{b}", "objectId": sha} for b, sha in repo.refs.items()
                      if f"refs/heads/{b}".startswith(prefix)]
            return httpx.Response(200, json={"value": values, "count": len(values)})
        if rest == ["refs"] and method == "POST":
            return self._update_refs(body)
        if rest[:1] == ["commits"] and method == "GET":
            commit = repo.commits.get(rest[1])
            return httpx.Response(200, json={"commitId": rest[1], "comment": commit["message"]}) if commit else \
                self._error(404, "TF401175: commit not found")
        if rest == ["items"] and method == "GET":
            commit = params.get("versionDescriptor.version", "")
            scope = params.get("scopePath", "/").strip("/")
            files = repo.commits[commit]["files"]
            if scope in files:
                return httpx.Response(200, json={"value": [{"path": f"/{scope}", "gitObjectType": "blob",
                                                            "objectId": bytes_blob_sha(files[scope])}]})
            listing = repo.listing(commit, scope)
            if listing is None:
                return self._error(404, "TF401174: The item could not be found")
            values = [{"path": f"/{scope}", "gitObjectType": "tree", "isFolder": True}]
            values += [{"path": f"/{e['path']}", "gitObjectType": e["type"], "objectId": e["sha"],
                        "isFolder": e["type"] == "tree"} for e in listing]
            return httpx.Response(200, json={"value": values})
        if rest[:1] == ["blobs"] and method == "GET":
            data = repo.blob(rest[1])
            return httpx.Response(200, content=data) if data is not None else self._error(404, "blob not found")
        if rest == ["pushes"] and method == "POST":
            return self._push(body)
        if rest == ["pullrequests"] and method == "GET":
            head = params.get("searchCriteria.sourceRefName", "").removeprefix("refs/heads/")
            pull = repo.open_from(head) if params.get("searchCriteria.status") == "active" else None
            return httpx.Response(200, json={"value": [self._pr(pull)] if pull else []})
        if rest == ["pullrequests"] and method == "POST":
            head = body["sourceRefName"].removeprefix("refs/heads/")
            if repo.open_from(head):
                return self._error(409, "TF401179: An active pull request for the source and target branch "
                                   "already exists.")
            if len(body["description"]) > 4000:
                return self._error(400, "The description is too long")
            pull = repo.add_pull(head, body["targetRefName"].removeprefix("refs/heads/"), body["title"],
                                 body["description"])
            return httpx.Response(201, json=self._pr(pull))
        if rest[:1] == ["pullrequests"] and len(rest) == 2 and method == "PATCH":
            pull = repo.pull(int(rest[1]))
            if len(body["description"]) > 4000:
                return self._error(400, "The description is too long")
            pull.title, pull.body = body["title"], body["description"]
            pull.base = body["targetRefName"].removeprefix("refs/heads/")
            return httpx.Response(200, json=self._pr(pull))
        return self._error(404, "not found")

    def _pr(self, pull: HostedPull) -> Dict[str, Any]:
        return {"pullRequestId": pull.number, "title": pull.title, "description": pull.body,
                "sourceRefName": f"refs/heads/{pull.head}", "targetRefName": f"refs/heads/{pull.base}"}

    def _push(self, body: Dict[str, Any]) -> httpx.Response:
        repo = self.repo
        [update] = body["refUpdates"]
        [commit] = body["commits"]
        branch = update["name"].removeprefix("refs/heads/")
        old = update["oldObjectId"]
        if branch in repo.protected:
            return self._error(403, "TF402455: Pushes to this branch are not permitted; you must use a pull "
                               "request to update this branch.")
        if branch in repo.refs and repo.refs[branch] != old:
            return self._error(409, "TF401028: The reference has already been updated by another client")
        if old not in repo.commits:
            return self._error(400, "TF401035: The object does not exist")
        files = repo.commits[old]["files"]
        writes: Dict[str, Optional[bytes]] = {}
        for change in commit["changes"]:
            item = change["item"]["path"].lstrip("/")
            if change["changeType"] == "add" and item in files:
                return self._error(400, "TF402446: the path already exists")
            if change["changeType"] in ("edit", "delete") and item not in files:
                return self._error(400, "TF401174: the item could not be found")
            writes[item] = None if change["changeType"] == "delete" else \
                change["newContent"]["content"].encode("utf-8")
        sha = repo.apply(old, writes, commit["comment"])
        repo.refs[branch] = sha
        return httpx.Response(201, json={"commits": [{"commitId": sha}],
                                         "refUpdates": [{"name": update["name"], "newObjectId": sha}]})

    def _update_refs(self, updates: List[Dict[str, Any]]) -> httpx.Response:
        repo = self.repo
        results = []
        for update in updates:
            branch = update["name"].removeprefix("refs/heads/")
            old, new = update["oldObjectId"], update["newObjectId"]
            if repo.refs.get(branch, _ZERO) != old:
                results.append({"name": update["name"], "success": False, "updateStatus": "staleOldObjectId"})
                continue
            if new == _ZERO:
                repo.refs.pop(branch, None)
            elif branch in repo.protected or (not self.allow_force and not self._is_ancestor(old, new)):
                results.append({"name": update["name"], "success": False, "updateStatus": "forcePushRequired",
                                "customMessage": "TF401027: You need the Git 'ForcePush' permission"})
                continue
            else:
                repo.refs[branch] = new
            results.append({"name": update["name"], "success": True, "updateStatus": "succeeded"})
        return httpx.Response(200, json={"value": results, "count": len(results)})


#: provider → (repository name, facade factory) for parametrised tests.
HOSTS: Dict[str, Tuple[str, Callable[[HostedRepo], _Facade]]] = {
    "gitlab": ("acme/platform/widgets-sdk", FakeGitLab),
    "bitbucket": ("acme/widgets-sdk", FakeBitbucket),
    "azure_devops": ("acme/Platform/widgets-sdk", FakeAzureDevOps),
}


def make_host(provider: str, **fields: Any) -> _Facade:
    """A seeded fake for ``provider`` holding ``README.md`` and a hand-written ``specs/orders/NOTES.md``."""
    full_name, factory = HOSTS[provider]
    facade_kwargs = {key: fields.pop(key) for key in ("decline_on_branch_delete", "permission", "allow_force")
                     if key in fields}
    repo = HostedRepo(full_name=full_name, **fields)
    repo.seed({"README.md": "# widgets\n", "specs/orders/NOTES.md": "hand-written\n"})
    return factory(repo, **facade_kwargs)
