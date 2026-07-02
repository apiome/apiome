"""Version workflow list and show commands (read-only)."""

from __future__ import annotations

from uuid import UUID

import typer

from apiome_cli.client.pagination import DEFAULT_PAGE_LIMIT
from apiome_cli.client.version_scope import resolve_version_scope
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json, json_mode_from_context
from apiome_cli.output_paths import (
    emit_workflow_show,
    emit_workflow_show_json,
    emit_workflows_list_table,
)
from apiome_cli.paths_inventory import (
    fetch_version_workflows,
    fetch_workflow_steps,
    resolve_workflow_record,
)

app = typer.Typer(
    name="workflows",
    help="List and inspect Arazzo workflows for a project version.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def workflows_group(ctx: typer.Context) -> None:
    """Workflows command group."""
    group_callback_without_subcommand(ctx)


@app.command("list")
def list_workflows(
    ctx: typer.Context,
    project: str = typer.Option(..., "--project", help="Project UUID or slug."),
    version: str = typer.Option(..., "--version", help="Version UUID, slug, or label."),
    limit: int = typer.Option(
        DEFAULT_PAGE_LIMIT,
        "--limit",
        min=1,
        help="Maximum rows per API page (server enforces its own max).",
    ),
    all_pages: bool = typer.Option(
        False,
        "--all",
        help="Fetch all API pages automatically.",
    ),
) -> None:
    """List workflows (GET /versions/{version_id}/workflows)."""
    client, _project_id, version_id = resolve_version_scope(ctx, project=project, version=version)
    items, total = fetch_version_workflows(
        client,
        version_id,
        fetch_all=all_pages,
        limit=limit,
    )
    if json_mode_from_context(ctx):
        emit_json({"total": total, "items": items})
        return
    emit_workflows_list_table(items, total=total)


@app.command("show")
def show_workflow(
    ctx: typer.Context,
    workflow_ref: str = typer.Argument(
        ...,
        help="Workflow row UUID or Arazzo workflowId.",
    ),
    project: str = typer.Option(..., "--project", help="Project UUID or slug."),
    version: str = typer.Option(..., "--version", help="Version UUID, slug, or label."),
) -> None:
    """Show one workflow and its steps (GET /versions/{version_id}/workflows/{id})."""
    client, _project_id, version_id = resolve_version_scope(ctx, project=project, version=version)
    workflow_record = resolve_workflow_record(client, version_id, workflow_ref)
    workflow_id = UUID(str(workflow_record["id"]))
    steps = fetch_workflow_steps(client, version_id, workflow_id)

    if json_mode_from_context(ctx):
        emit_workflow_show_json(workflow_record, steps)
        return

    emit_workflow_show(workflow_record, steps)
