"""Projects list and get commands (read-only)."""

from __future__ import annotations

from uuid import UUID

import typer

from apiome_cli.cli_context import insecure_from_context, settings_from_context, timeout_from_context
from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.client.list_response import fetch_list
from apiome_cli.client.tenant_scope import require_tenant_slug
from apiome_cli.config import require_api_key
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import (
    ListColumn,
    RecordField,
    emit_json,
    emit_list_table,
    emit_record_response,
    json_mode_from_context,
)

app = typer.Typer(
    name="projects",
    help="List and fetch tenant projects.",
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
