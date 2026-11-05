"""``apiome export auto …`` — auto-export on version publish (MFX-39.4).

An auto-export subscription runs an export preset on every publish of a project and delivers it through the
preset's delivery profile — unless the export's loss reaches the subscription's ``--halt-at`` (and the loss
was not pre-approved with ``--approve-loss``). A halted export is not delivered; the publisher and the
subscriber are notified, and ``apiome export auto release RUN`` delivers it anyway.
"""

from __future__ import annotations

from typing import Any

import typer

from apiome_cli.cli_context import (
    insecure_from_context,
    json_mode_from_context,
    settings_from_context,
    timeout_from_context,
)
from apiome_cli.client import api_paths
from apiome_cli.client.browse_scope import resolve_tenant_slug
from apiome_cli.client.errors import exit_on_api_error
from apiome_cli.client.http import RestClient
from apiome_cli.client.project_version_resolve import resolve_project_uuid
from apiome_cli.config import require_api_key
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import ListColumn, emit_json, emit_list_table
from apiome_cli.terminal import confirm_action

app = typer.Typer(
    name="auto",
    help="Run export presets on every publish of a project (auto-export), and see what each publish did.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

_HALT_HELP = ("Halt auto-delivery when the export's loss reaches this severity: critical (default: a severe or "
              "near-empty conversion, types-only, or a critical construct) or warn (any loss).")

_SUBSCRIPTION_COLUMNS: list[ListColumn] = [
    ("Project", "projectName", None),
    ("Preset", "presetName", None),
    ("Halt at", "haltAt", None),
    ("Loss approved", "approveLoss", lambda v: "yes" if v else "no"),
    ("Active", "active", lambda v: "yes" if v else "no"),
    ("ID", "id", None),
]

_RUN_COLUMNS: list[ListColumn] = [
    ("Created", "createdAt", None),
    ("Project", "projectName", None),
    ("Preset", "presetName", None),
    ("Status", "status", None),
    ("Loss", "lossSeverity", None),
    ("Why", "lossReasons", lambda v: "; ".join(v) if isinstance(v, list) else ""),
    ("Error", "errorCode", None),
    ("ID", "id", None),
]


@app.callback(invoke_without_command=True)
def auto_group(ctx: typer.Context) -> None:
    """Auto-export commands."""
    group_callback_without_subcommand(ctx)


def _client(ctx: typer.Context) -> tuple[RestClient, str]:
    """An authenticated client and the tenant slug."""
    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(settings, timeout=timeout_from_context(ctx), verify=not insecure_from_context(ctx))
    return client, resolve_tenant_slug(settings, client, tenant_override=None)


def _object(response: Any, what: str) -> dict[str, Any]:
    payload = response.json()
    if not isinstance(payload, dict):
        typer.echo(f"{what} response was not a JSON object.", err=True)
        raise typer.Exit(EXIT_ERROR)
    return payload


def _halt_at(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized not in ("warn", "critical"):
        typer.echo("--halt-at must be warn or critical.", err=True)
        raise typer.Exit(EXIT_USAGE)
    return normalized


def _emit_subscription(ctx: typer.Context, row: dict[str, Any], verb: str) -> None:
    if json_mode_from_context(ctx):
        emit_json(row)
        return
    approved = ", loss pre-approved" if row.get("approveLoss") else ""
    state = "" if row.get("active") else " (off)"
    typer.echo(f"{verb}: {row.get('presetName')!r} runs on every publish of {row.get('projectName')!r}, halting at "
               f"{row.get('haltAt')}{approved}{state} ({row.get('id')})")


@app.command("list", help="List the auto-export subscriptions (presets run on publish).")
def list_subscriptions(
    ctx: typer.Context,
    project: str | None = typer.Option(None, "--project", help="Only this project (id or slug)."),
    preset: str | None = typer.Option(None, "--preset", help="Only this preset (name or id)."),
) -> None:
    """List auto-export subscriptions."""
    client, tenant = _client(ctx)
    params = []
    if project:
        params.append(f"projectId={resolve_project_uuid(client, tenant, project)}")
    if preset:
        params.append(f"preset={preset}")
    path = api_paths.export_auto_subscriptions(tenant) + (f"?{'&'.join(params)}" if params else "")
    rows = _object(client.get(path), "Subscription list").get("subscriptions") or []
    if json_mode_from_context(ctx):
        emit_json({"subscriptions": rows})
        return
    emit_list_table(rows, _SUBSCRIPTION_COLUMNS, empty_message="No auto-export subscriptions.", min_width=160)


@app.command("add", help="Run an export preset on every publish of a project.")
def add_subscription(
    ctx: typer.Context,
    project: str = typer.Argument(..., help="The project (id or slug)."),
    preset: str = typer.Option(..., "--preset", help="The export preset (name or id)."),
    halt_at: str = typer.Option("critical", "--halt-at", help=_HALT_HELP),
    approve_loss: bool = typer.Option(False, "--approve-loss", help="Pre-approve the loss: deliver even past --halt-at."),
    inactive: bool = typer.Option(False, "--inactive", help="Add it switched off."),
) -> None:
    """Add one auto-export subscription."""
    client, tenant = _client(ctx)
    body = {"projectId": str(resolve_project_uuid(client, tenant, project)), "preset": preset,
            "haltAt": _halt_at(halt_at), "approveLoss": approve_loss, "active": not inactive}
    row = _object(client.post(api_paths.export_auto_subscriptions(tenant), json=body), "Subscription")
    _emit_subscription(ctx, row, "Added")


@app.command("update", help="Change a subscription's --halt-at, its loss pre-approval, or switch it on or off.")
def update_subscription(
    ctx: typer.Context,
    subscription_id: str = typer.Argument(..., help="The subscription id (apiome export auto list)."),
    halt_at: str | None = typer.Option(None, "--halt-at", help=_HALT_HELP),
    approve_loss: bool | None = typer.Option(None, "--approve-loss/--no-approve-loss",
                                             help="Pre-approve the loss, or stop pre-approving it."),
    active: bool | None = typer.Option(None, "--on/--off", help="Switch it on or off."),
) -> None:
    """Change one auto-export subscription."""
    body: dict[str, Any] = {}
    if halt_at is not None:
        body["haltAt"] = _halt_at(halt_at)
    if approve_loss is not None:
        body["approveLoss"] = approve_loss
    if active is not None:
        body["active"] = active
    if not body:
        typer.echo("Nothing to change: give --halt-at, --approve-loss/--no-approve-loss or --on/--off.", err=True)
        raise typer.Exit(EXIT_USAGE)
    client, tenant = _client(ctx)
    response = client.patch_raw(api_paths.export_auto_subscription(tenant, subscription_id), json=body)
    exit_on_api_error(response)
    _emit_subscription(ctx, _object(response, "Subscription"), "Updated")


@app.command("remove", help="Stop running a preset on publish. Past runs keep their record.")
def remove_subscription(
    ctx: typer.Context,
    subscription_id: str = typer.Argument(..., help="The subscription id."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Remove one auto-export subscription."""
    client, tenant = _client(ctx)
    confirm_action(f"Stop auto-export subscription {subscription_id}?", skip=yes)
    client.delete(api_paths.export_auto_subscription(tenant, subscription_id))
    if json_mode_from_context(ctx):
        emit_json({"deleted": subscription_id})
    else:
        typer.echo(f"Removed auto-export subscription {subscription_id}.")


@app.command("runs", help="List what each publish's auto-exports did: delivered, halted (and why) or failed.")
def list_runs(
    ctx: typer.Context,
    project: str | None = typer.Option(None, "--project", help="Only this project (id or slug)."),
    limit: int = typer.Option(50, "--limit", min=1, max=200, help="How many runs, newest first."),
) -> None:
    """List auto-export runs."""
    client, tenant = _client(ctx)
    params = [f"limit={limit}"]
    if project:
        params.append(f"projectId={resolve_project_uuid(client, tenant, project)}")
    rows = _object(client.get(f"{api_paths.export_auto_runs(tenant)}?{'&'.join(params)}"), "Run list").get("runs") or []
    if json_mode_from_context(ctx):
        emit_json({"runs": rows})
        return
    emit_list_table(rows, _RUN_COLUMNS, empty_message="No auto-export runs.", min_width=200)


@app.command("release", help="Deliver a halted auto-export anyway (needs versions:publish). Exits 1 if a delivery failed.")
def release_run(ctx: typer.Context, run_id: str = typer.Argument(..., help="The halted run's id.")) -> None:
    """Deliver one halted auto-export anyway."""
    client, tenant = _client(ctx)
    row = _object(client.post(api_paths.export_auto_run_release(tenant, run_id)), "Run")
    if json_mode_from_context(ctx):
        emit_json(row)
    else:
        typer.echo(f"Released auto-export {run_id}: {row.get('status')}")
        for delivery in row.get("deliveries") or []:
            typer.echo(f"  {delivery.get('outcome')}: {delivery.get('profileName') or delivery.get('profileId')}"
                       + (f" — {delivery.get('errorCode')}" if delivery.get("errorCode") else ""))
    if row.get("status") == "delivery_failed":
        raise typer.Exit(EXIT_ERROR)
