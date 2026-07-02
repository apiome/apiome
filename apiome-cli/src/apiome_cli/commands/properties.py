"""Properties list and get commands (read-only)."""

from __future__ import annotations

import json
from uuid import UUID

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.list_response import fetch_list
from apiome_cli.client.version_scope import tenant_scoped_client
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
    name="properties",
    help="List and fetch tenant properties.",
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


_PROPERTY_LIST_COLUMNS: tuple[ListColumn, ...] = (
    ("ID", "id", None),
    ("Name", "name", None),
    ("Description", "description", None),
    ("Enabled", "enabled", lambda value: "" if value is None else str(value)),
)

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
    project_id: UUID = typer.Option(..., "--project-id", help="Project UUID."),
) -> None:
    """List project properties (GET /v1/properties/{tenant_slug}/{project_id})."""
    client, tenant_slug = tenant_scoped_client(ctx)
    items, total = fetch_list(client, api_paths.properties(tenant_slug, project_id))
    if json_mode_from_context(ctx):
        emit_json({"total": total, "items": items})
    else:
        emit_list_table(items, _PROPERTY_LIST_COLUMNS, total=total)


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
