"""Helpers for ``apiome repos import``."""

from __future__ import annotations

from typing import Any

import typer

from apiome_cli.exit_codes import EXIT_USAGE

_MAPPING_NEW_PROJECT = "new_project"
_MAPPING_EXISTING_VERSION = "existing_version"
_MAPPING_EXISTING_PROJECT_NEW_VERSION = "existing_project_new_version"


def validate_import_mode(
    *,
    new_project: bool,
    project_id: str | None,
    version_id: str | None,
    version_name: str | None,
) -> str:
    """
    Validate mutually exclusive repository import mapping modes.

    Returns the REST ``mapping`` value when valid.
    """
    project_value = project_id.strip() if project_id and project_id.strip() else None
    version_id_value = version_id.strip() if version_id and version_id.strip() else None
    version_name_value = (
        version_name.strip() if version_name and version_name.strip() else None
    )

    if new_project and project_value is not None:
        typer.echo(
            "Use either --new-project or --project, not both.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    if version_id_value is not None and version_name_value is not None:
        typer.echo(
            "Use either --version-id for an existing version or --version-name "
            "to create a new version, not both.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    if new_project:
        if version_id_value is not None:
            typer.echo(
                "--version-id cannot be used with --new-project.",
                err=True,
            )
            raise typer.Exit(EXIT_USAGE)
        return _MAPPING_NEW_PROJECT

    if project_value is None:
        typer.echo(
            "Import a repository file with --new-project or --project ID "
            "and either --version-id ID or --version-name NAME.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    if version_id_value is not None:
        return _MAPPING_EXISTING_VERSION

    if version_name_value is not None:
        return _MAPPING_EXISTING_PROJECT_NEW_VERSION

    typer.echo(
        "When --project is set, provide --version-id for an existing version "
        "or --version-name to create a new version under that project.",
        err=True,
    )
    raise typer.Exit(EXIT_USAGE)


def build_repository_file_import_body(
    *,
    mapping: str,
    project_id: str | None,
    version_id: str | None,
    version_name: str | None,
    dry_run: bool,
) -> dict[str, Any]:
    """Build the REST payload for ``POST …/files/{file_id}/import``."""
    body: dict[str, Any] = {
        "mapping": mapping,
        "dry_run": dry_run,
    }

    project_value = project_id.strip() if project_id and project_id.strip() else None
    version_id_value = version_id.strip() if version_id and version_id.strip() else None
    version_name_value = (
        version_name.strip() if version_name and version_name.strip() else None
    )

    if mapping == _MAPPING_NEW_PROJECT:
        if version_name_value is not None:
            body["version_name"] = version_name_value
        return body

    if project_value is None:
        msg = "project_id is required for this import mapping."
        raise typer.BadParameter(msg)

    body["project_id"] = project_value

    if mapping == _MAPPING_EXISTING_VERSION:
        if version_id_value is None:
            msg = "version_id is required for existing_version imports."
            raise typer.BadParameter(msg)
        body["version_id"] = version_id_value
        return body

    if mapping == _MAPPING_EXISTING_PROJECT_NEW_VERSION:
        if version_name_value is not None:
            body["version_name"] = version_name_value
        return body

    msg = f"Unsupported import mapping: {mapping!r}."
    raise typer.BadParameter(msg)


def resolve_repository_file_path_label(
    client: Any,
    *,
    tenant_id: str,
    repository_id: str,
    file_id: str,
) -> str:
    """Return the repository-relative path for *file_id*, or the UUID on lookup failure."""
    file_row = client.get(
        f"/tenants/{tenant_id}/repositories/{repository_id}/files/{file_id}",
    ).json()
    if isinstance(file_row, dict):
        path = file_row.get("path")
        if isinstance(path, str) and path.strip():
            return path.strip()
    return file_id


def format_repository_file_import_progress(
    *,
    file_label: str,
    dry_run: bool,
) -> str:
    """Build a one-line stderr message before importing a repository file."""
    if dry_run:
        return f"Planning repository file import of {file_label} (dry run)…"
    return f"Importing repository file {file_label}…"
