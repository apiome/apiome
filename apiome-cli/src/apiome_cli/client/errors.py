"""Map REST HTTP failures to CLI exit behaviour."""

from __future__ import annotations

import json

import click
import httpx
import typer

from apiome_cli.config import API_KEY_ENV_VAR, SESSION_TOKEN_ENV_VAR
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_USAGE


class CliError(Exception):
    """Structured REST API error with a mapped CLI exit code.

    Parameters
    ----------
    message:
        Human-readable error message for stderr output.
    exit_code:
        Process exit code to use when this error surfaces as a CLI failure.
        Defaults to ``EXIT_ERROR``.
    """

    def __init__(self, message: str, exit_code: int = EXIT_ERROR) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


def http_exit_code(status: int) -> int:
    """Map an HTTP status code to the appropriate CLI exit code.

    4xx client errors map to ``EXIT_USAGE`` because they indicate bad input
    or a client-side mistake.  5xx server errors map to ``EXIT_ERROR``
    because the server failed to process the request.

    Parameters
    ----------
    status:
        HTTP status code from the server response.

    Returns
    -------
    int
        ``EXIT_USAGE`` for 4xx codes, ``EXIT_ERROR`` for all others.
    """
    if 400 <= status < 500:
        return EXIT_USAGE
    return EXIT_ERROR


_SERVICE_UNAVAILABLE_HINT = (
    "The service is temporarily unavailable. Please try again later."
)

_SESSION_AUTH_HINT = (
    "This REST route requires a UI session bearer (obj_sess_…), not an API key. "
    f"Use {API_KEY_ENV_VAR} for /api-keys and import commands, or obtain a session "
    f"token via POST /auth/login and set {SESSION_TOKEN_ENV_VAR} for auth, tokens, "
    "and integrations commands."
)


def is_verbose() -> bool:
    """Return whether the active Typer context requested ``--verbose``."""
    ctx = click.get_current_context(silent=True)
    if ctx is not None and isinstance(ctx.obj, dict):
        return bool(ctx.obj.get("verbose"))
    return False


def _format_detail_location(loc: object) -> str:
    """Render a FastAPI-style ``loc`` tuple as a dotted field path."""
    if not isinstance(loc, (list, tuple)):
        return ""
    parts = [str(part) for part in loc if part not in ("body", "query", "path", "header")]
    return ".".join(parts)


def _format_detail_item(item: object) -> str | None:
    """Format one validation detail entry from apiome-rest."""
    if not isinstance(item, dict):
        return None

    fastapi_message = item.get("msg")
    if isinstance(fastapi_message, str) and fastapi_message:
        location = _format_detail_location(item.get("loc"))
        if location:
            return f"  {location}: {fastapi_message}"
        return f"  {fastapi_message}"

    import_message = item.get("message")
    if isinstance(import_message, str) and import_message:
        code = item.get("code")
        path = item.get("path")
        prefix = f"[{code}] " if isinstance(code, str) and code else ""
        suffix = f" at {path}" if isinstance(path, str) and path else ""
        return f"  {prefix}{import_message}{suffix}"

    return None


def _append_details(base: str, details: object) -> str:
    """Append structured API ``details`` when the server returned them."""
    if details is None:
        return base
    if isinstance(details, list):
        lines = [base]
        for item in details:
            line = _format_detail_item(item)
            if line:
                lines.append(line)
        if len(lines) > 1:
            return "\n".join(lines)
        return base
    if isinstance(details, dict) and details:
        lookup = _format_version_lookup_details(details)
        if lookup is not None:
            return f"{base}\n  {lookup}"
        return f"{base}\n  {json.dumps(details, separators=(',', ':'))}"
    if isinstance(details, str) and details.strip():
        return f"{base}: {details.strip()}"
    return base


def _format_version_lookup_details(details: dict[str, object]) -> str | None:
    """Render project/version lookup fields from structured REST 404 payloads."""
    labels = (
        ("project_slug", "project slug"),
        ("version", "version"),
        ("version_slug", "version slug"),
        ("project_id", "project id"),
        ("version_id", "version id"),
    )
    parts: list[str] = []
    for key, label in labels:
        value = details.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"{label} {value!r}")
    if not parts:
        return None
    return f"Looking for: {', '.join(parts)}"


def format_api_error(response: httpx.Response) -> str:
    """Build a short human-readable message from an HTTP error response.

    For 4xx responses the structured ``details`` payload is appended (when
    present) so field-level validation paths stay visible to the user. For 503
    responses a service-unavailable hint is appended as an actionable suggestion.
    """
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        base = f"HTTP {response.status_code}: {response.text.strip() or response.reason_phrase}"
        if response.status_code == 503:
            return f"{base}\n  Hint: {_SERVICE_UNAVAILABLE_HINT}"
        return base

    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str) and message:
            code = payload.get("code", response.status_code)
            base = f"HTTP {code}: {message}"
            if response.status_code == 401 and message == "Session token required":
                base = f"{base}\n  Hint: {_SESSION_AUTH_HINT}"
            if 400 <= response.status_code < 500:
                return _append_details(base, payload.get("details"))
            if response.status_code == 503:
                return f"{base}\n  Hint: {_SERVICE_UNAVAILABLE_HINT}"
            return base

    base = f"HTTP {response.status_code}: {response.text.strip() or response.reason_phrase}"
    if response.status_code == 503:
        return f"{base}\n  Hint: {_SERVICE_UNAVAILABLE_HINT}"
    return base


def format_connection_error(exc: httpx.RequestError) -> str:
    """Build a concise message for transport-layer failures."""
    return f"Connection error: {exc}"


def format_unhandled_error(exc: BaseException) -> str:
    """Build a concise message for unexpected CLI failures."""
    return f"Error: {exc}"


def handle_cli_failure(exc: BaseException, *, verbose: bool) -> None:
    """Print a failure to stderr and exit, or re-raise when ``verbose`` is set."""
    if verbose:
        raise exc
    typer.echo(format_unhandled_error(exc), err=True)
    raise typer.Exit(EXIT_ERROR) from exc


def exit_on_api_error(response: httpx.Response) -> None:
    """Print API failure to stderr and exit with a mapped exit code when status is not successful.

    4xx responses exit with ``EXIT_USAGE``; 5xx responses exit with
    ``EXIT_ERROR``.  The error message includes field-level details for
    422 validation failures and a service-unavailable hint for 503 responses.
    """
    if response.is_success:
        return
    err = CliError(
        message=format_api_error(response),
        exit_code=http_exit_code(response.status_code),
    )
    try:
        raise err
    except CliError as exc:
        typer.echo(exc.message, err=True)
        raise typer.Exit(exc.exit_code) from exc


def exit_on_connection_error(exc: httpx.RequestError) -> None:
    """Print transport failure to stderr and exit, respecting ``--verbose``."""
    if is_verbose():
        raise exc
    typer.echo(format_connection_error(exc), err=True)
    raise typer.Exit(EXIT_ERROR) from exc


def echo_concise_help() -> None:
    """Print short usage with examples (stdout) for bare ``apiome`` invocation."""
    from apiome_cli.help_util import echo_concise_help as _echo_concise_help

    _echo_concise_help()
