"""In-memory database for the mock's spec-load path (#7208, DBP-1.25).

:class:`FakeSpecPool` quacks like ``psycopg_pool.AsyncConnectionPool`` for what the loaders call
(``pool.connection()``, ``conn.cursor(row_factory=...)``, ``cur.execute`` / ``fetchone`` /
``fetchall``). It answers the access, stamp and resolve statements of
:mod:`apiome_mock.spec_loader` and :mod:`apiome_mock.canonical_loader` and the eleven statements of
apiome-mcp's set-based loader for a published revision with ``operations`` operations (two per
path). Every statement is recorded, and :meth:`FakeSpecPool.get_stats` reports ``pool_available``
like psycopg's pool, so a test can assert no connection is checked out while a spec compiles.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

_NS = UUID("72080000-0000-4000-8000-000000000000")

#: Substrings that identify the loader's statements, most specific first.
_LOADER = (
    ("FROM apiome.class_properties cp", "properties"),
    ("FROM apiome.classes\n", "classes"),
    ("FROM apiome.version_path\n", "paths"),
    ("FROM apiome.path_operation_description pod", "descriptions"),
    ("FROM apiome.shared_path_parameter spp", "parameters"),
    ("FROM apiome.shared_path_request_body rb", "request_bodies"),
    ("FROM apiome.shared_path_response spr", "responses"),
    ("FROM apiome.path_operation po", "operations"),
    ("FROM apiome.version_security_scheme", "security"),
    ("FROM apiome.version_server", "servers"),
    ("FROM apiome.version_component_pins p", "pins"),
)


class FakeSpecPool:
    """A pool over one published, public, mock-enabled revision.

    Args:
        operations: Operations in the spec (even; two per path).
        size: Connections in the pool (``pool_available`` starts here).
        statement_delay: Seconds each statement takes (lets concurrent requests overlap).

    Attributes:
        kinds: The kind of every statement answered, in order (``access``, ``stamp``, ``resolve``,
            ``canonical_resolve`` or a loader kind).
        content_stamp: Bump it to simulate an edit of the revision.
        updated_at: The freshness ``updated_at`` the stamp and resolve statements return.
        checked_out: Connections currently handed out.
        max_checked_out: The most connections handed out at once.
    """

    tenant = "acme"
    project = "payments"
    version = "2.1.0"

    def __init__(self, *, operations: int, size: int = 10, statement_delay: float = 0.0) -> None:
        if operations % 2:
            raise ValueError("operations must be even (two per path)")
        self.operations = operations
        self.size = size
        self.statement_delay = statement_delay
        self.spec_id = uuid5(_NS, f"spec:{operations}")
        self.content_stamp = 7
        self.updated_at = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
        self.kinds: list[str] = []
        self.checked_out = 0
        self.max_checked_out = 0

    # ── pool API ────────────────────────────────────────────────────────────────────────────
    @asynccontextmanager
    async def connection(self) -> Any:
        self.checked_out += 1
        self.max_checked_out = max(self.max_checked_out, self.checked_out)
        try:
            yield _Connection(self)
        finally:
            self.checked_out -= 1

    def get_stats(self) -> dict[str, int]:
        """The ``pool_size`` / ``pool_available`` pair psycopg's pool reports."""
        return {"pool_size": self.size, "pool_available": self.size - self.checked_out}

    def count(self, kind: str) -> int:
        """How many statements of ``kind`` ran."""
        return self.kinds.count(kind)

    # ── statements ──────────────────────────────────────────────────────────────────────────
    async def run(self, sql: str, params: Any) -> list[dict[str, Any]]:
        if self.statement_delay:
            await asyncio.sleep(self.statement_delay)
        kind, rows = self._answer(sql, params)
        self.kinds.append(kind)
        return rows

    def _answer(self, sql: str, params: Any) -> tuple[str, list[dict[str, Any]]]:
        if "AS is_public_spec" in sql:
            return "access", [self._access_row()]
        if "AS version_record_id" in sql:
            return "canonical_resolve", [self._canonical_row()]
        if "AS tenant_slug" in sql:
            return "resolve", [self._resolve_row()]
        if "AS stamp_updated_at" in sql:
            return "stamp", [{"id": self.spec_id, **self._freshness()}]
        for needle, kind in _LOADER:
            if needle in sql:
                assert tuple(params) == (self.spec_id,), f"{kind} must be keyed by the revision id alone"
                return kind, getattr(self, f"_{kind}")()
        raise AssertionError(f"unexpected statement: {sql[:120]}")

    def _freshness(self) -> dict[str, Any]:
        return {"content_stamp": self.content_stamp, "stamp_updated_at": self.updated_at}

    def _access_row(self) -> dict[str, Any]:
        return {
            "mock_enabled": True,
            "published": True,
            "mock_mode": None,
            "source_format": "openapi",
            "is_public_spec": True,
        }

    def _resolve_row(self) -> dict[str, Any]:
        return {
            "id": self.spec_id,
            "updated_at": self.updated_at,
            "tenant_slug": self.tenant,
            "project_slug": self.project,
            "version_label": self.version,
            "project_description": "Payments service",
            "metadata": None,
            "mock_settings": None,
            **self._freshness(),
        }

    def _canonical_row(self) -> dict[str, Any]:
        return {
            "version_record_id": self.spec_id,
            "id": uuid5(_NS, "project"),
            "project_slug": self.project,
            "version_label": self.version,
            "updated_at": self.updated_at,
            "source_format": "asyncapi",
            "protocol": None,
            "format_metadata": None,
            "tool_versions": None,
            "metadata": None,
            "mock_settings": None,
            "tenant_slug": self.tenant,
            **self._freshness(),
        }

    def _id(self, kind: str, n: int) -> UUID:
        return uuid5(_NS, f"{self.operations}:{kind}:{n}")

    def _classes(self) -> list[dict[str, Any]]:
        return [
            {
                "id": self._id("class", n),
                "version_id": self.spec_id,
                "name": f"Model{n:05d}",
                "description": None,
                "schema": {"type": "object"},
                "enabled": True,
            }
            for n in range(max(1, self.operations // 5))
        ]

    def _properties(self) -> list[dict[str, Any]]:
        return [
            {
                "id": self._id("prop", n),
                "class_id": self._id("class", n),
                "property_id": None,
                "name": "name",
                "description": None,
                "data": {"type": "string"},
                "parent_id": None,
                "property_source_id": None,
                "property_source_name": None,
                "property_source_data": None,
            }
            for n in range(max(1, self.operations // 5))
        ]

    def _paths(self) -> list[dict[str, Any]]:
        return [
            {"id": self._id("path", n), "pathname": f"/resources{n:05d}/{{id}}", "summary": None, "description": None}
            for n in range(self.operations // 2)
        ]

    def _operations(self) -> list[dict[str, Any]]:
        return [
            {
                "id": self._id("op", n),
                "version_path_id": self._id("path", n // 2),
                "operation": "GET" if n % 2 == 0 else "DELETE",
            }
            for n in range(self.operations)
        ]

    def _descriptions(self) -> list[dict[str, Any]]:
        return [
            {
                "loader_path_operation_id": self._id("op", n),
                "id": self._id("desc", n),
                "summary": f"Operation {n}",
                "description": None,
                "operation_id": f"op{n}",
                "tags": None,
                "deprecated": None,
                "x_private": None,
                "external_docs": None,
                "metadata": None,
            }
            for n in range(self.operations)
        ]

    def _parameters(self) -> list[dict[str, Any]]:
        return [
            {
                "loader_path_operation_id": self._id("op", n),
                "id": self._id("param", n // 2),
                "name": "id",
                "in_location": "path",
                "summary": None,
                "description": None,
                "data": {"type": "string", "required": True},
            }
            for n in range(self.operations)
        ]

    def _request_bodies(self) -> list[dict[str, Any]]:
        return []

    def _responses(self) -> list[dict[str, Any]]:
        return [
            {
                "loader_path_operation_id": self._id("op", n),
                "id": self._id("response", n),
                "status_code": "200",
                "description": "OK",
                "data": None,
                "class_id": None,
                "class_name": None,
                "inline_schema": {"type": "object", "properties": {"id": {"type": "string"}}},
                "content_types": [],
            }
            for n in range(self.operations)
        ]

    def _security(self) -> list[dict[str, Any]]:
        return []

    def _servers(self) -> list[dict[str, Any]]:
        return []

    def _pins(self) -> list[dict[str, Any]]:
        return []


class _Cursor:
    def __init__(self, pool: FakeSpecPool) -> None:
        self._pool = pool
        self._rows: list[dict[str, Any]] = []

    async def execute(self, sql: str, params: Any = None) -> _Cursor:
        self._rows = await self._pool.run(sql, params)
        return self

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)

    async def __aenter__(self) -> _Cursor:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _Connection:
    def __init__(self, pool: FakeSpecPool) -> None:
        self._pool = pool

    def cursor(self, row_factory: Any = None) -> _Cursor:
        return _Cursor(self._pool)
