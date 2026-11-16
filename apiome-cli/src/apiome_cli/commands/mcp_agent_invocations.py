"""``apiome mcp agent-invocations export`` — the agent invocation audit for a SIEM (ATQ-4.5, #5847).

Thin client over ``GET /v1/tenants/{tenant_slug}/agent-invocations/export?day=&format=``: one
finalized UTC day of the tenant's agent ``tools/call`` audit rows, as JSON Lines (default, pipes
into ``jq``) or CSV, written to stdout or ``--out``. API-key auth, like the other ``mcp`` reads.

The server refuses a day the usage sweep has not finalized (``409``, with when it can be) and a
day past the plan's retention (``410``, with the retention); both are printed as one line and exit
with the usage code, so a scheduled pull can tell "try later" from "too late" by the message.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import httpx
import typer

from apiome_cli.cli_context import (
    insecure_from_context,
    settings_from_context,
    timeout_from_context,
)
from apiome_cli.client import api_paths
from apiome_cli.client.errors import exit_on_api_error, http_exit_code
from apiome_cli.client.http import RestClient
from apiome_cli.client.tenant_scope import require_tenant_slug
from apiome_cli.config import require_api_key
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand

__all__ = ["EXPORT_FORMATS", "agent_invocations_app", "refusal_message"]

#: Formats the REST route accepts (validated locally so a typo is a usage error, not a 422).
EXPORT_FORMATS = ("jsonl", "csv")

agent_invocations_app = typer.Typer(
    name="agent-invocations",
    help="Export the agent invocation audit (finalized UTC days) for a SIEM (ATQ-4.5).",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@agent_invocations_app.callback(invoke_without_command=True)
def agent_invocations_group(ctx: typer.Context) -> None:
    """Agent invocation audit command group."""
    group_callback_without_subcommand(ctx)


def refusal_message(response: httpx.Response) -> str | None:
    """The one-line message of a structured ``{detail: {code, message}}`` refusal.

    Args:
        response: A failed export response.

    Returns:
        ``HTTP <status> <code>: <message>``, or ``None`` when the body is not that shape (the
        generic CLI error rendering then applies).
    """
    try:
        payload = response.json()
    except ValueError:
        return None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if not isinstance(detail, dict) or not isinstance(detail.get("message"), str):
        return None
    code = detail.get("code")
    prefix = (
        f"HTTP {response.status_code} {code}"
        if code
        else f"HTTP {response.status_code}"
    )
    return f"{prefix}: {detail['message']}"


@agent_invocations_app.command("export")
def agent_invocations_export(
    ctx: typer.Context,
    day: str = typer.Option(
        ..., "--day", help="The UTC day to export, YYYY-MM-DD (must be finalized)."
    ),
    export_format: str = typer.Option(
        "jsonl",
        "--format",
        help="jsonl (one JSON object per line) or csv (header line first).",
    ),
    out: Path | None = typer.Option(
        None, "--out", help="Write the export to this file instead of stdout."
    ),
) -> None:
    """Export one finalized day of agent invocations (GET .../agent-invocations/export).

    Every stored audit column is written as stored, plus key_name and a hashed key_fingerprint;
    the key secret never appears. Today, and a day the usage sweep has not finalized yet (about
    six hours after it ends), are refused with when it can be exported; a day older than the
    plan's retention is refused with the retention.

    Example: apiome mcp agent-invocations export --day 2026-11-14 | jq -c 'select(.outcome != "success")'
    """
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        typer.echo(f"--day must be a date as YYYY-MM-DD, got {day!r}.", err=True)
        raise typer.Exit(EXIT_USAGE) from None
    if export_format not in EXPORT_FORMATS:
        typer.echo(f"--format must be one of: {', '.join(EXPORT_FORMATS)}.", err=True)
        raise typer.Exit(EXIT_USAGE)

    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
    )
    tenant_slug = require_tenant_slug(settings, client)
    query = urlencode({"day": parsed.isoformat(), "format": export_format})
    response = client.get_raw(
        f"{api_paths.agent_invocations_export(tenant_slug)}?{query}"
    )
    if not response.is_success:
        message = refusal_message(response)
        if message is None:
            exit_on_api_error(response)
        typer.echo(message, err=True)
        raise typer.Exit(http_exit_code(response.status_code))

    if out is None:
        typer.echo(response.text, nl=False)
        return
    # Byte for byte: a CSV keeps its RFC 4180 \r\n line ends.
    out.write_bytes(response.content)
    typer.echo(f"Wrote {out}", err=True)
