"""Catalog connectors from the command line — CDG-1.6 (#5957).

``apiome connectors shadow-report`` prints the shadow-API report: what connected gateways serve
that the catalog does not describe (**shadow**), served APIs that look like a catalog item
(**possible-matches**), described APIs no gateway serves (**undeployed**) and linked APIs whose
deployed revision the catalog does not have (**drift**). ``--fail-on shadow,drift`` turns it into
a CI gate: the command exits ``6`` when a named category has a row, and only then.

Everything is decided server-side (``GET /v1/tenants/{t}/shadow-report``); this command shapes the
request and renders the answer.
"""

from __future__ import annotations

from urllib.parse import urlencode

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.shadow_report import (
    CATEGORY_KEYS,
    FORMATS,
    failing_categories,
    parse_fail_on,
    table_rows,
)
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.exit_codes import EXIT_SHADOW_FOUND, EXIT_SUCCESS
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json, emit_list_table, json_mode_from_context

app = typer.Typer(
    name="connectors",
    help="Catalog connectors: compare what your gateways serve with the catalog.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

_COLUMNS = (
    ("Category", "category", None),
    ("API", "api", None),
    ("Connector", "connector", None),
    ("Environment", "environment", None),
    ("Served at", "served_at", None),
    ("Match / detail", "detail", None),
)


@app.callback(invoke_without_command=True)
def connectors_group(ctx: typer.Context) -> None:
    """Catalog connectors command group."""
    group_callback_without_subcommand(ctx)


@app.command("shadow-report")
def shadow_report(
    ctx: typer.Context,
    connector: str | None = typer.Option(
        None, "--connector", help="Only this connector's inventory (connector id)."
    ),
    environment: str | None = typer.Option(
        None, "--environment", help="Only gateway APIs found in this environment."
    ),
    output_format: str = typer.Option(
        "table", "--format", help="Output: table (default) or json (the API response)."
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help=(
            "Comma-separated categories that fail the command (exit 6) when they have a row: "
            "shadow, possible-matches, undeployed, drift."
        ),
    ),
) -> None:
    """Print the shadow-API report (GET …/shadow-report).

    A connector whose last sync failed is reported as stale on stderr, so an empty report is
    never mistaken for a clean one. Exit codes: 0 report printed (and no ``--fail-on`` category
    has a row), 6 a ``--fail-on`` category has a row, 1 unreachable, 2 rejected (auth, unknown
    connector, bad option).
    """
    fmt = (output_format or "table").strip().lower()
    if json_mode_from_context(ctx):
        fmt = "json"
    if fmt not in FORMATS:
        raise typer.BadParameter("must be one of table, json", param_hint="--format")
    try:
        gates = parse_fail_on(fail_on)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--fail-on") from exc

    client, tenant_slug = tenant_scoped_client(ctx)
    params = {
        key: value
        for key, value in (("connector", connector), ("environment", environment))
        if value
    }
    query = f"?{urlencode(params)}" if params else ""
    report = client.get(api_paths.shadow_report(tenant_slug) + query).json()

    if fmt == "json":
        emit_json(report)
    else:
        summary = report.get("summary") or {}
        typer.echo(
            "Shadow APIs: "
            + ", ".join(
                f"{name} {int(summary.get(key, 0) or 0)}"
                for name, key in CATEGORY_KEYS.items()
            )
            + f", ignored {int(summary.get('ignored', 0) or 0)}"
        )
        emit_list_table(
            table_rows(report),
            _COLUMNS,
            empty_message="Nothing to report.",
            min_width=140,
        )
    for stale in report.get("stale") or []:
        typer.echo(f"warning: {stale.get('message')}", err=True)

    failed = failing_categories(report, gates)
    if failed:
        typer.echo(f"fail-on: {', '.join(failed)} has rows.", err=True)
        raise typer.Exit(EXIT_SHADOW_FOUND)
    raise typer.Exit(EXIT_SUCCESS)
