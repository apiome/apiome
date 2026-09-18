"""In-memory stand-in for the ``api_keys`` lookup the agent-access middleware runs — AGX-3.1 (#4537).

:class:`FakeAgentKeyPool` quacks like the psycopg ``AsyncConnectionPool`` that
:func:`apiome_mcp.agent_access.resolve_agent_key` reads through. It answers the prefix lookup the
way V269's schema would:

* only ``kind = 'agent'`` rows match (a workspace row with the same prefix is invisible);
* ``revoked`` / ``expired`` / ``tenant_active`` are computed at query time, so a test can revoke
  or expire a key between two requests and see the very next request refused;
* keys are stored as bcrypt hashes (cheap cost 4), never as secrets.

Every SQL string it receives is kept in :attr:`FakeAgentKeyPool.queries`, and every
``last_used_at`` touch in :attr:`FakeAgentKeyPool.touched`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt

#: A valid-looking agent secret (``ak_`` + 64 hex characters).
AGENT_SECRET = "ak_" + "0123456789abcdef" * 4


def agent_secret(seed: int) -> str:
    """Return a distinct, well-formed agent secret with its own lookup prefix."""
    return "ak_" + f"{seed:09x}" + "f" * 55


class FakeAgentKeyPool:
    """The slice of ``apiome.api_keys`` / ``apiome.tenants`` the resolver reads.

    Attributes:
        rows: Stored keys by id.
        queries: SQL of every statement executed, in order.
        touched: Key ids whose ``last_used_at`` was updated.
    """

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.queries: list[str] = []
        self.touched: list[str] = []

    def add(
        self,
        *,
        secret: str = AGENT_SECRET,
        tenant_id: str | None = None,
        toolset_id: str | None = None,
        allowlist: Iterable[str] = (),
        kind: str = "agent",
        enabled: bool = True,
        revoked: bool = False,
        expires_at: datetime | None = None,
        tenant_active: bool = True,
    ) -> str:
        """Store a key and return its id."""
        key_id = str(uuid.uuid4())
        self.rows[key_id] = {
            "id": key_id,
            "tenant_id": tenant_id or str(uuid.uuid4()),
            "key_hash": bcrypt.hashpw(secret.encode(), bcrypt.gensalt(rounds=4)).decode(),
            "key_prefix": secret[:12] + "...",
            "kind": kind,
            "toolset_id": toolset_id if toolset_id is not None or kind != "agent" else str(uuid.uuid4()),
            "tool_allowlist": list(allowlist),
            "enabled": enabled,
            "revoked": revoked,
            "expires_at": expires_at,
            "tenant_active": tenant_active,
        }
        return key_id

    def revoke(self, key_id: str) -> None:
        """Soft-delete a key, as ``DELETE /agent-keys/{id}`` does."""
        self.rows[key_id]["revoked"] = True
        self.rows[key_id]["enabled"] = False

    def expire(self, key_id: str) -> None:
        """Move a key's expiry into the past."""
        self.rows[key_id]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)

    # -- pool protocol ---------------------------------------------------------------------

    def _lookup(self, prefix: str) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        out = []
        for row in self.rows.values():
            if row["key_prefix"] != prefix or row["kind"] != "agent":
                continue
            expires_at = row["expires_at"]
            out.append(
                {
                    "id": row["id"],
                    "tenant_id": row["tenant_id"],
                    "key_hash": row["key_hash"],
                    "toolset_id": row["toolset_id"],
                    "tool_allowlist": list(row["tool_allowlist"]),
                    "enabled": row["enabled"],
                    "revoked": row["revoked"],
                    "expired": expires_at is not None and expires_at <= now,
                    "tenant_active": row["tenant_active"],
                }
            )
        return out

    @asynccontextmanager
    async def connection(self) -> Any:
        yield _FakeConnection(self)


class _FakeCursor:
    def __init__(self, pool: FakeAgentKeyPool) -> None:
        self._pool = pool
        self._rows: list[dict[str, Any]] = []

    async def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self._pool.queries.append(sql)
        self._rows = self._pool._lookup(params[0])

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConnection:
    def __init__(self, pool: FakeAgentKeyPool) -> None:
        self._pool = pool

    @asynccontextmanager
    async def cursor(self, row_factory: Any = None) -> Any:
        yield _FakeCursor(self._pool)

    async def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self._pool.queries.append(sql)
        if "last_used_at" in sql:
            self._pool.touched.append(params[0])

    async def commit(self) -> None:
        return None
