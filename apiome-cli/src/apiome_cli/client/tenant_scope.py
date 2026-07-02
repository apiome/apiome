"""Resolve configured tenant scope to ``tenant_slug`` for ``/v1/...`` routes."""

from __future__ import annotations

from uuid import UUID

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.client.list_response import paginate_offset_list
from apiome_cli.config import CliSettings
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.extract.slug import slugify_project_name

_MISSING_TENANT_SCOPE_MESSAGE = (
    "Tenant scope required for this command. "
    "Set --tenant or APIOME_TENANT_ID (UUID or slug)."
)
_MISSING_TENANT_MESSAGE = "Configured tenant was not found on the server."
_TENANT_LOOKUP_LIMIT = 200


def normalize_tenant_ref(value: str) -> str:
    """Validate and normalize a tenant config value (UUID or URL slug)."""
    text = value.strip()
    if not text:
        raise ValueError("tenant cannot be empty")
    try:
        UUID(text)
        return text
    except ValueError:
        return slugify_project_name(text)


def _slug_from_membership(item: dict[str, object]) -> str | None:
    slug = item.get("slug")
    if isinstance(slug, str) and slug.strip():
        return slug.strip()
    return None


def resolve_tenant_slug(settings: CliSettings, client: RestClient) -> str | None:
    """Return ``tenant_slug`` for path segments, resolving UUIDs via ``GET /v1/tenants/me``."""
    if settings.tenant_id is None:
        return None

    ref = settings.tenant_id.strip()
    if not ref:
        return None

    try:
        tenant_uuid = UUID(ref)
    except ValueError:
        return slugify_project_name(ref)

    items, _total = paginate_offset_list(
        client,
        api_paths.tenants_me(),
        limit=_TENANT_LOOKUP_LIMIT,
        fetch_all=True,
    )
    matches = [
        item
        for item in items
        if isinstance(item.get("slug"), str) and item.get("slug")
    ]
    if len(items) == 1 and len(matches) == 1:
        slug = _slug_from_membership(matches[0])
        if slug is not None:
            return slug

    for item in items:
        slug = _slug_from_membership(item)
        if slug is None:
            continue
        try:
            info = client.get(api_paths.tenant(slug)).json()
        except SystemExit:
            continue
        if isinstance(info, dict) and str(info.get("id", "")) == str(tenant_uuid):
            return slug

    typer.echo(_MISSING_TENANT_MESSAGE, err=True)
    raise typer.Exit(EXIT_USAGE)


def require_tenant_slug(settings: CliSettings, client: RestClient) -> str:
    """Return ``tenant_slug`` or exit with usage code when tenant scope is missing."""
    slug = resolve_tenant_slug(settings, client)
    if slug is None:
        typer.echo(_MISSING_TENANT_SCOPE_MESSAGE, err=True)
        raise typer.Exit(EXIT_USAGE)
    return slug
