"""Poll specification import jobs until a terminal REST state is returned."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.exit_codes import EXIT_ERROR
from apiome_cli.cli_context import DEFAULT_IMPORT_TIMEOUT
from apiome_cli.progress import import_progress

DEFAULT_POLL_INTERVAL = 1.0

_TERMINAL_STATES = frozenset({"completed", "failed", "canceled", "rolled-back"})


def format_import_progress(state: str, *, elapsed_seconds: float) -> str:
    """Build a single-line stderr status message for the import poll loop."""
    elapsed = max(0, int(elapsed_seconds))
    return f"Import {state}… ({elapsed}s)"


def _failure_detail(payload: dict[str, Any]) -> str | None:
    """Best-effort human-readable reason for a non-completed terminal import.

    Prefers ``summary.message``, but the REST import engine only populates ``summary`` for
    *completed* imports — a failed worker or import records its reason in the job's ``events``
    (e.g. ``code="WORKER_FAILED"``) with no summary. Without this fallback the CLI collapses a
    real failure into a bare "Import failed." with the actual cause swallowed. Returns the joined
    error-level event messages (prefixed with their ``code`` when present), or ``None`` when the
    payload carries no usable detail.
    """
    summary = payload.get("summary")
    if isinstance(summary, dict):
        message = summary.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    events = payload.get("events")
    if isinstance(events, list):
        messages: list[str] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            if str(event.get("level") or "").lower() != "error":
                continue
            message = event.get("message")
            if not isinstance(message, str) or not message.strip():
                continue
            code = event.get("code")
            if isinstance(code, str) and code.strip():
                messages.append(f"[{code.strip()}] {message.strip()}")
            else:
                messages.append(message.strip())
        if messages:
            return "; ".join(messages)

    return None


def wait_for_import_job(
    client: RestClient,
    tenant_slug: str,
    job_id: str,
    *,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    timeout: float = DEFAULT_IMPORT_TIMEOUT,
    no_progress: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Poll ``GET /v1/tenants/{tenant_slug}/imports/{job_id}`` until terminal."""
    deadline = monotonic() + timeout
    path = api_paths.tenant_import(tenant_slug, job_id)

    # Error messaging is deferred until after the progress spinner's context exits: printing while the
    # Rich spinner is live renders the message on top of the spinner line (e.g.
    # "Import running… (0s)Import failed: …"). Inside the loop we only set `error_message` and break;
    # the message is echoed below, once the spinner has been cleared.
    error_message: str | None = None
    with import_progress(enabled=not no_progress) as status:
        while True:
            if monotonic() >= deadline:
                timeout_seconds = int(timeout)
                unit = "second" if timeout_seconds == 1 else "seconds"
                error_message = f"Import timed out after {timeout_seconds} {unit}."
                break

            response = client.get(path)
            payload = response.json()
            if not isinstance(payload, dict):
                error_message = "Import status response was not a JSON object."
                break

            job_state = payload.get("state")
            if not isinstance(job_state, str) or not job_state:
                error_message = "Import status response missing state field."
                break

            elapsed = timeout - (deadline - monotonic())
            if status is not None:
                status.update(
                    format_import_progress(job_state, elapsed_seconds=elapsed),
                )

            if job_state in _TERMINAL_STATES:
                if job_state == "completed":
                    return payload
                detail = _failure_detail(payload)
                error_message = f"Import {job_state}: {detail}" if detail else f"Import {job_state}."
                break

            remaining = deadline - monotonic()
            if remaining <= 0:
                continue
            sleep(min(poll_interval, remaining))

    typer.echo(error_message, err=True)
    raise typer.Exit(EXIT_ERROR)
