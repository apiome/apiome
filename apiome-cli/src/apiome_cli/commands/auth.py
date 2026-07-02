"""Auth identity and tenant-context commands (session bearer or API key)."""

from __future__ import annotations

import typer

from apiome_cli.cli_context import (
    insecure_from_context,
    json_mode_from_context,
    settings_from_context,
    timeout_from_context,
)
from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.client.list_response import paginate_offset_list
from apiome_cli.config import require_api_key, require_session_token
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import ListColumn, emit_json, emit_list_table, emit_record_table

app = typer.Typer(
    name="auth",
    help="Inspect signed-in identity and accessible tenants.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def auth_group(ctx: typer.Context) -> None:
    """Auth command group."""
    group_callback_without_subcommand(ctx)


def _auth_client(ctx: typer.Context, *, session: bool) -> RestClient:
    settings = settings_from_context(ctx)
    if session:
        require_session_token(settings)
    else:
        require_api_key(settings)
    return RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
        session=session,
    )


def _fetch_tenants_me(ctx: typer.Context, *, session: bool) -> tuple[list[dict], int]:
    client = _auth_client(ctx, session=session)
    return paginate_offset_list(
        client,
        api_paths.tenants_me(),
        limit=100,
        fetch_all=True,
    )


_TENANT_COLUMNS: tuple[ListColumn, ...] = (
    ("Slug", "slug", None),
    ("Name", "name", None),
    ("Role", "role", None),
)

_WHOAMI_FIELDS = (
    ("Slug", "slug", None),
    ("Name", "name", None),
    ("Role", "role", None),
)


@app.command("whoami")
def whoami(ctx: typer.Context) -> None:
    """Show accessible tenant membership (GET /v1/tenants/me)."""
    settings = settings_from_context(ctx)
    session = settings.session_token_value() is not None
    items, total = _fetch_tenants_me(ctx, session=session)
    if json_mode_from_context(ctx):
        emit_json({"total": total, "items": items})
        return
    if not items:
        typer.echo("No tenant memberships returned.")
        return
    if len(items) == 1:
        emit_record_table(items[0], _WHOAMI_FIELDS)
        return
    emit_list_table(items, _TENANT_COLUMNS, total=total)


@app.command("status")
def status(ctx: typer.Context) -> None:
    """Alias for ``auth whoami`` (GET /v1/tenants/me)."""
    whoami(ctx)


@app.command("tenants")
def tenants(ctx: typer.Context) -> None:
    """List tenants accessible to the caller (GET /v1/tenants/me)."""
    settings = settings_from_context(ctx)
    session = settings.session_token_value() is not None
    items, total = _fetch_tenants_me(ctx, session=session)
    if json_mode_from_context(ctx):
        emit_json({"total": total, "items": items})
        return
    emit_list_table(items, _TENANT_COLUMNS, total=total)
