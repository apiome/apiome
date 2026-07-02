"""Version path list and show commands (read-only)."""

from __future__ import annotations

from uuid import UUID

import typer

from apiome_cli.client.pagination import DEFAULT_PAGE_LIMIT
from apiome_cli.client.version_scope import resolve_version_scope
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import json_mode_from_context
from apiome_cli.output_paths import (
    emit_path_show,
    emit_path_show_json,
    emit_paths_inventory_table,
    emit_paths_list_json,
)
from apiome_cli.paths_inventory import (
    build_path_operation_rows,
    fetch_path_operations,
    fetch_version_paths,
    filter_rows_by_query,
    resolve_path_record,
)

app = typer.Typer(
    name="paths",
    help="List and inspect OpenAPI path templates for a project version.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def paths_group(ctx: typer.Context) -> None:
    """Paths command group."""
    group_callback_without_subcommand(ctx)


@app.command("list")
def list_paths(
    ctx: typer.Context,
    project: str = typer.Option(..., "--project", help="Project UUID or slug."),
    version: str = typer.Option(..., "--version", help="Version UUID, slug, or label."),
    tag: list[str] | None = typer.Option(
        None,
        "--tag",
        help="Filter by OpenAPI operation tag (repeatable).",
    ),
    method: list[str] | None = typer.Option(
        None,
        "--method",
        help="Filter by HTTP method (repeatable).",
    ),
    query: str | None = typer.Option(
        None,
        "--q",
        help="Case-insensitive text search over path, method, operationId, summary, and tags.",
    ),
    limit: int = typer.Option(
        DEFAULT_PAGE_LIMIT,
        "--limit",
        min=1,
        help="Maximum rows per API page (server enforces its own max).",
    ),
    all_pages: bool = typer.Option(
        False,
        "--all",
        help="Fetch all API pages when resolving paths and operations.",
    ),
) -> None:
    """List path templates and operations (GET /versions/{version_id}/paths)."""
    client, tenant_slug, _project_id, version_id = resolve_version_scope(
        ctx,
        project=project,
        version=version,
    )
    methods = [value.upper() for value in method] if method else None
    tags = tag
    paths, total = fetch_version_paths(
        client,
        tenant_slug,
        version_id,
        methods=methods,
        tags=tags,
    )

    if json_mode_from_context(ctx):
        payload = {
            "total": total,
            "offset": 0,
            "limit": limit,
            "items": paths,
        }
        emit_paths_list_json(payload)
        return

    rows = build_path_operation_rows(
        client,
        tenant_slug,
        version_id,
        paths,
        methods=methods,
        tags=tags,
    )
    rows = filter_rows_by_query(rows, query)
    emit_paths_inventory_table(rows, total=len(rows))


@app.command("show")
def show_path(
    ctx: typer.Context,
    path_ref: str = typer.Argument(..., help="Path UUID or OpenAPI path template."),
    project: str = typer.Option(..., "--project", help="Project UUID or slug."),
    version: str = typer.Option(..., "--version", help="Version UUID, slug, or label."),
    tag: list[str] | None = typer.Option(
        None,
        "--tag",
        help="Filter operations by OpenAPI tag (repeatable).",
    ),
    method: list[str] | None = typer.Option(
        None,
        "--method",
        help="Filter operations by HTTP method (repeatable).",
    ),
) -> None:
    """Show one path template and its operations (GET /versions/{version_id}/paths/{path_id})."""
    client, tenant_slug, _project_id, version_id = resolve_version_scope(
        ctx,
        project=project,
        version=version,
    )
    methods = [value.upper() for value in method] if method else None
    path_record = resolve_path_record(
        client,
        tenant_slug,
        version_id,
        path_ref,
    )
    path_id = UUID(str(path_record["id"]))
    operations, _total = fetch_path_operations(
        client,
        tenant_slug,
        version_id,
        path_id,
        methods=methods,
        tags=tag,
    )

    if json_mode_from_context(ctx):
        emit_path_show_json(path_record, operations)
        return

    emit_path_show(path_record, operations)
