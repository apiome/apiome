import json

import httpx
import pytest

from app.repositories.providers import (
    GithubRepositoryProvider,
    RepoRef,
    RepositoryProviderError,
    RepositoryProviderErrorCode,
)


def _json_response(status: int, payload: object, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, headers=headers, content=json.dumps(payload).encode("utf-8"))


@pytest.mark.asyncio
async def test_github_provider_contract_methods() -> None:
    call_index = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_index
        call_index += 1

        if call_index == 1:
            assert request.headers["Authorization"] == "Bearer token-a"
            return _json_response(
                200,
                [
                    {
                        "id": 1,
                        "name": "repo-a",
                        "full_name": "acme/repo-a",
                        "description": "demo",
                        "private": False,
                        "default_branch": "main",
                        "html_url": "https://github.com/acme/repo-a",
                        "updated_at": "2026-01-01T00:00:00Z",
                    }
                ],
            )
        if call_index == 2:
            return _json_response(
                200,
                {
                    "id": 1,
                    "name": "repo-a",
                    "full_name": "acme/repo-a",
                    "description": "demo",
                    "private": False,
                    "default_branch": "main",
                    "html_url": "https://github.com/acme/repo-a",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
            )
        if call_index == 3:
            return _json_response(200, [{"name": "main", "protected": True, "commit": {"sha": "abc123"}}])
        if call_index == 4:
            return _json_response(200, {"sha": "abc123"})
        if call_index == 5:
            return _json_response(
                200,
                {
                    "tree": [
                        {"path": "docs/readme.md", "type": "blob", "sha": "s1", "size": 10},
                        {"path": "src/index.ts", "type": "blob", "sha": "s2", "size": 11},
                    ]
                },
            )
        return _json_response(200, {"content": "YQ==", "sha": "f1", "size": 1})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.github.com", transport=transport) as client:
        provider = GithubRepositoryProvider(client)

        repos = [repo async for repo in provider.list_repositories("token-a")]
        repo = await provider.get_repository("token-a", "acme", "repo-a")
        branches = [branch async for branch in provider.list_branches("token-a", RepoRef(owner="acme", name="repo-a"))]
        sha = await provider.get_commit_sha("token-a", RepoRef(owner="acme", name="repo-a"), "main")
        tree = [
            item
            async for item in provider.walk_tree("token-a", RepoRef(owner="acme", name="repo-a"), "main", subpath="docs")
        ]
        read_file = await provider.read_file("token-a", RepoRef(owner="acme", name="repo-a"), "main", "docs/readme.md")

    assert len(repos) == 1
    assert repo.full_name == "acme/repo-a"
    assert [branch.name for branch in branches] == ["main"]
    assert sha == "abc123"
    assert [entry.path for entry in tree] == ["docs/readme.md"]
    assert read_file.content_base64 == "YQ=="


@pytest.mark.asyncio
async def test_github_provider_normalizes_errors() -> None:
    def rate_limit_handler(request: httpx.Request) -> httpx.Response:
        return _json_response(403, {"message": "API rate limit exceeded"}, headers={"x-ratelimit-remaining": "0"})

    transport = httpx.MockTransport(rate_limit_handler)
    async with httpx.AsyncClient(base_url="https://api.github.com", transport=transport) as client:
        provider = GithubRepositoryProvider(client)
        with pytest.raises(RepositoryProviderError) as exc:
            await provider.get_repository("token-z", "acme", "repo-a")

    assert exc.value.code == RepositoryProviderErrorCode.RATE_LIMITED
