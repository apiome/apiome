"""Resolve browse catalog slugs for published spec export requests."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote
from uuid import UUID

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.client.project_version_resolve import resolve_project_uuid, resolve_version_uuid
from apiome_cli.client.tenant_scope import normalize_tenant_ref, require_tenant_slug
from apiome_cli.config import CliSettings
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.extract.slug import slugify_project_name, slugify_version


@dataclass(frozen=True)
class BrowseExportScope:
    """Tenant, project, and version slugs for published spec export."""

    tenant_slug: str
    project_slug: str
    version_slug: str
    version_id: UUID | None


def resolve_tenant_slug(settings: CliSettings, client: RestClient, *, tenant_override: str | None) -> str:
    """Return the tenant URL slug from ``--tenant`` or configured tenant scope."""
    if tenant_override is not None and tenant_override.strip():
        ref = tenant_override.strip()
        try:
            UUID(ref)
        except ValueError:
            return normalize_tenant_ref(ref)
        return require_tenant_slug(settings, client)
    return require_tenant_slug(settings, client)


def resolve_browse_export_scope(
    client: RestClient,
    settings: CliSettings,
    *,
    project_ref: str,
    version_ref: str,
    tenant_override: str | None = None,
) -> BrowseExportScope:
    """Resolve browse slugs for ``GET /v1/schema/...`` export."""
    tenant_slug = resolve_tenant_slug(settings, client, tenant_override=tenant_override)
    if settings.api_key_value() is None and not (tenant_override or settings.tenant_id):
        typer.echo(
            "Tenant scope required. Set --tenant or APIOME_TENANT_ID (slug).",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    if settings.api_key_value() is None:
        if not project_ref.strip() or not version_ref.strip():
            typer.echo("Project and version references cannot be empty.", err=True)
            raise typer.Exit(EXIT_USAGE)
        try:
            project_slug = slugify_project_name(project_ref)
            version_slug = slugify_version(version_ref)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_USAGE) from exc
        return BrowseExportScope(
            tenant_slug=tenant_slug,
            project_slug=project_slug,
            version_slug=version_slug,
            version_id=None,
        )

    project_id = resolve_project_uuid(client, tenant_slug, project_ref)
    version_id = resolve_version_uuid(
        client,
        tenant_slug=tenant_slug,
        project_id=project_id,
        version_ref=version_ref,
    )
    project_record = client.get(api_paths.project(tenant_slug, project_id)).json()
    version_record = client.get(
        api_paths.version_record(tenant_slug, project_id, version_id),
    ).json()
    if not isinstance(project_record, dict) or not isinstance(version_record, dict):
        typer.echo("Unexpected project or version response from the server.", err=True)
        raise typer.Exit(EXIT_USAGE)

    project_slug = str(project_record.get("slug") or project_ref).strip()
    version_slug = str(version_record.get("slug") or version_ref).strip()
    return BrowseExportScope(
        tenant_slug=tenant_slug,
        project_slug=project_slug,
        version_slug=version_slug,
        version_id=version_id,
    )


def build_schema_export_path(scope: BrowseExportScope) -> str:
    """Return the published OpenAPI export path."""
    tenant = quote(scope.tenant_slug, safe="")
    project = quote(scope.project_slug, safe="")
    version = quote(scope.version_slug, safe="")
    return api_paths.schema_export(tenant, project, version)


def build_arazzo_export_path(scope: BrowseExportScope) -> str:
    tenant = quote(scope.tenant_slug, safe="")
    project = quote(scope.project_slug, safe="")
    version = quote(scope.version_slug, safe="")
    return api_paths.arazzo_export(tenant, project, version)
