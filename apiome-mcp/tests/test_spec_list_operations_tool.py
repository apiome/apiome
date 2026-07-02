from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastmcp.exceptions import NotFoundError
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.scope import Scope
from apiome_mcp.spec_list_operations_tool import (
    build_spec_list_operations_response,
    sorted_operations_from_openapi,
)


def _spec_alpha() -> dict[str, object]:
    """Paths out of order; methods out of order on same path."""
    return {
        "openapi": "3.1.0",
        "paths": {
            "/users": {
                "post": {"operationId": "createUser", "summary": "Create", "tags": ["users"]},
                "get": {"operationId": "listUsers", "summary": "List", "tags": ["users"]},
            },
            "/items/{id}": {
                "get": {"operationId": "getItem", "summary": None, "tags": ["items", "read"]},
                "delete": {"tags": ["items"]},
            },
        },
    }


def _spec_beta() -> dict[str, object]:
    """Another shape: parameters only on path item, trace method, missing operationId."""
    return {
        "openapi": "3.1.0",
        "paths": {
            "/v1/ping": {
                "parameters": [{"name": "x", "in": "header"}],
                "trace": {"summary": "probe"},
                "get": {"operationId": "pingGet"},
            },
        },
    }


def test_sorted_operations_from_openapi_spec_alpha_order() -> None:
    rows = sorted_operations_from_openapi(_spec_alpha())
    assert [r["path"] for r in rows] == ["/items/{id}", "/items/{id}", "/users", "/users"]
    assert [r["method"] for r in rows] == ["delete", "get", "get", "post"]
    assert rows[0] == {
        "path": "/items/{id}",
        "method": "delete",
        "operation_id": None,
        "summary": None,
        "tags": ["items"],
    }
    assert rows[1]["operation_id"] == "getItem"
    assert rows[2]["operation_id"] == "listUsers"
    assert rows[3]["operation_id"] == "createUser"


def test_sorted_operations_from_openapi_spec_beta_skips_parameters() -> None:
    rows = sorted_operations_from_openapi(_spec_beta())
    assert len(rows) == 2
    assert rows[0] == {
        "path": "/v1/ping",
        "method": "get",
        "operation_id": "pingGet",
        "summary": None,
        "tags": [],
    }
    assert rows[1] == {
        "path": "/v1/ping",
        "method": "trace",
        "operation_id": None,
        "summary": "probe",
        "tags": [],
    }


def test_sorted_operations_empty_and_malformed_paths() -> None:
    assert sorted_operations_from_openapi({}) == []
    assert sorted_operations_from_openapi({"paths": None}) == []
    assert sorted_operations_from_openapi({"paths": "/not-a-dict"}) == []
    assert sorted_operations_from_openapi({"paths": {"/x": "bad"}}) == []


def _openapi_row(*, spec_id: UUID | None = None, visibility: str = "public") -> dict[str, object]:
    sid = spec_id or uuid4()
    return {
        "id": sid,
        "tenant_slug": "acme",
        "project_slug": "payments",
        "version_label": "2.1.0",
        "project_description": "Payments service",
        "metadata": None,
        "spec_visibility": visibility,
    }


def test_build_spec_list_operations_success() -> None:
    sid = uuid4()
    row = _openapi_row(spec_id=sid)
    sample_spec = _spec_alpha()

    pool = MagicMock(spec=AsyncConnectionPool)
    describe_cur = MagicMock()
    describe_cur.execute = AsyncMock()
    describe_cur.fetchone = AsyncMock(return_value=row)
    describe_cm = AsyncMock()
    describe_cm.__aenter__.return_value = describe_cur
    describe_cm.__aexit__.return_value = None
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=describe_cm)
    conn_cm = AsyncMock()
    conn_cm.__aenter__.return_value = conn
    conn_cm.__aexit__.return_value = None
    pool.connection = MagicMock(return_value=conn_cm)

    async def fake_fetch(_conn: object, _revision_id: UUID) -> tuple:
        return ([], {}, [], [], [])

    with (
        patch("apiome_mcp.spec_get_openapi_tool.fetch_openapi_generation_inputs_async", side_effect=fake_fetch),
        patch("apiome_mcp.spec_get_openapi_tool.generate_openapi_spec", return_value=sample_spec),
    ):

        async def run() -> list[dict[str, object]]:
            return await build_spec_list_operations_response(pool, spec_id=str(sid))

        out = asyncio.run(run())

    assert len(out) == 4
    assert out[0]["method"] == "delete"


