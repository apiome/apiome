"""``apiome export presets …`` and ``apiome export --preset NAME …`` (MFX-39.3).

A preset saves an export's targets, each target's emit options and an optional delivery profile once per
workspace, by name. ``export presets`` manages them; ``export --preset NAME ARTIFACT --out PATH`` runs
one (see :func:`apiome_cli.export_preset_dispatch.run_preset_export`).
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
from apiome_cli.client import export_presets as presets_api
from apiome_cli.client.browse_scope import resolve_tenant_slug
from apiome_cli.client.export_delivery_profiles import resolve_profile_id
from apiome_cli.client.http import RestClient
from apiome_cli.config import require_api_key
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import ListColumn, emit_json, emit_list_table
from apiome_cli.terminal import confirm_action

app = typer.Typer(
    name="presets",
    help="List, create, change and delete the workspace's export presets (targets, options, delivery). "
    "Run one with: apiome export --preset NAME ARTIFACT --out PATH.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

_TARGET_HELP = "A target format (repeatable, in order): one is a single-target export, several a multi-target one."
_OPTION_HELP = "TARGET:KEY=VALUE — an emit option for one of the targets (repeatable; VALUE parsed as JSON when valid)."
_DELIVER_HELP = "A delivery profile (name or id) the export is delivered with on completion."

_PRESET_COLUMNS: list[ListColumn] = [
    ("Name", "name", None),
    ("Targets", "targets", presets_api.targets_summary),
    ("Delivery", "deliveryProfileName", None),
    ("Description", "description", None),
    ("ID", "id", None),
]


@app.callback(invoke_without_command=True)
def presets_group(ctx: typer.Context) -> None:
    """Export preset commands."""
    group_callback_without_subcommand(ctx)


def _client(ctx: typer.Context) -> tuple[RestClient, str]:
    """An authenticated client and the tenant slug."""
    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(settings, timeout=timeout_from_context(ctx), verify=not insecure_from_context(ctx))
    return client, resolve_tenant_slug(settings, client, tenant_override=None)


def _emit(ctx: typer.Context, preset: dict[str, Any], verb: str) -> None:
    """Print a preset: JSON in ``--json`` mode, else one confirmation line."""
    if json_mode_from_context(ctx):
        emit_json(preset)
        return
    delivery = f", delivered with {preset['deliveryProfileName']!r}" if preset.get("deliveryProfileName") else ""
    typer.echo(f"{verb} preset {preset.get('name')!r}: {presets_api.targets_summary(preset.get('targets'))}{delivery}")


@app.command("list", help="List the workspace's export presets.")
def list_presets(ctx: typer.Context) -> None:
    """List export presets."""
    client, tenant = _client(ctx)
    rows = presets_api.list_presets(client, tenant)
    if json_mode_from_context(ctx):
        emit_json({"presets": rows})
        return
    emit_list_table(rows, _PRESET_COLUMNS, empty_message="No export presets.", min_width=160)


@app.command("show", help="Show one export preset (by name or id).")
def show_preset(ctx: typer.Context, preset: str = typer.Argument(..., help="Preset name or id.")) -> None:
    """Show one export preset."""
    client, tenant = _client(ctx)
    row = presets_api.get_preset(client, tenant, preset)
    if json_mode_from_context(ctx):
        emit_json(row)
        return
    typer.echo(f"Name: {row.get('name')}")
    typer.echo(f"ID: {row.get('id')}")
    if row.get("description"):
        typer.echo(f"Description: {row.get('description')}")
    for entry in row.get("targets") or []:
        options = entry.get("options") or {}
        typer.echo(f"Target: {entry.get('target')}" + (f"  options: {options}" if options else ""))
    typer.echo(f"Delivery: {row.get('deliveryProfileName') or 'none'}")


@app.command(
    "create",
    help="Create an export preset: apiome export presets create nightly-sync --target openapi "
    "--option openapi:openapi_version=3.0 --target protobuf --deliver data-lake.",
)
def create_preset(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="A name unique in the workspace."),
    target: list[str] = typer.Option(..., "--target", help=_TARGET_HELP),
    option: list[str] = typer.Option([], "--option", metavar="TARGET:KEY=VALUE", help=_OPTION_HELP),
    deliver: str | None = typer.Option(None, "--deliver", metavar="PROFILE", help=_DELIVER_HELP),
    description: str | None = typer.Option(None, "--description", help="What the preset is for."),
) -> None:
    """Create one export preset."""
    targets = presets_api.build_targets(target, option)
    client, tenant = _client(ctx)
    body: dict[str, Any] = {"name": name, "targets": targets}
    if description is not None:
        body["description"] = description
    if deliver:
        body["deliveryProfileId"] = resolve_profile_id(client, tenant, deliver)
    _emit(ctx, presets_api.create_preset(client, tenant, body), "Created")


@app.command(
    "update",
    help="Change a preset's name, description, targets (replaced whole by --target / --option) or delivery "
    "(--deliver PROFILE, or --no-deliver to remove it).",
)
def update_preset(
    ctx: typer.Context,
    preset: str = typer.Argument(..., help="Preset name or id."),
    name: str | None = typer.Option(None, "--name", help="A new name."),
    description: str | None = typer.Option(None, "--description", help="A new description ('' clears it)."),
    target: list[str] = typer.Option([], "--target", help="Replace the targets (repeatable, in order)."),
    option: list[str] = typer.Option([], "--option", metavar="TARGET:KEY=VALUE", help=_OPTION_HELP),
    deliver: str | None = typer.Option(None, "--deliver", metavar="PROFILE", help=_DELIVER_HELP),
    no_deliver: bool = typer.Option(False, "--no-deliver", help="Remove the preset's delivery profile."),
) -> None:
    """Change one export preset."""
    if deliver and no_deliver:
        typer.echo("Use --deliver or --no-deliver, not both.", err=True)
        raise typer.Exit(EXIT_USAGE)
    if option and not target:
        typer.echo("--option replaces the targets' options: give the --target list with it.", err=True)
        raise typer.Exit(EXIT_USAGE)
    client, tenant = _client(ctx)
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if target:
        body["targets"] = presets_api.build_targets(target, option)
    if deliver:
        body["deliveryProfileId"] = resolve_profile_id(client, tenant, deliver)
    if no_deliver:
        body["deliveryProfileId"] = None
    if not body:
        typer.echo("Nothing to change: give --name, --description, --target, --deliver or --no-deliver.", err=True)
        raise typer.Exit(EXIT_USAGE)
    _emit(ctx, presets_api.update_preset(client, tenant, preset, body), "Updated")


@app.command("delete", help="Delete an export preset.")
def delete_preset(
    ctx: typer.Context,
    preset: str = typer.Argument(..., help="Preset name or id."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Delete one export preset."""
    client, tenant = _client(ctx)
    confirm_action(f"Delete export preset {preset!r}?", skip=yes)
    presets_api.delete_preset(client, tenant, preset)
    if json_mode_from_context(ctx):
        emit_json({"deleted": preset})
    else:
        typer.echo(f"Deleted export preset {preset!r}.")


