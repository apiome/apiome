"""Catalog connectors from the command line — CDG-1.6 (#5957), CDG-1.7 (#5958).

``apiome connectors list|add|show|sync|runs|items|remove`` manage the connectors that sync
gateway and registry APIs into the catalog — the same calls the Connectors pages make, under the
``imports`` permission. ``add`` asks the provider once (a dry run) and stores nothing unless it
answers; ``sync --wait`` exits with the run's outcome (``0`` succeeded, ``7`` failed), so a
pipeline can gate on it. ``--format json`` (or the global ``--json``) prints the API response.

``apiome connectors shadow-report`` prints the shadow-API report: what connected gateways serve
that the catalog does not describe (**shadow**), served APIs that look like a catalog item
(**possible-matches**), described APIs no gateway serves (**undeployed**) and linked APIs whose
deployed revision the catalog does not have (**drift**). ``--fail-on shadow,drift`` turns it into
a CI gate: the command exits ``6`` when a named category has a row, and only then.

Everything is decided server-side (``GET /v1/tenants/{t}/shadow-report``); this command shapes the
request and renders the answer.
"""

from __future__ import annotations

import sys
import time
from typing import Any
from urllib.parse import urlencode

import httpx
import typer

from apiome_cli.client import api_paths
from apiome_cli.client.connectors import (
    CODE_SYNC_RUNNING,
    CONFLICT_POLICIES,
    ITEM_STATUSES,
    RUN_SOURCES,
    RUNNING_STATUSES,
    connector_rows,
    item_rows,
    parse_scope,
    read_credentials,
    refusal,
    run_outcome,
    run_rows,
    sync_exit_code,
)
from apiome_cli.client.errors import http_exit_code
from apiome_cli.client.http import RestClient
from apiome_cli.client.shadow_report import (
    CATEGORY_KEYS,
    FORMATS,
    failing_categories,
    parse_fail_on,
    table_rows,
)
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.exit_codes import (
    EXIT_ERROR,
    EXIT_SHADOW_FOUND,
    EXIT_SUCCESS,
)
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json, emit_list_table, json_mode_from_context
from apiome_cli.terminal import confirm_action

