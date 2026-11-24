"""DBP-1.21 (#7204): the bounded, batched audit writer.

Covers the contract the call paths rely on: ``submit`` never does I/O, a flush is one transaction
with one multi-row INSERT per table (parents first), a full queue drops the whole new group and
counts it, a failed batch is retried group by group, and ``close`` writes everything still queued.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from apiome_mcp.audit_writer import (
    TABLES,
    AuditWriter,
    audit_writer_for,
    register_audit_writer,
    running_audit_writer,
    unregister_audit_writer,
)
from apiome_mcp.settings import Settings

_NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
_TENANT = "11111111-1111-4111-8111-111111111111"
_KEY = "22222222-2222-4222-8222-222222222222"


class _Pool:
    """Records checkouts, transactions and statements; can fail statements matching a needle."""

    def __init__(self, *, fail_when: Any = None) -> None:
        self.checkouts = 0
        self.transactions = 0
        self.statements: list[tuple[str, list[Any]]] = []
        self.committed: list[tuple[str, list[Any]]] = []
        self.fail_when = fail_when

    @asynccontextmanager
    async def connection(self) -> Any:
        self.checkouts += 1
        yield _Conn(self)


class _Conn:
    def __init__(self, pool: _Pool) -> None:
        self._pool = pool
        self._pending: list[tuple[str, list[Any]]] = []

    @asynccontextmanager
    async def transaction(self) -> Any:
        self._pool.transactions += 1
        self._pending = []
        yield
        self._pool.committed.extend(self._pending)

    async def execute(self, sql: str, params: list[Any]) -> None:
        self._pool.statements.append((sql, params))
        if self._pool.fail_when is not None and self._pool.fail_when(sql, params):
            raise RuntimeError("constraint violated")
        self._pending.append((sql, params))


def _denial(tool: str = "spec.list") -> tuple[Any, ...]:
    return (_KEY, _TENANT, tool, _NOW, "http", "not_in_ceiling")


def _invocation(invocation_id: str) -> tuple[Any, ...]:
    return (invocation_id, _TENANT, _KEY, _KEY, "listPets", "prod", _NOW, 12, "success", None, 200, 2, 3, True)


def _sample(invocation_id: str) -> tuple[Any, ...]:
    return (invocation_id, _TENANT, "{}", "[]", False, False)


def test_submit_queues_without_touching_the_pool() -> None:
    pool = _Pool()
    writer = AuditWriter(pool)  # type: ignore[arg-type]
    assert writer.submit("mcp_capability_denials", _denial())
    assert writer.queued_rows == 1
    assert pool.checkouts == 0


def test_a_flush_is_one_transaction_with_one_multi_row_insert_per_table() -> None:
    pool = _Pool()
    writer = AuditWriter(pool)  # type: ignore[arg-type]
    for tool in ("a", "b", "c"):
        writer.submit("mcp_capability_denials", _denial(tool))
    writer.submit_group([("agent_invocation_samples", _sample("i1")), ("agent_invocations", _invocation("i1"))])

    assert asyncio.run(writer.flush()) == 5
    assert pool.checkouts == 1 and pool.transactions == 1
    tables = [sql.split("apiome.")[1].split(" ")[0] for sql, _ in pool.statements]
    # Parents first: the sample's foreign key must find its invocation.
    assert tables == ["agent_invocations", "agent_invocation_samples", "mcp_capability_denials"]
    denials_sql, denials_params = pool.statements[2]
    assert denials_sql.count("(%s::uuid, %s::uuid, %s, %s, %s, %s)") == 3
    assert len(denials_params) == 18
    assert writer.stats.written == 5 and writer.queued_rows == 0


def test_a_backlog_is_written_in_batches_of_at_most_batch_max_rows() -> None:
    pool = _Pool()
    writer = AuditWriter(pool, batch_max_rows=2)  # type: ignore[arg-type]
    for tool in "abcde":
        writer.submit("mcp_capability_denials", _denial(tool))
    assert asyncio.run(writer.flush()) == 5
    assert pool.transactions == 3


def test_a_full_queue_drops_the_whole_new_group_and_counts_it() -> None:
    """Overflow: the newest submission is refused whole, the queue is untouched, calls never wait."""
    pool = _Pool()
    writer = AuditWriter(pool, max_queue_rows=3)  # type: ignore[arg-type]
    assert writer.submit("mcp_capability_denials", _denial("a"))
    assert writer.submit("mcp_capability_denials", _denial("b"))
    group = [("agent_invocations", _invocation("i1")), ("agent_invocation_samples", _sample("i1"))]
    assert writer.submit_group(group) is False
    assert writer.queued_rows == 2
    assert writer.stats.dropped == 2
    assert writer.stats.dropped_by_table == {"agent_invocations": 1, "agent_invocation_samples": 1}
    assert writer.submit("mcp_capability_denials", _denial("c"))
    assert asyncio.run(writer.flush()) == 3


def test_an_unknown_table_is_a_programming_error() -> None:
    writer = AuditWriter(_Pool())  # type: ignore[arg-type]
    with pytest.raises(KeyError):
        writer.submit("users", ("x",))
    assert writer.queued_rows == 0


def test_a_failed_batch_is_retried_group_by_group_and_only_the_bad_group_is_lost() -> None:
    pool = _Pool(fail_when=lambda sql, params: "poison" in params)
    writer = AuditWriter(pool)  # type: ignore[arg-type]
    writer.submit("mcp_capability_denials", _denial("good-1"))
    writer.submit("mcp_capability_denials", _denial("poison"))
    writer.submit("mcp_capability_denials", _denial("good-2"))

    assert asyncio.run(writer.flush()) == 2
    assert writer.stats.failed == 1
    written_tools = [params[2] for _, params in pool.committed if len(params) == 6]
    assert written_tools == ["good-1", "good-2"]


def test_close_writes_everything_still_queued_and_refuses_later_rows() -> None:
    """Graceful shutdown loses nothing: the lifespan closes the writer before the pool."""
    pool = _Pool()

    async def run() -> AuditWriter:
        writer = AuditWriter(pool, flush_interval_seconds=60)  # type: ignore[arg-type]
        writer.start()
        for tool in "abc":
            writer.submit("mcp_capability_denials", _denial(tool))
        await writer.close()
        assert writer.submit("mcp_capability_denials", _denial("late")) is False
        return writer

    writer = asyncio.run(run())
    assert writer.stats.written == 3
    assert writer.stats.dropped == 1
    assert writer.queued_rows == 0


def test_the_timer_flushes_without_being_asked() -> None:
    pool = _Pool()

    async def run() -> None:
        writer = AuditWriter(pool, flush_interval_seconds=0.01)  # type: ignore[arg-type]
        writer.start()
        writer.submit("mcp_capability_denials", _denial())
        for _ in range(100):
            if writer.stats.written:
                break
            await asyncio.sleep(0.01)
        await writer.close()

    asyncio.run(run())
    assert len(pool.committed) == 1


def test_running_audit_writer_registers_for_the_pool_and_flushes_on_exit() -> None:
    pool = _Pool()
    settings = Settings.model_validate(
        {
            "database_url": "postgresql://u:p@localhost:5432/apiome",
            "internal_secret": "x" * 32,
            "audit_flush_interval_ms": 60_000,
        }
    )

    async def run() -> None:
        async with running_audit_writer(pool, settings) as writer:  # type: ignore[arg-type]
            assert audit_writer_for(pool) is writer
            writer.submit("mcp_capability_denials", _denial())
            assert pool.statements == []
        assert audit_writer_for(pool) is None

    asyncio.run(run())
    assert len(pool.committed) == 1


def test_register_and_unregister() -> None:
    pool = _Pool()
    writer = AuditWriter(pool)  # type: ignore[arg-type]
    register_audit_writer(pool, writer)
    assert audit_writer_for(pool) is writer
    unregister_audit_writer(pool)
    assert audit_writer_for(pool) is None
    assert audit_writer_for(object.__new__(type("NoWeakref", (), {"__slots__": ()}))) is None


@pytest.mark.parametrize("name", list(TABLES))
def test_every_table_template_has_one_placeholder_per_column(name: str) -> None:
    table = TABLES[name]
    assert table.placeholders.count("%s") == len(table.columns.split(","))
    assert table.insert_sql(2).startswith(f"INSERT INTO apiome.{name} (")