#: The hidden command ``apiome export --preset NAME …`` is routed to (``DispatchExportGroup``).
PRESET_RUN_COMMAND = "preset-run"


def run_preset(
    ctx: typer.Context,
    artifact: str | None = typer.Argument(None, help="The artifact (id or slug) to export."),
    version: str | None = typer.Option(None, "--version", help="Version UUID, slug or label (default: latest)."),
    items_raw: str | None = typer.Option(None, "--items", metavar="ITEM[@VERSION],…",
                                         help="Export these items instead of ARTIFACT (a batch)."),
    out: str | None = typer.Option(None, "--out", metavar="PATH",
                                   help="A file or directory for one target; a directory or .zip for several."),
    force: bool = typer.Option(False, "--force", help="Exit 0 even when the export loses fidelity."),
    confirm: bool = typer.Option(False, "--confirm", help="Proceed with a severe conversion."),
    export_timeout: float | None = typer.Option(None, "--export-timeout", min=1.0, help="Seconds to wait for the job."),
    poll_interval: float = typer.Option(1.0, "--poll-interval", min=0.1, help="Seconds between job-status polls."),
    overlay_paths: list[str] = typer.Option([], "--overlay", metavar="FILE", help="Overlay documents, in order."),
    deliver: list[str] = typer.Option([], "--deliver", metavar="PROFILE",
                                      help="More delivery profiles, after the preset's own (repeatable)."),
) -> None:
    """Run the export preset named by ``apiome export --preset NAME``."""
    from apiome_cli.export_preset_dispatch import run_preset_export

    preset = (ctx.parent.params.get("preset") if ctx.parent else None) or ""
    run_preset_export(
        ctx, preset=preset, artifact=artifact, version=version, items_raw=items_raw, out=out, force=force,
        confirm=confirm, poll_interval=poll_interval, export_timeout_override=export_timeout,
        overlay_paths=overlay_paths, deliver_refs=deliver,
    )
