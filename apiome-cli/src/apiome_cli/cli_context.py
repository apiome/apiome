"""Read global Typer callback options from the active command context."""

from __future__ import annotations

import typer

from apiome_cli.client.http import DEFAULT_TIMEOUT
from apiome_cli.config import CliSettings, load_settings

DEFAULT_IMPORT_TIMEOUT = 120.0


def _context_obj(ctx: typer.Context) -> dict[str, object] | None:
    """Return the nearest Typer ``ctx.obj`` dict, if any."""
    current: typer.Context | None = ctx
    while current is not None:
        obj = current.obj
        if isinstance(obj, dict):
            return obj
        current = current.parent
    return None


def json_mode_from_context(ctx: typer.Context) -> bool:
    """Return True when a parent callback set ``json`` on the context object."""
    obj = _context_obj(ctx)
    if obj is not None and "json" in obj:
        return bool(obj["json"])
    return False


def timeout_from_context(
    ctx: typer.Context,
    *,
    default: float = DEFAULT_TIMEOUT,
) -> float:
    """Resolve HTTP timeout seconds from ``--timeout`` or a command default."""
    obj = _context_obj(ctx)
    if obj is not None:
        raw = obj.get("timeout")
        if isinstance(raw, (int, float)) and raw > 0:
            return float(raw)
    return default


def import_timeout_from_context(ctx: typer.Context) -> float:
    """Timeout for import poll loops (default 120s unless ``--timeout`` is set)."""
    return timeout_from_context(ctx, default=DEFAULT_IMPORT_TIMEOUT)


def no_progress_from_context(ctx: typer.Context) -> bool:
    """Return True when ``--no-progress`` was passed on the root command."""
    obj = _context_obj(ctx)
    if obj is not None:
        return bool(obj.get("no_progress"))
    return False


def insecure_from_context(ctx: typer.Context) -> bool:
    """Return True when ``--insecure`` was passed on the root command.

    When True, TLS certificate verification should be disabled on the HTTP
    client.  This is intended solely for local development with self-signed
    certificates and must never be used in production.
    """
    obj = _context_obj(ctx)
    if obj is not None:
        return bool(obj.get("insecure"))
    return False


def settings_from_context(ctx: typer.Context) -> CliSettings:
    """Load settings with root CLI flag overrides for URL, tenant, keys, and session."""
    obj = _context_obj(ctx)
    if obj is None:
        return load_settings()

    base_url = obj.get("base_url")
    tenant_id = obj.get("tenant_id")
    api_key = obj.get("api_key")
    session_token = obj.get("session_token")
    env_file = obj.get("env_file")
    return load_settings(
        base_url=base_url if isinstance(base_url, str) else None,
        tenant_id=tenant_id if isinstance(tenant_id, str) else None,
        api_key=api_key if isinstance(api_key, str) else None,
        session_token=session_token if isinstance(session_token, str) else None,
        env_file=env_file if isinstance(env_file, str) else None,
    )
