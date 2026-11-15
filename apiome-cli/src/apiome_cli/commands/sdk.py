"""``apiome sdk`` — generated SDK evidence (SGD-2.1, #4735).

``apiome sdk compatibility --project <slug|uuid> [--version <label|uuid>] [--fail-on <severity>]``
prints the generator compatibility manifest — the same document the dashboard's **Export studio → SDK
compatibility** tab renders — and, with ``--fail-on``, exits :data:`~apiome_cli.exit_codes
.EXIT_QUALITY_GATE` when a finding reaches that severity. ``--json`` (global) prints the manifest
exactly as served.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

import typer

from apiome_cli.cli_context import insecure_from_context, json_mode_from_context, settings_from_context
from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.client.tenant_scope import require_tenant_slug
from apiome_cli.config import require_api_key
from apiome_cli.exit_codes import EXIT_QUALITY_GATE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json
from apiome_cli.sdk_compat_output import SEVERITIES, fails_threshold, render_manifest

app = typer.Typer(
    name="sdk",
    help="Generated SDK evidence: what each generated artifact covers and leaves out.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def sdk_group(ctx: typer.Context) -> None:
    """SDK command group."""
    group_callback_without_subcommand(ctx)


@app.command("compatibility")
def sdk_compatibility(
    ctx: typer.Context,
    project: str = typer.Option(..., "--project", help="Project slug or UUID."),
    version: Optional[str] = typer.Option(
        None, "--version", help="Version label or revision UUID (default: the latest revision)."
    ),
    fail_on: Optional[str] = typer.Option(
        None,
        "--fail-on",
        help="Exit 4 when a finding is at or above this severity: error, warning or info.",
    ),
) -> None:
    """Show the generator compatibility manifest for a version (GET …/sdk-compatibility).

    Findings come first, each with the action that fixes it; then one line per generated artifact
    (coverage, runtime, unsupported auth, pagination); then semver and the source and options
    digests. Exit 4 when --fail-on is met.
    """
    threshold = (fail_on or "").strip().lower() or None
    if threshold is not None and threshold not in SEVERITIES:
        raise typer.BadParameter("must be one of error, warning, info", param_hint="--fail-on")
    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(settings, verify=not insecure_from_context(ctx))
    tenant_slug = require_tenant_slug(settings, client)
    path = api_paths.sdk_compatibility(tenant_slug, project)
    if version:
        path = f"{path}?{urlencode({'version': version})}"
    manifest = client.get(path).json()
    if json_mode_from_context(ctx):
        emit_json(manifest)
    else:
        for line in render_manifest(manifest):
            typer.echo(line)
    if fails_threshold(manifest, threshold):
        raise typer.Exit(EXIT_QUALITY_GATE)
