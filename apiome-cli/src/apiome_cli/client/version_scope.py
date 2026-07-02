"""Shared project/version scope options and resolution for path/workflow commands."""

from __future__ import annotations

from uuid import UUID

import typer

from apiome_cli.cli_context import insecure_from_context, settings_from_context, timeout_from_context
from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.client.project_version_resolve import resolve_project_uuid, resolve_version_uuid
from apiome_cli.client.tenant_scope import require_tenant_slug
from apiome_cli.config import require_api_key


def tier2_client(ctx: typer.Context) -> RestClient:
    """Build an authenticated REST client after enforcing Tier 2 API key configuration."""
    settings = settings_from_context(ctx)
    require_api_key(settings)
    return RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
    )


def tenant_scoped_client(ctx: typer.Context) -> tuple[RestClient, str]:
    """Return authenticated client and ``tenant_slug`` for tenant-scoped routes."""
    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
    )
    tenant_slug = require_tenant_slug(settings, client)
    return client, tenant_slug


def resolve_version_scope(
    ctx: typer.Context,
    *,
    project: str,
    version: str,
) -> tuple[RestClient, str, UUID, UUID]:
    """Resolve ``--project`` and ``--version`` to UUIDs and return tenant scope.

    Returns
    -------
    tuple[RestClient, str, UUID, UUID]
        Client, tenant slug, project id, and version record id.
    """
    client, tenant_slug = tenant_scoped_client(ctx)
    project_id = resolve_project_uuid(client, tenant_slug, project)
    version_id = resolve_version_uuid(
        client,
        tenant_slug=tenant_slug,
        project_id=project_id,
        version_ref=version,
    )
    return client, tenant_slug, project_id, version_id


def version_paths_base(tenant_slug: str, version_id: UUID) -> str:
    """Base path for version-scoped path CRUD routes."""
    return api_paths.paths(tenant_slug, version_id)
