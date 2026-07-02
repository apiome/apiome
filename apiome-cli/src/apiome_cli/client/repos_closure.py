"""Helpers for repository file ``$ref`` closure resolution (#2000)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypedDict

import typer

from apiome_cli.client.http import RestClient
from apiome_cli.import_.yaml_load import safe_load
from apiome_cli.client.pagination import paginate_list
from apiome_cli.output import emit_json

RepositoryFileClosureStatus = Literal["resolved", "missing"]


class RepositoryFileClosureMember(TypedDict):
    """One resolved or missing ``$ref`` target in a repository file closure."""

    path: str
    blob_sha: str | None
    status: RepositoryFileClosureStatus
    ref: str
    source_path: str


class RepositoryFileClosureResponse(TypedDict):
    """Resolved ``$ref`` closure for a repository entrypoint file."""

    entrypoint: str
    members: list[RepositoryFileClosureMember]
    has_unresolved: bool
    total: int
    resolved_count: int
    missing_count: int


_REF_ENTRY = tuple[str, str]
_YAML_REF_PATTERN = re.compile(
    r"\$ref\s*:\s*['\"]?([^'\"#\s][^'\"#\n]*?)\s*['\"]?\s*(?:#.*)?$",
    re.MULTILINE,
)
_REPOSITORY_FILE_TREE_LIMIT = 10_000


def resolve_relative_path(source_path: str, file_part: str) -> str:
    """Resolve *file_part* against the directory of *source_path*.

    Parameters
    ----------
    source_path:
        Repository-relative path of the file containing the ``$ref``.
    file_part:
        Relative target path from the ``$ref`` (fragment stripped).

    Returns
    -------
    str
        Normalized repository-relative path for the target file.
    """
    segments = source_path.split("/")
    segments.pop()

    for part in file_part.split("/"):
        if part == "..":
            if segments:
                segments.pop()
        elif part not in {".", ""}:
            segments.append(part)

    return "/".join(segment for segment in segments if segment)


def _collect_relative_refs(
    document: object,
    *,
    visited: set[int] | None = None,
) -> list[_REF_ENTRY]:
    """Recursively collect relative ``$ref`` targets from a parsed document."""
    refs: list[_REF_ENTRY] = []
    if document is None or not isinstance(document, (dict, list)):
        return refs

    document_id = id(document)
    if visited is None:
        visited = set()
    if document_id in visited:
        return refs
    visited.add(document_id)

    if isinstance(document, list):
        for item in document:
            refs.extend(_collect_relative_refs(item, visited=visited))
        return refs

    ref_value = document.get("$ref")
    if isinstance(ref_value, str):
        hash_idx = ref_value.find("#")
        file_part = ref_value[:hash_idx] if hash_idx >= 0 else ref_value
        if file_part and not file_part.startswith(("http://", "https://")):
            refs.append((ref_value, file_part))

    for value in document.values():
        refs.extend(_collect_relative_refs(value, visited=visited))

    return refs


def _collect_refs_from_yaml(content: str) -> list[_REF_ENTRY]:
    """Regex-based ``$ref`` extraction for YAML where structured parse fails."""
    refs: list[_REF_ENTRY] = []
    for match in _YAML_REF_PATTERN.finditer(content):
        raw_ref = match.group(1).strip()
        if raw_ref and not raw_ref.startswith(("http://", "https://")):
            refs.append((raw_ref, raw_ref))
    return refs


def extract_relative_refs(content: str) -> list[_REF_ENTRY]:
    """Extract relative ``$ref`` targets from JSON or YAML file content.

    Parameters
    ----------
    content:
        Raw file text from the repository content cache.

    Returns
    -------
    list[tuple[str, str]]
        Pairs of ``(ref, file_part)`` for each relative target found.
    """
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = None

    if parsed is None:
        try:
            yaml_parsed = safe_load(content)
        except ValueError:
            yaml_parsed = None
        if isinstance(yaml_parsed, (dict, list)):
            return _collect_relative_refs(yaml_parsed)

    if isinstance(parsed, (dict, list)):
        return _collect_relative_refs(parsed)

    return _collect_refs_from_yaml(content)


def build_repository_file_closure(
    *,
    source_path: str,
    content: str,
    files_by_path: Mapping[str, Mapping[str, Any]],
) -> RepositoryFileClosureResponse:
    """Build closure metadata for one repository entrypoint file.

    Parameters
    ----------
    source_path:
        Repository-relative path of the entrypoint file.
    content:
        Raw entrypoint file text used to extract ``$ref`` targets.
    files_by_path:
        Scanned repository files keyed by repository-relative path.

    Returns
    -------
    RepositoryFileClosureResponse
        Resolved and missing closure members with aggregate counts.
    """
    raw_refs = extract_relative_refs(content)
    target_paths: dict[str, _REF_ENTRY] = {}
    for ref, file_part in raw_refs:
        resolved = resolve_relative_path(source_path, file_part)
        if resolved not in target_paths:
            target_paths[resolved] = (ref, file_part)

    members: list[RepositoryFileClosureMember] = []
    resolved_count = 0
    missing_count = 0

    for target_path in sorted(target_paths):
        ref, _file_part = target_paths[target_path]
        match = files_by_path.get(target_path)
        if match is not None:
            resolved_count += 1
            blob_sha = match.get("blob_sha")
            members.append(
                {
                    "path": target_path,
                    "blob_sha": blob_sha if isinstance(blob_sha, str) else None,
                    "status": "resolved",
                    "ref": ref,
                    "source_path": source_path,
                },
            )
        else:
            missing_count += 1
            members.append(
                {
                    "path": target_path,
                    "blob_sha": None,
                    "status": "missing",
                    "ref": ref,
                    "source_path": source_path,
                },
            )

    members.sort(
        key=lambda entry: (0 if entry["status"] == "missing" else 1, entry["path"]),
    )

    return {
        "entrypoint": source_path,
        "members": members,
        "has_unresolved": missing_count > 0,
        "total": len(members),
        "resolved_count": resolved_count,
        "missing_count": missing_count,
    }


def fetch_repository_files_by_path(
    client: RestClient,
    tenant_id: str,
    repository_id: str,
) -> dict[str, dict[str, Any]]:
    """Fetch the scanned repository file tree keyed by repository-relative path."""
    items, total = paginate_list(
        client,
        f"/tenants/{tenant_id}/repositories/{repository_id}/files",
        limit=_REPOSITORY_FILE_TREE_LIMIT,
        fetch_all=True,
    )
    if total > _REPOSITORY_FILE_TREE_LIMIT:
        typer.echo(
            (
                f"Warning: repository has {total} files; dependency closure may be "
                f"incomplete due to {_REPOSITORY_FILE_TREE_LIMIT} file limit."
            ),
            err=True,
        )
    return {
        str(item.get("path") or ""): item
        for item in items
        if isinstance(item.get("path"), str) and item.get("path")
    }


def fetch_repository_file_content(
    client: RestClient,
    tenant_id: str,
    repository_id: str,
    file_id: str,
) -> str:
    """Download raw repository file content as UTF-8 text."""
    response = client.get(
        f"/tenants/{tenant_id}/repositories/{repository_id}/files/{file_id}/content",
    )
    return response.content.decode("utf-8", errors="replace")


def fetch_repository_file_closure(
    client: RestClient,
    tenant_id: str,
    repository_id: str,
    file_id: str,
    *,
    source_path: str | None = None,
    files_by_path: Mapping[str, Mapping[str, Any]] | None = None,
) -> RepositoryFileClosureResponse:
    """Resolve the ``$ref`` closure for one repository file via REST."""
    if source_path is None:
        file_row = client.get(
            f"/tenants/{tenant_id}/repositories/{repository_id}/files/{file_id}",
        ).json()
        if not isinstance(file_row, dict):
            msg = "Unexpected repository file response."
            raise typer.BadParameter(msg)
        path_value = file_row.get("path")
        if not isinstance(path_value, str) or not path_value:
            msg = "Repository file response is missing path."
            raise typer.BadParameter(msg)
        source_path = path_value

    content = fetch_repository_file_content(
        client,
        tenant_id,
        repository_id,
        file_id,
    )
    if files_by_path is None:
        files_by_path = fetch_repository_files_by_path(client, tenant_id, repository_id)

    return build_repository_file_closure(
        source_path=source_path,
        content=content,
        files_by_path=files_by_path,
    )


def format_closure_indicator(closure: RepositoryFileClosureResponse) -> str:
    """Format a compact closure summary for file list tables."""
    if closure["total"] == 0:
        return "—"
    if closure["missing_count"] == 0:
        return f"{closure['resolved_count']} resolved"
    if closure["resolved_count"] == 0:
        return f"{closure['missing_count']} missing"
    return f"{closure['resolved_count']} resolved, {closure['missing_count']} missing"


def truncate_blob_sha(sha: str | None, *, length: int = 7) -> str:
    """Return a short blob SHA prefix for human-readable closure rows."""
    if not sha:
        return ""
    trimmed = sha.strip()
    return trimmed if len(trimmed) <= length else trimmed[:length]


def emit_repository_file_closure_result(
    closure: RepositoryFileClosureResponse,
    *,
    json_mode: bool,
) -> None:
    """Print resolved and missing closure members."""
    if json_mode:
        emit_json(closure)
        return

    typer.echo("")
    typer.echo("$ref closure")
    typer.echo(f"  Entrypoint: {closure['entrypoint']}")

    if closure["total"] == 0:
        typer.echo("  No external file references found.")
        return

    typer.echo(
        f"  Summary: {closure['resolved_count']} resolved, "
        f"{closure['missing_count']} missing"
    )
    typer.echo("  Members:")
    for member in closure["members"]:
        status = member["status"]
        sha = truncate_blob_sha(member["blob_sha"])
        sha_suffix = f" ({sha})" if sha else ""
        typer.echo(f"    - [{status}] {member['path']}{sha_suffix}")


def attach_closure_indicators(
    client: RestClient,
    tenant_id: str,
    repository_id: str,
    items: Sequence[dict[str, Any]],
    *,
    files_by_path: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Attach closure summaries to repository file list rows."""
    if files_by_path is None:
        files_by_path = fetch_repository_files_by_path(client, tenant_id, repository_id)

    enriched: list[dict[str, Any]] = []
    for item in items:
        row = dict(item)
        file_id = row.get("id")
        source_path = row.get("path")
        if not isinstance(file_id, str) or not isinstance(source_path, str):
            row["closure"] = None
            enriched.append(row)
            continue

        content = fetch_repository_file_content(
            client,
            tenant_id,
            repository_id,
            file_id,
        )
        closure = build_repository_file_closure(
            source_path=source_path,
            content=content,
            files_by_path=files_by_path,
        )
        row["closure"] = closure
        row["closure_indicator"] = format_closure_indicator(closure)
        enriched.append(row)

    return enriched
