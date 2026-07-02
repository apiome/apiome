"""Doctor connectivity probe – quick unauthenticated health check."""

from __future__ import annotations

import typer

from apiome_cli.cli_context import insecure_from_context, settings_from_context, timeout_from_context
from apiome_cli.client.http import RestClient

app = typer.Typer(
    name="doctor",
    help="Quick connectivity check against the REST service (GET /health, no API key).",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def doctor(ctx: typer.Context) -> None:
    """Call GET /health without authentication and report connectivity status.

    Prints ``OK: <base_url>`` on success.  Exits non-zero and writes a
    diagnostic message to stderr on any connection or HTTP error.

    Unlike the ``health`` command, no API key is sent so this probe works
    even before an API key has been configured.
    """
    settings = settings_from_context(ctx)
    base_url = settings.base_url_str

    RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
        anonymous=True,
    ).get("/health")

    typer.echo(f"OK: {base_url}")
