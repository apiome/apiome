"""MCP ``ping`` tool: service identity, version, DB reachability, timestamp."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import structlog
from psycopg_pool import AsyncConnectionPool

from objectified_mcp import __version__
from objectified_mcp.database_pool import ping_pool

_log = structlog.get_logger(__name__)

# Matches URI authority patterns that contain credentials (scheme://[user[:pass]@]host).
# Covers postgresql://, postgres://, and generic URIs.  Limitations: does not handle IPv6
# bracket addresses ([::1]) and assumes no whitespace in the authority component.
_DSN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+\-.]*://\S*@\S+")
_MAX_DB_ERROR_LEN = 200


def _sanitize_db_error(exc: BaseException) -> str:
    """Return a safe, bounded error string with DSN credentials/hostnames redacted."""
    msg = _DSN_RE.sub("[redacted]", str(exc))
    if len(msg) > _MAX_DB_ERROR_LEN:
        msg = msg[:_MAX_DB_ERROR_LEN] + "..."
    return msg


async def build_ping_response(pool: AsyncConnectionPool) -> dict[str, Any]:
    """Return ping payload; ``db_ok`` is True after ``SELECT 1``, else False with ``db_error``."""
    ts = datetime.now(timezone.utc).isoformat()
    common: dict[str, Any] = {
        "service": "objectified-mcp",
        "version": __version__,
        "ts": ts,
    }
    try:
        await ping_pool(pool)
    except Exception as exc:
        _log.warning("ping_db_probe_failed", error=str(exc))
        return {**common, "db_ok": False, "db_error": _sanitize_db_error(exc)}
    return {**common, "db_ok": True}
