"""Catalog items from the command line — live refresh (MFI-31.1, #4398).

``apiome catalog refresh show|set|check|off`` manage whether a catalog item is re-checked against
its live source (GraphQL introspection or gRPC server reflection), the same calls the item's
**Live refresh** card makes. ``set`` stores the cadence (``off``, ``manual``, ``hourly``,
``daily``, ``weekly``), the adapter, the endpoint and an optional credential; ``check`` runs one
check now and exits ``7`` when it failed, so a pipeline can gate on it.

``apiome catalog refresh-policy show|set`` read and flip the workspace kill switch.

``apiome catalog drift list|dismiss`` read an item's drift — the classified change (safe, dangerous,
breaking) each refresh-created version brought — and clear its badge; ``apiome catalog drift-alerts
show|set`` read and change who hears about drift and when (MFI-31.3, #4400).

A credential never travels on the command line: ``--credentials-file`` names a JSON file (or
``-`` for standard input) with the type's fields. ``--format json`` (or the global ``--json``)
prints the API response.
"""

from __future__ import annotations

import sys
from typing import Any

import httpx
import typer

from apiome_cli.client import api_paths
from apiome_cli.client.catalog_drift import (
    DELIVERIES,
    alerts_body,
    alerts_rows,
    change_rows,
    event_rows,
)
from apiome_cli.client.catalog_refresh import (
    AUTH_TYPES,
    CADENCES,
    refresh_body,
    refresh_rows,
)
from apiome_cli.client.connectors import read_credentials, refusal
from apiome_cli.client.errors import http_exit_code
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.exit_codes import EXIT_REFRESH_CHECK_FAILED
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json, emit_list_table, json_mode_from_context
from apiome_cli.terminal import confirm_action

