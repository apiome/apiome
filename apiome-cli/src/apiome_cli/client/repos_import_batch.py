"""Helpers for ``apiome repos import --files`` batch imports."""

from __future__ import annotations

import fnmatch
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import typer

from apiome_cli.client.repos_files import validate_file_list_filters
from apiome_cli.client.repos_import import (
    build_repository_file_import_body,
    validate_import_mode,
)
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.import_.yaml_load import safe_load_mapping
from apiome_cli.output import emit_json

_RESERVED_MAP_KEYS = frozenset({"items", "default"})
_VALID_MAPPINGS = frozenset(
    {
        "new_project",
        "existing_version",
        "existing_project_new_version",
    },
)


def validate_batch_selection_mode(
    *,
    file_id: str | None,
    files_glob: str | None,
    files_regex: str | None,
    resume_run_id: str | None,
    manifest: str | None = None,
    manifest_file: str | None = None,
) -> str:
    """
    Validate single-file vs batch import invocation modes.

    Returns ``"single"``, ``"batch"``, ``"resume"``, ``"manifest"``, or
    ``"manifest_local"``.
    """
    manifest_set = manifest is not None or (
        manifest_file is not None and manifest_file.strip() != ""
    )
    resume_value = (
        resume_run_id.strip() if resume_run_id and resume_run_id.strip() else None
    )

    if manifest_set:
        if file_id is not None and file_id.strip():
            typer.echo(
                "Use --manifest or --manifest-file without a file id.",
                err=True,
            )
            raise typer.Exit(EXIT_USAGE)
        if files_glob is not None and files_glob.strip():
            typer.echo(
                "Use --manifest or --manifest-file without --files.",
                err=True,
            )
            raise typer.Exit(EXIT_USAGE)
        if files_regex is not None and files_regex.strip():
            typer.echo(
                "Use --manifest or --manifest-file without --regex.",
                err=True,
            )
            raise typer.Exit(EXIT_USAGE)
        if manifest_file is not None and manifest_file.strip() and resume_value is not None:
            typer.echo(
                "--resume-run-id applies only to the repository manifest, not --manifest-file.",
                err=True,
            )
            raise typer.Exit(EXIT_USAGE)
        if resume_value is not None:
            return "manifest"
        if manifest == "manifest":
            return "manifest"
        if manifest_file is not None and manifest_file.strip():
            return "manifest_local"
        typer.echo(
            "Use --manifest for the repository manifest or --manifest-file PATH for a local file.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    file_value = file_id.strip() if file_id and file_id.strip() else None
    glob_value = files_glob.strip() if files_glob and files_glob.strip() else None
    regex_value = files_regex.strip() if files_regex and files_regex.strip() else None

    if resume_value is not None:
        if file_value is not None or glob_value is not None or regex_value is not None:
            typer.echo(
                "Use --resume-run-id alone, without a file id or --files/--regex.",
                err=True,
            )
            raise typer.Exit(EXIT_USAGE)
        return "resume"

    batch_set = glob_value is not None or regex_value is not None
    if batch_set and file_value is not None:
        typer.echo(
            "Use either a single file id or --files/--regex for batch import, not both.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    if batch_set:
        validate_file_list_filters(glob=glob_value, regex=regex_value)
        return "batch"

    if file_value is None:
        typer.echo(
            "Import a repository file by id, pass --files/--regex for batch import, "
            "or use --manifest for manifest-driven import.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    return "single"


def load_repository_import_map(path: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    """
    Load a YAML or JSON import map from *path*.

    Returns ``(path_entries, default_entry)`` where keys in *path_entries* are
    repository-relative paths or glob patterns.
    """
    map_path = Path(path).expanduser()
    if not map_path.is_file():
        msg = f"Import map file not found: {map_path}"
        raise typer.BadParameter(msg)

    text = map_path.read_text(encoding="utf-8")
    suffix = map_path.suffix.lower()
    if suffix == ".json":
        data = json.loads(text)
        if not isinstance(data, dict):
            msg = "Import map JSON must be a top-level object."
            raise typer.BadParameter(msg)
    else:
        try:
            data = safe_load_mapping(text)
        except ValueError as exc:
            msg = f"Import map YAML must be a top-level mapping: {exc}"
            raise typer.BadParameter(msg) from exc

    default_entry: dict[str, Any] | None = None
    if isinstance(data.get("default"), dict):
        default_entry = dict(data["default"])

    entries: dict[str, dict[str, Any]] = {}
    items = data.get("items")
    if isinstance(items, list):
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                msg = f"Import map items[{index}] must be an object."
                raise typer.BadParameter(msg)
            path_value = item.get("path")
            if not isinstance(path_value, str) or not path_value.strip():
                msg = f"Import map items[{index}] requires a non-empty path."
                raise typer.BadParameter(msg)
            entries[path_value.strip()] = dict(item)
    else:
        for key, value in data.items():
            if key in _RESERVED_MAP_KEYS:
                continue
            if not isinstance(value, dict):
                msg = f"Import map entry {key!r} must be an object."
                raise typer.BadParameter(msg)
            entries[str(key)] = dict(value)

    if not entries and default_entry is None:
        msg = "Import map must define items, path entries, or a default mapping."
        raise typer.BadParameter(msg)

    return entries, default_entry


def _normalize_map_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one map entry and return REST batch item fields (without file_id)."""
    mapping_value = entry.get("mapping")
    if not isinstance(mapping_value, str) or not mapping_value.strip():
        msg = "Each import map entry requires mapping."
        raise typer.BadParameter(msg)

    mapping = mapping_value.strip()
    if mapping not in _VALID_MAPPINGS:
        allowed = ", ".join(sorted(_VALID_MAPPINGS))
        msg = f"Import map mapping must be one of: {allowed}."
        raise typer.BadParameter(msg)

    new_project = mapping == "new_project"
    project_id = entry.get("project_id")
    version_id = entry.get("version_id")
    version_name = entry.get("version_name")

    project_text = (
        project_id.strip()
        if isinstance(project_id, str) and project_id.strip()
        else None
    )
    version_id_text = (
        version_id.strip()
        if isinstance(version_id, str) and version_id.strip()
        else None
    )
    version_name_text = (
        version_name.strip()
        if isinstance(version_name, str) and version_name.strip()
        else None
    )

    validate_import_mode(
        new_project=new_project,
        project_id=project_text,
        version_id=version_id_text,
        version_name=version_name_text,
    )

    body = build_repository_file_import_body(
        mapping=mapping,
        project_id=project_text,
        version_id=version_id_text,
        version_name=version_name_text,
        dry_run=False,
    )
    body.pop("dry_run", None)
    return body


def resolve_mapping_for_path(
    path: str,
    *,
    map_entries: Mapping[str, Mapping[str, Any]],
    default_entry: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return the REST batch item body (without file_id) for *path*."""
    exact = map_entries.get(path)
    if exact is not None:
        return _normalize_map_entry(exact)

    pattern_matches = [
        entry
        for pattern, entry in map_entries.items()
        if pattern != path and fnmatch.fnmatch(path, pattern)
    ]
    if len(pattern_matches) == 1:
        return _normalize_map_entry(pattern_matches[0])
    if len(pattern_matches) > 1:
        msg = f"Import map matches multiple patterns for path {path!r}."
        raise typer.BadParameter(msg)

    if default_entry is not None:
        return _normalize_map_entry(default_entry)

    msg = f"No import map entry matches repository path {path!r}."
    raise typer.BadParameter(msg)


def build_global_batch_item_template(
    *,
    new_project: bool,
    project_id: str | None,
    version_id: str | None,
    version_name: str | None,
) -> dict[str, Any]:
    """Build one REST batch item template from CLI mapping flags."""
    mapping = validate_import_mode(
        new_project=new_project,
        project_id=project_id,
        version_id=version_id,
        version_name=version_name,
    )
    body = build_repository_file_import_body(
        mapping=mapping,
        project_id=project_id,
        version_id=version_id,
        version_name=version_name,
        dry_run=False,
    )
    body.pop("dry_run", None)
    return body


def build_batch_import_items(
    files: Sequence[Mapping[str, Any]],
    *,
    map_entries: Mapping[str, Mapping[str, Any]] | None,
    default_entry: Mapping[str, Any] | None,
    global_template: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """
    Build ``POST …/imports:batch`` item payloads from selected repository files.

    Each item includes ``file_id`` plus mapping fields. When *map_entries* is
    omitted, *global_template* is applied to every file.
    """
    if not files:
        typer.echo("No repository files matched the selection.", err=True)
        raise typer.Exit(EXIT_USAGE)

    items: list[dict[str, Any]] = []
    for file_row in files:
        file_uuid = file_row.get("id")
        path_value = file_row.get("path")
        if not isinstance(file_uuid, str) or not file_uuid:
            msg = "Repository file row is missing id."
            raise typer.BadParameter(msg)
        if not isinstance(path_value, str) or not path_value.strip():
            msg = f"Repository file {file_uuid} is missing path."
            raise typer.BadParameter(msg)

        if map_entries is not None:
            template = resolve_mapping_for_path(
                path_value.strip(),
                map_entries=map_entries,
                default_entry=default_entry,
            )
        elif global_template is not None:
            template = dict(global_template)
        else:
            typer.echo(
                "Batch import requires --map or import target flags "
                "(--new-project / --project …).",
                err=True,
            )
            raise typer.Exit(EXIT_USAGE)

        items.append({"file_id": file_uuid, **template})

    return items


def build_batch_import_request_body(
    *,
    items: list[dict[str, Any]] | None,
    dry_run: bool,
    resume_run_id: str | None,
) -> dict[str, Any]:
    """Build the REST payload for ``POST …/imports:batch``."""
    body: dict[str, Any] = {"dry_run": dry_run}
    resume_value = (
        resume_run_id.strip() if resume_run_id and resume_run_id.strip() else None
    )
    if resume_value is not None:
        body["resume_run_id"] = resume_value
        return body

    if not items:
        msg = "Batch import requires at least one mapped file."
        raise typer.BadParameter(msg)

    body["items"] = items
    return body


def batch_import_has_failures(result: Mapping[str, Any]) -> bool:
    """Return True when the batch result reports failed or skipped files."""
    counts = result.get("counts")
    if isinstance(counts, dict):
        failed = counts.get("failed")
        if isinstance(failed, int) and failed > 0:
            return True
        skipped = counts.get("skipped")
        if isinstance(skipped, int) and skipped > 0:
            return True

    status = result.get("status")
    return status in {"failed", "partial"}


def _format_batch_item_line(
    item: Mapping[str, Any],
    *,
    path_by_file_id: Mapping[str, str],
) -> str:
    file_uuid = item.get("file_id")
    path_label = path_by_file_id.get(str(file_uuid or ""), str(file_uuid or ""))
    status = str(item.get("status") or "unknown")

    if status == "succeeded":
        import_result = item.get("result")
        if isinstance(import_result, dict):
            project = import_result.get("project")
            version = import_result.get("version")
            project_name = ""
            version_label = ""
            if isinstance(project, dict) and isinstance(project.get("name"), str):
                project_name = project["name"]
            if isinstance(version, dict) and isinstance(version.get("version"), str):
                version_label = version["version"]
            target = f"{project_name} / {version_label}".strip(" /")
            if target:
                return f"[succeeded] {path_label} → {target}"
        return f"[succeeded] {path_label}"

    failure = item.get("failure")
    if isinstance(failure, dict) and isinstance(failure.get("message"), str):
        return f"[{status}] {path_label} — {failure['message']}"

    return f"[{status}] {path_label}"


def emit_batch_import_result(
    result: Mapping[str, Any],
    *,
    json_mode: bool,
    dry_run: bool,
    path_by_file_id: Mapping[str, str] | None = None,
) -> None:
    """Print a batch import summary to stdout (human table or raw JSON)."""
    if json_mode:
        emit_json(dict(result))
        return

    lookup = path_by_file_id or {}
    counts = result.get("counts")
    run_id = result.get("run_id", "")
    status = result.get("status", "")

    if dry_run:
        typer.echo("Batch dry run completed (no changes written).")
    else:
        typer.echo("Batch import completed.")
    typer.echo(f"  Run: {run_id}")
    typer.echo(f"  Status: {status}")

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
                typer.echo(f"  {_format_batch_item_line(item, path_by_file_id=lookup)}")
