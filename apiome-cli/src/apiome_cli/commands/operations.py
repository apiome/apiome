"""Path operation show command (read-only)."""

from __future__ import annotations

from uuid import UUID

import typer

from apiome_cli.client.version_scope import resolve_version_scope
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import json_mode_from_context
from apiome_cli.output_paths import emit_operation_show, emit_operation_show_json
from apiome_cli.paths_inventory import (
    fetch_operation_parameters,
    fetch_operation_request_body,
    fetch_operation_responses,
    locate_operation,
)

app = typer.Typer(
    name="operations",
    help="Inspect OpenAPI operations for a project version.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def operations_group(ctx: typer.Context) -> None:
    """Operations command group."""
    group_callback_without_subcommand(ctx)


@app.command("show")
def show_operation(
    ctx: typer.Context,
    operation_ref: str = typer.Argument(
        ...,
        help="Path operation UUID or OpenAPI operationId.",
    ),
    project: str = typer.Option(..., "--project", help="Project UUID or slug."),
    version: str = typer.Option(..., "--version", help="Version UUID, slug, or label."),
    tag: list[str] | None = typer.Option(
        None,
        "--tag",
        help="Narrow lookup by OpenAPI tag (repeatable).",
    ),
    method: list[str] | None = typer.Option(
        None,
        "--method",
        help="Narrow lookup by HTTP method (repeatable).",
    ),
) -> None:
    """Show one operation with parameters, bodies, and responses."""
    client, tenant_slug, _project_id, version_id = resolve_version_scope(
        ctx,
        project=project,
        version=version,
    )
    methods = [value.upper() for value in method] if method else None
    path_record, operation_record = locate_operation(
        client,
        tenant_slug,
        version_id,
        operation_ref,
        methods=methods,
        tags=tag,
    )
    path_id = UUID(str(path_record["id"]))
    operation_id = UUID(str(operation_record["id"]))
    parameters = fetch_operation_parameters(
        client,
        tenant_slug,
        version_id,
        path_id,
        operation_id,
    )
    request_body = fetch_operation_request_body(
        client,
        tenant_slug,
        version_id,
        path_id,
        operation_id,
    )
    responses = fetch_operation_responses(
        client,
        tenant_slug,
        version_id,
        path_id,
        operation_id,
    )

    if json_mode_from_context(ctx):
        emit_operation_show_json(
            path_record,
            operation_record,
            parameters=parameters,
            request_body=request_body,
            responses=responses,
        )
        return

    emit_operation_show(
        path_record,
        operation_record,
        parameters=parameters,
        request_body=request_body,
        responses=responses,
    )