def test_build_spec_list_operations_not_found() -> None:
    pool = MagicMock(spec=AsyncConnectionPool)
    describe_cur = MagicMock()
    describe_cur.execute = AsyncMock()
    describe_cur.fetchone = AsyncMock(return_value=None)
    describe_cm = AsyncMock()
    describe_cm.__aenter__.return_value = describe_cur
    describe_cm.__aexit__.return_value = None
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=describe_cm)
    conn_cm = AsyncMock()
    conn_cm.__aenter__.return_value = conn
    conn_cm.__aexit__.return_value = None
    pool.connection = MagicMock(return_value=conn_cm)

    async def run() -> None:
        await build_spec_list_operations_response(pool, spec_id=str(uuid4()))

    with pytest.raises(NotFoundError, match="Unknown or non-public"):
        asyncio.run(run())


def test_build_spec_list_operations_private_audited() -> None:
    sid = uuid4()
    row = _openapi_row(spec_id=sid, visibility="private")
    auth = McpAuthContext(
        key_id="00000000-0000-4000-8000-000000000099",
        tenant_id=str(uuid4()),
        label="k",
        scope=Scope(),
    )

    pool = MagicMock(spec=AsyncConnectionPool)
    describe_cur = MagicMock()
    describe_cur.execute = AsyncMock()
    describe_cur.fetchone = AsyncMock(return_value=row)
    describe_cm = AsyncMock()
    describe_cm.__aenter__.return_value = describe_cur
    describe_cm.__aexit__.return_value = None
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=describe_cm)
    conn_cm = AsyncMock()
    conn_cm.__aenter__.return_value = conn
    conn_cm.__aexit__.return_value = None
    pool.connection = MagicMock(return_value=conn_cm)

    async def fake_fetch(_conn: object, _revision_id: UUID) -> tuple:
        return ([], {}, [], [], [])

    with (
        patch("apiome_mcp.spec_get_openapi_tool.fetch_openapi_generation_inputs_async", side_effect=fake_fetch),
        patch("apiome_mcp.spec_get_openapi_tool.generate_openapi_spec", return_value=_spec_beta()),
        patch("apiome_mcp.spec_get_openapi_tool.schedule_mcp_private_access_audit") as audit,
    ):

        async def run() -> None:
            await build_spec_list_operations_response(pool, spec_id=str(sid), auth_ctx=auth)

        asyncio.run(run())

    audit.assert_called_once()
    assert audit.call_args.kwargs["tool"] == "spec.list_operations"


def test_build_spec_list_operations_allows_oversize_openapi_payload() -> None:
    """Operation index skips JSON byte cap that would block spec.get_openapi."""
    sid = uuid4()
    row = _openapi_row(spec_id=sid)
    huge = {"openapi": "3.1.0", "paths": {"/x": {"get": {"operationId": "x"}}}, "x": "y" * 500_000}

    pool = MagicMock(spec=AsyncConnectionPool)
    describe_cur = MagicMock()
    describe_cur.execute = AsyncMock()
    describe_cur.fetchone = AsyncMock(return_value=row)
    describe_cm = AsyncMock()
    describe_cm.__aenter__.return_value = describe_cur
    describe_cm.__aexit__.return_value = None
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=describe_cm)
    conn_cm = AsyncMock()
    conn_cm.__aenter__.return_value = conn
    conn_cm.__aexit__.return_value = None
    pool.connection = MagicMock(return_value=conn_cm)

    async def fake_fetch(_conn: object, _revision_id: UUID) -> tuple:
        return ([], {}, [], [], [])

    with (
        patch("apiome_mcp.spec_get_openapi_tool.fetch_openapi_generation_inputs_async", side_effect=fake_fetch),
        patch("apiome_mcp.spec_get_openapi_tool.generate_openapi_spec", return_value=huge),
        patch("apiome_mcp.spec_get_openapi_tool.get_settings") as gs,
    ):
        gs.return_value.openapi_max_json_bytes = 100

        async def run() -> list[dict[str, object]]:
            return await build_spec_list_operations_response(pool, spec_id=str(sid))

        out = asyncio.run(run())

    assert out == [
        {"path": "/x", "method": "get", "operation_id": "x", "summary": None, "tags": []},
    ]


def test_spec_list_operations_tool_registered_on_mcp() -> None:
    from apiome_mcp.server import mcp

    async def load() -> object:
        return await mcp.get_tool("spec.list_operations")

    tool = asyncio.run(load())
    assert tool is not None
    assert tool.name == "spec.list_operations"
