"""``apiome paths list`` / ``apiome paths show`` — a version's path templates (CLI 8.1, #3237)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import typer

from apiome_cli.client.pagination import DEFAULT_PAGE_LIMIT
from apiome_cli.client.version_scope import resolve_version_scope
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json, json_mode_from_context
from apiome_cli.output_paths import emit_path_tree, emit_paths_grouped_table
from apiome_cli.paths_inventory import (
    build_path_operation_rows,
    fetch_path_full,
    fetch_version_paths,
    filter_rows_by_query,
    resolve_path_record,
)
from apiome_cli.paths_view import group_by_path

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


def _scope(refs: list[str], project: str | None, version: str | None, *, extra: int) -> tuple[str, str, list[str]]:
    """``(project, version, remaining)`` from positionals ``PROJECT VERSION …`` or ``--project`` / ``--version``.

    Args:
        refs: The positional arguments.
        project: ``--project``.
        version: ``--version``.
        extra: How many positionals follow ``PROJECT VERSION`` (``0`` for list, ``1`` for show).

    Raises:
        typer.Exit: ``EXIT_USAGE`` when neither form names both the project and the version.
    """
    if len(refs) == extra + 2 and project is None and version is None:
        return refs[0], refs[1], refs[2:]
    if len(refs) == extra and project and version:
        return project, version, refs
    usage = "PROJECT VERSION" + (" PATH" if extra else "")
    typer.echo(
        f"Pass {usage}, or {'PATH with ' if extra else ''}--project and --version "
        "(not both forms).",
        err=True,
    )
    raise typer.Exit(EXIT_USAGE)


@app.command("list")
def list_paths(
    ctx: typer.Context,
    refs: list[str] = typer.Argument(
        None, metavar="[PROJECT VERSION]", help="Project (slug or UUID) and version (label, slug or UUID)."
    ),
    project: str | None = typer.Option(None, "--project", help="Project UUID or slug (instead of PROJECT)."),
    version: str | None = typer.Option(
        None, "--version", help="Version UUID, slug, or label (instead of VERSION)."
    ),
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
        "--search",
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
    """List a version's paths: one row per path with its methods, operations and tags.

    GET /v1/paths/{tenant}/{version}. --json prints the API's array of path records (only those
    --search matches, when given).
    """
    del limit, all_pages  # the list endpoint is not paginated; kept for existing scripts
    project_ref, version_ref, _rest = _scope(list(refs or []), project, version, extra=0)
    client, tenant_slug, _project_id, version_id = resolve_version_scope(
        ctx,
        project=project_ref,
        version=version_ref,
    )
    methods = [value.upper() for value in method] if method else None
    paths, _total = fetch_version_paths(client, tenant_slug, version_id, methods=methods, tags=tag)
    needs_rows = not json_mode_from_context(ctx) or bool(query)
    rows = (
        filter_rows_by_query(
            build_path_operation_rows(client, tenant_slug, version_id, paths, methods=methods, tags=tag),
            query,
        )
        if needs_rows
        else []
    )

    if json_mode_from_context(ctx):
        if query:
            matched = {str(row.get("path_id")) for row in rows}
            paths = [path for path in paths if str(path.get("id")) in matched]
        emit_json(paths)
        return
    grouped = group_by_path(rows)
    emit_paths_grouped_table(grouped, total=len(grouped))


def _keep(operation: dict[str, Any], methods: list[str] | None, tags: list[str] | None) -> bool:
    """Whether an operation of ``…/full`` passes ``--method`` / ``--tag``."""
    if methods and str(operation.get("operation") or "").upper() not in methods:
        return False
    if tags:
        description = operation.get("description") if isinstance(operation.get("description"), dict) else {}
        own = description.get("tags") if isinstance(description.get("tags"), list) else []
        return any(tag in own for tag in tags)
    return True


@app.command("show")
def show_path(
    ctx: typer.Context,
    refs: list[str] = typer.Argument(
        ...,
        metavar="[PROJECT VERSION] PATH",
        help=(
            "Project, version and path, or just PATH with --project / --version. PATH is the template "
            "(/charges/{id}), its URL-encoded or JSON Pointer form (~1charges~1{id}), or the path UUID."
        ),
    ),
    project: str | None = typer.Option(None, "--project", help="Project UUID or slug (instead of PROJECT)."),
    version: str | None = typer.Option(
        None, "--version", help="Version UUID, slug, or label (instead of VERSION)."
    ),
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
    """Show one path as a tree: its operations, then each one's parameters, body and responses.

    GET /v1/paths/{tenant}/{version}/{path_id}/full. --json prints that API object (operations
    filtered by --method / --tag, when given).
    """
    project_ref, version_ref, rest = _scope(list(refs or []), project, version, extra=1)
    client, tenant_slug, _project_id, version_id = resolve_version_scope(
        ctx,
        project=project_ref,
        version=version_ref,
    )
    methods = [value.upper() for value in method] if method else None
    path_record = resolve_path_record(client, tenant_slug, version_id, rest[0])
    full = fetch_path_full(client, tenant_slug, version_id, UUID(str(path_record["id"])))
    if methods or tag:
        full = {**full, "operations": [op for op in full.get("operations") or [] if _keep(op, methods, tag)]}

    if json_mode_from_context(ctx):
        emit_json(full)
        return
    emit_path_tree(full)
