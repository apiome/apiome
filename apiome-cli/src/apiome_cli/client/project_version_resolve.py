"""Resolve project and version references (UUID or slug) via REST list endpoints."""

from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.client.list_response import fetch_list
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.extract.slug import slugify_project_name, slugify_version


def _normalize_ref(value: str) -> str:
    return value.strip()


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def resolve_project_uuid(
    client: RestClient,
    tenant_slug: str,
    project_ref: str,
) -> UUID:
    """Return the project UUID for ``project_ref`` (UUID or slug)."""
    ref = _normalize_ref(project_ref)
    if not ref:
        typer.echo("Project reference cannot be empty.", err=True)
        raise typer.Exit(EXIT_USAGE)
    if _is_uuid(ref):
        return UUID(ref)

    slug = slugify_project_name(ref)
    response = client.get(api_paths.project_by_slug(tenant_slug, slug))
    record = response.json()
    if not isinstance(record, dict) or not record.get("id"):
        typer.echo(f"Project {ref!r} was not found for tenant {tenant_slug!r}.", err=True)
        raise typer.Exit(EXIT_USAGE)
    return UUID(str(record["id"]))


def resolve_version_uuid(
    client: RestClient,
    *,
    tenant_slug: str,
    project_id: UUID,
    version_ref: str,
) -> UUID:
    """Return the version record UUID for ``version_ref`` (UUID, slug, or semver label)."""
    ref = _normalize_ref(version_ref)
    if not ref:
        typer.echo("Version reference cannot be empty.", err=True)
        raise typer.Exit(EXIT_USAGE)
    if _is_uuid(ref):
        return UUID(ref)

    semver = slugify_version(ref)
    path = api_paths.version_by_semver(tenant_slug, project_id, quote(semver, safe=""))
    response = client.get(path)
    record = response.json()
    if not isinstance(record, dict) or not record.get("id"):
        typer.echo(
            f"Version {ref!r} was not found for project {project_id} in tenant {tenant_slug!r}.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)
    return UUID(str(record["id"]))


def list_projects(
    client: RestClient,
    tenant_slug: str,
) -> list[dict[str, object]]:
    """Return all projects for a tenant."""
    items, _total = fetch_list(client, api_paths.projects(tenant_slug))
    return items


def list_versions(
    client: RestClient,
    tenant_slug: str,
    project_id: UUID,
) -> list[dict[str, object]]:
    """Return all versions for one project."""
    items, _total = fetch_list(client, api_paths.versions(tenant_slug, project_id))
    return items
