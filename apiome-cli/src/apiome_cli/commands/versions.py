"""Project versions list and get commands (read-only)."""

from __future__ import annotations

from uuid import UUID

import typer

from apiome_cli.cli_context import insecure_from_context, settings_from_context, timeout_from_context
from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.client.project_version_resolve import (
    list_projects,
    list_versions,
    resolve_project_uuid,
    resolve_version_uuid,
)
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.config import require_api_key
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.import_.publish import normalize_cli_import_visibility
from apiome_cli.output import (
    ListColumn,
    RecordField,
    emit_json,
    emit_list_table,
    emit_record_response,
    json_mode_from_context,
)

app = typer.Typer(
    name="versions",
    help="List and fetch project versions.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def versions_group(ctx: typer.Context) -> None:
    """Versions command group."""
    group_callback_without_subcommand(ctx)

_VERSION_LIST_COLUMNS: tuple[ListColumn, ...] = (
    ("ID", "id", None),
    ("Project", "project_name", None),
    ("Project Slug", "project_slug", None),
    ("Version", "version", None),
    ("Version Slug", "slug", None),
    ("Source", "source", None),
    ("Enabled", "enabled", lambda value: "" if value is None else str(value)),
)

_VERSION_LIST_MIN_WIDTH = 120

_VERSION_RECORD_FIELDS: tuple[RecordField, ...] = (
    ("ID", "id", None),
    ("Project ID", "project_id", None),
    ("Version", "version", None),
    ("Slug", "slug", None),
    ("Source", "source", None),
    ("Enabled", "enabled", lambda value: "" if value is None else str(value)),
)

_VERSION_PUBLISH_RECORD_FIELDS: tuple[RecordField, ...] = (
    ("ID", "id", None),
    ("Project ID", "project_id", None),
    ("Version", "version", None),
    ("Slug", "slug", None),
    ("Visibility", "publish_visibility", None),
    ("Published On", "published_on", lambda value: "" if value is None else str(value)),
    ("Enabled", "enabled", lambda value: "" if value is None else str(value)),
)


def _with_project_columns(
    items: list[dict[str, object]],
    lookup: dict[str, dict[str, str]],
) -> list[dict[str, object]]:
    enriched: list[dict[str, object]] = []
    for item in items:
        row = dict(item)
        project_id = item.get("project_id")
        project = lookup.get(str(project_id)) if project_id is not None else None
        row["project_name"] = (project or {}).get("name", "")
        row["project_slug"] = (project or {}).get("slug", "")
        enriched.append(row)
    return enriched


def _resolve_publish_version_id(
    client: RestClient,
    tenant_slug: str,
    *,
    version_ref: str,
    project_ref: str | None,
) -> tuple[UUID, UUID]:
    if project_ref is None:
        ref = version_ref.strip()
        try:
            version_id = UUID(ref)
        except ValueError as exc:
            typer.echo(
                "Pass a version UUID, or provide --project to publish by slug or label.",
                err=True,
            )
            raise typer.Exit(EXIT_USAGE) from exc
        typer.echo(
            "Publishing by version UUID alone requires --project for tenant-scoped routes.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)
    project_id = resolve_project_uuid(client, tenant_slug, project_ref)
    version_id = resolve_version_uuid(
        client,
        tenant_slug=tenant_slug,
        project_id=project_id,
        version_ref=version_ref,
    )
    return project_id, version_id


@app.command("list")
def list_versions_cmd(
    ctx: typer.Context,
    project_id: UUID | None = typer.Option(
        None,
        "--project-id",
        help="Restrict results to one project (required unless listing all projects).",
    ),
) -> None:
    """List project versions (GET /v1/versions/{tenant_slug}/{project_id})."""
    client, tenant_slug = tenant_scoped_client(ctx)
    if project_id is not None:
        items = list_versions(client, tenant_slug, project_id)
        lookup = {
            str(project_id): {
                "name": "",
                "slug": "",
            }
        }
        project_record = client.get(api_paths.project(tenant_slug, project_id)).json()
        if isinstance(project_record, dict):
            lookup[str(project_id)] = {
                "name": str(project_record.get("name") or ""),
                "slug": str(project_record.get("slug") or ""),
            }
    else:
        projects = list_projects(client, tenant_slug)
        lookup = {
            str(item.get("id")): {
                "name": str(item.get("name") or ""),
                "slug": str(item.get("slug") or ""),
            }
            for item in projects
            if item.get("id") is not None
        }
        items = []
        for project in projects:
            pid = project.get("id")
            if pid is None:
                continue
            items.extend(list_versions(client, tenant_slug, UUID(str(pid))))

    if json_mode_from_context(ctx):
        emit_json({"total": len(items), "items": items})
    else:
        rows = _with_project_columns(items, lookup) if items else items
        emit_list_table(
            rows,
            _VERSION_LIST_COLUMNS,
            total=len(items),
            min_width=_VERSION_LIST_MIN_WIDTH,
        )


@app.command("get")
def get_version(
    ctx: typer.Context,
    project_id: UUID = typer.Option(..., "--project-id", help="Parent project UUID."),
    version_id: UUID = typer.Argument(..., help="Version record UUID."),
) -> None:
    """Fetch one version (GET /v1/versions/{tenant_slug}/{project_id}/{version_id})."""
    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
    )
    from apiome_cli.client.tenant_scope import require_tenant_slug

    tenant_slug = require_tenant_slug(settings, client)
    response = client.get(api_paths.version_record(tenant_slug, project_id, version_id))
    emit_record_response(
        response.json(),
        _VERSION_RECORD_FIELDS,
        json_mode=json_mode_from_context(ctx),
    )


@app.command("publish")
def publish_version(
    ctx: typer.Context,
    version: str = typer.Argument(
        ...,
        metavar="VERSION",
        help="Version UUID, or a slug/label when --project is supplied.",
    ),
    project: str = typer.Option(
        ...,
        "--project",
        help="Project UUID or slug.",
    ),
    visibility: str = typer.Option(
        "public",
        "--visibility",
        "-v",
        help="Publish visibility: 'public' (catalog) or 'private' (tenant-protected).",
    ),
) -> None:
    """Publish a version (POST …/{version_record_id}/publish)."""
    try:
        api_visibility = normalize_cli_import_visibility(visibility)
    except ValueError:
        typer.echo("--visibility must be 'public' or 'private'.", err=True)
        raise typer.Exit(EXIT_USAGE)
    client, tenant_slug = tenant_scoped_client(ctx)
    project_id, version_id = _resolve_publish_version_id(
        client,
        tenant_slug,
        version_ref=version,
        project_ref=project,
    )
    response = client.post(
        api_paths.version_publish(tenant_slug, project_id, version_id),
        json={"visibility": api_visibility},
    )
    emit_record_response(
        response.json(),
        _VERSION_PUBLISH_RECORD_FIELDS,
        json_mode=json_mode_from_context(ctx),
    )


@app.command("unpublish")
def unpublish_version(
    ctx: typer.Context,
    version: str = typer.Argument(
        ...,
        metavar="VERSION",
        help="Version UUID, or a slug/label when --project is supplied.",
    ),
    project: str = typer.Option(
        ...,
        "--project",
        help="Project UUID or slug.",
    ),
) -> None:
    """Return a published version to draft (POST …/{version_record_id}/unpublish)."""
    client, tenant_slug = tenant_scoped_client(ctx)
    project_id, version_id = _resolve_publish_version_id(
        client,
        tenant_slug,
        version_ref=version,
        project_ref=project,
    )
    response = client.post(
        api_paths.version_unpublish(tenant_slug, project_id, version_id),
    )
    emit_record_response(
        response.json(),
        _VERSION_PUBLISH_RECORD_FIELDS,
        json_mode=json_mode_from_context(ctx),
    )
