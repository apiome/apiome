"""Private draft mocks accept workspace keys only — AGX-3.1 (#4537).

V269 stores agent keys in ``apiome.api_keys`` beside workspace keys. An agent key is scoped to one
MCP toolset and a tool allowlist, so it must not open a tenant's private draft mocks: the lookup
selects ``kind = 'workspace'`` rows only. The pool here is a stand-in that records the SQL and
answers with whatever rows a test hands it, the way Postgres would after applying the filter.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any

import bcrypt

from apiome_mock.api_key import _API_KEY_LOOKUP, validate_api_key_for_tenant

_SECRET = "sk_" + "ab" * 32


class _Pool:
    """Records each statement and answers with ``rows``."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.queries: list[tuple[str, dict[str, Any]]] = []

    @asynccontextmanager
    async def connection(self) -> Any:
        pool = self

        class _Cursor:
            async def execute(self, sql: str, params: dict[str, Any]) -> None:
                pool.queries.append((sql, params))

            async def fetchall(self) -> list[dict[str, Any]]:
                return pool.rows

        class _Conn:
            @asynccontextmanager
            async def cursor(self, row_factory: Any = None) -> Any:
                yield _Cursor()

        yield _Conn()


def _row(secret: str = _SECRET) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "key_hash": bcrypt.hashpw(secret.encode(), bcrypt.gensalt(rounds=4)).decode(),
        "tenant_slug": "acme",
    }


def test_the_lookup_selects_workspace_keys_only() -> None:
    assert "AND ak.kind = 'workspace'" in _API_KEY_LOOKUP


def test_a_workspace_key_still_opens_its_tenants_private_mocks() -> None:
    pool = _Pool([_row()])
    key = asyncio.run(validate_api_key_for_tenant(pool, api_key=_SECRET, tenant_slug="acme"))  # type: ignore[arg-type]
    assert key is not None and key.tenant_slug == "acme"
    sql, params = pool.queries[0]
    assert "ak.kind = 'workspace'" in sql
    assert params == {"key_prefix": _SECRET[:12] + "..."}


def test_an_agent_key_finds_no_row() -> None:
    # Postgres returns nothing for an agent key: its row fails `ak.kind = 'workspace'`.
    pool = _Pool([])
    agent_secret = "ak_" + "cd" * 32
    assert asyncio.run(validate_api_key_for_tenant(pool, api_key=agent_secret, tenant_slug="acme")) is None  # type: ignore[arg-type]