app = typer.Typer(
    name="connectors",
    help="Catalog connectors: sync gateway APIs into the catalog and compare what they serve.",
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


# ---------------------------------------------------------------------------------------
# Connector management (CDG-1.7, #5958)
# ---------------------------------------------------------------------------------------

_CONNECTOR_COLUMNS = (
    ("ID", "id", None),
    ("Name", "name", None),
    ("Kind", "kind", None),
    ("Health", "status", None),
    ("Last run", "last_run", None),
    ("Schedule", "schedule", None),
)

_RUN_COLUMNS = (
    ("Run", "id", None),
    ("Source", "source", None),
    ("What", "what", None),
    ("Status", "status", None),
    ("Outcome", "outcome", None),
    ("Started", "started", None),
)

_ITEM_COLUMNS = (
    ("Remote ID", "remote_id", None),
    ("Name", "name", None),
    ("Environment", "environment", None),
    ("Status", "status", None),
    ("Catalog item", "catalog_item", None),
)

#: Seconds between polls while ``sync --wait`` waits for a sync already running.
_POLL_SECONDS = 2.0


def _format(ctx: typer.Context, output_format: str) -> str:
    """Resolve ``--format`` (``table`` | ``json``); the global ``--json`` wins."""
    fmt = (output_format or "table").strip().lower()
    if json_mode_from_context(ctx):
        return "json"
    if fmt not in FORMATS:
        raise typer.BadParameter("must be one of table, json", param_hint="--format")
    return fmt


def _format_option() -> Any:
    return typer.Option(
        "table", "--format", help="Output: table (default) or json (the API response)."
    )


def _expect(response: httpx.Response) -> httpx.Response:
    """Return a successful response, or print REST's reason and exit (4xx → 2, 5xx → 1)."""
    if response.is_success:
        return response
    message, _code = refusal(response)
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(http_exit_code(response.status_code))


def _query(params: dict[str, object]) -> str:
    """A query string from the set (non-empty) parameters."""
    present = {
        key: str(value) for key, value in params.items() if value not in (None, "")
    }
    return f"?{urlencode(present)}" if present else ""


@app.command("list")
def list_connectors(
    ctx: typer.Context,
    output_format: str = _format_option(),
) -> None:
    """List the workspace's connectors with their health and last run (GET …/connectors)."""
    fmt = _format(ctx, output_format)
    client, tenant = tenant_scoped_client(ctx)
    body = _expect(client.get_raw(api_paths.connectors(tenant))).json()
    if fmt == "json":
        emit_json(body)
        return
    emit_list_table(
        connector_rows(body.get("connectors") or []),
        _CONNECTOR_COLUMNS,
        empty_message="No connectors. Add one with: apiome connectors add",
        min_width=120,
    )


@app.command("add")
def add_connector(
    ctx: typer.Context,
    kind: str = typer.Option(
        ...,
        "--kind",
        help=(
            "Connector kind: kong-konnect, kong-admin, aws-apigateway, azure-apim, apigee, "
            "url, schema-registry, mcp-registry, registry. A registry connector crawls a "
            'registry; its --scope names the crawl: \'{"protocol": "a2a-registry"}\', '
            "xregistry or fhir-metadata."
        ),
    ),
    name: str = typer.Option(..., "--name", help="A name unique in the workspace."),
    base_url: str | None = typer.Option(
        None, "--base-url", help="The provider's URL, for kinds that take one."
    ),
    scope: str | None = typer.Option(
        None,
        "--scope",
        help='What to sync, as a JSON object or @file (for example \'{"region": "eu"}\').',
    ),
    credentials_file: str | None = typer.Option(
        None,
        "--credentials-file",
        help="JSON object of the kind's credential fields, or - for stdin. Never echoed.",
    ),
    refresh_interval: int | None = typer.Option(
        None,
        "--refresh-interval",
        min=1,
        help="Seconds between scheduled syncs (default: the deployment's).",
    ),
    conflict_policy: str = typer.Option(
        "hold-for-review",
        "--conflict-policy",
        help="When a synced API changed in Apiome: overwrite, hold-for-review, new-branch.",
    ),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Ask the provider once before saving; a failing dry run saves nothing.",
    ),
    output_format: str = _format_option(),
) -> None:
    """Register a connector (POST …/connectors), after a dry run of it.

    The dry run calls the provider once and prints how many APIs it would sync; nothing is stored
    until it answers. A refused dry run prints the provider's reason and exits 2. The credential,
    when given, is stored encrypted after the connector is created and is never printed.
    """
    fmt = _format(ctx, output_format)
    if conflict_policy not in CONFLICT_POLICIES:
        raise typer.BadParameter(
            f"must be one of {', '.join(CONFLICT_POLICIES)}",
            param_hint="--conflict-policy",
        )
    try:
        scope_body = parse_scope(scope)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--scope") from exc
    try:
        credentials = read_credentials(
            credentials_file, sys.stdin.read() if credentials_file == "-" else None
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--credentials-file") from exc

    client, tenant = tenant_scoped_client(ctx)
    draft: dict[str, Any] = {"kind": kind, "scope": scope_body}
    if base_url:
        draft["baseUrl"] = base_url
    if dry_run:
        probe = _expect(
            client.post_raw(
                api_paths.connector_dry_run(tenant),
                json={**draft, **({"credentials": credentials} if credentials else {})},
            )
        ).json()
        more = " (sample truncated)" if probe.get("truncated") else ""
        typer.echo(
            f"Dry run: {probe.get('itemCount', 0)} APIs would sync{more}.", err=True
        )

    body = {**draft, "name": name, "conflictPolicy": conflict_policy}
    if refresh_interval:
        body["refreshIntervalSeconds"] = refresh_interval
    created = _expect(client.post_raw(api_paths.connectors(tenant), json=body)).json()
    if credentials:
        stored = client.put_raw(
            api_paths.connector_credentials(tenant, str(created["id"])),
            json={"credentials": credentials},
        )
        if not stored.is_success:
            message, _code = refusal(stored)
            typer.echo(
                f"Error: connector {created['id']} was created but its credential was not "
                f"stored: {message}. Retry in the Connectors page Settings tab.",
                err=True,
            )
            raise typer.Exit(http_exit_code(stored.status_code))
        created["hasCredentials"] = True
    if fmt == "json":
        emit_json(created)
    else:
        typer.echo(f"Added connector {created.get('name')} ({created.get('id')}).")


@app.command("show")
def show_connector(
    ctx: typer.Context,
    connector_id: str = typer.Argument(..., help="Connector id."),
    output_format: str = _format_option(),
) -> None:
    """Show one connector (GET …/connectors/{id}); never its credential."""
    fmt = _format(ctx, output_format)
    client, tenant = tenant_scoped_client(ctx)
    body = _expect(client.get_raw(api_paths.connector(tenant, connector_id))).json()
    if fmt == "json":
        emit_json(body)
        return
    emit_list_table(connector_rows([body]), _CONNECTOR_COLUMNS, min_width=120)


def _wait_for_running(
    client: RestClient, tenant: str, connector_id: str, timeout: float
) -> dict[str, Any]:
    """Poll a connector's newest run until it finishes, or exit 1 after ``timeout`` seconds."""
    deadline = time.monotonic() + timeout
    path = api_paths.connector_runs(tenant, connector_id) + "?limit=1"
    while True:
        runs = _expect(client.get_raw(path)).json().get("runs") or []
        if runs and runs[0].get("status") not in RUNNING_STATUSES:
            return runs[0]
        if time.monotonic() >= deadline:
            typer.echo(
                f"Error: the running sync did not finish within {timeout:g}s.", err=True
            )
            raise typer.Exit(EXIT_ERROR)
        time.sleep(_POLL_SECONDS)


@app.command("sync")
def sync_connector(
    ctx: typer.Context,
    connector_id: str = typer.Argument(..., help="Connector id."),
    wait: bool = typer.Option(
        False,
        "--wait",
        help=(
            "Exit with the run's outcome (0 succeeded, 7 failed); if a sync is already "
            "running, wait for it instead of refusing."
        ),
    ),
    timeout: float = typer.Option(
        600.0,
        "--timeout",
        min=1,
        help="With --wait: seconds to wait for a running sync.",
    ),
    output_format: str = _format_option(),
) -> None:
    """Sync a connector now (POST …/sync) and print the finished run.

    A provider failure is a ``failed`` run, not an HTTP error: without ``--wait`` the command
    exits 0 once the run is recorded; with ``--wait`` it exits 7. A sync already running is
    refused (exit 2) unless ``--wait`` is passed.
    """
    fmt = _format(ctx, output_format)
    client, tenant = tenant_scoped_client(ctx)
    response = client.post_raw(api_paths.connector_sync(tenant, connector_id))
    if (
        response.status_code == 409
        and wait
        and refusal(response)[1] == CODE_SYNC_RUNNING
    ):
        typer.echo("A sync is already running; waiting for it to finish.", err=True)
        run = _wait_for_running(client, tenant, connector_id, timeout)
    else:
        run = _expect(response).json()
    if fmt == "json":
        emit_json(run)
    else:
        typer.echo(f"Run {run.get('id')}: {run_outcome(run)}.")
        if run.get("status") == "failed" and run.get("errorMessage"):
            typer.echo(str(run["errorMessage"]), err=True)
    raise typer.Exit(sync_exit_code(run) if wait else EXIT_SUCCESS)


@app.command("runs")
def list_runs(
    ctx: typer.Context,
    connector_id: str | None = typer.Argument(
        None, help="Only this connector's runs (default: every Git and connector run)."
    ),
    source: str | None = typer.Option(
        None, "--source", help="Only git or connector runs."
    ),
    limit: int = typer.Option(
        25, "--limit", min=1, max=200, help="At most this many runs."
    ),
    offset: int = typer.Option(0, "--offset", min=0, help="Skip this many runs."),
    output_format: str = _format_option(),
) -> None:
    """List refresh runs, newest first: Git refreshes and connector syncs interleaved."""
    fmt = _format(ctx, output_format)
    if source is not None and source not in RUN_SOURCES:
        raise typer.BadParameter("must be git or connector", param_hint="--source")
    client, tenant = tenant_scoped_client(ctx)
    query = _query(
        {
            "connector": connector_id,
            "source": source,
            "limit": limit,
            "offset": offset or None,
        }
    )
    body = _expect(client.get_raw(api_paths.refresh_runs(tenant) + query)).json()
    if fmt == "json":
        emit_json(body)
        return
    emit_list_table(
        run_rows(body.get("runs") or []),
        _RUN_COLUMNS,
        total=body.get("total"),
        empty_message="No runs.",
        min_width=140,
    )


@app.command("items")
def list_items(
    ctx: typer.Context,
    connector_id: str = typer.Argument(..., help="Connector id."),
    status: str | None = typer.Option(
        None, "--status", help="Only discovered, imported, ignored or missing APIs."
    ),
    limit: int = typer.Option(
        50, "--limit", min=1, max=200, help="At most this many APIs."
    ),
    offset: int = typer.Option(0, "--offset", min=0, help="Skip this many APIs."),
    output_format: str = _format_option(),
) -> None:
    """List a connector's inventory and the catalog item each imported API became."""
    fmt = _format(ctx, output_format)
    if status is not None and status not in ITEM_STATUSES:
        raise typer.BadParameter(
            f"must be one of {', '.join(ITEM_STATUSES)}", param_hint="--status"
        )
    client, tenant = tenant_scoped_client(ctx)
    query = _query({"status": status, "limit": limit, "offset": offset or None})
    body = _expect(
        client.get_raw(api_paths.connector_items(tenant, connector_id) + query)
    ).json()
    if fmt == "json":
        emit_json(body)
        return
    emit_list_table(
        item_rows(body.get("items") or []),
        _ITEM_COLUMNS,
        total=body.get("total"),
        empty_message="No APIs seen yet. Run: apiome connectors sync <id>",
        min_width=120,
    )


@app.command("remove")
def remove_connector(
    ctx: typer.Context,
    connector_id: str = typer.Argument(..., help="Connector id."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
) -> None:
    """Delete a connector (DELETE …/connectors/{id}).

    Scheduled syncs stop and the stored credential is destroyed; the catalog items it imported
    stay. Asks first unless ``--yes`` is passed (required when not interactive).
    """
    confirm_action(
        f"Delete connector {connector_id}? Its credential is destroyed; its catalog items stay.",
        skip=yes,
        escape_flag="--yes",
    )
    client, tenant = tenant_scoped_client(ctx)
    _expect(client.delete_raw(api_paths.connector(tenant, connector_id)))
    typer.echo(f"Removed connector {connector_id}.", err=json_mode_from_context(ctx))
    if json_mode_from_context(ctx):
        emit_json({"id": connector_id, "deleted": True})
