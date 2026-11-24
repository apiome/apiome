"""DBP-1.21 (#7204): per-call database budgets and the behaviours the caches must keep.

Acceptance criteria, as tests:

* a warm catalog ``tools/call`` uses one pool checkout and one statement before the tool's own
  query (the key gate's key + policy read); the capability gate runs no query of its own;
* a warm agent ``tools/call`` performs no synchronous write — the invocation row is queued on the
  batched writer — and reads one statement (the key);
* with bcrypt slowed, concurrent requests on the same process are not delayed (both planes);
* a revoked key is refused on the very next call, and a policy change applies on the next call
  (the documented budget is 0 s).

The pools here answer the real SQL the way the V096/V164/V269/V270 schema would, and count
checkouts and statements.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import bcrypt
import mcp.types as mt
import pytest
from fastmcp import Client, Context, FastMCP
from fastmcp.server.lifespan import lifespan

from agent_invocation_fakes import RecordingPool
from agent_runtime_fakes import ALL_TOOLS, KEY_ID, TENANT_ID, TOOLSET_ID, AgentDb, PetstoreUpstream
from apiome_mcp.agent_access import AgentAccessMiddleware, resolve_agent_key
from apiome_mcp.agent_invocation_proxy import InvocationConfig, InvocationProxy
from apiome_mcp.agent_quotas import AgentQuotaGuard, AgentQuotaMiddleware
from apiome_mcp.agent_server import AGENT_HTTP_CLIENT_KEY, build_agent_server
from apiome_mcp.agent_upstream_client import UpstreamCallPolicy
from apiome_mcp.audit_writer import AuditWriter, register_audit_writer, unregister_audit_writer
from apiome_mcp.capability_middleware import CapabilityCallGateMiddleware
from apiome_mcp.catalog_key_gate import McpKeyRequiredMiddleware
from apiome_mcp.database_pool import MCP_DB_POOL_KEY, get_db_pool
from apiome_mcp.http_credential_middleware import StashHttpBearerInToolContextMiddleware
from apiome_mcp.mcp_auth import hash_mcp_api_key_secret, validate_mcp_api_key

CATALOG_SECRET = "apiome_mcp_" + "c" * 40
AGENT_SECRET = "ak_" + "d4" * 32


# ==================================================================================================
# Catalog plane
# ==================================================================================================
class CatalogDb:
    """``mcp_api_keys`` + ``tenant_mcp_policies`` + ``tenant_mcp_policy_tools`` for one tenant."""

    def __init__(self) -> None:
        self.key_id = str(uuid.uuid4())
        self.tenant_id = str(uuid.uuid4())
        self.key: dict[str, Any] = {
            "id": self.key_id,
            "tenant_id": self.tenant_id,
            "prefix": CATALOG_SECRET[:12] + "...",
            "scope_json": {},
            "label": "budget",
            "key_hash": hash_mcp_api_key_secret(CATALOG_SECRET).decode("ascii"),
            "expires_at": None,
            "revoked_at": None,
            "capability_mode": "inherit",
            "enabled_tools": [],
        }
        self.policy: dict[str, Any] | None = {"default_mode": "explicit", "allow_anonymous_mcp": True}
        self.tools: dict[str, dict[str, bool]] = {
            "ping": {"in_ceiling": True, "default_enabled": True, "anonymous_enabled": True}
        }

    def _joined(self, tool: str | None) -> dict[str, Any]:
        row = dict(self.key)
        flags = self.tools.get(tool or "") if self.policy is not None else None
        row.update(
            has_policy=self.policy is not None,
            default_mode=(self.policy or {}).get("default_mode"),
            allow_anonymous_mcp=(self.policy or {}).get("allow_anonymous_mcp"),
            policy_tool_id=tool if flags is not None else None,
            in_ceiling=(flags or {}).get("in_ceiling"),
            default_enabled=(flags or {}).get("default_enabled"),
            anonymous_enabled=(flags or {}).get("anonymous_enabled"),
        )
        return row

    def __call__(self, sql: str, params: Any) -> Any:
        if "FROM apiome.mcp_api_keys k" in sql and "WHERE k.prefix" in sql:
            return [self._joined(params["tool"])] if params["prefix"] == self.key["prefix"] else []
        if "FROM apiome.mcp_api_keys k" in sql and "WHERE k.id" in sql:
            match = params["id"] == self.key_id and params["hash"] == self.key["key_hash"]
            return [self._joined(params["tool"])] if match else []
        if "FROM apiome.tenant_mcp_policies" in sql:
            raise AssertionError("the capability gate must use the policy read with the key")
        return None


class CountingPool(RecordingPool):
    """A :class:`RecordingPool` that also counts checkouts."""

    def __init__(self, responder: Any) -> None:
        super().__init__(responder)
        self.checkouts = 0

    @asynccontextmanager
    async def connection(self) -> Any:
        self.checkouts += 1
        async with super().connection() as conn:
            yield conn


def _catalog_app(pool: CountingPool) -> FastMCP:
    """The catalog's gate chain (same order as ``apiome_mcp.server``) over one probe tool."""

    @lifespan
    async def _lifespan(server: Any) -> Any:
        yield {MCP_DB_POOL_KEY: pool}

    app = FastMCP("budget-probe", lifespan=_lifespan)
    app.add_middleware(CapabilityCallGateMiddleware())
    app.add_middleware(McpKeyRequiredMiddleware())
    app.add_middleware(StashHttpBearerInToolContextMiddleware())

    @app.tool(name="ping")
    async def ping(ctx: Context) -> str:
        async with get_db_pool(ctx).connection() as conn:
            await conn.execute("SELECT 1 AS tool_query")
        return "pong"

    return app


