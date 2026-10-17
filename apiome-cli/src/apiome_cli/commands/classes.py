"""Classes: ``apiome classes list`` (CLI 7.1, #3229)."""

from __future__ import annotations

from typing import Any, Optional

import typer

from apiome_cli.class_view import filter_classes, render_hydrated, render_lean, summary_line
from apiome_cli.client import api_paths
from apiome_cli.client.pagination import DEFAULT_PAGE_LIMIT
from apiome_cli.client.project_version_resolve import list_versions, resolve_project_uuid
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json, json_mode_from_context
from apiome_cli.version_fork import ForkError, find_source_version

app = typer.Typer(
    name="classes",
    help="List a version's classes.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def classes_group(ctx: typer.Context) -> None:
    """Classes command group."""
    group_callback_without_subcommand(ctx)


def _version(client: Any, tenant_slug: str, project_id: Any, ref: str) -> dict[str, Any]:
    """The version ``ref`` names (label with or without ``v``, UUID, or version tag); exit 2 if none."""
    tags = client.get(api_paths.version_tags(tenant_slug, project_id)).json()
    try:
        return find_source_version(
            list_versions(client, tenant_slug, project_id), tags if isinstance(tags, list) else [], ref
        ).version
    except ForkError as exc:
        typer.echo(f"No version or version tag {ref!r} in this project.", err=True)
        raise typer.Exit(EXIT_USAGE) from exc


@app.command("list")
def list_classes(
    ctx: typer.Context,
    project_ref: str = typer.Argument(..., metavar="PROJECT", help="Project slug or UUID."),
    version_ref: str = typer.Argument(..., metavar="VERSION", help="Version label (2.1.0 or v2.1.0), UUID or tag."),
    tag: Optional[str] = typer.Option(None, "--tag", help="Only classes with this tag (any case)."),
    search: Optional[str] = typer.Option(None, "--search", help="Case-insensitive text in the name or description."),
    with_properties: bool = typer.Option(
        False, "--with-properties", help="Show every class's properties (one call for the whole version)."
    ),
    limit: int = typer.Option(DEFAULT_PAGE_LIMIT, "--limit", min=1, help="Show at most this many classes."),
    all_rows: bool = typer.Option(False, "--all", help="Show every match (ignores --limit)."),
) -> None:
    """List a version's classes with their property count, tags and description.

    --with-properties adds each class's properties (name, type, required), nested ones indented.

    --json prints the classes exactly as the API returns them (after the filters and --limit).
    """
    client, tenant_slug = tenant_scoped_client(ctx)
    project_id = resolve_project_uuid(client, tenant_slug, project_ref)
    version = _version(client, tenant_slug, project_id, version_ref)
    if with_properties:
        payload = client.get(api_paths.classes_with_properties_tags(tenant_slug, version["id"])).json()
    else:
        payload = client.get(f"{api_paths.classes(tenant_slug)}?version_id={version['id']}").json()
    classes = payload if isinstance(payload, list) else []
    matched = filter_classes(classes, tag=tag, search=search)
    shown = matched if all_rows else matched[:limit]
    if json_mode_from_context(ctx):
        emit_json(shown)
        return
    where = f"{project_ref} {version.get('version_id') or version_ref}"
    lines = render_hydrated(shown) if with_properties else render_lean(shown)
    if lines and lines[-1] != "":
        lines.append("")
    lines.append(summary_line(shown=len(shown), matched=len(matched), total=len(classes), where=where))
    typer.echo("\n".join(lines))
