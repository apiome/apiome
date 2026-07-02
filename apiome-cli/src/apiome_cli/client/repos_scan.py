"""Helpers for ``apiome repos scan`` enqueue and poll."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import typer

from apiome_cli.client.http import RestClient
from apiome_cli.cli_context import DEFAULT_IMPORT_TIMEOUT
from apiome_cli.exit_codes import EXIT_ERROR
from apiome_cli.import_.jobs import DEFAULT_POLL_INTERVAL
from apiome_cli.output import emit_json
from apiome_cli.progress import import_progress

_TERMINAL_SCAN_STATUSES = frozenset({"done", "failed"})


def format_scan_progress(status: str, *, elapsed_seconds: float) -> str:
    """Build a single-line stderr status message for the scan poll loop."""
    elapsed = max(0, int(elapsed_seconds))
    return f"Scan {status}… ({elapsed}s)"


def wait_for_repository_scan(
    client: RestClient,
    tenant_id: str,
    repository_id: str,
    scan_id: str,
    *,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    timeout: float = DEFAULT_IMPORT_TIMEOUT,
    no_progress: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Poll scan status until the job reaches a terminal state.

    Args:
        client: REST client configured with the desired HTTP read timeout.
        tenant_id: Tenant UUID for the repository scope.
        repository_id: Repository UUID to scan.
        scan_id: Scan job UUID from the enqueue response.
        poll_interval: Seconds between status polls.
        timeout: Maximum wall-clock seconds for the entire wait.
        no_progress: When True, do not show a stderr spinner.
        sleep: Injectable sleep function (for tests).
        monotonic: Injectable monotonic clock (for tests).

    Returns:
        Final scan JSON body when ``status`` is ``done``.

    Raises:
        typer.Exit: On timeout, failed jobs, or invalid payloads.
    """
    deadline = monotonic() + timeout
    path = f"/tenants/{tenant_id}/repositories/{repository_id}/scans/{scan_id}"

    with import_progress(enabled=not no_progress, initial_message="Scanning…") as status:
        while True:
            if monotonic() >= deadline:
                timeout_seconds = int(timeout)
                unit = "second" if timeout_seconds == 1 else "seconds"
                typer.echo(
                    f"Scan timed out after {timeout_seconds} {unit}.",
                    err=True,
                )
                raise typer.Exit(EXIT_ERROR)

            response = client.get(path)
            payload = response.json()
            if not isinstance(payload, dict):
                typer.echo("Scan status response was not a JSON object.", err=True)
                raise typer.Exit(EXIT_ERROR)

            scan_status = payload.get("status")
            if not isinstance(scan_status, str) or not scan_status:
                typer.echo("Scan status response missing status field.", err=True)
                raise typer.Exit(EXIT_ERROR)

            elapsed = timeout - (deadline - monotonic())
            if status is not None:
                status.update(
                    format_scan_progress(scan_status, elapsed_seconds=elapsed),
                )

            if scan_status in _TERMINAL_SCAN_STATUSES:
                if scan_status == "done":
                    return payload
                message = payload.get("error_message")
                if isinstance(message, str) and message.strip():
                    typer.echo(f"Scan failed: {message.strip()}", err=True)
                else:
                    typer.echo("Scan failed.", err=True)
                raise typer.Exit(EXIT_ERROR)

            remaining = deadline - monotonic()
            if remaining <= 0:
                continue
            sleep(min(poll_interval, remaining))


def emit_scan_enqueue_result(payload: dict[str, Any], *, json_mode: bool) -> None:
    """Print the enqueue response when not waiting for completion."""
    if json_mode:
        emit_json(payload)
        return

    scan_id = payload.get("scan_id", "")
    branch = payload.get("branch", "")
    status = payload.get("status", "")
    created = payload.get("created")
    typer.echo("Scan enqueued.")
    typer.echo(f"  Scan: {scan_id}")
    if isinstance(branch, str) and branch:
        typer.echo(f"  Branch: {branch}")
    if isinstance(status, str) and status:
        typer.echo(f"  Status: {status}")
    if created is False:
        typer.echo("  Note: existing pending scan returned (idempotent enqueue).")


def emit_scan_completed_counts(payload: dict[str, Any], *, json_mode: bool) -> None:
    """Print final scan counts after a completed wait."""
    if json_mode:
        emit_json(payload)
        return

    branch = payload.get("branch", "")
    typer.echo("Scan completed.")
    if isinstance(branch, str) and branch:
        typer.echo(f"  Branch: {branch}")
    for field, label in (
        ("files_seen", "Files seen"),
        ("files_added", "Files added"),
        ("files_changed", "Files changed"),
        ("files_removed", "Files removed"),
    ):
        value = payload.get(field)
        if value is not None:
            typer.echo(f"  {label}: {value}")
