"""Properties list and get commands (read-only)."""

from __future__ import annotations

import json
from typing import Optional
from uuid import UUID

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.list_response import fetch_list
from apiome_cli.client.pagination import DEFAULT_PAGE_LIMIT
from apiome_cli.client.project_version_resolve import resolve_project_uuid
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import (
    RecordField,
    emit_json,
    emit_record_response,
    json_mode_from_context,
)
from apiome_cli.property_view import UsageUnavailable, filter_properties, render_table

app = typer.Typer(
    name="properties",
    help="List and fetch project properties.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def properties_group(ctx: typer.Context) -> None:
    """Properties command group."""
    group_callback_without_subcommand(ctx)


def _sorted_json_value(value: object) -> object:
    """Recursively sort dictionary keys for stable JSON output."""
    if isinstance(value, dict):
        return {key: _sorted_json_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sorted_json_value(item) for item in value]
    return value


def _format_value_as_json(value: object) -> str:
    """Format a table value as compact JSON."""
    if value is None:
        return ""
    return json.dumps(_sorted_json_value(value), separators=(",", ":"))


_PROPERTY_RECORD_FIELDS: tuple[RecordField, ...] = (
    ("ID", "id", None),
    ("Tenant", "tenant_id", None),
    ("Name", "name", None),
    ("Description", "description", None),
    ("Body", "body", _format_value_as_json),
    ("Enabled", "enabled", lambda value: "" if value is None else str(value)),
    ("Created On", "created_on", None),
    ("Updated On", "updated_on", None),
)


@app.command("list")
def list_properties(
    ctx: typer.Context,
    project_ref: Optional[str] = typer.Argument(
        None, metavar="PROJECT", help="Project slug or UUID (or pass --project-id)."
    ),
    project_id: Optional[UUID] = typer.Option(None, "--project-id", help="Project UUID (the older form)."),
    type_filter: Optional[str] = typer.Option(
        None,
        "--type",
        "--primitive",
        help="Only properties of this schema type, e.g. string, uuid, date-time, array<string>.",
    ),
    search: Optional[str] = typer.Option(None, "--search", help="Case-insensitive text in the name or description."),
    unused: bool = typer.Option(False, "--unused", help="Only properties no class uses."),
    limit: int = typer.Option(DEFAULT_PAGE_LIMIT, "--limit", min=1, help="Show at most this many."),
    all_rows: bool = typer.Option(False, "--all", help="Show every match (ignores --limit)."),
) -> None:
    """List a project's properties with their type and the classes that use them (GET /v1/properties/{tenant}/{project}).

    Properties have no tags and are not bound to primitives, so the TYPE column is read from each
    property's JSON Schema (its format, else its type).
    """
    if project_ref is None and project_id is None:
        typer.echo("Name the project: apiome properties list <project>.", err=True)
        raise typer.Exit(EXIT_USAGE)
    client, tenant_slug = tenant_scoped_client(ctx)
    pid = project_id if project_id is not None else resolve_project_uuid(client, tenant_slug, str(project_ref))
    items, _total = fetch_list(client, api_paths.properties(tenant_slug, pid))
    try:
        matched = filter_properties(items, type_filter=type_filter, search=search, unused=unused)
    except UsageUnavailable as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    shown = matched if all_rows else matched[:limit]
    if json_mode_from_context(ctx):
        emit_json({"total": len(matched), "items": shown})
        return
    typer.echo(
        render_table(shown, matched=len(matched), project=str(project_ref or project_id), total=len(items))
    )


@app.command("get")
def get_property(
    ctx: typer.Context,
    property_id: UUID = typer.Argument(..., help="Property UUID."),
    project_id: UUID = typer.Option(..., "--project-id", help="Project UUID."),
) -> None:
    """Fetch one property by id (GET /v1/properties/{tenant_slug}/{project_id}/{id})."""
    client, tenant_slug = tenant_scoped_client(ctx)
    response = client.get(api_paths.property_record(tenant_slug, project_id, property_id))
    emit_record_response(
        response.json(),
        _PROPERTY_RECORD_FIELDS,
        json_mode=json_mode_from_context(ctx),
    )
