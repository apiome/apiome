import pytest

from app.repositories.providers import RepoRef, RepositoryProviderError, RepositoryProviderErrorCode, TreeEntry
from app.repositories.providers.base import ListReposOpts, ReadFileResult, RepoDetail
from app.repositories.tree_walker import DEFAULT_SCAN_IGNORE_PATTERNS, ScanLimit, walk_repository_tree


class _StubProvider:
    def __init__(self, entries: list[TreeEntry]) -> None:
        self._entries = entries
        self.walk_tree_calls: list[tuple[str, RepoRef, str, str | None]] = []
        self.walk_tree_yields = 0

    async def list_repositories(self, token: str, opts: ListReposOpts | None = None):  # pragma: no cover
        raise NotImplementedError

    async def get_repository(self, token: str, owner: str, name: str) -> RepoDetail:  # pragma: no cover
        raise NotImplementedError

    async def list_branches(self, token: str, repo: RepoRef):  # pragma: no cover
        raise NotImplementedError

    async def get_commit_sha(self, token: str, repo: RepoRef, branch: str) -> str:  # pragma: no cover
        raise NotImplementedError

    async def walk_tree(self, token: str, repo: RepoRef, branch: str, subpath: str | None = None):
        self.walk_tree_calls.append((token, repo, branch, subpath))
        for entry in self._entries:
            self.walk_tree_yields += 1
            yield entry

    async def read_file(self, token: str, repo: RepoRef, branch: str, path: str) -> ReadFileResult:  # pragma: no cover
        raise NotImplementedError


@pytest.mark.asyncio
async def test_walk_repository_tree_is_streaming_and_passes_commit_sha() -> None:
    provider = _StubProvider(
        [
            TreeEntry(path="README.md", type="file", sha="a1", size_bytes=4, mode="100644"),
            TreeEntry(path="src/main.py", type="file", sha="a2", size_bytes=8, mode="100644"),
        ]
    )

    collected: list[TreeEntry] = []
    async for entry in walk_repository_tree(
        provider=provider,
        token="token-a",
        repo=RepoRef(owner="acme", name="repo-a"),
        commit_sha="commit-sha-1",
        subpath_glob="**/*",
    ):
        collected.append(entry)
        break

    assert len(collected) == 1
    assert collected[0].path == "README.md"
    assert provider.walk_tree_yields == 1
    assert provider.walk_tree_calls == [("token-a", RepoRef(owner="acme", name="repo-a"), "commit-sha-1", None)]


@pytest.mark.asyncio
async def test_walk_repository_tree_filters_on_subpath_glob_boundary() -> None:
    provider = _StubProvider(
        [
            TreeEntry(path="docs/readme.md", type="file", sha="a1", size_bytes=10, mode="100644"),
            TreeEntry(path="src/main.py", type="file", sha="a2", size_bytes=12, mode="100644"),
            TreeEntry(path="src/utils/helpers.py", type="file", sha="a3", size_bytes=15, mode="100644"),
            TreeEntry(path="src/generated", type="dir", sha="a4", size_bytes=0, mode="040000"),
        ]
    )

    result = [
        entry
        async for entry in walk_repository_tree(
            provider=provider,
            token="token-a",
            repo=RepoRef(owner="acme", name="repo-a"),
            commit_sha="commit-sha-1",
            subpath_glob="src/**/*.py",
        )
    ]

    assert [entry.path for entry in result] == ["src/main.py", "src/utils/helpers.py"]


@pytest.mark.asyncio
async def test_walk_repository_tree_raises_typed_error_when_scan_limits_exceeded() -> None:
    provider = _StubProvider(
        [
            TreeEntry(path="src/main.py", type="file", sha="a1", size_bytes=10, mode="100644"),
            TreeEntry(path="src/helpers.py", type="file", sha="a2", size_bytes=10, mode="100644"),
        ]
    )

    with pytest.raises(RepositoryProviderError) as exc:
        [
            entry
            async for entry in walk_repository_tree(
                provider=provider,
                token="token-a",
                repo=RepoRef(owner="acme", name="repo-a"),
                commit_sha="commit-sha-1",
                subpath_glob="src/**/*.py",
                limits=ScanLimit(max_files=1, max_bytes=100),
            )
        ]

    assert exc.value.code == RepositoryProviderErrorCode.SCAN_LIMIT_EXCEEDED
    assert "scan file limit exceeded" in str(exc.value)


