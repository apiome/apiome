"""Platform primitive type library list and show commands."""

from __future__ import annotations

from uuid import UUID

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.errors import exit_on_api_error
from apiome_cli.client.list_response import fetch_list
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import (
    emit_type_detail,
    emit_types_list_response,
    json_mode_from_context,
)

app = typer.Typer(
    name="types",
    help="Browse tenant JSON Schema primitive types.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

_NOT_SUPPORTED = "Type publish/unpublish is not supported via the /v1 REST API yet."


@app.callback(invoke_without_command=True)
def types_group(ctx: typer.Context) -> None:
    """Types command group."""
    group_callback_without_subcommand(ctx)


def _looks_like_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _fetch_primitive_by_identifier(
    client,
    tenant_slug: str,
    identifier: str,
) -> dict[str, object]:
    if _looks_like_uuid(identifier):
        path = api_paths.primitive(tenant_slug, identifier)
        response = client.get_raw(path)
        if response.status_code == 404:
            typer.echo(f"Type not found: {identifier}", err=True)
            raise typer.Exit(EXIT_USAGE)
    else:
        items, _total = fetch_list(client, api_paths.primitives(tenant_slug))
        matches = [
            row
            for row in items
            if isinstance(row.get("slug"), str) and row["slug"] == identifier
        ]
        if len(matches) != 1:
            typer.echo(f"Type not found: {identifier}", err=True)
            raise typer.Exit(EXIT_USAGE)
        type_id = matches[0].get("id")
        if not isinstance(type_id, str):
            typer.echo(f"Type not found: {identifier}", err=True)
            raise typer.Exit(EXIT_USAGE)
        path = api_paths.primitive(tenant_slug, type_id)
        response = client.get_raw(path)
    exit_on_api_error(response)
    payload = response.json()
    if not isinstance(payload, dict):
        msg = f"Unexpected response from GET {path}."
        raise typer.BadParameter(msg)
    return payload


@app.command("list")
def list_types(ctx: typer.Context) -> None:
    """List tenant primitives (GET /v1/primitives/{tenant_slug})."""
    client, tenant_slug = tenant_scoped_client(ctx)
    items, total = fetch_list(client, api_paths.primitives(tenant_slug))
    payload = {"total": total, "items": items}
    emit_types_list_response(payload, json_mode=json_mode_from_context(ctx))


@app.command("show")
def show_type(
    ctx: typer.Context,
    identifier: str = typer.Argument(..., help="Type UUID or slug."),
) -> None:
    """Fetch one primitive by UUID or slug."""
    client, tenant_slug = tenant_scoped_client(ctx)
    payload = _fetch_primitive_by_identifier(client, tenant_slug, identifier)
    emit_type_detail(payload, json_mode=json_mode_from_context(ctx))


@app.command("search")
def search_types(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search query (name, slug, or description)."),
) -> None:
    """Search tenant primitives by substring match on list results."""
    client, tenant_slug = tenant_scoped_client(ctx)
    items, total = fetch_list(client, api_paths.primitives(tenant_slug))
    needle = query.strip().casefold()
    filtered = [
        row
        for row in items
        if any(
            needle in str(row.get(field, "")).casefold()
            for field in ("name", "slug", "description")
        )
    ]
    payload = {"total": len(filtered), "items": filtered}
    emit_types_list_response(
        payload,
        json_mode=json_mode_from_context(ctx),
        search_query=query,
    )


@app.command("publish")
def publish_type(
    ctx: typer.Context,
    identifier: str = typer.Argument(..., help="Type UUID or slug."),
) -> None:
    """Publish a tenant-owned type (not exposed on /v1 REST)."""
    del ctx, identifier
    typer.echo(_NOT_SUPPORTED, err=True)
    raise typer.Exit(EXIT_USAGE)


@app.command("unpublish")
def unpublish_type(
    ctx: typer.Context,
    identifier: str = typer.Argument(..., help="Type UUID or slug."),
) -> None:
    """Unpublish a system-wide type (not exposed on /v1 REST)."""
    del ctx, identifier
    typer.echo(_NOT_SUPPORTED, err=True)
    raise typer.Exit(EXIT_USAGE)
