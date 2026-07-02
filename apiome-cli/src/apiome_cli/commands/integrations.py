"""Linked integration status commands (session bearer token)."""

from __future__ import annotations

import typer

from apiome_cli.cli_context import (
    insecure_from_context,
    json_mode_from_context,
    settings_from_context,
    timeout_from_context,
)
from apiome_cli.client.http import RestClient
from apiome_cli.config import require_session_token
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import (
    ListColumn,
    RecordField,
    emit_json,
    emit_list_table,
    emit_record_response,
)

app = typer.Typer(
    name="integrations",
    help="List and inspect linked workspace integrations.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def integrations_group(ctx: typer.Context) -> None:
    """Integrations command group."""
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


def _reauth_label(status: object) -> str:
    return "yes" if status == "expired" else ""


def _flatten_linked_accounts(payload: dict[str, object]) -> list[dict[str, object]]:
    """Flatten dashboard sections into rows for tabular output."""
    rows: list[dict[str, object]] = []
    sections = payload.get("sections")
    if not isinstance(sections, list):
        return rows
    for section in sections:
        if not isinstance(section, dict):
            continue
        category = section.get("category", "")
        items = section.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["category"] = category
            rows.append(row)
    return rows


def _find_integration(
    payload: dict[str, object],
    provider: str,
) -> dict[str, object] | None:
    needle = provider.casefold()
    for row in _flatten_linked_accounts(payload):
        value = row.get("provider")
        if isinstance(value, str) and value.casefold() == needle:
            return row
    return None


_INTEGRATION_LIST_COLUMNS: tuple[ListColumn, ...] = (
    ("Provider", "provider", None),
    ("Display name", "display_name", None),
    ("Category", "category", None),
    ("Status", "status", None),
    ("Reauth", "status", _reauth_label),
    ("Last sync", "last_sync_on", None),
    ("Expires", "expires_on", None),
    ("Errors", "error_count", None),
    ("Scope", "scope", None),
)

_INTEGRATION_RECORD_FIELDS: tuple[RecordField, ...] = (
    ("Provider", "provider", None),
    ("Display name", "display_name", None),
    ("Category", "category", None),
    ("Status", "status", None),
    ("Reauth required", "status", _reauth_label),
    ("Summary", "summary", None),
    ("External ref", "external_account_ref", None),
    ("Last sync", "last_sync_on", None),
    ("Expires", "expires_on", None),
    ("Error count", "error_count", None),
    ("Last error", "last_error", None),
    ("Scope", "scope", None),
)


@app.command("list")
def list_integrations(ctx: typer.Context) -> None:
    """List linked integrations with status and sync metadata (GET /dashboard/linked-accounts)."""
    response = _session_client(ctx).get("/dashboard/linked-accounts")
    payload = response.json()
    if not isinstance(payload, dict):
        emit_json(payload)
        return

    if json_mode_from_context(ctx):
        emit_json(payload)
        return

    rows = _flatten_linked_accounts(payload)
    emit_list_table(rows, _INTEGRATION_LIST_COLUMNS, empty_message="No integrations.")


@app.command("show")
def show_integration(
    ctx: typer.Context,
    provider: str = typer.Argument(..., help="Integration provider id (e.g. github, okta, slack)."),
) -> None:
    """Show one integration's status, last sync, and re-auth requirements."""
    response = _session_client(ctx).get("/dashboard/linked-accounts")
    payload = response.json()
    if not isinstance(payload, dict):
        emit_json(payload)
        return

    match = _find_integration(payload, provider)
    if match is None:
        typer.echo(f"No integration found for provider {provider!r}.", err=True)
        raise typer.Exit(EXIT_USAGE)

    if json_mode_from_context(ctx):
        emit_json(match)
        return

    emit_record_response(match, _INTEGRATION_RECORD_FIELDS, json_mode=False)