@pytest.mark.asyncio
async def test_walk_repository_tree_emits_repository_scan_walked_audit() -> None:
    provider = _StubProvider(
        [
            TreeEntry(path="README.md", type="file", sha="a1", size_bytes=4, mode="100644"),
            TreeEntry(path="docs/guide.md", type="file", sha="a2", size_bytes=11, mode="100644"),
        ]
    )
    audits: list[tuple[str, dict[str, object]]] = []

    [
        entry
        async for entry in walk_repository_tree(
            provider=provider,
            token="token-a",
            repo=RepoRef(owner="acme", name="repo-a"),
            commit_sha="commit-sha-1",
            subpath_glob="**/*",
            audit_emitter=lambda event_type, detail: audits.append((event_type, detail)),
        )
    ]

    assert audits == [
        (
            "repository.scan.walked",
            {
                "owner": "acme",
                "name": "repo-a",
                "commitSha": "commit-sha-1",
                "subpathGlob": "**/*",
                "files": 2,
                "bytes": 15,
                "files_skipped_by_ignore": 0,
            },
        )
    ]


@pytest.mark.asyncio
async def test_walk_repository_tree_applies_default_ignore_rules_and_reports_skip_count() -> None:
    provider = _StubProvider(
        [
            TreeEntry(path="README.md", type="file", sha="a1", size_bytes=4, mode="100644"),
            TreeEntry(path="node_modules/package/index.js", type="file", sha="a2", size_bytes=20, mode="100644"),
            TreeEntry(path="src/main.py", type="file", sha="a3", size_bytes=8, mode="100644"),
        ]
    )
    audits: list[tuple[str, dict[str, object]]] = []

    result = [
        entry
        async for entry in walk_repository_tree(
            provider=provider,
            token="token-a",
            repo=RepoRef(owner="acme", name="repo-a"),
            commit_sha="commit-sha-1",
            subpath_glob="**/*",
            audit_emitter=lambda event_type, detail: audits.append((event_type, detail)),
        )
    ]

    assert [entry.path for entry in result] == ["README.md", "src/main.py"]
    assert audits[0][1]["files_skipped_by_ignore"] == 1
    assert "node_modules/**" in DEFAULT_SCAN_IGNORE_PATTERNS


@pytest.mark.asyncio
async def test_walk_repository_tree_merges_manifest_ignore_with_defaults() -> None:
    provider = _StubProvider(
        [
            TreeEntry(path="dist/app.js", type="file", sha="a1", size_bytes=11, mode="100644"),
            TreeEntry(path="docs/generated/spec.md", type="file", sha="a2", size_bytes=14, mode="100644"),
            TreeEntry(path="docs/guide.md", type="file", sha="a3", size_bytes=9, mode="100644"),
        ]
    )

    result = [
        entry
        async for entry in walk_repository_tree(
            provider=provider,
            token="token-a",
            repo=RepoRef(owner="acme", name="repo-a"),
            commit_sha="commit-sha-1",
            subpath_glob="**/*",
            manifest_ignore=["docs/generated/**"],
        )
    ]

    assert [entry.path for entry in result] == ["docs/guide.md"]


@pytest.mark.asyncio
async def test_walk_repository_tree_explicit_specs_override_ignore_patterns() -> None:
    provider = _StubProvider(
        [
            TreeEntry(path="dist/openapi.yaml", type="file", sha="a1", size_bytes=13, mode="100644"),
            TreeEntry(path="dist/bundle.js", type="file", sha="a2", size_bytes=21, mode="100644"),
        ]
    )

    result = [
        entry
        async for entry in walk_repository_tree(
            provider=provider,
            token="token-a",
            repo=RepoRef(owner="acme", name="repo-a"),
            commit_sha="commit-sha-1",
            subpath_glob="**/*",
            manifest_specs=["dist/openapi.yaml"],
            manifest_ignore=["dist/**"],
        )
    ]

    assert [entry.path for entry in result] == ["dist/openapi.yaml"]