async def _call(client: Client, name: str, secret: str, arguments: dict[str, Any] | None = None) -> mt.CallToolResult:
    request = mt.ClientRequest(
        mt.CallToolRequest(
            params=mt.CallToolRequestParams(name=name, arguments=arguments or {}, _meta={"api_key": secret})
        )
    )
    return await client.session.send_request(request, mt.CallToolResult)


def _text(result: mt.CallToolResult) -> str:
    return " ".join(block.text for block in result.content if isinstance(block, mt.TextContent))


def _before_tool(pool: CountingPool, start: int) -> list[str]:
    """Statements of one call that ran before the tool's own query (``last_used_at`` excluded)."""
    sqls = [sql for sql, _ in pool.statements[start:]]
    cut = next(i for i, sql in enumerate(sqls) if "tool_query" in sql)
    return [sql for sql in sqls[:cut] if "last_used_at" not in sql]


def test_a_warm_catalog_call_is_one_checkout_and_one_statement_before_the_tool() -> None:
    db = CatalogDb()
    pool = CountingPool(db)

    async def run() -> None:
        async with Client(_catalog_app(pool)) as client:
            cold = await _call(client, "ping", CATALOG_SECRET)
            assert not cold.isError, _text(cold)
            await asyncio.sleep(0)  # let the (first, throttled) last_used_at touch run
            start, checkouts = len(pool.statements), pool.checkouts
            warm = await _call(client, "ping", CATALOG_SECRET)
            assert not warm.isError, _text(warm)
            before = _before_tool(pool, start)
            assert len(before) == 1
            assert "WHERE k.id" in before[0] and "tenant_mcp_policy_tools" in before[0]
            # One checkout for the gate, one for the tool's own query; no last_used_at write.
            assert pool.checkouts - checkouts == 2
            assert not any("last_used_at" in sql for sql, _ in pool.statements[start:])

    asyncio.run(run())


def test_a_revoked_catalog_key_is_refused_on_the_next_call() -> None:
    db = CatalogDb()
    pool = CountingPool(db)

    async def run() -> None:
        async with Client(_catalog_app(pool)) as client:
            assert not (await _call(client, "ping", CATALOG_SECRET)).isError
            db.key["revoked_at"] = datetime.now(UTC)
            refused = await _call(client, "ping", CATALOG_SECRET)
            assert refused.isError
            assert "revoked" in _text(refused)

    asyncio.run(run())


def test_a_catalog_policy_change_applies_on_the_next_call() -> None:
    """POLICY_FRESHNESS_LAG_BUDGET_SECONDS stays 0: the policy is read with the key on every call."""
    db = CatalogDb()
    pool = CountingPool(db)

    async def run() -> None:
        async with Client(_catalog_app(pool)) as client:
            assert not (await _call(client, "ping", CATALOG_SECRET)).isError
            db.tools["ping"]["default_enabled"] = False
            denied = await _call(client, "ping", CATALOG_SECRET)
            assert denied.isError and "capability_disabled" in _text(denied)
            db.tools["ping"]["default_enabled"] = True
            assert not (await _call(client, "ping", CATALOG_SECRET)).isError

    asyncio.run(run())


