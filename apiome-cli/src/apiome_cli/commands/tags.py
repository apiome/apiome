"""Version tags: ``apiome tags list`` and ``tags show`` (CLI 11.4, #3263)."""

from __future__ import annotations

from typing import Any

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.pagination import DEFAULT_PAGE_LIMIT
from apiome_cli.client.project_version_resolve import resolve_project_uuid
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json, json_mode_from_context
from apiome_cli.tag_view import TagNotFound, find_tag, render_tag_list, render_tag_show, sort_tags

app = typer.Typer(
    name="tags",
    help="List and inspect version tags (named pointers to versions).",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def tags_group(ctx: typer.Context) -> None:
    """Version tags command group."""
    group_callback_without_subcommand(ctx)


def _project_tags(ctx: typer.Context, project_ref: str) -> list[dict[str, Any]]:
    """Every version tag of ``project_ref``, in name order."""
    client, tenant_slug = tenant_scoped_client(ctx)
    project_id = resolve_project_uuid(client, tenant_slug, project_ref)
    payload = client.get(api_paths.version_tags(tenant_slug, project_id)).json()
    return list(sort_tags(payload if isinstance(payload, list) else []))


@app.command("list")
def list_tags(
    ctx: typer.Context,
    project_ref: str = typer.Argument(..., metavar="PROJECT", help="Project slug or UUID."),
    limit: int = typer.Option(DEFAULT_PAGE_LIMIT, "--limit", min=1, help="Show at most this many tags."),
    all_tags: bool = typer.Option(False, "--all", help="Show every tag (ignores --limit)."),
) -> None:
    """List a project's version tags and the version each points to (GET /v1/version-tags/{tenant}/{project})."""
    tags = _project_tags(ctx, project_ref)
    shown = tags if all_tags else tags[:limit]
    if json_mode_from_context(ctx):
        emit_json({"total": len(tags), "items": shown})
        return
    typer.echo(render_tag_list(shown, total=len(tags)))


@app.command("show")
def show_tag(
    ctx: typer.Context,
    project_ref: str = typer.Argument(..., metavar="PROJECT", help="Project slug or UUID."),
    tag_ref: str = typer.Argument(..., metavar="TAG", help="Tag name (exact) or tag UUID."),
) -> None:
    """Show one version tag: the version it points to, its channel, locks and dates.

    The server keeps only the current pointer, so no move history is shown.
    """
    try:
        tag = find_tag(_project_tags(ctx, project_ref), tag_ref)
    except TagNotFound as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    if json_mode_from_context(ctx):
        emit_json(tag)
        return
    typer.echo(render_tag_show(tag))
