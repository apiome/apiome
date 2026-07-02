"""Helpers for ``apiome mcp discover`` trigger and poll.

Mirrors the import (``import_/jobs.py``) and repository-scan (``repos_scan.py``)
poll loops: a single long-poll over the ergonomic discovery-job *status* contract
(``GET …/endpoints/{id}/jobs/{job_id}``) until the run reaches a terminal state.
The status snapshot lifts the poller-facing fields out of the raw job row —
``state``, ``terminal``, the produced ``version_id`` / ``changed`` (success) or the
structured ``error`` / ``error_detail`` (failure) — so the command only has to read
back those keys.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import typer

from apiome_cli.cli_context import DEFAULT_IMPORT_TIMEOUT
from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.exit_codes import EXIT_ERROR
from apiome_cli.import_.jobs import DEFAULT_POLL_INTERVAL
from apiome_cli.output import emit_json
from apiome_cli.progress import import_progress

# A poller stops once a job reports one of these states; ``queued`` and ``running``
# mean "keep polling" (matches ``MCP_DISCOVERY_TERMINAL_STATES`` in the REST models).
_TERMINAL_DISCOVERY_STATES = frozenset({"completed", "failed"})


def format_discovery_progress(state: str, *, elapsed_seconds: float) -> str:
    """Build a single-line stderr status message for the discovery poll loop."""
    elapsed = max(0, int(elapsed_seconds))
    return f"Discovery {state}… ({elapsed}s)"


def _failure_detail(job: dict[str, Any]) -> str | None:
    """Best-effort human-readable reason for a failed discovery job.

    Prefers the lifted ``error`` summary, falling back to a ``code`` from the
    structured ``error_detail`` taxonomy entry. Returns ``None`` when neither is
    present so the caller can emit a bare "Discovery failed." message.
    """
    error = job.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()

    detail = job.get("error_detail")
    if isinstance(detail, dict):
        code = detail.get("code")
        if isinstance(code, str) and code.strip():
            return code.strip()
    return None


def wait_for_discovery_job(
    client: RestClient,
    tenant_slug: str,
    endpoint_id: str,
    job_id: str,
    *,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    timeout: float = DEFAULT_IMPORT_TIMEOUT,
    no_progress: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Poll a discovery job's status snapshot until it reaches a terminal state.

    Args:
        client: REST client configured with the desired HTTP read timeout.
        tenant_slug: Catalog tenant slug for the endpoint scope.
        endpoint_id: MCP endpoint UUID the job belongs to.
        job_id: Discovery job UUID returned by the trigger ``POST``.
        poll_interval: Seconds between status polls.
        timeout: Maximum wall-clock seconds for the entire wait.
        no_progress: When True, do not show a stderr spinner.
        sleep: Injectable sleep function (for tests).
        monotonic: Injectable monotonic clock (for tests).

    Returns:
        The terminal status snapshot (the ``job`` object) when ``state`` is
        ``completed``.

    Raises:
        typer.Exit: On timeout, a failed job, or an invalid/incomplete payload.
    """
    deadline = monotonic() + timeout
    path = api_paths.mcp_endpoint_job(tenant_slug, endpoint_id, job_id)

    # Error messaging is deferred until after the progress spinner's context exits so the
    # message is not rendered on top of the live spinner line (see ``import_/jobs.py``).
    error_message: str | None = None
    with import_progress(enabled=not no_progress, initial_message="Discovering…") as status:
        while True:
            if monotonic() >= deadline:
                timeout_seconds = int(timeout)
                unit = "second" if timeout_seconds == 1 else "seconds"
                error_message = f"Discovery timed out after {timeout_seconds} {unit}."
                break

            response = client.get(path)
            payload = response.json()
            job = payload.get("job") if isinstance(payload, dict) else None
            if not isinstance(job, dict):
                error_message = "Discovery status response was not a JSON object."
                break

            state = job.get("state")
            if not isinstance(state, str) or not state:
                error_message = "Discovery status response missing state field."
                break

            elapsed = timeout - (deadline - monotonic())
            if status is not None:
                status.update(
                    format_discovery_progress(state, elapsed_seconds=elapsed),
                )

            if state in _TERMINAL_DISCOVERY_STATES:
                if state == "completed":
                    return job
                detail = _failure_detail(job)
                error_message = (
                    f"Discovery failed: {detail}" if detail else "Discovery failed."
                )
                break

            remaining = deadline - monotonic()
            if remaining <= 0:
                continue
            sleep(min(poll_interval, remaining))

    typer.echo(error_message, err=True)
    raise typer.Exit(EXIT_ERROR)


def emit_discovery_enqueue_result(
    payload: dict[str, Any],
    *,
    json_mode: bool,
) -> None:
    """Print the trigger response when not polling to completion (``--no-wait``)."""
    if json_mode:
        emit_json(payload)
        return

    job = payload.get("job") if isinstance(payload, dict) else None
    job = job if isinstance(job, dict) else {}
    deduplicated = bool(payload.get("deduplicated")) if isinstance(payload, dict) else False

    typer.echo("Discovery enqueued.")
    typer.echo(f"  Endpoint: {job.get('endpoint_id', '')}")
    typer.echo(f"  Job: {job.get('id', '')}")
    state = job.get("state")
    if isinstance(state, str) and state:
        typer.echo(f"  State: {state}")
    if deduplicated:
        typer.echo("  Note: existing run reused (deduplicated enqueue).")


def emit_discovery_completed(
    job: dict[str, Any],
    *,
    deduplicated: bool,
    lint: dict[str, Any] | None,
    json_mode: bool,
) -> None:
    """Print the new version + change summary (and score) for a completed run.

    Args:
        job: The terminal :class:`McpDiscoveryJobStatus` snapshot (the ``job`` object).
        deduplicated: True when the trigger reused an in-flight run.
        lint: The version's lint report (``score`` / ``grade``), or ``None`` when the
            best-effort score read was skipped or failed.
        json_mode: Emit the raw snapshot (plus ``deduplicated`` / ``lint``) as JSON.
    """
    if json_mode:
        emit_json({"deduplicated": deduplicated, "job": job, "lint": lint})
        return

    result = job.get("result")
    result = result if isinstance(result, dict) else {}

    typer.echo("Discovery completed.")
    if deduplicated:
        typer.echo("  Note: existing run reused (deduplicated enqueue).")
    typer.echo(f"  Endpoint: {job.get('endpoint_id', '')}")

    version_id = job.get("version_id")
    version_seq = result.get("version_seq")
    version_tag = result.get("version_tag")
    if version_id:
        descriptor = str(version_id)
        suffixes = []
        if version_seq is not None:
            suffixes.append(f"seq {version_seq}")
        if isinstance(version_tag, str) and version_tag.strip():
            suffixes.append(version_tag.strip())
        if suffixes:
            descriptor = f"{descriptor} ({', '.join(suffixes)})"
        typer.echo(f"  Version: {descriptor}")

    changed = job.get("changed")
    if changed is True:
        change_count = result.get("change_count")
        if change_count is not None:
            noun = "change" if change_count == 1 else "changes"
            typer.echo(f"  Changed: yes ({change_count} {noun})")
        else:
            typer.echo("  Changed: yes")
    elif changed is False:
        typer.echo("  Changed: no (surface unchanged)")

    duration_ms = job.get("duration_ms")
    if isinstance(duration_ms, int):
        typer.echo(f"  Duration: {duration_ms} ms")

    if isinstance(lint, dict):
        score = lint.get("score")
        grade = lint.get("grade")
        if score is not None and grade:
            typer.echo(f"  Score: {score} (grade {grade})")