def test_a_tools_list_reads_the_key_without_policy_rows() -> None:
    db = CatalogDb()
    pool = CountingPool(db)

    async def run() -> None:
        async with Client(_catalog_app(pool)) as client:
            await _call(client, "ping", CATALOG_SECRET)
            start = len(pool.statements)
            request = mt.ClientRequest(
                mt.ListToolsRequest(params=mt.PaginatedRequestParams(_meta={"api_key": CATALOG_SECRET}))
            )
            listed = await client.session.send_request(request, mt.ListToolsResult)
            assert [tool.name for tool in listed.tools] == ["ping"]
            [(sql, params)] = pool.statements[start:]
            assert params["tool"] is None

    asyncio.run(run())


# ==================================================================================================
# bcrypt off the event loop (both planes)
# ==================================================================================================
def _slow_checkpw(real: Any, delay: float) -> Any:
    def slow(password: bytes, hashed: bytes) -> bool:
        time.sleep(delay)
        return real(password, hashed)

    return slow


async def _max_loop_stall(work: Any, *, tick: float = 0.005) -> float:
    """Run ``work`` while a ticker measures the longest gap between its wake-ups."""
    stalls: list[float] = []
    done = asyncio.Event()

    async def ticker() -> None:
        last = time.perf_counter()
        while not done.is_set():
            await asyncio.sleep(tick)
            now = time.perf_counter()
            stalls.append(now - last - tick)
            last = now

    task = asyncio.create_task(ticker())
    try:
        await work
    finally:
        done.set()
        await task
    return max(stalls, default=0.0)


def test_catalog_bcrypt_does_not_block_concurrent_requests() -> None:
    db = CatalogDb()
    pool = CountingPool(db)
    slow = _slow_checkpw(bcrypt.checkpw, 0.25)

    async def run() -> float:
        with patch("apiome_mcp.mcp_auth.bcrypt.checkpw", new=slow):
            work = asyncio.gather(*(validate_mcp_api_key(pool, CATALOG_SECRET) for _ in range(4)))  # type: ignore[arg-type]
            return await _max_loop_stall(work)

    assert asyncio.run(run()) < 0.1


def test_agent_bcrypt_does_not_block_concurrent_requests() -> None:
    db = AgentKeysDb(AgentDb())
    pool = CountingPool(db)
    slow = _slow_checkpw(bcrypt.checkpw, 0.25)

    async def run() -> float:
        with patch("apiome_mcp.agent_access.bcrypt.checkpw", new=slow):
            work = asyncio.gather(*(resolve_agent_key(pool, AGENT_SECRET) for _ in range(4)))  # type: ignore[arg-type]
            return await _max_loop_stall(work)

    assert asyncio.run(run()) < 0.1


# ==================================================================================================
# Agent plane
# ==================================================================================================
class AgentKeysDb:
    """The runtime's :class:`AgentDb` plus the ``api_keys`` lookups (prefix and by id + hash)."""

    def __init__(self, db: AgentDb) -> None:
        self.db = db
        self.key: dict[str, Any] = {
            "id": KEY_ID,
            "tenant_id": TENANT_ID,
            "key_hash": bcrypt.hashpw(AGENT_SECRET.encode(), bcrypt.gensalt(rounds=4)).decode(),
            "toolset_id": TOOLSET_ID,
            "tool_allowlist": sorted(ALL_TOOLS),
            "enabled": True,
            "revoked": False,
            "expired": False,
            "tenant_active": True,
            "toolset_target": "mock",
            "toolset_stamp": "2026-11-23 10:00:00+00",
        }

    def __call__(self, sql: str, params: Any) -> Any:
        if "FROM apiome.api_keys ak" in sql and "ak.key_prefix" in sql:
            return [dict(self.key)] if params[0] == AGENT_SECRET[:12] + "..." else []
        if "FROM apiome.api_keys ak" in sql and "ak.id = " in sql:
            return [dict(self.key)] if params == (self.key["id"], self.key["key_hash"]) else []
        if "UPDATE apiome.api_keys" in sql:
            return None
        return self.db(sql, params)


