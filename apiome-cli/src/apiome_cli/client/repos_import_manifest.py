"""Helpers for ``apiome repos import --manifest``."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

import typer
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from apiome_cli.client.http import RestClient
from apiome_cli.client.pagination import DEFAULT_PAGE_LIMIT, paginate_list
from apiome_cli.client.repos_import_batch import batch_import_has_failures
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.extract.slug import slugify_version
from apiome_cli.import_.yaml_load import safe_load_mapping
from apiome_cli.output import emit_json

_REQUIRED_PROPERTY_RE = re.compile(r"^'([^']+)' is a required property$")
_ADDITIONAL_PROPERTY_RE = re.compile(
    r"^Additional properties are not allowed \('([^']+)' was unexpected\)$"
)


def validate_manifest_import_flags(
    *,
    selection_mode: str,
    map_file: str | None,
    new_project: bool,
    project_id: str | None,
    version_id: str | None,
    version_name: str | None,
) -> None:
    """Reject mapping flags that conflict with manifest-driven import."""
    if selection_mode not in {"manifest", "manifest_local"}:
        return

    conflicts = [
        map_file is not None and map_file.strip(),
        new_project,
        project_id is not None and project_id.strip(),
        version_id is not None and version_id.strip(),
        version_name is not None and version_name.strip(),
    ]
    if any(conflicts):
        typer.echo(
            "Manifest import does not accept --map, --new-project, --project, "
            "--version-id, or --version-name.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)


def build_repo_manifest_import_request_body(
    *,
    dry_run: bool,
    resume_run_id: str | None,
) -> dict[str, object]:
    """Build the REST payload for ``POST …/imports:manifest``."""
    body: dict[str, object] = {"dry_run": dry_run}
    resume_value = (
        resume_run_id.strip() if resume_run_id and resume_run_id.strip() else None
    )
    if resume_value is not None:
        body["resume_run_id"] = resume_value
    return body


def _escape_json_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _pointer_from_absolute_path(path: Sequence[Any]) -> str:
    if not path:
        return "/"
    return "/" + "/".join(_escape_json_pointer_token(str(segment)) for segment in path)


def _pointer_from_validation_error(error: JsonSchemaValidationError) -> str:
    required_match = _REQUIRED_PROPERTY_RE.match(error.message)
    if required_match is not None:
        missing_property = required_match.group(1)
        if error.absolute_path:
            base = _pointer_from_absolute_path(error.absolute_path)
            if base == "/":
                return f"/{missing_property}"
            return f"{base}/{missing_property}"
        return f"/{missing_property}"

    if error.absolute_path:
        return _pointer_from_absolute_path(error.absolute_path)

    additional_match = _ADDITIONAL_PROPERTY_RE.match(error.message)
    if additional_match is not None:
        return f"/{additional_match.group(1)}"

    return "/"


@lru_cache(maxsize=1)
def _repository_import_manifest_schema() -> dict[str, Any]:
    schema_path = (
        resources.files("apiome_cli.import_.schemas.repository_import_manifest")
        .joinpath("1.0", "schema.json")
    )
    with schema_path.open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        msg = "Vendored repository import manifest schema must be a JSON object."
        raise typer.BadParameter(msg)
    return loaded


@lru_cache(maxsize=1)
def _repository_import_manifest_validator() -> Draft202012Validator:
    return Draft202012Validator(_repository_import_manifest_schema())


def _collect_manifest_validation_errors(
    document: Mapping[str, Any],
) -> list[tuple[str, str]]:
    validator = _repository_import_manifest_validator()
    findings: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for error in validator.iter_errors(document):
        pointer = _pointer_from_validation_error(error)
        message = error.message.strip()
        key = (pointer, message)
        if key in seen:
            continue
        seen.add(key)
        findings.append((pointer, message))
    findings.sort(key=lambda item: (-item[0].count("/"), item[0], item[1]))
    return findings


def load_local_repository_import_manifest(path: str) -> dict[str, Any]:
    """
    Load and validate a local ``.apiome.yaml`` or ``.apiome.json`` file.

    Returns the validated manifest document.

    Raises:
        typer.BadParameter: When the file is missing, unreadable, or invalid.
    """
    manifest_path = Path(path).expanduser()
    if not manifest_path.is_file():
        msg = f"Manifest file not found: {manifest_path}"
        raise typer.BadParameter(msg)

    text = manifest_path.read_text(encoding="utf-8")
    suffix = manifest_path.suffix.lower()
    if suffix == ".json":
        data = json.loads(text)
        if not isinstance(data, dict):
            msg = "Manifest JSON must be a top-level object."
            raise typer.BadParameter(msg)
    else:
        try:
            data = safe_load_mapping(text)
        except ValueError as exc:
            msg = f"Manifest YAML must be a top-level mapping: {exc}"
            raise typer.BadParameter(msg) from exc

    errors = _collect_manifest_validation_errors(data)
    if errors:
        pointer, message = errors[0]
        msg = f"At {pointer}: {message}"
        raise typer.BadParameter(msg)
    return data


def _glob_segment_to_regex(segment: str) -> str:
    parts: list[str] = []
    index = 0
    length = len(segment)
    while index < length:
        char = segment[index]
        if char == "*":
            if index + 1 < length and segment[index + 1] == "*":
                if index + 2 < length and segment[index + 2] == "/":
                    parts.append("(?:.*/)?")
                    index += 3
                    continue
                parts.append(".*")
                index += 2
                continue
            parts.append("[^/]*")
            index += 1
            continue
        if char == "?":
            parts.append("[^/]")
            index += 1
            continue
        parts.append(re.escape(char))
        index += 1
    return "".join(parts)


def _glob_pattern_to_regex(pattern: str) -> str:
    trimmed = pattern.strip()
    if not trimmed:
        msg = "Manifest path pattern must not be empty."
        raise typer.BadParameter(msg)
    return f"^{_glob_segment_to_regex(trimmed)}$"


def _path_matches_glob(*, pattern: str, path: str) -> bool:
    return re.match(_glob_pattern_to_regex(pattern), path) is not None


def _matched_repository_files(
    *,
    pattern: str,
    files: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    matched = [
        row
        for row in files
        if isinstance(row.get("path"), str)
        and _path_matches_glob(pattern=pattern, path=row["path"])
    ]
    matched.sort(key=lambda row: str(row.get("path", "")))
    return matched


def _load_project_catalog(
    client: RestClient,
) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """
    Return project slug → id and (project_id, version_slug) → version_id maps.
    """
    projects, _total = paginate_list(client, "/projects", limit=DEFAULT_PAGE_LIMIT, fetch_all=True)
    project_by_slug: dict[str, str] = {}
    for row in projects:
        slug = row.get("slug")
        project_id = row.get("id")
        if isinstance(slug, str) and isinstance(project_id, str):
            project_by_slug[slug] = project_id

    version_by_project_and_slug: dict[tuple[str, str], str] = {}
    versions, _total = paginate_list(
        client,
        "/project-versions",
        limit=DEFAULT_PAGE_LIMIT,
        fetch_all=True,
    )
    for row in versions:
        project_id = row.get("project_id")
        version_slug = row.get("slug")
        version_id = row.get("id")
        if (
            isinstance(project_id, str)
            and isinstance(version_slug, str)
            and isinstance(version_id, str)
        ):
            version_by_project_and_slug[(project_id, version_slug)] = version_id
    return project_by_slug, version_by_project_and_slug


def build_local_manifest_batch_items(
    client: RestClient,
    *,
    manifest: Mapping[str, Any],
    repository_files: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """
    Translate a validated local manifest into ``POST …/imports:batch`` items.

    Resolves existing project slugs via ``GET /projects`` and
    ``GET /project-versions``.
    """
    if not repository_files:
        typer.echo("No repository files are available to match against the manifest.", err=True)
        raise typer.Exit(EXIT_USAGE)

    imports = manifest.get("imports")
    if not isinstance(imports, list) or not imports:
        msg = "Manifest imports[] must be a non-empty array."
        raise typer.BadParameter(msg)

    project_by_slug, version_by_project_and_slug = _load_project_catalog(client)
    items: list[dict[str, Any]] = []
    seen_files: dict[str, int] = {}

    for index, entry in enumerate(imports):
        if not isinstance(entry, dict):
            msg = f"At /imports/{index}: entry must be an object."
            raise typer.BadParameter(msg)

        path_pattern = entry.get("path")
        version_name = entry.get("version")
        if not isinstance(path_pattern, str) or not path_pattern.strip():
            msg = f"At /imports/{index}/path: path is required."
            raise typer.BadParameter(msg)
        if not isinstance(version_name, str) or not version_name.strip():
            msg = f"At /imports/{index}/version: version is required."
            raise typer.BadParameter(msg)

        matched = _matched_repository_files(
            pattern=path_pattern.strip(),
            files=repository_files,
        )
        if not matched:
            typer.echo(
                f"Manifest entry /imports/{index} matched no repository files "
                f"for path {path_pattern!r}.",
                err=True,
            )
            raise typer.Exit(EXIT_USAGE)

        new_project = entry.get("newProject")
        project_slug = entry.get("project")

        for file_row in matched:
            file_uuid = file_row.get("id")
            if not isinstance(file_uuid, str) or not file_uuid:
                msg = "Repository file row is missing id."
                raise typer.BadParameter(msg)

            if file_uuid in seen_files:
                prior_index = seen_files[file_uuid]
                msg = (
                    f"File {file_row.get('path')!r} is matched by multiple manifest "
                    f"entries (indexes {prior_index} and {index})."
                )
                raise typer.BadParameter(msg)
            seen_files[file_uuid] = index

            if isinstance(new_project, dict):
                items.append(
                    {
                        "file_id": file_uuid,
                        "mapping": "new_project",
                        "version_name": version_name.strip(),
                    }
                )
                continue

            if not isinstance(project_slug, str) or not project_slug.strip():
                msg = f"At /imports/{index}: entry must declare project or newProject."
                raise typer.BadParameter(msg)

            project_id = project_by_slug.get(project_slug.strip())
            if project_id is None:
                msg = (
                    f"At /imports/{index}/project: project slug "
                    f"{project_slug!r} was not found in this tenant."
                )
                raise typer.BadParameter(msg)

            try:
                version_slug = slugify_version(version_name.strip())
            except ValueError as exc:
                msg = f"At /imports/{index}/version: {exc}"
                raise typer.BadParameter(msg) from exc

            version_id = version_by_project_and_slug.get((project_id, version_slug))
            if version_id is not None:
                items.append(
                    {
                        "file_id": file_uuid,
                        "mapping": "existing_version",
                        "project_id": project_id,
                        "version_id": version_id,
                    }
                )
            else:
                items.append(
                    {
                        "file_id": file_uuid,
                        "mapping": "existing_project_new_version",
                        "project_id": project_id,
                        "version_name": version_name.strip(),
                    }
                )

    if not items:
        typer.echo("Manifest matched no repository files to import.", err=True)
        raise typer.Exit(EXIT_USAGE)

    return items


def emit_manifest_import_result(
    result: Mapping[str, Any],
    *,
    json_mode: bool,
    dry_run: bool,
    path_by_file_id: Mapping[str, str] | None = None,
) -> None:
    """Print a manifest import summary to stdout (human table or raw JSON)."""
    if json_mode:
        emit_json(dict(result))
        return

    lookup = path_by_file_id or {}
    counts = result.get("counts")
    run_id = result.get("run_id", "")
    status = result.get("status", "")
    manifest = result.get("manifest")

    if dry_run:
        typer.echo("Manifest dry run completed (no changes written).")
    else:
        typer.echo("Manifest import completed.")
    typer.echo(f"  Run: {run_id}")
    typer.echo(f"  Status: {status}")

    if isinstance(manifest, dict):
        manifest_path = manifest.get("path", "")
        blob_sha = manifest.get("blob_sha", "")
        commit_sha = manifest.get("commit_sha", "")
        typer.echo(f"  Manifest: {manifest_path}")
        if blob_sha:
            typer.echo(f"  Blob SHA: {blob_sha}")
        if commit_sha:
            typer.echo(f"  Commit SHA: {commit_sha}")

    if isinstance(counts, dict):
        typer.echo(
            "  Total: {total} · Succeeded: {succeeded} · Failed: {failed} · Skipped: {skipped}".format(
                total=counts.get("total", 0),
                succeeded=counts.get("succeeded", 0),
                failed=counts.get("failed", 0),
                skipped=counts.get("skipped", 0),
            ),
        )

    items = result.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                from apiome_cli.client.repos_import_batch import _format_batch_item_line

                typer.echo(f"  {_format_batch_item_line(item, path_by_file_id=lookup)}")


__all__ = [
    "batch_import_has_failures",
    "build_local_manifest_batch_items",
    "build_repo_manifest_import_request_body",
    "emit_manifest_import_result",
    "load_local_repository_import_manifest",
    "validate_manifest_import_flags",
]
