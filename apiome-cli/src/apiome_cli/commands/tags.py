"""Version tags: ``apiome tags list`` and ``tags show`` (CLI 11.4, #3263)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.pagination import DEFAULT_PAGE_LIMIT
from apiome_cli.client.errors import exit_on_api_error
from apiome_cli.client.project_version_resolve import list_versions, resolve_project_uuid
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.exit_codes import EXIT_TAG_EXISTS, EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json, json_mode_from_context
from apiome_cli.tag_create import TagCreateError, merge_request, needs_confirmation, request_body
from apiome_cli.tag_view import TagNotFound, find_tag, render_tag_list, render_tag_show, sort_tags
from apiome_cli.terminal import confirm_action
from apiome_cli.version_fork import ForkError, find_source_version

app = typer.Typer(
    name="tags",
    help="List, inspect and create version tags (named pointers to versions).",
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


def _read_tag_file(path: Path) -> dict[str, Any]:
    """Read ``--from-file`` (one JSON tag object), or exit 2 saying why it cannot be used."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        typer.echo(f"Cannot read {path}: {exc.strerror or exc}.", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    except json.JSONDecodeError as exc:
        typer.echo(f"{path} is not valid JSON: {exc.msg} (line {exc.lineno}).", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    if not isinstance(document, dict):
        typer.echo(f"{path} must hold one tag object.", err=True)
        raise typer.Exit(EXIT_USAGE)
    return document


def _exists_hint(name: str, points_to: Optional[str]) -> str:
    where = f" (it points to {points_to})" if points_to else ""
    return (
        f"Tag '{name}' already exists{where}; nothing was created. To point it at another version, "
        "move it with `apiome tags update` instead."
    )


@app.command("create")
def create_tag(
    ctx: typer.Context,
    project_ref: str = typer.Argument(..., metavar="PROJECT", help="Project slug or UUID."),
    tag: Optional[str] = typer.Argument(
        None, metavar="TAG", help="Tag name, lower-cased: a letter, then letters, digits or hyphens (2–41)."
    ),
    version: Optional[str] = typer.Option(
        None, "--version", help="Version the tag points to: label (2.1.0 or v2.1.0) or revision UUID."
    ),
    description: Optional[str] = typer.Option(None, "--description", help="What the tag is for (stored as its message)."),
    from_file: Optional[Path] = typer.Option(
        None,
        "--from-file",
        help="JSON tag object (e.g. an edited `tags show --json`): name, version, description, channel, immutable.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation an immutable tag asks for."),
) -> None:
    """Create a version tag pointing at a version (POST /v1/version-tags/{tenant}/{project}).

    Exit 6 when the project already has a tag with that name — move it with `tags update` instead.
    """
    try:
        request = merge_request(
            name=tag,
            version=version,
            description=description,
            document=_read_tag_file(from_file) if from_file else None,
        )
    except TagCreateError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    client, tenant_slug = tenant_scoped_client(ctx)
    project_id = resolve_project_uuid(client, tenant_slug, project_ref)
    payload = client.get(api_paths.version_tags(tenant_slug, project_id)).json()
    existing = payload if isinstance(payload, list) else []
    for current in existing:
        if str(current.get("name")) == request.name:
            typer.echo(_exists_hint(request.name, current.get("target_version_string")), err=True)
            raise typer.Exit(EXIT_TAG_EXISTS)
    try:
        target = find_source_version(list_versions(client, tenant_slug, project_id), existing, request.version_ref).version
    except ForkError as exc:
        typer.echo(f"No version or version tag {request.version_ref!r} in this project.", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    label = target.get("version_id")
    if needs_confirmation(request):
        confirm_action(
            f"'{request.name}' will be immutable: it can never be moved or deleted. Create it → {label}?",
            skip=yes,
        )
    response = client.post_raw(
        api_paths.version_tags(tenant_slug, project_id), json=request_body(request, str(target["id"]))
    )
    if response.status_code == 409:
        typer.echo(_exists_hint(request.name, None), err=True)
        raise typer.Exit(EXIT_TAG_EXISTS)
    exit_on_api_error(response)
    created = response.json()
    if json_mode_from_context(ctx):
        emit_json(created)
        return
    typer.echo(f"✔ Tag '{created.get('name', request.name)}' created → {label}.")
