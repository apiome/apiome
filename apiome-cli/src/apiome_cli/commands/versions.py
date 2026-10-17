"""Project versions list and get commands (read-only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
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
from apiome_cli.client.errors import exit_on_api_error
from apiome_cli.client.list_response import fetch_list
from apiome_cli.exit_codes import EXIT_USAGE, EXIT_VERSION_EXISTS
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
from apiome_cli.version_fork import (
    ForkError,
    check_new_version,
    copy_counts,
    find_source_version,
    label_exists,
    render_summary,
    tags_to_copy,
)

app = typer.Typer(
    name="versions",
    help="List, fetch, publish and fork project versions.",
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


def _version_exists_conflict(response: Any) -> bool:
    """Whether a fork response is the server's ``409 version_exists``."""
    if response.status_code != 409:
        return False
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return False
    return isinstance(detail, dict) and detail.get("code") == "version_exists"


@app.command("fork")
def fork_version(
    ctx: typer.Context,
    project_ref: str = typer.Argument(..., help="Source project slug or UUID."),
    source_ref: str = typer.Argument(
        ..., help="Source version: label (2.1.0 or v2.1.0), revision UUID, or version tag."
    ),
    into: str = typer.Option(
        ..., "--into", help="Target project (slug or UUID) the fork is created in."
    ),
    to: str = typer.Option(..., "--to", help="New version label in the target, e.g. 3.0.0."),
    notes: Optional[str] = typer.Option(None, "--notes", help="Short revision note."),
    notes_file: Optional[Path] = typer.Option(
        None, "--notes-file", help="Markdown file used as the new version's changelog."
    ),
    include_tags: bool = typer.Option(
        False, "--include-tags", help="Also create the source's version tags on the fork."
    ),
    allow_lesser: bool = typer.Option(
        False, "--allow-lesser", help="Allow --to to be lower than or equal to the source."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be copied without forking."
    ),
) -> None:
    """Fork a version into another project, keeping its lineage (POST /v1/versions/{tenant}/{target}/fork).

    Copies the source version's classes and their properties into a new draft version of the
    target project, recorded as a fork so it can merge back later. Paths are not copied.
    Within one project, use a branch instead: the server refuses a same-project fork.
    """
    client, tenant_slug = tenant_scoped_client(ctx)
    source_project = resolve_project_uuid(client, tenant_slug, project_ref)
    target_project = resolve_project_uuid(client, tenant_slug, into)
    if source_project == target_project:
        typer.echo(
            "A fork goes into a different project (--into). To start a new version in the "
            "same project, branch it instead.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    source_versions = list_versions(client, tenant_slug, source_project)
    source_tags = client.get(api_paths.version_tags(tenant_slug, source_project)).json() or []
    try:
        match = find_source_version(source_versions, source_tags, source_ref)
        source = match.version
        new_label = check_new_version(to, source.get("version_id"), allow_lesser=allow_lesser)
    except ForkError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc

    changelog: Optional[str] = None
    if notes_file is not None:
        try:
            changelog = notes_file.read_text(encoding="utf-8")
        except OSError as exc:
            typer.echo(f"Cannot read {notes_file}: {exc.strerror or exc}.", err=True)
            raise typer.Exit(EXIT_USAGE) from exc

    target_versions = list_versions(client, tenant_slug, target_project)
    if label_exists(target_versions, new_label):
        typer.echo(
            f"Version {new_label} already exists in {into!r}; choose another --to.", err=True
        )
        raise typer.Exit(EXIT_VERSION_EXISTS)

    source_id = str(source["id"])
    classes = client.get(
        api_paths.classes_with_properties_tags(tenant_slug, source_id)
    ).json() or []
    class_count, property_count = copy_counts(classes)
    source_paths, _total = fetch_list(client, api_paths.paths(tenant_slug, source_id))
    tags = tags_to_copy(source_tags, source_id) if include_tags else []

    source_text = f"{project_ref}@{source.get('version_id')}"
    target_text = f"{into}@{new_label}"
    json_mode = json_mode_from_context(ctx)

    if dry_run:
        if json_mode:
            emit_json(
                {
                    "dryRun": True,
                    "source": {"projectId": str(source_project), "version": source},
                    "target": {"projectId": str(target_project), "versionId": new_label},
                    "classes": class_count,
                    "properties": property_count,
                    "sourcePaths": len(source_paths),
                    "pathsCopied": 0,
                    "tags": [tag.get("name") for tag in tags],
                }
            )
        else:
            typer.echo(
                render_summary(
                    dry_run=True,
                    source=source_text,
                    target=target_text,
                    classes=class_count,
                    properties=property_count,
                    source_paths=len(source_paths),
                    tags_copied=[str(tag.get("name")) for tag in tags],
                    include_tags=include_tags,
                )
            )
        return

    body: dict[str, Any] = {"sourceRevisionId": source_id, "versionId": new_label}
    if notes:
        body["shortMessage"] = notes
    if changelog:
        body["changelog"] = changelog
    response = client.post_raw(api_paths.version_fork(tenant_slug, target_project), json=body)
    if _version_exists_conflict(response):
        typer.echo(
            f"Version {new_label} already exists in {into!r}; choose another --to.", err=True
        )
        raise typer.Exit(EXIT_VERSION_EXISTS)
    exit_on_api_error(response)
    forked = response.json()

    copied: list[str] = []
    skipped: list[str] = []
    for tag in tags:
        tag_response = client.post_raw(
            api_paths.version_tags(tenant_slug, target_project),
            json={
                "version_id": forked["id"],
                "name": tag.get("name"),
                "message": tag.get("message"),
                "channel": tag.get("channel"),
            },
        )
        (copied if tag_response.is_success else skipped).append(str(tag.get("name")))

    if json_mode:
        emit_json(forked)
        return
    typer.echo(
        render_summary(
            dry_run=False,
            source=source_text,
            target=target_text,
            classes=class_count,
            properties=property_count,
            source_paths=len(source_paths),
            new_id=str(forked.get("id")),
            tags_copied=copied,
            tags_skipped=skipped,
            include_tags=include_tags,
        )
    )
