from __future__ import annotations

from typing import Any, AsyncIterator

import httpx

from .base import (
    BranchInfo,
    ListReposOpts,
    ReadFileResult,
    RepoDetail,
    RepoRef,
    RepositoryProvider,
    RepositoryProviderError,
    RepositoryProviderErrorCode,
    RepositoryProviderId,
    RepoSummary,
    TreeEntry,
)


class GithubRepositoryProvider(RepositoryProvider):
    id = RepositoryProviderId.GITHUB

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def list_repositories(self, token: str, opts: ListReposOpts | None = None) -> AsyncIterator[RepoSummary]:
        current = opts or ListReposOpts()
        page = current.page

        while True:
            repositories = await self._request_json(
                f"/user/repos?sort={current.sort}&per_page={current.per_page}&page={page}&visibility={current.visibility}",
                token,
            )
            if not isinstance(repositories, list) or len(repositories) == 0:
                return

            for repo in repositories:
                if not isinstance(repo, dict):
                    continue
                yield RepoSummary(
                    id=str(repo.get("id", "")),
                    name=str(repo.get("name", "")),
                    full_name=str(repo.get("full_name", "")),
                    description=repo.get("description"),
                    is_private=bool(repo.get("private", False)),
                    default_branch=str(repo.get("default_branch", "main")),
                    html_url=str(repo.get("html_url", "")),
                    updated_at=repo.get("updated_at"),
                )

            if len(repositories) < current.per_page:
                return
            page += 1

    async def get_repository(self, token: str, owner: str, name: str) -> RepoDetail:
        repo = await self._request_json(f"/repos/{owner}/{name}", token)
        if not isinstance(repo, dict):
            raise RepositoryProviderError(RepositoryProviderErrorCode.UNKNOWN, "Malformed GitHub response")

        return RepoDetail(
            id=str(repo.get("id", "")),
            name=str(repo.get("name", "")),
            full_name=str(repo.get("full_name", f"{owner}/{name}")),
            description=repo.get("description"),
            is_private=bool(repo.get("private", False)),
            default_branch=str(repo.get("default_branch", "main")),
            html_url=str(repo.get("html_url", "")),
            updated_at=repo.get("updated_at"),
        )

    async def list_branches(self, token: str, repo: RepoRef) -> AsyncIterator[BranchInfo]:
        page = 1
        per_page = 100

        while True:
            branches = await self._request_json(
                f"/repos/{repo.owner}/{repo.name}/branches?per_page={per_page}&page={page}",
                token,
            )
            if not isinstance(branches, list) or len(branches) == 0:
                return

            for branch in branches:
                if not isinstance(branch, dict):
                    continue
                commit = branch.get("commit", {})
                if not isinstance(commit, dict):
                    commit = {}
                yield BranchInfo(
                    name=str(branch.get("name", "")),
                    commit_sha=str(commit.get("sha", "")),
                    is_protected=bool(branch.get("protected", False)),
                )

            if len(branches) < per_page:
                return
            page += 1

    async def get_commit_sha(self, token: str, repo: RepoRef, branch: str) -> str:
        commit = await self._request_json(f"/repos/{repo.owner}/{repo.name}/commits/{branch}", token)
        if not isinstance(commit, dict):
            raise RepositoryProviderError(RepositoryProviderErrorCode.UNKNOWN, "Malformed GitHub response")
        return str(commit.get("sha", ""))

    async def walk_tree(
        self, token: str, repo: RepoRef, branch: str, subpath: str | None = None
    ) -> AsyncIterator[TreeEntry]:
        tree_response = await self._request_json(f"/repos/{repo.owner}/{repo.name}/git/trees/{branch}?recursive=1", token)
        if not isinstance(tree_response, dict):
            raise RepositoryProviderError(RepositoryProviderErrorCode.UNKNOWN, "Malformed GitHub response")

        tree = tree_response.get("tree", [])
        if not isinstance(tree, list):
            return

        prefix = _normalize_subpath(subpath)
        for entry in tree:
            if not isinstance(entry, dict):
                continue

            path = str(entry.get("path", ""))
            if not path:
                continue
            if prefix and not path.startswith(prefix):
                continue

            entry_type = _map_tree_type(str(entry.get("type", "")))
            if not entry_type:
                continue

            yield TreeEntry(
                path=path,
                type=entry_type,
                sha=str(entry.get("sha", "")),
                size_bytes=int(entry.get("size", 0)),
            )

    async def read_file(self, token: str, repo: RepoRef, branch: str, path: str) -> ReadFileResult:
        encoded_path = "/".join(httpx.QueryParams({"p": part})["p"] for part in path.split("/"))
        file_response = await self._request_json(
            f"/repos/{repo.owner}/{repo.name}/contents/{encoded_path}?ref={branch}",
            token,
        )
        if not isinstance(file_response, dict):
            raise RepositoryProviderError(RepositoryProviderErrorCode.UNKNOWN, "Malformed GitHub response")

        content = str(file_response.get("content", "")).replace("\n", "")
        return ReadFileResult(
            content_base64=content,
            sha=str(file_response.get("sha", "")),
            size_bytes=int(file_response.get("size", 0)),
        )

    async def _request_json(self, path_with_query: str, token: str) -> Any:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        if self._client is not None:
            return await _request_with_client(self._client, path_with_query, headers)

        async with httpx.AsyncClient(base_url="https://api.github.com", timeout=20) as client:
            return await _request_with_client(client, path_with_query, headers)


async def _request_with_client(client: httpx.AsyncClient, path_with_query: str, headers: dict[str, str]) -> Any:
    try:
        response = await client.get(path_with_query, headers=headers)
    except httpx.HTTPError as exc:
        raise RepositoryProviderError(RepositoryProviderErrorCode.NETWORK, "Failed to reach GitHub API") from exc

    if response.is_success:
        return response.json()

    body = response.text
    if response.status_code == 401:
        raise RepositoryProviderError(RepositoryProviderErrorCode.UNAUTHORIZED, "Unauthorized GitHub token", 401)
    if response.status_code == 404:
        raise RepositoryProviderError(RepositoryProviderErrorCode.NOT_FOUND, "GitHub resource not found", 404)
    if response.status_code == 429 or _is_rate_limited(response.status_code, body, response.headers):
        raise RepositoryProviderError(RepositoryProviderErrorCode.RATE_LIMITED, "GitHub API rate limit exceeded", 429)
    raise RepositoryProviderError(
        RepositoryProviderErrorCode.UNKNOWN,
        f"Unexpected GitHub API error: {response.status_code}",
        response.status_code,
    )


def _is_rate_limited(status_code: int, body: str, headers: httpx.Headers) -> bool:
    if status_code != 403:
        return False
    if headers.get("x-ratelimit-remaining") == "0":
        return True
    return "rate limit" in body.lower()


def _normalize_subpath(subpath: str | None) -> str:
    if not subpath:
        return ""
    trimmed = subpath.strip("/")
    if not trimmed:
        return ""
    return f"{trimmed}/"


def _map_tree_type(raw: str) -> str | None:
    if raw == "blob":
        return "file"
    if raw == "tree":
        return "dir"
    if raw == "symlink":
        return "symlink"
    if raw == "commit":
        return "submodule"
    return None
