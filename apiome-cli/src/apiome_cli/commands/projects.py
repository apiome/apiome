"""Projects list, get and update commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import typer

from apiome_cli.cli_context import insecure_from_context, settings_from_context, timeout_from_context
from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.client.errors import exit_on_api_error
from apiome_cli.client.list_response import fetch_list
from apiome_cli.client.project_version_resolve import resolve_project_uuid
from apiome_cli.client.tenant_scope import require_tenant_slug
from apiome_cli.config import require_api_key
from apiome_cli.exit_codes import EXIT_UPDATE_CONFLICT, EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import (
    ListColumn,
    RecordField,
    emit_json,
    emit_list_table,
    emit_record_response,
    json_mode_from_context,
)
from apiome_cli.project_update import (
    PROJECT_DOMAIN_CHOICES,
    PROJECT_DOMAIN_NONE,
    ProjectUpdateError,
    changes_from_file,
    changes_from_flags,
    expected_updated_at,
    field_changes,
    render_diff,
    request_body,
)
from apiome_cli.terminal import confirm_action, echo_notice

app = typer.Typer(
    name="projects",
    help="List, fetch and update tenant projects.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def projects_group(ctx: typer.Context) -> None:
    """Projects command group."""
    group_callback_without_subcommand(ctx)

_PROJECT_LIST_COLUMNS: tuple[ListColumn, ...] = (
    ("ID", "id", None),
    ("Name", "name", None),
    ("Slug", "slug", None),
    ("Source", "source", None),
    ("Enabled", "enabled", lambda value: "" if value is None else str(value)),
)

_PROJECT_RECORD_FIELDS: tuple[RecordField, ...] = (
    ("ID", "id", None),
    ("Tenant", "tenant_id", None),
    ("Name", "name", None),
    ("Slug", "slug", None),
    ("Source", "source", None),
    ("Enabled", "enabled", lambda value: "" if value is None else str(value)),
)


@app.command("list")
def list_projects(ctx: typer.Context) -> None:
    """List projects (GET /v1/projects/{tenant_slug})."""
    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
    )
    tenant_slug = require_tenant_slug(settings, client)
    items, total = fetch_list(client, api_paths.projects(tenant_slug))
    if json_mode_from_context(ctx):
        emit_json({"total": total, "items": items})
    else:
        emit_list_table(items, _PROJECT_LIST_COLUMNS, total=total)


@app.command("get")
def get_project(
    ctx: typer.Context,
    project_id: UUID = typer.Argument(..., help="Project UUID."),
) -> None:
    """Fetch one project by id (GET /v1/projects/{tenant_slug}/{project_id})."""
    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
    )
    tenant_slug = require_tenant_slug(settings, client)
    response = client.get(api_paths.project(tenant_slug, project_id))
    emit_record_response(
        response.json(),
        _PROJECT_RECORD_FIELDS,
        json_mode=json_mode_from_context(ctx),
    )


def _read_dump(path: Path) -> dict[str, Any]:
    """Read an edited ``projects get --json`` dump, or exit 2 saying why it cannot be used."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        typer.echo(f"Cannot read {path}: {exc.strerror or exc}.", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    except json.JSONDecodeError as exc:
        typer.echo(f"{path} is not valid JSON: {exc.msg} (line {exc.lineno}).", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    if not isinstance(document, dict):
        typer.echo(f"{path} must hold one project object.", err=True)
        raise typer.Exit(EXIT_USAGE)
    return document


def _exit_on_conflict(response: Any, *, ref: str, from_file: Optional[Path]) -> None:
    """Exit 6 with a re-fetch hint when the server reports an ``update_conflict``."""
    if response.status_code != 409:
        return
    try:
        detail = response.json().get("detail")
    except ValueError:
        return
    if not isinstance(detail, dict) or detail.get("code") != "update_conflict":
        return  # e.g. a slug already taken: the shared 4xx mapping says so.
    source = f"{from_file} was read" if from_file else "it was read"
    current = detail.get("current_updated_at") or "unknown"
    typer.echo(
        f"Conflict: project {ref!r} changed since {source} (server updated_at {current}). "
        f"Nothing was written.\n"
        f"Re-fetch it with `apiome projects get <id> --json > project.json`, re-apply your "
        f"edit, and run the update again.",
        err=True,
    )
    raise typer.Exit(EXIT_UPDATE_CONFLICT)


@app.command("update")
def update_project(
    ctx: typer.Context,
    project_ref: str = typer.Argument(..., help="Project slug or UUID."),
    name: Optional[str] = typer.Option(None, "--name", help="New display name."),
    rename: Optional[str] = typer.Option(
        None,
        "--rename",
        help="New slug. Asks for confirmation (or --yes): links using the old slug stop working.",
    ),
    description: Optional[str] = typer.Option(
        None, "--description", help="New description; an empty string clears it."
    ),
    domain: Optional[str] = typer.Option(
        None,
        "--domain",
        help=f"Domain category: {', '.join(PROJECT_DOMAIN_CHOICES)}, or {PROJECT_DOMAIN_NONE}.",
    ),
    from_file: Optional[Path] = typer.Option(
        None,
        "--from-file",
        help="Apply an edited `projects get --json` dump; fails (exit 6) if the project "
        "changed since the dump.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the --rename confirmation."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the changes as a diff without sending them."
    ),
) -> None:
    """Update a project's name, slug, description or domain (PUT /v1/projects/{tenant}/{id}).

    Only the fields that change are sent. Every update carries the project's ``updated_at``
    as a precondition — the dump's for ``--from-file``, otherwise the one read just before the
    write — so a concurrent edit is never overwritten: the command exits 6 instead.
    """
    flags_given = any(value is not None for value in (name, rename, description, domain))
    if from_file is not None and flags_given:
        typer.echo("--from-file cannot be combined with field flags.", err=True)
        raise typer.Exit(EXIT_USAGE)
    if from_file is None and not flags_given:
        typer.echo(
            "Nothing to update: pass --name, --rename, --description, --domain or --from-file.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
    )
    tenant_slug = require_tenant_slug(settings, client)
    project_id = resolve_project_uuid(client, tenant_slug, project_ref)
    project = client.get(api_paths.project(tenant_slug, project_id)).json()

    try:
        if from_file is not None:
            document = _read_dump(from_file)
            changes = changes_from_file(project, document)
            precondition = expected_updated_at(document)
        else:
            changes = changes_from_flags(
                project, name=name, rename=rename, description=description, domain=domain
            )
            precondition = project.get("updated_at")
    except ProjectUpdateError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc

    json_mode = json_mode_from_context(ctx)
    if dry_run:
        if json_mode:
            emit_json(
                {
                    "dryRun": True,
                    "projectId": str(project_id),
                    "changes": [
                        {"field": row.field, "before": row.before, "after": row.after}
                        for row in field_changes(project, changes)
                    ],
                    "request": request_body(changes, precondition),
                }
            )
        else:
            typer.echo(render_diff(project, changes))
        return

    if not changes:
        echo_notice(f"Project {project.get('slug')!r} already matches; nothing to update.")
        if json_mode:
            emit_json(project)
        return

    if "slug" in changes:
        confirm_action(
            f"This will change the project slug from {project.get('slug')!r} to "
            f"{changes['slug']!r}.\n"
            f"Links, scripts and CLI commands that use {project.get('slug')!r} will stop "
            "working; there is no redirect from the old slug.\nContinue?",
            skip=yes,
        )

    response = client.put_raw(
        api_paths.project(tenant_slug, project_id), json=request_body(changes, precondition)
    )
    _exit_on_conflict(response, ref=project_ref, from_file=from_file)
    exit_on_api_error(response)
    updated = response.json()
    if json_mode:
        emit_json(updated)
        return
    fields = ", ".join(row.field for row in field_changes(project, changes))
    typer.echo(f"Updated project {updated.get('slug')!r}: {fields}.")
