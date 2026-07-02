"""Resolve configured tenant slug or UUID to a tenant id via REST."""

from __future__ import annotations

from uuid import UUID

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.client.tenant_scope import require_tenant_slug
from apiome_cli.config import CliSettings
from apiome_cli.exit_codes import EXIT_USAGE

_MISSING_TENANT_SCOPE_MESSAGE = (
    "Tenant scope required for this command. "
    "Set --tenant or APIOME_TENANT_ID (UUID or slug)."
)


def require_tenant_uuid(settings: CliSettings, client: RestClient) -> UUID:
    """Return the configured tenant UUID, exiting when tenant scope is missing."""
    tenant_slug = require_tenant_slug(settings, client)
    info = client.get(api_paths.tenant(tenant_slug)).json()
    if not isinstance(info, dict) or not info.get("id"):
        typer.echo("Configured tenant was not found on the server.", err=True)
        raise typer.Exit(EXIT_USAGE)
    return UUID(str(info["id"]))


def resolve_tenant_uuid(settings: CliSettings, client: RestClient) -> UUID | None:
    """Return the tenant UUID for import overrides, resolving slugs via tenant info."""
    if settings.tenant_id is None:
        return None
    return require_tenant_uuid(settings, client)
