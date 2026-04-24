from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from inspect import isawaitable
from typing import Any, AsyncIterator, Callable, Sequence

from .providers import RepoRef, RepositoryProvider, RepositoryProviderError, RepositoryProviderErrorCode, TreeEntry

WorkflowAuditEmitter = Callable[[str, dict[str, Any]], Any]

DEFAULT_SCAN_IGNORE_PATTERNS: tuple[str, ...] = (
    ".git/**",
    "node_modules/**",
    "vendor/**",
    "dist/**",
    "build/**",
    "coverage/**",
    "**/__pycache__/**",
)


@dataclass(frozen=True)
class RepositoryWalkStats:
    files: int
    bytes: int


@dataclass(frozen=True)
class ScanLimit:
    max_files: int | None = None
    max_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.max_files is not None and self.max_files < 1:
            raise ValueError("max_files must be >= 1 when provided")
        if self.max_bytes is not None and self.max_bytes < 1:
            raise ValueError("max_bytes must be >= 1 when provided")


async def walk_repository_tree(
    provider: RepositoryProvider,
    *,
    token: str,
    repo: RepoRef,
    commit_sha: str,
    subpath_glob: str | None,
    manifest_specs: Sequence[str] | None = None,
    manifest_ignore: Sequence[str] | None = None,
    limits: ScanLimit | None = None,
    audit_emitter: WorkflowAuditEmitter | None = None,
) -> AsyncIterator[TreeEntry]:
    """Yield repository file entries for a specific commit SHA with scan limits."""
    stats = RepositoryWalkStats(files=0, bytes=0)
    effective_limits = limits or ScanLimit()
    files_skipped_by_ignore = 0
    explicit_specs = _normalize_patterns(manifest_specs)
    merged_ignore_patterns = _merge_ignore_patterns(manifest_ignore)

    async for entry in provider.walk_tree(token=token, repo=repo, branch=commit_sha):
        if entry.type != "file":
            continue
        if not _glob_match(entry.path, subpath_glob):
            continue
        if _should_skip_for_ignore(
            entry.path,
            ignore_patterns=merged_ignore_patterns,
            explicit_specs=explicit_specs,
        ):
            files_skipped_by_ignore += 1
            continue

        next_files = stats.files + 1
        next_bytes = stats.bytes + max(0, entry.size_bytes)
        _ensure_scan_limits(
            limits=effective_limits,
            files=next_files,
            bytes_scanned=next_bytes,
            path=entry.path,
        )
        stats = RepositoryWalkStats(files=next_files, bytes=next_bytes)
        yield entry

    if audit_emitter is not None:
        maybe_awaitable = audit_emitter(
            "repository.scan.walked",
            {
                "owner": repo.owner,
                "name": repo.name,
                "commitSha": commit_sha,
                "subpathGlob": subpath_glob,
                "files": stats.files,
                "bytes": stats.bytes,
                "files_skipped_by_ignore": files_skipped_by_ignore,
            },
        )
        if isawaitable(maybe_awaitable):
            await maybe_awaitable


def _ensure_scan_limits(*, limits: ScanLimit, files: int, bytes_scanned: int, path: str) -> None:
    if limits.max_files is not None and files > limits.max_files:
        raise RepositoryProviderError(
            RepositoryProviderErrorCode.SCAN_LIMIT_EXCEEDED,
            f"scan file limit exceeded at '{path}': {files} > {limits.max_files}",
        )
    if limits.max_bytes is not None and bytes_scanned > limits.max_bytes:
        raise RepositoryProviderError(
            RepositoryProviderErrorCode.SCAN_LIMIT_EXCEEDED,
            f"scan byte limit exceeded at '{path}': {bytes_scanned} > {limits.max_bytes}",
        )


def _glob_match(path: str, pattern: str | None) -> bool:
    if not pattern:
        return True

    normalized_pattern = pattern.strip()
    if not normalized_pattern or normalized_pattern in {"**", "**/*"}:
        return True

    path_parts = tuple(part for part in path.strip("/").split("/") if part)
    pattern_parts = tuple(part for part in normalized_pattern.strip("/").split("/") if part)
    if not path_parts:
        return False
    if not pattern_parts:
        return True
    return _match_parts(path_parts, pattern_parts)


def _normalize_patterns(patterns: Sequence[str] | None) -> tuple[str, ...]:
    if not patterns:
        return ()
    return tuple(pattern.strip() for pattern in patterns if pattern and pattern.strip())


def _merge_ignore_patterns(manifest_ignore: Sequence[str] | None) -> tuple[str, ...]:
    merged = list(DEFAULT_SCAN_IGNORE_PATTERNS)
    for pattern in _normalize_patterns(manifest_ignore):
        if pattern not in merged:
            merged.append(pattern)
    return tuple(merged)


def _matches_any(path: str, patterns: Sequence[str]) -> bool:
    return any(_glob_match(path, pattern) for pattern in patterns)


def _should_skip_for_ignore(path: str, *, ignore_patterns: Sequence[str], explicit_specs: Sequence[str]) -> bool:
    if _matches_any(path, explicit_specs):
        return False
    return _matches_any(path, ignore_patterns)


def _match_parts(path_parts: Sequence[str], pattern_parts: Sequence[str]) -> bool:
    if not pattern_parts:
        return len(path_parts) == 0

    pattern_head = pattern_parts[0]
    if pattern_head == "**":
        return _match_parts(path_parts, pattern_parts[1:]) or (
            len(path_parts) > 0 and _match_parts(path_parts[1:], pattern_parts)
        )

    if not path_parts:
        return False
    if not fnmatchcase(path_parts[0], pattern_head):
        return False
    return _match_parts(path_parts[1:], pattern_parts[1:])