def _agent_app(pool: CountingPool, upstream: PetstoreUpstream) -> FastMCP:
    @lifespan
    async def _lifespan(server: Any) -> Any:
        async with upstream.client() as client:
            yield {MCP_DB_POOL_KEY: pool, AGENT_HTTP_CLIENT_KEY: client}

    config = InvocationConfig(
        policy=UpstreamCallPolicy(timeout_seconds=0.5, budget_seconds=1.0, backoff_seconds=0.0),
        mock_base_url="http://mock.internal:8775",
    )
    return build_agent_server(
        proxy=InvocationProxy(config),
        access=AgentAccessMiddleware(),
        quota=AgentQuotaMiddleware(guard=AgentQuotaGuard()),
        server_lifespan=_lifespan,
    )


_WRITES = ("INSERT", "UPDATE", "DELETE")


def test_a_warm_agent_call_reads_one_statement_and_writes_nothing_synchronously() -> None:
    keys = AgentKeysDb(AgentDb())
    pool = CountingPool(keys)
    writer = AuditWriter(pool, flush_interval_seconds=60)  # type: ignore[arg-type]
    register_audit_writer(pool, writer)

    async def run() -> None:
        async with Client(_agent_app(pool, PetstoreUpstream())) as client:
            cold = await _call(client, "listPets", AGENT_SECRET)
            assert not cold.isError, _text(cold)
            await asyncio.sleep(0)
            start = len(pool.statements)
            warm = await _call(client, "listPets", AGENT_SECRET)
            assert not warm.isError, _text(warm)
            statements = [sql for sql, _ in pool.statements[start:]]
            assert not [sql for sql in statements if sql.lstrip().upper().startswith(_WRITES)]
            assert len(statements) == 1 and "ak.id = " in statements[0]
        assert writer.queued_rows == 2  # both calls' agent_invocations rows, not yet written
        await writer.flush()
        [(sql, params)] = [(s, p) for s, p in pool.statements if "agent_invocations" in s]
        assert sql.count("(%s::uuid, %s::uuid") == 2

    try:
        asyncio.run(run())
    finally:
        unregister_audit_writer(pool)


def test_a_revoked_agent_key_is_refused_on_the_next_call() -> None:
    keys = AgentKeysDb(AgentDb())
    pool = CountingPool(keys)

    async def run() -> None:
        async with Client(_agent_app(pool, PetstoreUpstream())) as client:
            assert not (await _call(client, "listPets", AGENT_SECRET)).isError
            keys.key["revoked"] = True
            refused = await _call(client, "listPets", AGENT_SECRET)
            assert refused.isError and "agent_key_revoked" in _text(refused)

    asyncio.run(run())


def test_a_switched_off_toolset_applies_on_the_next_call_through_its_stamp() -> None:
    """The manifest cache is keyed on the toolset row's updated_at, read with the key."""
    keys = AgentKeysDb(AgentDb())
    pool = CountingPool(keys)

    async def run() -> None:
        async with Client(_agent_app(pool, PetstoreUpstream())) as client:
            assert not (await _call(client, "listPets", AGENT_SECRET)).isError
            keys.db.manifest = None
            keys.key["toolset_stamp"] = "2026-11-23 10:00:09+00"
            refused = await _call(client, "listPets", AGENT_SECRET)
            assert refused.isError and "agent_toolset_unavailable" in _text(refused)

    asyncio.run(run())


@pytest.mark.parametrize("ttl", [0.0])
def test_with_caches_off_each_call_reads_the_manifest_once(ttl: float, monkeypatch: pytest.MonkeyPatch) -> None:
    """Even uncached, the access middleware and the provider share one manifest read per call."""
    from apiome_mcp import agent_toolset_source

    monkeypatch.setattr(agent_toolset_source.MANIFEST_CACHE, "_ttl", lambda: ttl)
    keys = AgentKeysDb(AgentDb())
    pool = CountingPool(keys)

    async def run() -> None:
        async with Client(_agent_app(pool, PetstoreUpstream())) as client:
            await _call(client, "listPets", AGENT_SECRET)
            start = len(pool.statements)
            await _call(client, "listPets", AGENT_SECRET)
            manifests = [sql for sql, _ in pool.statements[start:] if "exposed" in sql]
            assert len(manifests) == 1

    asyncio.run(run())