app = typer.Typer(
    name="catalog",
    help="Catalog items: keep an item fresh from its live source and watch its drift.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

refresh_app = typer.Typer(
    name="refresh",
    help="Re-check a catalog item against its live GraphQL or gRPC endpoint on a cadence.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

policy_app = typer.Typer(
    name="refresh-policy",
    help="The workspace switch for catalog item refresh.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

drift_app = typer.Typer(
    name="drift",
    help="What a live refresh changed in an item: classified drift and its badge.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

alerts_app = typer.Typer(
    name="drift-alerts",
    help="Who hears about catalog drift, and when: the workspace's drift alert settings.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

app.add_typer(refresh_app, name="refresh")
app.add_typer(policy_app, name="refresh-policy")
app.add_typer(drift_app, name="drift")
app.add_typer(alerts_app, name="drift-alerts")

_ROW_COLUMNS = (("Field", "field", None), ("Value", "value", None))
_FORMATS = ("table", "json")


@app.callback(invoke_without_command=True)
def catalog_group(ctx: typer.Context) -> None:
    """Catalog command group."""
    group_callback_without_subcommand(ctx)


@refresh_app.callback(invoke_without_command=True)
def refresh_group(ctx: typer.Context) -> None:
    """Catalog item refresh command group."""
    group_callback_without_subcommand(ctx)


@policy_app.callback(invoke_without_command=True)
def policy_group(ctx: typer.Context) -> None:
    """Catalog refresh policy command group."""
    group_callback_without_subcommand(ctx)


@drift_app.callback(invoke_without_command=True)
def drift_group(ctx: typer.Context) -> None:
    """Catalog drift command group."""
    group_callback_without_subcommand(ctx)


@alerts_app.callback(invoke_without_command=True)
def alerts_group(ctx: typer.Context) -> None:
    """Catalog drift alerts command group."""
    group_callback_without_subcommand(ctx)


def _format(ctx: typer.Context, output_format: str) -> str:
    """Resolve ``--format`` (``table`` | ``json``); the global ``--json`` wins."""
    fmt = (output_format or "table").strip().lower()
    if json_mode_from_context(ctx):
        return "json"
    if fmt not in _FORMATS:
        raise typer.BadParameter("must be one of table, json", param_hint="--format")
    return fmt


def _format_option() -> Any:
    return typer.Option("table", "--format", help="Output: table (default) or json (the API response).")


def _expect(response: httpx.Response) -> httpx.Response:
    """Return a successful response, or print REST's reason and exit (4xx → 2, 5xx → 1)."""
    if response.is_success:
        return response
    message, _code = refusal(response)
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(http_exit_code(response.status_code))


def _print_refresh(body: dict, fmt: str) -> None:
    """Print one refresh answer as JSON or a field table."""
    if fmt == "json":
        emit_json(body)
    else:
        emit_list_table(refresh_rows(body), _ROW_COLUMNS)


@refresh_app.command("show")
def show_refresh(
    ctx: typer.Context,
    item_id: str = typer.Argument(..., help="Catalog item id."),
    output_format: str = _format_option(),
) -> None:
    """Show an item's refresh setting and last check (GET …/refresh); never its credential."""
    fmt = _format(ctx, output_format)
    client, tenant = tenant_scoped_client(ctx)
    _print_refresh(_expect(client.get_raw(api_paths.catalog_refresh(tenant, item_id))).json(), fmt)


@refresh_app.command("set")
def set_refresh(
    ctx: typer.Context,
    item_id: str = typer.Argument(..., help="Catalog item id."),
    endpoint: str = typer.Option(
        ..., "--endpoint", help="The live endpoint: an http(s) URL for GraphQL, host:port for gRPC."
    ),
    adapter: str = typer.Option("graphql", "--adapter", help="How to discover it: graphql or grpc."),
    cadence: str = typer.Option(
        "daily", "--cadence", help=f"How often: {', '.join(CADENCES)} (off keeps the setting, checks nothing)."
    ),
    secure: bool = typer.Option(False, "--tls/--no-tls", help="gRPC only: open a TLS channel."),
    auth_type: str | None = typer.Option(
        None,
        "--auth-type",
        help=f"Credential type: {', '.join(AUTH_TYPES)}. Omit to keep the stored credential; none clears it.",
    ),
    credentials_file: str | None = typer.Option(
        None,
        "--credentials-file",
        help='JSON file with the credential fields (- for stdin), e.g. {"token": "…"}.',
    ),
    keep_versions: int | None = typer.Option(
        None,
        "--keep-versions",
        min=1,
        max=1000,
        help="Keep the last N versions a refresh creates (1-1000; default 50). Tagged, breaking-drift and "
        "conversion-source versions are always kept. Omit to keep the stored value.",
    ),
    output_format: str = _format_option(),
) -> None:
    """Create or replace an item's refresh setting (PUT …/refresh).

    Changing the adapter or endpoint resets the check history. Exit codes: 0 saved, 1 unreachable,
    2 rejected (unknown item, adapter that cannot be refreshed, unsafe URL, bad credential).
    """
    fmt = _format(ctx, output_format)
    if cadence not in CADENCES:
        raise typer.BadParameter(f"must be one of {', '.join(CADENCES)}", param_hint="--cadence")
    if auth_type is not None and auth_type not in AUTH_TYPES:
        raise typer.BadParameter(f"must be one of {', '.join(AUTH_TYPES)}", param_hint="--auth-type")
    try:
        stdin_text = sys.stdin.read() if credentials_file == "-" else None
        credentials = read_credentials(credentials_file, stdin_text)
        body = refresh_body(
            cadence=cadence,
            adapter=adapter,
            endpoint=endpoint,
            secure=secure,
            auth_type=auth_type,
            credentials=credentials,
            keep_versions=keep_versions,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--credentials-file") from exc
    client, tenant = tenant_scoped_client(ctx)
    _print_refresh(_expect(client.put_raw(api_paths.catalog_refresh(tenant, item_id), json=body)).json(), fmt)


@refresh_app.command("check")
def check_refresh(
    ctx: typer.Context,
    item_id: str = typer.Argument(..., help="Catalog item id."),
    output_format: str = _format_option(),
) -> None:
    """Run one live check now (POST …/refresh/check) and print the outcome.

    Exit codes: 0 the check ran (unchanged or changed), 7 the check failed (the reason is
    printed; the item is unchanged), 1 unreachable, 2 rejected (no setting, cadence off, refresh
    switched off for the workspace).
    """
    fmt = _format(ctx, output_format)
    client, tenant = tenant_scoped_client(ctx)
    body = _expect(client.post_raw(api_paths.catalog_refresh_check(tenant, item_id))).json()
    _print_refresh(body, fmt)
    if body.get("status") == "failed":
        raise typer.Exit(EXIT_REFRESH_CHECK_FAILED)


@refresh_app.command("off")
def remove_refresh(
    ctx: typer.Context,
    item_id: str = typer.Argument(..., help="Catalog item id."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
) -> None:
    """Remove an item's refresh setting and its stored credential (DELETE …/refresh).

    To pause checks but keep the setting, use ``set --cadence off`` instead. Asks first unless
    ``--yes`` is passed (required when not interactive).
    """
    confirm_action(
        f"Remove the refresh setting of {item_id}? Its stored credential is destroyed.",
        skip=yes,
        escape_flag="--yes",
    )
    client, tenant = tenant_scoped_client(ctx)
    _expect(client.delete_raw(api_paths.catalog_refresh(tenant, item_id)))
    typer.echo(f"Removed the refresh setting of {item_id}.", err=json_mode_from_context(ctx))
    if json_mode_from_context(ctx):
        emit_json({"itemId": item_id, "deleted": True})


@policy_app.command("show")
def show_policy(ctx: typer.Context, output_format: str = _format_option()) -> None:
    """Show whether catalog item refresh is on for the workspace (GET …/refresh-policy)."""
    fmt = _format(ctx, output_format)
    client, tenant = tenant_scoped_client(ctx)
    body = _expect(client.get_raw(api_paths.catalog_refresh_policy(tenant))).json()
    if fmt == "json":
        emit_json(body)
    else:
        typer.echo(f"Catalog refresh: {'on' if body.get('enabled') else 'off'}")


@policy_app.command("set")
def set_policy(
    ctx: typer.Context,
    enabled: bool = typer.Option(
        ..., "--enabled/--disabled", help="Turn catalog item refresh on or off for the whole workspace."
    ),
    output_format: str = _format_option(),
) -> None:
    """Turn catalog item refresh on or off for the workspace (PUT …/refresh-policy; imports:edit).

    Off stops scheduled and manual checks for every item; each item's setting is kept.
    """
    fmt = _format(ctx, output_format)
    client, tenant = tenant_scoped_client(ctx)
    body = _expect(client.put_raw(api_paths.catalog_refresh_policy(tenant), json={"enabled": enabled})).json()
    if fmt == "json":
        emit_json(body)
    else:
        typer.echo(f"Catalog refresh: {'on' if body.get('enabled') else 'off'}")


# ---------------------------------------------------------------------------------------
# Drift (MFI-31.3)
# ---------------------------------------------------------------------------------------

_EVENT_COLUMNS = (
    ("Event", "id", None),
    ("Severity", "severity", None),
    ("Versions", "versions", None),
    ("Changes", "changes", None),
    ("Trigger", "trigger", None),
    ("State", "state", None),
)
_CHANGE_COLUMNS = (("Severity", "severity", None), ("Change", "key", None), ("Why", "rationale", None))


@drift_app.command("list")
def list_drift(
    ctx: typer.Context,
    item_id: str = typer.Argument(..., help="Catalog item id."),
    changes: bool = typer.Option(False, "--changes", help="Also list the newest event's classified changes."),
    output_format: str = _format_option(),
) -> None:
    """List an item's drift events, newest first (GET …/drift).

    Each event is a version a live refresh added, graded by its worst change: safe, dangerous or
    breaking.
    """
    fmt = _format(ctx, output_format)
    client, tenant = tenant_scoped_client(ctx)
    body = _expect(client.get_raw(api_paths.catalog_drift_events(tenant, item_id))).json()
    if fmt == "json":
        emit_json(body)
        return
    events = body.get("events") or []
    emit_list_table(
        event_rows(events), _EVENT_COLUMNS, empty_message="No drift recorded for this item.", min_width=140
    )
    if changes and events:
        typer.echo("")
        emit_list_table(
            change_rows(events[0]), _CHANGE_COLUMNS, empty_message="No classified changes.", min_width=140
        )


@drift_app.command("dismiss")
def dismiss_drift(
    ctx: typer.Context,
    item_id: str = typer.Argument(..., help="Catalog item id."),
    event_id: str = typer.Argument(..., help="Drift event id (from `apiome catalog drift list`)."),
    output_format: str = _format_option(),
) -> None:
    """Clear a drift event's badge and banner (POST …/drift/{event}/dismiss; projects:edit).

    The event and its changes are kept. Dismissing twice changes nothing.
    """
    fmt = _format(ctx, output_format)
    client, tenant = tenant_scoped_client(ctx)
    body = _expect(client.post_raw(api_paths.catalog_drift_dismiss(tenant, item_id, event_id))).json()
    if fmt == "json":
        emit_json(body)
    else:
        typer.echo(f"Dismissed drift {event_id} ({body.get('severity')}, {body.get('versionLabel')}).")


def _print_alerts(body: dict, fmt: str) -> None:
    """Print the drift alert settings as JSON or a field table."""
    if fmt == "json":
        emit_json(body)
    else:
        emit_list_table(alerts_rows(body), _ROW_COLUMNS)


@alerts_app.command("show")
def show_alerts(ctx: typer.Context, output_format: str = _format_option()) -> None:
    """Show the workspace's drift alert settings (GET …/drift-notifications)."""
    fmt = _format(ctx, output_format)
    client, tenant = tenant_scoped_client(ctx)
    _print_alerts(_expect(client.get_raw(api_paths.catalog_drift_alerts(tenant))).json(), fmt)


@alerts_app.command("set")
def set_alerts(
    ctx: typer.Context,
    breaking: bool | None = typer.Option(None, "--breaking/--no-breaking", help="Announce breaking drift."),
    dangerous: bool | None = typer.Option(None, "--dangerous/--no-dangerous", help="Announce dangerous drift."),
    safe: bool | None = typer.Option(None, "--safe/--no-safe", help="Announce safe drift (off: badge only)."),
    delivery: str | None = typer.Option(
        None, "--delivery", help=f"How to send: {', '.join(DELIVERIES)} (one webhook a day listing it all)."
    ),
    breaking_immediate: bool | None = typer.Option(
        None,
        "--breaking-immediate/--breaking-in-digest",
        help="With daily_digest: send breaking drift right away, or hold it for the digest too.",
    ),
    email: bool | None = typer.Option(
        None, "--email/--no-email", help="Opt in to drift email (stored; email is not sent yet)."
    ),
    output_format: str = _format_option(),
) -> None:
    """Change the workspace's drift alert settings (PUT …/drift-notifications; imports:edit).

    Options left out keep their current value. Announcements go to the workspace's webhooks and
    the item's owner team; a version made by `apiome catalog refresh check` is never announced.
    """
    fmt = _format(ctx, output_format)
    client, tenant = tenant_scoped_client(ctx)
    current = _expect(client.get_raw(api_paths.catalog_drift_alerts(tenant))).json()
    try:
        body = alerts_body(
            current,
            notifyBreaking=breaking,
            notifyDangerous=dangerous,
            notifySafe=safe,
            delivery=delivery,
            breakingImmediate=breaking_immediate,
            emailEnabled=email,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--delivery") from exc
    _print_alerts(_expect(client.put_raw(api_paths.catalog_drift_alerts(tenant), json=body)).json(), fmt)
