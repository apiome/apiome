from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator


class RepositoryProviderId(str, Enum):
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    AZURE_DEVOPS = "azure_devops"


class RepositoryProviderErrorCode(str, Enum):
    RATE_LIMITED = "RATE_LIMITED"
    UNAUTHORIZED = "UNAUTHORIZED"
    NOT_FOUND = "NOT_FOUND"
    NETWORK = "NETWORK"
    UNKNOWN = "UNKNOWN"


class RepositoryProviderError(RuntimeError):
    def __init__(self, code: RepositoryProviderErrorCode, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class ListReposOpts:
    per_page: int = 100
    page: int = 1
    sort: str = "updated"
    visibility: str = "all"


@dataclass(frozen=True)
class RepoRef:
    owner: str
    name: str


@dataclass(frozen=True)
class RepoSummary:
    id: str
    name: str
    full_name: str
    description: str | None
    is_private: bool
    default_branch: str
    html_url: str
    updated_at: str | None


@dataclass(frozen=True)
class RepoDetail(RepoSummary):
    pass


@dataclass(frozen=True)
class BranchInfo:
    name: str
    commit_sha: str
    is_protected: bool


@dataclass(frozen=True)
class TreeEntry:
    path: str
    type: str
    sha: str
    size_bytes: int


@dataclass(frozen=True)
class WebhookTarget:
    url: str
    events: tuple[str, ...]


@dataclass(frozen=True)
class ReadFileResult:
    content_base64: str
    sha: str
    size_bytes: int


class RepositoryProvider(ABC):
    id: RepositoryProviderId

    @abstractmethod
    async def list_repositories(self, token: str, opts: ListReposOpts | None = None) -> AsyncIterator[RepoSummary]:
        raise NotImplementedError

    @abstractmethod
    async def get_repository(self, token: str, owner: str, name: str) -> RepoDetail:
        raise NotImplementedError

    @abstractmethod
    async def list_branches(self, token: str, repo: RepoRef) -> AsyncIterator[BranchInfo]:
        raise NotImplementedError

    @abstractmethod
    async def get_commit_sha(self, token: str, repo: RepoRef, branch: str) -> str:
        raise NotImplementedError

    @abstractmethod
    async def walk_tree(
        self, token: str, repo: RepoRef, branch: str, subpath: str | None = None
    ) -> AsyncIterator[TreeEntry]:
        raise NotImplementedError

    @abstractmethod
    async def read_file(self, token: str, repo: RepoRef, branch: str, path: str) -> ReadFileResult:
        raise NotImplementedError
