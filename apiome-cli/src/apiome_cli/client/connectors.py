"""Pure helpers for ``apiome connectors`` (CDG-1.7, #5958).

Request shaping (scope and credential files), refusal messages, run outcomes and table rows —
kept free of I/O against Apiome so they are unit-testable on their own. The command module owns the
HTTP calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_SYNC_FAILED

#: Run statuses that are not finished yet.
RUNNING_STATUSES = frozenset({"queued", "running"})

#: The refusal code REST answers when a sync of the connector is already running.
CODE_SYNC_RUNNING = "connector-sync-running"

#: Conflict policies REST accepts (shared with Git repositories).
CONFLICT_POLICIES = ("overwrite", "hold-for-review", "new-branch")

#: Ledger sources ``connectors runs --source`` accepts.
RUN_SOURCES = ("git", "connector")

#: Item statuses ``connectors items --status`` accepts.
ITEM_STATUSES = ("discovered", "imported", "ignored", "missing")


def parse_scope(text: str | None) -> dict[str, Any]:
    """Parse ``--scope`` as a JSON object.

    Args:
        text: The option value: inline JSON, ``@path`` to a JSON file, or ``None``.

    Returns:
        The scope object (empty when omitted).

    Raises:
        ValueError: The value is not a JSON object or the file cannot be read.
    """
    if not text:
        return {}
    raw = text
    if text.startswith("@"):
        try:
            raw = Path(text[1:]).read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"cannot read {text[1:]}: {exc.strerror}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON ({exc.msg})") from exc
    if not isinstance(value, dict):
        raise ValueError('must be a JSON object, e.g. \'{"region": "eu"}\'')
    return value


def read_credentials(
    path: str | None, stdin_text: str | None = None
) -> dict[str, str] | None:
    """Read a credential file: a JSON object of the kind's credential fields.

    A credential never travels on the command line (shell history, process lists), so it comes
    from a file or from standard input (``-``).

    Args:
        path: The ``--credentials-file`` value, ``-`` for stdin, or ``None``.
        stdin_text: Standard input's text when ``path`` is ``-``.

    Returns:
        The fields with string values, or ``None`` when no file was named.

    Raises:
        ValueError: The file is unreadable, not a JSON object, or a value is not a string.
    """
    if not path:
        return None
    if path == "-":
        raw = stdin_text or ""
    else:
        try:
            raw = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"cannot read {path}: {exc.strerror}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON ({exc.msg})") from exc
    if not isinstance(value, dict) or not value:
        raise ValueError('must be a non-empty JSON object, e.g. {"token": "…"}')
    for key, field in value.items():
        if not isinstance(field, str):
            raise ValueError(f"field {key!r} must be a string")
    return value


def refusal(response: httpx.Response) -> tuple[str, str | None]:
    """REST's message and refusal code for a failed call.

    Connector refusals carry ``detail: {code, message, reason?}``; other errors a string
    ``detail`` or FastAPI's validation list.

    Args:
        response: The failed response.

    Returns:
        ``(message, code)``; ``code`` is ``None`` when REST sent none.
    """
    try:
        payload = response.json()
    except ValueError:
        return (f"HTTP {response.status_code}: {response.text.strip()}", None)
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return (detail["message"], detail.get("code"))
    if isinstance(detail, str):
        return (detail, None)
    if isinstance(detail, list) and detail:
        first = detail[0] if isinstance(detail[0], dict) else {}
        where = ".".join(str(part) for part in first.get("loc", []) if part != "body")
        message = first.get("msg", "invalid request")
        return (f"{where}: {message}" if where else str(message), None)
    return (f"HTTP {response.status_code}", None)


def sync_exit_code(run: dict[str, Any]) -> int:
    """The exit code ``sync --wait`` ends with: the run's outcome.

    Args:
        run: The finished run.

    Returns:
        ``0`` when it succeeded, :data:`EXIT_SYNC_FAILED` otherwise.
    """
    return EXIT_SUCCESS if run.get("status") == "succeeded" else EXIT_SYNC_FAILED


def run_outcome(run: dict[str, Any]) -> str:
    """A run's one-line outcome, as the Runs tab words it.

    Args:
        run: A ledger row or a sync answer.

    Returns:
        For example ``Imported 2 of 5``, ``Unchanged (5 checked)`` or ``Failed: auth (HTTP 401)``.
    """
    status = run.get("status")
    if status == "failed":
        http = f" (HTTP {run['httpStatus']})" if run.get("httpStatus") else ""
        return f"Failed: {run.get('errorClass') or 'error'}{http}"
    if status in RUNNING_STATUSES:
        return "Running"
    if (run.get("source") or run.get("refreshSource")) == "git":
        return "Refreshed" if status == "succeeded" else str(status)
    summary = run.get("summary") or {}
    imported = int(summary.get("imported") or 0)
    candidates = int(summary.get("candidates") or 0)
    if imported:
        return f"Imported {imported} of {candidates}"
    return f"Unchanged ({candidates} checked)" if candidates else "Nothing to sync"


def connector_rows(connectors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows for the ``connectors list`` table."""
    return [
        {
            "id": c.get("id"),
            "name": c.get("name"),
            "kind": c.get("kind"),
            "status": c.get("status"),
            "last_run": c.get("lastRunAt") or "never",
            "schedule": schedule_label(c.get("refreshIntervalSeconds")),
        }
        for c in connectors
    ]


def schedule_label(seconds: int | None) -> str:
    """A refresh interval as words (``None`` = the deployment default)."""
    if not seconds:
        return "default"
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds % size == 0:
            return f"every {seconds // size}{unit}"
    return f"every {seconds}s"


def run_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows for the ``connectors runs`` table (Git and connector runs interleaved)."""
    rows = []
    for run in runs:
        if run.get("source") == "git":
            what = " ".join(
                part
                for part in (
                    run.get("repositoryName"),
                    run.get("branch"),
                    run.get("path"),
                )
                if part
            )
        else:
            what = run.get("connectorName") or run.get("connectorId") or ""
        rows.append(
            {
                "id": run.get("id"),
                "source": run.get("source"),
                "what": what,
                "status": run.get("status"),
                "outcome": run_outcome(run),
                "started": run.get("startedAt") or run.get("createdAt") or "",
            }
        )
    return rows


def item_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows for the ``connectors items`` table."""
    return [
        {
            "remote_id": item.get("remoteId"),
            "name": item.get("remoteName") or "",
            "environment": item.get("environment") or "",
            "status": item.get("status"),
            "catalog_item": item.get("catalogItemId") or "",
        }
        for item in items
    ]
