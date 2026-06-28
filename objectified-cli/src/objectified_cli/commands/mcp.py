"""MCP catalog endpoint commands (Tier 2 API key auth).

Thin client over the ``objectified-rest`` MCP catalog routes
(``/v1/mcp/{tenant_slug}/endpoints``). The command group registers an external
MCP server in the caller's tenant catalog, lists the registered endpoints, and
shows one endpoint by id. Tenant scope is resolved to a ``tenant_slug`` the same
way as ``repos`` (the server re-scopes from the token, not the URL slug).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import typer

from objectified_cli.cli_context import (
    insecure_from_context,
    json_mode_from_context,
    settings_from_context,
    timeout_from_context,
)
from objectified_cli.client import api_paths
from objectified_cli.client.http import RestClient
from objectified_cli.client.tenant_scope import require_tenant_slug
from objectified_cli.config import require_api_key
from objectified_cli.help_util import group_callback_without_subcommand
from objectified_cli.output import (
    ListColumn,
    RecordField,
    emit_json,
    emit_list_table,
    emit_record_table,
)

app = typer.Typer(
    name="mcp",
    help="Register, list, and inspect MCP catalog endpoints.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

# Mirrors ``MCP_ENDPOINT_TRANSPORTS`` / ``MCP_ENDPOINT_VISIBILITIES`` in the REST
# models; the server re-validates, but rejecting locally yields a usage exit code
# and a clearer message than a round-trip 422.
_MCP_TRANSPORTS = frozenset({"streamable_http", "sse", "stdio"})
_MCP_VISIBILITIES = frozenset({"private", "public"})

# Widen the render target for the wide list table when output is piped/CI, so
# columns are not squeezed to the 80-column fallback (see ``emit_list_table``).
_MCP_LIST_MIN_WIDTH = 140


@app.callback(invoke_without_command=True)
def mcp_group(ctx: typer.Context) -> None:
    """MCP catalog command group."""
    group_callback_without_subcommand(ctx)


def _scoped_client(ctx: typer.Context) -> tuple[RestClient, str]:
    """Build an API-key REST client and resolve the configured tenant slug."""
    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
    )
    tenant_slug = require_tenant_slug(settings, client)
    return client, tenant_slug


def _json_output(ctx: typer.Context, output: str | None) -> bool:
    """Return True when global ``--json`` or local ``--output json`` was requested."""
    if output == "json":
        return True
    if output is not None and output != "table":
        msg = "--output must be 'table' or 'json'."
        raise typer.BadParameter(msg)
    return json_mode_from_context(ctx)


def _normalize_transport(transport: str) -> str:
    """Validate ``--transport`` against the REST transport enum."""
    normalized = transport.strip().lower()
    if normalized in _MCP_TRANSPORTS:
        return normalized
    msg = "--transport must be streamable_http, sse, or stdio."
    raise typer.BadParameter(msg)


def _normalize_visibility(visibility: str) -> str:
    """Validate ``--visibility`` against the REST visibility enum."""
    normalized = visibility.strip().lower()
    if normalized in _MCP_VISIBILITIES:
        return normalized
    msg = "--visibility must be 'private' or 'public'."
    raise typer.BadParameter(msg)


def _credential_body(bearer: str | None, header: str | None) -> dict[str, Any] | None:
    """Build a credential upsert body from ``--bearer`` / ``--header``.

    ``--bearer TOKEN`` seals a bearer token; ``--header NAME:VALUE`` seals a
    custom header secret. The two are mutually exclusive. Returns ``None`` when
    neither flag was supplied (the endpoint stays anonymous).
    """
    if bearer is not None and header is not None:
        msg = "Use either --bearer or --header, not both."
        raise typer.BadParameter(msg)
    if bearer is not None:
        token = bearer.strip()
        if not token:
            msg = "--bearer must not be empty."
            raise typer.BadParameter(msg)
        return {"auth_type": "bearer", "payload": {"token": token}}
    if header is not None:
        name, sep, value = header.partition(":")
        if not sep or not name.strip() or not value.strip():
            msg = "--header must be 'Name:Value' with a non-empty name and value."
            raise typer.BadParameter(msg)
        return {
            "auth_type": "header",
            "payload": {"name": name.strip(), "value": value.strip()},
        }
    return None


def _format_optional(value: object) -> str:
    """Render an optional cell, leaving missing values blank."""
    return "" if value in (None, "") else str(value)


_MCP_LIST_COLUMNS: tuple[ListColumn, ...] = (
    ("ID", "id", None),
    ("Name", "name", None),
    ("Slug", "slug", None),
    ("Transport", "transport", None),
    ("Visibility", "visibility", None),
    ("URL", "endpoint_url", None),
    ("Last Discovered", "last_discovered_at", _format_optional),
)

_MCP_SHOW_FIELDS: tuple[RecordField, ...] = (
    ("ID", "id", None),
    ("Name", "name", None),
    ("Slug", "slug", None),
    ("URL", "endpoint_url", None),
    ("Transport", "transport", None),
    ("Description", "description", _format_optional),
    ("Category", "category", _format_optional),
    ("Visibility", "visibility", None),
    ("Published", "published", None),
    ("Enabled", "enabled", None),
    ("Discovery cadence (s)", "discovery_cadence_seconds", _format_optional),
    ("Last discovered", "last_discovered_at", _format_optional),
    ("Last discovery status", "last_discovery_status", _format_optional),
    ("Consecutive failures", "consecutive_failures", None),
    ("Quarantined", "quarantined", None),
    ("Quarantine reason", "quarantine_reason", _format_optional),
    ("Current version", "current_version_id", _format_optional),
    ("Created", "created_at", _format_optional),
    ("Updated", "updated_at", _format_optional),
)


@app.command("register")
def register_endpoint(
    ctx: typer.Context,
    name: str = typer.Option(
        ...,
        "--name",
        help="Human-readable endpoint name.",
    ),
    url: str = typer.Option(
        ...,
        "--url",
        help="MCP server URL (http/https for streamable_http/sse).",
    ),
    transport: str = typer.Option(
        "streamable_http",
        "--transport",
        help="MCP transport: streamable_http (default), sse, or stdio.",
    ),
    slug: str | None = typer.Option(
        None,
        "--slug",
        help="Optional catalog slug; derived from --name and uniquified when omitted.",
    ),
    description: str | None = typer.Option(
        None,
        "--description",
        help="Optional endpoint description.",
    ),
    category: str | None = typer.Option(
        None,
        "--category",
        help="Optional catalog category.",
    ),
    visibility: str = typer.Option(
        "private",
        "--visibility",
        help="Catalog visibility: private (default) or public.",
    ),
    bearer: str | None = typer.Option(
        None,
        "--bearer",
        help="Seal a bearer token as the endpoint's outbound credential.",
    ),
    header: str | None = typer.Option(
        None,
        "--header",
        help="Seal a custom header secret as 'Name:Value'.",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """Register an MCP server in the tenant catalog (POST /v1/mcp/{tenant}/endpoints)."""
    trimmed_name = name.strip()
    if not trimmed_name:
        msg = "--name must not be empty."
        raise typer.BadParameter(msg)
    trimmed_url = url.strip()
    if not trimmed_url:
        msg = "--url must not be empty."
        raise typer.BadParameter(msg)

    credential = _credential_body(bearer, header)

    body: dict[str, Any] = {
        "name": trimmed_name,
        "endpoint_url": trimmed_url,
        "transport": _normalize_transport(transport),
        "visibility": _normalize_visibility(visibility),
    }
    if slug is not None and slug.strip():
        body["slug"] = slug.strip()
    if description is not None and description.strip():
        body["description"] = description.strip()
    if category is not None and category.strip():
        body["category"] = category.strip()

    client, tenant_slug = _scoped_client(ctx)

    response = client.post(api_paths.mcp_endpoints(tenant_slug), json=body)
    payload = response.json()
    endpoint = payload.get("endpoint") if isinstance(payload, dict) else None

    # Attach the outbound credential once the endpoint exists (PUT credentials).
    if credential is not None and isinstance(endpoint, dict):
        endpoint_id = endpoint.get("id")
        if isinstance(endpoint_id, str) and endpoint_id:
            client.put(
                api_paths.mcp_endpoint_credentials(tenant_slug, endpoint_id),
                json=credential,
            )

    if _json_output(ctx, output):
        emit_json(payload)
        return

    if isinstance(endpoint, dict):
        emit_record_table(endpoint, _MCP_SHOW_FIELDS)
        if credential is not None:
            typer.echo(f"Credential set ({credential['auth_type']}).")
    else:
        emit_json(payload)


@app.command("list")
def list_endpoints(
    ctx: typer.Context,
    output: str | None = typer.Option(
        None,
        "--output",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """List MCP catalog endpoints (GET /v1/mcp/{tenant}/endpoints)."""
    client, tenant_slug = _scoped_client(ctx)
    response = client.get(api_paths.mcp_endpoints(tenant_slug))
    payload = response.json()

    if _json_output(ctx, output):
        emit_json(payload)
        return

    endpoints = payload.get("endpoints") if isinstance(payload, dict) else None
    if not isinstance(endpoints, list):
        emit_json(payload)
        return
    emit_list_table(
        endpoints,
        _MCP_LIST_COLUMNS,
        empty_message="No MCP endpoints.",
        min_width=_MCP_LIST_MIN_WIDTH,
    )


@app.command("show")
def show_endpoint(
    ctx: typer.Context,
    endpoint_id: UUID = typer.Argument(..., help="MCP endpoint UUID."),
    output: str | None = typer.Option(
        None,
        "--output",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """Show one MCP catalog endpoint (GET /v1/mcp/{tenant}/endpoints/{id})."""
    client, tenant_slug = _scoped_client(ctx)
    response = client.get(api_paths.mcp_endpoint(tenant_slug, endpoint_id))
    payload = response.json()

    if _json_output(ctx, output):
        emit_json(payload)
        return

    endpoint = payload.get("endpoint") if isinstance(payload, dict) else None
    if not isinstance(endpoint, dict):
        emit_json(payload)
        return
    emit_record_table(endpoint, _MCP_SHOW_FIELDS)
