"""Health probe against apiome-rest."""

from __future__ import annotations

import json

import typer

from apiome_cli.cli_context import insecure_from_context, settings_from_context, timeout_from_context
from apiome_cli.client.http import RestClient
from apiome_cli.output import emit_json, json_mode_from_context

app = typer.Typer(
    name="health",
    help="Check REST service health (GET /health).",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def health(ctx: typer.Context) -> None:
    """Query GET /health and print the JSON body on success."""
    settings = settings_from_context(ctx)

    payload = RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
    ).get("/health").json()
    if json_mode_from_context(ctx):
        emit_json(payload)
        return
    typer.echo(json.dumps(payload, indent=2))
