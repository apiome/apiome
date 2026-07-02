"""Personal access token commands (session bearer token)."""

from __future__ import annotations

from uuid import UUID

import typer

from apiome_cli.cli_context import (
    insecure_from_context,
    json_mode_from_context,
    settings_from_context,
    timeout_from_context,
)
from apiome_cli.client.http import RestClient
from apiome_cli.config import require_session_token
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import (
    ListColumn,
    RecordField,
    emit_json,
    emit_list_response,
    emit_record_response,
)

app = typer.Typer(
    name="tokens",
    help="List, create, and revoke personal access tokens.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def tokens_group(ctx: typer.Context) -> None:
    """Tokens command group."""
    group_callback_without_subcommand(ctx)


def _session_client(ctx: typer.Context) -> RestClient:
    """Build a REST client authenticated with the configured session bearer token."""
    settings = settings_from_context(ctx)
    require_session_token(settings)
    return RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
        session=True,
    )


_PAT_LIST_COLUMNS: tuple[ListColumn, ...] = (
    ("ID", "id", None),
    ("Name", "name", None),
    ("Prefix", "token_prefix", None),
    ("Scopes", "scopes", lambda value: ", ".join(value) if isinstance(value, list) else ""),
    ("Last used", "last_used_on", None),
    ("Expires", "expires_on", None),
    ("Created", "created_on", None),
)

_PAT_CREATE_FIELDS: tuple[RecordField, ...] = (
    ("ID", "id", None),
    ("Name", "name", None),
    ("Prefix", "token_prefix", None),
    ("Scopes", "scopes", lambda value: ", ".join(value) if isinstance(value, list) else ""),
    ("Expires", "expires_on", None),
    ("Created", "created_on", None),
)


@app.command("list")
def list_tokens(ctx: typer.Context) -> None:
    """List personal access tokens (GET /auth/personal-access-tokens)."""
    response = _session_client(ctx).get("/auth/personal-access-tokens")
    payload = response.json()
    if not isinstance(payload, dict):
        emit_json(payload)
        return

    emit_list_response(payload, _PAT_LIST_COLUMNS, json_mode=json_mode_from_context(ctx))


@app.command("create")
def create_token(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Human-readable label for the token."),
    scope: list[str] = typer.Option(
        [],
        "--scope",
        help="Scope name (repeat for multiple scopes).",
    ),
    ttl_days: int = typer.Option(
        0,
        "--ttl-days",
        min=0,
        help="Days until expiry (0 = no expiry per platform TTL rules).",
    ),
) -> None:
    """Create a PAT; the full secret is shown only in this command output."""
    body: dict[str, object] = {"name": name, "ttl_days": ttl_days}
    if scope:
        body["scopes"] = scope

    response = _session_client(ctx).post(
        "/auth/personal-access-tokens",
        json=body,
    )
    payload = response.json()
    if not isinstance(payload, dict):
        emit_json(payload)
        return

    if json_mode_from_context(ctx):
        emit_json(payload)
        return

    token = payload.get("token")
    display = {key: value for key, value in payload.items() if key != "token"}
    emit_record_response(display, _PAT_CREATE_FIELDS, json_mode=False)

    if isinstance(token, str) and token:
        typer.echo("")
        typer.echo("Token (save now — it will not be shown again):")
        typer.echo(token)


@app.command("revoke")
def revoke_token(
    ctx: typer.Context,
    pat_id: UUID = typer.Argument(..., help="Personal access token UUID."),
) -> None:
    """Revoke a personal access token (DELETE /auth/personal-access-tokens/{id})."""
    response = _session_client(ctx).delete(f"/auth/personal-access-tokens/{pat_id}")
    payload = response.json()
    if json_mode_from_context(ctx):
        emit_json(payload)
        return

    revoked = payload.get("revoked") if isinstance(payload, dict) else None
    if revoked is True:
        typer.echo(f"Revoked personal access token {pat_id}.")
    else:
        emit_json(payload)
